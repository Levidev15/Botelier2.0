"""Email Sender Connection API.

Thin layer around the existing integration infrastructure for Gmail and
Microsoft outbound email sender connections. Platform OAuth credentials
(GMAIL_CLIENT_ID / MICROSOFT_CLIENT_ID env vars) are injected server-side so
account users only click "Connect" — they never enter app credentials.

Routes (all under /api/settings/email-senders):
  GET  /                       — list connected senders for account
  POST /connect/{provider}     — start OAuth flow (returns authorization_url)
  GET  /{id}/info              — refresh + return stored email / status
  DELETE /{id}                 — disconnect a sender

The OAuth callback and code-exchange are handled by the existing shared
/api/integrations/oauth/callback + /api/integrations/oauth/complete endpoints.
After completion the frontend must redirect to /dashboard/settings?tab=email
(not /dashboard/integrations) — the oauth/complete page checks the slug
prefix to decide.
"""

from __future__ import annotations

import os
import secrets
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy.orm import Session

from botelier.api.auth import get_current_user
from botelier.api.integrations import (
    _OAUTH_STATE_NONCE_KEY,
    _assert_account_access,
    _build_authorization_url,
    _oauth_redirect_uri,
)
from botelier.database import get_db
from botelier.models.integration import AccountIntegration, IntegrationStatus, IntegrationType
from botelier.services.ssrf_safe_transport import SSRFSafeTransport

router = APIRouter(prefix="/api/settings/email-senders", tags=["email-senders"])

# ── Constants ────────────────────────────────────────────────────────────────

EMAIL_SENDER_SLUGS = frozenset({"email-sender-gmail", "email-sender-microsoft"})

_PROVIDER_SLUGS: dict[str, str] = {
    "gmail": "email-sender-gmail",
    "microsoft": "email-sender-microsoft",
}

_PROVIDER_ENV: dict[str, tuple[str, str]] = {
    "email-sender-gmail": ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET"),
    "email-sender-microsoft": ("MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"),
}

# ── Helpers ──────────────────────────────────────────────────────────────────


def _assert_settings_access(current_user, account_id: str, db: Session) -> None:
    _assert_account_access(current_user, account_id, db, permission="settings.edit")


def _get_email_sender_types(db: Session) -> dict[UUID, IntegrationType]:
    rows = (
        db.query(IntegrationType)
        .filter(IntegrationType.slug.in_(EMAIL_SENDER_SLUGS))
        .all()
    )
    return {t.id: t for t in rows}


def _conn_to_dict(conn: AccountIntegration, it: Optional[IntegrationType]) -> dict:
    conn_config = conn.get_connection_config() or {}
    return {
        "id": str(conn.id),
        "connection_name": conn.connection_name or "",
        "provider": it.provider if it else "",
        "slug": it.slug if it else "",
        "email": conn_config.get("email") or "",
        "status": conn.status.value if hasattr(conn.status, "value") else str(conn.status),
        "connected_at": conn.connected_at.isoformat() if conn.connected_at else None,
        "last_error": conn.last_error,
    }


