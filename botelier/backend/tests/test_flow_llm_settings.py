"""Tests for per-flow-tool LLM settings (Task #477).

Covers:
- AssistantSnapshot and ToolSnapshot carry the new LLM fields
- Cold-path flow call: no override → temperature falls back to 0.4
- Cold-path flow call: flow tool has explicit LLM settings → override applied
- Pre-warm-hit path: AssistantSnapshot.temperature is used (no AttributeError)
- Pre-warm-hit path: ToolSnapshot LLM fields propagate through FunctionMapper
- VoiceAgentConfig default max_tokens is 400
"""

from dataclasses import fields
from unittest.mock import MagicMock, patch

import pytest

from botelier.voice.agent import VoiceAgentConfig
from botelier.voice.prewarm import AssistantSnapshot, ToolSnapshot


# ---------------------------------------------------------------------------
# Snapshot dataclass contract
# ---------------------------------------------------------------------------


def test_assistant_snapshot_has_temperature_field():
    snap = AssistantSnapshot(id="a1", account_id="ac1", name="n")
    assert hasattr(snap, "temperature")
    assert snap.temperature is None  # falsy when not set


def test_assistant_snapshot_temperature_preserved():
    snap = AssistantSnapshot(id="a1", account_id="ac1", name="n", temperature=0.3)
    assert snap.temperature == 0.3


def test_tool_snapshot_has_llm_override_fields():
    snap = ToolSnapshot(id="t1", name="book", description="d", tool_type=object())
    for field in ("llm_provider", "llm_model", "llm_temperature", "llm_max_tokens"):
        assert hasattr(snap, field), f"ToolSnapshot missing field: {field}"
        assert getattr(snap, field) is None  # falsy when not set


def test_tool_snapshot_llm_fields_preserved():
    from botelier.models.tool import ToolType

    snap = ToolSnapshot(
        id="t1",
        name="book",
        description="d",
        tool_type=ToolType.FLOW,
        llm_provider="openai",
        llm_model="gpt-4o",
        llm_temperature=0.3,
        llm_max_tokens=500,
    )
    assert snap.llm_provider == "openai"
    assert snap.llm_model == "gpt-4o"
    assert snap.llm_temperature == 0.3
    assert snap.llm_max_tokens == 500


# ---------------------------------------------------------------------------
# VoiceAgentConfig default
# ---------------------------------------------------------------------------


def test_voice_agent_config_default_max_tokens_is_400():
    """Default must be 400 so untuned assistants don't truncate confirmations."""
    cfg = VoiceAgentConfig(agent_id="a", account_id="ac", name="n")
    assert cfg.llm_max_tokens == 400


# ---------------------------------------------------------------------------
# FunctionMapper.get_flow_llm_override — stores and surfaces LLM settings
# ---------------------------------------------------------------------------


def _make_flow_tool(
    llm_provider=None, llm_model=None, llm_temperature=None, llm_max_tokens=None
):
    """Return a minimal mock Tool/ToolSnapshot with LLM fields."""
    tool = MagicMock()
    tool.id = "tool-1"
    tool.name = "book_reservation"
    tool.description = "Book a room"
    tool.llm_provider = llm_provider
    tool.llm_model = llm_model
    tool.llm_temperature = llm_temperature
    tool.llm_max_tokens = llm_max_tokens
    return tool


def _mapper_with_flow_tool(tool):
    """Create a FunctionMapper with a mock executor whose _llm_override is set."""
    from botelier.voice.function_mapper import FunctionMapper

    mapper = FunctionMapper.__new__(FunctionMapper)
    mapper._flow_executors = {}

    executor = MagicMock()
    executor._llm_override = {
        "llm_provider": tool.llm_provider,
        "llm_model": tool.llm_model,
        "llm_temperature": tool.llm_temperature,
        "llm_max_tokens": tool.llm_max_tokens,
    }
    mapper._flow_executors["book_reservation"] = executor
    return mapper


def test_get_flow_llm_override_returns_none_when_all_null():
    tool = _make_flow_tool()
    mapper = _mapper_with_flow_tool(tool)
    assert mapper.get_flow_llm_override() is None


