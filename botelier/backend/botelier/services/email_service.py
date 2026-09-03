"""Email Service — transactional email delivery via SendGrid.

Configuration (environment variables):
    SENDGRID_API_KEY        — SendGrid API key (required to enable sending)
    EMAIL_FROM_DEFAULT      — Platform sender email address (e.g. hello@botelier.io)
    EMAIL_FROM_NAME_DEFAULT — Platform sender display name (e.g. Botelier)

When SENDGRID_API_KEY is not set the service logs a warning and silently skips
all sends. This prevents misconfiguration from crashing the platform while
making misconfiguration clearly visible in logs.

The send_email() signature is backward-compatible with the previous SMTP
version so callers (billing_alert_service, etc.) require no changes.
"""

import os
from typing import List, Optional

from loguru import logger

try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Content, From, Mail, To

    _SENDGRID_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SENDGRID_AVAILABLE = False


import base64
import email as _email_module
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

import requests as _requests

# Module-level reference to the SQLAlchemy engine — exposed at module scope so
# tests can patch it via 'botelier.services.email_service._db_engine' without
# a real Postgres connection being required at import time.
try:
    from botelier.database import engine as _db_engine
except Exception:  # pragma: no cover — only fails if DB module is broken
    _db_engine = None  # type: ignore[assignment]


def _sendgrid_api_key() -> Optional[str]:
    """Return the SendGrid API key, or None if not configured."""
    key = os.environ.get("SENDGRID_API_KEY", "").strip()
    return key if key else None


def _platform_sender() -> tuple[str, str]:
    """Return (from_email, from_name) for the platform default sender."""
    email = os.environ.get("EMAIL_FROM_DEFAULT", "").strip()
    name = os.environ.get("EMAIL_FROM_NAME_DEFAULT", "Botelier").strip()
    return email, name


def send_email(
    to_addresses: List[str],
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
) -> bool:
    """Send an email to one or more recipients via SendGrid.

    Args:
        to_addresses: List of recipient email addresses.
        subject:      Email subject line.
        body_text:    Plain-text body (always required as fallback).
        body_html:    Optional HTML body. When provided, a multipart/alternative
                      message is sent so clients can render either.
        from_email:   Sender email address. Falls back to EMAIL_FROM_DEFAULT.
        from_name:    Sender display name. Falls back to EMAIL_FROM_NAME_DEFAULT.

    Returns:
        True if SendGrid accepted the message (2xx response), False otherwise.
        Never raises — failures are logged and swallowed so a transient email
        outage cannot propagate into business-critical write paths.
    """
    if not to_addresses:
        logger.warning("send_email: called with empty recipient list, skipping")
        return False

    api_key = _sendgrid_api_key()
    if api_key is None:
        logger.warning(
            "send_email: SENDGRID_API_KEY not configured — skipping email to %s (subject: %s)",
            to_addresses,
            subject,
        )
        return False

    platform_email, platform_name = _platform_sender()
    effective_from_email = from_email or platform_email
    effective_from_name = from_name or platform_name

    if not effective_from_email:
        logger.warning(
            "send_email: no sender email configured — set EMAIL_FROM_DEFAULT. "
            "Skipping email to %s (subject: %s)",
            to_addresses,
            subject,
        )
        return False

    if not _SENDGRID_AVAILABLE:
        logger.error(
            "send_email: sendgrid package not installed — cannot deliver '%s' to %s",
            subject,
            to_addresses,
        )
        return False

    try:
        sg = SendGridAPIClient(api_key=api_key)

        from_field = From(email=effective_from_email, name=effective_from_name or None)

        # Build recipient list
        to_fields = [To(email=addr) for addr in to_addresses]

        message = Mail(
            from_email=from_field,
            subject=subject,
        )
        for to_field in to_fields:
            message.add_to(to_field)

        message.add_content(Content("text/plain", body_text))
        if body_html:
            message.add_content(Content("text/html", body_html))

        response = sg.send(message)
        status = response.status_code

        if 200 <= status < 300:
            logger.info(
                "send_email: delivered '%s' to %d recipient(s) via SendGrid (status %d)",
                subject,
                len(to_addresses),
                status,
            )
            return True
        else:
            logger.error(
                "send_email: SendGrid returned unexpected status %d for '%s' to %s",
                status,
                subject,
                to_addresses,
            )
            return False

    except Exception as exc:
        logger.error(
            "send_email: failed to deliver '%s' to %s — %s: %s",
            subject,
            to_addresses,
            type(exc).__name__,
            exc,
        )
        return False


