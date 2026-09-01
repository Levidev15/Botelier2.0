"""Task #547 — narration fixes: completion bridge, speakable prompts, TTS normalization."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from botelier.flow_executor import (
    FlowExecutor,
    build_flow_behavioral_rules,
    parse_flow_config,
    substitute_variables,
)
from botelier.voice.function_mapper import FunctionMapper
from botelier.voice.speech_normalize import (
    normalize_for_speech,
    number_to_words,
    ordinal_to_words,
)


# ---------------------------------------------------------------------------
# TTS text normalization
# ---------------------------------------------------------------------------

def test_number_to_words():
    assert number_to_words(0) == "zero"
    assert number_to_words(3000) == "three thousand"
    assert number_to_words(3200) == "three thousand two hundred"
    assert number_to_words(1600) == "one thousand six hundred"
    assert number_to_words(21) == "twenty-one"
    assert number_to_words(115) == "one hundred fifteen"


def test_ordinal_to_words():
    assert ordinal_to_words(1) == "first"
    assert ordinal_to_words(3) == "third"
    assert ordinal_to_words(5) == "fifth"
    assert ordinal_to_words(12) == "twelfth"
    assert ordinal_to_words(20) == "twentieth"
    assert ordinal_to_words(21) == "twenty-first"
    assert ordinal_to_words(30) == "thirtieth"


def test_normalize_ordinal_suffixes_in_dates():
    assert (
        normalize_for_speech("from September 3rd to the 5th.")
        == "from September third to the fifth."
    )
    assert normalize_for_speech("the 21st of June") == "the twenty-first of June"


def test_normalize_prices_and_currency():
    assert (
        normalize_for_speech("The total is 3,000 EUR.")
        == "The total is three thousand euros."
    )
    assert (
        normalize_for_speech("That's 3000 EUR total")
        == "That's three thousand euros total"
    )
    assert normalize_for_speech("320.00 USD") == "three hundred twenty dollars"
    assert (
        normalize_for_speech("It costs 320.50 EUR")
        == "It costs three hundred twenty point five zero euros"
    )


def test_normalize_comma_decimal_prices():
    """Comma-grouped integers with decimal cents must be spoken as a single amount,
    not split at the word boundary between the comma and the trailing digit run."""
    # Zero cents: 3,000.00 -> "three thousand" (cents suppressed)
    assert (
        normalize_for_speech("The total is 3,000.00 EUR.")
        == "The total is three thousand euros."
    )
    # Non-zero cents: fractional part expanded digit-by-digit
    assert (
        normalize_for_speech("That's 1,500.50 EUR")
        == "That's one thousand five hundred point five zero euros"
    )
    # Larger amount with zero cents
    assert (
        normalize_for_speech("The rate is 10,000.00 USD")
        == "The rate is ten thousand dollars"
    )


def test_normalize_leaves_phone_numbers_times_and_small_numbers_alone():
    # 7+ digit sequences (phone/confirmation numbers) read digit-by-digit — keep.
    assert normalize_for_speech("call 5551234567") == "call 5551234567"
    assert normalize_for_speech("+1-555-123-4567") == "+1-555-123-4567"
    # Times and small numbers are already spoken fine.
    assert normalize_for_speech("at 3:00 pm for 2 adults") == "at 3:00 pm for 2 adults"
    assert normalize_for_speech("room 12") == "room 12"


def test_normalize_preserves_identifier_style_numbers():
    # Confirmation/booking codes must remain digits the caller can write down.
    assert (
        normalize_for_speech("your confirmation number is 123456")
        == "your confirmation number is 123456"
    )
    assert normalize_for_speech("booking reference 4821") == "booking reference 4821"
    # But prices right after a room NAME still convert.
    assert (
        normalize_for_speech("The Double room is 3000 EUR")
        == "The Double room is three thousand euros"
    )


def test_normalize_never_raises_on_oversized_numbers():
    assert (
        normalize_for_speech("that is 1,000,000,000 EUR")
        == "that is 1,000,000,000 euros"
    )


# ---------------------------------------------------------------------------
# Speakable prompt interpolation — never raw JSON/HTML aloud
# ---------------------------------------------------------------------------

_RATE_PLANS = [
    {
        "rate_plan_code": "4",
        "name": "Base Rate Plan",
        "description_formatted": "<p>Room only — <b>no meals</b></p>",
        "restrictions": {"min_stay": 1},
    },
    {"rate_plan_code": "7", "name": "Breakfast Included", "restrictions": {}},
]


def test_speakable_substitution_summarizes_structured_values():
    spoken = substitute_variables(
        "Available plans: {{rate_plans}}. Which would you like?",
        {"rate_plans": _RATE_PLANS},
        speakable=True,
    )
    assert spoken == (
        "Available plans: Base Rate Plan and Breakfast Included. Which would you like?"
    )
    assert "{" not in spoken and "<" not in spoken


def test_speakable_substitution_strips_html_and_keeps_scalars():
    spoken = substitute_variables(
        "Details: {{desc}} for {{nights}} nights",
        {"desc": "<p>Sea view</p>", "nights": 2},
        speakable=True,
    )
    assert spoken == "Details: Sea view for 2 nights"


def test_default_substitution_still_serializes_json_for_templates():
    rendered = substitute_variables("{{rate_plans}}", {"rate_plans": _RATE_PLANS})
    assert rendered.startswith("[{")  # request/set-variable templates need real JSON


def test_slot_prompt_interpolation_is_speakable():
    config = {
        "initial_node": "start",
        "variables": [{"key": "rate_plan", "type": "text", "description": "plan"}],
        "nodes": [
            {"id": "start", "type": "initial", "data": {"greeting": "Hi", "waitForResponse": False}},
            {
                "id": "rate_plan",
                "type": "collect_slot",
                "data": {
                    "slot": {
                        "variableKey": "rate_plan",
                        "prompt": "We have {{rate_plans}}. Which plan?",
                    }
                },
            },
        ],
        "edges": [{"id": "e1", "source": "start", "target": "rate_plan"}],
    }
    executor = FlowExecutor(parse_flow_config(config))
    executor.get_initial_messages()
    executor.state.set_variable("rate_plans", _RATE_PLANS)
    next_slot = executor._get_next_slot_instructions()
    assert next_slot["prompt"] == (
        "We have Base Rate Plan and Breakfast Included. Which plan?"
    )


# ---------------------------------------------------------------------------
# Behavioral rules — price totals, no raw JSON, no transition parroting
# ---------------------------------------------------------------------------

def test_behavioral_rules_cover_narration_contract():
    rules = build_flow_behavioral_rules("2026-08-27", has_past_date_slot=False)
    assert "TOTAL for the whole stay" in rules
    assert "Never multiply a price by the number of nights" in rules
    assert "Never read raw JSON" in rules
    assert "I've completed that check" in rules  # anti-parroting rule


# ---------------------------------------------------------------------------
# API completion bridge — configurable, non-stacking
# ---------------------------------------------------------------------------

def _api_flow_config(api_data=None):
    return {
        "initial_node": "start",
        "variables": [{"key": "arrival", "type": "date", "description": "arrival"}],
        "nodes": [
            {"id": "start", "type": "initial", "data": {"greeting": "Hi", "waitForResponse": False}},
            {
                "id": "arrival",
                "type": "collect_slot",
                "data": {"slot": {"variableKey": "arrival", "prompt": "Arrival?"}},
            },
            {"id": "book", "type": "api_request", "data": {"api": {"method": "POST", **(api_data or {})}}},
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "arrival"},
            {"id": "e2", "source": "arrival", "target": "book"},
            {"id": "e3", "source": "book", "target": "end"},
        ],
    }


def _spoken_texts(push_frame: AsyncMock) -> list[str]:
    return [call.args[0].text for call in push_frame.await_args_list]


def _run_api_handler(api_data, api_result):
    """Run the flow function handler for execute_book with a stubbed executor result."""
    mapper = FunctionMapper()
    executor = FlowExecutor(parse_flow_config(_api_flow_config(api_data)))
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
    return _spoken_texts(params.llm.push_frame)


def test_success_bridge_speaks_default_when_nothing_else_will():
    spoken = _run_api_handler({}, {"success": True, "action": None})
    assert any("I've completed that check" in t for t in spoken)


def test_success_bridge_is_suppressible_per_node():
    spoken = _run_api_handler({"onComplete": ""}, {"success": True, "action": None})
    assert spoken == []


def test_success_bridge_is_configurable_per_node():
    spoken = _run_api_handler(
        {"onComplete": "One moment while I pull that up."},
        {"success": True, "action": None},
    )
    assert spoken == ["One moment while I pull that up."]
    assert not any("I've completed that check" in t for t in spoken)


def test_success_bridge_skipped_when_next_prompt_speaks_directly():
    spoken = _run_api_handler(
        {},
        {
            "success": True,
            "action": None,
            "collected": {"arrival": "2099-06-10"},
            "next_slot": {"variable": "departure", "prompt": "And your departure date?"},
        },
    )
    assert spoken == ["And your departure date?"]


def test_configured_bridge_also_skipped_when_next_prompt_speaks_directly():
    spoken = _run_api_handler(
        {"onComplete": "One moment."},
        {
            "success": True,
            "action": None,
            "collected": {"arrival": "2099-06-10"},
            "next_slot": {"variable": "departure", "prompt": "And your departure date?"},
        },
    )
    assert spoken == ["And your departure date?"]


def test_error_bridge_still_speaks_on_failure():
    spoken = _run_api_handler({}, {"success": False, "action": None})
    assert any("wasn't able to complete" in t for t in spoken)


def test_api_failure_logs_call_event_with_real_error_detail():
    """Task #599 — an API node failure must log an `api_request_failed`
    CallEvent carrying the real underlying error, even though the caller only
    ever hears the generic/onError bridge text."""
    from unittest.mock import MagicMock

    mapper = FunctionMapper()
    mock_queue = MagicMock()
    mapper.set_event_queue(mock_queue)

    executor = FlowExecutor(parse_flow_config(_api_flow_config({})))
    executor.get_initial_messages()
    executor.state.current_node_id = "book"
    executor.handle_function_call = AsyncMock(
        return_value={
            "success": False,
            "action": None,
            "status_code": 422,
            "error_type": "validation_error",
            "error_detail": "Currency not supported",
            "message": "There was an issue with the information provided.",
        }
    )
    mapper._flow_executors["rooms"] = executor
    mapper.update_llm_tools_for_flow = lambda *_: None

    params = SimpleNamespace(
        arguments={},
        llm=SimpleNamespace(push_frame=AsyncMock()),
        result_callback=AsyncMock(),
    )
    handler = mapper._create_flow_function_handler("rooms", "execute_book")
    asyncio.run(handler(params))

    mock_queue.log.assert_called_once()
    call_args = mock_queue.log.call_args
    assert call_args.args[0] == "api_request_failed"
    assert call_args.kwargs["severity"] == "error"
    details = call_args.kwargs["details"]
    assert details["node_id"] == "book"
    assert details["status_code"] == 422
    assert details["error_type"] == "validation_error"
    # The raw provider reason is preserved for operators, distinct from
    # whatever generic text the caller heard via the onError bridge.
    assert details["error_detail"] == "Currency not supported"
    assert details["onerror_configured"] is False


def test_on_complete_survives_flow_config_round_trip():
    """A saved node's api.onComplete (including explicit "") must reload intact."""
    config = _api_flow_config({"onComplete": ""})
    parsed = parse_flow_config(config)
    book = next(n for n in parsed.nodes if n.id == "book")
    assert book.data["api"]["onComplete"] == ""

    config2 = _api_flow_config({"onComplete": "One moment."})
    parsed2 = parse_flow_config(config2)
    book2 = next(n for n in parsed2.nodes if n.id == "book")
    assert book2.data["api"]["onComplete"] == "One moment."


