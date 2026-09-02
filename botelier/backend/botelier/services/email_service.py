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
