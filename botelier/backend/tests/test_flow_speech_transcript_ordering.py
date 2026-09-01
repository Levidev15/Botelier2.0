"""Task #598 — end-to-end: a flow-injected direct TTSSpeakFrame push must end
up in the correct chronological position in the saved transcript, even when
Pipecat's context aggregator commits it out of real-time order.

Root cause: FunctionMapper speaks several kinds of text directly via
TTSSpeakFrame instead of going through a normal LLM completion — the next
collection prompt, an API node's thinkingMessage, and API completion bridges
(onComplete/onError). None of these registered into CallHandler's
pending_responses capture buffer, the only source _extract_transcript uses to
anchor an assistant message to its real elapsed time. Without a real
timestamp, the raw committed context order (which the aggregator can delay
until the *next* real LLM completion) drove the transcript order instead,
occasionally placing the question after the caller's answer to it.

This module wires FunctionMapper's flow-function handler to a real
CallHandler._extract_transcript so both halves of the fix are exercised
together: FunctionMapper._capture_direct_speech populates pending_responses,
and _extract_transcript's existing prefix-matched annotation + global
chronological sort (already proven correct for genuine LLM turns in
test_interrupted_transcript.py) uses it to place the entry correctly.
"""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from botelier.flow_executor import FlowExecutor, parse_flow_config
from botelier.voice.call_handler import CallHandler
from botelier.voice.function_mapper import FunctionMapper

CALL_SID = "CA_test_598_e2e"


def _greeting_flow_config():
    """A flow whose first node speaks a greeting via waitForResponse=False,
    auto-walking straight into the first collect_slot prompt — reproducing
    the start_<flow> trigger path (_create_flow_trigger_handler), which
    speaks every initial_messages entry directly via TTSSpeakFrame."""
    return {
        "initial_node": "start",
        "variables": [{"key": "checkin", "type": "date", "description": "checkin"}],
        "nodes": [
            {"id": "start", "type": "initial", "data": {"greeting": "Hi, I can help with that.", "waitForResponse": False}},
            {
                "id": "checkin",
                "type": "collect_slot",
                "data": {"slot": {"variableKey": "checkin", "prompt": "What is your check-in date?"}},
            },
        ],
        "edges": [{"id": "e1", "source": "start", "target": "checkin"}],
    }


def _bare_call_handler() -> CallHandler:
    """CallHandler with only the state _extract_transcript / capture need."""
    handler = CallHandler.__new__(CallHandler)
    handler.interrupted_responses = {}
    handler.user_turn_timestamps = {CALL_SID: []}
    handler.pending_responses = {CALL_SID: []}
    handler.action_timestamps = {CALL_SID: []}
    handler.call_start_times = {CALL_SID: datetime.utcnow()}
    return handler


def _api_flow_config(api_data=None):
    return {
        "initial_node": "start",
        "variables": [{"key": "checkin", "type": "date", "description": "checkin"}],
        "nodes": [
            {"id": "start", "type": "initial", "data": {"greeting": "Hi", "waitForResponse": False}},
            {
                "id": "checkin",
                "type": "collect_slot",
                "data": {"slot": {"variableKey": "checkin", "prompt": "Checkin?"}},
            },
            {"id": "book", "type": "api_request", "data": {"api": {"method": "POST", **(api_data or {})}}},
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "checkin"},
            {"id": "e2", "source": "checkin", "target": "book"},
            {"id": "e3", "source": "book", "target": "end"},
        ],
    }


def _run_flow_handler_capturing(call_handler: CallHandler, api_result: dict):
    """Run FunctionMapper's flow function handler wired to a real
    CallHandler, so its direct TTSSpeakFrame pushes populate
    call_handler.pending_responses exactly as they would on a live call."""
    mapper = FunctionMapper()
    mapper.call_handler = call_handler
    mapper.call_sid = CALL_SID
    executor = FlowExecutor(parse_flow_config(_api_flow_config({})))
    executor.get_initial_messages()
    executor.state.current_node_id = "book"
    executor.handle_function_call = AsyncMock(return_value=api_result)
    mapper._flow_executors["rooms"] = executor
    mapper.update_llm_tools_for_flow = lambda *_: None

    params = SimpleNamespace(
        arguments={},
        llm=SimpleNamespace(push_frame=AsyncMock()),
        result_callback=AsyncMock(),
    )
    handler = mapper._create_flow_function_handler("rooms", "execute_book")
    asyncio.run(handler(params))
    return [c.args[0].text for c in params.llm.push_frame.await_args_list]


def _run_flow_trigger_capturing(call_handler: CallHandler):
    """Run FunctionMapper's start_<flow> trigger handler
    (_create_flow_trigger_handler) wired to a real CallHandler — this is the
    path a caller actually hits first: it speaks the greeting AND, when
    waitForResponse=False, the first collect_slot prompt, all directly via
    TTSSpeakFrame in the same turn, bypassing a normal LLM completion."""
    mapper = FunctionMapper()
    mapper.call_handler = call_handler
    mapper.call_sid = CALL_SID
    executor = FlowExecutor(parse_flow_config(_greeting_flow_config()))
    mapper._flow_executors["rooms"] = executor
    mapper.track_tool_usage = lambda *_, **__: None
    mapper.update_llm_tools_for_flow = lambda *_: None

    params = SimpleNamespace(
        arguments={},
        llm=SimpleNamespace(push_frame=AsyncMock()),
        result_callback=AsyncMock(),
    )
    handler = mapper._create_flow_trigger_handler("rooms")
    asyncio.run(handler(params))
    return [c.args[0].text for c in params.llm.push_frame.await_args_list]