# ---------------------------------------------------------------------------
# Direct voice_result narration — Task #563
#
# When the API node returns a non-empty voice_result (the caller-facing
# summary built from onSuccess + extracted variables, or from
# responseInstructions), it must be spoken immediately via TTSSpeakFrame
# instead of a generic bridge, and run_llm must be False so that the LLM
# doesn't call the next flow tool before the caller has heard the result.
# ---------------------------------------------------------------------------

def _run_api_handler_full(api_data, api_result):
    """Like _run_api_handler but also returns the result_callback mock."""
    mapper = FunctionMapper()
    executor = FlowExecutor(parse_flow_config(_api_flow_config(api_data)))
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
    return _spoken_texts(params.llm.push_frame), params.result_callback


def _result_callback_run_llm(cb: AsyncMock) -> bool:
    """Return the effective run_llm flag from the result_callback invocation.

    True when result_callback was called without explicit properties (the
    default), False when FunctionCallResultProperties(run_llm=False) was set.
    """
    props = (cb.call_args.kwargs or {}).get("properties")
    if props is not None and props.run_llm is not None:
        return bool(props.run_llm)
    return True  # pipecat default


def test_voice_result_spoken_directly_when_present():
    """voice_result from the API response is narrated immediately via TTS."""
    spoken, _ = _run_api_handler_full(
        {},
        {
            "success": True,
            "action": None,
            "voice_result": "Available rooms: Superior Room at one hundred ninety-nine per night.",
        },
    )
    assert any("Superior Room" in t for t in spoken)


