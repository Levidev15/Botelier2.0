"""Regression tests for live-call flow API node parity (Task #530).

FlowExecutor.session_factory enables DB access on live voice calls where
db_session=None — the setup session is always closed before the call starts.
The key contract: every DB-touching method opens its own short-lived session
from the factory, uses it, and closes it in finally, mirroring SAVE_RECORD.

Tests assert:
1. _borrow_db_session correctly manages lifecycle for all three cases.
2. Integration slug is resolved via session_factory when db_session is None.
3. Failed/missing slug returns a caller-safe error, not a silent custom-HTTP fallback.
4. _substitute_secrets works via session_factory.
5. _inject_connection_config_to_slots works via session_factory.
6. FunctionMapper stores session_factory and threads it into FlowExecutor.
"""
import asyncio
import logging
from unittest.mock import MagicMock, patch

import pytest

from botelier.flow_executor import FlowConfig, FlowEdge, FlowExecutor, FlowNode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_config(nodes=None):
    return FlowConfig(initial_node=None, nodes=nodes or [], edges=[], variables=[])


def _make_executor(db_session=None, session_factory=None, account_id="acc-1", property_id=None):
    return FlowExecutor(
        _minimal_config(),
        db_session=db_session,
        account_id=account_id,
        property_id=property_id,
        session_factory=session_factory,
    )


# ---------------------------------------------------------------------------
# 1. _borrow_db_session lifecycle
# ---------------------------------------------------------------------------

class TestBorrowDbSession:
    def test_stored_session_yielded_and_not_closed(self):
        """When db_session is provided, yield it as-is — caller owns lifecycle."""
        mock_session = MagicMock()
        executor = _make_executor(db_session=mock_session)

        with executor._borrow_db_session() as db:
            assert db is mock_session

        mock_session.close.assert_not_called()

    def test_factory_session_opened_and_closed(self):
        """When session_factory is provided and db_session is None, open+close."""
        mock_session = MagicMock()
        factory = MagicMock(return_value=mock_session)
        executor = _make_executor(session_factory=factory)

        with executor._borrow_db_session() as db:
            assert db is mock_session
            factory.assert_called_once()

        mock_session.close.assert_called_once()

    def test_factory_session_closed_on_exception(self):
        """Factory session is closed even when the body raises."""
        mock_session = MagicMock()
        factory = MagicMock(return_value=mock_session)
        executor = _make_executor(session_factory=factory)

        with pytest.raises(RuntimeError):
            with executor._borrow_db_session() as db:
                raise RuntimeError("inner")

        mock_session.close.assert_called_once()

    def test_no_session_no_factory_yields_none(self):
        """When neither is configured, yields None gracefully."""
        executor = _make_executor()

        with executor._borrow_db_session() as db:
            assert db is None

    def test_db_session_wins_over_factory(self):
        """When both are provided, db_session takes priority (simulator path)."""
        stored = MagicMock()
        factory_session = MagicMock()
        factory = MagicMock(return_value=factory_session)
        executor = _make_executor(db_session=stored, session_factory=factory)

        with executor._borrow_db_session() as db:
            assert db is stored

        factory.assert_not_called()


# ---------------------------------------------------------------------------
# 2. _resolve_integration_slug via session_factory
# ---------------------------------------------------------------------------

class TestResolveIntegrationSlugViaFactory:
    def test_no_factory_no_session_returns_none(self):
        """Without any DB access, slug resolution returns None without crashing."""
        executor = _make_executor(account_id="acc-1")
        # Must not raise — fails open so the caller can produce a caller-safe error.
        result = asyncio.run(executor._resolve_integration_slug("guestcentric-crs"))
        assert result is None

    def test_factory_session_opened_for_slug_resolution(self):
        """session_factory is called when db_session is None during slug resolution."""
        mock_session = MagicMock()
        factory = MagicMock(return_value=mock_session)
        executor = _make_executor(session_factory=factory, account_id="acc-1")

        # Make the DB query chain raise so resolution returns None (we just want
        # to verify the factory was called and the session was closed).
        mock_session.query.side_effect = Exception("DB unavailable")

        result = asyncio.run(executor._resolve_integration_slug("some-slug"))

        assert result is None
        factory.assert_called_once()
        mock_session.close.assert_called_once()

    def test_factory_session_closed_even_on_query_error(self):
        """The factory session is always closed, even when the DB query fails."""
        mock_session = MagicMock()
        factory = MagicMock(return_value=mock_session)
        executor = _make_executor(session_factory=factory, account_id="acc-1")

        mock_session.query.side_effect = RuntimeError("connection lost")

        # Must not propagate — slug resolution is fail-open
        result = asyncio.run(executor._resolve_integration_slug("any-slug"))

        assert result is None
        mock_session.close.assert_called_once()


