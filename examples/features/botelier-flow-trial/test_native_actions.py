import asyncio
import json
import uuid

import httpx


def _compiled_custom_read(identity=None):
    from botelier.voice.flows.native_graph import compile_flow
    from botelier.voice.flows.pilot_contract import PilotIdentity

    identity = identity or PilotIdentity(
        account_id="00000000-0000-0000-0000-000000000101",
        property_id="00000000-0000-0000-0000-000000000102",
        tool_id="offline-flow", flow_version_id="00000000-0000-0000-0000-000000000109",
        call_sid="CAoffline-actions",
    )
    config = {
        "initial_node": "start",
        "variables": [
            {"key": "query", "type": "text"},
            {"key": "amount", "type": "number"},
            {"key": "tax_included", "type": "text"},
        ],
        "nodes": [
            {"id": "start", "type": "initial", "data": {"greeting": ""}},
            {"id": "lookup", "type": "api_request", "data": {"api": {
                "apiSource": "custom", "method": "GET",
                "url": "https://api.fixture.invalid/items/{{query}}",
                "responseMapping": {
                    "amount": "$.amount", "tax_included": "$.tax_included",
                },
                "responseProjection": {"fields": [{"variable": "amount"}]},
                "timeout": 2, "retryCount": 0,
            }}},
            {"id": "done", "type": "end", "data": {"closingMessage": ""}},
        ],
        "edges": [
            {"id": "start-lookup", "source": "start", "target": "lookup"},
            {"id": "lookup-done", "source": "lookup", "target": "done", "sourceHandle": "success"},
        ],
    }
    return compile_flow(config, identity)


def _native_mcp_policy(db, fixture, connection_id, *, enabled, read_only):
    from botelier.services.native_mcp_policy import protect_connection_config

    return protect_connection_config(
        {
            "property_id": fixture.property_id,
            "native_enabled_tools": enabled,
            "native_read_only_tools": read_only,
        },
        account_id=fixture.account_id,
        connection_id=connection_id,
        db=db,
    )


def test_native_custom_api_uses_action_executor_and_exact_projection(monkeypatch):
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        from botelier.voice.flows.native_actions import NativeActionRunner

        observed = []

        async def controlled_transport(_transport, request):
            observed.append(request)
            return httpx.Response(
                200, json={"amount": 0, "tax_included": False}, request=request,
            )

        executors = []
        async with NativeEffectsFixture() as fixture:
            from botelier.services.action_executor import ActionExecutor
            from botelier.services.ssrf_safe_transport import SSRFSafeTransport

            monkeypatch.setattr(
                SSRFSafeTransport, "handle_async_request", controlled_transport,
            )

            class RecordingExecutor(ActionExecutor):
                async def execute(self, request):
                    self.last_result = await super().execute(request)
                    return self.last_result

            def executor_factory(db):
                executor = RecordingExecutor(db)
                executors.append(executor)
                return executor

            compiled = _compiled_custom_read(fixture.identity)
            runner = NativeActionRunner(
                compiled, fixture.factory,
                http_executor_factory=executor_factory,
            )
            preview_runner = NativeActionRunner(
                compiled, fixture.factory, execution_mode="preview",
            )
            preview = await preview_runner.execute(
                compiled.node("lookup"), {"query": "standard"},
            )
            assert preview.failure_reason == "preview_required"
            assert observed == []
            hostile_value = await runner.execute(
                compiled.node("lookup"),
                {"query": "0/../reserved?host=elsewhere", "earlier_value": "preserved"},
            )
            assert hostile_value.success is True
            assert len(observed) == 1
            assert observed[0].url.host == "api.fixture.invalid"
            assert observed[0].url.query == b""
            result = await runner.execute(
                compiled.node("lookup"),
                {"query": "standard", "earlier_value": "preserved"},
            )

            assert result.success is True, (result, len(observed))
            assert result.variables == {"amount": 0, "tax_included": False}
            assert result.llm_data == {"amount": 0}
            assert len(observed) == 2
            assert str(observed[1].url) == "https://api.fixture.invalid/items/standard"

    asyncio.run(scenario())