# ── Connected email sender paths ─────────────────────────────────────────────


class EmailSenderAuthError(ValueError):
    """Raised when the provider rejects the access token (HTTP 401/403).

    Signals that the stored token has been revoked or expired at the provider
    and the user must reconnect the sender in Settings > Email.  It is a
    subclass of ValueError so the function_mapper handler's existing
    ``except ValueError`` branch surfaces it as a reconnect prompt.
    """


def _read_email_sender_fresh(connection_id):
    """Read an email sender ``AccountIntegration`` in its own short-lived session.

    Always uses a fresh ``SessionLocal()`` (never the caller's ORM session) so
    READ-COMMITTED isolation surfaces another worker's committed token rotation.
    ``integration_type`` is eagerly loaded so the detached object is safe to
    inspect after the session closes.

    Returns ``None`` when the row no longer exists.
    """
    from botelier.database import SessionLocal
    from botelier.models.integration import AccountIntegration
    from sqlalchemy.orm import joinedload

    db = SessionLocal()
    try:
        return (
            db.query(AccountIntegration)
            .options(joinedload(AccountIntegration.integration_type))
            .filter(AccountIntegration.id == connection_id)
            .first()
        )
    finally:
        db.close()


def _do_http_refresh_email_sender(connection, db) -> str:
    """Perform the HTTP refresh-token grant and persist the rotated credentials.

    This is the **bare** grant — it does NOT hold an advisory lock.  Callers
    must serialize via :func:`_refresh_email_sender_token_sync`.

    Returns the new access token on success.
    Raises ``ValueError`` with a reconnect message on terminal failures.
    Raises ``ValueError`` with a transient message on network errors (status
    is left unchanged so the next delivery attempt can retry the grant).
    """
    from datetime import datetime, timedelta

    from botelier.models.integration import IntegrationStatus
    from botelier.services.integration_runtime.adapters.oauth2 import resolve_token_endpoint

    refresh_token = connection.get_refresh_token()
    if not refresh_token:
        connection.status = IntegrationStatus.TOKEN_EXPIRED
        connection.last_error = "No refresh token; reconnect required"
        db.add(connection)
        db.commit()
        raise ValueError(
            "Your email sender needs to be reconnected — "
            "please go to Settings > Email and reconnect your account."
        )

    auth_config = connection.integration_type.get_auth_config()
    credentials = connection.get_credentials()
    token_url = resolve_token_endpoint(auth_config)
    client_id = credentials.get("client_id")
    client_secret = credentials.get("client_secret")

    form: dict = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    if client_id:
        form["client_id"] = client_id
    scope = credentials.get("scope") or auth_config.get("scope")
    if scope:
        form["scope"] = scope
    basic_auth = (client_id, client_secret) if (client_id and client_secret) else None

    try:
        resp = _requests.post(
            token_url,
            data=form,
            auth=basic_auth,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            timeout=20,
        )
    except Exception as exc:
        # Transient — leave status/refresh_token unchanged so the next
        # delivery attempt can retry the grant.
        logger.warning(
            "email sender: refresh network error for %s: %s", connection.id, exc
        )
        raise ValueError(
            "Could not refresh your email sender token (network error). "
            "Please try again shortly."
        )

    if resp.status_code == 200:
        data = resp.json()
        access_token = data.get("access_token")
        if not access_token:
            connection.status = IntegrationStatus.TOKEN_EXPIRED
            connection.last_error = "Token refresh response missing access_token"
            db.add(connection)
            db.commit()
            raise ValueError(
                "Your email sender needs to be reconnected — "
                "please go to Settings > Email and reconnect your account."
            )
        connection.set_access_token(access_token)
        # Rotate the refresh token only when the provider sends a new one
        # (many providers keep the original valid indefinitely).
        if data.get("refresh_token"):
            connection.set_refresh_token(data["refresh_token"])
        expires_in = 3600
        try:
            expires_in = int(data.get("expires_in") or 3600)
        except (TypeError, ValueError):
            pass
        connection.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        connection.status = IntegrationStatus.CONNECTED
        connection.last_error = None
        db.add(connection)
        db.commit()
        logger.info(
            "email sender: refreshed access token for integration %s", connection.id
        )
        return access_token

    # Distinguish definitive credential rejection from transient service errors.
    # 400/401/403 = the provider has definitively rejected the grant (invalid,
    # expired, or revoked refresh token).  Mark TOKEN_EXPIRED so subsequent
    # delivery attempts fail closed rather than spending the refresh token again.
    # 429/5xx = rate-limit or token-endpoint outage — transient; leave status
    # unchanged so the next delivery attempt can retry after the outage clears.
    if resp.status_code in (400, 401, 403):
        connection.status = IntegrationStatus.TOKEN_EXPIRED
        connection.last_error = f"Token refresh rejected: {resp.status_code}"
        db.add(connection)
        db.commit()
        raise ValueError(
            "Your email sender needs to be reconnected — "
            "please go to Settings > Email and reconnect your account."
        )

    # Transient token-endpoint error (429 rate-limit, 5xx outage etc.) — do not
    # change status so the next delivery attempt can retry the grant.
    logger.warning(
        "email sender: transient token endpoint error %s for %s",
        resp.status_code,
        connection.id,
    )
    raise ValueError(
        f"Could not refresh your email sender token (server error {resp.status_code}). "
        "Please try again shortly."
    )


