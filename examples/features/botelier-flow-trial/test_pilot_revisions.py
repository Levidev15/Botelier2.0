"""Visit authority through actual native dispatch, read and transition queues.

Only tests explicitly drive host re-entry. No caller correction route is
enabled. Queue gates delegate to the real SDK after fixing the ordering; they
do not supply handler results or implement another transition manager.
"""

import asyncio
import json
import re
from unittest.mock import patch

import pytest

from node_contract_io import PRESENTATION, WAIT, speech, tool_delta, tool_result, wait_for_speech
from pilot_io import (
    REVISION_COLLISION, PilotCall, PilotProviders, native_schema, native_tool_names, pilot_config,
)
from test_pilot_reentry import enter_node


def current_schema(call):
    return native_schema(call, "query")


def settled_result(call, call_id):
    try:
        result = tool_result(call, call_id)
    except (StopIteration, json.JSONDecodeError):
        return None
    return result if isinstance(result, dict) and result.get("status") != "IN_PROGRESS" else None


@pytest.mark.parametrize("reuse_config", [False, True])
@pytest.mark.parametrize("replayed_query", ["standard", "premium"])
def test_retained_wrapper_cannot_regain_authority_at_the_same_unaccepted_node(
    reuse_config, replayed_query,
):
    async def scenario():
        async with PilotCall(providers=PilotProviders([])) as call:
            await call.activate()
            node = call.adapter._node(call.compiled.query, "Which current fixture?")
            await enter_node(call, node)
            retained = current_schema(call)
            await enter_node(call, node if reuse_config else call.adapter._node(
                call.compiled.query, "Which newest fixture?",
            ))
            result = await call.invoke_retained(retained, {"query": replayed_query})
            assert result == {"status": "rejected", "reason": "busy_or_stale"}
            assert call.adapter.facts == {}
            assert call.providers.business_requests == []
            assert WAIT not in speech(call)
            assert call.adapter.manager.current_node == "query"
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_an_actually_queued_call_cannot_use_a_replacement_handlers_authority():
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}, call_id="queued-old"),
            "That earlier answer was ignored.",
        ])
        async with PilotCall(providers=providers) as call:
            await call.activate()
            queued, release = asyncio.Event(), asyncio.Event()
            llm = call.created[2]
            run = llm._run_function_call
            original_arguments = []
            original_names = []

            async def held_execution(item):
                # The actual SDK has already created/queued this runner item.
                # Pause BEFORE its real execution-time registry lookup.
                if item.tool_call_id == "queued-old":
                    original_arguments.append(dict(item.arguments))
                    original_names.append(item.function_name)
                    queued.set()
                    await release.wait()
                return await run(item)

            with patch.object(llm, "_run_function_call", held_execution):
                try:
                    await providers.user_turn("Please check the standard fixture.")
                    await call.wait_until(queued.is_set)
                    await enter_node(call, call.adapter._node(
                        call.compiled.query, "Which newest fixture?",
                    ))
                    release.set()
                    await call.wait_until(lambda: settled_result(call, "queued-old"))
                    assert tool_result(call, "queued-old") == {
                        "status": "rejected", "reason": "busy_or_stale",
                    }
                    await wait_for_speech(call, "That earlier answer was ignored.")
                finally:
                    release.set()
            assert original_arguments[0]["query"] == "standard"
            assert call.adapter.facts == {}
            assert providers.business_requests == []
            assert WAIT not in speech(call)
            assert PRESENTATION not in speech(call)
            assert set(original_arguments[0]) == {"query"}
            assert original_names[0] != current_schema(call).name
            assert original_names[0] not in " ".join(speech(call))
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_a_read_cannot_commit_after_the_same_node_gets_a_new_visit():
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}, call_id="old-read"),
            "The earlier lookup is no longer active.",
            tool_delta("collect_query", {"query": "premium"}, call_id="fresh-read"),
        ], status="hold")
        async with PilotCall(providers=providers) as call:
            await call.activate()
            await providers.user_turn("Please check the standard fixture.")
            await call.wait_until(providers.business_started.is_set)
            await enter_node(call, call.adapter._node(
                call.compiled.query, "Which newest fixture?",
            ))
            providers.release_business.set()
            await call.wait_until(lambda: settled_result(call, "old-read"))
            assert tool_result(call, "old-read") == {
                "status": "rejected", "reason": "busy_or_stale",
            }
            await wait_for_speech(call, "The earlier lookup is no longer active.")
            assert call.adapter.facts == {"query": "standard"}
            assert call.adapter.manager.current_node == "query"
            assert PRESENTATION not in speech(call)
            assert len(providers.business_requests) == 1

            # The old read must neither spend nor strand the current visit.
            # This is host-driven re-entry of a not-yet-accepted query, not an
            # enabled caller edit of an already accepted earlier answer.
            await providers.user_turn("Please check premium.", turn_index=1)
            await wait_for_speech(call, PRESENTATION)
            assert tool_result(call, "fresh-read")["outcome"] == "has_results"
            assert [dict(request.url.params) for request in providers.business_requests] == [
                {"query": "standard"}, {"query": "premium"},
            ]
            assert call.adapter.facts["query"] == "premium"
            assert set(call.adapter.facts) == {"query", "rooms", "price"}
            assert speech(call).count(PRESENTATION) == 1
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_a_deferred_native_transition_cannot_enter_after_its_source_visit_changed():
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}, call_id="deferred-old"),
        ])
        async with PilotCall(providers=providers) as call:
            await call.activate()
            pending, release = asyncio.Event(), asyncio.Event()
            manager = call.adapter.manager
            original_name = current_schema(call).name
            execute = manager._execute_transition
            callbacks = []

            async def held_transition(info):
                # Native Flows has removed its pending slot and captured the
                # real transition in its asynchronous context-updated task.
                callbacks.append(asyncio.current_task())
                pending.set()
                await release.wait()
                return await execute(info)

            with patch.object(manager, "_execute_transition", held_transition):
                try:
                    await providers.user_turn("Please check the standard fixture.")
                    await call.wait_until(pending.is_set)
                    assert tool_result(call, "deferred-old")["outcome"] == "has_results"
                    await enter_node(call, call.adapter._node(
                        call.compiled.query, "Which newest fixture?",
                    ))
                    fresh_guidance = call.adapter._guidance
                    release.set()
                    outcomes = await asyncio.gather(*callbacks, return_exceptions=True)
                finally:
                    release.set()
            assert call.adapter.manager.current_node == "query"
            assert call.adapter._guidance is fresh_guidance
            assert native_tool_names(call) == {"collect_query"}
            assert current_schema(call).name != original_name
            assert PRESENTATION not in speech(call)
            assert len(providers.business_requests) == 1
            # A safe native entry rejection may propagate a categorized
            # FlowError. It must never silently apply the obsolete transition.
            assert all(result is None or "pilot_stale_entry" in str(result) for result in outcomes)
            assert tool_result(call, "deferred-old")["data"]["rooms"] == [
                {"name": "Standard", "price": 0},
            ]
            await call.finish("graceful_end")
            # The supported pre-action guard aborts stale entry via FlowError.
            # Keep all three precise native diagnostics visible and expected;
            # do not suppress logging or allow unrelated task errors.
            stale = "Failed to execute action pilot_enter: pilot_stale_entry"
            call.assert_clean(expected_errors=[
                re.escape(f"Error setting node choice: {stale}"),
                re.escape(f"Error executing transition: Failed to set node choice: {stale}"),
                rf"LLMAssistantAggregator#\d+::{re.escape(original_name)}:deferred-old:"
                rf"on_context_updated unexpected exception \([^)]+\): "
                + re.escape(f"Failed to set node choice: {stale}"),
            ])
    asyncio.run(scenario())


