"""Test-only inputs/host attachment for the inactive native flow pilot.

The real call coordinator builds and runs the real pipeline. Only this fixture
attaches the new adapter; production selection and the legacy executor are not
changed. External transports and storage remain the prior enumerated fakes.
"""

import asyncio
import importlib
import importlib.util
import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from lifecycle_io import CALL_SID
from lifecycle_support import OfflineCall
from node_contract_io import (
    ACCOUNT, API_URL, CONNECTION, MCP_URL, PROPERTY,
    ActionRecords, CatalogueRecords, NodeProviders, flow_config, speech, synthetic_integration,
)


def pilot_config():
    """A saved graph in the explicitly approved connected-GET subset."""
    config = flow_config(source="integration", presentation=True, narration=False)
    lookup = next(node for node in config["nodes"] if node["id"] == "lookup")
    lookup["data"]["instructions"] = ""
    for key in ("url", "onSuccess", "onComplete"):
        lookup["data"]["api"].pop(key)
    return config


IDENTITY_FIELDS = {
    "account_id": "00000000-0000-0000-0000-000000000101",
    "property_id": "00000000-0000-0000-0000-000000000102",
    "tool_id": "offline-flow",
    "flow_version_id": "offline-version",
    "call_sid": "CAofflinefixture",
}
REVISION_COLLISION = "pilot_collect_query_" + "0" * 32


def logical_function_name(name):
    """Human-readable fixture view; runtime dispatch NEVER uses this alias."""
    if name.startswith("pilot_collect_"):
        return "collect_" + name[len("pilot_collect_"):].rsplit("_", 1)[0]
    return name


def native_schema(call, node_id):
    prefix = f"pilot_collect_{node_id[:16]}_"
    return next(schema for schema in call.created[4].tools.standard_tools
                if schema.name.startswith(prefix))


def native_tool_names(call):
    return {logical_function_name(schema.name) for schema in call.created[4].tools.standard_tools}


class PilotProviders(NodeProviders):
    def __init__(
        self, *args, late_business_result=False, hold_tts_turn=None,
        separate_call_chunks=False, bind_native_names=True, **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.tts.hold_turn = hold_tts_turn
        self.separate_call_chunks = separate_call_chunks
        self.bind_native_names = bind_native_names
        self.late_business_result = late_business_result
        self.returned_late_result = False

    async def http(self, request):
        try:
            response = await super().http(request)
        except asyncio.CancelledError:
            if not self.late_business_result or not str(request.url).startswith(API_URL):
                raise
            # Deliberately broken external transport: return a late successful
            # read instead of honoring cancellation. The real adapter must
            # still refuse to speak, mutate facts or advance.
            self.returned_late_result = True
            return httpx.Response(200, json=self.payload, request=request)
        if response.headers.get("content-type") == "text/event-stream":
            # A scripted model selects the tool in THIS serialized request,
            # not mutable application state. Held/late replies retain that
            # wire identity. Raw old/forged names can bypass fixture aliasing.
            body = json.loads(request.content)
            advertised = {
                logical_function_name(tool["function"]["name"]): tool["function"]["name"]
                for tool in body.get("tools", []) if tool.get("type") == "function"
            }
            lines = []
            for line in response.text.splitlines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    if line:
                        lines.append(line)
                    continue
                chunk = json.loads(line[6:])
                choices = chunk.get("choices", [])
                calls = choices[0].get("delta", {}).get("tool_calls", []) if choices else []
                if self.bind_native_names:
                    for tool in calls:
                        function = tool["function"]
                        name = function["name"]
                        if name.startswith("collect_"):
                            key = "collect_" + name[len("collect_"):][:16]
                            function["name"] = advertised.get(key, name)
                if len(calls) <= 1 or not self.separate_call_chunks:
                    lines.append("data: " + json.dumps(chunk))
                    continue
                # Preserve the explicit indexed-delta layout supported by the
                # pinned parser; this is a fixture choice, not a runtime repair.
                for index, tool in enumerate(calls):
                    copy = {**chunk, "choices": [{
                        **choices[0], "delta": {"tool_calls": [tool]},
                    }]}
                    if index:
                        copy.pop("usage", None)
                    lines.append("data: " + json.dumps(copy))
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"},
                content="\n\n".join(lines) + "\n\n", request=request,
            )
        return response

    async def mcp_http(self, request):
        response = await super().mcp_http(request)
        message = json.loads(request.content)
        if message["method"] == "tools/list":
            body = response.json()
            for name in ("collect_failure", REVISION_COLLISION):
                body["result"]["tools"].append({
                    "name": name, "description": "A native-name collision",
                    "inputSchema": {"type": "object", "properties": {
                        "query": {"type": "string"},
                    }, "required": ["query"]},
                })
            return httpx.Response(200, json=body, request=request)
        return response