def _refresh_email_sender_token_sync(connection, db) -> str:
    """Refresh an email sender's access token, serialized across all workers.

    Implements the same holder/waiter advisory-lock pattern as
    ``IntegrationClient._refresh_token_with_lock`` but **synchronously**
    (``time.sleep`` + ``requests``) since this runs in a thread-pool context
    (``run_in_executor``).

    **Holder** — the worker that wins ``pg_try_advisory_lock`` re-reads the row
    (another worker may have refreshed while it contended) and, if still stale,
    calls :func:`_do_http_refresh_email_sender` and commits the rotated tokens.

    **Waiters** — every other worker releases its raw connection immediately and
    polls the row with short sleeps until the holder's commit is visible or a
    terminal status (``TOKEN_EXPIRED``) is observed, without holding a DB
    connection while the provider HTTP call is in flight.

    The lock is held on a **dedicated raw connection**, never on the ORM
    session, so the advisory lock outlives the session's commit.

    Raises ``ValueError`` (with a reconnect message) on terminal failures.
    Never falls through to an unlocked refresh.
    """
    import time as _time

    from botelier.models.integration import IntegrationStatus
    from botelier.services.integration_runtime.locks import (
        _LOCK_ACQUIRE_BACKOFF_S,
        _LOCK_ACQUIRE_RETRIES,
        _REFRESH_POLL_INTERVAL_S,
        _REFRESH_WAIT_TIMEOUT_S,
        _advisory_lock_key,
        _safe_close,
    )
    from sqlalchemy import text as _sql_text

    lock_key = _advisory_lock_key(connection.id)

    # ── Acquire the advisory lock on a dedicated raw connection ──────────────
    # Both engine.connect() and pg_try_advisory_lock are retried as a unit.
    # On persistent infrastructure failure we raise rather than fall through to
    # an unlocked refresh — concurrent double-refresh can spend a rotating
    # refresh token and permanently disable the mailbox connection.
    raw_conn = None
    acquired = None
    last_exc: Exception | None = None

    for attempt in range(_LOCK_ACQUIRE_RETRIES + 1):
        if attempt > 0:
            _time.sleep(_LOCK_ACQUIRE_BACKOFF_S * (2 ** (attempt - 1)))
        try:
            raw_conn = _db_engine.connect()
        except Exception as exc:
            last_exc = exc
            raw_conn = None
            continue
        try:
            acquired = raw_conn.execute(
                _sql_text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key}
            ).scalar()
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            _safe_close(raw_conn)
            raw_conn = None
            acquired = None

    if last_exc is not None:
        raise ValueError(
            "Could not acquire token refresh lock (database error). "
            "Please try again shortly."
        )

    # ── Holder path ───────────────────────────────────────────────────────────
    if acquired:
        try:
            # Re-read the row fresh before deciding to skip or refresh.
            # Mirrors IntegrationClient._sync_cached_integration: sync the
            # fresh token fields into the caller's ORM row in BOTH branches —
            # when skipping (another worker already refreshed) AND when still
            # stale — so a reconnect that replaced the refresh_token between
            # the original DB lookup and lock acquisition is always honoured.
            fresh = _read_email_sender_fresh(connection.id)
            if fresh is not None:
                connection.access_token_encrypted = fresh.access_token_encrypted
                connection.refresh_token_encrypted = fresh.refresh_token_encrypted
                connection.token_expires_at = fresh.token_expires_at
                connection.status = fresh.status

                if (
                    fresh.status == IntegrationStatus.CONNECTED
                    and not fresh.is_token_expired()
                ):
                    logger.info(
                        "email sender: token already refreshed by another worker for %s",
                        connection.id,
                    )
                    return fresh.get_access_token()

                if fresh.status == IntegrationStatus.TOKEN_EXPIRED:
                    # Another worker already attempted and terminally failed the
                    # refresh (invalid/revoked grant) — raise immediately without
                    # spending the refresh token a second time.
                    logger.warning(
                        "email sender: fresh row shows TOKEN_EXPIRED for %s; "
                        "raising without HTTP refresh",
                        connection.id,
                    )
                    raise ValueError(
                        "Your email sender needs to be reconnected — "
                        "please go to Settings > Email and reconnect your account."
                    )
            # Still stale (CONNECTED + expired, or row missing) — perform the
            # HTTP grant on the synchronised row.
            return _do_http_refresh_email_sender(connection, db)
        finally:
            try:
                raw_conn.execute(
                    _sql_text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key}
                )
            except Exception as exc:
                # A stranded lock blocks ALL future refreshes for this
                # connection until the pooled connection recycles — hard-drop it.
                logger.error(
                    "email sender: advisory-unlock failed for %s: %s; invalidating",
                    connection.id,
                    exc,
                )
                raw_conn.invalidate()
            finally:
                _safe_close(raw_conn)

    # ── Waiter path ───────────────────────────────────────────────────────────
    # Release the raw connection immediately so the holder is not competing
    # for connection-pool slots while its provider HTTP call is in flight.
    _safe_close(raw_conn)

    deadline = _time.monotonic() + _REFRESH_WAIT_TIMEOUT_S
    while _time.monotonic() < deadline:
        _time.sleep(_REFRESH_POLL_INTERVAL_S)
        fresh = _read_email_sender_fresh(connection.id)
        if fresh is None:
            continue
        if fresh.status == IntegrationStatus.CONNECTED and not fresh.is_token_expired():
            logger.info(
                "email sender: waiter observed successful refresh for %s", connection.id
            )
            return fresh.get_access_token()
        if fresh.status == IntegrationStatus.TOKEN_EXPIRED:
            raise ValueError(
                "Your email sender needs to be reconnected — "
                "please go to Settings > Email and reconnect your account."
            )

    raise ValueError(
        "Could not refresh your email sender token (timed out). "
        "Please try again shortly."
    )


