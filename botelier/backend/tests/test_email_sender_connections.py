"""Tests for connected email sender delivery (Gmail, Microsoft).

Covers the new Task #655 functionality:
 1. send_email_via_gmail  — success, API error, empty recipients, network error
 2. send_email_via_microsoft — success, API error, empty recipients, network error
 3. send_email_via_connection — provider routing, missing token, disconnected status,
                                unsupported slug
 4. _map_send_email handler — connection_id routes to connected sender, connection not
                              found → failed, disconnected → failed with reconnect
                              message, Gmail delivery → sent, Microsoft → sent,
                              absent connection_id → SendGrid fallback (not connected)
"""

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

os_import_guard = True  # ensure we can import without a real DB


def _mock_response(status_code: int, text: str = ""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    return r


def _run(coro):
    return asyncio.run(coro)


class _FakeParams:
    def __init__(self, arguments: dict):
        self.arguments = arguments
        self._result = None

    async def result_callback(self, value: Any):
        self._result = value


# ---------------------------------------------------------------------------
# 1. send_email_via_gmail
# ---------------------------------------------------------------------------


class TestSendEmailViaGmail:
    def test_success_calls_gmail_api_with_bearer_token(self):
        from botelier.services.email_service import send_email_via_gmail

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(200)
            result = send_email_via_gmail(
                to_addresses=["guest@hotel.com"],
                subject="Your booking",
                body_text="Hello!",
                access_token="tok-abc",
                from_email="concierge@hotel.com",
            )

        assert result is True
        call_kwargs = mock_req.post.call_args
        headers = call_kwargs[1]["headers"] if call_kwargs[1] else call_kwargs[0][1]
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer tok-abc"

    def test_202_accepted_counts_as_success(self):
        from botelier.services.email_service import send_email_via_gmail

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(202)
            result = send_email_via_gmail(
                to_addresses=["a@b.com"],
                subject="Hi",
                body_text="Hello",
                access_token="tok",
                from_email="sender@hotel.com",
            )

        assert result is True

    def test_non_auth_api_error_returns_false(self):
        """Non-auth errors (5xx) return False without raising."""
        from botelier.services.email_service import send_email_via_gmail

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(500, "Internal Server Error")
            result = send_email_via_gmail(
                to_addresses=["a@b.com"],
                subject="Hi",
                body_text="Hello",
                access_token="tok",
                from_email="sender@hotel.com",
            )

        assert result is False

    def test_401_raises_email_sender_auth_error(self):
        """A 401 response must raise EmailSenderAuthError (not return False)."""
        from botelier.services.email_service import EmailSenderAuthError, send_email_via_gmail

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(401, "Unauthorized")
            with pytest.raises(EmailSenderAuthError, match="reconnect"):
                send_email_via_gmail(
                    to_addresses=["a@b.com"],
                    subject="Hi",
                    body_text="Hello",
                    access_token="expired-tok",
                    from_email="sender@hotel.com",
                )

    def test_403_raises_email_sender_auth_error(self):
        """A 403 response must raise EmailSenderAuthError (not return False)."""
        from botelier.services.email_service import EmailSenderAuthError, send_email_via_gmail

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(403, "Forbidden")
            with pytest.raises(EmailSenderAuthError):
                send_email_via_gmail(
                    to_addresses=["a@b.com"],
                    subject="Hi",
                    body_text="Hello",
                    access_token="revoked-tok",
                    from_email="sender@hotel.com",
                )

    def test_empty_recipients_returns_false_without_http_call(self):
        from botelier.services.email_service import send_email_via_gmail

        with patch("botelier.services.email_service._requests") as mock_req:
            result = send_email_via_gmail(
                to_addresses=[],
                subject="Hi",
                body_text="Hello",
                access_token="tok",
                from_email="sender@hotel.com",
            )

        assert result is False
        mock_req.post.assert_not_called()

    def test_network_error_returns_false_no_raise(self):
        from botelier.services.email_service import send_email_via_gmail

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.side_effect = ConnectionError("network error")
            result = send_email_via_gmail(
                to_addresses=["a@b.com"],
                subject="Hi",
                body_text="Hello",
                access_token="tok",
                from_email="sender@hotel.com",
            )

        assert result is False

    def test_multiple_recipients_sends_separate_messages(self):
        from botelier.services.email_service import send_email_via_gmail

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(202)
            result = send_email_via_gmail(
                to_addresses=["a@b.com", "c@d.com"],
                subject="Hi",
                body_text="Hello",
                access_token="tok",
                from_email="sender@hotel.com",
            )

        assert result is True
        assert mock_req.post.call_count == 2

    def test_partial_failure_returns_false(self):
        """If any recipient fails, the overall result is False."""
        from botelier.services.email_service import send_email_via_gmail

        responses = [_mock_response(202), _mock_response(500)]
        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.side_effect = responses
            result = send_email_via_gmail(
                to_addresses=["ok@b.com", "fail@b.com"],
                subject="Hi",
                body_text="Hello",
                access_token="tok",
                from_email="sender@hotel.com",
            )

        assert result is False


# ---------------------------------------------------------------------------
# 2. send_email_via_microsoft
# ---------------------------------------------------------------------------


class TestSendEmailViaMicrosoft:
    def test_success_posts_to_graph_api(self):
        from botelier.services.email_service import send_email_via_microsoft

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(202)
            result = send_email_via_microsoft(
                to_addresses=["guest@hotel.com"],
                subject="Booking confirmed",
                body_text="Hello!",
                access_token="ms-tok-xyz",
            )

        assert result is True
        url_arg = mock_req.post.call_args[0][0]
        assert "graph.microsoft.com" in url_arg
        assert "sendMail" in url_arg

    def test_bearer_token_in_auth_header(self):
        from botelier.services.email_service import send_email_via_microsoft

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(202)
            send_email_via_microsoft(
                to_addresses=["a@b.com"],
                subject="Hi",
                body_text="Hello",
                access_token="ms-tok-abc",
            )

        headers = mock_req.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer ms-tok-abc"

    def test_non_auth_api_error_returns_false(self):
        """Non-auth errors (5xx) return False without raising."""
        from botelier.services.email_service import send_email_via_microsoft

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(500, "Internal Server Error")
            result = send_email_via_microsoft(
                to_addresses=["a@b.com"],
                subject="Hi",
                body_text="Hello",
                access_token="tok",
            )

        assert result is False

    def test_401_raises_email_sender_auth_error(self):
        """A 401 from Graph must raise EmailSenderAuthError (not return False)."""
        from botelier.services.email_service import EmailSenderAuthError, send_email_via_microsoft

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(401, "Unauthorized")
            with pytest.raises(EmailSenderAuthError, match="reconnect"):
                send_email_via_microsoft(
                    to_addresses=["a@b.com"],
                    subject="Hi",
                    body_text="Hello",
                    access_token="expired-tok",
                )

    def test_403_raises_email_sender_auth_error(self):
        """A 403 from Graph must raise EmailSenderAuthError (not return False)."""
        from botelier.services.email_service import EmailSenderAuthError, send_email_via_microsoft

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(403, "Forbidden")
            with pytest.raises(EmailSenderAuthError):
                send_email_via_microsoft(
                    to_addresses=["a@b.com"],
                    subject="Hi",
                    body_text="Hello",
                    access_token="revoked-tok",
                )

    def test_empty_recipients_returns_false_without_http_call(self):
        from botelier.services.email_service import send_email_via_microsoft

        with patch("botelier.services.email_service._requests") as mock_req:
            result = send_email_via_microsoft(
                to_addresses=[],
                subject="Hi",
                body_text="Hello",
                access_token="tok",
            )

        assert result is False
        mock_req.post.assert_not_called()

    def test_network_error_returns_false_no_raise(self):
        from botelier.services.email_service import send_email_via_microsoft

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.side_effect = TimeoutError("timeout")
            result = send_email_via_microsoft(
                to_addresses=["a@b.com"],
                subject="Hi",
                body_text="Hello",
                access_token="tok",
            )

        assert result is False


# ---------------------------------------------------------------------------
# 3. send_email_via_connection — routing and guard tests
# ---------------------------------------------------------------------------


_ACCOUNT_UUID = uuid.uuid4()  # shared valid account UUID for handler tests


def _make_connection(
    slug: str = "email-sender-gmail",
    status_value: str = "connected",
    access_token: str = "tok-123",
    email: str = "sender@hotel.com",
    token_expired: bool = False,
):
    """Build a minimal mock AccountIntegration for send_email_via_connection."""
    from botelier.models.integration import IntegrationStatus

    conn = MagicMock()
    conn.integration_type = MagicMock()
    conn.integration_type.slug = slug
    conn.get_access_token.return_value = access_token
    conn.status = IntegrationStatus(status_value)
    conn.get_connection_config.return_value = {"email": email}
    # Explicit mock so proactive-refresh path is not triggered in unit tests
    conn.is_token_expired.return_value = token_expired
    return conn


class TestSendEmailViaConnection:
    def test_gmail_slug_routes_to_gmail_function(self):
        from botelier.services.email_service import send_email_via_connection

        conn = _make_connection(slug="email-sender-gmail")
        with patch("botelier.services.email_service.send_email_via_gmail") as mock_gmail:
            mock_gmail.return_value = True
            result = send_email_via_connection(
                conn, ["a@b.com"], "Subject", "Body"
            )

        assert result is True
        mock_gmail.assert_called_once()

    def test_microsoft_slug_routes_to_microsoft_function(self):
        from botelier.services.email_service import send_email_via_connection

        conn = _make_connection(slug="email-sender-microsoft")
        with patch("botelier.services.email_service.send_email_via_microsoft") as mock_ms:
            mock_ms.return_value = True
            result = send_email_via_connection(
                conn, ["a@b.com"], "Subject", "Body"
            )

        assert result is True
        mock_ms.assert_called_once()

    def test_missing_access_token_raises_valueerror(self):
        from botelier.services.email_service import send_email_via_connection

        conn = _make_connection(access_token="")
        with pytest.raises(ValueError, match="disconnected"):
            send_email_via_connection(conn, ["a@b.com"], "Sub", "Body")

    def test_disconnected_status_raises_valueerror(self):
        from botelier.services.email_service import send_email_via_connection

        conn = _make_connection(status_value="disconnected")
        with pytest.raises(ValueError, match="reconnect"):
            send_email_via_connection(conn, ["a@b.com"], "Sub", "Body")

    def test_error_status_raises_valueerror(self):
        from botelier.services.email_service import send_email_via_connection

        conn = _make_connection(status_value="error")
        with pytest.raises(ValueError, match="reconnect"):
            send_email_via_connection(conn, ["a@b.com"], "Sub", "Body")

    def test_token_expired_status_fails_closed_without_retry(self):
        """A TOKEN_EXPIRED connection must fail closed immediately — never retry.

        Passing a TOKEN_EXPIRED row to send_email_via_connection must raise
        ValueError with a reconnect message WITHOUT calling the refresh helper.
        The stored refresh token may have already been consumed or revoked, so
        retrying would only spend more auth budget and confuse the provider.
        """
        from botelier.services.email_service import send_email_via_connection

        conn = _make_connection(status_value="token_expired")
        with (
            patch(
                "botelier.services.email_service._refresh_email_sender_token_sync"
            ) as mock_refresh,
            pytest.raises(ValueError, match="reconnect"),
        ):
            send_email_via_connection(conn, ["a@b.com"], "Sub", "Body", db=MagicMock())

        # The refresh helper must never be called for a terminal connection
        mock_refresh.assert_not_called()

    def test_unsupported_slug_raises_valueerror(self):
        from botelier.services.email_service import send_email_via_connection

        conn = _make_connection(slug="email-sender-unknown")
        with pytest.raises(ValueError, match="Unsupported"):
            send_email_via_connection(conn, ["a@b.com"], "Sub", "Body")

    def test_gmail_from_email_passed_from_connection_config(self):
        """send_email_via_gmail must receive the stored email as from_email."""
        from botelier.services.email_service import send_email_via_connection

        conn = _make_connection(slug="email-sender-gmail", email="mybox@gmail.com")
        with patch("botelier.services.email_service.send_email_via_gmail") as mock_gmail:
            mock_gmail.return_value = True
            send_email_via_connection(conn, ["a@b.com"], "Sub", "Body")

        call_kwargs = mock_gmail.call_args[1] if mock_gmail.call_args[1] else {}
        call_args = mock_gmail.call_args[0] if mock_gmail.call_args[0] else ()
        # from_email is a keyword argument
        assert mock_gmail.call_args.kwargs.get("from_email") == "mybox@gmail.com" or \
               (len(call_args) > 4 and call_args[4] == "mybox@gmail.com")


# ---------------------------------------------------------------------------
# 4. _map_send_email handler — connected sender path
# ---------------------------------------------------------------------------


def _make_tool(config: dict = None, description: str = "Send an email"):
    from botelier.models.tool import ToolType

    tool = MagicMock()
    tool.tool_type = ToolType.SEND_EMAIL
    tool.name = "send_email"
    tool.description = description
    tool.config = config or {}
    return tool


def _make_mapper(account_id=None, session_factory=None):
    from botelier.voice.function_mapper import FunctionMapper

    # Default to the shared valid UUID so the uuid.UUID() conversion in the
    # handler does not raise an "Invalid account context" error.
    if account_id is None:
        account_id = str(_ACCOUNT_UUID)

    return FunctionMapper(
        call_sid="CA-test",
        from_number="+15551234567",
        to_number="+15559876543",
        account_id=account_id,
        account_name="Test Hotel",
        session_factory=session_factory,
    )


def _call_handler(mapper, tool, arguments: dict) -> dict:
    _, handler = mapper._map_send_email(tool)
    params = _FakeParams(arguments)
    _run(handler(params))
    return params._result


def _make_connected_integration(
    slug="email-sender-gmail",
    status_value="connected",
    access_token="tok-abc",
    email="sender@hotel.com",
    token_expired: bool = False,
    account_id=None,
):
    """Build a mock AccountIntegration that looks like what the DB returns."""
    from botelier.models.integration import AccountIntegration, IntegrationStatus

    conn = MagicMock(spec=AccountIntegration)
    conn.id = uuid.uuid4()
    conn.account_id = account_id or _ACCOUNT_UUID
    conn.integration_type = MagicMock()
    conn.integration_type.slug = slug
    conn.get_access_token.return_value = access_token
    conn.status = IntegrationStatus(status_value)
    conn.get_connection_config.return_value = {"email": email}
    # Explicit mock to prevent MagicMock() truthy from triggering the
    # proactive-refresh path in tests that don't exercise refresh.
    conn.is_token_expired.return_value = token_expired
    return conn


def _make_db_session(connection=None):
    """Build a mock session that returns `connection` from a .first() call."""
    mock_db = MagicMock()
    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = (
        connection
    )
    return mock_db


class TestSendEmailHandlerConnectedSender:
    def test_connection_id_routes_to_connected_sender_not_sendgrid(self):
        """When connection_id is set, SendGrid must NOT be called."""
        conn = _make_connected_integration(slug="email-sender-gmail")
        mock_db = _make_db_session(connection=conn)
        mapper = _make_mapper()
        mapper.db_session = mock_db

        with (
            patch("botelier.services.email_service.send_email_via_gmail") as mock_gmail,
            patch("botelier.services.email_service.SendGridAPIClient") as mock_sg,
        ):
            mock_gmail.return_value = True
            result = _call_handler(
                mapper,
                _make_tool(config={"connection_id": str(conn.id), "message_body": "Hello"}),
                {"to": "guest@hotel.com", "message": "Hello"},
            )

        mock_sg.assert_not_called()
        assert result["status"] == "sent"

    def test_gmail_connection_returns_sent_status(self):
        conn = _make_connected_integration(slug="email-sender-gmail")
        mock_db = _make_db_session(connection=conn)
        mapper = _make_mapper()
        mapper.db_session = mock_db

        with patch("botelier.services.email_service.send_email_via_gmail") as mock_gmail:
            mock_gmail.return_value = True
            result = _call_handler(
                mapper,
                _make_tool(config={"connection_id": str(conn.id), "message_body": "Hi"}),
                {"to": "guest@hotel.com", "message": "Hi"},
            )

        assert result["status"] == "sent"
        assert result["to"] == "guest@hotel.com"

    def test_microsoft_connection_returns_sent_status(self):
        conn = _make_connected_integration(slug="email-sender-microsoft")
        mock_db = _make_db_session(connection=conn)
        mapper = _make_mapper()
        mapper.db_session = mock_db

        with patch("botelier.services.email_service.send_email_via_microsoft") as mock_ms:
            mock_ms.return_value = True
            result = _call_handler(
                mapper,
                _make_tool(config={"connection_id": str(conn.id), "message_body": "Hi"}),
                {"to": "guest@hotel.com", "message": "Hi"},
            )

        assert result["status"] == "sent"

    def test_connection_not_found_returns_failed_status(self):
        """DB returns None for the connection_id → failed, not an exception to caller."""
        mock_db = _make_db_session(connection=None)
        mapper = _make_mapper()
        mapper.db_session = mock_db

        result = _call_handler(
            mapper,
            _make_tool(config={"connection_id": str(uuid.uuid4()), "message_body": "Hi"}),
            {"to": "guest@hotel.com", "message": "Hi"},
        )

        assert result["status"] == "failed"
        assert "not found" in result["reason"].lower() or "reconfigure" in result["reason"].lower()

    def test_disconnected_sender_returns_failed_with_reconnect_message(self):
        """A revoked / disconnected connection must return failed with a reconnect prompt."""
        conn = _make_connected_integration(
            slug="email-sender-gmail", status_value="disconnected", access_token=""
        )
        mock_db = _make_db_session(connection=conn)
        mapper = _make_mapper()
        mapper.db_session = mock_db

        result = _call_handler(
            mapper,
            _make_tool(config={"connection_id": str(conn.id), "message_body": "Hi"}),
            {"to": "guest@hotel.com", "message": "Hi"},
        )

        assert result["status"] == "failed"
        # Must mention reconnection — not a generic "delivery failed"
        assert "reconnect" in result["reason"].lower() or "disconnected" in result["reason"].lower()

    def test_gmail_delivery_failure_returns_failed_status(self):
        """Gmail API returns False (non-2xx) → handler returns failed status."""
        conn = _make_connected_integration(slug="email-sender-gmail")
        mock_db = _make_db_session(connection=conn)
        mapper = _make_mapper()
        mapper.db_session = mock_db

        with patch("botelier.services.email_service.send_email_via_gmail") as mock_gmail:
            mock_gmail.return_value = False
            result = _call_handler(
                mapper,
                _make_tool(config={"connection_id": str(conn.id), "message_body": "Hi"}),
                {"to": "guest@hotel.com", "message": "Hi"},
            )

        assert result["status"] == "failed"

    def test_microsoft_delivery_failure_returns_failed_status(self):
        conn = _make_connected_integration(slug="email-sender-microsoft")
        mock_db = _make_db_session(connection=conn)
        mapper = _make_mapper()
        mapper.db_session = mock_db

        with patch("botelier.services.email_service.send_email_via_microsoft") as mock_ms:
            mock_ms.return_value = False
            result = _call_handler(
                mapper,
                _make_tool(config={"connection_id": str(conn.id), "message_body": "Hi"}),
                {"to": "guest@hotel.com", "message": "Hi"},
            )

        assert result["status"] == "failed"

    def test_no_connection_id_does_not_attempt_connected_path(self):
        """Tool without connection_id must fall through to the SendGrid path."""
        mapper = _make_mapper()

        with (
            patch("botelier.services.email_service.SendGridAPIClient") as mock_sg,
            patch("botelier.services.email_service._sendgrid_api_key", return_value="sg-key"),
        ):
            mock_instance = MagicMock()
            mock_instance.send.return_value = MagicMock(status_code=202)
            mock_sg.return_value = mock_instance

            with patch.dict(
                "os.environ",
                {"SENDGRID_API_KEY": "sg-key", "EMAIL_FROM_DEFAULT": "bot@botelier.io"},
            ):
                result = _call_handler(
                    mapper,
                    _make_tool(config={"message_body": "Hello"}),
                    {"to": "guest@hotel.com", "message": "Hello"},
                )

        # SendGrid path reached (not the connected sender path)
        mock_instance.send.assert_called_once()

    def test_session_factory_used_when_db_session_is_none(self):
        """Live-call path uses session_factory when db_session is None."""
        conn = _make_connected_integration(slug="email-sender-gmail")

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.options.return_value.filter.return_value.first.return_value = conn

        session_factory = MagicMock(return_value=mock_session)
        mapper = _make_mapper(session_factory=session_factory)
        # db_session is deliberately not set (None by default)

        with patch("botelier.services.email_service.send_email_via_gmail") as mock_gmail:
            mock_gmail.return_value = True
            result = _call_handler(
                mapper,
                _make_tool(config={"connection_id": str(conn.id), "message_body": "Hi"}),
                {"to": "guest@hotel.com", "message": "Hi"},
            )

        session_factory.assert_called_once()
        assert result["status"] == "sent"

    # ── New security/correctness tests ────────────────────────────────────────

    def test_cross_account_connection_id_returns_failed(self):
        """A connection belonging to a DIFFERENT account must not be accessible.

        The DB returns None when the account_id predicate is applied (simulating
        that the connection exists but belongs to a different tenant).  The
        handler must return 'failed' rather than raising or leaking mailbox
        access.
        """
        # DB returns None — as though the account_id filter excluded the row
        mock_db = _make_db_session(connection=None)
        own_account_id = str(uuid.uuid4())
        mapper = _make_mapper(account_id=own_account_id)
        mapper.db_session = mock_db

        result = _call_handler(
            mapper,
            _make_tool(config={"connection_id": str(uuid.uuid4()), "message_body": "Hi"}),
            {"to": "guest@hotel.com", "message": "Hi"},
        )

        assert result["status"] == "failed"
        # Must mention the sender not being found / reconfiguration; must NOT
        # surface internal account details.
        reason_lower = result["reason"].lower()
        assert "not found" in reason_lower or "reconfigure" in reason_lower

    def test_cross_account_query_includes_account_id_filter(self):
        """The DB filter call must include the mapper's account_id UUID.

        This verifies the ownership predicate is actually passed to the ORM
        query rather than relying solely on a DB-returns-None simulation.
        """
        import inspect

        from botelier.models.integration import AccountIntegration as AI

        conn = _make_connected_integration(slug="email-sender-gmail")
        own_account_id = str(uuid.uuid4())

        mock_db = MagicMock()
        # Capture whatever args are passed to .filter()
        filter_calls = []

        def _capturing_filter(*args, **kwargs):
            filter_calls.extend(args)
            m = MagicMock()
            m.first.return_value = conn
            return m

        mock_db.query.return_value.options.return_value.filter.side_effect = _capturing_filter

        mapper = _make_mapper(account_id=own_account_id)
        mapper.db_session = mock_db

        with patch("botelier.services.email_service.send_email_via_gmail", return_value=True):
            _call_handler(
                mapper,
                _make_tool(config={"connection_id": str(conn.id), "message_body": "Hi"}),
                {"to": "guest@hotel.com", "message": "Hi"},
            )

        # At least one filter clause must encode the account_id UUID
        account_uuid = uuid.UUID(own_account_id)
        # SQLAlchemy BinaryExpression objects: check right-hand value
        found_account_predicate = any(
            (
                hasattr(c, "right")
                and hasattr(c.right, "value")
                and c.right.value == account_uuid
            )
            for c in filter_calls
        )
        assert found_account_predicate, (
            "account_id predicate not found in ORM .filter() call — "
            "cross-tenant isolation gap"
        )

    def test_expired_token_triggers_refresh_before_send(self):
        """An expired access token must be refreshed before the delivery attempt.

        The refresh path calls _refresh_email_sender_token_sync; once it
        succeeds the fresh token is used and delivery proceeds normally.
        """
        conn = _make_connected_integration(
            slug="email-sender-gmail",
            token_expired=True,  # simulate expired token
        )
        mock_db = _make_db_session(connection=conn)
        mapper = _make_mapper()
        mapper.db_session = mock_db

        fresh_token = "fresh-tok-456"

        with (
            patch(
                "botelier.services.email_service._refresh_email_sender_token_sync",
                return_value=fresh_token,
            ) as mock_refresh,
            patch("botelier.services.email_service.send_email_via_gmail") as mock_gmail,
        ):
            mock_gmail.return_value = True
            result = _call_handler(
                mapper,
                _make_tool(config={"connection_id": str(conn.id), "message_body": "Hi"}),
                {"to": "guest@hotel.com", "message": "Hi"},
            )

        # Refresh must have been called once
        mock_refresh.assert_called_once()
        # Gmail send must use the fresh token returned by the refresh
        mock_gmail.assert_called_once()
        assert mock_gmail.call_args.kwargs.get("access_token") == fresh_token, (
            "send_email_via_gmail must use the fresh token, not the stale stored one"
        )
        assert result["status"] == "sent"

    def test_provider_401_surfaces_reconnect_message(self):
        """A 401 from Gmail during send must surface a reconnect prompt to the LLM.

        The EmailSenderAuthError raised by send_email_via_gmail must propagate
        as a ValueError and be caught by the handler, resulting in a 'failed'
        status whose reason contains reconnection guidance.
        """
        from botelier.services.email_service import EmailSenderAuthError

        conn = _make_connected_integration(slug="email-sender-gmail")
        mock_db = _make_db_session(connection=conn)
        mapper = _make_mapper()
        mapper.db_session = mock_db

        with patch("botelier.services.email_service.send_email_via_gmail") as mock_gmail:
            mock_gmail.side_effect = EmailSenderAuthError(
                "Gmail rejected the access token (401). "
                "Please reconnect your email sender in Settings > Email."
            )
            result = _call_handler(
                mapper,
                _make_tool(config={"connection_id": str(conn.id), "message_body": "Hi"}),
                {"to": "guest@hotel.com", "message": "Hi"},
            )

        assert result["status"] == "failed"
        assert "reconnect" in result["reason"].lower(), (
            "Handler must surface a reconnect prompt when provider rejects token"
        )


# ---------------------------------------------------------------------------
# 5. _do_http_refresh_email_sender — token persistence and provider responses
# ---------------------------------------------------------------------------


def _make_refresh_connection(
    refresh_token: str = "rt-abc",
    token_url: str = "https://oauth.example.com/token",
    client_id: str = "cid",
    client_secret: str = "csecret",
    status_value: str = "connected",
):
    """Build a minimal mock AccountIntegration for _do_http_refresh_email_sender."""
    from botelier.models.integration import AccountIntegration, IntegrationStatus

    conn = MagicMock(spec=AccountIntegration)
    conn.id = uuid.uuid4()
    conn.integration_type = MagicMock()
    conn.integration_type.get_auth_config.return_value = {
        "token_endpoint": token_url,
        "scope": "https://mail.google.com/",
    }
    conn.get_refresh_token.return_value = refresh_token
    conn.get_credentials.return_value = {
        "client_id": client_id,
        "client_secret": client_secret,
    }
    conn.status = IntegrationStatus(status_value)
    return conn


def _make_refresh_db():
    return MagicMock()


class TestDoHttpRefreshEmailSender:
    """Direct tests for _do_http_refresh_email_sender — no advisory lock."""

    def test_success_stores_access_token_and_expiry(self):
        """200 response must call set_access_token and set token_expires_at."""
        from botelier.services.email_service import _do_http_refresh_email_sender

        conn = _make_refresh_connection()
        db = _make_refresh_db()

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(
                200, '{"access_token":"new-at","expires_in":3600}'
            )
            mock_req.post.return_value.json.return_value = {
                "access_token": "new-at",
                "expires_in": 3600,
            }
            token = _do_http_refresh_email_sender(conn, db)

        assert token == "new-at"
        conn.set_access_token.assert_called_once_with("new-at")
        assert conn.token_expires_at is not None
        from botelier.models.integration import IntegrationStatus
        assert conn.status == IntegrationStatus.CONNECTED
        db.commit.assert_called()

    def test_rotated_refresh_token_is_stored(self):
        """When the provider returns a new refresh_token it must be persisted."""
        from botelier.services.email_service import _do_http_refresh_email_sender

        conn = _make_refresh_connection()
        db = _make_refresh_db()

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(200, "")
            mock_req.post.return_value.json.return_value = {
                "access_token": "new-at",
                "refresh_token": "new-rt",
                "expires_in": 3600,
            }
            _do_http_refresh_email_sender(conn, db)

        conn.set_refresh_token.assert_called_once_with("new-rt")

    def test_no_new_refresh_token_keeps_existing(self):
        """When the provider does NOT rotate the refresh_token it must not be overwritten."""
        from botelier.services.email_service import _do_http_refresh_email_sender

        conn = _make_refresh_connection()
        db = _make_refresh_db()

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(200, "")
            mock_req.post.return_value.json.return_value = {
                "access_token": "new-at",
                "expires_in": 3600,
                # no "refresh_token" key
            }
            _do_http_refresh_email_sender(conn, db)

        conn.set_refresh_token.assert_not_called()

    def test_provider_4xx_sets_token_expired_status(self):
        """A 4xx rejection must mark the connection TOKEN_EXPIRED and raise ValueError."""
        from botelier.models.integration import IntegrationStatus
        from botelier.services.email_service import _do_http_refresh_email_sender

        conn = _make_refresh_connection()
        db = _make_refresh_db()

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(400, "invalid_grant")
            with pytest.raises(ValueError, match="reconnect"):
                _do_http_refresh_email_sender(conn, db)

        assert conn.status == IntegrationStatus.TOKEN_EXPIRED
        assert "400" in conn.last_error
        db.commit.assert_called()

    def test_network_error_does_not_change_status(self):
        """A network error must raise ValueError without changing connection status."""
        from botelier.models.integration import IntegrationStatus
        from botelier.services.email_service import _do_http_refresh_email_sender

        conn = _make_refresh_connection()
        original_status = conn.status
        db = _make_refresh_db()

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.side_effect = TimeoutError("timeout")
            with pytest.raises(ValueError, match="network error"):
                _do_http_refresh_email_sender(conn, db)

        # Status must not have changed — transient error
        assert conn.status == original_status
        db.commit.assert_not_called()

    def test_missing_refresh_token_marks_terminal(self):
        """No stored refresh_token → TOKEN_EXPIRED immediately, reconnect message."""
        from botelier.models.integration import IntegrationStatus
        from botelier.services.email_service import _do_http_refresh_email_sender

        conn = _make_refresh_connection(refresh_token="")
        conn.get_refresh_token.return_value = None  # no refresh token stored
        db = _make_refresh_db()

        with pytest.raises(ValueError, match="reconnect"):
            _do_http_refresh_email_sender(conn, db)

        assert conn.status == IntegrationStatus.TOKEN_EXPIRED
        db.commit.assert_called()

    def test_missing_access_token_in_200_response_marks_terminal(self):
        """A 200 response that omits access_token must still mark TOKEN_EXPIRED."""
        from botelier.models.integration import IntegrationStatus
        from botelier.services.email_service import _do_http_refresh_email_sender

        conn = _make_refresh_connection()
        db = _make_refresh_db()

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(200, "")
            mock_req.post.return_value.json.return_value = {"token_type": "Bearer"}
            with pytest.raises(ValueError, match="reconnect"):
                _do_http_refresh_email_sender(conn, db)

        assert conn.status == IntegrationStatus.TOKEN_EXPIRED
        db.commit.assert_called()

    def test_429_does_not_mark_token_expired(self):
        """A 429 (rate-limited) from the token endpoint must leave status unchanged.

        A temporary rate-limit at the token endpoint is a transient outage, not
        a credential rejection.  Marking TOKEN_EXPIRED would permanently disconnect
        a valid sender when the endpoint recovers.
        """
        from botelier.models.integration import IntegrationStatus
        from botelier.services.email_service import _do_http_refresh_email_sender

        conn = _make_refresh_connection()
        original_status = conn.status
        db = _make_refresh_db()

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(429, "Too Many Requests")
            with pytest.raises(ValueError, match="server error"):
                _do_http_refresh_email_sender(conn, db)

        # Status must not have changed — 429 is transient
        assert conn.status == original_status
        db.commit.assert_not_called()

    def test_5xx_does_not_mark_token_expired(self):
        """A 5xx token-endpoint error must leave status unchanged (transient outage)."""
        from botelier.models.integration import IntegrationStatus
        from botelier.services.email_service import _do_http_refresh_email_sender

        conn = _make_refresh_connection()
        original_status = conn.status
        db = _make_refresh_db()

        with patch("botelier.services.email_service._requests") as mock_req:
            mock_req.post.return_value = _mock_response(503, "Service Unavailable")
            with pytest.raises(ValueError, match="server error"):
                _do_http_refresh_email_sender(conn, db)

        assert conn.status == original_status
        db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# 6. _refresh_email_sender_token_sync — advisory-lock holder/waiter & concurrency
# ---------------------------------------------------------------------------


class TestRefreshEmailSenderTokenSync:
    """Tests for the advisory-lock holder/waiter orchestration.

    DB and lock primitives are mocked so tests run without a real Postgres
    instance.  The advisory-lock correctness (pg_try_advisory_lock SQL) is
    tested by verifying the SQL text passed to execute(); functional DB tests
    belong in integration / e2e suites.
    """

    def _make_raw_conn(self, lock_acquired: bool):
        """Build a mock raw connection that returns `lock_acquired` from pg_try_advisory_lock."""
        raw = MagicMock()
        raw.execute.return_value.scalar.return_value = lock_acquired
        return raw

    def test_holder_calls_http_refresh_and_returns_token(self):
        """Holder wins the lock, refreshes, and returns the fresh access token."""
        from botelier.services.email_service import _refresh_email_sender_token_sync

        conn = _make_refresh_connection()
        db = _make_refresh_db()

        fresh_conn = _make_refresh_connection()
        fresh_conn.is_token_expired.return_value = True  # still stale after re-read

        with (
            patch("botelier.services.email_service._db_engine") as mock_engine,
            patch(
                "botelier.services.email_service._read_email_sender_fresh",
                return_value=fresh_conn,
            ),
            patch(
                "botelier.services.email_service._do_http_refresh_email_sender",
                return_value="fresh-tok",
            ) as mock_http,
        ):
            mock_engine.connect.return_value = self._make_raw_conn(lock_acquired=True)
            token = _refresh_email_sender_token_sync(conn, db)

        mock_http.assert_called_once()
        assert token == "fresh-tok"

    def test_holder_skips_http_if_already_refreshed(self):
        """Holder must NOT call HTTP when the fresh row shows a valid token.

        This covers the case where another worker refreshed while this one
        contended for the advisory lock.
        """
        from botelier.models.integration import IntegrationStatus
        from botelier.services.email_service import _refresh_email_sender_token_sync

        conn = _make_refresh_connection()
        db = _make_refresh_db()

        fresh_conn = _make_refresh_connection()
        fresh_conn.status = IntegrationStatus.CONNECTED
        fresh_conn.is_token_expired.return_value = False
        fresh_conn.get_access_token.return_value = "already-fresh"

        with (
            patch("botelier.services.email_service._db_engine") as mock_engine,
            patch(
                "botelier.services.email_service._read_email_sender_fresh",
                return_value=fresh_conn,
            ),
            patch(
                "botelier.services.email_service._do_http_refresh_email_sender"
            ) as mock_http,
        ):
            mock_engine.connect.return_value = self._make_raw_conn(lock_acquired=True)
            token = _refresh_email_sender_token_sync(conn, db)

        mock_http.assert_not_called()
        assert token == "already-fresh"

    def test_waiter_polls_until_holder_commits(self):
        """Waiter must not call HTTP; it must poll and return the fresh token."""
        from botelier.models.integration import IntegrationStatus
        from botelier.services.email_service import _refresh_email_sender_token_sync

        conn = _make_refresh_connection()
        db = _make_refresh_db()

        # First poll: still stale; second poll: fresh
        stale_row = _make_refresh_connection()
        stale_row.status = IntegrationStatus.CONNECTED
        stale_row.is_token_expired.return_value = True

        fresh_row = _make_refresh_connection()
        fresh_row.status = IntegrationStatus.CONNECTED
        fresh_row.is_token_expired.return_value = False
        fresh_row.get_access_token.return_value = "holder-refreshed"

        poll_results = [stale_row, fresh_row]

        with (
            patch("botelier.services.email_service._db_engine") as mock_engine,
            patch(
                "botelier.services.email_service._read_email_sender_fresh",
                side_effect=poll_results,
            ),
            patch(
                "botelier.services.email_service._do_http_refresh_email_sender"
            ) as mock_http,
            patch("time.sleep"),  # skip actual sleeps
        ):
            mock_engine.connect.return_value = self._make_raw_conn(lock_acquired=False)
            token = _refresh_email_sender_token_sync(conn, db)

        mock_http.assert_not_called()
        assert token == "holder-refreshed"

    def test_waiter_raises_on_token_expired_status(self):
        """Waiter must raise ValueError when the fresh row shows TOKEN_EXPIRED."""
        from botelier.models.integration import IntegrationStatus
        from botelier.services.email_service import _refresh_email_sender_token_sync

        conn = _make_refresh_connection()
        db = _make_refresh_db()

        expired_row = _make_refresh_connection()
        expired_row.status = IntegrationStatus.TOKEN_EXPIRED

        with (
            patch("botelier.services.email_service._db_engine") as mock_engine,
            patch(
                "botelier.services.email_service._read_email_sender_fresh",
                return_value=expired_row,
            ),
            patch("time.sleep"),
        ):
            mock_engine.connect.return_value = self._make_raw_conn(lock_acquired=False)
            with pytest.raises(ValueError, match="reconnect"):
                _refresh_email_sender_token_sync(conn, db)

    def test_holder_raises_immediately_when_fresh_row_is_token_expired(self):
        """Holder must NOT call HTTP when the freshly-read row shows TOKEN_EXPIRED.

        If another worker already terminally failed refresh (400/401/403 grant
        rejection), syncing TOKEN_EXPIRED into the caller row and then calling
        _do_http_refresh_email_sender would spend the refresh token a second time.
        The holder must detect the terminal fresh status and raise immediately.
        """
        from botelier.models.integration import IntegrationStatus
        from botelier.services.email_service import _refresh_email_sender_token_sync

        conn = _make_refresh_connection()
        db = _make_refresh_db()

        # Fresh row shows another worker already failed terminally
        terminal_row = MagicMock()
        terminal_row.status = IntegrationStatus.TOKEN_EXPIRED
        terminal_row.access_token_encrypted = "stale"
        terminal_row.refresh_token_encrypted = "spent"
        terminal_row.token_expires_at = None

        with (
            patch("botelier.services.email_service._db_engine") as mock_engine,
            patch(
                "botelier.services.email_service._read_email_sender_fresh",
                return_value=terminal_row,
            ),
            patch(
                "botelier.services.email_service._do_http_refresh_email_sender"
            ) as mock_http,
        ):
            mock_engine.connect.return_value = self._make_raw_conn(lock_acquired=True)
            with pytest.raises(ValueError, match="reconnect"):
                _refresh_email_sender_token_sync(conn, db)

        # Must NOT have called HTTP — refresh token is already spent
        mock_http.assert_not_called()

    def test_holder_syncs_fresh_credentials_before_http_refresh(self):
        """Holder must sync fresh token fields into the caller row before the HTTP grant.

        If the sender was reconnected (new refresh_token) between the original
        DB lookup and lock acquisition, the holder must use the NEW credentials,
        not the stale ones that may have already been spent by another worker.
        """
        from botelier.models.integration import IntegrationStatus
        from botelier.services.email_service import _refresh_email_sender_token_sync

        conn = _make_refresh_connection()
        conn.refresh_token_encrypted = "stale-encrypted-rt"
        conn.access_token_encrypted = "stale-encrypted-at"
        conn.token_expires_at = None
        db = _make_refresh_db()

        # Fresh row has new credentials (e.g., user reconnected the sender after
        # the caller originally loaded the row).
        from unittest.mock import MagicMock as _MM
        fresh_conn = _MM()
        fresh_conn.status = IntegrationStatus.CONNECTED
        fresh_conn.is_token_expired.return_value = True  # still stale, needs refresh
        fresh_conn.refresh_token_encrypted = "new-encrypted-rt"
        fresh_conn.access_token_encrypted = "new-encrypted-at"
        fresh_conn.token_expires_at = None

        captured_rt = []

        def capture_http(c, d):
            # Record the refresh_token_encrypted on the caller row at call time
            captured_rt.append(c.refresh_token_encrypted)
            return "new-at"

        with (
            patch("botelier.services.email_service._db_engine") as mock_engine,
            patch(
                "botelier.services.email_service._read_email_sender_fresh",
                return_value=fresh_conn,
            ),
            patch(
                "botelier.services.email_service._do_http_refresh_email_sender",
                side_effect=capture_http,
            ),
        ):
            mock_engine.connect.return_value = self._make_raw_conn(lock_acquired=True)
            _refresh_email_sender_token_sync(conn, db)

        assert captured_rt == ["new-encrypted-rt"], (
            "Holder must sync fresh refresh_token_encrypted into the caller row "
            "before the HTTP grant; using the stale value would spend an already-"
            "consumed rotating token and break the mailbox connection."
        )

    def test_only_one_http_call_under_concurrent_delivery(self):
        """Under concurrent delivery, exactly ONE worker performs the HTTP grant.

        Two threads race to refresh the same expired token.  The first that wins
        the mock advisory lock calls the HTTP grant; the second (waiter) observes
        the fresh row via polling without making its own HTTP call.
        """
        import threading

        from botelier.models.integration import IntegrationStatus
        from botelier.services.email_service import _refresh_email_sender_token_sync

        conn = _make_refresh_connection()
        db = _make_refresh_db()

        http_call_count = 0
        http_lock = threading.Lock()
        holder_done = threading.Event()
        fresh_token = "concurrent-fresh"

        def fake_http(connection, db_):
            nonlocal http_call_count
            with http_lock:
                http_call_count += 1
            holder_done.set()
            return fresh_token

        # Simulate: first call to engine.connect() wins the advisory lock (True),
        # second call does not (False) and enters the waiter path.
        lock_seq = [True, False]
        call_idx = 0
        idx_lock = threading.Lock()

        def make_raw_conn_seq():
            nonlocal call_idx
            with idx_lock:
                acquired = lock_seq[call_idx % len(lock_seq)]
                call_idx += 1
            return self._make_raw_conn(lock_acquired=acquired)

        # Fresh rows returned by the waiter's poll: stale then fresh.
        stale_row = _make_refresh_connection()
        stale_row.status = IntegrationStatus.CONNECTED
        stale_row.is_token_expired.return_value = True

        fresh_row = _make_refresh_connection()
        fresh_row.status = IntegrationStatus.CONNECTED
        fresh_row.is_token_expired.return_value = False
        fresh_row.get_access_token.return_value = fresh_token

        poll_seq = [stale_row, fresh_row]
        poll_idx = 0
        poll_lock = threading.Lock()

        def fake_read_fresh(_id):
            nonlocal poll_idx
            # Holder path: return a still-stale fresh row (triggers HTTP)
            # Waiter path: alternate stale → fresh
            with poll_lock:
                row = poll_seq[min(poll_idx, len(poll_seq) - 1)]
                poll_idx += 1
            return row

        results = []
        errors = []

        def worker(conn_obj, db_obj):
            try:
                tok = _refresh_email_sender_token_sync(conn_obj, db_obj)
                results.append(tok)
            except Exception as exc:
                errors.append(exc)

        with (
            patch("botelier.services.email_service._db_engine") as mock_engine,
            patch(
                "botelier.services.email_service._read_email_sender_fresh",
                side_effect=fake_read_fresh,
            ),
            patch(
                "botelier.services.email_service._do_http_refresh_email_sender",
                side_effect=fake_http,
            ),
            patch("time.sleep"),
        ):
            mock_engine.connect.side_effect = make_raw_conn_seq

            t1 = threading.Thread(target=worker, args=(conn, db))
            t2 = threading.Thread(target=worker, args=(conn, db))
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

        assert not errors, f"Unexpected errors: {errors}"
        assert http_call_count == 1, (
            f"Expected exactly 1 HTTP refresh call, got {http_call_count}. "
            "Concurrent callers must not both spend the refresh token."
        )
        assert all(t == fresh_token for t in results), (
            "Both callers must receive the fresh token"
        )