def test_global_mcp_exposure_is_explicitly_read_only_and_scope_checked():
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        async with NativeEffectsFixture() as fixture:
            from botelier.models.mcp_connection import (
                MCPAuthType, MCPConnection, MCPTransportType,
            )
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_graph import compile_flow

            connection_id = uuid.uuid4()
            db = fixture.factory()
            db.add(MCPConnection(
                id=connection_id, account_id=uuid.UUID(fixture.account_id),
                name="Native global read-only fixture",
                server_url="https://mcp.fixture.invalid/mcp",
                auth_type=MCPAuthType.NONE,
                transport_type=MCPTransportType.STREAMABLE_HTTP,
                is_active=True,
                connection_config=_native_mcp_policy(
                    db, fixture, connection_id,
                    enabled=["lookup", "reserve"], read_only=["lookup"],
                ),
            ))
            db.commit()
            db.close()
            compiled = compile_flow({
                "initial_node": "start",
                "variables": [],
                "nodes": [
                    {"id": "start", "type": "initial", "data": {
                        "greeting": "", "waitForResponse": False,
                    }},
                    {"id": "end", "type": "end", "data": {"closingMessage": ""}},
                ],
                "edges": [{"id": "done", "source": "start", "target": "end"}],
            }, fixture.identity)
            runner = NativeActionRunner(compiled, fixture.factory)
            assert runner.is_mcp_tool_read_only(str(connection_id), "lookup") is True
            assert runner.is_mcp_tool_read_only(str(connection_id), "reserve") is False
            try:
                runner.is_mcp_tool_read_only(str(connection_id), "disabled")
            except PermissionError:
                pass
            else:
                raise AssertionError("A disabled global MCP tool was authorized")

            legacy_id = uuid.uuid4()
            clone_id = uuid.uuid4()
            stored_policy = db.query(MCPConnection).filter(
                MCPConnection.id == connection_id,
            ).first().get_connection_config()
            db.add_all([
                MCPConnection(
                    id=legacy_id, account_id=uuid.UUID(fixture.account_id),
                    name="Legacy flat self-grant",
                    server_url="https://mcp.fixture.invalid/mcp",
                    auth_type=MCPAuthType.NONE,
                    transport_type=MCPTransportType.STREAMABLE_HTTP,
                    is_active=True,
                    connection_config={
                        "property_id": fixture.property_id,
                        "native_enabled_tools": ["lookup"],
                        "native_read_only_tools": ["lookup"],
                    },
                ),
                MCPConnection(
                    id=clone_id, account_id=uuid.UUID(fixture.account_id),
                    name="Copied sealed grant",
                    server_url="https://mcp.fixture.invalid/mcp",
                    auth_type=MCPAuthType.NONE,
                    transport_type=MCPTransportType.STREAMABLE_HTTP,
                    is_active=True,
                    connection_config=stored_policy,
                ),
            ])
            db.commit()
            db.close()
            for untrusted_id in (legacy_id, clone_id):
                try:
                    runner.is_mcp_tool_read_only(str(untrusted_id), "lookup")
                except PermissionError:
                    pass
                else:
                    raise AssertionError(
                        "An untrusted or cross-connection MCP policy was authorized",
                    )
            await runner.close()

    asyncio.run(scenario())


def test_output_only_mapping_defaults_preserve_false_and_required_missing_fails(monkeypatch):
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        from botelier.services.ssrf_safe_transport import SSRFSafeTransport
        from botelier.voice.flows.native_actions import NativeActionRunner
        from botelier.voice.flows.native_graph import compile_flow

        responses = [
            {"amount": 0, "flag": None},
            {},
        ]

        async def controlled_transport(_transport, request):
            return httpx.Response(200, json=responses.pop(0), request=request)

        async with NativeEffectsFixture() as fixture:
            monkeypatch.setattr(
                SSRFSafeTransport, "handle_async_request", controlled_transport,
            )
            config = {
                "initial_node": "start",
                "variables": [
                    {"key": "query", "type": "text", "required": False},
                    {"key": "amount", "type": "number"},
                ],
                "nodes": [
                    {"id": "start", "type": "initial", "data": {"greeting": ""}},
                    {"id": "lookup", "type": "api_request", "data": {"api": {
                        "apiSource": "custom", "method": "GET",
                        "url": "https://api.fixture.invalid/items",
                        "responseMapping": {"amount": "$.amount"},
                        "responseVariables": [
                            {"variableKey": "flag", "jsonPath": "$.flag",
                             "defaultValue": False},
                            {"variableKey": "optionalZero", "jsonPath": "$.missing",
                             "defaultValue": 0},
                            {"variableKey": "optional", "jsonPath": "$.optional"},
                        ],
                        "responseProjection": {
                            "fields": [
                                {"variable": "amount"}, {"variable": "flag"},
                                {"variable": "optionalZero"},
                            ],
                        },
                        "timeout": 2, "retryCount": 0,
                    }}},
                ],
                "edges": [{"id": "start-lookup", "source": "start", "target": "lookup"}],
            }
            compiled = compile_flow(config, fixture.identity)
            runner = NativeActionRunner(compiled, fixture.factory)

            first = await runner.execute(compiled.node("lookup"), {"query": "unused"})
            assert first.success is True
            assert first.variables == {
                "amount": 0, "flag": False, "optionalZero": 0,
            }
            assert first.llm_data == {
                "amount": 0, "flag": False, "optionalZero": 0,
            }
            second = await runner.execute(compiled.node("lookup"), {"query": "unused"})
            assert second.failure_reason == "response_mapping_invalid"

    asyncio.run(scenario())


