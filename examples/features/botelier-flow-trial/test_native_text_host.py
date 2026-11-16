"""The real native FlowManager in a bounded, TTS/STT-free text pipeline."""

import asyncio

import pytest
from pipecat.flows.manager import FlowManager
from pipecat.frames.frames import LLMSetToolsFrame
from pipecat.pipeline.worker import PipelineWorker

from botelier.voice.flows.pilot_adapter import NativePilotAdapter
from node_contract_io import API_URL, tool_delta
from native_text_io import NativeTextFixture


def run(scenario):
    asyncio.run(asyncio.wait_for(scenario(), timeout=15))


async def wait_for_model_ends(host, count):
    async with asyncio.timeout(3):
        while host._response_ends < count:
            host._changed.clear()
            if host._response_ends >= count:
                return
            await host._changed.wait()


def native_tool_name(host, prefix):
    return next(
        tool.name
        for tool in host.context.tools.standard_tools
        if tool.name.startswith(prefix)
    )


def test_start_commits_greeting_before_query_without_model_or_audio_services():
    async def scenario():
        async with NativeTextFixture([]) as fixture:
            result = await fixture.host.start()
            assert isinstance(fixture.host.adapter, NativePilotAdapter)
            assert isinstance(fixture.host.adapter.manager, FlowManager)
            assert isinstance(fixture.host._worker, PipelineWorker)
            assert result == {
                "messages": [
                    {"role": "assistant", "content": "Offline greeting."},
                    {"role": "assistant", "content": "Which fixture?"},
                ],
                "function_called": None,
                "function_result": None,
            }
            assert fixture.providers.requests == []
            assert fixture.providers.business_requests == []
            assert fixture.host.adapter.manager.current_node == "query"
            assistant_history = [
                message["content"]
                for message in fixture.host.context.get_messages()
                if message.get("role") == "assistant"
                and isinstance(message.get("content"), str)
            ]
            assert assistant_history == [
                "Offline greeting.",
                "Which fixture?",
            ]
            names = {
                schema.name for schema in fixture.host._context.tools.standard_tools
            }
            assert len(names) == 1
            assert next(iter(names)).startswith("pilot_collect_query_")
            processor_names = {
                type(processor).__name__
                for processor in fixture.host._pipeline_processors
            }
            assert not any("STT" in name or "TTS" in name for name in processor_names)
            processors = fixture.host._pipeline_processors
            llm_index = processors.index(fixture.host._llm)
            assert type(processors[llm_index - 1]).__name__ == (
                "AssistantLocalTimeContextUpdater"
            )
            assert fixture.host.config.runtime_has_flow is False
            assert "## ASSISTANT LOCAL TIME" in (
                fixture.host.context.get_messages()[0]["content"]
            )
            assert "Private host policy" not in str(result)
            assert "Current saved flow node" not in str(result)
            assert fixture.host.snapshot() == {
                "collected_slots": {},
                "current_node": "query",
                "pending_slot": "query",
                "is_complete": False,
                "is_ended": False,
                "progress": {"collected": 0, "total": 2, "percentage": 0},
            }
    run(scenario)