def _build_rfc2822(
    to_address: str,
    subject: str,
    body_text: str,
    body_html: Optional[str],
    from_email: str,
    from_name: Optional[str],
) -> str:
    """Build a base64url-encoded RFC 2822 message (for the Gmail API)."""
    if body_html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))
    else:
        msg = MIMEText(body_text, "plain", "utf-8")

    msg["To"] = to_address
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name or "", from_email))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return raw


def send_email_via_gmail(
    to_addresses: List[str],
    subject: str,
    body_text: str,
    access_token: str,
    from_email: str,
    from_name: Optional[str] = None,
    body_html: Optional[str] = None,
    timeout: int = 30,
) -> bool:
    """Send email(s) through the Gmail API using a connected OAuth access token.

    Called synchronously from a thread pool so it can be awaited via
    asyncio.run_in_executor without blocking the voice event loop.
    """
    if not to_addresses:
        logger.warning("send_email_via_gmail: empty recipient list, skipping")
        return False

    url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    all_ok = True
    for addr in to_addresses:
        raw = _build_rfc2822(addr, subject, body_text, body_html, from_email, from_name)
        try:
            resp = _requests.post(url, json={"raw": raw}, headers=headers, timeout=timeout)
            if resp.status_code in (200, 202):
                logger.info(
                    "send_email_via_gmail: delivered '%s' to %s (status %s)",
                    subject,
                    addr,
                    resp.status_code,
                )
            elif resp.status_code in (401, 403):
                # Provider rejected the token — it has been revoked or expired
                # at the Google side. Raise so send_email_via_connection can
                # surface a targeted reconnect message (not a generic failure).
                raise EmailSenderAuthError(
                    f"Gmail rejected the access token ({resp.status_code}). "
                    "Please reconnect your email sender in Settings > Email."
                )
            else:
                logger.error(
                    "send_email_via_gmail: Gmail API returned %s for '%s' to %s: %s",
                    resp.status_code,
                    subject,
                    addr,
                    resp.text[:200],
                )
                all_ok = False
        except EmailSenderAuthError:
            raise
        except Exception as exc:
            logger.error(
                "send_email_via_gmail: failed to deliver '%s' to %s — %s",
                subject,
                addr,
                exc,
            )
            all_ok = False

    return all_ok


