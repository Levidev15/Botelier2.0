"""
Recording Sync Service.

Provides utilities for managing Twilio call recording.

Two approaches are available:

1. ``sync_phone_number_recording`` — Legacy phone-number-level ``VoiceRecord``
   configuration via IncomingPhoneNumbers REST API.  Kept for reference but no
   longer called automatically; the in-call approach below supersedes it.

2. ``start_in_call_recording`` — Preferred.  Calls the Twilio Recordings REST
   API (POST /Calls/{CallSid}/Recordings) once the call is answered.  Fires as
   a non-blocking asyncio task from ``call_handler.py`` so it never delays the
   pipeline start.
"""

import asyncio
import logging
import os as _os
from typing import Optional

import requests as _requests

from sqlalchemy.orm import Session

from botelier.models.phone_number import PhoneNumber
from botelier.models.account import Account
from botelier.models.assistant import Assistant
from botelier.integrations.twilio.phone_numbers import PhoneNumberManager
from botelier.auth.features import get_account_features
from botelier.config.domain import get_public_base_url


_log = logging.getLogger(__name__)


async def start_in_call_recording(
    call_sid: str,
    account_sub_sid: Optional[str],
    account_sub_token: Optional[str],
    base_url: str,
) -> None:
    """
    Start recording an in-progress Twilio call via the Recordings REST API.

    Uses ``POST /2010-04-01/Accounts/{AccountSid}/Calls/{CallSid}/Recordings.json``
    (Twilio docs option 6).  This approach requires no phone-number-level
    pre-configuration — the decision to record is made per-call at answer time
    using credentials already in memory.

    The HTTP call is offloaded to a thread via ``asyncio.to_thread`` so it never
    blocks the Pipecat pipeline event loop.

    Credential resolution order:
    1. Account sub-account SID / auth token (``account_sub_sid`` / ``account_sub_token``)
    2. Platform-level env vars (``TWILIO_ACCOUNT_SID`` / ``TWILIO_AUTH_TOKEN``)

    Failures are logged as warnings and never propagate — a recording error must
    never abort an active call.
    """
    account_sid = account_sub_sid or _os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = account_sub_token or _os.environ.get("TWILIO_AUTH_TOKEN")

    if not account_sid or not auth_token:
        _log.warning(
            "No Twilio credentials available for in-call recording — skipping (call %s)",
            call_sid,
        )
        return

    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}"
        f"/Calls/{call_sid}/Recordings.json"
    )
    data = {
        "RecordingChannels": "dual",
        "RecordingStatusCallback": f"{base_url}/api/calls/recording-status",
        "RecordingStatusCallbackMethod": "POST",
    }

    def _post() -> _requests.Response:
        return _requests.post(url, data=data, auth=(account_sid, auth_token), timeout=10)

    try:
        response = await asyncio.to_thread(_post)
        if response.status_code == 201:
            recording_sid = response.json().get("sid", "unknown")
            _log.info(
                "✅ Started in-call recording for %s (SID %s)",
                call_sid, recording_sid,
            )
        else:
            _log.warning(
                "Failed to start in-call recording for %s: HTTP %s — %s",
                call_sid, response.status_code, response.text[:300],
            )
    except Exception as exc:
        _log.warning("Error starting in-call recording for %s: %s", call_sid, exc)


def sync_phone_number_recording(
    phone_number: PhoneNumber,
    account: Account,
    db: Session,
) -> None:
    """
    Sync Twilio phone-number-level call recording config for *phone_number*.

    NOTE: This function is superseded by ``start_in_call_recording`` which fires
    at call-answer time and requires no phone-number pre-configuration.  It is
    kept here for reference and is no longer called automatically by the platform.
    Manual calls from the Admin UI (Reconfigure button) still work.

    Resolves whether recording should be active by combining the account's
    feature entitlement (``call_recording``) with the assistant's per-instance
    toggle (``call_settings.call_recording_enabled``).  Sends a direct REST
    request to Twilio because the Python SDK's ``incoming_phone_numbers().update()``
    does not expose the ``VoiceRecord`` parameter.

    Credential resolution order:
    1. Account sub-account credentials (``twilio_sub_account_sid`` /
       ``twilio_sub_auth_token``) — preferred; used when present.
    2. Main account / environment credentials (``TWILIO_ACCOUNT_SID`` /
       ``TWILIO_AUTH_TOKEN`` env vars) — fallback for accounts that share the
       main Twilio account rather than having a dedicated sub-account.

    Silently logs warnings on failure so that transient Twilio errors never
    prevent the primary DB operation from succeeding.
    """
    has_sub_creds = bool(
        account.twilio_sub_account_sid and account.twilio_sub_auth_token
    )
    has_main_creds = bool(
        _os.environ.get("TWILIO_ACCOUNT_SID") and _os.environ.get("TWILIO_AUTH_TOKEN")
    )

    if not has_sub_creds and not has_main_creds:
        _log.warning(
            "No Twilio credentials available for account %s — skipping recording sync",
            account.id,
        )
        return

    try:
        features = get_account_features(
            subscription_tier=getattr(account, "subscription_tier", None) or "free",
            feature_flags_override=account.feature_flags or {},
        )
        account_recording_allowed = features.get("call_recording", False)

        assistant_recording_enabled = False
        if account_recording_allowed and phone_number.assistant_id:
            assistant = db.query(Assistant).filter(
                Assistant.id == phone_number.assistant_id
            ).first()
            if assistant:
                assistant_recording_enabled = bool(
                    (assistant.call_settings or {}).get("call_recording_enabled", False)
                )

        should_record = account_recording_allowed and assistant_recording_enabled

        if has_sub_creds:
            manager = PhoneNumberManager(
                sub_account_sid=account.twilio_sub_account_sid,
                sub_auth_token=account.twilio_sub_auth_token,
            )
        else:
            manager = PhoneNumberManager(
                sub_account_sid=_os.environ["TWILIO_ACCOUNT_SID"],
                sub_auth_token=_os.environ["TWILIO_AUTH_TOKEN"],
            )

        base_url = get_public_base_url()
        manager.sync_recording_config(
            phone_number_sid=phone_number.twilio_sid,
            recording_enabled=should_record,
            recording_status_callback_url=f"{base_url}/api/calls/recording-status",
        )
        _log.info(
            "Synced recording config for %s (SID %s): should_record=%s",
            phone_number.phone_number,
            phone_number.twilio_sid,
            should_record,
        )
    except Exception as exc:
        _log.warning(
            "Failed to sync recording config for %s (SID %s): %s",
            phone_number.phone_number,
            phone_number.twilio_sid,
            exc,
        )
