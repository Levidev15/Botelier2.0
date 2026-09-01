"""Tests for API REQUEST node success/error edge routing (Task #588).

The frontend flow editor renders two outgoing handles for API REQUEST and CAPABILITY
nodes: ``success`` and ``error``.  This module verifies the backend routes through
those handles correctly.

Verifies that:
1. _resolve_api_edge returns the success-handle node on success,
   and the error-handle node on failure.
2. Falls back to the first unlabeled edge when the requested handle is absent,
   so flows drawn without explicit handle labels continue to work.
3. Custom URL success advances state to the 'success' node.
4. Custom URL failure advances state to the 'error' node (not stuck).
5. Custom URL failure with no 'error' edge falls back to the first edge.
6. An 'error' edge drawn AFTER a 'success' edge is still correctly selected on
   failure (fallback cannot accidentally return the success edge).
7. Exception inside ActionExecutor also routes to the 'error' node.
8. Integration API failure and exception routes to the 'error' node.
9. Payment exception routes to the 'error' node.
"""

import asyncio
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from botelier.flow_executor import FlowExecutor, parse_flow_config


# ---------------------------------------------------------------------------
# Flow config builders
# ---------------------------------------------------------------------------


def _api_flow_with_handles(
    *,
    api_node_id: str = "api",
    success_target: str = "s_node",
    failed_target: str = "f_node",
    api_source: str = "custom",
) -> dict:
    """Flow: start → api_request node → success/failed branches."""
    return {
        "initial_node": "start",
        "variables": [],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {
                "id": api_node_id,
                "type": "api_request",
                "data": {
                    "api": {
                        "apiSource": api_source,
                        "method": "GET",
                        "url": "https://example.com/test",
                        "onSuccess": "Great!",
                        "onError": "Sorry, something went wrong.",
                    }
                },
            },
            {"id": success_target, "type": "message", "data": {"message": "success path"}},
            {"id": failed_target, "type": "message", "data": {"message": "failure path"}},
        ],
        "edges": [
            {"id": "e0", "source": "start", "target": api_node_id},
            {
                "id": "e1",
                "source": api_node_id,
                "target": success_target,
                "sourceHandle": "success",
            },
            {
                "id": "e2",
                "source": api_node_id,
                "target": failed_target,
                "sourceHandle": "error",
            },
        ],
    }


def _api_flow_single_edge(
    *,
    api_node_id: str = "api",
    next_target: str = "next",
) -> dict:
    """Flow: start → api_request → next (single unlabeled edge, no success/failed handles)."""
    return {
        "initial_node": "start",
        "variables": [],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {
                "id": api_node_id,
                "type": "api_request",
                "data": {
                    "api": {
                        "apiSource": "custom",
                        "method": "GET",
                        "url": "https://example.com/test",
                        "onSuccess": "Done.",
                        "onError": "Error.",
                    }
                },
            },
            {"id": next_target, "type": "message", "data": {"message": "only way out"}},
        ],
        "edges": [
            {"id": "e0", "source": "start", "target": api_node_id},
            {"id": "e1", "source": api_node_id, "target": next_target},  # no sourceHandle
        ],
    }


def _executor_at(config_dict: dict, node_id: str) -> FlowExecutor:
    """Build a FlowExecutor positioned at node_id."""
    ex = FlowExecutor(parse_flow_config(config_dict))
    ex.state.current_node_id = node_id
    return ex


def _mock_action_response(*, success: bool) -> MagicMock:
    """Build a mock ActionExecutorResponse."""
    resp = MagicMock()
    resp.success = success
    resp.extracted_variables = {}
    if success:
        resp.voice_result = "Completed"
    else:
        resp.error_message = "API call failed"
        resp.error_type = MagicMock()
        resp.error_type.value = "http_error"
        resp.status_code = 503
    return resp


def _attach_no_op_locks(executor: FlowExecutor) -> None:
    """Attach lightweight no-op stubs for the turn-lock and DB-session context managers.

    This lets us call _handle_custom_api_request without a real pipeline or DB.
    """

    @asynccontextmanager
    async def _no_lock():
        yield

    @contextmanager
    def _no_db():
        yield None

    executor._suspend_turn_lock = _no_lock
    executor._borrow_db_session = _no_db


