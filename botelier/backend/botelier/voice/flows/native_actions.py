"""Fail-closed broker for scoped native graph business actions."""

import asyncio
import json
import re
from uuid import UUID
from urllib.parse import parse_qsl, urlsplit

from botelier.services.request_templates import (
    PreparedRequestBody, RequestTemplateError, prepare_body_headers,
    referenced_secrets, render_content_template, render_json_template,
    render_request_url,
)
from botelier.services.response_projection import (
    ResponseProjectionError, project_mapped_values,
)
from botelier.voice.flows.native_execution import (
    NativeActionResult, NativeConfirmation, NativeTerminalResult,
)
from botelier.voice.flows.native_effect_ledger import NativeEffectLedger
from botelier.voice.flows.native_graph import CompiledFlow, CompiledNode
from botelier.voice.flows.native_outcome_policy import is_definitive_rejection
from botelier.voice.flows.native_response_mapping import (
    NativeResponseMappingError, map_project_response as _map_project_response,
    map_response_data, resolve_response_variables,
)


_TOKEN = re.compile(r"{{\s*([A-Za-z][A-Za-z0-9_]*)\s*}}")
_SECRET = re.compile(r"\{\{secrets\.([A-Za-z][A-Za-z0-9_]*)\}\}\Z")
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}\Z")
_BLOCKED_HEADERS = frozenset({
    "host", "content-length", "transfer-encoding", "connection",
    "proxy-authorization", "proxy-connection", "cookie", "set-cookie",
})
_MAX_FACT_BYTES = 250_000
def _failure(reason, branch="error"):
    return NativeActionResult(False, branch=branch, failure_reason=reason)