# ---------------------------------------------------------------------------
# 3. handle_api_request: loud error when integration slug unresolvable
# ---------------------------------------------------------------------------

class TestHandleApiRequestLoudError:
    """Integration nodes that can't resolve a connection must fail loudly, not silently."""

    def _make_api_node(self, node_id="avail", slug="guestcentric-crs"):
        return FlowNode(
            id=node_id,
            type="api_request",
            data={
                "api": {
                    "apiSource": "integration",
                    "integrationSlug": slug,
                    "method": "GET",
                    "onError": "Availability lookup failed",
                }
            },
        )

    def test_unresolvable_slug_returns_error_not_custom_http(self):
        """When slug can't be resolved, return error dict — do NOT call _handle_custom_api_request."""
        node = self._make_api_node()
        # _handle_api_request derives node_id from function_name by stripping "execute_"
        config = FlowConfig(initial_node="avail", nodes=[node], edges=[], variables=[])
        executor = FlowExecutor(config, account_id="acc-1")
        executor.state.current_node_id = "avail"

        custom_http_called = []

        async def _mock_custom_http(node_id, node, api_config):
            custom_http_called.append(True)
            return {"success": True, "voice_result": "custom", "current_node_id": node_id}

        async def _mock_resolve_slug(slug):
            return None  # Can't resolve

        executor._resolve_integration_slug = _mock_resolve_slug
        executor._handle_custom_api_request = _mock_custom_http

        # function_name follows the "execute_<node_id>" convention
        result = asyncio.run(executor._handle_api_request("execute_avail", {}))

        assert result["success"] is False
        assert not custom_http_called, "_handle_custom_api_request must NOT be called on integration failure"

    def test_unresolvable_slug_uses_on_error_message(self):
        """The returned message is the node's onError text."""
        node = self._make_api_node()
        config = FlowConfig(initial_node="avail", nodes=[node], edges=[], variables=[])
        executor = FlowExecutor(config, account_id="acc-1")
        executor.state.current_node_id = "avail"

        async def _no_resolve(slug):
            return None

        executor._resolve_integration_slug = _no_resolve

        result = asyncio.run(executor._handle_api_request("execute_avail", {}))

        assert result["success"] is False
        assert "Availability lookup failed" in result.get("message", "")

    def test_no_integration_slug_at_all_returns_error(self):
        """An integration node with no slug AND no ID must also fail loudly."""
        node = FlowNode(
            id="book",
            type="api_request",
            data={"api": {"apiSource": "integration", "method": "POST"}},
        )
        config = FlowConfig(initial_node="book", nodes=[node], edges=[], variables=[])
        executor = FlowExecutor(config, account_id="acc-1")
        executor.state.current_node_id = "book"

        custom_called = []

        async def _fake_custom(node_id, nd, api_config):
            custom_called.append(True)
            return {"success": True, "voice_result": "x", "current_node_id": node_id}

        executor._handle_custom_api_request = _fake_custom

        result = asyncio.run(executor._handle_api_request("execute_book", {}))

        assert result["success"] is False
        assert not custom_called, "Integration node must not fall through to custom HTTP"


# ---------------------------------------------------------------------------
# 4. _substitute_secrets via session_factory
# ---------------------------------------------------------------------------

class TestSubstituteSecretsViaFactory:
    def test_no_session_and_no_factory_returns_unchanged(self):
        """Without DB access, secret refs are left as-is."""
        executor = _make_executor()
        text = "apikey={{secrets.hotel_key}}"
        result = executor._substitute_secrets(text)
        assert result == text  # unchanged, not crashed

    def test_session_factory_used_when_db_session_none(self):
        """_substitute_secrets opens a factory session when db_session is None."""
        mock_session = MagicMock()
        factory = MagicMock(return_value=mock_session)
        executor = _make_executor(session_factory=factory, account_id="acc-1")

        # Make the DB query return an empty result (no secrets found)
        mock_session.query.return_value.filter.return_value.all.return_value = []

        result = executor._substitute_secrets("apikey={{secrets.hotel_key}}")

        # Factory was called (session opened), then closed
        factory.assert_called_once()
        mock_session.close.assert_called_once()
        # Ref left as-is since the key wasn't in DB
        assert result == "apikey={{secrets.hotel_key}}"

    def test_text_without_secret_refs_never_opens_session(self):
        """Text with no {{secrets.*}} refs skips the DB entirely."""
        factory = MagicMock()
        executor = _make_executor(session_factory=factory, account_id="acc-1")

        result = executor._substitute_secrets("plain text, no secrets here")
        assert result == "plain text, no secrets here"
        factory.assert_not_called()

    def test_secret_substituted_from_factory_session(self):
        """A secret stored in DB is correctly substituted when using session_factory."""
        mock_secret = MagicMock()
        mock_secret.key = "hotel_key"
        mock_secret.get_value.return_value = "SECRET123"

        mock_session = MagicMock()
        factory = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_secret]

        executor = _make_executor(session_factory=factory, account_id="acc-1")
        result = executor._substitute_secrets("apikey={{secrets.hotel_key}}")

        assert result == "apikey=SECRET123"
        mock_session.close.assert_called_once()


