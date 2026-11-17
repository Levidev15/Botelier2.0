"""The real TextHost keeps one SDK startup callback alive across previews."""

import asyncio
from copy import deepcopy

import pytest

from application_support import API_KEYS, make_config
from native_effect_io import NativeEffectsFixture
from native_text_io import NativeTextFixture
from node_contract_io import NodeProviders


def test_actual_text_host_resumes_sequential_startup_actions_without_a_model_turn():
    async def scenario():
        from botelier.services.native_simulation_session import (
            NativeSimulationError, NativeSimulationRegistry, NativeSimulationSession,
        )
        from botelier.voice.flows.native_action_preview import NativeActionPreview
        from botelier.voice.flows.native_dev_host import NativeFlowDevPolicy
        from botelier.voice.flows.native_graph import compile_flow
        from botelier.voice.flows.native_text_host import NativeTextHost
        from test_native_actions import _compiled_custom_read

        async with NativeEffectsFixture() as fixture:
            providers = NodeProviders([])
            async with NativeTextFixture(
                [], create_host=False, providers=providers,
            ):
                source = _compiled_custom_read(fixture.identity).config()
                start_node = next(
                    node for node in source["nodes"] if node["id"] == "start"
                )
                start_node["data"]["waitForResponse"] = False
                lookup_source = next(
                    node for node in source["nodes"] if node["id"] == "lookup"
                )
                lookup_source["data"]["api"]["url"] = "https://api.fixture.invalid/items"
                lookup = deepcopy(lookup_source)
                lookup["id"] = "lookup2"
                source["nodes"].insert(
                    next(
                        index for index, node in enumerate(source["nodes"])
                        if node["id"] == "done"
                    ),
                    lookup,
                )
                source["edges"] = [
                    {"id": "start-lookup", "source": "start", "target": "lookup"},
                    {
                        "id": "lookup-lookup2", "source": "lookup",
                        "target": "lookup2", "sourceHandle": "success",
                    },
                    {
                        "id": "lookup2-done", "source": "lookup2",
                        "target": "done", "sourceHandle": "success",
                    },
                ]
                compiled = compile_flow(source, fixture.identity)
                host = NativeTextHost(
                    compiled, config=make_config(
                        greeting_message="",
                        system_prompt="Private test system prompt.",
                        llm_provider="openai", llm_model="gpt-4.1-mini",
                        llm_temperature=0.2, llm_max_tokens=64,
                    ),
                    api_keys=API_KEYS, session_factory=fixture.factory,
                    turn_timeout=5, preview=NativeActionPreview(timeout=5),
                )
                registry = NativeSimulationRegistry()
                owner = "native-preview-owner"
                session_id = registry.reserve(owner)
                session = NativeSimulationSession(
                    session_id=session_id, owner_user_id=owner,
                    account_id=fixture.account_id,
                    runtime={
                        "engine": "native_pilot", "source": "published",
                        "execution_mode": "preview", "effect_mode": "simulation",
                    },
                    variables_to_collect=[], host=host, registry=registry,
                    session_map={}, policy_provider=lambda: NativeFlowDevPolicy(
                        "development", "1",
                    ),
                )
                try:
                    started = await session.start()
                    pending = started["state"]["pending_preview"]
                    assert pending is not None, {
                        "state": started["state"],
                        "host": host.snapshot(),
                        "adapter": host.adapter.snapshot(),
                        "failure": getattr(host, "_failure", None),
                        "preview_effects": host.preview.effects,
                        "runtime": started["runtime"],
                    }
                    assert pending["node_id"] == "lookup"
                    assert pending["source_kind"] == "http"
                    assert started["runtime"]["execution_mode"] == "preview"
                    assert started["runtime"]["effect_mode"] == "simulation"
                    assert not any(item.get("stream") for item in providers.requests)

                    with pytest.raises(NativeSimulationError) as pending_turn:
                        await session.send("A normal caller turn is not accepted here.")
                    assert pending_turn.value.code == "native_simulation_preview_pending"
                    assert session._turn_count == 0

                    with pytest.raises(NativeSimulationError) as stale:
                        await session.send("", preview_result={
                            "request_id": "wrong-session-request",
                            "status_code": 200, "data": {"amount": 1},
                        })
                    assert stale.value.code == "native_simulation_preview_request_mismatch"
                    invalid_samples = [
                        {"request_id": pending["request_id"], "status_code": 200},
                        {
                            "request_id": pending["request_id"], "status_code": 200,
                            "data": {}, "data_json": "{}",
                        },
                        {
                            "request_id": pending["request_id"], "status_code": True,
                            "data_json": "{}",
                        },
                        {
                            "request_id": pending["request_id"], "status_code": 200,
                            "data_json": '{"amount":NaN}',
                        },
                        {
                            "request_id": pending["request_id"], "status_code": 200,
                            "data_json": "x" * 65_537,
                        },
                    ]
                    for invalid_sample in invalid_samples:
                        with pytest.raises(NativeSimulationError) as invalid:
                            await session.send("", preview_result=invalid_sample)
                        assert invalid.value.code == "native_simulation_preview_invalid"
                        assert session.get_state_snapshot()["pending_preview"][
                            "request_id"
                        ] == pending["request_id"]
                    assert session.get_state_snapshot()["pending_preview"]["request_id"] == pending[
                        "request_id"
                    ]

                    first = await session.send("", preview_result={
                        "request_id": pending["request_id"], "status_code": 200,
                        "data_json": (
                            '{"amount":0,"tax_included":false,'
                            '"id":9007199254740993}'
                        ),
                    })
                    second_pending = first["state"]["pending_preview"]
                    assert second_pending["node_id"] == "lookup2"
                    assert second_pending["request_id"] != pending["request_id"]
                    assert first["state"]["safe_preview_effects"] == [
                        {
                            "kind": "api_request", "node_id": "lookup",
                            "simulated": True,
                        },
                    ]

                    finished = await session.send("", preview_result={
                        "request_id": second_pending["request_id"],
                        "status_code": 200,
                        "data": {"amount": 0, "tax_included": False},
                    })
                    assert finished["state"]["is_complete"] is True
                    assert finished["state"]["pending_preview"] is None
                    assert finished["state"]["safe_preview_effects"] == [
                        {
                            "kind": "api_request", "node_id": "lookup",
                            "simulated": True,
                        },
                        {
                            "kind": "api_request", "node_id": "lookup2",
                            "simulated": True,
                        },
                    ]
                    assert session._turn_count == 0
                    assert not any(item.get("stream") for item in providers.requests)
                    assert providers.business_requests == []
                    db = fixture.factory()
                    try:
                        assert db.query(
                            fixture.effect_models["OperationIdempotency"],
                        ).count() == 0
                    finally:
                        db.close()
                finally:
                    await session.close()

    asyncio.run(scenario())