class PilotCall(OfflineCall):
    def __init__(self, *, config=None, providers=None, mcp=False):
        module = "botelier.voice.flows.pilot_adapter"
        assert importlib.util.find_spec(module) is not None, (
            "The approved native single-flow adapter is not implemented"
        )
        self.adapter_type = importlib.import_module(module).NativePilotAdapter
        from botelier.voice.flows.pilot_contract import PilotIdentity, compile_pilot

        self.compiled = compile_pilot(
            pilot_config() if config is None else config,
            PilotIdentity(**{**IDENTITY_FIELDS, "call_sid": CALL_SID}),
        )
        super().__init__(providers=providers)
        self.records = CatalogueRecords()
        self.records.assistant.account_id = ACCOUNT
        self.records.assistant.property_id = PROPERTY
        self.records.assistant.tool_set_id = "offline-fixture-tools"
        self.records.rows["Tool"] = []
        self.actions = ActionRecords(synthetic_integration())
        self.adapter = None
        self.host_schemas = []
        self.host_handlers = {}
        self.mcp = mcp
        if mcp:
            assert importlib.util.find_spec("botelier.voice.flows.pilot_mcp") is not None, (
                "The native bridge for the existing filtered MCP catalogue is not implemented"
            )
            from botelier.models.mcp_connection import MCPConnectionStatus, MCPTransportType
            from pipecat.services.mcp_service import MCPClient

            assert self.module.PIPECAT_MCP_AVAILABLE
            assert self.module.PipecatMCPClient is MCPClient
            self.records.assistant.mcp_connection_id = CONNECTION
            self.records.assistant.mcp_enabled_tools = [
                "mcp_lookup", "collect_query", "collect_choice", "collect_failure",
                REVISION_COLLISION,
            ]
            self.records.rows["MCPConnection"] = SimpleNamespace(
                id=CONNECTION, name="Offline MCP fixture", server_url=MCP_URL,
                status=MCPConnectionStatus.CONNECTED,
                transport_type=MCPTransportType.STREAMABLE_HTTP,
                credentials_encrypted=None, auth_type=None, discovered_tools=[],
            )

    async def __aenter__(self):
        from botelier.services.ssrf_safe_transport import SSRFSafeTransport

        original_factory = self.module.VoiceEngineFactory.create_pipeline

        def attach(*args, **kwargs):
            # Capture the actual account/connection/enablement-filtered host
            # catalogue. Do not leave explicit legacy handler registrations
            # that would take precedence over native auto-bound schemas.
            self.host_schemas = list(kwargs.get("function_schemas") or [])
            self.host_handlers = dict(kwargs.get("function_handlers") or {})
            assert {schema.name for schema in self.host_schemas} <= {
                "mcp_lookup", "collect_query", "collect_choice", "collect_failure",
                REVISION_COLLISION,
            }
            kwargs.update(function_schemas=None, function_handlers=None)
            result = original_factory(*args, **kwargs)
            globals_ = []
            if self.mcp:
                from botelier.voice.flows.pilot_mcp import native_mcp_globals

                globals_ = native_mcp_globals(
                    self.host_schemas, self.host_handlers,
                    reserved_names=self.compiled.native_names,
                )
            self.adapter = self.adapter_type(
                self.compiled, llm=result[2], worker=result[1],
                context_aggregator=result[3], session_factory=self.actions.session,
                global_functions=globals_,
            )
            return result

        async def business_transport(transport, request):
            return await self.providers.http(request)

        self.patches.enter_context(patch.object(
            self.module.VoiceEngineFactory, "create_pipeline", attach,
        ))
        self.patches.enter_context(patch.object(
            SSRFSafeTransport, "handle_async_request", business_transport,
        ))
        return await super().__aenter__()

    async def activate(self):
        from test_application_transcripts import start_conversation

        # Keep cold coordinator/worker startup and playback/DB completion as
        # separate readiness phases, matching the existing lifecycle fixture.
        # Neither the adapter nor a model turn starts before greeting completion.
        await self.wait_until(lambda: self.started.is_set())
        await start_conversation(self)
        await self.adapter.start()
        await self.wait_until(lambda: (
            self.compiled.query.prompt in speech(self)
            and not self.created[16].get_audio_contexts()
            and not self.created[5]._bot_speaking
            and any(tool.name.startswith(
                f"pilot_collect_{self.compiled.query.node_id[:16]}_",
            ) for tool in getattr(self.created[4].tools, "standard_tools", ()))
        ))

    async def invoke_retained(self, schema, arguments):
        """Probe a retained native wrapper, not a second executor or dispatcher."""
        from pipecat.services.llm_service import FunctionCallParams

        results = []

        async def capture(result, *, properties=None):
            results.append(result)

        await schema.handler(FunctionCallParams(
            function_name=schema.name, tool_call_id="retained-native-contract-probe",
            arguments=arguments, llm=self.created[2], pipeline_worker=self.created[1],
            context=self.created[4], result_callback=capture,
        ))
        assert len(results) == 1
        return results[0]

    async def wait_for_node(self, node_id):
        # A native pre-action may finish synthetic TTS before the subsequent
        # context/tool frames and current-node assignment have completed.
        await self.wait_until(lambda: (
            self.adapter.manager.current_node == node_id
            and any(tool.name.startswith(f"pilot_collect_{node_id[:16]}_")
                    for tool in getattr(self.created[4].tools, "standard_tools", ()))
        ))

    async def wait_until(self, predicate, timeout=4.0):
        try:
            return await super().wait_until(predicate, timeout)
        except TimeoutError as exc:
            raise AssertionError({
                "worker_started": self.started.is_set(),
                "greeting_requested": self.greeting_requested.is_set(),
                "greeting_completed": self.records.call.ai_greeting_completed,
                "stt_connected": self.providers.stt_connected.is_set(),
                "tts_connected": self.providers.tts_connected.is_set(),
                "tts_flushes": self.providers.tts.flush_count,
                "node": self.adapter.manager.current_node if self.adapter else None,
                "facts": self.adapter.facts if self.adapter else None,
                "speech": speech(self),
                "messages": self.created[4].messages if self.created else None,
                "model_requests": [
                    body for body in self.providers.requests if body.get("stream")
                ],
                "in_progress": self.created[3].assistant().has_function_calls_in_progress,
                "business_cancelled": self.providers.business_cancelled,
                "errors": self.errors,
            }) from exc

    def assert_clean(self, **kwargs):
        super().assert_clean(**kwargs)
        assert self.adapter.closed
        assert all(session.closed for session in self.actions.sessions)
        ingress = self.adapter._replacement._input
        assert ingress.closed and not ingress.holding
        assert not ingress._users and not ingress._queued and not ingress._seen
        assert not ingress._pending and ingress._bytes == 0