def test_get_flow_llm_override_returns_dict_when_model_set():
    tool = _make_flow_tool(llm_provider="openai", llm_model="gpt-4o")
    mapper = _mapper_with_flow_tool(tool)
    override = mapper.get_flow_llm_override()
    assert override is not None
    assert override["llm_model"] == "gpt-4o"
    assert override["llm_provider"] == "openai"


def test_get_flow_llm_override_returns_dict_when_only_temperature_set():
    tool = _make_flow_tool(llm_temperature=0.2)
    mapper = _mapper_with_flow_tool(tool)
    override = mapper.get_flow_llm_override()
    assert override is not None
    assert override["llm_temperature"] == 0.2


# ---------------------------------------------------------------------------
# call_handler flow-override and temperature-fallback logic
# (unit-tested without spinning up the full pipeline)
# ---------------------------------------------------------------------------


def _apply_flow_overrides(config, assistant, flow_mapper):
    """Replicate the Task #477 block from call_handler verbatim so we can
    test it without importing the full handle_call coroutine."""
    _flow_llm_override = flow_mapper.get_flow_llm_override() if flow_mapper else None
    if _flow_llm_override:
        if _flow_llm_override.get("llm_provider"):
            config.llm_provider = _flow_llm_override["llm_provider"]
        if _flow_llm_override.get("llm_model"):
            config.llm_model = _flow_llm_override["llm_model"]
        if _flow_llm_override.get("llm_temperature") is not None:
            config.llm_temperature = _flow_llm_override["llm_temperature"]
        if _flow_llm_override.get("llm_max_tokens") is not None:
            config.llm_max_tokens = _flow_llm_override["llm_max_tokens"]
    else:
        if assistant.temperature is None:
            config.llm_temperature = 0.4
    return config


def _base_config():
    return VoiceAgentConfig(
        agent_id="a", account_id="ac", name="n",
        llm_provider="openai", llm_model="gpt-4o-mini",
        llm_temperature=0.7, llm_max_tokens=400,
    )


class TestColdPathFlowOverride:
    def test_no_override_no_explicit_temp_falls_back_to_0_4(self):
        """Cold path: flow tool has no LLM settings, assistant has no explicit
        temperature (None) → call_handler sets 0.4."""
        config = _base_config()
        assistant = MagicMock()
        assistant.temperature = None
        mapper = _mapper_with_flow_tool(_make_flow_tool())

        result = _apply_flow_overrides(config, assistant, mapper)
        assert result.llm_temperature == 0.4

    def test_no_override_explicit_temp_preserved(self):
        """Cold path: operator set temperature=0.6 on the assistant → keep it."""
        config = _base_config()
        config.llm_temperature = 0.6
        assistant = MagicMock()
        assistant.temperature = 0.6
        mapper = _mapper_with_flow_tool(_make_flow_tool())

        result = _apply_flow_overrides(config, assistant, mapper)
        assert result.llm_temperature == 0.6

    def test_no_override_zero_temperature_preserved(self):
        """Cold path: operator explicitly set temperature=0.0 (deterministic) →
        must NOT be treated as falsy and overwritten to 0.4."""
        config = _base_config()
        config.llm_temperature = 0.0
        assistant = MagicMock()
        assistant.temperature = 0.0
        mapper = _mapper_with_flow_tool(_make_flow_tool())

        result = _apply_flow_overrides(config, assistant, mapper)
        assert result.llm_temperature == 0.0

    def test_flow_tool_override_applied_fully(self):
        """Cold path: flow tool has all four LLM settings → all applied."""
        config = _base_config()
        assistant = MagicMock()
        assistant.temperature = None
        tool = _make_flow_tool(
            llm_provider="openai", llm_model="gpt-4o",
            llm_temperature=0.3, llm_max_tokens=600,
        )
        mapper = _mapper_with_flow_tool(tool)

        result = _apply_flow_overrides(config, assistant, mapper)
        assert result.llm_provider == "openai"
        assert result.llm_model == "gpt-4o"
        assert result.llm_temperature == 0.3
        assert result.llm_max_tokens == 600

    def test_flow_tool_override_partial_only_model(self):
        """Cold path: only model overridden → others from config unchanged."""
        config = _base_config()
        config.llm_temperature = 0.7
        assistant = MagicMock()
        assistant.temperature = 0.7
        tool = _make_flow_tool(llm_provider="openai", llm_model="gpt-4o")
        mapper = _mapper_with_flow_tool(tool)

        result = _apply_flow_overrides(config, assistant, mapper)
        assert result.llm_model == "gpt-4o"
        # temperature and max_tokens from override are None → not applied
        assert result.llm_temperature == 0.7


