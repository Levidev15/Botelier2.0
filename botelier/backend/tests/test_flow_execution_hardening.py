"""Regression tests for live-call flow execution hardening (Task #534).

Covers the fixes made after auditing "is the LLM following the flow
correctly end-to-end" for a real call that hit ~10s of dead air after
confirm_details, a duplicate GET, and a phantom flow_sessions row:

1. Universal direct-speech guarantee — SET_VARIABLE/ROUTER surface the
   destination node's configured message with speak_directly=True instead
   of relying on the LLM to keep talking on its own.
2. Exhausted-flow guardrail — a node with no outgoing edge marks the flow
   complete, and the per-turn node context tells the model not to invent
   an outcome once the graph is over.
3. GET dedup guard — a GET API node called twice with identical arguments
   within the dedup window returns the cached result instead of re-firing.
4. flow_sessions lifecycle — CallLogger only abandons rows still "active";
   a session that already legitimately reached "complete" is left alone.

No OpenAI or live DB access: flow position is driven directly via the
public handler methods (mirrors the pattern in test_flow_function_gating.py).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from botelier.flow_executor import FlowExecutor, parse_flow_config


def _flow_with_set_variable_into_message():
    """sync(set_variable) -> note(message, static) -> end (no outgoing edge)."""
    config = {
        "initial_node": "sync",
        "variables": [],
        "nodes": [
            {
                "id": "sync",
                "type": "set_variable",
                "data": {"setVariable": {"variableKey": "flag", "value": "yes"}},
            },
            {
                "id": "note",
                "type": "message",
                "data": {"message": "Great, all set.", "deliveryMode": "static"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "sync", "target": "note"},
        ],
    }
    return FlowExecutor(parse_flow_config(config))


def _flow_with_router_into_message():
    config = {
        "initial_node": "router1",
        "variables": [],
        "nodes": [
            {
                "id": "router1",
                "type": "router",
                "data": {
                    "router": {
                        "variable": "choice",
                        "options": [{"id": "opt_a", "value": "a", "label": "A"}],
                    }
                },
            },
            {"id": "note", "type": "message", "data": {"message": "Routed here."}},
        ],
        "edges": [
            {
                "id": "e1",
                "source": "router1",
                "target": "note",
                "source_handle": "opt_a",
            },
        ],
    }
    return FlowExecutor(parse_flow_config(config))


def _flow_dead_end_message():
    """A MESSAGE node with no outgoing edge — the flow simply ends here."""
    config = {
        "initial_node": "note",
        "variables": [],
        "nodes": [
            {"id": "note", "type": "message", "data": {"message": "That's all I can do."}},
        ],
        "edges": [],
    }
    return FlowExecutor(parse_flow_config(config))


class TestDirectSpeechGuarantee:
    @pytest.mark.asyncio
    async def test_set_variable_surfaces_destination_message(self):
        executor = _flow_with_set_variable_into_message()
        result = await executor._handle_set_variable("set_var_sync", {})

        assert result["speak_directly"] is True
        assert result["message"] == "Great, all set."
        # Static delivery mode must also set speak_exactly so the mapper
        # doesn't let the LLM paraphrase operator-authored copy.
        assert result["speak_exactly"] == "Great, all set."
        assert result["current_node_id"] == "note"

    @pytest.mark.asyncio
    async def test_router_surfaces_destination_message(self):
        executor = _flow_with_router_into_message()
        result = await executor._handle_router("route_router1", {"choice": "a"})

        assert result["speak_directly"] is True
        assert result["message"] == "Routed here."
        assert result["current_node_id"] == "note"

    @pytest.mark.asyncio
    async def test_set_variable_without_destination_message_stays_silent(self):
        """A destination node with nothing configured (e.g. an API node with
        no onSuccess) must NOT set speak_directly — there is nothing real to
        say, so the internal-only debug message must never reach TTS."""
        config = {
            "initial_node": "sync",
            "variables": [],
            "nodes": [
                {
                    "id": "sync",
                    "type": "set_variable",
                    "data": {"setVariable": {"variableKey": "flag", "value": "yes"}},
                },
                {"id": "api", "type": "api_request", "data": {"api": {}}},
            ],
            "edges": [{"id": "e1", "source": "sync", "target": "api"}],
        }
        executor = FlowExecutor(parse_flow_config(config))
        result = await executor._handle_set_variable("set_var_sync", {})

        assert "speak_directly" not in result
        assert result["message"] == "Set flag to yes"


class TestExhaustedFlowGuardrail:
    """Covers the *structural* "graph has nothing further from here" signal.

    This is deliberately a separate flag (``graph_exhausted``) from
    ``is_complete``, which means "a terminal action actually executed" and
    gates end_call idempotency — see TestTerminalTransitionExecution below
    for why conflating the two was a real regression caught in completion
    review.
    """

    def test_advance_to_marks_graph_exhausted_when_no_outgoing_edge(self):
        """Arriving at a node with no outgoing edge (however the flow got
        there — a handler's own advance_to call, exactly as in production)
        must mark the graph exhausted."""
        executor = _flow_dead_end_message()
        assert executor.state.graph_exhausted is False  # not yet arrived
        executor.state.advance_to("note")
        assert executor.state.graph_exhausted is True
        # Landing here structurally does NOT mean a terminal action executed.
        assert executor.state.is_complete is False

    def test_advance_to_leaves_incomplete_mid_graph(self):
        """Advancing onto a node that still has a real outgoing edge must
        NOT mark the graph exhausted."""
        executor = _flow_with_set_variable_into_message()
        executor.state.advance_to("sync")
        assert executor.state.graph_exhausted is False

    @pytest.mark.asyncio
    async def test_node_context_warns_llm_not_to_invent_outcomes(self):
        executor = _flow_dead_end_message()
        executor.state.advance_to("note")
        context = executor.get_current_node_context()
        assert context is not None
        assert "FLOW COMPLETE" in context
        assert "Do NOT claim" in context

    def test_end_node_does_not_get_generic_flow_complete_line(self):
        """END/TRANSFER already carry their own explicit call-to-action —
        the generic guardrail line must not double up on them."""
        config = {
            "initial_node": "start",
            "variables": [],
            "nodes": [
                {"id": "start", "type": "message", "data": {"message": "hi"}},
                {"id": "end1", "type": "end", "data": {}},
            ],
            "edges": [{"id": "e1", "source": "start", "target": "end1"}],
        }
        executor = FlowExecutor(parse_flow_config(config))
        executor.state.advance_to("end1")
        assert executor.state.graph_exhausted is True
        context = executor.get_current_node_context() or ""
        assert "FLOW COMPLETE: This flow has reached the end" not in context


class TestTerminalTransitionExecution:
    """Regression coverage for the completion-review finding: a silent
    advance into END/TRANSFER must actually execute that terminal action
    (invoke the end/transfer callback, return action="end"/"transfer") —
    not just speak the destination's configured message and stall.

    Before this fix, FlowState.advance_to() marked ``is_complete=True`` the
    instant it landed on ANY node with no outgoing edge, including END/
    TRANSFER — before the handler that actually fires the terminal callback
    ever ran. _handle_end_call's own idempotency guard then swallowed itself
    as a "duplicate" and returned an empty message, so the call never
    actually ended. All node-handler call sites route through the shared
    ``_maybe_execute_terminal_transition`` helper, so exercising it directly
    (plus one call site each for SET_VARIABLE/ROUTER/CONFIRMATION) covers
    every wiring point, including SAVE_RECORD's identical call site.
    """

    def _flow_set_variable_into_end(self):
        config = {
            "initial_node": "sync",
            "variables": [],
            "nodes": [
                {
                    "id": "sync",
                    "type": "set_variable",
                    "data": {"setVariable": {"variableKey": "flag", "value": "yes"}},
                },
                {"id": "end1", "type": "end", "data": {"closingMessage": "Goodbye now!"}},
            ],
            "edges": [{"id": "e1", "source": "sync", "target": "end1"}],
        }
        return FlowExecutor(parse_flow_config(config))

    def _flow_set_variable_into_transfer(self):
        config = {
            "initial_node": "sync",
            "variables": [],
            "nodes": [
                {
                    "id": "sync",
                    "type": "set_variable",
                    "data": {"setVariable": {"variableKey": "flag", "value": "yes"}},
                },
                {
                    "id": "xfer1",
                    "type": "transfer",
                    "data": {
                        "transfer": {
                            "phoneNumber": "+15551234567",
                            "preTransferMessage": "One moment, transferring you now.",
                            "transferMode": "warm",
                        }
                    },
                },
            ],
            "edges": [{"id": "e1", "source": "sync", "target": "xfer1"}],
        }
        return FlowExecutor(parse_flow_config(config))

    @pytest.mark.asyncio
    async def test_set_variable_into_end_actually_ends_the_call(self):
        executor = self._flow_set_variable_into_end()
        end_calls = []
        executor.end_call_callback = AsyncMock(side_effect=lambda msg: end_calls.append(msg))

        result = await executor._handle_set_variable("set_var_sync", {})

        assert result["action"] == "end"
        assert result["message"] == "Goodbye now!"
        assert end_calls == ["Goodbye now!"]
        assert executor.state.is_complete is True

    @pytest.mark.asyncio
    async def test_set_variable_into_transfer_actually_dials_out(self):
        executor = self._flow_set_variable_into_transfer()
        transfer_calls = []

        async def _capture_transfer(phone, reason, transfer_mode="warm"):
            transfer_calls.append((phone, transfer_mode))

        executor.transfer_callback = _capture_transfer

        result = await executor._handle_set_variable("set_var_sync", {})

        assert result["action"] == "transfer"
        assert result["target"] == "+15551234567"
        assert result["message"] == "One moment, transferring you now."
        assert transfer_calls == [("+15551234567", "warm")]
        assert executor.state.transfer_requested is True

    @pytest.mark.asyncio
    async def test_router_into_end_actually_ends_the_call(self):
        config = {
            "initial_node": "router1",
            "variables": [],
            "nodes": [
                {
                    "id": "router1",
                    "type": "router",
                    "data": {
                        "router": {
                            "variable": "choice",
                            "options": [{"id": "opt_a", "value": "a", "label": "A"}],
                        }
                    },
                },
                {"id": "end1", "type": "end", "data": {"closingMessage": "All done, bye!"}},
            ],
            "edges": [
                {"id": "e1", "source": "router1", "target": "end1", "source_handle": "opt_a"},
            ],
        }
        executor = FlowExecutor(parse_flow_config(config))
        end_calls = []
        executor.end_call_callback = AsyncMock(side_effect=lambda msg: end_calls.append(msg))

        result = await executor._handle_router("route_router1", {"choice": "a"})

        assert result["action"] == "end"
        assert result["message"] == "All done, bye!"
        assert end_calls == ["All done, bye!"]

    @pytest.mark.asyncio
    async def test_confirmation_confirmed_into_transfer_actually_dials_out(self):
        config = {
            "initial_node": "confirm1",
            "variables": [],
            "nodes": [
                {
                    "id": "confirm1",
                    "type": "confirmation",
                    "data": {
                        "confirmation": {
                            "summaryTemplate": "Booking a room.",
                            "confirmPrompt": "Shall I proceed?",
                        }
                    },
                },
                {
                    "id": "xfer1",
                    "type": "transfer",
                    "data": {
                        "transfer": {
                            "phoneNumber": "+15559998888",
                            "preTransferMessage": "Connecting you now.",
                        }
                    },
                },
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": "confirm1",
                    "target": "xfer1",
                    "source_handle": "confirmed",
                },
            ],
        }
        executor = FlowExecutor(parse_flow_config(config))
        transfer_calls = []

        async def _capture_transfer(phone, reason, transfer_mode="warm"):
            transfer_calls.append(phone)

        executor.transfer_callback = _capture_transfer

        result = await executor._handle_confirmation("confirm_confirm1", {"confirmed": True})

        assert result["action"] == "transfer"
        assert result["target"] == "+15559998888"
        assert transfer_calls == ["+15559998888"]

    @pytest.mark.asyncio
    async def test_end_call_idempotency_guard_does_not_self_trigger_on_arrival(self):
        """The regression itself: merely landing on an END node (graph_exhausted)
        must never look like "already ended" to _handle_end_call's own
        duplicate-call guard. A direct, subsequent LLM-invoked end_call_<id>
        call for the SAME node must still be swallowed as a true duplicate
        (the callback fires exactly once)."""
        executor = self._flow_set_variable_into_end()
        end_calls = []
        executor.end_call_callback = AsyncMock(side_effect=lambda msg: end_calls.append(msg))

        first = await executor._handle_set_variable("set_var_sync", {})
        assert first["action"] == "end"
        assert first["message"] == "Goodbye now!"

        # A genuine duplicate (e.g. a stray second LLM turn) must still be a no-op.
        second = await executor._handle_end_call("end_call_end1", {})
        assert second["message"] == ""
        assert len(end_calls) == 1


class TestGetDedupGuard:
    @pytest.mark.asyncio
    async def test_identical_get_within_window_returns_cached_result(self):
        config = {
            "initial_node": "api1",
            "variables": [],
            "nodes": [
                {
                    "id": "api1",
                    "type": "api_request",
                    "data": {"api": {"method": "GET", "apiSource": "custom"}},
                }
            ],
            "edges": [],
        }
        executor = FlowExecutor(parse_flow_config(config))

        call_count = 0

        async def _fake_custom(node_id, node, api_config):
            nonlocal call_count
            call_count += 1
            return {"success": True, "message": f"result-{call_count}", "action": None}

        executor._handle_custom_api_request = _fake_custom

        r1 = await executor._handle_api_request("execute_api1", {"room": "101"})
        r2 = await executor._handle_api_request("execute_api1", {"room": "101"})

        assert call_count == 1
        assert r1["message"] == "result-1"
        assert r2["message"] == "result-1"

    @pytest.mark.asyncio
    async def test_get_with_different_arguments_is_not_deduped(self):
        config = {
            "initial_node": "api1",
            "variables": [],
            "nodes": [
                {
                    "id": "api1",
                    "type": "api_request",
                    "data": {"api": {"method": "GET", "apiSource": "custom"}},
                }
            ],
            "edges": [],
        }
        executor = FlowExecutor(parse_flow_config(config))

        call_count = 0

        async def _fake_custom(node_id, node, api_config):
            nonlocal call_count
            call_count += 1
            return {"success": True, "message": f"result-{call_count}", "action": None}

        executor._handle_custom_api_request = _fake_custom

        await executor._handle_api_request("execute_api1", {"room": "101"})
        await executor._handle_api_request("execute_api1", {"room": "102"})

        assert call_count == 2


class TestFlowSessionAbandonment:
    def test_only_active_rows_are_marked_abandoned(self):
        from botelier.services.call_logger import CallLogger

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db.execute.return_value = mock_result

        logger_svc = CallLogger(mock_db)
        logger_svc._abandon_active_flow_sessions("CA123")

        mock_db.execute.assert_called_once()
        args, kwargs_or_params = mock_db.execute.call_args[0], mock_db.execute.call_args[1]
        # The bound param dict is the second positional arg to db.execute(text, params).
        bound_params = mock_db.execute.call_args[0][1]
        assert bound_params == {"session_key": "CA123"}
        # Query text must scope the UPDATE to status='active' only.
        query_text = str(mock_db.execute.call_args[0][0])
        assert "status = 'active'" in query_text
        assert "'abandoned'" in query_text

    def test_no_op_when_no_active_rows_found(self):
        from botelier.services.call_logger import CallLogger

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_db.execute.return_value = mock_result

        logger_svc = CallLogger(mock_db)
        # Must not raise even when nothing was updated.
        logger_svc._abandon_active_flow_sessions("CA999")
        mock_db.execute.assert_called_once()