def test_voice_result_replaces_generic_bridge():
    """When voice_result is present the generic bridge must NOT be spoken."""
    spoken, _ = _run_api_handler_full(
        {},
        {
            "success": True,
            "action": None,
            "voice_result": "Available rooms: Superior Room at one hundred ninety-nine per night.",
        },
    )
    assert not any("I've completed that check" in t for t in spoken)


def test_voice_result_sets_run_llm_false():
    """Directly-spoken voice_result must suppress the follow-up LLM turn."""
    _, cb = _run_api_handler_full(
        {},
        {
            "success": True,
            "action": None,
            "voice_result": "Available rooms: Superior Room at one hundred ninety-nine per night.",
        },
    )
    assert _result_callback_run_llm(cb) is False


def test_no_voice_result_still_falls_back_to_bridge():
    """Regression: bridge fires and run_llm stays True when voice_result is absent."""
    spoken, cb = _run_api_handler_full({}, {"success": True, "action": None})
    assert any("I've completed that check" in t for t in spoken)
    assert _result_callback_run_llm(cb) is True


def test_no_voice_result_custom_bridge_still_spoken():
    """Configured onComplete bridge still fires when there's no voice_result."""
    spoken, cb = _run_api_handler_full(
        {"onComplete": "Done! Let me walk you through it."},
        {"success": True, "action": None},
    )
    assert spoken == ["Done! Let me walk you through it."]
    assert _result_callback_run_llm(cb) is True


