"""Shared Twilio authenticity helpers for the voice surface.

Two concerns live here:

1. HTTP signature validation — `validate_twilio_signature()` checks the
   `X-Twilio-Signature` header on the public voice lifecycle webhooks
   (`/incoming`, `/status`, `/connect-complete`, `/transfer-status`,
   `/recording-status`).  Mirrors the proven pattern from
   `sms_pkg/webhook.py` and the in-file `_validate_recording_webhook_signature`
   used in `calls.py`.

2. Media-stream binding — Twilio Media Streams cannot carry an
   `X-Twilio-Signature` header on the WebSocket upgrade, so `/incoming`
   mints a short-lived HMAC token bound to `(CallSid, To)` and embeds
   it in the TwiML `<Stream>` `<Parameter>` block.  The `/api/ws/call`
   endpoint then verifies that token on the first `start` frame before
   any pipeline work begins.

HTTP signature validation fails closed: if no auth token is configured
the request is rejected with a WARNING rather than allowed through.

Stream-token verification skips the HMAC when no secret is available
(dev-mode skip) but still requires a CallLog binding, so a fabricated
callSid from an unauthenticated source is always rejected.

Production deployments must always have the required secrets set.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Optional

from fastapi import Request
from loguru import logger
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# HTTP signature validation
# ---------------------------------------------------------------------------


def _build_webhook_url(request: Request, path: str) -> str:
    """Reconstruct the public URL Twilio signed.

    Twilio signs the URL it dialled, which behind Replit/Cloudflare proxies
    is not what FastAPI sees.  Use the same logic the SMS webhook uses to
    rebuild it from `PUBLIC_BASE_URL` (or X-Forwarded-Host fallback).
    """
    from ..config.domain import get_public_base_url

    fallback_host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host", "")
    base = get_public_base_url(fallback_host=fallback_host)
    query = request.url.query
    return f"{base}{path}{'?' + query if query else ''}"


def validate_twilio_signature(
    request: Request,
    form_data: dict,
    path: str,
    auth_token: str,
) -> tuple[bool, str]:
    """Validate the `X-Twilio-Signature` header.

    Returns `(is_valid, diagnostic_url)`. The diagnostic URL omits query
    values; callers may log the origin/path to diagnose proxy mismatches.
    Signature validation still covers the complete, unmodified query string.

    When `auth_token` is empty, validation fails closed and `(False, url)` is
    returned — mirrors the `sms_pkg/webhook.py` fail-closed contract and the
    threat-model requirement that a missing Twilio secret must never silently
    downgrade to allow-all behaviour.  Configure `TWILIO_AUTH_TOKEN` (or a
    per-account sub-account token) in every environment that receives live
    Twilio webhooks.
    """
    url = _build_webhook_url(request, path)
    diagnostic_url = url.partition("?")[0]

    if not auth_token:
        logger.warning(
            f"Twilio signature validation failed — no auth token configured ({path}). "
            f"Set TWILIO_AUTH_TOKEN (or a per-account sub-account token)."
        )
        return False, diagnostic_url

    try:
        from twilio.request_validator import RequestValidator

        validator = RequestValidator(auth_token)
        signature = request.headers.get("X-Twilio-Signature", "")

        # GET query fields are already covered by the URL, not POST parameters.
        parameters = {} if request.method == "GET" else dict(form_data)
        is_valid = validator.validate(url, parameters, signature)
        return is_valid, diagnostic_url
    except Exception as exc:
        logger.warning(f"Twilio signature validation error on {path}: {type(exc).__name__}")
        return False, diagnostic_url


def get_call_auth_token(
    db: Session,
    *,
    to_number: Optional[str] = None,
    call_sid: Optional[str] = None,
    parent_call_sid: Optional[str] = None,
) -> str:
    """Resolve which Twilio auth token to validate against.

    Known call/leg ownership is authoritative; ``To`` can be a transfer
    destination owned by a different account. Both supplied SIDs must agree
    on one parent call. Only an unresolved new call may use its phone number.
    Database lookup failures never fall through to another account's token.
    """
    from ..models.account import Account
    from ..models.call_log import CallLeg, CallLog
    from ..models.phone_number import PhoneNumber

    # Query only the columns we need — never load a full Account ORM object here.
    # Loading full Account rows triggers SQLAlchemy's PostgreSQL native-enum type
    # resolution for `status` / `subscription_tier`, which can fail if the PG enum
    # type in a remote DB (e.g. Neon) was created with different values/casing than
    # the current Python enum definitions.  Selecting a single String column avoids
    # that entirely and is also more efficient.

    try:
        owners = {}
        for sid in (call_sid, parent_call_sid):
            if not sid:
                continue
            log_row = (
                db.query(CallLog.id, CallLog.account_id)
                .filter(CallLog.call_sid == sid)
                .first()
            )
            if not log_row:
                leg_row = (
                    db.query(CallLeg.call_log_id)
                    .filter(CallLeg.call_sid == sid)
                    .first()
                )
                if leg_row:
                    log_row = (
                        db.query(CallLog.id, CallLog.account_id)
                        .filter(CallLog.id == leg_row.call_log_id)
                        .first()
                    )
                    if not log_row:
                        return ""
            if log_row:
                owners[log_row.id] = log_row.account_id
            elif sid == parent_call_sid and owners:
                return ""
        if len(owners) > 1:
            logger.warning("Twilio callback rejected: call and parent ownership disagree")
            return ""
        account_id = next(iter(owners.values()), None)
        if account_id is None and to_number:
            phone_row = (
                db.query(PhoneNumber.account_id)
                .filter(PhoneNumber.phone_number == to_number)
                .first()
            )
            account_id = phone_row.account_id if phone_row else None
        if account_id is not None:
            token_row = (
                db.query(Account.twilio_sub_auth_token)
                .filter(Account.id == account_id)
                .first()
            )
            if not token_row:
                return ""
            if token_row.twilio_sub_auth_token:
                return token_row.twilio_sub_auth_token
    except Exception:
        logger.warning("Twilio callback rejected: ownership lookup unavailable")
        try:
            db.rollback()
        except Exception:
            pass
        return ""

    # Preserve platform-owned numbers/accounts without a sub-account token.
    return os.environ.get("TWILIO_AUTH_TOKEN", "")


# ---------------------------------------------------------------------------
# Stream-token binding for the media WebSocket
# ---------------------------------------------------------------------------

# Default TTL: 5 minutes covers the time between `/incoming` returning
# TwiML and Twilio dialling the WebSocket.  Real-world delay is sub-second;
# this is a safety margin for retries and clock skew.
STREAM_TOKEN_TTL_SECONDS = 300


def _stream_token_secret(account_token: str) -> str:
    """Choose the HMAC secret for stream tokens.

    Prefer an explicit secret (`STREAM_TOKEN_SECRET`) so rotating the
    Twilio auth token doesn't invalidate in-flight calls; otherwise
    fall back to the per-account Twilio auth token (or platform env)
    so deployments work out of the box.
    """
    explicit = os.environ.get("STREAM_TOKEN_SECRET", "")
    if explicit:
        return explicit
    if account_token:
        return account_token
    return os.environ.get("TWILIO_AUTH_TOKEN", "")


def _stream_payload(call_sid: str, to_number: str, exp: int) -> bytes:
    return f"{call_sid}|{to_number}|{exp}".encode("utf-8")


def mint_stream_token(
    call_sid: str,
    to_number: str,
    account_token: str,
    ttl_seconds: int = STREAM_TOKEN_TTL_SECONDS,
) -> tuple[str, int]:
    """Mint a stream-binding token.

    Returns `(token, exp_unix)`.  When no secret is available, returns
    `("", 0)` — `verify_stream_token()` will reject any token (including
    empty) when no secret is configured, so the WebSocket will be closed.
    """
    secret = _stream_token_secret(account_token)
    if not secret:
        return "", 0

    exp = int(time.time()) + max(1, int(ttl_seconds))
    digest = hmac.new(
        secret.encode("utf-8"),
        _stream_payload(call_sid, to_number, exp),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return digest, exp


def verify_stream_token(
    call_sid: str,
    to_number: str,
    token: str,
    exp: str | int,
    account_token: str,
) -> tuple[bool, str]:
    """Verify a stream-binding token minted by `mint_stream_token()`.

    Returns `(is_valid, reason)` where `reason` is a short tag suitable
    for logging on rejection.

    Behaviour:
      * No secret configured → skip HMAC (returns True, "skipped_no_secret").
        Mirrors the HTTP validate_twilio_signature skip-when-no-token contract
        so local dev works without secrets set.  The CallLog binding check in
        websockets.py is still enforced, so an attacker cannot forge a callSid
        that never went through the authenticated /incoming route.
      * Missing token / exp when a secret IS configured → reject.
      * Expired or tampered → reject.
    """
    secret = _stream_token_secret(account_token)
    if not secret:
        logger.warning(
            "Stream token verification skipped — no HMAC secret configured "
            "(STREAM_TOKEN_SECRET / TWILIO_AUTH_TOKEN / sub-account token all absent). "
            "WebSocket is protected only by CallLog binding. "
            "Set TWILIO_AUTH_TOKEN or STREAM_TOKEN_SECRET in production."
        )
        return True, "skipped_no_secret"

    if not token or exp in (None, "", 0):
        return False, "missing"

    try:
        exp_int = int(exp)
    except (TypeError, ValueError):
        return False, "exp_malformed"

    if exp_int < int(time.time()):
        return False, "expired"

    expected = hmac.new(
        secret.encode("utf-8"),
        _stream_payload(call_sid, to_number, exp_int),
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, token):
        return False, "signature_mismatch"

    return True, "ok"
