"""Caller grounding must allow validated formats, not invented scalar values."""

import asyncio
from datetime import date

import pytest


def _definition(kind):
    return {
        "initial_node": "start",
        "variables": [{
            "key": "answer", "type": kind,
            **({"choices": ["Standard Room", "Suite"]} if kind == "choice" else {}),
        }],
        "nodes": [
            {"id": "start", "type": "initial", "data": {"greeting": "", "waitForResponse": False}},
            {"id": "answer", "type": "collect_slot", "data": {"slot": {
                "variableKey": "answer", "type": kind, "prompt": "What is your answer?",
                **({"validation": {"allowDecimal": True}} if kind == "number" else {}),
            }}},
            {"id": "done", "type": "end", "data": {"closingMessage": ""}},
        ],
        "edges": [
            {"id": "start-answer", "source": "start", "target": "answer"},
            {"id": "answer-done", "source": "answer", "target": "done"},
        ],
    }


async def _collect(kind, caller, proposed, *, built_in=True, validation=None, today=date(2026, 11, 17)):
    from botelier.voice.flows.native_execution import NativeTerminalResult
    from botelier.voice.flows.native_graph import compile_flow
    from native_graph_io import GraphCall
    from test_native_graph import identity

    async def terminal(_node, _facts):
        return NativeTerminalResult(True, completed=True)

    definition = _definition(kind)
    slot = definition["nodes"][1]["data"]["slot"]
    slot["useBuiltInValidator"] = built_in
    if validation is not None:
        slot["validation"] = validation
    call = GraphCall(
        compile_flow(definition, identity()), today=today,
        terminal_handler=terminal,
    )
    await call.adapter.start()
    call.user_turn(caller)
    name = next(name for name in call.worker.tools if name.startswith("native_"))
    result = await call.invoke(name, {"answer": proposed})
    facts = call.adapter.facts
    await call.adapter.close()
    return result, facts


@pytest.mark.parametrize("kind,caller,proposed,expected", [
    ("date", "December 1, 2026", "2026-12-01", "2026-12-01"),
    ("date", "I arrive on December 1, 2026.", "2026-12-01", "2026-12-01"),
    ("date", "December 1st, 2026", "2026-12-01", "2026-12-01"),
    ("date", "December 1st, 2026", "December 1st, 2026", "2026-12-01"),
    ("date", "tomorrow", "2026-11-18", "2026-11-18"),
    ("number", "Two adults", 2, 2),
    ("number", "2.", 2, 2),
    ("number", "No children", 0, 0),
    ("number", "Twenty-one guests", 21, 21),
    ("number", "One hundred and two guests", 102, 102),
    ("number", "Two point five", 2.5, 2.5),
    ("number", "The amount is 1000.25", 1000.25, 1000.25),
    ("number", "There are 2 adults arriving December 2, 2026", 2, 2),
    ("phone", "Please use (415) 555-0101", "+14155550101", "+14155550101"),
    ("time", "1 pm", "13:00", "13:00"),
    ("choice", "standard", "Standard Room", "Standard Room"),
])
def test_actual_slot_callback_accepts_only_equivalent_caller_formats(kind, caller, proposed, expected):
    result, facts = asyncio.run(_collect(kind, caller, proposed))
    assert facts.get("answer") == expected, result


@pytest.mark.parametrize("kind,caller,proposed", [
    ("date", "December 1, 2027", "2026-12-01"),
    ("date", "December 2, 2026", "2026-12-01"),
    ("number", "twenty-two guests", 2),
    ("number", "twenty-two guests", 22.5),
    ("number", "2.5 adults", 2),
    ("number", "negative two", 2),
    ("number", "minus 2", 2),
    ("number", "No, I meant two children", 0),
    ("number", "December 2, 2026", 2),
    ("number", "At 2:30 pm", 2),
    ("number", "My phone is (415) 555-0101", 415),
    ("phone", "415-555-0102", "+14155550101"),
    ("time", "2 pm", "13:00"),
    ("choice", "deluxe", "Standard Room"),
    ("choice", "Not Standard Room; Suite instead", "Standard Room"),
    ("choice", "Standard Room or Suite", "Standard Room"),
    ("text", "My name is Ada", "Bob"),
])
def test_actual_slot_callback_rejects_invented_or_misread_values(kind, caller, proposed):
    result, facts = asyncio.run(_collect(kind, caller, proposed))
    assert "answer" not in facts, result


@pytest.mark.parametrize("kind,caller,proposed", [
    ("number", "Two adults", 2),
    ("date", "December 1, 2026", "2026-12-01"),
    ("phone", "(415) 555-0101", "+14155550101"),
    ("time", "1 pm", "13:00"),
])
def test_disabled_builtin_normalization_is_respected(kind, caller, proposed):
    result, facts = asyncio.run(_collect(kind, caller, proposed, built_in=False))
    assert "answer" not in facts, result


@pytest.mark.parametrize("kind,caller,proposed,validation", [
    ("number", "Two adults", 2, {"min": 3}),
    ("number", "Two point five", 2.5, {"allowDecimal": False}),
    ("date", "December 1, 2027", "2027-12-01", {"maxDaysAhead": 365}),
    ("phone", "(415) 555-0101", "+14155550101", {"pattern": r"\+44[0-9]+"}),
])
def test_caller_normalization_does_not_bypass_actual_constraints(kind, caller, proposed, validation):
    result, facts = asyncio.run(_collect(kind, caller, proposed, validation=validation))
    assert "answer" not in facts, result


def test_yearless_future_date_uses_the_same_rollover_as_actual_validator():
    result, facts = asyncio.run(_collect(
        "date", "January 2", "2027-01-02", today=date(2026, 12, 20),
    ))
    assert facts.get("answer") == "2027-01-02", result


@pytest.mark.parametrize("kind,caller,proposed", [
    ("number", "two or three adults", 2),
    ("number", "two or three adults", 3),
    ("date", "Not December 1, 2026; use December 2, 2026 instead", "2026-12-01"),
    ("date", "December 1, 2026 isn't correct; we need December 2, 2026", "2026-12-01"),
    ("number", "Two adults isn't correct; we need three adults", 2),
    ("choice", "I wouldn't choose Standard Room", "Standard Room"),
    ("choice", "I won't choose Standard Room", "Standard Room"),
])
def test_unresolved_or_negated_scalar_is_not_a_selection(kind, caller, proposed):
    result, facts = asyncio.run(_collect(kind, caller, proposed))
    assert "answer" not in facts, result