@pytest.mark.parametrize("name", [
    "collect_query", REVISION_COLLISION, "pilot_collect_untrusted",
])
def test_bare_or_forged_visit_names_cannot_authorize_a_native_or_mcp_action(name):
    async def scenario():
        providers = PilotProviders([
            tool_delta(name, {"query": "standard"}),
            "Please answer the current question.",
        ], bind_native_names=False)
        async with PilotCall(providers=providers, mcp=True) as call:
            await call.activate()
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, "Please answer the current question.")
            result = tool_result(call)
            assert result == f"The function `{name}` is not currently available."
            assert call.adapter.facts == {}
            assert providers.business_requests == []
            assert not any(message["method"] == "tools/call" for message in providers.mcp_messages)
            assert WAIT not in speech(call)
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_a_tool_identity_from_a_disposed_call_has_no_authority_in_another_call():
    async def scenario():
        async with PilotCall(providers=PilotProviders([])) as previous:
            await previous.activate()
            old_name = current_schema(previous).name
            await previous.finish("graceful_end")
            previous.assert_clean()
        providers = PilotProviders([
            tool_delta(old_name, {"query": "standard"}),
            "Please answer this call's question.",
        ], bind_native_names=False)
        async with PilotCall(providers=providers) as current:
            await current.activate()
            assert current_schema(current).name != old_name
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(current, "Please answer this call's question.")
            result = tool_result(current)
            assert result == f"The function `{old_name}` is not currently available."
            assert current.adapter.facts == {}
            assert current.providers.business_requests == []
            assert WAIT not in speech(current)
            await current.finish("graceful_end")
            current.assert_clean()
    asyncio.run(scenario())


