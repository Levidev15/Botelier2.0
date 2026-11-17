"""Synthetic published-flow host for the real CallHandler development gate."""

import copy
from types import SimpleNamespace
from unittest.mock import patch

import guard

from lifecycle_io import CALL_SID
from lifecycle_support import OfflineCall
from node_contract_io import (
    ACCOUNT, CONNECTION, PROPERTY, ActionRecords, CatalogueRecords,
    CatalogueSession, flow_config, synthetic_integration,
)
from pilot_io import PilotProviders


TOOL_ID = "00000000-0000-0000-0000-000000000104"
TOOL_SET_ID = "00000000-0000-0000-0000-000000000108"
VERSION_ID = "00000000-0000-0000-0000-000000000109"
ALT_TOOL_ID = "00000000-0000-0000-0000-000000000110"
ALT_VERSION_ID = "00000000-0000-0000-0000-000000000111"


class NativeDevCatalogueSession(CatalogueSession):
    def __init__(self, records):
        super().__init__(records)
        self.criteria = []

    def query(self, model):
        self.criteria = []
        return super().query(model)

    def filter(self, *criteria):
        self.criteria = list(criteria)
        return self

    def first(self):
        if self.closed:
            guard.deny("closed_native_dev_catalogue_query")
        if self.model == "Tool":
            return self.records.rows["Tool"][0]
        if self.model == "FlowVersion":
            candidates = [
                self.records.rows["FlowVersion"],
                *self.records.rows.get("AdditionalFlowVersions", []),
            ]
            for version in candidates:
                if all(
                    str(getattr(
                        getattr(version, criterion.left.key, None), "value",
                        getattr(version, criterion.left.key, None),
                    )) == str(getattr(criterion.right.value, "value", criterion.right.value))
                    for criterion in self.criteria
                ):
                    return version
            return None
        return super().first()


class NativeDevRecords(CatalogueRecords):
    def __init__(
        self, *, extra_tool=False, with_mcp=False, bad_contract=False,
        with_global_prompt=False, extra_global_tool=False, escalation=False,
        extra_published_flow=False,
        wrong_ownership=None, missing_version=False, unpublished_version=False,
        wrong_selection=False,
    ):
        super().__init__()
        from botelier.models.flow_version import FlowVersionStatus
        from botelier.models.mcp_connection import (
            MCPAuthType, MCPConnectionStatus, MCPTransportType,
        )
        from botelier.models.tool import ToolType

        config = flow_config(source="custom", presentation=True, narration=False)
        if with_global_prompt:
            config["globalPrompt"] = (
                "Keep the caller's requested availability constraints intact."
            )
        if bad_contract:
            config["unknownPrivatePrompt"] = "Reject unknown editor fields."
        tool = SimpleNamespace(
            id=TOOL_ID, name="fixture", description="Fixture flow",
            tool_type=ToolType.FLOW, config=copy.deepcopy(config),
            published_version_id=None if missing_version else VERSION_ID,
            published_version_number=1,
            tool_set_id=TOOL_SET_ID,
            account_id=(
                "00000000-0000-0000-0000-000000000999"
                if wrong_ownership == "tool" else None
            ),
            is_active="true",
            llm_provider=None, llm_model=None, llm_temperature=None,
            llm_max_tokens=None,
        )
        self.rows["Tool"] = [tool]
        if extra_tool:
            self.rows["Tool"].append(SimpleNamespace(
                id="offline-extra-tool", name="extra", description="Extra tool",
                tool_type=ToolType.FLOW, config=copy.deepcopy(config),
                tool_set_id=TOOL_SET_ID, account_id=None, is_active="true",
                published_version_id=None, llm_provider=None, llm_model=None,
                llm_temperature=None, llm_max_tokens=None,
            ))
        alternate_config = copy.deepcopy(config)
        alternate_start = next(
            node for node in alternate_config["nodes"] if node["id"] == "start"
        )
        alternate_start["data"]["greeting"] = "Alternate workflow."
        alternate_query = next(
            node for node in alternate_config["nodes"] if node["id"] == "query"
        )
        alternate_query["data"]["slot"]["prompt"] = "Which alternate fixture?"
        if extra_published_flow:
            alternate_config["nodes"].append({
                "id": "end", "type": "end", "data": {
                    "closingMessage": "The alternate support task is complete.",
                },
            })
            alternate_config["edges"].append({
                "id": "choice-end", "source": "choice", "target": "end",
            })
            self.rows["Tool"].append(SimpleNamespace(
                id=ALT_TOOL_ID, name="fixture support",
                description="A second assigned published workflow.",
                tool_type=ToolType.FLOW, config=copy.deepcopy(alternate_config),
                tool_set_id=TOOL_SET_ID, account_id=None, is_active="true",
                published_version_id=ALT_VERSION_ID, llm_provider=None,
                llm_model=None, llm_temperature=None, llm_max_tokens=None,
            ))
        if extra_global_tool:
            self.rows["Tool"].append(SimpleNamespace(
                id="00000000-0000-0000-0000-000000000106",
                name="end_call_fixture", description="End the offline call.",
                tool_type=ToolType.END_CALL,
                config={"goodbye_message": "Goodbye from the assigned tool."},
                tool_set_id=TOOL_SET_ID, account_id=None, is_active="true",
                published_version_id=None, llm_provider=None, llm_model=None,
                llm_temperature=None, llm_max_tokens=None,
            ))
        self.rows.update({
            "ToolSet": SimpleNamespace(id=TOOL_SET_ID, account_id=ACCOUNT),
            "FlowVersion": SimpleNamespace(
                id=VERSION_ID, tool_id=TOOL_ID,
                status=(
                    FlowVersionStatus.DRAFT
                    if unpublished_version else FlowVersionStatus.PUBLISHED
                ),
                flow_config=config,
            ),
            "AdditionalFlowVersions": (
                [SimpleNamespace(
                    id=ALT_VERSION_ID, tool_id=ALT_TOOL_ID,
                    status=FlowVersionStatus.PUBLISHED,
                    version_number=1,
                    flow_config=alternate_config,
                )]
                if extra_published_flow else []
            ),
            "Property": (
                None if wrong_ownership == "property"
                else SimpleNamespace(id=PROPERTY, account_id=ACCOUNT)
            ),
            "MCPConnection": (
                None if not with_mcp else SimpleNamespace(
                    id=CONNECTION, account_id=ACCOUNT, is_active=True,
                    status=MCPConnectionStatus.CONNECTED,
                    transport_type=MCPTransportType.STREAMABLE_HTTP,
                    auth_type=MCPAuthType.NONE,
                    server_url="https://mcp.fixture.invalid/mcp",
                    credentials_encrypted=None, name="Offline MCP fixture",
                    discovered_tools=[
                        {"name": "lookup", "parameters": {
                            "type": "object", "properties": {},
                        }},
                        {"name": "reserve", "parameters": {
                            "type": "object", "properties": {},
                        }},
                    ],
                    get_connection_config=lambda: {
                        "property_id": PROPERTY,
                        "native_enabled_tools": ["lookup", "reserve"],
                        "native_read_only_tools": ["lookup"],
                    },
                )
            ),
        })
        self.assistant.account_id = ACCOUNT
        self.assistant.property_id = PROPERTY
        self.assistant.tool_set_id = TOOL_SET_ID
        self.assistant.call_settings = {
            "native_flow_tool_id": "offline-other-flow" if wrong_selection else TOOL_ID,
        }
        if escalation:
            self.assistant.call_settings["escalation_number"] = "+15555550199"
        if wrong_ownership == "tool_set":
            self.rows["ToolSet"].account_id = "00000000-0000-0000-0000-000000000999"
        self.assistant.mcp_connection_id = CONNECTION if with_mcp else None
        self.assistant.mcp_enabled_tools = ["lookup", "reserve"] if with_mcp else []
        self.rows["PhoneNumber"] = SimpleNamespace(
            property_id=PROPERTY, assistant_id=self.assistant.id,
        )

    def session(self):
        session = NativeDevCatalogueSession(self)
        self.sessions.append(session)
        return session


