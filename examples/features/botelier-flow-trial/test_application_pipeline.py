"""Construct the real application pipeline and inspect real outbound LLM data."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.processors.frame_processor import FrameProcessor

from application_support import API_KEYS, load_function_mapper, load_voice_engine, make_config


def date_schema(name="collect_date"):
    return FunctionSchema(
        name=name, description="Collect the active fixture date.",
        properties={"date": {"type": "string"}}, required=["date"],
    )


def make_pipeline(**config_overrides):
    engine = load_voice_engine()
    transport = SimpleNamespace(
        input=lambda: FrameProcessor(name="offline-input"),
        output=lambda: FrameProcessor(name="offline-output"),
    )

    async def handler(params):
        await params.result_callback({"accepted": True})

    return engine.VoiceEngineFactory.create_pipeline(
        make_config(**config_overrides), API_KEYS, transport,
        function_schemas=[date_schema()],
        function_handlers={"collect_date": handler}, stream_sid="offline-stream",
    )


async def capture_request(llm, context):
    """Capture serialized HTTP JSON after the real Pipecat and OpenAI SDKs."""
    recorded = {}
    original = llm._client

    async def request_boundary(request):
        assert request.method == "POST"
        assert request.url.host == "api.openai.com"
        assert request.url.path == "/v1/chat/completions"
        recorded.update(json.loads(request.content))
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            content="data: [DONE]\n\n",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(request_boundary)) as http:
        llm._client = type(original)(
            api_key=API_KEYS["openai_api_key"], http_client=http, max_retries=0,
        )
        try:
            # OpenAI's OS-header discovery can execute `uname` through Python's
            # platform module. Host fingerprinting is an external metadata
            # boundary, not voice behavior; never relax the subprocess guard.
            with patch("platform.platform", return_value="Linux-offline-test"):
                stream = await llm.get_chat_completions(context)
            try:
                async for _ in stream:
                    pass
            finally:
                await stream.close()
        finally:
            await llm._client.close()
            llm._client = original
    return recorded


@pytest.mark.parametrize("interruptions", [True, False])
def test_real_pipeline_constructs_without_smart_turn_download_or_provider_io(interruptions):
    async def scenario():
        result = make_pipeline(enable_interruptions=interruptions)
        assert len(result) == 17
        pipeline, worker, llm, aggregators, context = result[:5]
        try:
            assert pipeline is not None and worker is not None
            # Both real aggregators must share the exact context used for
            # outgoing requests; detached contexts hide future tool refreshes.
            assert aggregators.user()._context is context
            assert aggregators.assistant()._context is context
            params = await capture_request(llm, context)
            assert params["model"] == "gpt-4.1-mini"
            assert params["parallel_tool_calls"] is False
            assert params["temperature"] == 0.25
            assert params["max_completion_tokens"] == 231
            assert params["tools"][0]["function"]["name"] == "collect_date"
            assert params["messages"][0] == {
                "role": "system",
                "content": "Private fixture instructions. Never read these aloud.",
            }
        finally:
            await llm._client.close()
    asyncio.run(scenario())


def test_changed_active_tools_reach_same_llm_without_recreating_pipeline():
    async def scenario():
        result = make_pipeline()
        llm, context = result[2], result[4]
        try:
            first = await capture_request(llm, context)
            context.set_tools(ToolsSchema(standard_tools=[date_schema("confirm_date")]))
            second = await capture_request(llm, context)
            assert [t["function"]["name"] for t in first["tools"]] == ["collect_date"]
            assert [t["function"]["name"] for t in second["tools"]] == ["confirm_date"]
            assert second["parallel_tool_calls"] is False
            assert second["messages"] == first["messages"]
        finally:
            await llm._client.close()
    asyncio.run(scenario())


def test_application_mapper_refresh_replaces_stale_tool_in_actual_live_context():
    async def scenario():
        result = make_pipeline()
        llm, context = result[2], result[4]
        try:
            mapper_module = load_function_mapper()
            mapper = mapper_module.FunctionMapper(
                call_sid="offline-call", account_id="offline-account",
                call_handler=SimpleNamespace(call_contexts={"offline-call": context}),
            )
            from botelier.flow_executor import FlowExecutor, parse_flow_config

            executor = FlowExecutor(parse_flow_config({
                "nodes": [
                    {"id": "start", "type": "initial", "data": {}},
                    {"id": "finish", "type": "end", "data": {}},
                ],
                "edges": [{"source": "start", "target": "finish"}],
                "variables": [],
            }))
            executor.state.current_node_id = "finish"
            mapper._flow_executors["fixture"] = executor
            mapper.update_llm_tools_for_flow("fixture")
            outgoing = await capture_request(llm, context)
            assert [t["function"]["name"] for t in outgoing["tools"]] == ["end_call_finish"]
        finally:
            await llm._client.close()
    asyncio.run(scenario())
