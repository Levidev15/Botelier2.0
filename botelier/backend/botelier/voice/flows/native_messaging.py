"""Scoped synchronous-provider delivery boundaries for native flow actions."""

import asyncio
import re
import threading

from botelier.voice.flows.native_execution import NativeTerminalResult


_E164 = re.compile(r"\+[1-9][0-9]{7,14}\Z")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")
_MAX_SMS_BODY = 1600
_MAX_EMAIL_SUBJECT = 200
_MAX_EMAIL_BODY = 30_000
_DEFAULT_TIMEOUT = 8.0


class NativeSMSNotSubmitted(asyncio.CancelledError):
    """Cancellation atomically prevented the provider submission boundary."""


class _SMSSubmissionState:
    """Linearize cancellation against the final pre-submit boundary."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cancelled = False
        self._submitting = False

    def cancelled(self):
        with self._lock:
            return self._cancelled

    def cancel_before_submission(self):
        with self._lock:
            if not self._submitting:
                self._cancelled = True
                return True
            return False

    def begin_submission(self):
        with self._lock:
            if self._cancelled:
                return False
            self._submitting = True
            return True


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

    async def send_sms(self, recipient, body, *, before_submit=None):
        """Send SMS after an optional synchronous worker-thread pre-submit guard.

        The guard runs after resolving the provider callable and immediately
        before the submission boundary; it returns ``None`` to proceed or a
        bounded failure reason to reject without provider I/O.
        """
        invalid = self.validate_sms(recipient, body, self.from_number)
        if invalid:
            return NativeTerminalResult(False, failure_reason=invalid)
        if self.execution_mode != "execute":
            return NativeTerminalResult(False, failure_reason="preview_required")
        if self.twilio_client is None:
            return NativeTerminalResult(False, failure_reason="messenger_unavailable")
        if before_submit is not None and not callable(before_submit):
            return NativeTerminalResult(False, failure_reason="pre_submit_guard_invalid")

        submission = _SMSSubmissionState()
        try:
            accepted = await asyncio.wait_for(
                asyncio.to_thread(
                    self._submit_sms, recipient, body, before_submit, submission,
                ),
                timeout=self.timeout,
            )
        except asyncio.CancelledError as exc:
            if submission.cancel_before_submission():
                raise NativeSMSNotSubmitted() from exc
            raise
        except Exception:
            if submission.cancel_before_submission():
                return NativeTerminalResult(False, failure_reason="submission_cancelled")
            # Once submission began, a synchronous provider may continue after
            # a timeout. Its outcome must remain pending, never guessed.
            return NativeTerminalResult(False, failure_reason="effect_outcome_unknown")
        if isinstance(accepted, NativeTerminalResult):
            return accepted
        if not isinstance(getattr(accepted, "sid", None), str) or not accepted.sid:
            return NativeTerminalResult(False, failure_reason="effect_outcome_unknown")
        return NativeTerminalResult(True, completed=False)

    def _submit_sms(self, recipient, body, before_submit, submission):
        if submission.cancelled():
            return NativeTerminalResult(False, failure_reason="submission_cancelled")
        create = self.twilio_client.messages.create
        if submission.cancelled():
            return NativeTerminalResult(False, failure_reason="submission_cancelled")
        if before_submit is not None:
            try:
                rejected = before_submit()
            except Exception:
                return NativeTerminalResult(
                    False, failure_reason="pre_submit_guard_failed",
                )
            if rejected is not None:
                if type(rejected) is not str:
                    return NativeTerminalResult(
                        False, failure_reason="pre_submit_guard_invalid",
                    )
                return NativeTerminalResult(False, failure_reason=rejected)
        if not submission.begin_submission():
            return NativeTerminalResult(False, failure_reason="submission_cancelled")
        return create(body=body, from_=self.from_number, to=recipient)

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

    def send_email_sync(
        self, connection, recipient, subject, body, *, db=None, body_html=None,
    ):
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
            if body_html is None:
                accepted = dispatch(connection, [recipient], subject, body, db=db)
            else:
                if not isinstance(body_html, str) or not body_html:
                    return NativeTerminalResult(False, failure_reason="invalid_message")
                accepted = dispatch(
                    connection, [recipient], subject, body,
                    body_html=body_html, db=db,
                )
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


__all__ = ["NativeMessenger", "NativeSMSNotSubmitted"]
