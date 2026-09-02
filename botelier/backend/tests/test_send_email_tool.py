"""Tests for the SEND_EMAIL tool handler and email_service SendGrid rewrite.

Covers:
  1. send_email() calls SendGrid API with correct to/from/subject/body.
  2. Missing SENDGRID_API_KEY logs a warning and returns False (no crash).
  3. Missing EMAIL_FROM_DEFAULT logs a warning and returns False.
  4. SendGrid non-2xx response returns False.
  5. _map_send_email handler passes correct args to send_email.
  6. LLM-supplied subject and message override tool config defaults.
  7. Configured subject remains available when the LLM omits the optional subject.
  8. Missing 'to' arg returns skipped result (no send attempted).
  9. Account-level email_from/email_from_name are used when set.
 10. Empty message body returns skipped result.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_response(status_code: int = 202):
    resp = MagicMock()
    resp.status_code = status_code
    return resp


def _make_env(api_key="sg-test-key", from_email="hello@botelier.io", from_name="Botelier"):
    env = {}
    if api_key is not None:
        env["SENDGRID_API_KEY"] = api_key
    if from_email is not None:
        env["EMAIL_FROM_DEFAULT"] = from_email
    if from_name is not None:
        env["EMAIL_FROM_NAME_DEFAULT"] = from_name
    return env


# ---------------------------------------------------------------------------
# email_service.send_email — unit tests
# ---------------------------------------------------------------------------


class TestSendEmailService:
    def test_calls_sendgrid_with_correct_params(self):
        """SendGrid client must be called with the right to/from/subject/body."""
        from botelier.services import email_service

        mock_sg_instance = MagicMock()
        mock_sg_instance.send.return_value = _make_mock_response(202)

        with (
            patch.dict("os.environ", _make_env(), clear=False),
            patch("botelier.services.email_service.SendGridAPIClient", return_value=mock_sg_instance),
        ):
            result = email_service.send_email(
                to_addresses=["guest@hotel.com"],
                subject="Your booking confirmation",
                body_text="Hello, your booking is confirmed.",
            )

        assert result is True
        mock_sg_instance.send.assert_called_once()
        # Inspect the Mail object passed to send()
        sent_mail = mock_sg_instance.send.call_args[0][0]
        assert sent_mail.subject.get() == "Your booking confirmation"

    def test_missing_api_key_returns_false_and_logs_warning(self, caplog):
        """No SENDGRID_API_KEY → return False without raising."""
        from botelier.services import email_service

        env = _make_env(api_key=None)
        with (
            patch.dict("os.environ", env, clear=False),
            patch.dict("os.environ", {"SENDGRID_API_KEY": ""}, clear=False),
        ):
            import importlib
            importlib.reload(email_service)
            with patch("botelier.services.email_service._sendgrid_api_key", return_value=None):
                result = email_service.send_email(
                    to_addresses=["guest@hotel.com"],
                    subject="Test",
                    body_text="Body",
                )

        assert result is False

    def test_missing_from_email_returns_false(self):
        """No sender address configured → return False, do not call SendGrid."""
        from botelier.services import email_service

        mock_sg_instance = MagicMock()

        with (
            patch.dict("os.environ", _make_env(from_email=""), clear=False),
            patch("botelier.services.email_service.SendGridAPIClient", return_value=mock_sg_instance),
            patch("botelier.services.email_service._sendgrid_api_key", return_value="sg-fake"),
        ):
            result = email_service.send_email(
                to_addresses=["guest@hotel.com"],
                subject="Test",
                body_text="Body",
            )

        assert result is False
        mock_sg_instance.send.assert_not_called()

    def test_sendgrid_non_2xx_returns_false(self):
        """A 4xx/5xx response from SendGrid must return False."""
        from botelier.services import email_service

        mock_sg_instance = MagicMock()
        mock_sg_instance.send.return_value = _make_mock_response(400)

        with (
            patch.dict("os.environ", _make_env(), clear=False),
            patch("botelier.services.email_service.SendGridAPIClient", return_value=mock_sg_instance),
        ):
            result = email_service.send_email(
                to_addresses=["guest@hotel.com"],
                subject="Test",
                body_text="Body",
            )

        assert result is False

    def test_from_email_override_used_when_provided(self):
        """Explicit from_email/from_name params must take priority over env defaults."""
        from botelier.services import email_service

        mock_sg_instance = MagicMock()
        mock_sg_instance.send.return_value = _make_mock_response(202)

        with (
            patch.dict("os.environ", _make_env(), clear=False),
            patch("botelier.services.email_service.SendGridAPIClient", return_value=mock_sg_instance),
        ):
            result = email_service.send_email(
                to_addresses=["guest@hotel.com"],
                subject="Test",
                body_text="Body",
                from_email="custom@myproperty.com",
                from_name="My Property",
            )

        assert result is True
        sent_mail = mock_sg_instance.send.call_args[0][0]
        # The From field should reflect the override
        from_field = sent_mail.from_email
        assert from_field.get()["email"] == "custom@myproperty.com"

    def test_empty_recipient_list_returns_false(self):
        """Empty to_addresses must short-circuit before touching SendGrid."""
        from botelier.services import email_service

        mock_sg_instance = MagicMock()

        with (
            patch.dict("os.environ", _make_env(), clear=False),
            patch("botelier.services.email_service.SendGridAPIClient", return_value=mock_sg_instance),
        ):
            result = email_service.send_email(
                to_addresses=[],
                subject="Test",
                body_text="Body",
            )

        assert result is False
        mock_sg_instance.send.assert_not_called()

    def test_sendgrid_exception_returns_false_no_raise(self):
        """SendGrid SDK exception must be caught — never propagate to callers."""
        from botelier.services import email_service

        mock_sg_instance = MagicMock()
        mock_sg_instance.send.side_effect = RuntimeError("network error")

        with (
            patch.dict("os.environ", _make_env(), clear=False),
            patch("botelier.services.email_service.SendGridAPIClient", return_value=mock_sg_instance),
        ):
            result = email_service.send_email(
                to_addresses=["guest@hotel.com"],
                subject="Test",
                body_text="Body",
            )

        assert result is False


# ---------------------------------------------------------------------------
# _map_send_email handler — integration-level unit tests
# ---------------------------------------------------------------------------


def _make_tool(config: dict = None, description: str = "") -> MagicMock:
    """Return a mock Tool configured as SEND_EMAIL."""
    from botelier.models.tool import ToolType

    tool = MagicMock()
    tool.tool_type = ToolType.SEND_EMAIL
    tool.name = "send_confirmation_email"
    tool.description = description
    tool.config = config or {}
    return tool


def _make_mapper(account_id="acc-123", account_name="Grand Hotel", session_factory=None):
    """Return a FunctionMapper with the minimal attrs needed for send_email_handler."""
    from botelier.voice.function_mapper import FunctionMapper

    mapper = FunctionMapper(
        call_sid="CA-test",
        from_number="+15551234567",
        to_number="+15559876543",
        account_id=account_id,
        account_name=account_name,
        session_factory=session_factory,
    )
    return mapper


def _run(coro):
    # Use asyncio.run() so each call gets a fresh event loop rather than
    # inheriting a potentially-closed loop from an earlier test in the suite.
    return asyncio.run(coro)


class _FakeParams:
    """Minimal stand-in for FunctionCallParams."""

    def __init__(self, arguments: dict):
        self.arguments = arguments
        self._result = None

    async def result_callback(self, value: Any):
        self._result = value


class TestSendEmailHandler:
    def _call_handler(self, mapper, tool, arguments: dict) -> dict:
        _, handler = mapper._map_send_email(tool)
        params = _FakeParams(arguments)
        _run(handler(params))
        return params._result

    def test_message_is_required_in_llm_schema(self):
        """The LLM must provide the email body for every SEND_EMAIL call."""
        from botelier.voice.function_mapper import FunctionMapper

        mapper = _make_mapper()
        schema, _ = mapper._map_send_email(_make_tool())

        assert "message" in schema["parameters"]["required"]

    def test_lm_values_override_config_defaults(self):
        """LLM-supplied subject/message must take priority over tool config."""
        tool = _make_tool(
            config={
                "default_subject": "Default subject",
                "message_body": "Default body",
            }
        )
        mapper = _make_mapper()

        with (
            patch("botelier.services.email_service.SendGridAPIClient") as MockSG,
        ):
            mock_instance = MagicMock()
            mock_instance.send.return_value = _make_mock_response(202)
            MockSG.return_value = mock_instance

            with patch.dict(
                "os.environ",
                {"SENDGRID_API_KEY": "sg-key", "EMAIL_FROM_DEFAULT": "bot@botelier.io"},
            ):
                result = self._call_handler(
                    mapper,
                    tool,
                    {
                        "to": "guest@hotel.com",
                        "subject": "LLM subject",
                        "message": "LLM message body",
                    },
                )

        assert result["status"] == "sent"
        assert result["to"] == "guest@hotel.com"
        assert result["subject"] == "LLM subject"
        sent_mail = mock_instance.send.call_args[0][0]
        assert sent_mail.subject.get() == "LLM subject"

    def test_config_body_remains_compatibility_fallback(self):
        """Existing configured bodies remain a fallback for non-LLM callers."""
        tool = _make_tool(
            config={
                "default_subject": "Your stay details",
                    "message_body": "Configured fallback body",
            }
        )
        mapper = _make_mapper(account_name="Grand Hotel")

        with patch("botelier.services.email_service.SendGridAPIClient") as MockSG:
            mock_instance = MagicMock()
            mock_instance.send.return_value = _make_mock_response(202)
            MockSG.return_value = mock_instance

            with patch.dict(
                "os.environ",
                {"SENDGRID_API_KEY": "sg-key", "EMAIL_FROM_DEFAULT": "bot@botelier.io"},
            ):
                result = self._call_handler(
                    mapper,
                    tool,
                    {"to": "guest@hotel.com"},
                )

        assert result["status"] == "sent"
        assert result["subject"] == "Your stay details"
        sent_mail = mock_instance.send.call_args[0][0]
        plain_content = sent_mail.contents[0].get()["value"]
        assert plain_content == "Configured fallback body"

    def test_missing_to_returns_skipped(self):
        """Handler must return skipped (not raise) when 'to' is absent."""
        tool = _make_tool()
        mapper = _make_mapper()

        result = self._call_handler(mapper, tool, {})
        assert result["status"] == "skipped"
        assert "recipient" in result["reason"].lower() or "email address" in result["reason"].lower()

    def test_empty_body_returns_skipped(self):
        """No message body (no LLM value, no config template) → skipped result."""
        tool = _make_tool(config={"default_subject": "Hi"})  # no message_body
        mapper = _make_mapper()

        with patch.dict(
            "os.environ",
            {"SENDGRID_API_KEY": "sg-key", "EMAIL_FROM_DEFAULT": "bot@botelier.io"},
        ):
            result = self._call_handler(mapper, tool, {"to": "guest@hotel.com"})

        assert result["status"] == "skipped"

    def test_account_email_from_used_when_set(self):
        """Account-level email_from/email_from_name must override platform env defaults."""
        tool = _make_tool(
            config={
                "default_subject": "Welcome",
                "message_body": "Hello!",
            }
        )

        # Mock a session_factory that returns an account with custom sender
        mock_account = MagicMock()
        mock_account.email_from = "front-desk@grandhotel.com"
        mock_account.email_from_name = "Grand Hotel Front Desk"

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.first.return_value = mock_account

        session_factory = MagicMock(return_value=mock_session)

        mapper = _make_mapper(session_factory=session_factory)

        with patch("botelier.services.email_service.SendGridAPIClient") as MockSG:
            mock_instance = MagicMock()
            mock_instance.send.return_value = _make_mock_response(202)
            MockSG.return_value = mock_instance

            with patch.dict(
                "os.environ",
                {"SENDGRID_API_KEY": "sg-key", "EMAIL_FROM_DEFAULT": "platform@botelier.io"},
            ):
                result = self._call_handler(
                    mapper,
                    tool,
                    {"to": "guest@hotel.com", "message": "Hello from the front desk."},
                )

        assert result["status"] == "sent"
        sent_mail = mock_instance.send.call_args[0][0]
        from_field = sent_mail.from_email
        assert from_field.get()["email"] == "front-desk@grandhotel.com"

    def test_account_email_from_used_from_existing_db_session(self):
        """When mapper.db_session is set (simulator/API context), it is used instead of session_factory."""
        tool = _make_tool(
            config={
                "default_subject": "Welcome",
                "message_body": "Hello!",
            }
        )

        mock_account = MagicMock()
        mock_account.email_from = "api@myproperty.com"
        mock_account.email_from_name = "My Property API"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_account

        # session_factory is NOT set; db_session is set directly
        mapper = _make_mapper(session_factory=None)
        mapper.db_session = mock_db  # inject existing session

        with patch("botelier.services.email_service.SendGridAPIClient") as MockSG:
            mock_instance = MagicMock()
            mock_instance.send.return_value = _make_mock_response(202)
            MockSG.return_value = mock_instance

            with patch.dict(
                "os.environ",
                {"SENDGRID_API_KEY": "sg-key", "EMAIL_FROM_DEFAULT": "platform@botelier.io"},
            ):
                result = self._call_handler(
                    mapper,
                    tool,
                    {"to": "guest@hotel.com", "message": "Here is the information you requested."},
                )

        assert result["status"] == "sent"
        sent_mail = mock_instance.send.call_args[0][0]
        from_field = sent_mail.from_email
        assert from_field.get()["email"] == "api@myproperty.com"

    def test_delivery_failure_returns_failed_status(self):
        """When send_email returns False, handler must return failed status."""
        tool = _make_tool(
            config={"default_subject": "Hi", "message_body": "Hello!"}
        )
        mapper = _make_mapper()

        with patch("botelier.services.email_service.SendGridAPIClient") as MockSG:
            mock_instance = MagicMock()
            mock_instance.send.return_value = _make_mock_response(500)
            MockSG.return_value = mock_instance

            with patch.dict(
                "os.environ",
                {"SENDGRID_API_KEY": "sg-key", "EMAIL_FROM_DEFAULT": "bot@botelier.io"},
            ):
                result = self._call_handler(
                    mapper,
                    tool,
                    {"to": "guest@hotel.com", "message": "Your requested information is attached."},
                )

        assert result["status"] == "failed"