def send_email_via_microsoft(
    to_addresses: List[str],
    subject: str,
    body_text: str,
    access_token: str,
    body_html: Optional[str] = None,
    timeout: int = 30,
) -> bool:
    """Send email(s) through Microsoft Graph using a connected OAuth access token.

    Microsoft Graph /me/sendMail delivers from the authenticated mailbox so
    no explicit From address is needed.
    """
    if not to_addresses:
        logger.warning("send_email_via_microsoft: empty recipient list, skipping")
        return False

    url = "https://graph.microsoft.com/v1.0/me/sendMail"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    all_ok = True
    for addr in to_addresses:
        body_type = "HTML" if body_html else "Text"
        body_content = body_html if body_html else body_text
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": body_type, "content": body_content},
                "toRecipients": [{"emailAddress": {"address": addr}}],
            },
            "saveToSentItems": "false",
        }
        try:
            resp = _requests.post(url, json=payload, headers=headers, timeout=timeout)
            # 202 Accepted is the normal success response from Graph
            if resp.status_code in (200, 202):
                logger.info(
                    "send_email_via_microsoft: delivered '%s' to %s (status %s)",
                    subject,
                    addr,
                    resp.status_code,
                )
            elif resp.status_code in (401, 403):
                # Provider rejected the token — it has been revoked or expired
                # at the Microsoft side. Raise so send_email_via_connection can
                # surface a targeted reconnect message (not a generic failure).
                raise EmailSenderAuthError(
                    f"Microsoft Graph rejected the access token ({resp.status_code}). "
                    "Please reconnect your email sender in Settings > Email."
                )
            else:
                logger.error(
                    "send_email_via_microsoft: Graph API returned %s for '%s' to %s: %s",
                    resp.status_code,
                    subject,
                    addr,
                    resp.text[:200],
                )
                all_ok = False
        except EmailSenderAuthError:
            raise
        except Exception as exc:
            logger.error(
                "send_email_via_microsoft: failed to deliver '%s' to %s — %s",
                subject,
                addr,
                exc,
            )
            all_ok = False

    return all_ok


