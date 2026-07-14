"""Lockstep tests for flow system-prompt composition.

Task #319 makes the flow-editor's static system-prompt fields (the Initial
node ``systemPrompt``, the flow-level ``global_prompt``, and the shared
behavioural rules) reach LIVE voice calls, not just the simulator.

The live path (``call_handler`` injection) and the simulator path
(``FlowExecutor.get_system_prompt``) both compose the SAME static pieces:

    get_flow_persona_section()  +  build_flow_behavioral_rules(...)

These tests pin that shared contract so the two paths cannot silently drift.
They exercise the pure server-side engine (no DB, no LLM). Run directly:

    python -m tests.test_flow_system_prompt

or under pytest.
"""

from datetime import datetime, timezone

from botelier.flow_executor import (
    FlowExecutor,
    build_flow_behavioral_rules,
    parse_flow_config,
)


def _cfg(nodes, edges=None, variables=None, initial=None, global_prompt=None):
    payload = {
        "initial_node": initial or nodes[0]["id"],
        "nodes": nodes,
        "edges": edges or [],
        "variables": variables or [],
    }
    if global_prompt is not None:
        payload["global_prompt"] = global_prompt
    return parse_flow_config(payload)


def _executor(nodes, **kwargs):
    return FlowExecutor(_cfg(nodes, **kwargs))


# ---------------------------------------------------------------------------
# get_system_prompt() == static additions + "\n\n" + flow context
# This is the invariant that keeps the live and simulator prompts in lockstep:
# the live injector reuses get_static_system_prompt_additions() verbatim.
# ---------------------------------------------------------------------------
def test_get_system_prompt_is_static_additions_plus_flow_context():
    ex = _executor(
        [
            {"id": "init", "type": "initial",
             "data": {"systemPrompt": "You are Ava, a friendly concierge."}},
            {"id": "name", "type": "collect_slot",
             "data": {"slot": {"variableKey": "guest_name"}}},
        ],
        global_prompt="Always confirm spelling of names.",
    )
    expected = (
        ex.get_static_system_prompt_additions()
        + "\n\n"
        + ex._generate_flow_context()
    )
    assert ex.get_system_prompt() == expected
    print("PASS: get_system_prompt == static additions + flow context")


# ---------------------------------------------------------------------------
# Persona section: surfaces Initial systemPrompt + global_prompt when present.
# ---------------------------------------------------------------------------
def test_persona_section_includes_system_and_global_prompt():
    ex = _executor(
        [
            {"id": "init", "type": "initial",
             "data": {"systemPrompt": "You are Ava, a friendly concierge."}},
            {"id": "name", "type": "collect_slot",
             "data": {"slot": {"variableKey": "guest_name"}}},
        ],
        global_prompt="Always confirm spelling of names.",
    )
    persona = ex.get_flow_persona_section()
    assert "You are Ava, a friendly concierge." in persona
    assert "Always confirm spelling of names." in persona
    assert "FLOW-LEVEL INSTRUCTIONS" in persona
    assert persona.startswith("## FLOW INSTRUCTIONS")
    print("PASS: persona section includes system + global prompt")


def test_persona_section_only_system_prompt():
    ex = _executor(
        [
            {"id": "init", "type": "initial",
             "data": {"systemPrompt": "You are Ava."}},
            {"id": "name", "type": "collect_slot",
             "data": {"slot": {"variableKey": "guest_name"}}},
        ],
    )
    persona = ex.get_flow_persona_section()
    assert "You are Ava." in persona
    assert "FLOW-LEVEL INSTRUCTIONS" not in persona
    print("PASS: persona section with only system prompt")


# ---------------------------------------------------------------------------
# Persona section is empty when the flow configures neither field, so the live
# injector appends only the shared behavioural rules (no empty persona block).
# ---------------------------------------------------------------------------
def test_persona_section_empty_when_nothing_configured():
    ex = _executor(
        [
            {"id": "init", "type": "initial", "data": {}},
            {"id": "name", "type": "collect_slot",
             "data": {"slot": {"variableKey": "guest_name"}}},
        ],
    )
    assert ex.get_flow_persona_section() == ""
    # Static additions collapse to exactly the behavioural rules.
    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert ex.get_static_system_prompt_additions() == build_flow_behavioral_rules(
        current_date, ex.has_past_date_slot()
    )
    print("PASS: empty persona -> static additions are just the rules")


# ---------------------------------------------------------------------------
# Behavioural rules: voice/flow guarantees that must reach live calls.
# ---------------------------------------------------------------------------
def test_behavioral_rules_contain_core_guarantees():
    rules = build_flow_behavioral_rules("2026-07-14", has_past_date_slot=False)
    assert "Current date: 2026-07-14" in rules
    assert "Never use markdown" in rules
    assert "speak_exactly" in rules
    assert "Collect information in the order specified" in rules
    assert "continue collecting where you left off" in rules
    # Date-only: no wall-clock time leaks in (keeps the prompt cache stable).
    assert "UTC" not in rules
    print("PASS: behavioural rules contain core guarantees")


def test_behavioral_rules_date_variant_switches_on_past_date_slot():
    future_only = build_flow_behavioral_rules("2026-07-14", has_past_date_slot=False)
    with_past = build_flow_behavioral_rules("2026-07-14", has_past_date_slot=True)
    assert "Never assume a past year" in future_only
    assert "Never assume a past year" not in with_past
    assert "most recent past occurrence" in with_past
    print("PASS: date rule variant switches on past-date slot")


ALL_TESTS = [
    test_get_system_prompt_is_static_additions_plus_flow_context,
    test_persona_section_includes_system_and_global_prompt,
    test_persona_section_only_system_prompt,
    test_persona_section_empty_when_nothing_configured,
    test_behavioral_rules_contain_core_guarantees,
    test_behavioral_rules_date_variant_switches_on_past_date_slot,
]


if __name__ == "__main__":
    for t in ALL_TESTS:
        t()
    print(f"\n{len(ALL_TESTS)} tests passed.")
