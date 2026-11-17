"""Actual SDK/context/TTS boundary tests, with controlled model and action I/O."""

import asyncio
import html
import json

import pytest

from native_graph_io import GraphProviders, NativeGraphPipelineCall
from test_native_quote_actions import caller_facts, configuration
from test_native_quote_bridge import quote_definition
from test_reservation_quote_contract import NOW


def privacy_definition():
    source = quote_definition()
    source["nodes"][0]["data"]["waitForResponse"] = False
    source["variables"].extend([
        {"key": "name", "type": "text"},
        {"key": "room_label", "type": "text"},
    ])
    source["nodes"][1:1] = [
        {"id": "name", "type": "collect_slot", "data": {"slot": {
            "variableKey": "name", "type": "text", "prompt": "Name?",
        }}},
        {"id": "lookup", "type": "api_request", "data": {"api": {
            "apiSource": "custom", "url": "https://example.invalid/quote",
            "responseMapping": {
                "provider_quote": "$.quote", "selection": "$.selection",
                "room_label": "$.label", "quote_fingerprint": "$.fingerprint",
            },
            "responseProjection": {"fields": [{"variable": "room_label"}]},
        }}},
        {"id": "message", "type": "message", "data": {
            "message": "Room {{room_label}}.", "deliveryMode": "static",
            "waitForResponse": True,
        }},
    ]
    source["edges"] = [
        {"id": "start-name", "source": "start", "target": "name"},
        {"id": "name-lookup", "source": "name", "target": "lookup"},
        {"id": "lookup-message", "source": "lookup", "target": "message",
         "sourceHandle": "success"},
        {"id": "message-quote", "source": "message", "target": "quote"},
        {"id": "quote-done", "source": "quote", "target": "done",
         "sourceHandle": "success"},
    ]
    return source


@pytest.mark.parametrize("case", ["private_url", "html_alias", "fingerprint", "normal"])
def test_fresh_action_data_is_checked_before_real_sdk_context_or_tts(case):
    async def scenario():
        from botelier.voice.flows.native_execution import NativeActionResult
        from botelier.voice.flows.native_graph import compile_flow
        from botelier.voice.flows.native_quote_actions import prepare_quote
        from node_contract_io import speech, tool_delta
        from test_native_graph import identity

        source, facts = privacy_definition(), caller_facts()
        facts["provider_quote"]["checkout_url"] += "&copy=1"
        prepared = prepare_quote(configuration(), facts, now=NOW)
        private_url = facts["provider_quote"]["checkout_url"]
        fingerprint = prepared.validated.fingerprint
        room_label = (
            fingerprint if case == "fingerprint" else
            "Suite" if case == "normal" else private_url
        )
        projected_label = html.unescape(room_label) if case == "html_alias" else room_label
        calls = []

        async def execute(node, current, *, confirmation):
            calls.append(node.node_id)
            if node.node_id == "lookup":
                assert current["name"] == "Ada"
                return NativeActionResult(
                    True, variables={
                        "provider_quote": facts["provider_quote"],
                        "selection": facts["selection"], "room_label": room_label,
                        "quote_fingerprint": fingerprint,
                    },
                    llm_data={"room_label": projected_label},
                )
            return prepare_quote(configuration(), current, now=NOW).result

        call = NativeGraphPipelineCall(
            compile_flow(source, identity()),
            providers=GraphProviders([
                tool_delta("collect_name", {"name": "Ada"}),
            ]),
            execute_action=execute,
        )
        async with call:
            await call.activate()
            await call.wait_until(lambda: call.adapter.manager.current_node == "name")
            await call.providers.user_turn("Ada", turn_index=0)
            await call.wait_until(lambda: (
                call.adapter.snapshot()["status"] == "failed"
                or call.adapter.manager.current_node == "message"
            ))
            snapshot = call.adapter.snapshot()
            if case == "normal":
                assert snapshot["status"] != "failed", snapshot
                await call.wait_until(lambda: "Room Suite." in speech(call))
                assert call.adapter.manager.current_node == "message"
            else:
                assert snapshot["status"] == "failed", snapshot
                assert snapshot["failure_reason"] == "quote_private_projection"
            evidence = json.dumps({
                "model_requests": call.providers.requests,
                "sdk_context": call.created[4].get_messages(),
                "spoken": speech(call),
            }, ensure_ascii=False)
            assert private_url not in evidence
            assert fingerprint not in evidence
            assert html.unescape(private_url) not in evidence
            assert calls == ["lookup"]
            assert call.providers.business_requests == []
            await call.adapter.close()
        call.assert_clean()

    asyncio.run(asyncio.wait_for(scenario(), 20))
