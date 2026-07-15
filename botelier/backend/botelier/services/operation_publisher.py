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
    return sanitize_function_name(combined)[:60]


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
            Tool.config["integration_action_id"].astext == str(action.id),
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
            Tool.config["integration_action_id"].astext == str(action.id),
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