async def _fetch_provider_email(slug: str, access_token: str) -> Optional[str]:
    """Fetch the authenticated user's email from the provider's userinfo endpoint."""
    endpoints = {
        "email-sender-gmail": (
            "https://www.googleapis.com/oauth2/v2/userinfo",
            "email",
            None,
        ),
        "email-sender-microsoft": (
            "https://graph.microsoft.com/v1.0/me",
            "mail",
            "userPrincipalName",
        ),
    }
    if slug not in endpoints:
        return None

    url, field, fallback = endpoints[slug]
    try:
        async with httpx.AsyncClient(transport=SSRFSafeTransport(), timeout=10.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
        if resp.status_code == 200:
            data = resp.json()
            return data.get(field) or (data.get(fallback) if fallback else None)
    except Exception as exc:
        logger.warning(f"[email-senders] Could not fetch userinfo from {slug}: {exc}")
    return None


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("")
async def list_email_senders(
    account_id: str = Query(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all connected email sender accounts for the given account."""
    _assert_settings_access(current_user, account_id, db)

    type_map = _get_email_sender_types(db)
    if not type_map:
        return {"connections": []}

    connections = (
        db.query(AccountIntegration)
        .filter(
            AccountIntegration.account_id == UUID(account_id),
            AccountIntegration.integration_type_id.in_(type_map.keys()),
        )
        .order_by(AccountIntegration.created_at)
        .all()
    )

    return {
        "connections": [
            _conn_to_dict(c, type_map.get(c.integration_type_id))
            for c in connections
        ]
    }


@router.post("/connect/{provider}")
async def connect_email_sender(
    provider: str,
    account_id: str = Query(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start OAuth authorization for a Gmail or Microsoft sender connection.

    Returns the provider consent URL. Platform credentials are read from
    environment variables — account users supply no app credentials.
    """
    slug = _PROVIDER_SLUGS.get(provider.lower())
    if not slug:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'")

    _assert_settings_access(current_user, account_id, db)

    client_id_key, client_secret_key = _PROVIDER_ENV[slug]
    client_id = os.environ.get(client_id_key, "").strip()
    client_secret = os.environ.get(client_secret_key, "").strip()

    if not client_id:
        raise HTTPException(
            status_code=503,
            detail=(
                f"{provider.title()} email connection is not yet configured on this "
                "platform. Please contact support."
            ),
        )

    integration_type = db.query(IntegrationType).filter_by(slug=slug).first()
    if not integration_type:
        raise HTTPException(
            status_code=404, detail=f"Integration type '{slug}' not seeded"
        )

    auth_config = integration_type.get_auth_config()
    credentials = {"client_id": client_id, "client_secret": client_secret}

    # Create a CONNECTING integration record; tokens arrive via oauth/complete
    integration = AccountIntegration(
        account_id=UUID(account_id),
        integration_type_id=integration_type.id,
        connection_name=f"{provider.title()} Sender",
        status=IntegrationStatus.CONNECTING,
    )
    integration.set_credentials(credentials)

    nonce = secrets.token_urlsafe(24)
    integration.set_connection_config({_OAUTH_STATE_NONCE_KEY: nonce})

    db.add(integration)
    db.commit()

    state = f"{account_id}:{integration.id}:{nonce}"
    redirect_uri = _oauth_redirect_uri()
    authorization_url = _build_authorization_url(auth_config, credentials, redirect_uri, state)

    logger.info(
        f"[email-senders] Started {provider} OAuth for account {account_id} "
        f"(integration {integration.id})"
    )
    return {"integration_id": str(integration.id), "authorization_url": authorization_url}


@router.get("/{connection_id}/info")
async def refresh_sender_info(
    connection_id: str,
    account_id: str = Query(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch and cache the provider email address for a connected sender.

    Called by the frontend after OAuth completes to surface the authenticated
    email address without requiring a full page reload.
    """
    _assert_settings_access(current_user, account_id, db)

    type_map = _get_email_sender_types(db)
    conn = (
        db.query(AccountIntegration)
        .filter(
            AccountIntegration.id == UUID(connection_id),
            AccountIntegration.account_id == UUID(account_id),
            AccountIntegration.integration_type_id.in_(type_map.keys()),
        )
        .first()
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Email sender connection not found")

    it = type_map.get(conn.integration_type_id)

    # Try to fetch / refresh the email address
    conn_config = conn.get_connection_config() or {}
    if not conn_config.get("email") and conn.status == IntegrationStatus.CONNECTED:
        try:
            access_token = conn.get_access_token()
            if access_token and it:
                email = await _fetch_provider_email(it.slug, access_token)
                if email:
                    conn_config["email"] = email
                    conn.set_connection_config(conn_config)
                    db.commit()
        except Exception as exc:
            logger.warning(f"[email-senders] Could not refresh email for {connection_id}: {exc}")

    return _conn_to_dict(conn, it)


@router.delete("/{connection_id}")
async def disconnect_email_sender(
    connection_id: str,
    account_id: str = Query(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove an email sender connection."""
    _assert_settings_access(current_user, account_id, db)

    type_map = _get_email_sender_types(db)
    conn = (
        db.query(AccountIntegration)
        .filter(
            AccountIntegration.id == UUID(connection_id),
            AccountIntegration.account_id == UUID(account_id),
            AccountIntegration.integration_type_id.in_(type_map.keys()),
        )
        .first()
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Email sender connection not found")

    db.delete(conn)
    db.commit()
    logger.info(f"[email-senders] Disconnected sender {connection_id} for account {account_id}")
    return {"ok": True}
