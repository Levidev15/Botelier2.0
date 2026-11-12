"""Native saved-flow behavior through the actual guarded coordinator/worker."""

import asyncio
import json

import pytest

from lifecycle_io import CALL_SID
from node_contract_io import ERROR, PRESENTATION, PRIVATE, WAIT, speech, tool_delta, tool_result, wait_for_speech
from pilot_io import PilotCall, PilotProviders, native_schema, native_tool_names, pilot_config


def tools(call):
    return native_tool_names(call)


def test_native_collection_runs_one_connected_read_and_issues_the_next_question_once():
    async def scenario():
        providers = PilotProviders([tool_delta("collect_query", {"query": "standard"})])
        async with PilotCall(providers=providers) as call:
            await call.activate()
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, PRESENTATION)
            await call.wait_for_node("choice")
            assert call.adapter.manager.current_node == "choice"
            assert tools(call) == {"collect_choice"}
            assert call.adapter.facts == {
                "query": "standard", "rooms": [{"name": "Standard", "price": 0}], "price": 0,
            }
            assert speech(call)[1:] == ["Which fixture?", WAIT, PRESENTATION]
            assert len(providers.business_requests) == 1
            assert str(providers.business_requests[0].url) == (
                "https://api.fixture.invalid/search?query=standard"
            )
            assert sum(bool(body.get("stream")) for body in providers.requests) == 1
            result = tool_result(call)
            assert result["outcome"] == "has_results"
            assert result["action_node_id"] == "lookup"
            assert result["presentation_node_id"] == "response"
            assert result["current_node_id"] == "choice"
            assert result["flow_version_id"] == "offline-version"
            assert PRIVATE not in " ".join(speech(call))
            assert all(not mapper._flow_executors for mapper in call.handler.call_mappers.values())
            assert [type(row).__name__ for row in call.actions.writes] == [
                "IntegrationCallLog", "IntegrationActionInvocation", "IntegrationCallLog",
            ]
            invocation = call.actions.writes[1]
            assert invocation.account_id == "00000000-0000-0000-0000-000000000101"
            assert invocation.call_sid == CALL_SID
            assert invocation.tool_id == "offline-flow"
            assert invocation.flow_tool_id == "offline-flow"
            assert invocation.flow_version_id == "offline-version"
            assert invocation.node_id == "lookup"
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("arguments", [
    {}, {"query": ""}, {"query": "   "}, {"query": 0}, {"query": False},
    {"query": []}, {"query": {}}, {"query": "standard", "method": "POST"},
    {"query": "x" * 2049},
])
def test_invalid_tool_arguments_never_become_a_fact_request_or_direct_wait_announcement(arguments):
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_query", arguments), "Please provide a fixture query.",
        ])
        async with PilotCall(providers=providers) as call:
            await call.activate()
            await providers.user_turn("Please check a fixture.")
            await wait_for_speech(call, "Please provide a fixture query.")
            assert tool_result(call)["reason"] == "invalid_arguments"
            assert tool_result(call)["status"] == "rejected"
            assert call.adapter.facts == {}
            assert call.adapter.manager.current_node == "query"
            assert providers.business_requests == []
            assert WAIT not in speech(call)
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("payload,outcome,text", [
    ({"rooms": []}, "no_results", "No fixture options were found. Try a different fixture?"),
    ({}, "failure", ERROR + " Try a different fixture?"),
    ({"rooms": None}, "failure", ERROR + " Try a different fixture?"),
    ({"rooms": {"name": "Not an array"}}, "failure", ERROR + " Try a different fixture?"),
    ({"rooms": [{"name": "Incomplete"}]}, "failure", ERROR + " Try a different fixture?"),
    ({"rooms": [{"name": {"raw": "Never speak dictionaries"}, "price": 0}]},
     "failure", ERROR + " Try a different fixture?"),
])
def test_only_explicit_empty_arrays_mean_no_results_and_malformed_data_uses_failure(
    payload, outcome, text,
):
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}),
        ], payload=payload)
        async with PilotCall(providers=providers) as call:
            await call.activate()
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, text)
            await call.wait_for_node("failure")
            assert call.adapter.manager.current_node == "failure"
            assert tools(call) == {"collect_failure"}
            assert tool_result(call)["outcome"] == outcome
            assert speech(call)[1:] == ["Which fixture?", WAIT, text]
            assert sum(bool(body.get("stream")) for body in providers.requests) == 1
            if outcome == "failure":
                assert call.adapter.facts == {"query": "standard"}
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("status", [403, 503, "timeout"])
def test_provider_failures_route_once_without_speaking_internal_error_payloads(status):
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}),
        ], status=status, payload={"message": "internal-provider-detail-marker"})
        async with PilotCall(providers=providers) as call:
            await call.activate()
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, ERROR + " Try a different fixture?")
            await call.wait_for_node("failure")
            assert tool_result(call)["outcome"] == "failure"
            assert call.adapter.facts == {"query": "standard"}
            assert len(providers.business_requests) == 1
            assert "internal-provider-detail-marker" not in " ".join(speech(call))
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_false_and_zero_are_rendered_as_scalars_not_replaced_with_empty_text():
    async def scenario():
        config = pilot_config()
        config["nodes"][-1]["data"]["responsePresentation"]["itemTemplate"] = (
            "{{name}} costs {{price}}; refundable {{refundable}}."
        )
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}),
        ], payload={"rooms": [{"name": "Standard", "price": 0, "refundable": False}]})
        async with PilotCall(config=config, providers=providers) as call:
            await call.activate()
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(
                call, "Here are the fixture options. Standard costs 0; refundable false. Which option?",
            )
            await call.wait_for_node("choice")
            assert call.adapter.facts["rooms"][0]["refundable"] is False
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("outro", ["", "  WHICH   option? "])
def test_the_next_prompt_is_canonical_and_not_duplicated_by_the_outro(outro):
    async def scenario():
        config = pilot_config()
        config["nodes"][-1]["data"]["responsePresentation"]["outroText"] = outro
        providers = PilotProviders([tool_delta("collect_query", {"query": "standard"})])
        async with PilotCall(config=config, providers=providers) as call:
            await call.activate()
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, PRESENTATION)
            await call.wait_for_node("choice")
            assert speech(call)[1:] == ["Which fixture?", WAIT, PRESENTATION]
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_next_node_replaces_only_owned_guidance_and_keeps_committed_history():
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}),
            tool_delta("collect_choice", {"choice": "Standard"}, call_id="choice-call"),
            "The selection is captured; no booking has been made.",
        ])
        async with PilotCall(providers=providers) as call:
            await call.wait_until(lambda: call.started.is_set())
            call.created[4].add_message({
                "role": "developer", "content": "Preserve the host's unrelated policy.",
            })
            await call.activate()
            baseline = [
                message.copy() for message in call.created[4].messages
                if message.get("role") == "system"
            ]
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, PRESENTATION)
            await call.wait_for_node("choice")
            await providers.user_turn("The Standard option.", turn_index=1)
            await wait_for_speech(call, "The selection is captured; no booking has been made.")
            requests = [body for body in providers.requests if body.get("stream")]
            assert len(requests) == 3
            messages = requests[1]["messages"]
            # The host deliberately refreshes the volatile clock tail on every
            # frame. Its actual policy prefix, not a frozen timestamp, must stay.
            policy = baseline[0]["content"].split("\n\n## ASSISTANT LOCAL TIME", 1)[0]
            assert messages[0]["role"] == "system"
            assert messages[0]["content"].startswith(policy + "\n\n## ASSISTANT LOCAL TIME")
            assert {"role": "developer", "content": "Preserve the host's unrelated policy."} in messages
            assert any(
                "Private next-node guidance" in message.get("content", "")
                for message in messages if message.get("role") == "developer"
            )
            assert all(PRIVATE not in message.get("content", "")
                       for message in messages if message.get("role") == "developer")
            committed = next(message for message in messages if message.get("role") == "tool")
            assert json.loads(committed["content"])["outcome"] == "has_results"
            assert committed["content"] != "IN_PROGRESS"
            assert any(message.get("role") == "user"
                       and "standard fixture" in message.get("content", "") for message in messages)
            assert call.adapter.facts["choice"] == "Standard"
            assert tool_result(call, "choice-call")["outcome"] == "paused"
            assert len(providers.business_requests) == 1
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_competing_and_spent_native_calls_cannot_repeat_a_read_wait_or_transition():
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}),
        ], status="hold")
        async with PilotCall(providers=providers) as call:
            await call.activate()
            retained = native_schema(call, "query")
            await providers.user_turn("Please check the standard fixture.")
            await call.wait_until(lambda: providers.business_started.is_set())
            competing = await call.invoke_retained(retained, {"query": "other"})
            assert competing == {"status": "rejected", "reason": "busy_or_stale"}
            assert len(providers.business_requests) == 1
            assert call.adapter.facts["query"] == "standard"
            providers.release_business.set()
            await wait_for_speech(call, PRESENTATION)
            await call.wait_for_node("choice")
            stale = await call.invoke_retained(retained, {"query": "other"})
            assert stale == {"status": "rejected", "reason": "busy_or_stale"}
            assert call.adapter.manager.current_node == "choice"
            assert speech(call)[1:] == ["Which fixture?", WAIT, PRESENTATION]
            assert len(providers.business_requests) == 1
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("late", [False, True])
@pytest.mark.parametrize("after_bookkeeping", [False, True])
@pytest.mark.parametrize("control", ["queued", "broadcast"])
def test_native_control_interruption_cancels_the_read_and_rejects_late_success(
    late, after_bookkeeping, control,
):
    async def scenario():
        from pipecat.frames.frames import InterruptionFrame
        from pipecat.processors.frame_processor import FrameDirection

        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}),
            "We can try later.",
        ], status="hold", late_business_result=late)
        async with PilotCall(providers=providers) as call:
            await call.activate()
            await providers.user_turn("Please check the standard fixture.")
            await call.wait_until(lambda: providers.business_started.is_set())
            if after_bookkeeping:
                await call.wait_until(lambda: any(
                    message.get("role") == "tool" and message.get("content") == "IN_PROGRESS"
                    for message in call.created[4].messages
                ))
            # The unchanged host mutes user frames during synchronous tools.
            # Exercise actual native cancellation at the LLM control boundary,
            # not a fabricated claim that spoken barge-in bypasses that policy.
            if control == "queued":
                await call.created[2].queue_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
            else:
                from botelier.voice.engine import AssistantLocalTimeContextUpdater

                # A broadcaster sends to its neighbors, not to itself. Use the
                # real processor immediately before the LLM and after user mute.
                control_source = next(
                    processor for processor in call.created[0].processors
                    if isinstance(processor, AssistantLocalTimeContextUpdater)
                )
                await control_source.broadcast_interruption()
            await call.wait_until(lambda: (
                providers.business_cancelled
                and not call.created[3].assistant().has_function_calls_in_progress
            ))
            await providers.user_turn("Actually stop that lookup.", turn_index=1)
            await wait_for_speech(call, "We can try later.")
            assert providers.business_cancelled
            assert providers.returned_late_result is late
            assert call.adapter.manager.current_node == "query"
            assert call.adapter.facts == {"query": "standard"}
            assert PRESENTATION not in speech(call)
            providers.release_business.set()
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("late", [False, True])
def test_hangup_disposes_owned_action_work_without_late_fact_or_speech_changes(late):
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}),
        ], status="hold", late_business_result=late)
        async with PilotCall(providers=providers) as call:
            await call.activate()
            await providers.user_turn("Please check the standard fixture.")
            await call.wait_until(lambda: providers.business_started.is_set())
            await call.finish("caller_hangup")
            assert providers.business_cancelled
            assert call.adapter.closed
            assert call.adapter.manager.current_node == "query"
            assert call.adapter.facts == {"query": "standard"}
            assert PRESENTATION not in speech(call)
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("scope", ["property_id", "account_id"])
def test_existing_connection_authorization_still_blocks_a_different_scope(scope):
    async def scenario():
        providers = PilotProviders([tool_delta("collect_query", {"query": "standard"})])
        async with PilotCall(providers=providers) as call:
            setattr(call.actions.integration, scope, "00000000-0000-0000-0000-000000000999")
            await call.activate()
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, ERROR + " Try a different fixture?")
            await call.wait_for_node("failure")
            assert tool_result(call)["outcome"] == "failure"
            assert providers.business_requests == []
            assert call.adapter.facts == {"query": "standard"}
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_collected_text_cannot_inject_another_query_parameter():
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard&hotel=other"}),
        ])
        async with PilotCall(providers=providers) as call:
            await call.activate()
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, PRESENTATION)
            await call.wait_for_node("choice")
            assert dict(providers.business_requests[0].url.params) == {
                "query": "standard&hotel=other",
            }
            assert call.compiled.identity.call_sid == CALL_SID
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("late", [False, True])
def test_total_read_deadline_is_failure_even_if_the_transport_returns_late_success(late):
    async def scenario():
        config = pilot_config()
        config["nodes"][2]["data"]["api"]["timeout"] = 1
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}),
        ], status="hold", late_business_result=late)
        async with PilotCall(config=config, providers=providers) as call:
            await call.activate()
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, ERROR + " Try a different fixture?")
            await call.wait_for_node("failure")
            assert providers.business_cancelled
            assert providers.returned_late_result is late
            assert call.adapter.facts == {"query": "standard"}
            assert tool_result(call)["outcome"] == "failure"
            assert len(providers.business_requests) == 1
            assert PRESENTATION not in speech(call)
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_two_calls_in_the_same_real_model_reply_can_only_accept_one_lookup():
    async def scenario():
        reply = tool_delta("collect_query", {"query": "standard"})
        duplicate = tool_delta("collect_query", {"query": "other"}, call_id="duplicate-call")[
            "tool_calls"
        ][0]
        duplicate["index"] = 1
        reply["tool_calls"].append(duplicate)
        providers = PilotProviders(
            [reply, "A lookup is already in progress."], status="hold", separate_call_chunks=True,
        )
        async with PilotCall(providers=providers) as call:
            await call.activate()
            await providers.user_turn("Please check the standard fixture.")
            await call.wait_until(lambda: providers.business_started.is_set())
            await call.wait_until(lambda: any(
                message.get("role") == "tool"
                and message.get("tool_call_id") == "duplicate-call"
                and message.get("content") != "IN_PROGRESS"
                for message in call.created[4].messages
            ))
            assert tool_result(call, "duplicate-call") == {
                "status": "rejected", "reason": "busy_or_stale",
            }
            providers.release_business.set()
            await wait_for_speech(call, PRESENTATION)
            await call.wait_for_node("choice")
            assert call.adapter.facts["query"] == "standard"
            assert len(providers.business_requests) == 1
            assert speech(call).count(WAIT) == 1
            assert speech(call).count(PRESENTATION) == 1
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_real_spoken_barge_in_during_result_audio_does_not_repeat_the_action():
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}),
            tool_delta("collect_choice", {"choice": "Standard"}, call_id="choice-call"),
            "The selection is captured; no booking has been made.",
        ], hold_tts_turn=4)
        async with PilotCall(providers=providers) as call:
            await call.activate()
            await providers.user_turn("Please check the standard fixture.")
            await call.wait_for_node("choice")
            await call.wait_until(lambda: (
                call.providers.tts.pending_metadata is not None
                and call.created[5]._bot_speaking
                and PRESENTATION in speech(call)
            ))
            await providers.user_turn("The Standard option.", turn_index=1)
            await wait_for_speech(call, "The selection is captured; no booking has been made.")
            assert call.adapter.facts["choice"] == "Standard"
            assert call.adapter.manager.current_node == "choice"
            assert len(providers.business_requests) == 1
            assert speech(call).count(PRESENTATION) == 1
            assert any(item.get("type") == "Interrupt" for item in providers.tts.sent)
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())