def test_native_action_runner_rejects_node_not_in_compiled_flow():
    from dataclasses import replace
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        async with NativeEffectsFixture() as fixture:
            from botelier.voice.flows.native_actions import NativeActionRunner

            compiled = _compiled_custom_read(fixture.identity)
            runner = NativeActionRunner(
                compiled, fixture.factory, execution_mode="preview",
            )
            forged = replace(compiled.node("lookup"), node_id="other")

            result = await runner.execute(forged, {"query": "anything"})
            assert result.success is False
            assert result.failure_reason == "action_node_mismatch"

    asyncio.run(scenario())


def test_simulation_preview_validates_bound_sms_but_never_sends_or_claims():
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        async with NativeEffectsFixture() as fixture:
            from botelier.models.tool import Tool, ToolType
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_execution import NativeConfirmation
            from botelier.voice.flows.native_graph import compile_flow
            from botelier.voice.flows.native_messaging import NativeMessenger

            tool_id = "offline-sms-tool"
            db = fixture.factory()
            flow = db.query(Tool).filter(Tool.id == fixture.tool_id).first()
            db.add(Tool(
                id=tool_id, name="Synthetic SMS", description="Preview only",
                tool_type=ToolType.SEND_SMS,
                config={}, tool_set_id=flow.tool_set_id, is_active="true",
            ))
            db.commit()
            db.close()

            config = {
                "initial_node": "start",
                "variables": [
                    {"key": "recipient", "type": "phone"},
                    {"key": "body", "type": "text"},
                ],
                "nodes": [
                    {"id": "start", "type": "initial", "data": {"greeting": ""}},
                    {"id": "confirm", "type": "confirmation", "data": {
                        "confirmation": {
                            "summaryTemplate": "Send {{body}} to {{recipient}}?",
                            "confirmPrompt": "Proceed?",
                            "variablesToConfirm": ["recipient", "body"],
                            "allowEdit": False,
                        },
                    }},
                    {"id": "send", "type": "api_request", "data": {"api": {
                        "apiSource": "tool", "toolId": tool_id,
                        "argumentsTemplate": (
                            '{"recipient":"{{recipient}}","body":"{{body}}"}'
                        ),
                    }}},
                ],
                "edges": [
                    {"id": "start-confirm", "source": "start", "target": "confirm"},
                    {"id": "confirmed-send", "source": "confirm", "target": "send",
                     "sourceHandle": "confirmed"},
                ],
            }
            compiled = compile_flow(config, fixture.identity)
            calls = []

            class Messages:
                def create(self, **kwargs):
                    calls.append(kwargs)
                    return type("Accepted", (), {"sid": "SMoffline"})()

            messenger = NativeMessenger(
                identity=fixture.identity,
                twilio_client=type("Client", (), {"messages": Messages()})(),
                from_number="+12025550100", execution_mode="preview",
            )
            runner = NativeActionRunner(
                compiled, fixture.factory, messenger=messenger,
                channel="simulation", execution_mode="preview",
            )
            facts = {"recipient": "+12025550101", "body": "Approved message"}
            confirmation = NativeConfirmation(
                "confirm", 1, json.dumps(facts), ("recipient", "body"),
            )

            invalid = await runner.execute(
                compiled.node("send"),
                {"recipient": "not-a-phone", "body": "Approved message"},
                confirmation=NativeConfirmation(
                    "confirm", 1,
                    json.dumps({"recipient": "not-a-phone", "body": "Approved message"}),
                    ("recipient", "body"),
                ),
            )
            assert invalid.failure_reason == "invalid_recipient"
            missing_consent = await runner.execute(compiled.node("send"), facts)
            assert missing_consent.failure_reason == "confirmation_required"
            valid_preview = await runner.execute(
                compiled.node("send"), facts, confirmation=confirmation,
            )
            assert valid_preview.failure_reason == "preview_required"
            assert calls == []
            db = fixture.factory()
            assert db.query(
                fixture.effect_models["OperationIdempotency"],
            ).count() == 0
            db.close()

    asyncio.run(scenario())