# ---------------------------------------------------------------------------
# Unit tests for _resolve_api_edge (pure, no mocking)
# ---------------------------------------------------------------------------


class TestResolveApiEdge:
    """_resolve_api_edge selects the right outgoing edge by handle."""

    def test_success_handle_preferred_on_success(self):
        cfg = _api_flow_with_handles()
        ex = _executor_at(cfg, "api")
        node = ex._resolve_api_edge("api", success=True)
        assert node is not None
        assert node.id == "s_node"

    def test_error_handle_preferred_on_failure(self):
        """_resolve_api_edge selects the 'error' sourceHandle node on failure."""
        cfg = _api_flow_with_handles()
        ex = _executor_at(cfg, "api")
        node = ex._resolve_api_edge("api", success=False)
        assert node is not None
        assert node.id == "f_node"

    def test_falls_back_to_first_edge_when_success_handle_absent(self):
        """A flow with no 'success' label falls back to the first outgoing edge."""
        cfg = _api_flow_single_edge()
        ex = _executor_at(cfg, "api")
        node = ex._resolve_api_edge("api", success=True)
        assert node is not None
        assert node.id == "next"

    def test_falls_back_to_first_edge_when_error_handle_absent(self):
        """A flow with no 'error' label falls back to the first outgoing edge (not None)."""
        cfg = _api_flow_single_edge()
        ex = _executor_at(cfg, "api")
        node = ex._resolve_api_edge("api", success=False)
        assert node is not None
        assert node.id == "next"

    def test_error_edge_selected_even_when_success_edge_appears_first(self):
        """When the success edge is listed before the error edge in the graph,
        failure still selects the error node — not the success node via fallback."""
        cfg = {
            "initial_node": "start",
            "variables": [],
            "nodes": [
                {"id": "start", "type": "initial", "data": {}},
                {
                    "id": "api",
                    "type": "api_request",
                    "data": {"api": {"apiSource": "custom", "url": "https://x.com"}},
                },
                {"id": "s_node", "type": "message", "data": {"message": "ok"}},
                {"id": "e_node", "type": "message", "data": {"message": "fail"}},
            ],
            "edges": [
                {"id": "e0", "source": "start", "target": "api"},
                # success edge is FIRST in the list
                {"id": "e1", "source": "api", "target": "s_node", "sourceHandle": "success"},
                # error edge is SECOND
                {"id": "e2", "source": "api", "target": "e_node", "sourceHandle": "error"},
            ],
        }
        ex = _executor_at(cfg, "api")
        # On failure: must return the error node, not s_node (the first edge)
        node = ex._resolve_api_edge("api", success=False)
        assert node is not None
        assert node.id == "e_node", (
            "Fallback must not pick the 'success' edge when an 'error' edge exists "
            "even if the success edge appears first in the graph"
        )

    def test_returns_none_for_terminal_node_with_no_edges(self):
        """A node with no outgoing edges returns None — not a crash."""
        cfg = {
            "initial_node": "api",
            "variables": [],
            "nodes": [
                {
                    "id": "api",
                    "type": "api_request",
                    "data": {"api": {"apiSource": "custom", "url": "https://x.com"}},
                }
            ],
            "edges": [],
        }
        ex = _executor_at(cfg, "api")
        assert ex._resolve_api_edge("api", success=True) is None
        assert ex._resolve_api_edge("api", success=False) is None


# ---------------------------------------------------------------------------
# Custom URL routing via _handle_custom_api_request
# ---------------------------------------------------------------------------


