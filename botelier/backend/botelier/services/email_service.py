"""Email Service — transactional email delivery via SMTP.

Configuration (environment variables):
    SMTP_HOST        — SMTP server hostname (required to enable sending)
    SMTP_PORT        — SMTP server port (default: 587)
    SMTP_USER        — SMTP login username
    SMTP_PASSWORD    — SMTP login password
    ALERT_EMAIL_FROM — From address for alert emails (defaults to SMTP_USER)

When SMTP_HOST is not set the service logs a warning and silently skips
all sends. This prevents SMTP misconfiguration from crashing the platform
while making misconfiguration clearly visible in logs.
"""

import os
import smtplib
import socket
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

from loguru import logger


def _smtp_config() -> Optional[dict]:
    """Return SMTP config dict, or None if SMTP is not configured."""
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ.get("SMTP_USER", "").strip(),
        "password": os.environ.get("SMTP_PASSWORD", "").strip(),
        "from_addr": (
            os.environ.get("ALERT_EMAIL_FROM", "").strip()
            or os.environ.get("SMTP_USER", "").strip()
            or f"alerts@{host}"
        ),
    }


def send_email(
    to_addresses: List[str],
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
) -> bool:
    """Send an email to one or more recipients.

    Args:
        to_addresses: List of recipient email addresses.
        subject:      Email subject line.
        body_text:    Plain-text body (always required as fallback).
        body_html:    Optional HTML body. When provided the message is sent
                      as multipart/alternative so clients can render either.

    Returns:
        True if the message was accepted by the SMTP server, False otherwise.
        Never raises — failures are logged and swallowed so a transient email
        outage cannot propagate into business-critical write paths.
    """
    if not to_addresses:
        logger.warning("send_email: called with empty recipient list, skipping")
        return False

    cfg = _smtp_config()
    if cfg is None:
        logger.warning(
            "send_email: SMTP_HOST not configured — skipping email to %s (subject: %s)",
            to_addresses,
            subject,
        )
        return False

    try:
        if body_html:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(body_text, "plain", "utf-8"))
            msg.attach(MIMEText(body_html, "html", "utf-8"))
        else:
            msg = MIMEText(body_text, "plain", "utf-8")

        msg["Subject"] = subject
        msg["From"] = cfg["from_addr"]
        msg["To"] = ", ".join(to_addresses)

        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as smtp:
            smtp.ehlo()
            try:
                smtp.starttls()
                smtp.ehlo()
            except smtplib.SMTPException:
                pass
            if cfg["user"] and cfg["password"]:
                smtp.login(cfg["user"], cfg["password"])
            smtp.sendmail(cfg["from_addr"], to_addresses, msg.as_string())

        logger.info(
            "send_email: delivered '%s' to %d recipient(s)", subject, len(to_addresses)
        )
        return True

    except (smtplib.SMTPException, OSError, socket.timeout) as exc:
        logger.error(
            "send_email: failed to deliver '%s' to %s — %s: %s",
            subject,
            to_addresses,
            type(exc).__name__,
            exc,
        )
        return False
    except Exception as exc:
        logger.exception(
            "send_email: unexpected error delivering '%s' to %s — %s",
            subject,
            to_addresses,
            exc,
        )
        return False