def test_preview_submission_schema_rejects_extra_provider_payload_fields():
    from pydantic import ValidationError
    from botelier.api.simulation import NativePreviewSubmission

    with pytest.raises(ValidationError):
        NativePreviewSubmission(
            request_id="id", status_code=200, data={},
            headers={"Authorization": "secret"},
        )


def test_preview_submission_schema_requires_one_bounded_strict_json_payload():
    from pydantic import ValidationError
    from botelier.api.simulation import NativePreviewSubmission
    from botelier.voice.flows.native_action_preview import NativePreviewResponse

    sample = NativePreviewSubmission(
        request_id="id", status_code=200,
        data_json='{"id":9007199254740993}',
    )
    response = NativePreviewResponse(
        status_code=sample.status_code, data_json=sample.data_json,
    )
    assert response.data["id"] == 9007199254740993
    invalid = [
        {"request_id": "id", "status_code": 200},
        {
            "request_id": "id", "status_code": 200,
            "data": {}, "data_json": "{}",
        },
        {
            "request_id": "id", "status_code": True, "data_json": "{}",
        },
        {
            "request_id": "id", "status_code": 200, "data": {}, "success": "true",
        },
        {
            "request_id": "id", "status_code": 200, "data_json": "{",
        },
        {
            "request_id": "id", "status_code": 200,
            "data_json": "x" * 65_537,
        },
    ]
    for payload in invalid:
        with pytest.raises(ValidationError):
            NativePreviewSubmission(**payload)


