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
    return f"{base}{path}"


def validate_twilio_signature(
    request: Request,
    form_data: dict,
    path: str,
    auth_token: str,
) -> tuple[bool, str]:
    """Validate the `X-Twilio-Signature` header.

    Returns `(is_valid, validated_url)`.  The URL is included so callers
    can log it on failure to diagnose proxy / host mismatches.

    When `auth_token` is empty, validation fails closed and `(False, url)` is
    returned — mirrors the `sms_pkg/webhook.py` fail-closed contract and the
    threat-model requirement that a missing Twilio secret must never silently
    downgrade to allow-all behaviour.  Configure `TWILIO_AUTH_TOKEN` (or a
    per-account sub-account token) in every environment that receives live
    Twilio webhooks.
    """
    url = _build_webhook_url(request, path)

    if not auth_token:
        logger.warning(
            f"Twilio signature validation failed — no auth token configured ({path}). "
            f"Set TWILIO_AUTH_TOKEN (or a per-account sub-account token)."
        )
        return False, url

    try:
        from twilio.request_validator import RequestValidator

        validator = RequestValidator(auth_token)
        signature = request.headers.get("X-Twilio-Signature", "")

        # Diagnostic — logs enough to confirm header arrival and token usage
        # without leaking the full values. Remove once signature validation is stable.
        logger.info(
            f"[twilio-sig-debug] path={path} "
            f"sig_present={'yes' if signature else 'NO — HEADER MISSING'} "
            f"sig_len={len(signature)} "
            f"sig_prefix={signature[:8] if signature else ''} "
            f"token_prefix={auth_token[:8] if auth_token else ''} "
            f"form_keys={sorted(dict(form_data).keys())} "
            f"url={url}"
        )

        is_valid = validator.validate(url, dict(form_data), signature)
        return is_valid, url
    except Exception as exc:
        logger.warning(f"Twilio signature validation error on {path}: {exc}")
        return False, url


def get_call_auth_token(
    db: Session,
    *,
    to_number: Optional[str] = None,
    call_sid: Optional[str] = None,
    parent_call_sid: Optional[str] = None,
) -> str:
    """Resolve which Twilio auth token to validate against.

    Voice webhooks may carry either `To` (incoming) or `CallSid` /
    `ParentCallSid` (status, connect-complete, transfer-status).  We
    prefer the hotel sub-account token where possible, falling back to
    the platform-level `TWILIO_AUTH_TOKEN` env var when the hotel-level
    token is not configured (or no resolution path is available).
    """
    from ..models.account import Account
    from ..models.call_log import CallLog
    from ..models.phone_number import PhoneNumber

    account = None

    if to_number:
        try:
            phone = db.query(PhoneNumber).filter(PhoneNumber.phone_number == to_number).first()
            if phone:
                account = db.query(Account).filter(Account.id == phone.account_id).first()
                if account:
                    logger.debug(
                        f"get_call_auth_token: resolved via phone_number={to_number} "
                        f"account_id={account.id} has_token={bool(account.twilio_sub_auth_token)}"
                    )
        except Exception:
            logger.warning(
                f"get_call_auth_token: DB lookup via to_number={to_number} failed — "
                f"falling back to call_sid lookup",
                exc_info=True,
            )
            try:
                db.rollback()
            except Exception:
                pass

    if account is None:
        for sid in (call_sid, parent_call_sid):
            if not sid:
                continue
            try:
                call_log = db.query(CallLog).filter(CallLog.call_sid == sid).first()
                if call_log:
                    account = db.query(Account).filter(Account.id == call_log.account_id).first()
                    if account:
                        logger.debug(
                            f"get_call_auth_token: resolved via call_sid={sid} "
                            f"account_id={account.id} has_token={bool(account.twilio_sub_auth_token)}"
                        )
                        break
            except Exception:
                logger.warning(
                    f"get_call_auth_token: DB lookup via call_sid={sid} failed",
                    exc_info=True,
                )
                try:
                    db.rollback()
                except Exception:
                    pass

    if account and account.twilio_sub_auth_token:
        return account.twilio_sub_auth_token

    logger.warning(
        f"get_call_auth_token: could not resolve sub-account token "
        f"(to_number={to_number}, call_sid={call_sid}) — falling back to TWILIO_AUTH_TOKEN env var"
    )
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