def test_error_path_unaffected_by_voice_result_logic():
    """Failed API calls use the error bridge; run_llm stays True for LLM recovery."""
    spoken, cb = _run_api_handler_full({}, {"success": False, "action": None})
    assert any("wasn't able to complete" in t for t in spoken)
    assert _result_callback_run_llm(cb) is True


# ---------------------------------------------------------------------------
# Raw extracted-data digest must never be spoken verbatim — Task #601
#
# When responseInstructions is blank, flow_executor falls back to a compact
# "success_msg. Extracted data — field: value; ..." digest so the LLM still
# has the data to narrate.  That digest is flagged
# voice_result_is_auto_summary=True precisely so FunctionMapper never pushes
# it to TTS the way it does genuine designer-authored responseInstructions.
# ---------------------------------------------------------------------------

_RAW_DIGEST = (
    "Request completed successfully. Extracted data — room_price: 8000, 7500; "
    "rooms_name: Double, Family; room_currency: EUR"
)


def test_auto_summary_voice_result_is_never_spoken_verbatim():
    spoken, _ = _run_api_handler_full(
        {},
        {
            "success": True,
            "action": None,
            "voice_result": _RAW_DIGEST,
            "voice_result_is_auto_summary": True,
        },
    )
    assert not any("Extracted data" in t for t in spoken)
    assert not any("room_price" in t for t in spoken)