class _SessionRouter:
    """Route native action reads to action fakes, all host reads to records."""

    _ACTION_MODELS = {
        "AccountIntegration", "IntegrationCallLog", "IntegrationActionInvocation",
    }

    def __init__(self, records, actions):
        self.records = records
        self.actions = actions
        self.delegate = None
        self.delegates = {}

    def query(self, model):
        store = (
            "actions" if model.__name__ in self._ACTION_MODELS else "records"
        )
        self.delegate = self.delegates.get(store)
        if self.delegate is None:
            self.delegate = (
                self.actions.session()
                if store == "actions" else self.records.session()
            )
            self.delegates[store] = self.delegate
        return self.delegate.query(model)

    def close(self):
        for delegate in self.delegates.values():
            if not delegate.closed:
                delegate.close()

    def __getattr__(self, name):
        if self.delegate is None:
            raise AttributeError(name)
        return getattr(self.delegate, name)


class _NoQueueMap(dict):
    def __missing__(self, key):
        return None


class NativeDevVoiceCall(OfflineCall):
    """Real call coordinator and Pipecat worker; only I/O/storage are synthetic."""

    def __init__(
        self, *, native_enabled=True, extra_tool=False, with_mcp=False,
        bad_contract=False, with_global_prompt=False, providers=None, handler=None,
        wrong_ownership=None, missing_version=False, unpublished_version=False,
        wrong_selection=False, extra_global_tool=False, escalation=False,
        extra_published_flow=False,
        prewarmed=False, missing_call_log=False,
    ):
        module = __import__("botelier.voice.call_handler", fromlist=["CallHandler"])
        if handler is None:
            policy = module.NativeFlowDevPolicy(
                "development" if native_enabled else None,
                "1" if native_enabled else None,
            )
            handler = module.CallHandler(native_flow_dev_policy=policy)
        self.handler = handler
        super().__init__(
            handler=self.handler,
            providers=providers or PilotProviders([
                {"tool_calls": [{
                    "index": 0, "id": "native-dev-call", "type": "function",
                    "function": {
                        "name": "collect_query",
                        "arguments": '{"query":"standard"}',
                    },
                }]},
                "The selected fixture is ready.",
            ]),
        )
        self.records = NativeDevRecords(
            extra_tool=extra_tool, with_mcp=with_mcp, bad_contract=bad_contract,
            with_global_prompt=with_global_prompt,
            extra_global_tool=extra_global_tool, escalation=escalation,
            extra_published_flow=extra_published_flow,
            wrong_ownership=wrong_ownership, missing_version=missing_version,
            unpublished_version=unpublished_version, wrong_selection=wrong_selection,
        )
        self.mcp_calls = []
        if missing_call_log:
            self.records.rows["CallLog"] = None
        self.actions = ActionRecords(synthetic_integration())
        self.session_routers = []
        self.native_adapter = None
        self.prewarmed = prewarmed

    async def __aenter__(self):
        from botelier.services.ssrf_safe_transport import SSRFSafeTransport
        from pipecat.adapters.schemas.function_schema import FunctionSchema
        from pipecat.adapters.schemas.tools_schema import ToolsSchema

        if self.records.rows["CallLog"] is None:
            self.handler.call_event_queues = _NoQueueMap(
                self.handler.call_event_queues,
            )

        if self.prewarmed:
            from botelier.voice.prewarm import (
                AssistantSnapshot, PreWarmBundle, PreWarmCache, ToolSnapshot,
            )

            # Use the real reduced snapshots, not ORM-shaped stand-ins. Their
            # omitted fields are part of the production prewarm contract.
            config = await self.handler._create_agent_config(self.records.assistant)
            assistant = self.records.assistant
            assistant_snapshot = AssistantSnapshot(
                id=assistant.id, account_id=assistant.account_id,
                name=getattr(assistant, "name", "Offline assistant"),
                business_name=assistant.business_name,
                timezone=assistant.timezone,
                call_settings=copy.deepcopy(assistant.call_settings),
                property_id=assistant.property_id,
                temperature=assistant.temperature,
            )
            tool_snapshots = [
                ToolSnapshot(
                    id=tool.id, name=tool.name, description=tool.description,
                    tool_type=tool.tool_type, config=copy.deepcopy(tool.config),
                )
                for tool in self.records.rows["Tool"]
            ]
            tool_snapshots[0].config["globalPrompt"] = (
                "stale tool snapshot; never the published graph"
            )
            bundle = PreWarmBundle(
                assistant=assistant_snapshot,
                config=config,
                tools=tool_snapshots,
                mcp_connection_data=None,
                mcp_enabled_tools=[],
                hotel_twilio_sid=None,
                hotel_twilio_token=None,
                should_record_call=False,
            )
            cache = PreWarmCache()
            entry = cache.reserve(CALL_SID)
            entry.bundle = bundle
            entry.ready.set()
            self.handler.precomputed_configs = cache

        async def business_transport(transport, request):
            return await self.providers.http(request)

        self.patches.enter_context(patch.object(
            SSRFSafeTransport, "handle_async_request", business_transport,
        ))
        await super().__aenter__()
        # The real CallHandler and NativePilotAdapter resolve this factory at
        # call/action time. Keep CallLogger's ordinary record sessions routed
        # separately from the synthetic integration-action store.
        self.patches.enter_context(patch.object(
            self.module, "SessionLocal", self.session_factory,
        ))
        if self.records.assistant.mcp_connection_id:
            class OfflineMCPSession:
                async def call_tool(_session, tool_name, arguments=None):
                    self.mcp_calls.append((tool_name, arguments))
                    return SimpleNamespace(
                        content=[SimpleNamespace(text="Offline MCP fixture data.")],
                        structuredContent=None,
                        isError=False,
                    )

            class OfflineMCPClient:
                def __init__(self, **_kwargs):
                    self.closed = False
                    self._active_session = OfflineMCPSession()

                async def start(self):
                    return None

                async def get_tools_schema(self):
                    return ToolsSchema(standard_tools=[
                        FunctionSchema("lookup", "Read fixture data.", {}, []),
                        FunctionSchema("reserve", "Write fixture data.", {}, []),
                    ])

                async def close(self):
                    self.closed = True

            self.patches.enter_context(patch.object(
                self.module, "PIPECAT_MCP_AVAILABLE", True,
            ))
            self.patches.enter_context(patch.object(
                self.module, "PipecatMCPClient", OfflineMCPClient,
            ))
        return self

    def session_factory(self):
        router = _SessionRouter(self.records, self.actions)
        self.session_routers.append(router)
        return router

    def assert_rejected_before_pipeline(self, expected_code):
        assert self.run_task.done()
        assert self.created is None
        assert any(expected_code in message for message in self.errors)
        assert self.handler.native_flow_hosts == {}
        assert self.handler.call_mappers == {}
        assert all(session.closed for session in self.records.sessions)
        assert self.remaining_tasks() == []
