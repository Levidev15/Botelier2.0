"""
Recording Sync Service.

Provides the shared utility for syncing Twilio phone-number-level call recording
configuration.  Imported by both the phone-numbers and assistants API routers to
avoid cross-router coupling.
"""

import logging
import os as _os

from sqlalchemy.orm import Session

from botelier.models.phone_number import PhoneNumber
from botelier.models.account import Account
from botelier.models.assistant import Assistant
from botelier.integrations.twilio.phone_numbers import PhoneNumberManager
from botelier.auth.features import get_account_features
from botelier.config.domain import get_public_base_url


_log = logging.getLogger(__name__)


def sync_phone_number_recording(
    phone_number: PhoneNumber,
    account: Account,
    db: Session,
) -> None:
    """
    Sync Twilio phone-number-level call recording config for *phone_number*.

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
