"""Characterization, NOT a claim that business/voice acceptance gates pass."""

import asyncio

import pytest

from pipecat.flows import ContextStrategy, ContextStrategyConfig
from pipecat.frames.frames import EndFrame, LLMRunFrame, TTSSpeakFrame
from native_support import NativeHarness, function, node


def run(scenario):
    asyncio.run(asyncio.wait_for(scenario(), timeout=3))


def test_real_manager_advertises_stage_tools_without_running_a_model():
    async def scenario():
        async def collect(args, manager):
            return {"accepted": args}

        trial = NativeHarness()
        await trial.manager.initialize(node(
            "collect", functions=[function("collect", collect)],
            instruction="Collect only missing details.",
        ))
        assert trial.manager.current_node == "collect"
        assert set(trial.boundary.tools) == {"collect"}
        assert trial.boundary.context.get_messages() == [
            {"role": "developer", "content": "Collect only missing details."}
        ]
        assert not any(isinstance(frame, LLMRunFrame) for frame in trial.boundary.frames)
    run(scenario)


def test_edge_transition_waits_for_tool_result_context_update():
    async def scenario():
        async def advance(args, manager):
            return {"status": "ok"}, node("review")

        trial = NativeHarness()
        await trial.manager.initialize(node("collect", functions=[function("advance", advance)]))
        assert await trial.invoke("advance", {}, defer_context=True) == {"status": "ok"}
        assert trial.manager.current_node == "collect"
        await trial.flush_context_updates()
        assert trial.manager.current_node == "review"
        assert trial.boundary.tools == {}
    run(scenario)


@pytest.mark.parametrize("value", [False, {}, [], 0, ""])
def test_flows_callback_preserves_falsey_results_before_aggregator(value):
    async def scenario():
        async def return_value(args, manager):
            return value

        trial = NativeHarness()
        await trial.manager.initialize(node("collect", functions=[function("value", return_value)]))
        observed = await trial.invoke("value", {})
        assert type(observed) is type(value)
        assert observed == value
    run(scenario)


@pytest.mark.parametrize("arguments", [{}, {"confirmed": "false"}, {"confirmed": {"bad": "type"}}])
def test_framework_forwards_missing_or_wrong_type_without_schema_validation(arguments):
    async def scenario():
        async def echo(args, manager):
            return {"received": args}

        trial = NativeHarness()
        await trial.manager.initialize(node(
            "review",
            functions=[function(
                "confirm", echo, properties={"confirmed": {"type": "boolean"}},
                required=["confirmed"],
            )],
        ))
        result = await trial.invoke("confirm", arguments)
        assert result == {"received": arguments}
        assert trial.manager.current_node == "review"
    run(scenario)


def test_failed_business_result_still_transitions_if_handler_returns_next_node():
    async def scenario():
        async def unsuccessful(args, manager):
            return {"success": False, "record_saved": False}, node("end")

        trial = NativeHarness()
        await trial.manager.initialize(node("save", functions=[function("save", unsuccessful)]))
        assert await trial.invoke("save", {}) == {"success": False, "record_saved": False}
        assert trial.manager.current_node == "end"
    run(scenario)


def test_global_mcp_tool_survives_local_node_tool_replacement():
    async def scenario():
        async def lookup(args, manager):
            return {"source": "synthetic"}

        async def advance(args, manager):
            return {"status": "ok"}, node("review")

        trial = NativeHarness(globals=[function("mcp_lookup", lookup)])
        await trial.manager.initialize(node("collect", functions=[function("advance", advance)]))
        assert set(trial.boundary.tools) == {"mcp_lookup", "advance"}
        await trial.invoke("advance", {})
        assert set(trial.boundary.tools) == {"mcp_lookup"}
        assert await trial.invoke("mcp_lookup", {}) == {"source": "synthetic"}
    run(scenario)


def test_complete_mcp_error_payload_reaches_callback_without_flattening():
    async def scenario():
        async def lookup(args, manager):
            return {
                "isError": True,
                "content": [
                    {"type": "text", "text": "First block"},
                    {"type": "text", "text": "Second block"},
                ],
                "structuredContent": {"status": "rejected", "code": "NOT_AVAILABLE"},
            }

        trial = NativeHarness(globals=[function("mcp_lookup", lookup)])
        await trial.manager.initialize(node("collect"))
        assert await trial.invoke("mcp_lookup", {}) == {
            "isError": True,
            "content": [
                {"type": "text", "text": "First block"},
                {"type": "text", "text": "Second block"},
            ],
            "structuredContent": {"status": "rejected", "code": "NOT_AVAILABLE"},
        }
        assert trial.manager.current_node == "collect"
    run(scenario)


def test_reset_replaces_stale_private_guidance_and_conversation_history():
    async def scenario():
        trial = NativeHarness()
        await trial.manager.initialize(node("collect", instruction="Collect missing details."))
        trial.boundary.context.add_message({"role": "user", "content": "Synthetic earlier answer"})
        await trial.manager.set_node_from_config(node(
            "review", instruction="Review collected details.",
            context_strategy=ContextStrategyConfig(strategy=ContextStrategy.RESET),
        ))
        assert trial.boundary.context.get_messages() == [
            {"role": "developer", "content": "Review collected details."}
        ]
    run(scenario)


def test_default_append_keeps_previous_private_guidance():
    async def scenario():
        trial = NativeHarness()
        await trial.manager.initialize(node("collect", instruction="Collect missing details."))
        await trial.manager.set_node_from_config(node("review", instruction="Review details."))
        assert trial.boundary.context.get_messages() == [
            {"role": "developer", "content": "Collect missing details."},
            {"role": "developer", "content": "Review details."},
        ]
    run(scenario)


def test_end_action_enqueues_end_without_playback_acknowledgement():
    async def scenario():
        trial = NativeHarness()
        with pytest.warns(DeprecationWarning, match="Single-argument"):
            await trial.manager.initialize(node(
                "end",
                pre_actions=[{"type": "end_conversation", "text": "Goodbye."}],
            ))
        relevant = [
            frame for frame in trial.boundary.frames
            if isinstance(frame, (TTSSpeakFrame, EndFrame))
        ]
        assert len(relevant) == 2
        assert isinstance(relevant[0], TTSSpeakFrame)
        assert relevant[0].text == "Goodbye."
        assert isinstance(relevant[1], EndFrame)
    run(scenario)
