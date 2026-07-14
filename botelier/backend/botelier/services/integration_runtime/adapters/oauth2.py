"""3-legged OAuth2 (authorization_code) adapter (Task #331).

This adapter serves integrations whose type declares
``auth_type = "oauth2_authorization_code"`` — providers where a human grants
access through a browser consent screen and the provider returns an
authorization code that is exchanged for an access token + a long-lived refresh
token.

The one-time browser dance (authorize URL + code→token exchange) lives at the
API edge (``api/integrations.py``); this adapter owns the *runtime* half:

  • ``needs_token`` → True, so the shared runtime keeps the bearer fresh before
    every data request (reusing the cross-worker advisory-lock refresh path).
  • ``refresh_credentials`` performs the ``refresh_token`` grant and persists the
    rotated tokens with the same encrypted storage every other adapter uses.

Auth headers/base-URL resolution use the generic base-class behavior (static
Bearer + ``auth_config["base_url"]``), so a provider needs no custom code beyond
declaring its ``authorization_endpoint`` / ``token_endpoint`` in the seed's
``auth_config``.

Transient-vs-terminal contract (identical to Opera/GuestCentric): a network
blip keeps the integration CONNECTED so the NEXT request retries the refresh; a
definitive provider rejection (non-200) or a missing refresh token is terminal
(TOKEN_EXPIRED — the user must re-consent). Never persist ERROR here, which
would trip the status gate and permanently disable auto-refresh.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
from loguru import logger

from botelier.models.integration import IntegrationStatus
from botelier.services.ssrf_safe_transport import SSRFSafeTransport

from .base import BaseIntegrationAdapter, RefreshContext


def resolve_token_endpoint(auth_config: dict) -> str:
    """Full token-endpoint URL from the seed auth_config.

    Accepts either an absolute ``token_endpoint`` or a ``token_endpoint_path``
    joined onto ``base_url``.
    """
    token_endpoint = (auth_config.get("token_endpoint") or "").strip()
    if token_endpoint.startswith("http://") or token_endpoint.startswith("https://"):
        return token_endpoint
    base_url = (auth_config.get("base_url", "") or "").rstrip("/")
    path = auth_config.get("token_endpoint_path") or token_endpoint or "/oauth/token"
    if not path.startswith("/"):
        path = "/" + path
    return f"{base_url}{path}"


class OAuth2AuthorizationCodeAdapter(BaseIntegrationAdapter):
    """Runtime behavior for 3-legged OAuth2 connections."""

    slug = None  # resolved by auth_type, not by a vendor slug

    def needs_token(self, credentials: dict) -> bool:
        # Every data request must ride a fresh bearer obtained via the code
        # exchange / refresh grant.
        return True

    def resolve_base_url(self, auth_config: dict, credentials: dict) -> str:
        return (auth_config.get("base_url", "") or "").rstrip("/")

    async def refresh_credentials(self, ctx: RefreshContext) -> bool:
        return await self.refresh_oauth(ctx)

    async def refresh_oauth(self, ctx: RefreshContext) -> bool:
        integration = ctx.integration
        credentials = ctx.credentials or {}
        auth_config = ctx.auth_config or {}

        db = ctx.get_db_session()
        try:
            refresh_token = integration.get_refresh_token()
            if not refresh_token:
                # authorization_code without a refresh token cannot be renewed
                # server-side — the user must re-consent. Terminal.
                integration.status = IntegrationStatus.TOKEN_EXPIRED
                integration.last_error = (
                    "No refresh token available; reconnect required"
                )
                db.add(integration)
                db.commit()
                logger.warning(
                    f"OAuth2 refresh skipped for integration {integration.id}: "
                    "no refresh token (re-consent required)"
                )
                return False

            token_url = resolve_token_endpoint(auth_config)
            client_id = credentials.get("client_id")
            client_secret = credentials.get("client_secret")

            form = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
            if client_id:
                form["client_id"] = client_id
            scope = credentials.get("scope") or auth_config.get("scope")
            if scope:
                form["scope"] = scope

            # Confidential clients authenticate with HTTP Basic; public clients
            # send only client_id in the body.
            basic_auth = (client_id, client_secret) if client_secret else None

            try:
                async with httpx.AsyncClient(transport=SSRFSafeTransport()) as client:
                    response = await client.post(
                        token_url,
                        data=form,
                        auth=basic_auth,
                        headers={
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Accept": "application/json",
                        },
                        timeout=30.0,
                    )
            except Exception as exc:
                # Transient: keep CONNECTED so the next request retries.
                logger.error(f"OAuth2 refresh network error: {exc}")
                integration.last_error = str(exc)[:500]
                db.add(integration)
                db.commit()
                return False

            if response.status_code == 200:
                token_data = response.json()
                access_token = token_data.get("access_token")
                if not access_token:
                    integration.status = IntegrationStatus.TOKEN_EXPIRED
                    integration.last_error = "Token response missing access_token"
                    db.add(integration)
                    db.commit()
                    return False

                integration.set_access_token(access_token)
                # Refresh-token rotation: only overwrite when the provider
                # returns a new one (many keep the original valid).
                if token_data.get("refresh_token"):
                    integration.set_refresh_token(token_data["refresh_token"])
                expires_in = token_data.get("expires_in") or 3600
                try:
                    expires_in = int(expires_in)
                except (TypeError, ValueError):
                    expires_in = 3600
                integration.token_expires_at = datetime.utcnow() + timedelta(
                    seconds=expires_in
                )
                integration.status = IntegrationStatus.CONNECTED
                integration.last_error = None
                db.add(integration)
                db.commit()
                logger.info(
                    f"Refreshed OAuth2 authorization_code token for integration "
                    f"{integration.id}"
                )
                return True

            # Definitive provider rejection — terminal.
            logger.error(
                f"OAuth2 refresh rejected: {response.status_code} - {response.text[:300]}"
            )
            integration.status = IntegrationStatus.TOKEN_EXPIRED
            integration.last_error = f"Token refresh failed: {response.status_code}"
            db.add(integration)
            db.commit()
            return False
        finally:
            if ctx.owns_session:
                db.close()
