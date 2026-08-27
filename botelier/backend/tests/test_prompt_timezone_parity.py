"""Focused tests for assistant-local prompt composition."""

from datetime import datetime, timezone

from botelier.api.simulation import SimulationState
from botelier.flow_executor import FlowExecutor, parse_flow_config
from botelier.voice.agent import VoiceAgentConfig
from botelier.voice.engine import AssistantLocalTimeContextUpdater
from botelier.voice.prompt_context import (
    build_runtime_system_prompt,
    build_assistant_local_time_segment,
    compose_assistant_system_prompt,
    static_prompt_prefix,
)
from pipecat.processors.aggregators.llm_context import LLMContext


FIXED_UTC = datetime(2026, 1, 2, 7, 8, 9, tzinfo=timezone.utc)


def _executor(assistant_timezone: str = "UTC") -> FlowExecutor:
    return FlowExecutor(
        parse_flow_config(
            {
                "initial_node": "init",
                "nodes": [
                    {
                        "id": "init",
                        "type": "initial",
                        "data": {"systemPrompt": "FLOW PERSONA"},
                    },
                    {
                        "id": "slot",
                        "type": "collect_slot",
                        "data": {
                            "slot": {
                                "variableKey": "arrival",
                                "type": "date",
                                "prompt": "Which date?",
                            }
                        },
                    },
                ],
                "edges": [{"id": "e", "source": "init", "target": "slot"}],
                "variables": [
                    {
                        "key": "arrival",
                        "type": "date",
                        "description": "Arrival date",
                    }
                ],
            }
        ),
        assistant_timezone=assistant_timezone,
    )


def test_local_time_segment_converts_date_time_and_offset():
    segment = build_assistant_local_time_segment(
        "America/Los_Angeles", FIXED_UTC
    )
    assert segment == (
        "## ASSISTANT LOCAL TIME\n"
        "Date: 2026-01-01 | Time: 23:08:09 | "
        "Timezone: America/Los_Angeles | UTC offset: -08:00"
    )


def test_invalid_timezone_explicitly_falls_back_to_utc():
    segment = build_assistant_local_time_segment("Not/A_Zone", FIXED_UTC)
    assert (
        "Date: 2026-01-02 | Time: 07:08:09 | Timezone: UTC | UTC offset: +00:00"
        in segment
    )


def test_exact_static_clock_dynamic_ordering():
    prompt = compose_assistant_system_prompt(
        ["ASSISTANT", "KB", "FLOW"],
        "UTC",
        now=FIXED_UTC,
        dynamic_sections=["CURRENT NODE", "USER TEXT"],
    )
    assert prompt == (
        "ASSISTANT\n\nKB\n\nFLOW\n\n"
        "## ASSISTANT LOCAL TIME\n"
        "Date: 2026-01-02 | Time: 07:08:09 | Timezone: UTC | UTC offset: +00:00"
        "\n\nCURRENT NODE\n\nUSER TEXT"
    )


def test_simulator_matches_live_composition_and_uses_local_date():
    executor = _executor("America/Los_Angeles")
    state = SimulationState(
        tool_id="tool",
        executor=executor,
        assistant_prompt="ASSISTANT",
        kb_prompt_block="\n\nKB",
        timezone="America/Los_Angeles",
    )
    live_equivalent = build_runtime_system_prompt(
        "ASSISTANT\n\nKB",
        [executor],
        "America/Los_Angeles",
        now=FIXED_UTC,
    )
    assert state.build_system_prompt(FIXED_UTC) == live_equivalent
    assert "Current date: 2026-01-01" in live_equivalent
    assert executor.assistant_timezone == "America/Los_Angeles"
    assert "CURRENT NODE:" not in live_equivalent
    assert "Which date?" not in live_equivalent


def test_prewarm_shape_excludes_node_and_user_dynamic_text():
    executor = _executor()
    prewarm_prompt = build_runtime_system_prompt(
        "ASSISTANT\n\nKB",
        [executor],
        "America/Los_Angeles",
        now=FIXED_UTC,
    )
    assert "ASSISTANT LOCAL TIME" in prewarm_prompt
    assert "CURRENT NODE:" not in prewarm_prompt
    assert "Which date?" not in prewarm_prompt
    assert "USER TEXT" not in prewarm_prompt


def test_turn_refresh_preserves_prefix_and_rolls_local_midnight():
    executor = _executor()
    before_midnight = datetime(2026, 1, 2, 7, 59, 59, tzinfo=timezone.utc)
    after_midnight = datetime(2026, 1, 2, 8, 0, 1, tzinfo=timezone.utc)
    initial = build_runtime_system_prompt(
        "ASSISTANT\n\nKB",
        [executor],
        "America/Los_Angeles",
        now=before_midnight,
    )
    config = VoiceAgentConfig(
        agent_id="a",
        account_id="ac",
        name="Assistant",
        system_prompt=initial,
        timezone="America/Los_Angeles",
        runtime_assistant_prompt="ASSISTANT\n\nKB",
        runtime_flow_personas=[executor.get_flow_persona_section()],
        runtime_has_flow=True,
        runtime_has_past_date_slot=False,
    )
    context = LLMContext([{"role": "system", "content": initial}])
    updater = AssistantLocalTimeContextUpdater(context, config)

    updater.refresh_context(before_midnight)
    first = context.messages[0]["content"]
    updater.refresh_context(before_midnight.replace(second=30))
    same_day = context.messages[0]["content"]
    assert static_prompt_prefix(first) == static_prompt_prefix(same_day)

    updater.refresh_context(after_midnight)
    next_day = context.messages[0]["content"]
    assert "Date: 2026-01-02" in next_day
    assert "Current date: 2026-01-02" in next_day
    assert "Current date: 2026-01-01" in first
    assert next_day.startswith("ASSISTANT\n\nKB")