def test_auto_summary_falls_back_to_completion_bridge():
    """The digest is suppressed from TTS, but the caller must still hear
    *something* — the normal silence-safety bridge — instead of dead air."""
    spoken, cb = _run_api_handler_full(
        {},
        {
            "success": True,
            "action": None,
            "voice_result": _RAW_DIGEST,
            "voice_result_is_auto_summary": True,
        },
    )
    assert any("I've completed that check" in t for t in spoken)
    # run_llm stays True so a real LLM turn narrates the digest naturally —
    # the digest itself still reaches the LLM via result["result"].
    assert _result_callback_run_llm(cb) is True


def test_auto_summary_still_reaches_llm_context_for_narration():
    """The digest must not vanish — it stays in result['result'] so the LLM
    can compose natural narration from the real extracted data."""
    _, cb = _run_api_handler_full(
        {},
        {
            "success": True,
            "action": None,
            "voice_result": _RAW_DIGEST,
            "voice_result_is_auto_summary": True,
        },
    )
    passed_result = cb.call_args.args[0]
    assert passed_result["result"] == _RAW_DIGEST
    assert "voice_result_is_auto_summary" not in passed_result


def test_configured_onComplete_bridge_used_instead_of_default_for_auto_summary():
    spoken, _ = _run_api_handler_full(
        {"onComplete": "One moment while I check that for you."},
        {
            "success": True,
            "action": None,
            "voice_result": _RAW_DIGEST,
            "voice_result_is_auto_summary": True,
        },
    )
    assert spoken == ["One moment while I check that for you."]


class _FakeCallHandler:
    """Minimal stand-in exposing exactly what _capture_direct_speech reads."""

    def __init__(self):
        from datetime import datetime

        self.call_sid = "CA_test_598"
        self.call_start_times = {self.call_sid: datetime.utcnow()}
        self.pending_responses = {self.call_sid: []}


def _run_api_handler_with_call_handler(api_data, api_result):
    """Like _run_api_handler_full, but wired to a fake call_handler so direct
    TTSSpeakFrame pushes get captured into pending_responses (Task #598)."""
    call_handler = _FakeCallHandler()
    mapper = FunctionMapper()
    mapper.call_handler = call_handler
    mapper.call_sid = call_handler.call_sid
    executor = FlowExecutor(parse_flow_config(_api_flow_config(api_data)))
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
    captured_texts = [c["text"] for c in call_handler.pending_responses[call_handler.call_sid]]
    return _spoken_texts(params.llm.push_frame), captured_texts


