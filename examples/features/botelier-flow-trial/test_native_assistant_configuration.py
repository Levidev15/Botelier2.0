"""Keep native voice and text on the same assistant/configuration contract."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from application_support import load_function_mapper
from lifecycle_io import Records


def configuration_module():
    load_function_mapper()
    from botelier.voice import assistant_config
    return assistant_config


def test_shared_assistant_configuration_preserves_the_real_voice_settings():
    async def scenario():
        module = configuration_module()
        assistant = Records().assistant
        assistant.temperature = 0
        assistant.max_tokens = 777
        assistant.llm_config = {"top_p": 0.8}
        config = await module.build_assistant_agent_config(assistant)
        assert config.agent_id == str(assistant.id)
        assert config.account_id == str(assistant.account_id)
        assert config.system_prompt == assistant.system_prompt
        assert config.greeting_message == assistant.first_message
        assert config.llm_provider == assistant.llm_provider
        assert config.llm_model == assistant.llm_model
        assert config.llm_temperature == 0
        assert config.llm_max_tokens == 777
        assert config.llm_config == {"top_p": 0.8}
        assert config.stt_provider == assistant.stt_provider
        assert config.tts_provider == assistant.tts_provider
        assert config.timezone == assistant.timezone
        assert config.enable_function_calling
    asyncio.run(scenario())


def test_shared_assistant_configuration_keeps_knowledge_private_and_loads_it_once():
    async def scenario():
        module = configuration_module()
        from botelier.voice import knowledge_handler

        assistant = Records().assistant
        assistant.knowledge_base_id = "offline-knowledge"
        with patch.object(
            knowledge_handler, "load_knowledge_for_prompt",
            return_value="PRIVATE_KNOWLEDGE_FIXTURE",
        ) as load:
            config = await module.build_assistant_agent_config(assistant)
        load.assert_called_once_with("offline-knowledge")
        assert assistant.system_prompt in config.system_prompt
        assert "PRIVATE_KNOWLEDGE_FIXTURE" in config.system_prompt
        assert "PRIVATE_KNOWLEDGE_FIXTURE" not in config.greeting_message
    asyncio.run(scenario())


@pytest.mark.parametrize(
    "assistant_temperature,tool_settings,expected_temperature",
    [
        (None, {}, 0.4),
        (0, {}, 0),
        (None, {"llm_temperature": 0}, 0),
        (0.2, {"llm_temperature": 0.6}, 0.6),
        (None, {"llm_model": "gpt-native-fixture"}, 0.7),
    ],
)
def test_native_voice_and_text_apply_identical_tool_overrides_and_private_clock_context(
    assistant_temperature, tool_settings, expected_temperature,
):
    async def scenario():
        module = configuration_module()
        from botelier.voice.flows.native_dev_host import apply_native_pilot_context

        assistant = Records().assistant
        assistant.temperature = assistant_temperature
        config = await module.build_assistant_agent_config(assistant)
        private_prompt = config.system_prompt
        tool = SimpleNamespace(
            **{
                **dict.fromkeys((
                    "llm_provider", "llm_model", "llm_temperature", "llm_max_tokens",
                )),
                **tool_settings,
            },
        )
        apply_native_pilot_context(
            config, assistant=assistant, tool=tool,
            now=datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc),
        )
        assert config.llm_temperature == expected_temperature
        assert config.llm_model == tool_settings.get("llm_model", assistant.llm_model)
        assert private_prompt in config.runtime_assistant_prompt
        assert private_prompt in config.system_prompt
        # This field enables legacy controller instructions in the clock
        # refresher; native node instructions belong to FlowManager instead.
        assert config.runtime_has_flow is False
        assert config.runtime_flow_personas == []
        assert config.runtime_has_past_date_slot is False
        assert private_prompt not in config.greeting_message
    asyncio.run(scenario())


def test_native_tool_model_provider_and_zero_values_are_not_silently_replaced():
    async def scenario():
        module = configuration_module()
        from botelier.voice.flows.native_dev_host import apply_native_pilot_context

        assistant = Records().assistant
        config = await module.build_assistant_agent_config(assistant)
        tool = SimpleNamespace(
            llm_provider="google_gemini", llm_model="configured-fixture-model",
            llm_temperature=0, llm_max_tokens=123,
        )
        apply_native_pilot_context(config, assistant=assistant, tool=tool)
        assert config.llm_provider == "google_gemini"
        assert config.llm_model == "configured-fixture-model"
        assert config.llm_temperature == 0
        assert config.llm_max_tokens == 123
    asyncio.run(scenario())


def test_native_private_prompt_and_business_survive_the_real_clock_refresher():
    async def scenario():
        module = configuration_module()
        from botelier.voice.engine import AssistantLocalTimeContextUpdater
        from botelier.voice.flows.native_dev_host import apply_native_pilot_context
        from botelier.voice.prompt_context import static_prompt_prefix
        from pipecat.processors.aggregators.llm_context import LLMContext

        assistant = Records().assistant
        assistant.business_name = "Clock-safe Fixture Hotel"
        assistant.timezone = "UTC"
        config = await module.build_assistant_agent_config(assistant)
        tool = SimpleNamespace(
            llm_provider=None, llm_model=None,
            llm_temperature=None, llm_max_tokens=None,
        )
        now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        apply_native_pilot_context(config, assistant=assistant, tool=tool, now=now)
        context = LLMContext([{"role": "system", "content": config.system_prompt}])
        updater = AssistantLocalTimeContextUpdater(context, config)
        updater.refresh_context(now.replace(minute=1))
        refreshed = context.messages[0]["content"]
        assert assistant.business_name in refreshed
        assert assistant.system_prompt in refreshed
        assert static_prompt_prefix(refreshed) == static_prompt_prefix(config.system_prompt)
        assert "12:01" in refreshed
    asyncio.run(scenario())


def test_native_voice_clock_never_restores_legacy_controller_instructions():
    """Reproduce on the actual coordinator, not a hand-built native config."""
    async def scenario():
        load_function_mapper()
        from botelier.flow_executor import build_flow_behavioral_rules
        from lifecycle_io import CALL_SID
        from native_dev_voice_io import NativeDevVoiceCall
        from node_contract_io import speech

        async with NativeDevVoiceCall(native_enabled=True) as call:
            await call.wait_until(lambda: call.started.is_set())
            adapter = call.handler.native_flow_hosts[CALL_SID]
            call.adapter = adapter
            await call.wait_until(
                lambda: adapter._started and "Which fixture?" in speech(call),
            )
            legacy_marker = build_flow_behavioral_rules(
                "2026-11-16", False,
            ).strip().splitlines()[0]
            system_prompt = call.created[4].messages[0]["content"]
            assert legacy_marker not in system_prompt
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())