def test_native_tool_read_waits_for_result_and_actual_node_consumers():
    async def scenario():
        async with NativeTextFixture(
            [tool_delta("collect_query", {"query": "standard"})],
            payload={"rooms": [{"name": "Standard", "price": 0}], "price": 0},
        ) as fixture:
            await fixture.host.start()
            query_tool = native_tool_name(
                fixture.host, "pilot_collect_query_",
            )
            send = asyncio.create_task(fixture.host.send("Check the standard fixture."))
            await asyncio.wait_for(fixture.providers.business_started.wait(), timeout=3)
            await wait_for_model_ends(fixture.host, 1)
            assert not send.done(), "model end is not native function completion"

            assistant = fixture.host._context_aggregator.assistant()
            held = asyncio.Event()
            release = asyncio.Event()

            @assistant.event_handler("on_before_process_frame")
            async def hold_choice_tools(_, frame):
                if isinstance(frame, LLMSetToolsFrame) and any(
                    tool.name.startswith("pilot_collect_choice_")
                    for tool in getattr(frame.tools, "standard_tools", ())
                ):
                    held.set()
                    await release.wait()

            fixture.providers.release_business.set()
            await asyncio.wait_for(held.wait(), timeout=3)
            assert not send.done(), "send must await the real assistant tool consumer"
            release.set()
            result = await asyncio.wait_for(send, timeout=3)

            assert len(fixture.providers.business_requests) == 1
            assert str(fixture.providers.business_requests[0].url) == (
                API_URL + "?query=standard"
            )
            model_request = next(
                body for body in fixture.providers.requests if body.get("stream")
            )
            assert model_request["model"] == "gpt-4.1-mini"
            assert model_request["temperature"] == 0.25
            assert model_request["max_completion_tokens"] == 231
            assert model_request["parallel_tool_calls"] is False
            assert result["messages"] == [
                {"role": "assistant", "content": "I am checking the fixture."},
                {
                    "role": "assistant",
                    "content": (
                        "Here are the fixture options. Standard costs 0. "
                        "Which option?"
                    ),
                },
            ]
            assert result["function_called"] == query_tool
            assert result["function_result"]["data"] == {
                "rooms": [{"name": "Standard", "price": 0}],
                "price": 0,
            }
            assert fixture.host.snapshot() == {
                "collected_slots": {"query": "standard"},
                "current_node": "choice",
                "pending_slot": "choice",
                "is_complete": False,
                "is_ended": False,
                "progress": {"collected": 1, "total": 2, "percentage": 50},
            }
            current_tools = {
                tool.name for tool in fixture.host.context.tools.standard_tools
            }
            assert len(current_tools) == 1
            assert next(iter(current_tools)).startswith("pilot_collect_choice_")
            assistant_history = [
                message["content"]
                for message in fixture.host.context.get_messages()
                if message.get("role") == "assistant"
                and isinstance(message.get("content"), str)
            ]
            assert assistant_history == [
                "Offline greeting.",
                "Which fixture?",
                "I am checking the fixture.",
                "Here are the fixture options. Standard costs 0. Which option?",
            ]
            assert "Private host policy" not in str(result)
            assert "Current saved flow node" not in str(result)
    run(scenario)


def test_second_native_collection_pauses_and_settles_with_scalar_function_metadata():
    async def scenario():
        async with NativeTextFixture(
            [
                tool_delta("collect_query", {"query": "standard"}),
                tool_delta("collect_choice", {"choice": "standard"}),
                "Your choice is paused for this pilot.",
            ],
            payload={"rooms": [{"name": "Standard", "price": 0}], "price": 0},
            turn_timeout=1.5,
        ) as fixture:
            await fixture.host.start()
            query_tool = native_tool_name(
                fixture.host, "pilot_collect_query_",
            )
            first = await asyncio.wait_for(
                fixture.host.send("Look up the standard fixture."),
                timeout=3,
            )
            assert first["function_called"] == query_tool
            assert fixture.host.snapshot()["current_node"] == "choice"

            choice_tool = native_tool_name(
                fixture.host, "pilot_collect_choice_",
            )
            final = await asyncio.wait_for(
                fixture.host.send("I choose the standard option."),
                timeout=3,
            )
            assert final["function_called"] == choice_tool
            assert final["function_result"]["outcome"] == "paused"
            assert final["function_result"]["booking_completed"] is False
            assert fixture.host._transition_expected == 0
            assert fixture.host._observer.node_updates == 0
            assert fixture.host._model_inflight == 0
            assert fixture.host.snapshot() == {
                "collected_slots": {
                    "query": "standard",
                    "choice": "standard",
                },
                "current_node": "choice",
                "pending_slot": None,
                "is_complete": False,
                "is_ended": False,
                "progress": {"collected": 2, "total": 2, "percentage": 100},
            }
            assert len(fixture.providers.business_requests) == 1
            await fixture.host.close()
            assert fixture.host.snapshot()["is_ended"] is True
            assert fixture.host.snapshot()["is_complete"] is False
    run(scenario)