class TestPreWarmPathFlowOverride:
    """Same logic as cold path but using AssistantSnapshot (no ORM session)."""

    def test_assistant_snapshot_no_temperature_falls_back_to_0_4(self):
        """Pre-warm hit: AssistantSnapshot.temperature is None (falsy) →
        should apply the 0.4 flow fallback without AttributeError."""
        config = _base_config()
        snap = AssistantSnapshot(id="a", account_id="ac", name="n", temperature=None)
        mapper = _mapper_with_flow_tool(_make_flow_tool())

        result = _apply_flow_overrides(config, snap, mapper)
        assert result.llm_temperature == 0.4

    def test_assistant_snapshot_explicit_temperature_preserved(self):
        """Pre-warm hit: operator set temperature → snapshot carries it → kept."""
        config = _base_config()
        config.llm_temperature = 0.5
        snap = AssistantSnapshot(id="a", account_id="ac", name="n", temperature=0.5)
        mapper = _mapper_with_flow_tool(_make_flow_tool())

        result = _apply_flow_overrides(config, snap, mapper)
        assert result.llm_temperature == 0.5

    def test_assistant_snapshot_zero_temperature_preserved(self):
        """Pre-warm hit: operator explicitly set temperature=0.0 on the assistant.
        The snapshot carries it and the fallback must NOT overwrite it with 0.4
        (0.0 is falsy in Python — the guard must use 'is None', not 'not')."""
        config = _base_config()
        config.llm_temperature = 0.0
        snap = AssistantSnapshot(id="a", account_id="ac", name="n", temperature=0.0)
        mapper = _mapper_with_flow_tool(_make_flow_tool())

        result = _apply_flow_overrides(config, snap, mapper)
        assert result.llm_temperature == 0.0

    def test_tool_snapshot_llm_override_applied(self):
        """Pre-warm hit: ToolSnapshot with LLM fields → override applied correctly."""
        from botelier.models.tool import ToolType

        config = _base_config()
        snap = AssistantSnapshot(id="a", account_id="ac", name="n", temperature=None)
        tool_snap = ToolSnapshot(
            id="t1", name="book_reservation", description="d",
            tool_type=ToolType.FLOW,
            llm_provider="openai", llm_model="gpt-4o",
            llm_temperature=0.25, llm_max_tokens=800,
        )
        mapper = _mapper_with_flow_tool(tool_snap)

        result = _apply_flow_overrides(config, snap, mapper)
        assert result.llm_model == "gpt-4o"
        assert result.llm_temperature == 0.25
        assert result.llm_max_tokens == 800

    def test_tool_snapshot_null_fields_do_not_override(self):
        """Pre-warm hit: ToolSnapshot has all-null LLM fields → 0.4 fallback,
        no AttributeError, no stale values from a prior call."""
        config = _base_config()
        snap = AssistantSnapshot(id="a", account_id="ac", name="n", temperature=None)
        tool_snap = ToolSnapshot(
            id="t1", name="book", description="d", tool_type=object(),
        )
        mapper = _mapper_with_flow_tool(tool_snap)

        result = _apply_flow_overrides(config, snap, mapper)
        # No override → fallback
        assert result.llm_temperature == 0.4
        # Provider and model unchanged
        assert result.llm_provider == "openai"
        assert result.llm_model == "gpt-4o-mini"