@pytest.mark.parametrize("reuse_config", [False, True])
def test_each_visit_gets_a_fresh_callable_without_accumulating_registered_handlers(reuse_config):
    async def scenario():
        replies = [f"Waiting for fixture answer {visit}." for visit in range(4)]
        providers = PilotProviders(replies)
        async with PilotCall(providers=providers, mcp=True) as call:
            await call.activate()
            reusable = call.adapter._node(call.compiled.query, "Which current fixture?")
            seen = {current_schema(call).name}
            for index, reply in enumerate(replies):
                await enter_node(call, reusable if reuse_config else call.adapter._node(
                    call.compiled.query, "Which current fixture?",
                ))
                name = current_schema(call).name
                assert name not in seen
                seen.add(name)
                await providers.user_turn("I have a question.", turn_index=index)
                await call.wait_until(lambda: (
                    reply in speech(call) and not call.created[16].get_audio_contexts()
                    and not call.created[5]._bot_speaking
                ))
                # Actual native inference must install the NEW handler and
                # prune obsolete auto-registered ones. No SDK registry writes.
                owned = {registered for registered in call.created[2]._functions
                         if isinstance(registered, str) and registered.startswith("pilot_collect_")}
                assert owned == {name}
                assert "mcp_lookup" in call.created[2]._functions
            assert len([body for body in providers.requests if body.get("stream")]) == 4
            assert call.providers.business_requests == []
            assert call.adapter.facts == {}
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_the_longest_saved_node_id_still_has_a_valid_callable_wire_name():
    async def scenario():
        config = pilot_config()
        long_id = "query_" + "x" * 42
        for node in config["nodes"]:
            if node["id"] == "query":
                node["id"] = long_id
        for edge in config["edges"]:
            for key in ("source", "target"):
                if edge[key] == "query":
                    edge[key] = long_id
        providers = PilotProviders([tool_delta(f"collect_{long_id}", {"query": "standard"})])
        async with PilotCall(config=config, providers=providers) as call:
            await call.activate()
            name = native_schema(call, long_id).name
            assert len(name) <= 64 and re.fullmatch(r"[A-Za-z0-9_-]+", name)
            await providers.user_turn("Please check the standard fixture.")
            await wait_for_speech(call, PRESENTATION)
            assert tool_result(call)["outcome"] == "has_results"
            assert len(providers.business_requests) == 1
            assert call.compiled.query.node_id == long_id
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_the_adapter_rejects_a_global_that_claims_the_visit_namespace():
    async def scenario():
        from pipecat.flows import FlowsFunctionSchema

        async def forbidden(arguments, manager):
            pytest.fail("A namespace collision must never dispatch")

        async with PilotCall(providers=PilotProviders([])) as call:
            await call.activate()
            collision = FlowsFunctionSchema(
                name=REVISION_COLLISION, description="An unauthorized visit identity",
                properties={}, required=[], handler=forbidden,
            )
            with pytest.raises(ValueError, match="^native_global_collision$"):
                call.adapter_type(
                    call.compiled, llm=call.created[2], worker=call.created[1],
                    context_aggregator=call.created[3], session_factory=call.actions.session,
                    global_functions=[collision],
                )
            assert call.providers.business_requests == []
            assert call.adapter.facts == {}
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())
