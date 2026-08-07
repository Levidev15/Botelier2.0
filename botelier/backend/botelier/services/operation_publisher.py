"""Operation Publisher — Universal API Adapter.

Handles the Configured → Tested → Published lifecycle for IMPORTED operations.

``publish_operation`` creates or updates:
  1. An ``IntegrationAction`` (kind=IMPORTED, status=PUBLISHED)
  2. An ``IntegrationActionVersion`` with LLM-only input schema + full execution config
  3. A ``Tool`` row (type=DYNAMIC_OPERATION) linked to that action

``unpublish_operation`` disables the action and deactivates the Tool row.

All tool names are namespaced by connection slug to prevent collisions when
multiple connections of the same integration type exist on one account.
"""

import json
import re
import uuid
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from botelier.models.integration import (
    AccountIntegration,
    IntegrationAction,
    IntegrationActionKind,
    IntegrationActionStatus,
    IntegrationActionVersion,
    IntegrationType,
)
from botelier.models.operation_policy import ConnectionOperationPolicy
from botelier.models.tool import Tool, ToolType
from botelier.utils import sanitize_function_name


def _build_llm_input_schema(
    variables: list[dict],
    param_ownership: Optional[dict] = None,
) -> dict:
    """Build the OpenAI function-calling input_schema from LLM-owned variables.

    Only variables with ownership ``llm`` (or unset) are included in the
    schema exposed to the model.  connection/secret/fixed/derived params are
    stripped entirely so the LLM cannot observe or influence them.
    """
    param_ownership = param_ownership or {}
    properties: dict = {}
    required: list[str] = []

    for var in variables or []:
        name = var.get("name", "")
        ownership = param_ownership.get(name) or var.get("ownership", "llm")
        if ownership != "llm":
            continue

        prop: dict = {
            "type": var.get("type", "string"),
        }
        desc = var.get("description") or ""
        if desc:
            prop["description"] = desc
        if var.get("enum"):
            prop["enum"] = var["enum"]
        properties[name] = prop

        if var.get("required") and ownership == "llm":
            required.append(name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def normalize_request_overrides(raw: Optional[dict]) -> dict:
    """Normalize per-operation request overrides to one canonical shape.

    Single source of truth for the request settings an operator may customize
    per operation: ``headers``, ``content_type`` (merged into headers),
    ``body_template`` (``body`` accepted as alias), ``timeout`` (1–30s), and
    ``retry_count`` (0–3). The SAME function feeds the policy PATCH,
    ``test_operation``, and ``_build_execution_config`` — so the request shape
    a test exercises and the shape the published tool executes cannot diverge.

    Raises ValueError on malformed input (the API layer surfaces it as 400).
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("request_overrides must be an object")

    normalized: dict = {}

    headers = raw.get("headers") or {}
    if not isinstance(headers, dict):
        raise ValueError("request_overrides.headers must be an object")
    headers = {str(k): str(v) for k, v in headers.items() if k}

    content_type = str(raw.get("content_type") or "").strip()
    if content_type and not any(k.lower() == "content-type" for k in headers):
        headers["Content-Type"] = content_type
    if headers:
        normalized["headers"] = headers

    body_template = raw.get("body_template", raw.get("body"))
    if body_template is not None:
        if not isinstance(body_template, str):
            body_template = json.dumps(body_template)
        normalized["body_template"] = body_template

    for key, lo, hi in (("timeout", 1, 30), ("retry_count", 0, 3)):
        value = raw.get(key)
        if value is None:
            continue
        try:
            normalized[key] = min(max(int(value), lo), hi)
        except (TypeError, ValueError):
            raise ValueError(f"request_overrides.{key} must be an integer")

    return normalized


def build_operation_api_config(
    exec_config: dict,
    *,
    fallback_integration_id: str = "",
    fallback_endpoint_id: str = "",
):
    """Build the runtime ``IntegrationAPIConfig`` from a published version config.

    Shared by EVERY dispatcher of DYNAMIC_OPERATION tools (voice, SMS,
    simulator) and by ``test_operation`` — one builder means all channels and
    the tester execute the exact same request shape, including any persisted
    ``request_overrides``.
    """
    from botelier.services.integration_runtime.types import (
        IntegrationAPIConfig,
        ResponseVariable,
    )

    mapping = exec_config.get("response_mapping") or {}
    response_variables = [
        ResponseVariable(variable_key=str(k), json_path=str(v))
        for k, v in mapping.items()
        if k and v
    ]

    overrides = normalize_request_overrides(exec_config.get("request_overrides"))
    optional: dict = {}
    if overrides.get("headers"):
        optional["headers"] = overrides["headers"]
    if overrides.get("body_template") is not None:
        optional["body_template"] = overrides["body_template"]
    if overrides.get("timeout") is not None:
        optional["timeout"] = overrides["timeout"]
    if overrides.get("retry_count") is not None:
        optional["retry_count"] = overrides["retry_count"]

    return IntegrationAPIConfig(
        integration_id=exec_config.get("integration_id") or fallback_integration_id,
        method=exec_config.get("method", "GET"),
        path=exec_config.get("path", "/"),
        endpoint_id=exec_config.get("endpoint_id") or fallback_endpoint_id,
        query_param_overrides={},
        response_variables=response_variables,
        **optional,
    )


def _build_execution_config(
    endpoint: dict,
    connection: AccountIntegration,
    integration_type: IntegrationType,
    param_ownership: dict,
    policy: Optional[ConnectionOperationPolicy],
) -> dict:
    """Build the full execution config stored in IntegrationActionVersion.config.

    This config is passed to ActionExecutor (via IntegrationAPIConfig) at
    runtime.  It contains the integration_id, method, path, and the full param
    routing map — which variables come from the LLM vs connection config vs
    credentials.  This is the runtime truth; the LLM-only input_schema is the
    visibility boundary.
    """
    variables = endpoint.get("variables") or []
    connection_params: dict = {}
    fixed_params: dict = {}

    for var in variables:
        name = var.get("name", "")
        ownership = param_ownership.get(name) or var.get("ownership", "llm")
        if ownership == "connection":
            # Value resolved from connection_config at execution time
            connection_params[name] = f"{{{{connection.{name}}}}}"
        elif ownership == "fixed":
            # Constant baked in here
            fixed_params[name] = var.get("default", "")

    return {
        "integration_id": str(connection.id),
        "integration_type_id": str(connection.integration_type_id),
        "method": endpoint.get("method", "GET"),
        "path": endpoint.get("path", ""),
        "endpoint_id": endpoint.get("id"),
        "connection_params": connection_params,
        "fixed_params": fixed_params,
        "variables": variables,
        "risk_level": endpoint.get("risk_level", "read"),
        "response_policy": (policy.to_dict() if policy else {}),
        "response_mapping": (policy.response_mapping or {}) if policy else {},
        # Persisted request-shape settings (headers/body/timeout/retries) —
        # the same values test_operation exercises. Normalized here so the
        # stored config is canonical regardless of how the policy row was set.
        "request_overrides": normalize_request_overrides(
            policy.request_overrides if policy else None
        ),
    }


def _derive_tool_name(
    fn_name: str,
    connection: AccountIntegration,
    integration_type: IntegrationType,
) -> str:
    """Derive a unique, collision-safe tool slug.

    Namespaced as ``{connection_slug}_{fn_name}`` where connection_slug is
    derived from the connection_name (or integration type slug).  This prevents
    two different connections on the same account from clobbering each other's
    tool names.
    """
    conn_name = (connection.connection_name or integration_type.slug or "api")
    safe_conn = re.sub(r"[^a-zA-Z0-9]", "_", conn_name.lower()).strip("_")[:20]
    combined = f"{safe_conn}_{fn_name}"
    # Sanitize AFTER truncation so the stored tool name is a fixed point of
    # sanitize_function_name — a bare [:60] can leave a trailing underscore
    # that channel-side re-sanitization would strip, silently diverging the
    # published name from the schema name the LLM calls.
    return sanitize_function_name(sanitize_function_name(combined)[:60])


def publish_operation(
    db: Session,
    account_id: str,
    connection_id: str,
    operation_id: str,
    tool_set_id: Optional[str] = None,
) -> Tool:
    """Publish an operation as a DYNAMIC_OPERATION tool.

    Creates or updates:
    - ``IntegrationAction`` (kind=IMPORTED, status=PUBLISHED)
    - ``IntegrationActionVersion`` (input_schema, config)
    - ``Tool`` (type=DYNAMIC_OPERATION, config={integration_action_id, connection_id})

    Args:
        db:           SQLAlchemy session.
        account_id:   Owner account UUID string.
        connection_id: AccountIntegration UUID string.
        operation_id: Endpoint ID string from endpoints_config (e.g. ``"GET_listRooms"``).
        tool_set_id:  Optional UUID to assign the Tool to; if None, tool is not
                      yet assigned to any tool set.

    Returns:
        The created or updated ``Tool`` row.

    Raises:
        ValueError: if the connection or endpoint cannot be found.
    """
    connection = (
        db.query(AccountIntegration)
        .filter(
            AccountIntegration.id == connection_id,
            AccountIntegration.account_id == account_id,
        )
        .first()
    )
    if not connection:
        raise ValueError(f"Connection {connection_id!r} not found for account {account_id!r}")

    integration_type = db.query(IntegrationType).filter(
        IntegrationType.id == connection.integration_type_id
    ).first()
    if not integration_type:
        raise ValueError(f"IntegrationType not found for connection {connection_id!r}")

    endpoints = integration_type.get_endpoints()
    endpoint = next((e for e in endpoints if e.get("id") == operation_id), None)
    if not endpoint:
        raise ValueError(f"Endpoint {operation_id!r} not found in integration type {integration_type.slug!r}")

    policy = (
        db.query(ConnectionOperationPolicy)
        .filter(
            ConnectionOperationPolicy.account_integration_id == connection_id,
            ConnectionOperationPolicy.operation_id == operation_id,
        )
        .first()
    )

    # Resolve param_ownership: policy/action-level overrides endpoint defaults
    param_ownership: dict = {}
    for var in endpoint.get("variables") or []:
        name = var.get("name", "")
        param_ownership[name] = var.get("ownership", "llm")

    # Apply per-connection-policy overrides (e.g. operator forces a param to
    # "connection" or "fixed" so the LLM never sees or controls it).
    if policy and policy.param_ownership_overrides:
        param_ownership.update(policy.param_ownership_overrides)

    fn_name = endpoint.get("name") or sanitize_function_name(operation_id)
    tool_slug = _derive_tool_name(fn_name, connection, integration_type)
    description = (endpoint.get("description") or endpoint.get("summary") or fn_name)[:500]

    # Upsert IntegrationAction keyed on (account_id, connection_id, source_endpoint_id)
    action = (
        db.query(IntegrationAction)
        .filter(
            IntegrationAction.account_id == account_id,
            IntegrationAction.connection_id == connection_id,
            IntegrationAction.source_endpoint_id == operation_id,
        )
        .first()
    )
    if not action:
        action = IntegrationAction(id=uuid.uuid4())
        db.add(action)

    action.account_id = account_id
    action.integration_type_id = connection.integration_type_id
    action.connection_id = connection_id
    action.source_endpoint_id = operation_id
    action.name = fn_name[:255]
    action.description = description
    action.slug = tool_slug
    action.kind = IntegrationActionKind.IMPORTED
    action.status = IntegrationActionStatus.PUBLISHED
    action.param_ownership = param_ownership
    action.response_policy = (policy.to_dict() if policy else None)

    # Build version
    input_schema = _build_llm_input_schema(endpoint.get("variables") or [], param_ownership)
    execution_config = _build_execution_config(endpoint, connection, integration_type, param_ownership, policy)

    existing_versions = list(getattr(action, "versions", []))
    version_number = max((v.version_number for v in existing_versions), default=0) + 1

    version = IntegrationActionVersion(id=uuid.uuid4())
    db.add(version)
    version.action_id = action.id
    version.version_number = version_number
    version.status = IntegrationActionStatus.PUBLISHED
    version.config = execution_config
    version.input_schema = input_schema
    version.output_schema = {}
    version.published_at = datetime.utcnow()

    db.flush()
    action.published_version_id = version.id

    # Upsert Tool row
    tool = (
        db.query(Tool)
        .filter(
            Tool.tool_type == ToolType.DYNAMIC_OPERATION.value,
            Tool.config["integration_action_id"].as_string() == str(action.id),
        )
        .first()
    )
    if not tool:
        tool = Tool(id=uuid.uuid4())
        db.add(tool)

    tool.name = tool_slug  # Namespaced slug prevents collision across connections
    tool.description = description
    tool.tool_type = ToolType.DYNAMIC_OPERATION.value
    tool.is_active = "true"
    tool.account_id = account_id
    if tool_set_id:
        tool.tool_set_id = tool_set_id
    tool.config = {
        "integration_action_id": str(action.id),
        "connection_id": str(connection_id),
        "operation_id": operation_id,
    }

    db.flush()

    logger.info(
        "publish_operation: published %s (action=%s, tool=%s) for account=%s connection=%s",
        operation_id,
        action.id,
        tool.id,
        account_id,
        connection_id,
    )
    return tool


def unpublish_operation(
    db: Session,
    account_id: str,
    connection_id: str,
    operation_id: str,
) -> None:
    """Disable a published DYNAMIC_OPERATION and deactivate its Tool row."""
    action = (
        db.query(IntegrationAction)
        .filter(
            IntegrationAction.account_id == account_id,
            IntegrationAction.connection_id == connection_id,
            IntegrationAction.source_endpoint_id == operation_id,
        )
        .first()
    )
    if not action:
        return

    action.status = IntegrationActionStatus.DISABLED

    tool = (
        db.query(Tool)
        .filter(
            Tool.tool_type == ToolType.DYNAMIC_OPERATION.value,
            Tool.config["integration_action_id"].as_string() == str(action.id),
        )
        .first()
    )
    if tool:
        tool.is_active = "false"

    db.flush()
    logger.info(
        "unpublish_operation: disabled %s (action=%s) for account=%s connection=%s",
        operation_id,
        action.id,
        account_id,
        connection_id,
    )