def test_api_failure_collects_failure_branch_then_pauses_without_timeout():
    async def scenario():
        async with NativeTextFixture(
            [
                tool_delta("collect_query", {"query": "missing"}),
                tool_delta("collect_failure", {"choice": "try another"}),
                "The failure answer is paused for this pilot.",
            ],
            status=500,
            turn_timeout=1.5,
        ) as fixture:
            await fixture.host.start()
            query_tool = native_tool_name(
                fixture.host, "pilot_collect_query_",
            )
            failed_lookup = await asyncio.wait_for(
                fixture.host.send("Look for a missing fixture."),
                timeout=3,
            )
            assert failed_lookup["function_called"] == query_tool
            assert failed_lookup["function_result"]["outcome"] == "failure"
            assert fixture.host.snapshot() == {
                "collected_slots": {"query": "missing"},
                "current_node": "failure",
                "pending_slot": "choice",
                "is_complete": False,
                "is_ended": False,
                "progress": {"collected": 1, "total": 2, "percentage": 50},
            }

            failure_tool = native_tool_name(
                fixture.host, "pilot_collect_failure_",
            )
            paused = await asyncio.wait_for(
                fixture.host.send("Try another fixture."),
                timeout=3,
            )
            assert paused["function_called"] == failure_tool
            assert paused["function_result"]["outcome"] == "paused"
            assert paused["function_result"]["booking_completed"] is False
            assert fixture.host._transition_expected == 0
            assert fixture.host._observer.node_updates == 0
            assert fixture.host._model_inflight == 0
            assert fixture.host.snapshot() == {
                "collected_slots": {
                    "query": "missing",
                    "choice": "try another",
                },
                "current_node": "failure",
                "pending_slot": None,
                "is_complete": False,
                "is_ended": False,
                "progress": {"collected": 2, "total": 2, "percentage": 100},
            }
            await fixture.host.close()
            assert fixture.host.snapshot()["is_ended"] is True
    run(scenario)


def test_free_model_reply_stays_on_current_node_and_bad_inputs_do_not_mutate():
    async def scenario():
        async with NativeTextFixture(["A plain answer."]) as fixture:
            await fixture.host.start()
            for invalid in ("  ", "x" * 2049, None):
                with pytest.raises(fixture.host.error_type) as error:
                    await fixture.host.send(invalid)
                assert error.value.code == "invalid"
            assert fixture.providers.requests == []
            result = await fixture.host.send("A normal question.")
            assert result == {
                "messages": [{"role": "assistant", "content": "A plain answer."}],
                "function_called": None,
                "function_result": None,
            }
            assert fixture.host.adapter.manager.current_node == "query"
            assert fixture.providers.business_requests == []
            assert fixture.host.snapshot()["collected_slots"] == {}
    run(scenario)


def test_overlapping_send_is_rejected_and_provider_timeout_disposes_work():
    async def scenario():
        async with NativeTextFixture(
            [tool_delta("collect_query", {"query": "standard"})],
            status="hold",
            turn_timeout=4.0,
        ) as fixture:
            await fixture.host.start()
            pending = asyncio.create_task(fixture.host.send("Check the fixture."))
            await asyncio.wait_for(fixture.providers.business_started.wait(), timeout=3)
            with pytest.raises(fixture.host.error_type) as error:
                await fixture.host.send("Do not queue this turn.")
            assert error.value.code == "busy"
            await fixture.host.close()
            with pytest.raises(fixture.host.error_type) as closed:
                await pending
            assert closed.value.code == "closed"
            assert fixture.providers.business_cancelled
            assert set(fixture.host.adapter.facts) <= {"query"}
            assert fixture.host.closed
            with pytest.raises(fixture.host.error_type) as after_close:
                await fixture.host.send("Too late.")
            assert after_close.value.code == "closed"
    run(scenario)


