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
            else:
                logger.error(
                    "send_email_via_gmail: Gmail API returned %s for '%s' to %s: %s",
                    resp.status_code,
                    subject,
                    addr,
                    resp.text[:200],
                )
                all_ok = False
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
            else:
                logger.error(
                    "send_email_via_microsoft: Graph API returned %s for '%s' to %s: %s",
                    resp.status_code,
                    subject,
                    addr,
                    resp.text[:200],
                )
                all_ok = False
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
) -> bool:
    """Dispatch an email through a connected Gmail or Microsoft account.

    `connection` is an AccountIntegration row with integration_type eagerly
    loaded (or at least its slug accessible as connection.integration_type.slug).

    Returns True if all recipients received the message.
    Raises ValueError when the connection is not a recognised email sender type
    or the access token is missing — the caller is expected to surface the error
    to the LLM as a tool result.
    """
    try:
        slug = connection.integration_type.slug
    except AttributeError:
        slug = ""

    access_token = connection.get_access_token()
    if not access_token:
        raise ValueError(
            "The selected email sender is disconnected — please reconnect it in Settings > Email."
        )

    from botelier.models.integration import IntegrationStatus

    if connection.status != IntegrationStatus.CONNECTED:
        raise ValueError(
            f"The selected email sender is not connected (status: {connection.status}). "
            "Please reconnect it in Settings > Email."
        )

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