def send_email_via_connection(
    connection,  # AccountIntegration
    to_addresses: List[str],
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    db=None,  # SQLAlchemy Session — required for proactive token refresh
) -> bool:
    """Dispatch an email through a connected Gmail or Microsoft account.

    ``connection`` is an ``AccountIntegration`` row with ``integration_type``
    eagerly loaded.  The function handles three token lifecycle scenarios:

    1. **Token still valid** — sends immediately.
    2. **Token expired** (``is_token_expired()`` → True, ``db`` provided) —
       attempts a synchronous refresh-token grant and sends with the fresh
       access token.  Persists the rotated tokens to ``db``.
    3. **Provider rejects token** (HTTP 401/403) — the send functions raise
       ``EmailSenderAuthError``, which this function converts to a ``ValueError``
       with a reconnect prompt so the LLM can surface it to the caller.

    Returns True when all recipients received the message.
    Raises ValueError (including ``EmailSenderAuthError`` subclass) for
    auth/config failures the caller should surface as an LLM tool result.
    """
    try:
        slug = connection.integration_type.slug
    except AttributeError:
        slug = ""

    from botelier.models.integration import IntegrationStatus

    if connection.status != IntegrationStatus.CONNECTED:
        # TOKEN_EXPIRED (and all other non-CONNECTED statuses) fail closed:
        # the stored refresh token may have already been consumed or revoked.
        # The user must re-connect the sender in Settings > Email.
        raise ValueError(
            "Your email sender needs to be reconnected — "
            "please go to Settings > Email and reconnect your account."
        )

    # ── Proactive token refresh ────────────────────────────────────────────────
    # If the stored access token is past its recorded expiry time, attempt a
    # refresh-token grant before the send so we do not burn a delivery attempt
    # on a stale bearer.  The refresh requires a DB session to persist rotated
    # credentials; skip if db is unavailable and let the send surface the 401.
    access_token = connection.get_access_token()

    if connection.is_token_expired() and db is not None:
        logger.info(
            "email sender: access token expired for integration %s — refreshing",
            connection.id,
        )
        access_token = _refresh_email_sender_token_sync(connection, db)
        # _refresh_email_sender_token_sync raises ValueError on failure;
        # if we get here the token is fresh.

    if not access_token:
        raise ValueError(
            "The selected email sender is disconnected — please reconnect it in Settings > Email."
        )

    # ── Dispatch by provider ───────────────────────────────────────────────────
    if slug == "email-sender-gmail":
        conn_config = connection.get_connection_config() or {}
        from_email = conn_config.get("email", "")
        return send_email_via_gmail(
            to_addresses=to_addresses,
            subject=subject,
            body_text=body_text,
            access_token=access_token,
            from_email=from_email,
            body_html=body_html,
        )

    if slug == "email-sender-microsoft":
        return send_email_via_microsoft(
            to_addresses=to_addresses,
            subject=subject,
            body_text=body_text,
            access_token=access_token,
            body_html=body_html,
        )

    raise ValueError(
        f"Unsupported email sender type '{slug}'. "
        "Supported types: Gmail (email-sender-gmail), Microsoft (email-sender-microsoft)."
    )