def test_scoped_mcp_write_requires_consent_and_replays_mapped_result():
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        async with NativeEffectsFixture() as fixture:
            from botelier.models.mcp_connection import (
                MCPAuthType, MCPConnection, MCPTransportType,
            )
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_execution import NativeConfirmation
            from botelier.voice.flows.native_graph import compile_flow

            connection_id = uuid.uuid4()
            db = fixture.factory()
            db.add(MCPConnection(
                id=connection_id, account_id=uuid.UUID(fixture.account_id),
                name="Native fixture", server_url="https://mcp.fixture.invalid/mcp",
                auth_type=MCPAuthType.NONE,
                transport_type=MCPTransportType.STREAMABLE_HTTP,
                is_active=True,
                discovered_tools=[{
                    "name": "reserve",
                    "parameters": {
                        "type": "object",
                        "properties": {"amount": {"type": "number"}},
                        "required": ["amount"],
                    },
                }],
                connection_config=_native_mcp_policy(
                    db, fixture, connection_id,
                    enabled=["reserve"], read_only=[],
                ),
            ))
            db.commit()
            db.close()

            config = {
                "initial_node": "start",
                "variables": [
                    {"key": "amount", "type": "number"},
                    {"key": "receipt", "type": "number"},
                ],
                "nodes": [
                    {"id": "start", "type": "initial", "data": {"greeting": ""}},
                    {"id": "confirm", "type": "confirmation", "data": {
                        "confirmation": {
                            "summaryTemplate": "Reserve amount {{amount}}?",
                            "confirmPrompt": "Proceed?",
                            "variablesToConfirm": ["amount"],
                            "allowEdit": False,
                        },
                    }},
                    {"id": "reserve", "type": "api_request", "data": {"api": {
                        "apiSource": "mcp", "mcpConnectionId": str(connection_id),
                        "mcpToolName": "reserve",
                        "argumentsTemplate": '{"amount":{{amount}}}',
                        "responseMapping": {
                            "receipt": "$.structuredContent.receipt",
                        },
                        "responseProjection": {"fields": [{"variable": "receipt"}]},
                    }}},
                ],
                "edges": [
                    {"id": "start-confirm", "source": "start", "target": "confirm"},
                    {"id": "confirmed-reserve", "source": "confirm", "target": "reserve",
                     "sourceHandle": "confirmed"},
                ],
            }
            compiled = compile_flow(config, fixture.identity)
            calls = []
            clients = []
            client_configs = []

            class Session:
                async def list_tools(self):
                    return type("ListedTools", (), {"tools": [
                        type("Tool", (), {
                            "name": "reserve",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"amount": {"type": "number"}},
                                "required": ["amount"],
                            },
                        })(),
                    ]})()

                async def call_tool(self, name, arguments):
                    calls.append((name, arguments))
                    return type("ToolResult", (), {
                        "isError": False,
                        "structuredContent": {"receipt": 0},
                        "content": [{"type": "text", "text": "Accepted"}],
                    })()

            class Client:
                def __init__(self, **kwargs):
                    self._session = Session()
                    clients.append(self)
                    client_configs.append(kwargs["connection_config"])

                async def connect(self, timeout):
                    assert timeout == 10
                    return True, None

                async def disconnect(self):
                    return None

            facts = {"amount": 0}
            confirmation = NativeConfirmation(
                "confirm", 1, json.dumps(facts), ("amount",),
            )
            preview_runner = NativeActionRunner(
                compiled, fixture.factory, channel="simulation",
                mcp_client_factory=Client,
            )
            preview = await preview_runner.execute(
                compiled.node("reserve"), facts, confirmation=confirmation,
            )
            assert preview.failure_reason == "preview_required"
            assert calls == [] and clients == []
            db = fixture.factory()
            assert db.query(
                fixture.effect_models["OperationIdempotency"],
            ).count() == 0
            db.close()

            runner = NativeActionRunner(
                compiled, fixture.factory, mcp_client_factory=Client,
            )
            denied = await runner.execute(compiled.node("reserve"), facts)
            assert denied.failure_reason == "confirmation_required"
            assert calls == []
            first = await runner.execute(
                compiled.node("reserve"), facts, confirmation=confirmation,
            )
            second = await runner.execute(
                compiled.node("reserve"), facts, confirmation=confirmation,
            )
            assert first.success is True, (first, calls, len(clients))
            assert first.variables == {"receipt": 0}
            assert first.llm_data == {"receipt": 0}
            assert second == first
            assert calls == [("reserve", {"amount": 0})]
            assert len(clients) == 1
            assert "_native_policy_v1" not in client_configs[0]
            assert not {
                "native_enabled_tools", "native_read_only_tools",
                "property_id", "account_global",
            } & set(client_configs[0])

    asyncio.run(scenario())