def test_actual_text_host_keeps_the_original_sdk_turn_through_preview_continuation():
    async def scenario():
        import json

        from botelier.services.native_simulation_session import (
            NativeSimulationRegistry, NativeSimulationSession,
        )
        from botelier.voice.flows.native_action_preview import NativeActionPreview
        from botelier.voice.flows.native_dev_host import NativeFlowDevPolicy
        from botelier.voice.flows.native_graph import compile_flow
        from botelier.voice.flows.native_text_host import NativeTextHost
        from test_native_actions import _compiled_custom_read

        class ToolReplyProviders(NodeProviders):
            async def http(self, request):
                if request.headers.get("content-type", "").startswith("application/json"):
                    try:
                        body = json.loads(request.content)
                    except (TypeError, ValueError):
                        body = {}
                    if body.get("stream") is True:
                        tools = body.get("tools", [])
                        collect_name = next(
                            item["function"]["name"]
                            for item in tools
                            if item.get("type") == "function"
                            and item.get("function", {}).get("name", "").startswith(
                                "native_collect_query"
                            )
                        )
                        self.replies = ({
                            "tool_calls": [{
                                "index": 0, "id": "preview-user-turn-call",
                                "type": "function",
                                "function": {
                                    "name": collect_name,
                                    "arguments": json.dumps({"query": "standard"}),
                                },
                            }],
                        },)
                return await super().http(request)

        async with NativeEffectsFixture() as fixture:
            providers = ToolReplyProviders([""])
            async with NativeTextFixture(
                [], create_host=False, providers=providers,
            ):
                source = _compiled_custom_read(fixture.identity).config()
                source["nodes"][0]["data"]["waitForResponse"] = False
                lookup_source = next(
                    node for node in source["nodes"] if node["id"] == "lookup"
                )
                lookup_source["data"]["api"]["url"] = (
                    "https://api.fixture.invalid/items/{{query}}"
                )
                query = {
                    "id": "collect_query", "type": "collect_slot",
                    "data": {"slot": {
                        "variableKey": "query", "prompt": "Which item?",
                    }},
                }
                source["nodes"].insert(1, query)
                lookup2 = deepcopy(lookup_source)
                lookup2["id"] = "lookup2"
                source["nodes"].insert(3, lookup2)
                source["edges"] = [
                    {"id": "start-query", "source": "start", "target": "collect_query"},
                    {"id": "query-lookup", "source": "collect_query", "target": "lookup"},
                    {"id": "lookup-lookup2", "source": "lookup", "target": "lookup2",
                     "sourceHandle": "success"},
                    {"id": "lookup2-done", "source": "lookup2", "target": "done",
                     "sourceHandle": "success"},
                ]
                compiled = compile_flow(source, fixture.identity)
                host = NativeTextHost(
                    compiled,
                    config=make_config(
                        greeting_message="", system_prompt="Private test system prompt.",
                        llm_provider="openai", llm_model="gpt-4.1-mini",
                        llm_temperature=0.2, llm_max_tokens=64,
                    ),
                    api_keys=API_KEYS, session_factory=fixture.factory,
                    turn_timeout=8, preview=NativeActionPreview(timeout=8),
                )
                registry = NativeSimulationRegistry()
                owner = "native-preview-turn-owner"
                session_id = registry.reserve(owner)
                session = NativeSimulationSession(
                    session_id=session_id, owner_user_id=owner,
                    account_id=fixture.account_id,
                    runtime={
                        "engine": "native_pilot", "source": "published",
                        "execution_mode": "preview", "effect_mode": "simulation",
                    },
                    variables_to_collect=[], host=host, registry=registry,
                    session_map={}, policy_provider=lambda: NativeFlowDevPolicy(
                        "development", "1",
                    ),
                )
                try:
                    await session.start()
                    try:
                        first = await session.send("standard")
                    except Exception as error:
                        raise AssertionError({
                            "error": getattr(error, "code", type(error).__name__),
                            "requests": providers.requests,
                            "blocked_business": providers.business_requests,
                        }) from error
                    pending = first["state"]["pending_preview"]
                    assert pending["node_id"] == "lookup"
                    assert session._turn_count == 1
                    streamed = [item for item in providers.requests if item.get("stream")]
                    assert len(streamed) == 1

                    next_step = await session.send("", preview_result={
                        "request_id": pending["request_id"], "status_code": 200,
                        "data": {"amount": 0, "tax_included": False},
                    })
                    second_pending = next_step["state"]["pending_preview"]
                    assert second_pending["node_id"] == "lookup2"
                    assert len([
                        item for item in providers.requests if item.get("stream")
                    ]) == 1

                    finished = await session.send("", preview_result={
                        "request_id": second_pending["request_id"],
                        "status_code": 200,
                        "data": {"amount": 0, "tax_included": False},
                    })
                    assert finished["state"]["is_complete"] is True
                    assert session._turn_count == 1
                    assert len([
                        item for item in providers.requests if item.get("stream")
                    ]) == 1
                    assert providers.business_requests == []
                finally:
                    await session.close()

    asyncio.run(scenario())
