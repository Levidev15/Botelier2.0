"""Scoped synchronous-provider delivery boundaries for native flow actions."""

import asyncio
import re

from botelier.voice.flows.native_execution import NativeTerminalResult


_E164 = re.compile(r"\+[1-9][0-9]{7,14}\Z")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")
_MAX_SMS_BODY = 1600
_MAX_EMAIL_SUBJECT = 200
_MAX_EMAIL_BODY = 30_000
_DEFAULT_TIMEOUT = 8.0


class NativeMessenger:
    """Send only pre-rendered, caller-approved content through account tools.

    This class is a transport boundary, not a source of message content or
    consent. The action broker must resolve configured templates and establish
    the current confirmation before calling it.
    """

    def __init__(
        self, *, identity, twilio_client, from_number, execution_mode="execute",
        email_dispatch=None, timeout=_DEFAULT_TIMEOUT,
    ):
        if (
            not all(isinstance(getattr(identity, key, None), str) and
                    getattr(identity, key) for key in ("account_id", "property_id"))
            or execution_mode not in {"execute", "preview"}
            or type(timeout) not in (int, float) or timeout <= 0 or timeout > 30
        ):
            raise ValueError("native_messenger_config")
        self.identity = identity
        self.twilio_client = twilio_client
        self.from_number = from_number
        self.execution_mode = execution_mode
        self.email_dispatch = email_dispatch
        self.timeout = float(timeout)

    async def send_sms(self, recipient, body):
        invalid = self.validate_sms(recipient, body, self.from_number)
        if invalid:
            return NativeTerminalResult(False, failure_reason=invalid)
        if self.execution_mode != "execute":
            return NativeTerminalResult(False, failure_reason="preview_required")
        if self.twilio_client is None:
            return NativeTerminalResult(False, failure_reason="messenger_unavailable")

        try:
            accepted = await asyncio.wait_for(asyncio.to_thread(
                self.twilio_client.messages.create,
                body=body, from_=self.from_number, to=recipient,
            ), timeout=self.timeout)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A synchronous provider may continue after asyncio's timeout. Do
            # not assert rejection; the durable claim must remain pending.
            return NativeTerminalResult(False, failure_reason="effect_outcome_unknown")
        if not isinstance(getattr(accepted, "sid", None), str) or not accepted.sid:
            return NativeTerminalResult(False, failure_reason="effect_outcome_unknown")
        return NativeTerminalResult(True, completed=False)

    @staticmethod
    def validate_sms(recipient, body, from_number):
        if (
            not isinstance(recipient, str) or not _E164.fullmatch(recipient)
            or not isinstance(from_number, str) or not _E164.fullmatch(from_number)
        ):
            return "invalid_recipient"
        if not isinstance(body, str) or not body.strip() or len(body) > _MAX_SMS_BODY:
            return "invalid_message"
        return None

    async def send_email(self, connection, recipient, subject, body, *, db=None):
        invalid = self.validate_email(
            connection, recipient, subject, body, self.identity,
        )
        if invalid:
            return NativeTerminalResult(False, failure_reason=invalid)
        if self.execution_mode != "execute":
            return NativeTerminalResult(False, failure_reason="preview_required")
        return await asyncio.wait_for(asyncio.to_thread(
            self.send_email_sync, connection, recipient, subject, body, db=db,
        ), timeout=self.timeout)

    def send_email_sync(self, connection, recipient, subject, body, *, db=None):
        invalid = self.validate_email(
            connection, recipient, subject, body, self.identity,
        )
        if invalid:
            return NativeTerminalResult(False, failure_reason=invalid)
        if self.execution_mode != "execute":
            return NativeTerminalResult(False, failure_reason="preview_required")

        dispatch = self.email_dispatch
        if dispatch is None:
            from botelier.services.email_service import send_email_via_connection
            dispatch = send_email_via_connection
        try:
            accepted = dispatch(connection, [recipient], subject, body, db=db)
        except Exception:
            return NativeTerminalResult(False, failure_reason="effect_outcome_unknown")
        if accepted is not True:
            # The existing email service can return False after an upstream
            # attempt; conservatively classify this as unknown, not rejected.
            return NativeTerminalResult(False, failure_reason="effect_outcome_unknown")
        return NativeTerminalResult(True, completed=False)

    @staticmethod
    def validate_email(connection, recipient, subject, body, identity):
        if connection is not None:
            if str(getattr(connection, "account_id", "")) != str(identity.account_id):
                return "sender_scope_mismatch"
            integration_type = getattr(connection, "integration_type", None)
            if getattr(integration_type, "slug", None) not in {
                "email-sender-gmail", "email-sender-microsoft",
            }:
                return "sender_scope_mismatch"
            status = getattr(connection, "status", None)
            if getattr(status, "value", status) != "connected":
                return "sender_scope_mismatch"
            property_id = getattr(connection, "property_id", None)
            if property_id is not None and str(property_id) != str(identity.property_id):
                return "sender_scope_mismatch"
        if not isinstance(recipient, str) or not _EMAIL.fullmatch(recipient):
            return "invalid_recipient"
        if (
            not isinstance(subject, str) or not subject.strip()
            or len(subject) > _MAX_EMAIL_SUBJECT or "\r" in subject or "\n" in subject
        ):
            return "invalid_subject"
        if not isinstance(body, str) or not body.strip() or len(body) > _MAX_EMAIL_BODY:
            return "invalid_message"
        return None

    def _email_connection_matches(self, connection):
        if connection is None or str(getattr(connection, "account_id", "")) != str(
            self.identity.account_id,
        ):
            return False
        integration_type = getattr(connection, "integration_type", None)
        if getattr(integration_type, "slug", None) not in {
            "email-sender-gmail", "email-sender-microsoft",
        }:
            return False
        status = getattr(connection, "status", None)
        if getattr(status, "value", status) != "connected":
            return False
        property_id = getattr(connection, "property_id", None)
        if property_id is not None:
            return str(property_id) == str(self.identity.property_id)
        try:
            config = connection.get_connection_config() or {}
        except Exception:
            return False
        return isinstance(config, dict)


__all__ = ["NativeMessenger"]