class TestDirectSpeechCapturedForTranscriptOrdering:
    """Task #598 — every direct TTSSpeakFrame push from the flow function
    handler must also be captured with a real elapsed-time anchor into
    call_handler.pending_responses, exactly like a genuine LLM completion.
    _extract_transcript's prefix-matched annotation + global chronological
    sort (see test_interrupted_transcript.py::TestDefectFixes) already
    restores correct order GIVEN such a capture; without one, Pipecat's
    context aggregator can commit this text merged with — or behind — a
    later message, and no timestamp means the sort can't undo that."""

    def test_success_bridge_is_captured(self):
        spoken, captured = _run_api_handler_with_call_handler(
            {}, {"success": True, "action": None}
        )
        assert any("I've completed that check" in t for t in spoken)
        assert captured == spoken

    def test_next_flow_prompt_is_captured(self):
        spoken, captured = _run_api_handler_with_call_handler(
            {},
            {
                "success": True,
                "action": None,
                "collected": {"arrival": "2099-06-10"},
                "next_slot": {"variable": "departure", "prompt": "And your departure date?"},
            },
        )
        assert spoken == ["And your departure date?"]
        assert captured == spoken

    def test_designer_voice_result_is_captured(self):
        spoken, captured = _run_api_handler_with_call_handler(
            {},
            {
                "success": True,
                "action": None,
                "voice_result": "We have a Family room available.",
                "voice_result_is_auto_summary": False,
            },
        )
        assert spoken == ["We have a Family room available."]
        assert captured == spoken

    def test_auto_summary_bridge_fallback_is_captured_not_the_raw_digest(self):
        """The raw digest itself is never spoken (Task #601), but whatever
        DOES get spoken instead (the completion bridge) must still be
        captured so its real position in the transcript is correct."""
        spoken, captured = _run_api_handler_with_call_handler(
            {},
            {
                "success": True,
                "action": None,
                "voice_result": "Request completed successfully. Extracted data — x: 1",
                "voice_result_is_auto_summary": True,
            },
        )
        assert spoken == captured
        assert not any("Extracted data" in t for t in captured)

    def test_no_crash_when_call_handler_unset(self):
        """The simulator and bare-constructed mappers have no call_handler —
        capture must be a silent no-op, not a crash."""
        spoken, _ = _run_api_handler_full({}, {"success": True, "action": None})
        assert any("I've completed that check" in t for t in spoken)


def test_designer_response_instructions_are_still_spoken_directly():
    """Regression: explicit voice_result_is_auto_summary=False (genuine
    designer responseInstructions) must still be spoken immediately, exactly
    like the Task #563 behavior this fix must not regress."""
    spoken, cb = _run_api_handler_full(
        {},
        {
            "success": True,
            "action": None,
            "voice_result": "We have a Family room available for five adults.",
            "voice_result_is_auto_summary": False,
        },
    )
    assert any("Family room available" in t for t in spoken)
    assert not any("I've completed that check" in t for t in spoken)
    assert _result_callback_run_llm(cb) is False


# ---------------------------------------------------------------------------
# Auto-fire path: collect_slot → api_request
#
# When a collect function advances the flow to an API_REQUEST node the mapper
# fires execute_* immediately (the "auto-fire").  The same voice_result logic
# must apply — callers must hear the result without a second LLM turn.
# ---------------------------------------------------------------------------

_COLLECT_AND_API_FLOW = {
    "initial_node": "start",
    "variables": [{"key": "arrival", "type": "date", "description": "arrival"}],
    "nodes": [
        {
            "id": "start",
            "type": "initial",
            "data": {"greeting": "Hi", "waitForResponse": False},
        },
        {
            "id": "arrival",
            "type": "collect_slot",
            "data": {"slot": {"variableKey": "arrival", "prompt": "Arrival?"}},
        },
        {
            "id": "book",
            "type": "api_request",
            "data": {"api": {"method": "GET", "url": "https://api.example.com/rooms"}},
        },
        {"id": "end", "type": "end", "data": {}},
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "arrival"},
        {"id": "e2", "source": "arrival", "target": "book"},
        {"id": "e3", "source": "book", "target": "end"},
    ],
}