class TestFlowTriggerSpeechOrderingEndToEnd:
    """The start_<flow> trigger — not just the later per-node handler — must
    anchor its directly-spoken messages too, since it is the very first
    thing a caller hears and answers on a real call."""

    def test_initial_prompt_sorts_before_the_callers_answer(self):
        call_handler = _bare_call_handler()

        spoken = _run_flow_trigger_capturing(call_handler)
        assert spoken == ["Hi, I can help with that.", "What is your check-in date?"]
        assert [c["text"] for c in call_handler.pending_responses[CALL_SID]] == spoken

        # Caller answers 4s later; the context aggregator commits the
        # answer before the (delayed) merged greeting+prompt message —
        # the exact inversion reported on a real call.
        call_handler.user_turn_timestamps[CALL_SID] = [
            {"text": "September third.", "elapsed_s": 4.0},
        ]

        transcript, _ = call_handler._extract_transcript(
            CALL_SID,
            {
                "messages": [
                    # Raw commit order — wrong: both directly-spoken pieces
                    # land in context only after the caller's answer.
                    {"role": "user", "content": "September third."},
                    {"role": "assistant", "content": "Hi, I can help with that."},
                    {"role": "assistant", "content": "What is your check-in date?"},
                ]
            },
        )

        contents = [e["content"] for e in transcript]
        assert contents == [
            "Hi, I can help with that.",
            "What is your check-in date?",
            "September third.",
        ], f"Greeting/prompt must sort before the caller's answer: {contents}"


class TestFlowSpokenPromptOrderingEndToEnd:
    def test_next_collection_prompt_sorts_before_the_answer_it_prompted(self):
        """Reproduces the reported defect: the caller's answer to a
        flow-spoken question was committed to context before the question
        itself, and the question — having no real timestamp — could not be
        moved back ahead of its own answer."""
        call_handler = _bare_call_handler()

        spoken = _run_flow_handler_capturing(
            call_handler,
            {
                "success": True,
                "action": None,
                "collected": {"checkin": "2099-09-01"},
                "next_slot": {"variable": "checkout", "prompt": "What is your check-in date?"},
            },
        )
        assert spoken == ["What is your check-in date?"]
        # It was captured with a real elapsed time, not left to interpolate.
        assert call_handler.pending_responses[CALL_SID][0]["text"] == (
            "What is your check-in date?"
        )

        # Caller answers 3s later; the context aggregator, per the reported
        # defect, commits the question merged with the NEXT tool call —
        # AFTER the caller's answer already exists in the raw message array.
        call_handler.user_turn_timestamps[CALL_SID] = [
            {"text": "September third.", "elapsed_s": 3.0},
        ]
        call_handler.action_timestamps[CALL_SID] = [
            {"name": "collect_checkout", "elapsed_s": 3.5},
        ]

        transcript, _ = call_handler._extract_transcript(
            CALL_SID,
            {
                "messages": [
                    # Raw commit order — wrong: answer arrives before the
                    # merged question+action message.
                    {"role": "user", "content": "September third."},
                    {
                        "role": "assistant",
                        "content": "What is your check-in date?",
                        "tool_calls": [{"function": {"name": "collect_checkout"}}],
                    },
                ]
            },
        )

        # Real-time order: question (~0s) -> caller's answer (3.0s) ->
        # collect_checkout firing to process that answer (3.5s). The critical
        # assertion is that the question sorts BEFORE its own answer — the
        # exact inversion reported live.
        contents = [e["content"] for e in transcript]
        assert contents == [
            "What is your check-in date?",
            "September third.",
            "[Action: collect_checkout]",
        ], f"Question must sort before its own answer: {contents}"

    def test_thinking_message_and_completion_bridge_both_sort_correctly(self):
        """A thinkingMessage (spoken while the API call runs) and the
        completion bridge that follows it must both land ahead of the
        caller's next reply, using their own real capture times."""
        call_handler = _bare_call_handler()

        spoken = _run_flow_handler_capturing(
            call_handler,
            {"success": True, "action": None},
        )
        # Only the default completion bridge fires here (no thinkingMessage
        # configured on this node) — confirms it alone is captured too.
        assert spoken == [
            "I've completed that check. Let me walk you through what I found."
        ]
        assert [c["text"] for c in call_handler.pending_responses[CALL_SID]] == spoken

        call_handler.user_turn_timestamps[CALL_SID] = [
            {"text": "Sounds good.", "elapsed_s": 4.0},
        ]

        transcript, _ = call_handler._extract_transcript(
            CALL_SID,
            {
                "messages": [
                    {"role": "user", "content": "Sounds good."},
                    {
                        "role": "assistant",
                        "content": "I've completed that check. Let me walk you through what I found.",
                    },
                ]
            },
        )

        contents = [e["content"] for e in transcript]
        assert contents == [
            "I've completed that check. Let me walk you through what I found.",
            "Sounds good.",
        ], f"Bridge must sort before the reply it precedes: {contents}"