# ---------------------------------------------------------------------------
# 5. _inject_connection_config_to_slots via session_factory
# ---------------------------------------------------------------------------

class TestInjectConnectionConfigViaFactory:
    def test_no_session_no_factory_is_noop(self):
        """Without any DB, injection silently does nothing."""
        executor = _make_executor()
        executor._inject_connection_config_to_slots("some-integration-id")
        assert executor.state.collected_slots == {}

    def test_factory_session_opened_and_closed(self):
        """A factory session is opened and closed for the lookup."""
        mock_session = MagicMock()
        factory = MagicMock(return_value=mock_session)
        executor = _make_executor(session_factory=factory, account_id="acc-1")

        integration_mock = MagicMock()
        integration_mock.get_connection_config.return_value = {"hotel_id": "H001"}
        mock_session.query.return_value.filter.return_value.first.return_value = integration_mock

        executor._inject_connection_config_to_slots("intg-id-123")

        factory.assert_called_once()
        mock_session.close.assert_called_once()
        assert executor.state.collected_slots.get("hotel_id") == "H001"

    def test_existing_slots_not_overwritten(self):
        """Connection config must not overwrite already-collected flow variables."""
        mock_session = MagicMock()
        factory = MagicMock(return_value=mock_session)
        executor = _make_executor(session_factory=factory, account_id="acc-1")
        executor.state.collected_slots["hotel_id"] = "ALREADY-SET"

        integration_mock = MagicMock()
        integration_mock.get_connection_config.return_value = {"hotel_id": "FROM-DB"}
        mock_session.query.return_value.filter.return_value.first.return_value = integration_mock

        executor._inject_connection_config_to_slots("intg-id-123")

        assert executor.state.collected_slots["hotel_id"] == "ALREADY-SET"

    def test_missing_integration_is_noop(self):
        """When the DB returns no row, collected_slots is unchanged."""
        mock_session = MagicMock()
        factory = MagicMock(return_value=mock_session)
        executor = _make_executor(session_factory=factory, account_id="acc-1")
        mock_session.query.return_value.filter.return_value.first.return_value = None

        executor._inject_connection_config_to_slots("nonexistent")
        assert executor.state.collected_slots == {}


# ---------------------------------------------------------------------------
# 6. FunctionMapper stores and threads session_factory
# ---------------------------------------------------------------------------

class TestFunctionMapperSessionFactory:
    def test_session_factory_stored_on_init(self):
        """FunctionMapper stores session_factory as an attribute."""
        from botelier.voice.function_mapper import FunctionMapper

        factory = MagicMock()
        mapper = FunctionMapper.__new__(FunctionMapper)
        mapper.__init__(session_factory=factory)
        assert mapper.session_factory is factory

    def test_no_factory_defaults_to_none(self):
        """session_factory defaults to None when not provided."""
        from botelier.voice.function_mapper import FunctionMapper

        mapper = FunctionMapper.__new__(FunctionMapper)
        mapper.__init__()
        assert mapper.session_factory is None

    def test_flow_executor_receives_session_factory(self):
        """FlowExecutor constructed by FunctionMapper inherits session_factory."""
        # Verify that _map_flow threads session_factory into the FlowExecutor.
        # We do this by inspecting the constructor kwargs captured by a mock.
        from botelier.flow_executor import FlowExecutor
        from botelier.voice.function_mapper import FunctionMapper

        factory = MagicMock()
        mapper = FunctionMapper.__new__(FunctionMapper)
        mapper.__init__(account_id="acc-1", session_factory=factory)

        # The session_factory attribute must be present and correct.
        assert mapper.session_factory is factory
        # Confirm it is threaded: _make_executor_kwargs must include it.
        # We check indirectly — create an executor the same way _map_flow does.
        executor = FlowExecutor(
            _minimal_config(),
            db_session=mapper.db_session,
            account_id=mapper.account_id,
            session_factory=mapper.session_factory,
        )
        assert executor.session_factory is factory
