"""Synthetic catalogue/storage and HTTP responses for real voice node checks.

No mapper, executor, client serializer, MCP session, runner or TTS method is
replaced. HTTP transport and short-lived storage are the explicit boundaries.
Flow snapshots and cross-worker business-write idempotency are not certified.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import guard
import httpx

from application_support import load_function_mapper
from lifecycle_io import CALL_SID, Records, Session
from lifecycle_support import OfflineCall
from transcript_io import TranscriptProviders


ACCOUNT = "00000000-0000-0000-0000-000000000101"
PROPERTY = "00000000-0000-0000-0000-000000000102"
CONNECTION = "00000000-0000-0000-0000-000000000103"
MCP_URL = "https://mcp.fixture.invalid/mcp"
API_URL = "https://api.fixture.invalid/search"
WAIT = "I am checking the fixture."
BRIDGE = "The fixture lookup finished."
ERROR = "The fixture service is unavailable."
PRIVATE = "Private node guidance: use only the fixture results."
NARRATION = "Fixture price is 0."
PRESENTATION = "Here are the fixture options. Standard costs 0. Which option?"


def flow_config(*, source="custom", presentation=False, narration=True, method="GET"):
    api = {
        "apiSource": source, "url": API_URL + "?query={{query}}",
        "method": method, "thinkingMessage": WAIT, "onComplete": BRIDGE,
        "onError": ERROR, "onSuccess": "The fixture request succeeded.",
        "responseMapping": {"rooms": "$.rooms", "price": "$.rooms[0].price"},
        "timeout": 2, "retryCount": 0,
    }
    if source == "integration":
        api.update(integrationId=CONNECTION, path="/search?query={{query}}")
    if narration:
        api["responseInstructions"] = "Fixture price is {{price}}."
    nodes = [
        {"id": "start", "type": "initial", "data": {
            "greeting": "", "waitForResponse": False,
        }},
        {"id": "query", "type": "collect_slot", "data": {
            "instructions": PRIVATE,
            "slot": {"variableKey": "query", "prompt": "Which fixture?"},
        }},
        {"id": "lookup", "type": "api_request", "data": {
            "name": "Fixture lookup", "instructions": PRIVATE, "api": api,
        }},
        {"id": "choice", "type": "collect_slot", "data": {
            "instructions": "Private next-node guidance: collect the selected option.",
            "slot": {"variableKey": "choice", "prompt": "Which option?"},
        }},
        {"id": "failure", "type": "collect_slot", "data": {
            "slot": {"variableKey": "choice", "prompt": "Try a different fixture?"},
        }},
    ]
    edges = [
        {"id": "start-q", "source": "start", "target": "query"},
        {"id": "q-api", "source": "query", "target": "lookup"},
        {"id": "ok", "source": "lookup", "target": "response" if presentation else "choice",
         "sourceHandle": "success"},
        {"id": "bad", "source": "lookup", "target": "failure", "sourceHandle": "error"},
    ]
    if presentation:
        nodes.append({"id": "response", "type": "api_response", "data": {
            "responsePresentation": {
                "arrayVariable": "rooms", "introText": "Here are the fixture options.",
                "itemTemplate": "{{name}} costs {{price}}.", "outroText": "Which option?",
                "noResultsText": "No fixture options were found.",
            },
        }})
        edges.append({"id": "response-choice", "source": "response", "target": "choice",
                      "sourceHandle": "has_results"})
        edges.append({"id": "response-empty", "source": "response", "target": "failure",
                      "sourceHandle": "no_results"})
    return {
        "initial_node": "start", "nodes": nodes, "edges": edges,
        "variables": [
            {"key": "query", "type": "text", "description": "Fixture query"},
            {"key": "choice", "type": "text", "description": "Fixture selection"},
        ],
    }


class CatalogueSession(Session):
    def all(self):
        if self.closed or self.model != "Tool":
            guard.deny("unexpected_node_catalogue_query")
        return list(self.records.rows["Tool"])


class CatalogueRecords(Records):
    def session(self):
        session = CatalogueSession(self)
        self.sessions.append(session)
        return session


class ActionRecords:
    """Only invocation/log writes and enumerated synthetic connection reads."""

    def __init__(self, integration=None):
        self.integration = integration
        self.sessions = []
        self.writes = []

    def session(self):
        session = ActionSession(self)
        self.sessions.append(session)
        return session


class ActionSession:
    def __init__(self, records):
        self.records = records
        self.closed = False
        self.criteria = []
        self.staged = []

    def query(self, model):
        if self.closed or model.__name__ != "AccountIntegration":
            guard.deny("unexpected_node_action_query")
        self.criteria = []
        return self

    def options(self, *options):
        return self

    def filter(self, *criteria):
        for criterion in criteria:
            name = criterion.left.key
            if name not in {"id", "account_id"} or criterion.operator.__name__ != "eq":
                guard.deny("unexpected_node_connection_filter")
            self.criteria.append((name, str(criterion.right.value)))
        return self

    def first(self):
        record = self.records.integration
        if record is not None and all(
            str(getattr(record, name)) == value for name, value in self.criteria
        ):
            return record
        return None

    def execute(self, statement, parameters):
        if (
            self.closed
            or str(statement) != "SELECT pg_advisory_xact_lock(hashtext(:key))"
            or parameters != {"key": f"integration-token-refresh:{CONNECTION}"}
        ):
            guard.deny("unexpected_node_action_sql")
        # Models only the refresh-lock storage boundary, not PostgreSQL locking.
        return None

    def add(self, row):
        if self.closed or type(row).__name__ not in {
            "IntegrationCallLog", "IntegrationActionInvocation",
        }:
            guard.deny("unexpected_node_action_write")
        self.staged.append(row)

    def commit(self):
        if self.closed:
            guard.deny("closed_node_action_session")
        self.records.writes.extend(self.staged)
        self.staged.clear()

    def rollback(self):
        self.staged.clear()

    def close(self):
        assert not self.closed
        self.closed = True

    def __getattr__(self, name):
        guard.deny("unexpected_node_action_storage_operation")


def synthetic_integration():
    from botelier.models.integration import IntegrationStatus

    auth_config = {
        "base_url": "https://api.fixture.invalid",
        "resilience": {
            "rate_limit_enabled": False, "breaker_enabled": False,
            "backoff_base_s": 0, "backoff_max_s": 0, "backoff_jitter": False,
        },
    }
    return SimpleNamespace(
        id=CONNECTION, account_id=ACCOUNT, property_id=PROPERTY,
        status=IntegrationStatus.CONNECTED, token_expires_at=None,
        access_token=None, refresh_token=None,
        get_credentials=lambda: {}, get_connection_config=lambda: {},
        integration_type=SimpleNamespace(
            slug="offline-fixture", auth_type="none",
            get_auth_config=lambda: auth_config, get_endpoints=lambda: [],
        ),
    )


class NodeProviders(TranscriptProviders):
    def __init__(self, replies, *, status=200, payload=None, mcp_result=None, mcp_fault=None):
        super().__init__(replies)
        self.status = status
        self.payload = {"rooms": [{"name": "Standard", "price": 0}]} if payload is None else payload
        self.business_requests = []
        self.business_started = asyncio.Event()
        self.release_business = asyncio.Event()
        self.business_cancelled = False
        self.mcp_messages = []
        self.mcp_fault = mcp_fault
        self.mcp_started = asyncio.Event()
        self.release_mcp = asyncio.Event()
        self.mcp_cancelled = False
        self.mcp_result = mcp_result or {
            "content": [{"type": "text", "text": "The fixture is ready."}],
            "isError": False,
        }

    async def http(self, request):
        if str(request.url).startswith(API_URL):
            if request.method not in {"GET", "POST"} or request.url.path != "/search":
                guard.deny("unexpected_node_business_request")
            self.business_requests.append(request)
            self.business_started.set()
            if self.status == "timeout":
                raise httpx.ReadTimeout("Synthetic fixture response was not received", request=request)
            if self.status == "hold":
                try:
                    await self.release_business.wait()
                except asyncio.CancelledError:
                    self.business_cancelled = True
                    raise
            return httpx.Response(
                200 if self.status == "hold" else self.status, json=self.payload, request=request,
            )
        if str(request.url) == MCP_URL:
            return await self.mcp_http(request)
        return await super().http(request)

    async def mcp_http(self, request):
        if request.method != "POST":
            guard.deny("unexpected_node_mcp_method")
        message = json.loads(request.content)
        self.mcp_messages.append(message)
        method = message["method"]
        if method == "notifications/initialized":
            return httpx.Response(202, request=request)
        if method == "initialize":
            result = {
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "offline-fixture", "version": "1.0"},
            }
        elif method == "tools/list":
            result = {"tools": [
                {"name": name, "description": "Synthetic fixture lookup",
                 "inputSchema": {"type": "object", "properties": {
                     "query": {"type": "string"},
                 }, "required": ["query"]}}
                for name in ("mcp_lookup", "mcp_disabled", "collect_query")
            ]}
        elif method == "tools/call":
            assert message["params"] == {
                "name": "mcp_lookup", "arguments": {"query": "standard"},
            }
            self.mcp_started.set()
            if self.mcp_fault == "timeout":
                raise httpx.ReadTimeout("Synthetic MCP response was not received", request=request)
            if self.mcp_fault == "hold":
                try:
                    await self.release_mcp.wait()
                except asyncio.CancelledError:
                    self.mcp_cancelled = True
                    raise
            result = self.mcp_result
        else:
            guard.deny("unexpected_node_mcp_rpc")
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": message["id"], "result": result,
        }, request=request)

    def release_blocked_io(self):
        super().release_blocked_io()
        self.release_mcp.set()
        self.release_business.set()


class NodeCall(OfflineCall):
    def __init__(self, *, config=None, providers=None, mcp=False):
        super().__init__(providers=providers)
        from botelier.flow_executor import FlowExecutor, parse_flow_config
        from botelier.models.tool import ToolType

        self.records = CatalogueRecords()
        self.records.assistant.account_id = ACCOUNT
        config = config if config is not None else flow_config()
        source = next(node["data"]["api"]["apiSource"]
                      for node in config["nodes"] if node["type"] == "api_request")
        self.actions = ActionRecords(synthetic_integration() if source == "integration" else None)
        self.mapper = load_function_mapper().FunctionMapper(
            call_sid=CALL_SID, call_handler=self.handler, account_id=ACCOUNT,
            property_id=PROPERTY,
        )
        # Real catalogue loading reuses this mapper and its ephemeral executor.
        # No snapshot, billing, ledger or business database is reached.
        self.executor = FlowExecutor(
            parse_flow_config(config), account_id=ACCOUNT, property_id=PROPERTY,
            session_factory=self.actions.session,
        )
        self.executor.state.advance_to("query")
        self.executor._flow_started = True
        self.mapper._flow_executors["fixture"] = self.executor
        self.handler.call_mappers[CALL_SID] = self.mapper
        self.records.assistant.tool_set_id = "offline-fixture-tools"
        self.records.rows["Tool"] = [SimpleNamespace(
            id="offline-flow", name="fixture", description="Check a fixture",
            tool_type=ToolType.FLOW, config=config,
        )]
        if mcp:
            from botelier.models.mcp_connection import MCPConnectionStatus, MCPTransportType

            self.records.assistant.mcp_connection_id = CONNECTION
            self.records.assistant.mcp_enabled_tools = ["mcp_lookup", "collect_query"]
            self.records.rows["MCPConnection"] = SimpleNamespace(
                id=CONNECTION, name="Offline MCP fixture", server_url=MCP_URL,
                status=MCPConnectionStatus.CONNECTED,
                transport_type=MCPTransportType.STREAMABLE_HTTP,
                credentials_encrypted=None, auth_type=None, discovered_tools=[],
            )

    async def __aenter__(self):
        from botelier.services.ssrf_safe_transport import SSRFSafeTransport

        async def business_transport(transport, request):
            # DNS/IP/TLS protection is not the subject of this offline format
            # checkpoint. Do not let even a fixture hostname reach DNS.
            return await self.providers.http(request)

        self.patches.enter_context(patch.object(
            SSRFSafeTransport, "handle_async_request", business_transport,
        ))
        return await super().__aenter__()

    def assert_clean(self, **kwargs):
        super().assert_clean(**kwargs)
        assert all(session.closed for session in self.actions.sessions)

    async def wait_until(self, predicate, timeout=4.0):
        try:
            return await super().wait_until(predicate, timeout=timeout)
        except TimeoutError as exc:
            raise AssertionError({
                "node": self.executor.state.current_node_id,
                "slots": self.executor.state.collected_slots,
                "speech": speech(self),
                "messages": [
                    message for message in self.created[4].messages
                    if message.get("role") != "system"
                ],
                "errors": self.errors,
            }) from exc


def tool_delta(name, arguments=None, call_id="node-contract-call"):
    return {"tool_calls": [{
        "index": 0, "id": call_id, "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments or {})},
    }]}


def tool_result(call, call_id="node-contract-call"):
    return next(json.loads(message["content"]) for message in call.created[4].messages
                if message.get("role") == "tool" and message.get("tool_call_id") == call_id)


def speech(call):
    return [item["text"] for item in call.providers.tts.sent if item.get("type") == "Speak"]


async def wait_for_speech(call, text):
    """Direct TTS and model speech can coalesce in context; inspect the TTS sink."""
    await call.wait_until(lambda: (
        text in speech(call) and not call.created[16].get_audio_contexts()
        and not call.created[5]._bot_speaking
        and not call.created[3].assistant().has_function_calls_in_progress
        and any(message.get("role") == "tool" for message in call.created[4].messages)
    ))


async def wait_for_tool_result(call):
    await call.wait_until(lambda: (
        not call.created[3].assistant().has_function_calls_in_progress
        and any(message.get("role") == "tool" for message in call.created[4].messages)
    ))
