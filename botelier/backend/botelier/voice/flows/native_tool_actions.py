"""Execution for explicitly selected, current Tool API operations."""

import asyncio
import re
from uuid import UUID

from botelier.services.request_templates import (
    RequestTemplateError,
    render_json_template,
    render_request_url,
)
from botelier.voice.flows.native_response_mapping import (
    NativeResponseMappingError,
    map_response_data,
)
from botelier.services.response_projection import project_mapped_values


_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_DEFINITIVE_REJECTION_STATUSES = {
    400, 401, 403, 404, 405, 409, 410, 415, 422, 429,
}
_PAYMENT_TERMS = {
    "charge", "checkout", "collectpayment", "invoice", "payment", "refund",
}


class NativeToolActionHandler:
    """Runs only selected Tool rows; never delegates to the legacy FlowExecutor."""

    def __init__(self, runner):
        self.runner = runner

    async def execute(self, node, source_config, facts, confirmation, tool_config, tool_type):
        if tool_type == "API_REQUEST":
            return await self._api_request(
                node, source_config, facts, confirmation, tool_config,
            )
        if tool_type == "DYNAMIC_OPERATION":
            return await self._dynamic_operation(
                node, source_config, facts, confirmation,
            )
        if tool_type == "CAPABILITY":
            return await self._capability_tool(
                node, source_config, facts, confirmation, tool_config,
            )
        return self._failure("tool_type_not_supported")

    async def _api_request(self, node, source_config, facts, confirmation, tool_config):
        from botelier.services.action_executor import ActionContext, ActionExecutionRequest

        try:
            arguments = render_json_template(source_config["argumentsTemplate"], facts)
            parameters = tool_config.get("parameters") or {}
            if not isinstance(parameters, dict):
                raise ValueError("tool_parameters")
            schema = {
                "type": "object",
                "properties": parameters,
                "required": [
                    key for key, value in parameters.items()
                    if isinstance(value, dict) and value.get("required") is True
                ],
            }
            self.runner._validate_mcp_schema(schema, arguments)
            method = str(tool_config.get("method", "GET")).upper()
            if method not in {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"}:
                raise ValueError("tool_method")
            risk = str(
                tool_config.get("risk_level", tool_config.get("riskLevel", ""))
            ).casefold()
            if risk in {"financial", "payment", "collect_payment"}:
                raise ValueError("financial_tool_not_supported")
            self._reject_payment_target(
                tool_config.get("_native_tool_name", ""),
                tool_config.get("_native_tool_description", ""),
                tool_config.get("url", ""),
            )
            request_url = render_request_url(tool_config.get("url", ""), arguments)
            prepared_config = dict(tool_config)
            prepared_config["url"] = request_url
            if "bodyTemplate" not in prepared_config and "body_template" in prepared_config:
                prepared_config["bodyTemplate"] = prepared_config["body_template"]
            headers, prepared_body = await self.runner._prepare_custom_request(
                prepared_config, arguments,
            )
        except (KeyError, RequestTemplateError, TypeError, ValueError):
            return self._failure("tool_arguments_invalid")
        try:
            mappings = self._approved_mappings(
                source_config, tool_config.get("responseMapping")
                or tool_config.get("response_mapping") or {},
            )
        except (NativeResponseMappingError, TypeError, ValueError):
            return self._failure("response_mapping_invalid")

        references = self.runner._request_references(source_config)
        writing = method not in _SAFE_METHODS or (
            bool(risk) and risk not in {"read", "safe"}
        )
        if writing and not self.runner._confirmation_matches(
            confirmation, facts, node, references,
        ):
            return self._failure("confirmation_required")
        if self.runner.preview_only:
            return self._failure("preview_required")

        claim = None
        if writing:
            claim = await asyncio.to_thread(
                self.runner._ledger.claim, node.node_id, {
                    "source": "tool_api", "tool_id": source_config["toolId"],
                    "method": method, "url": request_url, "arguments": arguments,
                    "body": prepared_body.value() if prepared_body is not None else None,
                },
            )
            if claim.outcome == "replay":
                return claim.result
            if claim.outcome != "execute":
                return self._failure(claim.failure_reason or "effect_claim_blocked")

        request = ActionExecutionRequest(
            context=ActionContext(
                account_id=self.runner.compiled.identity.account_id,
                channel=self.runner.policy_channel,
                call_sid=self.runner.compiled.identity.call_sid,
                tool_id=str(source_config["toolId"]),
                flow_tool_id=self.runner.compiled.identity.tool_id,
                flow_version_id=self.runner.compiled.identity.flow_version_id,
                node_id=node.node_id,
                property_id=self.runner.compiled.identity.property_id,
            ),
            variables=arguments, legacy_config=prepared_config,
            prepared_body=prepared_body,
        )
        try:
            response = await asyncio.to_thread(
                self.runner._execute_integration_in_owned_thread, request,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return self._failure("effect_outcome_unknown" if writing else "api_request_failed")

        result = self._map_result(response, source_config, mappings, writing)
        if writing:
            status = getattr(response, "status_code", 0)
            known = result.success or (
                not response.success and status in _DEFINITIVE_REJECTION_STATUSES
            )
            if not known or not await asyncio.to_thread(
                self.runner._ledger.complete, claim, result, outcome_known=True,
            ):
                return self._failure("effect_outcome_unknown")
        return result

    async def _dynamic_operation(self, node, source_config, facts, confirmation):
        from botelier.services.action_executor import ActionContext, ActionExecutionRequest

        try:
            arguments = render_json_template(source_config["argumentsTemplate"], facts)
            resolved = await asyncio.to_thread(
                self._resolve_dynamic_operation, source_config["toolId"],
                source_config, arguments,
            )
            (
                integration_config, response_policy, approved_mapping, risk,
                confirm_required, action_version_id,
            ) = resolved
            mappings = self._approved_mappings(source_config, approved_mapping)
        except LookupError:
            return self._failure("tool_not_found", "not_found")
        except PermissionError:
            return self._failure("tool_scope_mismatch", "auth_error")
        except (KeyError, NativeResponseMappingError, RequestTemplateError, TypeError, ValueError):
            return self._failure("tool_arguments_invalid")

        method = str(integration_config.method).upper()
        writing = method not in _SAFE_METHODS or risk not in {"read", "safe"}
        if risk in {"financial", "payment", "collect_payment"}:
            return self._failure("financial_action_not_supported", "auth_error")
        references = self.runner._request_references(source_config)
        if (writing or confirm_required) and not self.runner._confirmation_matches(
            confirmation, facts, node, references,
        ):
            return self._failure("confirmation_required")
        if self.runner.preview_only:
            return self._failure("preview_required")

        claim = None
        if writing:
            claim = await asyncio.to_thread(
                self.runner._ledger.claim, node.node_id, {
                    "source": "dynamic_operation", "tool_id": source_config["toolId"],
                    "integration_id": integration_config.integration_id,
                    "endpoint_id": integration_config.endpoint_id,
                    "method": method, "action_version_id": action_version_id,
                    "arguments": arguments, "operation_policy": response_policy,
                    "risk": risk, "confirm_required": confirm_required,
                },
            )
            if claim.outcome == "replay":
                return claim.result
            if claim.outcome != "execute":
                return self._failure(claim.failure_reason or "effect_claim_blocked")

        integration_config.response_variables = self._integration_response_variables(mappings)
        request = ActionExecutionRequest(
            context=ActionContext(
                account_id=self.runner.compiled.identity.account_id,
                channel=self.runner.policy_channel,
                call_sid=self.runner.compiled.identity.call_sid,
                tool_id=str(source_config["toolId"]),
                flow_tool_id=self.runner.compiled.identity.tool_id,
                flow_version_id=self.runner.compiled.identity.flow_version_id,
                node_id=node.node_id,
                property_id=self.runner.compiled.identity.property_id,
            ),
            variables=arguments, integration_config=integration_config,
            response_policy=response_policy,
        )
        try:
            response = await asyncio.to_thread(
                self.runner._execute_integration_in_owned_thread, request,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return self._failure("effect_outcome_unknown" if writing else "api_request_failed")
        result = self._map_result(response, source_config, mappings, writing)
        if writing:
            status = getattr(response, "status_code", 0)
            known = result.success or (
                not response.success and status in _DEFINITIVE_REJECTION_STATUSES
            )
            if not known or not await asyncio.to_thread(
                self.runner._ledger.complete, claim, result, outcome_known=True,
            ):
                return self._failure("effect_outcome_unknown")
        return result

    def _resolve_dynamic_operation(self, tool_id, source_config, arguments):
        from botelier.models.integration import (
            AccountIntegration, IntegrationAction, IntegrationActionKind,
            IntegrationActionStatus, IntegrationActionVersion, IntegrationStatus,
        )
        from botelier.models.operation_policy import ConnectionOperationPolicy
        from botelier.models.tool import Tool, ToolType
        from botelier.models.tool_set import ToolSet
        from botelier.services.operation_publisher import build_operation_api_config
        from botelier.services.property_scope import property_access_allowed

        db = self.runner.session_factory()
        try:
            target = db.query(Tool).filter(Tool.id == tool_id).first()
            flow = db.query(Tool).filter(
                Tool.id == self.runner.compiled.identity.tool_id,
            ).first()
            if (
                target is None or flow is None
                or str(target.is_active).casefold() != "true"
                or getattr(target.tool_type, "value", target.tool_type)
                != ToolType.DYNAMIC_OPERATION.value
                or target.tool_set_id is None or target.tool_set_id != flow.tool_set_id
            ):
                raise LookupError("tool_not_found")
            tool_set = db.query(ToolSet).filter(
                ToolSet.id == flow.tool_set_id,
                ToolSet.account_id == UUID(self.runner.compiled.identity.account_id),
            ).first()
            if tool_set is None:
                raise PermissionError("tool_scope")

            target_config = dict(target.config or {})
            action_id = UUID(str(target_config.get("integration_action_id") or ""))
            connection_id = UUID(str(target_config.get("connection_id") or ""))
            operation_id = str(target_config.get("operation_id") or "")
            if not operation_id:
                raise LookupError("operation_not_found")
            action = db.query(IntegrationAction).filter(
                IntegrationAction.id == action_id,
                IntegrationAction.account_id == UUID(self.runner.compiled.identity.account_id),
                IntegrationAction.connection_id == connection_id,
                IntegrationAction.source_endpoint_id == operation_id,
                IntegrationAction.kind == IntegrationActionKind.IMPORTED,
                IntegrationAction.status == IntegrationActionStatus.PUBLISHED,
            ).first()
            if action is None or action.published_version_id is None:
                raise LookupError("operation_not_found")
            version = db.query(IntegrationActionVersion).filter(
                IntegrationActionVersion.id == action.published_version_id,
                IntegrationActionVersion.action_id == action.id,
                IntegrationActionVersion.status == IntegrationActionStatus.PUBLISHED,
            ).first()
            if version is None:
                raise LookupError("operation_not_found")
            connection = db.query(AccountIntegration).filter(
                AccountIntegration.id == connection_id,
                AccountIntegration.account_id == UUID(self.runner.compiled.identity.account_id),
                AccountIntegration.status == IntegrationStatus.CONNECTED,
            ).first()
            if (
                connection is None or connection.integration_type is None
                or connection.integration_type.is_enabled is not True
                or not property_access_allowed(
                    self.runner.compiled.identity.property_id, connection.property_id,
                )
            ):
                raise PermissionError("operation_connection_scope")
            policy = db.query(ConnectionOperationPolicy).filter(
                ConnectionOperationPolicy.account_integration_id == connection.id,
                ConnectionOperationPolicy.operation_id == operation_id,
            ).first()
            if (
                policy is None or policy.enabled is not True
                or policy.approval_required is True
                or policy.test_passed is not True
                or _enum_value(policy.test_status) != "passed"
                or self.runner.policy_channel not in (policy.allowed_channels or [])
            ):
                raise PermissionError("operation_policy")

            endpoints = connection.integration_type.get_endpoints() or []
            endpoint_matches = [
                item for item in endpoints
                if isinstance(item, dict) and item.get("id") == operation_id
            ]
            if len(endpoint_matches) != 1:
                raise PermissionError("operation_endpoint")
            endpoint = endpoint_matches[0]
            if _endpoint_disabled(endpoint) or _is_payment_operation(endpoint):
                raise PermissionError("operation_disallowed")
            execution_config = version.config or {}
            if (
                execution_config.get("endpoint_id") != operation_id
                or execution_config.get("method", "GET").upper()
                != str(endpoint.get("method", "GET")).upper()
                or execution_config.get("path") != endpoint.get("path")
            ):
                raise PermissionError("operation_contract_changed")

            schema = version.input_schema or {}
            self.runner._validate_mcp_schema(schema, arguments)
            integration_config = build_operation_api_config(
                execution_config,
                fallback_integration_id=str(connection.id),
                fallback_endpoint_id=operation_id,
            )
            if (
                str(integration_config.integration_id) != str(connection.id)
                or integration_config.endpoint_id != operation_id
            ):
                raise PermissionError("operation_binding_changed")
            approved_mapping = (
                (policy.response_mapping or {})
                or (execution_config.get("response_mapping") or {})
                or (endpoint.get("response_mapping") or {})
            )
            risk = str(policy.risk_level or endpoint.get("risk_level") or "write").casefold()
            return (
                integration_config, policy.to_dict(), approved_mapping,
                risk, bool(policy.confirm_required), str(version.id),
            )
        except (TypeError, ValueError, AttributeError):
            raise LookupError("operation_not_found") from None
        finally:
            try:
                db.close()
            except Exception:
                pass

    async def _capability_tool(self, node, source_config, facts, confirmation, tool_config):
        name = tool_config.get("capability")
        if not isinstance(name, str) or not name:
            return self._failure("capability_unavailable")
        config = dict(source_config)
        config["capability"] = name
        try:
            arguments = render_json_template(source_config["argumentsTemplate"], facts)
        except (KeyError, RequestTemplateError, TypeError, ValueError):
            return self._failure("capability_arguments_invalid")
        merged = dict(facts)
        merged.update(arguments)
        return await self.runner._capability_api(
            node, config, merged, confirmation,
        )

    def _approved_mappings(self, source_config, approved):
        if not isinstance(approved, dict):
            raise NativeResponseMappingError("mapping_policy")
        requested = {}
        for key, path in (source_config.get("responseMapping") or {}).items():
            requested[key] = path
        for item in source_config.get("responseVariables") or ():
            key, path = item.get("variableKey"), item.get("jsonPath")
            if key in requested and requested[key] != path:
                raise NativeResponseMappingError("mapping_conflict")
            requested[key] = path
        if any(approved.get(key) != path for key, path in requested.items()):
            raise NativeResponseMappingError("mapping_policy")
        return self.runner._effective_mappings(
            source_config, override=requested,
        )

    @staticmethod
    def _integration_response_variables(mappings):
        from botelier.services.integration_runtime.types import ResponseVariable

        return [
            ResponseVariable(
                variable_key=entry.variable_key,
                json_path=entry.json_path,
                default_value=entry.default_value if entry.has_default else None,
            )
            for entry in mappings
        ]

    def _map_result(self, response, source_config, mappings, writing):
        if response.success:
            try:
                mapped = map_response_data(response.data, mappings)
                projected = project_mapped_values(
                    mapped, source_config.get("responseProjection"),
                )
            except (NativeResponseMappingError, TypeError, ValueError):
                return self._failure(
                    "effect_outcome_unknown" if writing else "response_mapping_invalid",
                )
            from botelier.voice.flows.native_actions import NativeActionResult

            return NativeActionResult(True, variables=mapped, llm_data=projected)
        if writing and (
            response.status_code == 0 or response.status_code >= 500
            or _enum_value(response.error_type) in {"timeout", "network_error"}
        ):
            return self._failure("effect_outcome_unknown")
        return self._failure("tool_operation_rejected")

    def _failure(self, reason, branch="error"):
        from botelier.voice.flows.native_actions import _failure

        return _failure(reason, branch)

    @staticmethod
    def _reject_payment_target(*values):
        normalized = " ".join(
            re.sub(r"[^a-z0-9]+", "", str(value).casefold())
            for value in values
        )
        if any(term in normalized for term in _PAYMENT_TERMS):
            raise ValueError("payment_operations_not_supported")


def _endpoint_disabled(endpoint):
    value = endpoint.get("enabled", endpoint.get("is_enabled", True))
    return value is False or value == 0 or (
        isinstance(value, str) and value.casefold() in {"false", "disabled", "no"}
    )


def _is_payment_operation(endpoint):
    risk = str(endpoint.get("risk_level", "")).casefold()
    capability = str(endpoint.get("capability", "")).casefold()
    if risk in {"financial", "payment", "collect_payment"}:
        return True
    if capability in {"collect_payment", "payment"}:
        return True
    return any(
        term in re.sub(r"[^a-z0-9]+", "", str(endpoint.get(key, "")).casefold())
        for key in ("id", "name", "path", "description", "summary")
        for term in _PAYMENT_TERMS
    )


def _enum_value(value):
    return str(getattr(value, "value", value) or "").casefold()