class NativeActionRunner:
    """Executes only exact admitted nodes with server-owned source authority."""

    def __init__(
        self, compiled, session_factory, *, messenger=None,
        execution_mode="execute", channel="voice", http_executor_factory=None,
        mcp_client_factory=None,
    ):
        if (
            not isinstance(compiled, CompiledFlow) or not callable(session_factory)
            or execution_mode not in {"execute", "preview"}
            or channel not in {"voice", "simulation"}
        ):
            raise ValueError("native_action_runner_config")
        self.compiled = compiled
        self.session_factory = session_factory
        self.messenger = messenger
        self.execution_mode = execution_mode
        self.channel = channel
        self.policy_channel = "voice" if channel == "voice" else "test"
        self.preview_only = execution_mode == "preview" or channel == "simulation"
        self.http_executor_factory = http_executor_factory
        self.mcp_client_factory = mcp_client_factory
        if messenger is not None and (
            str(getattr(messenger.identity, "account_id", ""))
            != str(compiled.identity.account_id)
            or str(getattr(messenger.identity, "property_id", ""))
            != str(compiled.identity.property_id)
        ):
            raise ValueError("native_messenger_scope_mismatch")
        self._ledger = NativeEffectLedger(session_factory, compiled.identity)
        self._closed = False

    async def execute(self, node, facts, *, confirmation=None):
        if self._closed:
            return _failure("action_runner_closed")
        admitted = self.compiled.node(getattr(node, "node_id", None))
        if not isinstance(node, CompiledNode) or admitted != node:
            return _failure("action_node_mismatch")
        try:
            detached = json.loads(json.dumps(
                facts, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
            ))
            if not isinstance(detached, dict) or len(json.dumps(detached).encode()) > _MAX_FACT_BYTES:
                return _failure("action_facts_invalid")
        except (TypeError, ValueError, RecursionError, OverflowError):
            return _failure("action_facts_invalid")
        try:
            await asyncio.to_thread(self._verify_flow_scope)
        except Exception:
            return _failure("action_scope_unavailable", "auth_error")
        data = node.data()
        if node.type == "save_record":
            return await self._save_record(node, data, detached, confirmation)
        if node.type not in {"api_request", "capability"}:
            return _failure("action_type_unavailable")
        config = data.get("api") or {}
        source = config.get("apiSource", "capability" if node.type == "capability" else "custom")
        if source == "custom":
            return await self._custom_api(node, config, detached, confirmation)
        if source == "integration":
            return await self._integration_api(node, config, detached, confirmation)
        if source == "mcp":
            return await self._mcp_api(node, config, detached, confirmation)
        if source == "tool":
            return await self._tool_api(node, config, detached, confirmation)
        if source == "capability":
            return await self._capability_api(node, config, detached, confirmation)
        return _failure("api_source_unavailable")

    def _verify_flow_scope(self):
        from botelier.models.flow_version import FlowVersion
        from botelier.models.property import Property
        from botelier.models.tool import Tool
        from botelier.models.tool_set import ToolSet

        db = self.session_factory()
        try:
            try:
                version_id = UUID(self.compiled.identity.flow_version_id)
                account_id = UUID(self.compiled.identity.account_id)
                property_id = UUID(self.compiled.identity.property_id)
            except (TypeError, ValueError, AttributeError):
                raise LookupError("native_scope_invalid") from None
            flow = db.query(Tool).filter(
                Tool.id == self.compiled.identity.tool_id,
                Tool.is_active == "true",
            ).first()
            if (
                flow is None
                or str(flow.id) != str(self.compiled.identity.tool_id)
                or flow.tool_set_id is None
            ):
                raise LookupError("native_flow_tool_unavailable")
            flow_type = getattr(flow.tool_type, "value", flow.tool_type)
            if flow_type != "FLOW":
                raise LookupError("native_flow_tool_invalid")
            tool_set = db.query(ToolSet).filter(
                ToolSet.id == flow.tool_set_id,
                ToolSet.account_id == account_id,
            ).first()
            version = db.query(FlowVersion).filter(
                FlowVersion.id == version_id, FlowVersion.tool_id == flow.id,
            ).first()
            property_row = db.query(Property).filter(
                Property.id == property_id, Property.account_id == account_id,
                Property.is_active.is_(True),
            ).first()
            if tool_set is None or version is None or property_row is None:
                raise LookupError("native_scope_mismatch")
            version_status = getattr(version.status, "value", version.status)
            # The host admits the immutable version once at call start. Publishing
            # another version must not strand that admitted call mid-conversation.
            is_live_binding = version_status == "published"
            is_simulation_binding = (
                is_live_binding
                or version_status == "draft"
                and str(flow.draft_version_id or "") == str(version.id)
            )
            if (
                self.channel == "voice" and not is_live_binding
                or self.channel == "simulation" and not is_simulation_binding
            ):
                raise LookupError("native_version_not_active")
            return True
        finally:
            try:
                db.close()
            except Exception:
                pass

    async def _tool_api(self, node, config, facts, confirmation):
        references = self._request_references(config)
        try:
            tool_config, tool_type = await asyncio.to_thread(
                self._resolve_bound_tool, config.get("toolId"),
            )
            if tool_type in {"API_REQUEST", "DYNAMIC_OPERATION", "CAPABILITY"}:
                from botelier.voice.flows.native_tool_actions import NativeToolActionHandler

                return await NativeToolActionHandler(self).execute(
                    node, config, facts, confirmation, tool_config, tool_type,
                )
            if tool_type not in {"SEND_SMS", "SEND_EMAIL"}:
                return _failure("tool_type_not_supported")
            arguments = render_json_template(
                config["argumentsTemplate"], facts,
            )
            recipient = arguments.get("recipient")
            body = arguments.get("body")
            subject = arguments.get("subject", "")
            if (
                set(arguments) - {"recipient", "body", "subject"}
                or not isinstance(recipient, str) or not isinstance(body, str)
                or tool_type == "SEND_SMS" and "subject" in arguments
            ):
                return _failure("messaging_arguments_invalid")
            from botelier.voice.flows.native_messaging import NativeMessenger

            if tool_type == "SEND_SMS":
                if self.messenger is None:
                    return _failure("messenger_unavailable")
                invalid = NativeMessenger.validate_sms(
                    recipient, body, self.messenger.from_number,
                )
            else:
                invalid = NativeMessenger.validate_email(
                    None, recipient, subject, body, self.compiled.identity,
                )
                connection_id = tool_config.get("connection_id")
                if not isinstance(connection_id, str) or not connection_id:
                    return _failure("email_sender_unavailable")
                sender_valid = await asyncio.to_thread(
                    self._email_sender_is_owned, connection_id,
                )
                if not sender_valid:
                    return _failure("sender_scope_mismatch", "auth_error")
            if invalid:
                return _failure(invalid)
        except LookupError:
            return _failure("tool_not_found", "not_found")
        except PermissionError:
            return _failure("tool_scope_mismatch", "auth_error")
        except (KeyError, RequestTemplateError, TypeError, ValueError):
            return _failure("messaging_arguments_invalid")
        except Exception:
            return _failure("tool_binding_unavailable", "auth_error")

        if not self._confirmation_matches(confirmation, facts, node, references):
            return _failure("confirmation_required")
        try:
            mapped, projected = map_project_response(
                config, {"status": "accepted"},
                declared_variables={
                    item.key for item in self.compiled.variable_declarations
                },
            )
        except (ValueError, TypeError, ResponseProjectionError):
            return _failure("response_mapping_invalid")
        if self.preview_only:
            return _failure("preview_required")
        if self.messenger is None:
            return _failure("messenger_unavailable")
        claim = await asyncio.to_thread(
            self._ledger.claim, node.node_id, {
                "source": "tool", "tool_id": config["toolId"],
                "tool_type": tool_type, "recipient": recipient,
                "subject": subject, "body": body,
            },
        )
        if claim.outcome == "replay":
            return claim.result
        if claim.outcome != "execute":
            return _failure(claim.failure_reason or "effect_claim_blocked")
        if tool_type == "SEND_SMS":
            delivery = await self.messenger.send_sms(recipient, body)
        else:
            try:
                delivery = await asyncio.wait_for(asyncio.to_thread(
                    self._send_email_from_tool, connection_id,
                    recipient, subject, body,
                ), timeout=self.messenger.timeout)
            except asyncio.CancelledError:
                raise
            except Exception:
                delivery = NativeTerminalResult(
                    False, failure_reason="effect_outcome_unknown",
                )
        if not delivery.accepted:
            result = _failure(delivery.failure_reason or "effect_outcome_unknown")
            if delivery.failure_reason in {
                "messenger_unavailable", "invalid_recipient", "invalid_message",
                "sender_scope_mismatch", "invalid_subject", "email_sender_unavailable",
                "preview_required",
            }:
                await asyncio.to_thread(
                    self._ledger.complete, claim, result, outcome_known=True,
                )
            return result
        outcome = NativeActionResult(True, variables=mapped, llm_data=projected)
        if not await asyncio.to_thread(
            self._ledger.complete, claim, outcome, outcome_known=True,
        ):
            return _failure("effect_outcome_unknown")
        return outcome

    def _resolve_bound_tool(self, tool_id):
        from botelier.models.tool import Tool
        from botelier.models.tool_set import ToolSet

        db = self.session_factory()
        try:
            flow = db.query(Tool).filter(Tool.id == self.compiled.identity.tool_id).first()
            target = db.query(Tool).filter(Tool.id == tool_id).first()
            if (
                flow is None or target is None or str(target.is_active).casefold() != "true"
                or flow.tool_set_id is None or target.tool_set_id != flow.tool_set_id
            ):
                raise LookupError("tool_not_found")
            tool_set = db.query(ToolSet).filter(
                ToolSet.id == flow.tool_set_id,
                ToolSet.account_id == UUID(self.compiled.identity.account_id),
            ).first()
            if tool_set is None:
                raise PermissionError("tool_scope")
            target_type = getattr(target.tool_type, "value", target.tool_type)
            if target_type not in {"SEND_SMS", "SEND_EMAIL"}:
                config = dict(target.config or {})
                config["_native_tool_name"] = target.name
                config["_native_tool_description"] = target.description
                return config, str(target_type)
            return dict(target.config or {}), str(target_type)
        finally:
            try:
                db.close()
            except Exception:
                pass

    def _send_email_from_tool(self, connection_id, recipient, subject, body):
        from sqlalchemy.orm import joinedload
        from botelier.models.integration import AccountIntegration

        db = self.session_factory()
        try:
            try:
                parsed_id = UUID(connection_id)
            except (TypeError, ValueError, AttributeError):
                return NativeTerminalResult(
                    False, failure_reason="sender_scope_mismatch",
                )
            connection = db.query(AccountIntegration).options(
                joinedload(AccountIntegration.integration_type),
            ).filter(
                AccountIntegration.id == parsed_id,
                AccountIntegration.account_id == UUID(self.compiled.identity.account_id),
            ).first()
            if connection is None or not self.messenger._email_connection_matches(connection):
                return NativeTerminalResult(
                    False, failure_reason="sender_scope_mismatch",
                )
            return self.messenger.send_email_sync(
                connection, recipient, subject, body, db=db,
            )
        finally:
            try:
                db.close()
            except Exception:
                pass

    def _email_sender_is_owned(self, connection_id):
        from sqlalchemy.orm import joinedload
        from botelier.models.integration import AccountIntegration
        from botelier.voice.flows.native_messaging import NativeMessenger

        db = self.session_factory()
        try:
            try:
                parsed_id = UUID(connection_id)
            except (TypeError, ValueError, AttributeError):
                return False
            connection = db.query(AccountIntegration).options(
                joinedload(AccountIntegration.integration_type),
            ).filter(
                AccountIntegration.id == parsed_id,
                AccountIntegration.account_id == UUID(self.compiled.identity.account_id),
            ).first()
            return NativeMessenger.validate_email(
                connection, "preview@example.invalid", "Preview",
                "Preview", self.compiled.identity,
            ) is None
        finally:
            try:
                db.close()
            except Exception:
                pass

    async def _mcp_api(self, node, config, facts, confirmation):
        try:
            arguments = render_json_template(config["argumentsTemplate"], facts)
            mappings = self._effective_mappings(config)
            connection, read_only = await asyncio.to_thread(
                self._resolve_mcp_connection, config.get("mcpConnectionId"),
                config.get("mcpToolName"),
            )
        except LookupError:
            return _failure("mcp_connection_not_found", "not_found")
        except PermissionError:
            return _failure("mcp_connection_scope_mismatch", "auth_error")
        except (
            KeyError, RequestTemplateError, NativeResponseMappingError,
            ResponseProjectionError,
            TypeError, ValueError,
        ):
            return _failure("mcp_arguments_invalid")
        writing = not read_only
        if writing and not self._confirmation_matches(
            confirmation, facts, node, self._request_references(config),
        ):
            return _failure("confirmation_required")
        if self.preview_only:
            discovered = connection.get_discovered_tools() or []
            matching = [
                item for item in discovered
                if isinstance(item, dict) and item.get("name") == config["mcpToolName"]
            ]
            if len(matching) != 1:
                return _failure("mcp_tool_unavailable")
            try:
                self._validate_mcp_schema(
                    matching[0].get("parameters") or {}, arguments,
                )
            except (TypeError, ValueError):
                return _failure("mcp_arguments_invalid")
            return _failure("preview_required")
        claim = None
        if writing:
            claim = await asyncio.to_thread(
                self._ledger.claim, node.node_id, {
                    "source": "mcp", "connection_id": config["mcpConnectionId"],
                    "tool": config["mcpToolName"], "arguments": arguments,
                },
            )
            if claim.outcome == "replay":
                return claim.result
            if claim.outcome != "execute":
                return _failure(claim.failure_reason or "effect_claim_blocked")
        try:
            raw = await self._call_mcp_tool(
                connection, config["mcpToolName"], arguments,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return _failure("effect_outcome_unknown" if writing else "mcp_request_failed")
        if raw.get("isError"):
            return _failure("effect_outcome_unknown" if writing else "mcp_tool_error")
        try:
            mapped = self._map_outputs(raw, mappings)
            projected = project_mapped_values(mapped, config.get("responseProjection"))
        except (ValueError, TypeError, ResponseProjectionError):
            return _failure(
                "effect_outcome_unknown" if writing else "response_mapping_invalid",
            )
        outcome = NativeActionResult(True, variables=mapped, llm_data=projected)
        if writing and not await asyncio.to_thread(
            self._ledger.complete, claim, outcome, outcome_known=True,
        ):
            return _failure("effect_outcome_unknown")
        return outcome

    def _resolve_mcp_connection(self, connection_id, tool_name):
        db = self.session_factory()
        try:
            return self.resolve_mcp_tool_policy(
                db, self.compiled.identity, connection_id, tool_name,
            )
        finally:
            try:
                db.close()
            except Exception:
                pass

    @staticmethod
    def resolve_mcp_tool_policy(db, identity, connection_id, tool_name):
        """Resolve one tool against current account/property connection policy."""
        from botelier.models.mcp_connection import MCPConnection
        from botelier.models.property import Property

        try:
            parsed_id = UUID(connection_id)
        except (ValueError, TypeError, AttributeError):
            raise LookupError("mcp_connection_not_found") from None
        try:
            account_id = UUID(identity.account_id)
            property_id = UUID(identity.property_id)
        except (ValueError, TypeError, AttributeError):
            raise PermissionError("mcp_connection_scope") from None
        property_row = db.query(Property).filter(
            Property.id == property_id,
            Property.account_id == account_id,
            Property.is_active.is_(True),
        ).first()
        if property_row is None:
            raise PermissionError("mcp_connection_scope")
        connection = db.query(MCPConnection).filter(
            MCPConnection.id == parsed_id,
            MCPConnection.account_id == account_id,
            MCPConnection.is_active.is_(True),
        ).first()
        if connection is None:
            raise LookupError("mcp_connection_not_found")
        from botelier.services.native_mcp_policy import resolve_connection_policy

        policy = resolve_connection_policy(connection)
        if policy.property_id is not None:
            try:
                parsed_property = UUID(policy.property_id)
                identity_property = UUID(identity.property_id)
            except (TypeError, ValueError, AttributeError):
                raise PermissionError("mcp_connection_scope") from None
            if parsed_property != identity_property:
                raise PermissionError("mcp_connection_scope")
        elif policy.account_global is not True:
            raise PermissionError("mcp_connection_scope")
        enabled_tools = policy.enabled_tools
        read_only_tools = policy.read_only_tools
        if tool_name not in enabled_tools:
            raise PermissionError("mcp_tool_disabled")
        # Server-provided readOnly annotations are intentionally ignored.
        read_only = tool_name in read_only_tools
        return connection, read_only

    def is_mcp_tool_read_only(self, connection_id, tool_name):
        """Resolve global-MCP exposure through the same account/property policy.

        Callers may advertise only explicitly enabled read-only tools outside
        a saved flow action. Server annotations and assistant tool names alone
        are not authority to run a global mutation.
        """
        _, read_only = self._resolve_mcp_connection(connection_id, tool_name)
        return read_only

    async def _call_mcp_tool(self, connection, tool_name, arguments):
        from botelier.services.mcp_client import MCPClient
        from botelier.services.native_mcp_policy import public_connection_config

        factory = self.mcp_client_factory or MCPClient
        transport = getattr(connection.transport_type, "value", connection.transport_type)
        auth_type = getattr(connection.auth_type, "value", connection.auth_type) or "none"
        if transport not in {"sse", "streamable_http", "SSE", "STREAMABLE_HTTP"}:
            raise RuntimeError("mcp_transport_unsupported")
        client = factory(
            server_url=connection.server_url, auth_type=auth_type,
            credentials=connection.get_credentials(),
            connection_config=public_connection_config(
                connection.get_connection_config(),
            ),
            transport_type=transport,
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 15

        def operation_timeout():
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            return min(10, remaining)

        try:
            connected, _error = await asyncio.wait_for(
                client.connect(timeout=10), timeout=operation_timeout(),
            )
            if not connected:
                raise RuntimeError("mcp_connection_failed")
            tools = await asyncio.wait_for(
                client._session.list_tools(), timeout=operation_timeout(),
            )
            matches = [
                item for item in getattr(tools, "tools", ())
                if getattr(item, "name", None) == tool_name
            ]
            if len(matches) != 1:
                raise RuntimeError("mcp_tool_unavailable")
            schema = getattr(matches[0], "inputSchema", None) or {}
            self._validate_mcp_schema(schema, arguments)
            response = await asyncio.wait_for(
                client._session.call_tool(tool_name, arguments),
                timeout=operation_timeout(),
            )
            envelope = self._json_safe_mcp_value({
                "isError": bool(getattr(response, "isError", False)),
                "structuredContent": getattr(response, "structuredContent", None),
                "content": getattr(response, "content", ()) or (),
            })
            encoded = json.dumps(
                envelope, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
            )
            if len(encoded.encode("utf-8")) > 250_000:
                raise ValueError("mcp_result_too_large")
            return json.loads(encoded)
        finally:
            try:
                await asyncio.wait_for(client.disconnect(), timeout=1)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    @staticmethod
    def _validate_mcp_schema(schema, arguments):
        try:
            encoded_schema = json.dumps(
                schema, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
            )
            encoded_arguments = json.dumps(
                arguments, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
            )
        except (TypeError, ValueError, RecursionError):
            raise ValueError("mcp_schema_invalid") from None
        if (
            len(encoded_schema.encode("utf-8")) > 64_000
            or len(encoded_arguments.encode("utf-8")) > 64_000
            or not isinstance(schema, dict) or schema.get("type") != "object"
        ):
            raise ValueError("mcp_schema_invalid")
        if "$ref" in encoded_schema:
            raise ValueError("mcp_schema_ref")

        expected_types = {
            "string": str, "number": (int, float), "integer": int,
            "boolean": bool, "object": dict, "array": list,
        }

        def validate(value, definition, depth=0):
            if depth > 16 or not isinstance(definition, dict):
                raise ValueError("mcp_schema_invalid")
            kind = definition.get("type")
            expected = expected_types.get(kind)
            if expected is None or type(value) is bool and expected != bool:
                raise ValueError("mcp_arguments_invalid")
            if not isinstance(value, expected):
                raise ValueError("mcp_arguments_invalid")
            if "enum" in definition and value not in definition["enum"]:
                raise ValueError("mcp_arguments_invalid")
            if kind == "string":
                if (
                    len(value) > min(definition.get("maxLength", 16_000), 16_000)
                    or len(value) < definition.get("minLength", 0)
                ):
                    raise ValueError("mcp_arguments_invalid")
            elif kind in {"number", "integer"}:
                if "minimum" in definition and value < definition["minimum"]:
                    raise ValueError("mcp_arguments_invalid")
                if "maximum" in definition and value > definition["maximum"]:
                    raise ValueError("mcp_arguments_invalid")
            elif kind == "object":
                properties = definition.get("properties", {})
                required = definition.get("required", [])
                if (
                    not isinstance(properties, dict) or len(properties) > 128
                    or not isinstance(required, list)
                    or any(not isinstance(key, str) for key in required)
                    or len(value) > 128 or set(value) - set(properties)
                    or set(required) - set(value)
                ):
                    raise ValueError("mcp_arguments_invalid")
                for key, item in value.items():
                    validate(item, properties[key], depth + 1)
            elif kind == "array":
                items_schema = definition.get("items")
                if not isinstance(items_schema, dict) or len(value) > 256:
                    raise ValueError("mcp_schema_invalid")
                for item in value:
                    validate(item, items_schema, depth + 1)

        validate(arguments, schema)

    @staticmethod
    def _json_safe_mcp_value(value, depth=0, budget=None):
        if budget is None:
            budget = [12_000, 250_000]
        if depth > 24 or budget[0] <= 0:
            raise ValueError("mcp_result_depth")
        budget[0] -= 1
        if value is None or type(value) is bool:
            return value
        if type(value) is str:
            budget[1] -= len(value.encode("utf-8"))
            if budget[1] < 0:
                raise ValueError("mcp_result_too_large")
            return value
        if type(value) is int:
            if value.bit_length() > 1024:
                raise ValueError("mcp_result_number")
            return value
        if type(value) is float:
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError("mcp_result_number")
            return value
        if isinstance(value, dict):
            if len(value) > 2048 or any(not isinstance(key, str) for key in value):
                raise ValueError("mcp_result_shape")
            budget[1] -= sum(len(key.encode("utf-8")) for key in value)
            if budget[1] < 0:
                raise ValueError("mcp_result_too_large")
            return {
                key: NativeActionRunner._json_safe_mcp_value(
                    item, depth + 1, budget,
                )
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            if len(value) > 4096:
                raise ValueError("mcp_result_shape")
            return [
                NativeActionRunner._json_safe_mcp_value(
                    item, depth + 1, budget,
                )
                for item in value
            ]
        if hasattr(value, "model_dump"):
            return NativeActionRunner._json_safe_mcp_value(
                value.model_dump(mode="json"), depth + 1, budget,
            )
        if hasattr(value, "dict"):
            return NativeActionRunner._json_safe_mcp_value(
                value.dict(), depth + 1, budget,
            )
        raise ValueError("mcp_result_shape")

    async def _integration_api(self, node, config, facts, confirmation):
        return await self._execute_integration(
            node, config, facts, confirmation,
        )

    async def _execute_integration(
        self, node, config, facts, confirmation, *, force_write=False,
        confirmation_references=None,
    ):
        from botelier.services.action_executor import ActionContext, ActionExecutionRequest
        from botelier.services.integration_runtime.types import ResponseVariable as IntegrationResponseVariable

        method = config.get("method", "GET")
        if method not in {
            "GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE",
        }:
            return _failure("api_method_invalid")
        try:
            headers, prepared = await self._prepare_custom_request(config, facts)
            # Native flow-authored headers cannot override server-owned auth.
            if any(key.casefold() not in {"accept", "content-type"} for key in headers):
                return _failure("integration_header_override")
            integration_config, policy, risk, policy_mapping, confirm_required = await asyncio.to_thread(
                self._resolve_integration_config, config, method, headers, prepared,
            )
        except LookupError:
            return _failure("integration_not_found", "not_found")
        except PermissionError:
            return _failure("integration_policy_rejected", "auth_error")
        except (RequestTemplateError, ValueError, TypeError):
            return _failure("integration_config_invalid")
        try:
            mappings = self._effective_mappings(config, policy_mapping)
        except (NativeResponseMappingError, ResponseProjectionError, TypeError, ValueError):
            return _failure("response_mapping_invalid")

        if risk in {"financial", "payment", "collect_payment"}:
            return _failure("financial_action_not_supported", "auth_error")
        writing = (
            force_write
            or method not in _SAFE_METHODS
            or risk not in {"read", "safe"}
        )
        if (writing or confirm_required) and not self._confirmation_matches(
            confirmation, facts, node,
            confirmation_references
            if confirmation_references is not None
            else self._request_references(config),
        ):
            return _failure("confirmation_required")
        if self.preview_only:
            return _failure("preview_required")
        if writing:
            claim = await asyncio.to_thread(
                self._ledger.claim, node.node_id,
                {
                    "source": "integration", "integration_id": integration_config.integration_id,
                    "endpoint_id": integration_config.endpoint_id, "method": method,
                    "facts": facts, "operation_policy": policy,
                    "risk": risk, "confirm_required": confirm_required,
                    "body": prepared.value() if prepared is not None else None,
                },
            )
            if claim.outcome == "replay":
                return claim.result
            if claim.outcome != "execute":
                return _failure(claim.failure_reason or "effect_claim_blocked")
        else:
            claim = None

        response_variables = [
            IntegrationResponseVariable(
                variable_key=entry.variable_key, json_path=entry.json_path,
                default_value=entry.default_value if entry.has_default else None,
            )
            for entry in mappings
        ]
        integration_config.response_variables = response_variables
        request = ActionExecutionRequest(
            context=ActionContext(
                account_id=self.compiled.identity.account_id, channel=self.policy_channel,
                call_sid=self.compiled.identity.call_sid,
                flow_tool_id=self.compiled.identity.tool_id,
                flow_version_id=self.compiled.identity.flow_version_id,
                node_id=node.node_id, property_id=self.compiled.identity.property_id,
            ),
            variables=facts, integration_config=integration_config,
            response_policy=policy, prepared_body=prepared,
        )
        try:
            result = await asyncio.to_thread(
                self._execute_integration_in_owned_thread, request,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return _failure("effect_outcome_unknown" if writing else "integration_failed")
        if writing and (
            result.status_code == 0
            or getattr(result.error_type, "value", result.error_type)
            in {"timeout", "network_error"}
            or result.status_code >= 500
        ):
            return _failure("effect_outcome_unknown")
        if result.success:
            try:
                mapped = self._map_outputs(result.data, mappings)
                projected = project_mapped_values(mapped, config.get("responseProjection"))
            except (ValueError, TypeError, ResponseProjectionError):
                return _failure(
                    "effect_outcome_unknown" if writing else "response_mapping_invalid",
                )
            outcome = NativeActionResult(True, variables=mapped, llm_data=projected)
        else:
            branch = (
                "auth_error" if getattr(result.error_type, "value", result.error_type) == "auth_error"
                else "not_found" if getattr(result.error_type, "value", result.error_type) == "not_found"
                else "error"
            )
            outcome = _failure(
                "integration_auth_error" if branch == "auth_error"
                else "integration_not_found" if branch == "not_found"
                else "integration_rejected",
                branch,
            )
        if writing:
            known = outcome.success or (
                not result.success and is_definitive_rejection(result.status_code)
            )
            if not known:
                return _failure("effect_outcome_unknown")
            if not await asyncio.to_thread(
                self._ledger.complete, claim, outcome, outcome_known=True,
            ):
                return _failure("effect_outcome_unknown")
        return outcome

    async def _capability_api(self, node, config, facts, confirmation):
        from botelier.services.capabilities.registry import get_capability

        capability_name = config.get("capability")
        spec = get_capability(capability_name)
        if spec is None or spec.service_backed:
            return _failure("capability_unavailable")
        if capability_name == "validate_reservation_quote":
            from botelier.voice.flows.native_quote_actions import (
                NativeQuoteError, prepare_quote,
            )

            try:
                return prepare_quote(
                    config, facts,
                    variable_declarations=self.compiled.variable_declarations,
                ).result
            except NativeQuoteError as exc:
                return _failure(exc.code)
        if spec.native_flow_only:
            return _failure("capability_unavailable")
        try:
            arguments = (
                render_json_template(config["argumentsTemplate"], facts)
                if "argumentsTemplate" in config else {
                    key: facts[key] for key in spec.parameters if key in facts
                }
            )
            self._validate_mcp_schema(spec.json_schema(), arguments)
            resolved = await asyncio.to_thread(
                self._resolve_capability, capability_name, arguments, facts,
                config, bool(spec.mutating),
            )
        except LookupError:
            return _failure("capability_unavailable", "not_found")
        except PermissionError:
            return _failure("capability_scope_mismatch", "auth_error")
        except (TypeError, ValueError, KeyError):
            return _failure("capability_arguments_invalid")

        api_config, translated, confirmation_fields, is_write = resolved
        if is_write and not self._confirmation_matches(
            confirmation, facts, node, confirmation_fields,
        ):
            return _failure("confirmation_required")
        return await self._execute_integration(
            node, api_config, translated, confirmation,
            force_write=is_write, confirmation_references=confirmation_fields,
        )

    def _resolve_capability(
        self, capability_name, arguments, facts, source_config, is_write,
    ):
        from botelier.models.integration import AccountIntegration
        from botelier.services.capabilities.resolver import CapabilityResolver
        from botelier.services.property_scope import property_access_allowed
        from botelier.services.capabilities.registry import get_capability

        db = self.session_factory()
        try:
            resolver = CapabilityResolver(
                db, self.compiled.identity.account_id,
                self.compiled.identity.property_id,
            )
            resolution = resolver.resolve(capability_name)
            if resolution is None:
                raise LookupError("capability_unavailable")
            connection = db.query(AccountIntegration).filter(
                AccountIntegration.id == UUID(resolution.integration_id),
                AccountIntegration.account_id == UUID(self.compiled.identity.account_id),
            ).first()
            if (
                connection is None
                or getattr(connection.status, "value", connection.status) != "connected"
                or connection.integration_type is None
                or connection.integration_type.is_enabled is not True
                or not property_access_allowed(
                    self.compiled.identity.property_id, connection.property_id,
                )
            ):
                raise PermissionError("capability_connection_scope")
            endpoints = connection.integration_type.get_endpoints() or []
            matches = [
                endpoint for endpoint in endpoints
                if isinstance(endpoint, dict)
                and endpoint.get("id") == resolution.endpoint_id
                and endpoint.get("capability") == capability_name
            ]
            if len(matches) != 1:
                raise PermissionError("capability_endpoint_scope")
            endpoint = matches[0]
            endpoint_enabled = endpoint.get("enabled", endpoint.get("is_enabled", True))
            if endpoint_enabled is False or endpoint_enabled == 0 or (
                isinstance(endpoint_enabled, str)
                and endpoint_enabled.casefold() in {"false", "disabled", "no"}
            ):
                raise PermissionError("capability_endpoint_disabled")
            source_variables = {
                item.key for item in self.compiled.variable_declarations
            }
            endpoint_references = set()
            pending = [endpoint]
            while pending:
                value = pending.pop()
                if isinstance(value, dict):
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
                elif isinstance(value, str):
                    endpoint_references.update(_TOKEN.findall(value))
            extras = {
                key: facts[key]
                for key in endpoint_references & source_variables
                if key not in arguments and key in facts
            }
            vendor_vars = dict(arguments)
            vendor_vars.update(extras)
            translated = resolver.translate_variables(resolution, vendor_vars)
            synthetic = {
                "apiSource": "integration",
                "integrationId": str(connection.id),
                "integrationSlug": connection.integration_type.slug,
                "endpointId": resolution.endpoint_id,
                "method": resolution.method,
                "path": endpoint.get("path"),
                "timeout": source_config.get("timeout", 8),
                "retryCount": source_config.get("retryCount", 0),
                "responseMapping": source_config.get("responseMapping") or {},
                "responseVariables": source_config.get("responseVariables") or [],
                "responseProjection": source_config.get("responseProjection"),
            }
            if get_capability(capability_name) is None:
                raise LookupError("capability_unavailable")
            return synthetic, translated, set(arguments) | set(extras), is_write
        finally:
            try:
                db.close()
            except Exception:
                pass

    def _resolve_integration_config(self, api, method, headers, prepared):
        import json
        from botelier.models.integration import (
            AccountIntegration, IntegrationStatus,
        )
        from botelier.models.operation_policy import ConnectionOperationPolicy
        from botelier.services.integration_runtime.types import IntegrationAPIConfig

        db = self.session_factory()
        try:
            if api.get("integrationId"):
                try:
                    connection_id = UUID(api["integrationId"])
                except (ValueError, TypeError, AttributeError):
                    raise LookupError("integration_not_found") from None
                connection = db.query(AccountIntegration).filter(
                    AccountIntegration.id == connection_id,
                    AccountIntegration.account_id == UUID(self.compiled.identity.account_id),
                ).first()
            elif api.get("integrationSlug"):
                connection = self._resolve_integration_slug(
                    db, api["integrationSlug"],
                )
            else:
                raise LookupError("integration_not_found")
            if connection is None or connection.status != IntegrationStatus.CONNECTED:
                raise LookupError("integration_not_found")
            if connection.property_id is not None:
                if str(connection.property_id) != self.compiled.identity.property_id:
                    raise PermissionError("integration_scope")
            integration_type = connection.integration_type
            if integration_type is None or not integration_type.is_enabled:
                raise LookupError("integration_not_found")
            if api.get("integrationSlug") and integration_type.slug != api["integrationSlug"]:
                raise PermissionError("integration_identity")
            endpoints = integration_type.get_endpoints() or []
            configured_path = api.get("path")
            if not configured_path and api.get("endpointId"):
                by_id = [
                    item for item in endpoints
                    if isinstance(item, dict) and item.get("id") == api["endpointId"]
                ]
                if len(by_id) == 1:
                    configured_path = by_id[0].get("path")
            if not isinstance(configured_path, str) or not configured_path:
                raise PermissionError("integration_path")
            parsed_config_path = urlsplit(configured_path)
            if (
                parsed_config_path.scheme or parsed_config_path.netloc
                or parsed_config_path.fragment or not parsed_config_path.path.startswith("/")
            ):
                raise PermissionError("integration_path")
            requested_query = parse_qsl(
                parsed_config_path.query, keep_blank_values=True, strict_parsing=True,
            )
            if len({key for key, _ in requested_query}) != len(requested_query):
                raise PermissionError("integration_path")

            candidates = self._matching_integration_endpoints(
                endpoints, api, method, parsed_config_path, requested_query,
            )
            resolved = []
            for item in candidates:
                item_id = item.get("id")
                if not isinstance(item_id, str) or not item_id:
                    continue
                policy = None
                if integration_type.origin == "customer_imported":
                    policy = db.query(ConnectionOperationPolicy).filter(
                        ConnectionOperationPolicy.account_integration_id == connection.id,
                        ConnectionOperationPolicy.operation_id == item_id,
                    ).first()
                    if (
                        policy is None or not policy.enabled
                        or policy.test_status != "passed" or policy.test_passed is False
                        or policy.approval_required
                        or policy.allowed_channels is not None
                        and self.policy_channel not in policy.allowed_channels
                    ):
                        continue
                resolved.append((item, policy))
            if len(resolved) != 1:
                raise PermissionError("integration_endpoint_ambiguous")
            endpoint, policy = resolved[0]
            endpoint_id = endpoint["id"]
            current_path = endpoint.get("path")
            merged_overrides = dict(api.get("queryParamOverrides") or {})
            for key, value in requested_query:
                merged_overrides.setdefault(key, value)
            confirm_required = False
            if policy is not None:
                risk = str(policy.risk_level or endpoint.get("risk_level", "write")).casefold()
                confirm_required = bool(
                    policy.confirm_required or endpoint.get("confirm_required", False)
                )
                approved_mapping = policy.response_mapping or {}
                requested_mapping = dict(api.get("responseMapping") or {})
                for entry in api.get("responseVariables") or []:
                    requested_mapping[entry["variableKey"]] = entry["jsonPath"]
                if approved_mapping and any(
                    approved_mapping.get(key) != path
                    for key, path in requested_mapping.items()
                ):
                    raise PermissionError("integration_mapping")
                policy_mapping = requested_mapping or approved_mapping
                response_policy = policy.to_dict()
            else:
                risk = str(endpoint.get("risk_level", "read")).casefold()
                policy_mapping = {}
                response_policy = None
                confirm_required = bool(endpoint.get("confirm_required", False))
            integration_config = IntegrationAPIConfig(
                integration_id=str(connection.id),
                endpoint_id=endpoint_id, method=method,
                path=current_path,
                endpoint_template=configured_path,
                headers=headers,
                query_param_overrides=merged_overrides,
                timeout=api.get("timeout", 8),
                retry_count=api.get("retryCount", 0),
                prepared_body=prepared,
            )
            return integration_config, response_policy, risk, policy_mapping, confirm_required
        finally:
            try:
                db.close()
            except Exception:
                pass

    def _resolve_integration_slug(self, db, slug):
        from botelier.models.integration import AccountIntegration, IntegrationStatus

        if not isinstance(slug, str) or not slug or len(slug) > 128:
            raise LookupError("integration_not_found")
        candidates = db.query(AccountIntegration).filter(
            AccountIntegration.account_id == UUID(self.compiled.identity.account_id),
            AccountIntegration.status == IntegrationStatus.CONNECTED,
        ).all()
        matching = [
            connection for connection in candidates
            if connection.integration_type is not None
            and connection.integration_type.is_enabled is True
            and connection.integration_type.slug == slug
            and (
                connection.property_id is None
                or str(connection.property_id) == self.compiled.identity.property_id
            )
        ]
        bound = [
            connection for connection in matching
            if str(connection.property_id or "") == self.compiled.identity.property_id
        ]
        selected = bound or [
            connection for connection in matching if connection.property_id is None
        ]
        if not selected:
            raise LookupError("integration_not_found")
        if len(selected) != 1:
            raise PermissionError("integration_slug_ambiguous")
        return selected[0]

    @staticmethod
    def _matching_integration_endpoints(endpoints, api, method, parsed_path, requested_query):
        matches = []
        for item in endpoints:
            if not isinstance(item, dict):
                continue
            enabled = item.get("enabled", item.get("is_enabled", True))
            if enabled is False or enabled == 0 or (
                isinstance(enabled, str) and enabled.casefold() in {"false", "disabled", "no"}
            ):
                continue
            try:
                endpoint_path = urlsplit(item.get("path", "")).path
            except (TypeError, ValueError):
                continue
            endpoint_method = item.get("method", "GET")
            if (
                not isinstance(endpoint_method, str)
                or endpoint_method.upper() != method
                or parsed_path.path != endpoint_path
            ):
                continue
            declared = item.get("query_params") or []
            allowed_keys = {
                field.get("key") for field in declared
                if isinstance(field, dict) and isinstance(field.get("key"), str)
            }
            if any(key not in allowed_keys for key, _ in requested_query):
                continue
            overrides = api.get("queryParamOverrides") or {}
            if any(key not in allowed_keys for key in overrides):
                continue
            if any(
                key in overrides and overrides[key] != value
                for key, value in requested_query
            ):
                continue
            if api.get("endpointId") and item.get("id") != api["endpointId"]:
                continue
            matches.append(item)
        return matches

    def _execute_integration_in_owned_thread(self, request):
        import asyncio
        from botelier.services.action_executor import ActionExecutor

        db = self.session_factory()
        try:
            executor = (
                self.http_executor_factory(db) if self.http_executor_factory
                else ActionExecutor(db)
            )
            return asyncio.run(executor.execute(request))
        finally:
            try:
                db.close()
            except Exception:
                pass

    async def _save_record(self, node, data, facts, confirmation):
        setting = data.get("saveRecord", data.get("save_record")) or {}
        references = set()
        for template in list(setting.get("mapping", {}).values()) + [
            setting.get("status", ""),
        ]:
            references.update(_TOKEN.findall(template))
        if not self._confirmation_matches(confirmation, facts, node, references):
            return _failure("confirmation_required")
        from botelier.voice.flows.native_record_actions import NativeRecordActionStore

        store = NativeRecordActionStore(self.session_factory, self.compiled.identity)
        try:
            prepared = await asyncio.to_thread(
                store.prepare, setting, facts,
            )
        except LookupError:
            return _failure("record_type_unavailable")
        except (ValueError, TypeError, RequestTemplateError):
            return _failure("record_values_invalid")
        if prepared is None:
            return _failure("record_source_unavailable")
        record_data, record_status, call_log_id, assistant_id = prepared
        if self.preview_only:
            return _failure("preview_required")
        return await asyncio.to_thread(
            store.apply, node.node_id, setting, record_data, record_status,
            call_log_id, assistant_id,
        )

    async def _custom_api(self, node, config, facts, confirmation):
        from botelier.services.action_executor import (
            ActionContext, ActionExecutionRequest, ActionExecutor,
        )

        method = config.get("method", "GET")
        if not isinstance(method, str) or method not in {
            "GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE",
        }:
            return _failure("api_method_invalid")
        writing = method not in _SAFE_METHODS
        try:
            url = render_request_url(config.get("url", ""), facts)
            headers, prepared = await self._prepare_custom_request(config, facts)
            mappings = self._effective_mappings(config)
        except NativeResponseMappingError:
            return _failure("response_mapping_invalid")
        except (RequestTemplateError, ValueError, TypeError):
            return _failure("api_request_invalid")

        if writing:
            if not self._confirmation_matches(
                confirmation, facts, node, self._request_references(config),
            ):
                return _failure("confirmation_required")
        if self.preview_only:
            return _failure("preview_required")
        if writing:
            claim = await asyncio.to_thread(
                self._ledger.claim, node.node_id,
                {"method": method, "url": url, "headers": headers,
                 "body": prepared.value() if prepared is not None else None},
            )
            if claim.outcome == "replay":
                return claim.result
            if claim.outcome != "execute":
                return _failure(claim.failure_reason or "effect_claim_blocked")
        else:
            claim = None

        request_config = {
            "method": method, "url": url, "headers": headers,
            "timeout": config.get("timeout", 8), "retryCount": config.get("retryCount", 0),
            "onSuccess": config.get("onSuccess"), "onError": config.get("onError"),
            "onNotFound": config.get("onNotFound"), "onAuthError": config.get("onAuthError"),
            "responseMapping": config.get("responseMapping") or {},
            "responseVariables": config.get("responseVariables") or [],
        }
        try:
            executor = (
                self.http_executor_factory(None) if self.http_executor_factory
                else ActionExecutor(None)
            )
            context = ActionContext(
                account_id=self.compiled.identity.account_id, channel=self.policy_channel,
                call_sid=self.compiled.identity.call_sid,
                flow_tool_id=self.compiled.identity.tool_id,
                flow_version_id=self.compiled.identity.flow_version_id,
                node_id=node.node_id, property_id=self.compiled.identity.property_id,
            )
            request = ActionExecutionRequest(
                context=context, variables=facts, test_config=request_config,
                prepared_body=prepared,
            )
            result = await executor.execute(request)
        except asyncio.CancelledError:
            raise
        except Exception:
            return _failure("effect_outcome_unknown" if writing else "api_request_failed")

        if writing and (
            result.status_code == 0
            or getattr(result.error_type, "value", result.error_type)
            in {"timeout", "network_error"}
            or result.status_code >= 500
        ):
            return _failure("effect_outcome_unknown")
        if result.success:
            try:
                mapped = self._map_outputs(result.data, mappings)
                projected = project_mapped_values(mapped, config.get("responseProjection"))
            except (ValueError, TypeError, ResponseProjectionError):
                return _failure(
                    "effect_outcome_unknown" if writing else "response_mapping_invalid",
                )
            outcome = NativeActionResult(True, variables=mapped, llm_data=projected)
        else:
            branch = (
                "auth_error" if getattr(result.error_type, "value", result.error_type) == "auth_error"
                else "not_found" if getattr(result.error_type, "value", result.error_type) == "not_found"
                else "error"
            )
            outcome = _failure(
                "api_auth_error" if branch == "auth_error"
                else "api_not_found" if branch == "not_found" else "api_rejected",
                branch,
            )
        if writing:
            known = result.success or is_definitive_rejection(result.status_code)
            if not known:
                return _failure("effect_outcome_unknown")
            completed = await asyncio.to_thread(
                self._ledger.complete, claim, outcome, outcome_known=True,
            )
            if not completed:
                return _failure("effect_outcome_unknown")
        return outcome

    async def _prepare_custom_request(self, config, facts):
        raw_headers = config.get("headers") or {}
        if not isinstance(raw_headers, dict):
            raise RequestTemplateError("request_headers")
        secrets_needed = set()
        for key, value in raw_headers.items():
            if (
                not isinstance(key, str) or not _HEADER_NAME.fullmatch(key)
                or key.casefold() in _BLOCKED_HEADERS
                or not isinstance(value, str) or "\r" in value or "\n" in value
            ):
                raise RequestTemplateError("request_headers")
            secret = _SECRET.fullmatch(value)
            if "{{" in value and not secret:
                raise RequestTemplateError("request_headers")
            if secret:
                secrets_needed.add(secret.group(1))
        body_template = config.get("bodyTemplate")
        if body_template is not None:
            if not isinstance(body_template, str):
                raise RequestTemplateError("request_body")
            secrets_needed.update(referenced_secrets(body_template))
        secrets = await asyncio.to_thread(self._load_account_secrets, secrets_needed)

        def resolve_secret(key):
            if key not in secrets:
                raise RequestTemplateError("request_secret_unavailable")
            return secrets[key]

        headers = {}
        for key, value in raw_headers.items():
            secret = _SECRET.fullmatch(value)
            if secret:
                if key.casefold() not in {"authorization", "x-api-key", "api-key"}:
                    raise RequestTemplateError("request_secret_sink")
                headers[key] = resolve_secret(secret.group(1))
            else:
                headers[key] = value

        if body_template is None:
            return headers, None
        content_type = next(
            (value for key, value in headers.items() if key.casefold() == "content-type"),
            "application/json",
        )
        media = content_type.split(";", 1)[0].strip().casefold()
        if media == "application/json" or media.endswith("+json"):
            value = render_json_template(
                body_template, facts, secret_resolver=resolve_secret,
            )
            body = PreparedRequestBody("json", value)
        elif media == "application/x-www-form-urlencoded":
            value = render_json_template(
                body_template, facts, secret_resolver=resolve_secret,
            )
            body = PreparedRequestBody("data", value)
        elif media == "multipart/form-data":
            value = render_json_template(
                body_template, facts, secret_resolver=resolve_secret,
            )
            body = PreparedRequestBody("files", value)
        elif media in {"text/plain", "application/xml", "text/xml"} or media.endswith("+xml"):
            content = render_content_template(
                body_template, facts, media_type=content_type,
                secret_resolver=resolve_secret,
            )
            body = PreparedRequestBody("content", content)
        else:
            raise RequestTemplateError("request_content_type")
        headers = prepare_body_headers(body, headers)
        return headers, body

    def _load_account_secrets(self, names):
        if not names:
            return {}
        from botelier.models.integration import AccountSecret

        db = self.session_factory()
        try:
            rows = db.query(AccountSecret).filter(
                AccountSecret.account_id == UUID(self.compiled.identity.account_id),
                AccountSecret.key.in_(list(names)),
            ).all()
            return {row.key: row.get_value() for row in rows}
        finally:
            try:
                db.close()
            except Exception:
                pass

    def _effective_mappings(self, config, override=None):
        declared = {item.key for item in self.compiled.variable_declarations}
        return resolve_response_variables(
            config,
            variable_declarations=self.compiled.variable_declarations,
            mapping_override=override,
            declared_variables=declared,
        )

    @staticmethod
    def _map_outputs(response, mappings):
        return map_response_data(response, mappings)

    @staticmethod
    def _request_references(config):
        references = set()
        for key in ("url", "bodyTemplate", "path", "argumentsTemplate"):
            value = config.get(key)
            if isinstance(value, str):
                references.update(_TOKEN.findall(value))
        return references

    def _confirmation_matches(self, confirmation, facts, node, references):
        if not isinstance(confirmation, NativeConfirmation):
            return False
        consent_node = self.compiled.node(confirmation.node_id)
        if consent_node is None or consent_node.type != "confirmation":
            return False
        values = confirmation.values()
        if not set(references) <= set(confirmation.confirmed_fields):
            return False
        return all(
            key in facts and key in values and values[key] == facts[key]
            for key in confirmation.confirmed_fields
        )

    async def close(self):
        self._closed = True


def map_project_response(
    config, response, declared_variables=None, *, variable_declarations=(),
):
    """Purely map provider/sample data and apply the exact configured projection."""
    return _map_project_response(
        config, response, declared_variables=declared_variables,
        variable_declarations=variable_declarations,
    )


__all__ = ["NativeActionRunner", "map_project_response"]