def _run_collect_then_auto_fire(api_result):
    """Simulate collect_slot finishing → auto-fire of the API node → return results."""
    mapper = FunctionMapper()
    executor = FlowExecutor(parse_flow_config(_COLLECT_AND_API_FLOW))
    executor.get_initial_messages()
    executor.state.current_node_id = "arrival"

    call_count = 0

    async def _mock_handle(fn_name, args):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # collect_arrival succeeded — advance state to the API node.
            executor.state.current_node_id = "book"
            return {
                "success": True,
                "action": None,
                "collected": {"arrival": "2099-07-01"},
                "next_slot": None,
                "message": "Got it.",
            }
        # Auto-fired execute_book result.
        return api_result

    executor.handle_function_call = _mock_handle
    mapper._flow_executors["rooms"] = executor
    mapper.update_llm_tools_for_flow = lambda *_: None

    params = SimpleNamespace(
        arguments={"arrival": "2099-07-01"},
        llm=SimpleNamespace(push_frame=AsyncMock()),
        result_callback=AsyncMock(),
    )
    handler = mapper._create_flow_function_handler("rooms", "collect_arrival")
    asyncio.run(handler(params))
    return _spoken_texts(params.llm.push_frame), params.result_callback


def test_auto_fire_speaks_voice_result_immediately():
    """collect_slot → auto-fired API: voice_result spoken directly, no bridge."""
    spoken, _ = _run_collect_then_auto_fire(
        {
            "success": True,
            "action": None,
            "voice_result": "We have two rooms: Superior at one ninety-nine, Deluxe at two fifty-nine.",
        }
    )
    assert any("Superior" in t for t in spoken)
    assert not any("I've completed that check" in t for t in spoken)


def test_auto_fire_sets_run_llm_false():
    """Auto-fire with voice_result must suppress the follow-up LLM narration turn."""
    _, cb = _run_collect_then_auto_fire(
        {
            "success": True,
            "action": None,
            "voice_result": "We have two rooms: Superior at one ninety-nine, Deluxe at two fifty-nine.",
        }
    )
    assert _result_callback_run_llm(cb) is False


def test_auto_fire_no_voice_result_falls_back_to_bridge():
    """Auto-fire with empty voice_result still uses the bridge + run_llm=True."""
    spoken, cb = _run_collect_then_auto_fire({"success": True, "action": None})
    assert any("I've completed that check" in t for t in spoken)
    assert _result_callback_run_llm(cb) is True


# ---------------------------------------------------------------------------
# Provider-neutral TTS normalization (Cartesia / ElevenLabs / OpenAI paths)
# ---------------------------------------------------------------------------

def test_make_normalizing_tts_normalizes_sentence_mode_text():
    from botelier.voice.engine import make_normalizing_tts

    received: list[str] = []

    class _FakeTTS:
        def __init__(self):
            self._text_aggregation_mode = None  # sentence-style: whole text at once

        async def run_tts(self, text, context_id=None):
            received.append(text)
            yield text

    wrapped = make_normalizing_tts(_FakeTTS)()

    async def _speak(text):
        return [f async for f in wrapped.run_tts(text, "ctx")]

    asyncio.run(_speak("That's 3,000 EUR total, from the 3rd to the 5th."))
    assert received == [
        "That's three thousand euros total, from the third to the fifth."
    ]


def test_make_normalizing_tts_skips_token_mode():
    """TOKEN mode delivers sub-word fragments — normalization must not touch them."""
    from pipecat.services.tts_service import TextAggregationMode

    from botelier.voice.engine import make_normalizing_tts

    received: list[str] = []

    class _FakeTTS:
        def __init__(self):
            self._text_aggregation_mode = TextAggregationMode.TOKEN

        async def run_tts(self, text, context_id=None):
            received.append(text)
            yield text

    wrapped = make_normalizing_tts(_FakeTTS)()

    async def _speak(text):
        return [f async for f in wrapped.run_tts(text, "ctx")]

    asyncio.run(_speak("3,0"))  # fragment of "3,000" mid-stream
    assert received == ["3,0"]
