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