class TestCustomUrlRouting:
    """Custom URL (apiSource=custom) routes via success/failed handles."""

    @pytest.mark.asyncio
    async def test_success_advances_to_success_node(self):
        cfg = _api_flow_with_handles()
        ex = _executor_at(cfg, "api")
        _attach_no_op_locks(ex)

        mock_resp = _mock_action_response(success=True)
        with patch(
            "botelier.services.action_executor.ActionExecutor.execute_and_log",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            result = await ex._handle_custom_api_request(
                "api", ex.flow_config._node_index["api"], {"apiSource": "custom", "url": "x"}
            )

        assert result["success"] is True
        assert result["current_node_id"] == "s_node"
        assert ex.state.current_node_id == "s_node"

    @pytest.mark.asyncio
    async def test_failure_advances_to_failed_node(self):
        """Failure routes to the 'failed' edge — executor is no longer stuck on the API node."""
        cfg = _api_flow_with_handles()
        ex = _executor_at(cfg, "api")
        _attach_no_op_locks(ex)

        mock_resp = _mock_action_response(success=False)
        with patch(
            "botelier.services.action_executor.ActionExecutor.execute_and_log",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            result = await ex._handle_custom_api_request(
                "api", ex.flow_config._node_index["api"], {"apiSource": "custom", "url": "x"}
            )

        assert result["success"] is False
        assert result["current_node_id"] == "f_node"
        # State must have advanced — the executor is not stuck on "api"
        assert ex.state.current_node_id == "f_node"

    @pytest.mark.asyncio
    async def test_failure_falls_back_to_first_edge_when_no_failed_handle(self):
        """When the flow has no 'failed' edge, failure falls back to the first edge, not stall."""
        cfg = _api_flow_single_edge()
        ex = _executor_at(cfg, "api")
        _attach_no_op_locks(ex)

        mock_resp = _mock_action_response(success=False)
        with patch(
            "botelier.services.action_executor.ActionExecutor.execute_and_log",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            result = await ex._handle_custom_api_request(
                "api", ex.flow_config._node_index["api"], {"apiSource": "custom", "url": "x"}
            )

        assert result["success"] is False
        # Falls back to the only outgoing edge ("next"), not stuck on "api"
        assert result["current_node_id"] == "next"
        assert ex.state.current_node_id == "next"

    @pytest.mark.asyncio
    async def test_exception_in_action_executor_routes_to_failed_node(self):
        """An unhandled ActionExecutor exception still routes to the 'failed' edge."""
        cfg = _api_flow_with_handles()
        ex = _executor_at(cfg, "api")
        _attach_no_op_locks(ex)

        with patch(
            "botelier.services.action_executor.ActionExecutor.execute_and_log",
            new_callable=AsyncMock,
            side_effect=RuntimeError("connection timeout"),
        ):
            result = await ex._handle_custom_api_request(
                "api", ex.flow_config._node_index["api"], {"apiSource": "custom", "url": "x"}
            )

        assert result["success"] is False
        assert result["current_node_id"] == "f_node"
        assert ex.state.current_node_id == "f_node"


# ---------------------------------------------------------------------------
# Integration API routing via _handle_integration_api_request (mocked)
# ---------------------------------------------------------------------------


class TestIntegrationApiRouting:
    """Integration API (apiSource=integration) failure routes to the 'failed' edge."""

    @pytest.mark.asyncio
    async def test_integration_failure_advances_to_failed_node(self):
        """When an integration call fails, executor moves to the 'failed' node.

        We call _handle_integration_api_request directly, mocking ActionExecutor
        and the per-call helpers so no DB or real HTTP is needed.
        """
        cfg = _api_flow_with_handles(api_source="integration")
        ex = _executor_at(cfg, "api")
        ex.account_id = "00000000-0000-0000-0000-000000000001"  # avoid early-return guard
        _attach_no_op_locks(ex)

        # Also stub _inject_connection_config_to_slots and _substitute_secrets
        # so the method doesn't need a DB or secrets store.
        ex._inject_connection_config_to_slots = lambda integration_id: None
        ex._substitute_secrets = lambda text: text or ""

        node = ex.flow_config._node_index["api"]
        api_config_dict = {
            "apiSource": "integration",
            "integrationId": "fake-int-id",
            "endpointId": "fake-ep",
            "method": "GET",
            "onSuccess": "OK",
            "onError": "Fail",
            "responseVariables": [],
        }
        node.data["api"] = api_config_dict

        # Failing ActionExecutorResponse — error_type only needs .value.
        mock_resp = MagicMock()
        mock_resp.success = False
        mock_resp.error_message = "Not authorized"
        mock_resp.error_type = MagicMock()
        mock_resp.error_type.value = "auth_error"
        mock_resp.status_code = 401

        with (
            patch(
                "botelier.services.action_executor.ActionExecutor.execute_and_log",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
            patch(
                "botelier.services.integration_client.get_llm_friendly_error_message",
                return_value="Not authorized",
            ),
        ):
            result = await ex._handle_integration_api_request("api", node, api_config_dict)

        assert result["success"] is False
        assert result["current_node_id"] == "f_node"
        assert ex.state.current_node_id == "f_node"

    @pytest.mark.asyncio
    async def test_integration_failure_carries_raw_error_detail(self):
        """The result dict must carry the raw provider error text separately from
        the LLM-facing `message`, so callers hear the (possibly generic) bridge
        while operators can see the real failure reason (Task #599)."""
        cfg = _api_flow_with_handles(api_source="integration")
        ex = _executor_at(cfg, "api")
        ex.account_id = "00000000-0000-0000-0000-000000000001"
        _attach_no_op_locks(ex)
        ex._inject_connection_config_to_slots = lambda integration_id: None
        ex._substitute_secrets = lambda text: text or ""

        node = ex.flow_config._node_index["api"]
        api_config_dict = {
            "apiSource": "integration",
            "integrationId": "fake-int-id",
            "endpointId": "fake-ep",
            "method": "GET",
            "onSuccess": "OK",
            "onError": "",  # blank — caller gets the generic fallback bridge
            "responseVariables": [],
        }
        node.data["api"] = api_config_dict

        mock_resp = MagicMock()
        mock_resp.success = False
        mock_resp.error_message = "Currency not supported"
        mock_resp.error_type = MagicMock()
        mock_resp.error_type.value = "validation_error"
        mock_resp.status_code = 422

        with (
            patch(
                "botelier.services.action_executor.ActionExecutor.execute_and_log",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
            patch(
                "botelier.services.integration_client.get_llm_friendly_error_message",
                return_value="There was an issue with the information provided: Currency not supported",
            ),
        ):
            result = await ex._handle_integration_api_request("api", node, api_config_dict)

        assert result["success"] is False
        assert result["status_code"] == 422
        assert result["error_type"] == "validation_error"
        # Raw underlying reason is preserved verbatim for operator-facing surfaces...
        assert result["error_detail"] == "Currency not supported"
        # ...distinct from the LLM/caller-facing wording in `message`.
        assert result["message"] != result["error_detail"]

    @pytest.mark.asyncio
    async def test_integration_exception_advances_to_failed_node(self):
        """An unhandled exception inside _handle_integration_api_request still routes
        to the 'failed' edge rather than leaving the executor stuck on the API node."""
        cfg = _api_flow_with_handles(api_source="integration")
        ex = _executor_at(cfg, "api")
        ex.account_id = "00000000-0000-0000-0000-000000000001"
        _attach_no_op_locks(ex)

        ex._inject_connection_config_to_slots = lambda integration_id: None
        ex._substitute_secrets = lambda text: text or ""

        node = ex.flow_config._node_index["api"]
        api_config_dict = {
            "apiSource": "integration",
            "integrationId": "fake-int-id",
            "endpointId": "fake-ep",
            "method": "GET",
            "onError": "Payment system error.",
            "responseVariables": [],
        }
        node.data["api"] = api_config_dict

        with patch(
            "botelier.services.action_executor.ActionExecutor.execute_and_log",
            new_callable=AsyncMock,
            side_effect=RuntimeError("stripe sdk timeout"),
        ):
            result = await ex._handle_integration_api_request("api", node, api_config_dict)

        assert result["success"] is False
        assert result["current_node_id"] == "f_node"
        assert ex.state.current_node_id == "f_node"


# ---------------------------------------------------------------------------
# Service-backed capability (payment) exception routing
# ---------------------------------------------------------------------------


class TestVoiceResultAutoSummaryFlag:
    """Task #601 — a raw extracted-data digest must never look like designer
    narration to FunctionMapper.  ``voice_result_is_auto_summary`` marks
    ``voice_result`` as LLM-context-only whenever it was auto-built from
    ``_build_api_voice_result`` (no ``responseInstructions`` configured), and
    False whenever it is genuine, designer-authored narration."""

    @pytest.mark.asyncio
    async def test_custom_api_no_response_instructions_flags_auto_summary(self):
        cfg = _api_flow_with_handles()
        ex = _executor_at(cfg, "api")
        _attach_no_op_locks(ex)

        node = ex.flow_config._node_index["api"]
        api_config_dict = dict(node.data["api"])
        node.data["api"] = api_config_dict  # no "responseInstructions" key

        mock_resp = MagicMock()
        mock_resp.success = True
        mock_resp.extracted_variables = {"room_price": [8000, 7500], "rooms_name": ["Double", "Family"]}

        with patch(
            "botelier.services.action_executor.ActionExecutor.execute_and_log",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            result = await ex._handle_custom_api_request("api", node, api_config_dict)

        assert result["success"] is True
        assert result["voice_result_is_auto_summary"] is True
        assert "Extracted data" in result["voice_result"]
        assert "room_price" in result["voice_result"]

    @pytest.mark.asyncio
    async def test_custom_api_with_response_instructions_not_flagged(self):
        """Designer-authored responseInstructions must never be flagged as an
        auto-summary — it is genuine caller-facing narration."""
        cfg = _api_flow_with_handles()
        ex = _executor_at(cfg, "api")
        _attach_no_op_locks(ex)

        node = ex.flow_config._node_index["api"]
        api_config_dict = dict(node.data["api"])
        api_config_dict["responseInstructions"] = "We found a great room for you."
        node.data["api"] = api_config_dict

        mock_resp = MagicMock()
        mock_resp.success = True
        mock_resp.extracted_variables = {"room_price": 8000}

        with patch(
            "botelier.services.action_executor.ActionExecutor.execute_and_log",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            result = await ex._handle_custom_api_request("api", node, api_config_dict)

        assert result["success"] is True
        assert result["voice_result_is_auto_summary"] is False
        assert result["voice_result"] == "We found a great room for you."

    @pytest.mark.asyncio
    async def test_integration_api_no_response_instructions_flags_auto_summary(self):
        cfg = _api_flow_with_handles(api_source="integration")
        ex = _executor_at(cfg, "api")
        ex.account_id = "00000000-0000-0000-0000-000000000001"
        _attach_no_op_locks(ex)
        ex._inject_connection_config_to_slots = lambda integration_id: None
        ex._substitute_secrets = lambda text: text or ""

        node = ex.flow_config._node_index["api"]
        api_config_dict = {
            "apiSource": "integration",
            "integrationId": "fake-int-id",
            "endpointId": "fake-ep",
            "method": "GET",
            "onSuccess": "Request completed successfully",
            "onError": "Fail",
            "responseVariables": [],
        }
        node.data["api"] = api_config_dict

        mock_resp = MagicMock()
        mock_resp.success = True
        mock_resp.extracted_variables = {"room_price": [8000, 7500], "rooms_name": ["Double", "Family"]}

        with patch(
            "botelier.services.action_executor.ActionExecutor.execute_and_log",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            result = await ex._handle_integration_api_request("api", node, api_config_dict)

        assert result["success"] is True
        assert result["voice_result_is_auto_summary"] is True
        assert "Extracted data" in result["voice_result"]


class TestServiceBackedCapabilityRouting:
    """Payment capability exception routes to the 'failed' edge, not stuck on node."""

    @pytest.mark.asyncio
    async def test_payment_exception_advances_to_failed_node(self):
        """A PaymentService exception routes to the 'failed' edge, not stuck on the node."""
        cfg = _api_flow_with_handles()
        ex = _executor_at(cfg, "api")
        _attach_no_op_locks(ex)

        node = ex.flow_config._node_index["api"]
        api_config_dict = {
            "apiSource": "capability",
            "capability": "collect_payment",
            "onError": "Payment failed. Please try again.",
        }

        with patch(
            "botelier.services.payments.PaymentService.collect_payment",
            side_effect=RuntimeError("stripe connection error"),
        ):
            result = await ex._handle_service_backed_capability(
                "api", node, api_config_dict, "collect_payment"
            )

        assert result["success"] is False
        assert result["current_node_id"] == "f_node"
        assert ex.state.current_node_id == "f_node"