def test_turn_timeout_cancels_held_action_and_prevents_late_mapped_facts():
    async def scenario():
        async with NativeTextFixture(
            [tool_delta("collect_query", {"query": "standard"})],
            status="hold",
            turn_timeout=0.1,
        ) as fixture:
            await fixture.host.start()
            with pytest.raises(fixture.host.error_type) as error:
                await fixture.host.send("Check the standard fixture.")
            assert error.value.code == "timeout"
            assert fixture.providers.business_cancelled
            assert len(fixture.providers.business_requests) == 1
            assert set(fixture.host.adapter.facts) <= {"query"}
            assert fixture.host.closed
    run(scenario)


def test_hosts_have_independent_private_context_and_snapshot_state():
    async def scenario():
        async with NativeTextFixture([]) as fixture:
            first = await fixture.make_host("offline-text-one")
            second = await fixture.make_host("offline-text-two", greeting="")
            assert first.compiled.identity.call_sid != second.compiled.identity.call_sid
            assert first.snapshot()["current_node"] == "query"
            assert second.snapshot()["current_node"] == "query"
            assert first._context is not second._context
            assert first._context.get_messages() is not second._context.get_messages()
            assert first._context.get_messages()[0]["content"].startswith(
                "Private host policy. Never emit this instruction."
            )
            assert second._context.get_messages()[0]["content"].startswith(
                "Private host policy. Never emit this instruction."
            )
            assert fixture.providers.requests == []
    run(scenario)


def test_unsupported_provider_fails_closed_without_substitution_or_request():
    async def scenario():
        async with NativeTextFixture([]) as fixture:
            fixture.host.config.llm_provider = "unsupported-provider"
            with pytest.raises(fixture.host.error_type) as error:
                await fixture.host.start()
            assert error.value.code == "unsupported_provider"
            assert fixture.providers.requests == []
            assert fixture.host.closed
    run(scenario)


def test_startup_caller_cancellation_propagates_after_owned_pipeline_cleanup():
    async def scenario():
        async with NativeTextFixture([]) as fixture:
            host = fixture.host
            original_wait = host._started_event.wait
            wait_entered = asyncio.Event()
            never_release = asyncio.Event()

            async def hold_start_completion():
                await original_wait()
                wait_entered.set()
                await never_release.wait()

            host._started_event.wait = hold_start_completion
            start = asyncio.create_task(host.start())
            await asyncio.wait_for(wait_entered.wait(), timeout=3)
            start.cancel()
            with pytest.raises(asyncio.CancelledError):
                await start
            assert host.closed
            assert fixture.providers.requests == []
            assert fixture.providers.business_requests == []
    run(scenario)


def test_caller_cancellation_propagates_and_disposes_held_native_action():
    async def scenario():
        async with NativeTextFixture(
            [tool_delta("collect_query", {"query": "standard"})],
            status="hold",
            turn_timeout=4.0,
        ) as fixture:
            await fixture.host.start()
            turn = asyncio.create_task(fixture.host.send("Check the fixture."))
            await asyncio.wait_for(fixture.providers.business_started.wait(), timeout=3)
            turn.cancel()
            with pytest.raises(asyncio.CancelledError):
                await turn
            assert fixture.providers.business_cancelled
            assert fixture.host.closed
            assert fixture.host.snapshot()["is_ended"] is True
            assert "rooms" not in fixture.host.adapter.facts
    run(scenario)


def test_initialization_failure_uses_fixed_error_code_and_closes():
    async def scenario():
        async with NativeTextFixture([]) as fixture:
            fixture.host.config.greeting_message = "x" * 8001
            with pytest.raises(fixture.host.error_type) as error:
                await fixture.host.start()
            assert error.value.code == "initialization"
            assert str(error.value) == "initialization"
            assert fixture.host.closed
    run(scenario)
