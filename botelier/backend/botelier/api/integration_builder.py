"""Integration Builder API — Universal API Adapter.

Endpoints for importing specs, managing the operation catalog, configuring
per-connection policies, testing operations, and publishing/unpublishing tools.

All endpoints require ``integrations.view`` or ``integrations.manage``
permissions (same permission model as the existing integrations router).

Route prefix: no explicit prefix — paths are explicit per endpoint so they
slot naturally alongside the existing ``/api/integrations/...`` routes.
"""

import base64
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy.orm import Session

from botelier.auth.middleware import check_account_permission, get_current_user
from botelier.database import get_db
from botelier.models.integration import (
    AccountIntegration,
    IntegrationAction,
    IntegrationActionKind,
    IntegrationActionStatus,
    IntegrationActionVersion,
    IntegrationType,
)
from botelier.models.operation_policy import (
    ApprovalRequest,
    ConnectionOperationPolicy,
    OperationTestStatus,
)
from botelier.models.tool import Tool, ToolType
from botelier.models.user import User
from botelier.services.action_executor import ActionContext, ActionExecutionRequest, ActionExecutor
from botelier.services.integration_client import IntegrationAPIConfig
from botelier.services.operation_publisher import publish_operation, unpublish_operation
from botelier.services.spec_importer import import_spec
from datetime import datetime

router = APIRouter()


# ---------------------------------------------------------------------------
# Spec import
# ---------------------------------------------------------------------------


@router.post("/api/integrations/import")
async def import_integration_spec(
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Import an OpenAPI / Swagger / Postman spec to create an IntegrationType.

    Body fields:
        account_id   (required)
        spec_type    — "openapi" | "swagger" | "postman"
        spec_file_b64 — base64-encoded spec JSON (mutually exclusive with spec_url)
        spec_url     — URL to fetch the spec from (mutually exclusive with spec_file_b64)
        base_url_override — override the server base URL extracted from the spec
    """
    account_id = body.get("account_id")
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id required")

    check_account_permission(user, account_id, "integrations.manage", db)

    spec_type = (body.get("spec_type") or "").lower().strip()
    if spec_type not in ("openapi", "swagger", "postman"):
        raise HTTPException(
            status_code=400,
            detail="spec_type must be 'openapi', 'swagger', or 'postman'",
        )

    spec_data: Optional[dict] = None
    spec_url: Optional[str] = body.get("spec_url")

    if body.get("spec_file_b64"):
        try:
            raw = base64.b64decode(body["spec_file_b64"])
            spec_data = json.loads(raw)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid spec_file_b64: {exc}")
    elif spec_url:
        _validate_spec_url(spec_url)
        import httpx

        try:
            async with httpx.AsyncClient(
                timeout=20.0,
                follow_redirects=False,  # Redirects bypass the SSRF hostname check
            ) as client:
                resp = await client.get(spec_url)
                if resp.is_redirect:
                    raise HTTPException(
                        status_code=400,
                        detail="spec_url returned a redirect; provide the direct URL",
                    )
                resp.raise_for_status()
                spec_data = resp.json()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to fetch spec from URL: {exc}")
    else:
        raise HTTPException(status_code=400, detail="Either spec_file_b64 or spec_url is required")

    try:
        integration_type = import_spec(
            db=db,
            spec_data=spec_data,
            source_type=spec_type,
            account_id=account_id,
            base_url_override=body.get("base_url_override"),
            spec_url=spec_url,
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        db.rollback()
        logger.exception("import_integration_spec failed: %s", exc)
        raise HTTPException(status_code=500, detail="Import failed")

    endpoints = integration_type.get_endpoints()
    return {
        "id": str(integration_type.id),
        "slug": integration_type.slug,
        "name": integration_type.name,
        "source_type": integration_type.source_type,
        "spec_version": integration_type.spec_version,
        "endpoint_count": len(endpoints),
        "was_truncated": (integration_type.raw_spec or {}).get("was_truncated", False),
    }


# ---------------------------------------------------------------------------
# Operation catalog
# ---------------------------------------------------------------------------


@router.get("/api/integrations/account/{account_id}/connection/{connection_id}/operations")
def list_operations(
    account_id: str,
    connection_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all operations for a connection with per-connection policy overlay."""
    check_account_permission(user, account_id, "integrations.view", db)

    connection = _get_connection(db, account_id, connection_id)
    integration_type = db.query(IntegrationType).filter(
        IntegrationType.id == connection.integration_type_id
    ).first()
    if not integration_type:
        raise HTTPException(status_code=404, detail="Integration type not found")

    endpoints = integration_type.get_endpoints()

    # Load all policies for this connection in one query
    policies: dict[str, ConnectionOperationPolicy] = {
        p.operation_id: p
        for p in db.query(ConnectionOperationPolicy).filter(
            ConnectionOperationPolicy.account_integration_id == connection_id
        ).all()
    }

    # Load published actions to know which are published
    published_actions: dict[str, IntegrationAction] = {
        a.source_endpoint_id: a
        for a in db.query(IntegrationAction).filter(
            IntegrationAction.account_id == account_id,
            IntegrationAction.connection_id == connection_id,
            IntegrationAction.kind == IntegrationActionKind.IMPORTED,
        ).all()
    }

    results = []
    for ep in endpoints:
        op_id = ep.get("id", "")
        policy = policies.get(op_id)
        action = published_actions.get(op_id)
        results.append({
            **ep,
            "policy": policy.to_dict() if policy else None,
            "is_published": (
                action is not None
                and action.status == IntegrationActionStatus.PUBLISHED
            ),
            "action_id": str(action.id) if action else None,
        })

    return {"operations": results, "total": len(results)}


@router.put("/api/integrations/account/{account_id}/connection/{connection_id}/operations/{operation_id}/policy")
def update_operation_policy(
    account_id: str,
    connection_id: str,
    operation_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create or update the ConnectionOperationPolicy for one operation."""
    check_account_permission(user, account_id, "integrations.manage", db)
    _get_connection(db, account_id, connection_id)
    _verify_operation_exists(db, connection_id, operation_id)

    policy = (
        db.query(ConnectionOperationPolicy)
        .filter(
            ConnectionOperationPolicy.account_integration_id == connection_id,
            ConnectionOperationPolicy.operation_id == operation_id,
        )
        .first()
    )
    if not policy:
        import uuid
        policy = ConnectionOperationPolicy(
            id=uuid.uuid4(),
            account_integration_id=connection_id,
            operation_id=operation_id,
        )
        db.add(policy)

    _ALLOWED_POLICY_FIELDS = {
        "enabled",
        "risk_level",
        "confirm_required",
        "approval_required",
        "max_amount",
        "max_executions_per_conv",
        "allowed_channels",
        "response_size_bytes",
        "redact_field_patterns",
    }
    for field, value in body.items():
        if field in _ALLOWED_POLICY_FIELDS:
            setattr(policy, field, value)

    policy.updated_at = datetime.utcnow()
    db.commit()
    return policy.to_dict()


# ---------------------------------------------------------------------------
# Test operation
# ---------------------------------------------------------------------------


@router.post("/api/integrations/account/{account_id}/connection/{connection_id}/operations/{operation_id}/test")
async def test_operation(
    account_id: str,
    connection_id: str,
    operation_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Test one operation through the certified execution runtime.

    Persists the result to the ConnectionOperationPolicy row.
    """
    check_account_permission(user, account_id, "integrations.manage", db)
    connection = _get_connection(db, account_id, connection_id)
    endpoint = _get_endpoint(db, connection, operation_id)

    # Upsert policy row
    policy = _get_or_create_policy(db, connection_id, operation_id)

    # Build IntegrationAPIConfig for the certified runtime path
    config = IntegrationAPIConfig(
        integration_id=connection_id,
        method=endpoint.get("method", "GET"),
        path=endpoint.get("path", "/"),
        endpoint_id=operation_id,
        query_param_overrides=body.get("query_params") or {},
    )

    context = ActionContext(
        account_id=account_id,
        channel="test",
    )

    request = ActionExecutionRequest(
        context=context,
        variables=body.get("variables") or {},
        integration_config=config,
    )

    executor = ActionExecutor(db)
    result = await executor.execute_and_log(request)

    # Persist test result
    policy.test_status = OperationTestStatus.PASSED.value if result.success else OperationTestStatus.FAILED.value
    policy.tested_at = datetime.utcnow()
    policy.test_passed = result.success
    policy.test_error = result.error_message if not result.success else None
    policy.updated_at = datetime.utcnow()
    db.commit()

    return {
        "success": result.success,
        "status_code": result.status_code,
        "data": result.data,
        "error_type": result.error_type.value if result.error_type else None,
        "error_message": result.error_message,
        "latency_ms": result.latency_ms,
        "warnings": result.warnings,
        "test_status": policy.test_status,
    }


# ---------------------------------------------------------------------------
# Publish / unpublish
# ---------------------------------------------------------------------------


@router.post("/api/integrations/account/{account_id}/connection/{connection_id}/operations/{operation_id}/publish")
def publish_op(
    account_id: str,
    connection_id: str,
    operation_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Publish an operation: creates IntegrationAction + Tool(DYNAMIC_OPERATION)."""
    check_account_permission(user, account_id, "integrations.manage", db)
    _get_connection(db, account_id, connection_id)
    _verify_operation_exists(db, connection_id, operation_id)

    try:
        tool = publish_operation(
            db=db,
            account_id=account_id,
            connection_id=connection_id,
            operation_id=operation_id,
            tool_set_id=body.get("tool_set_id"),
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        db.rollback()
        logger.exception("publish_op failed: %s", exc)
        raise HTTPException(status_code=500, detail="Publish failed")

    return {
        "tool_id": str(tool.id),
        "tool_name": tool.name,
        "tool_type": tool.tool_type,
        "is_active": tool.is_active == "true",
        "config": tool.config,
    }


@router.post("/api/integrations/account/{account_id}/connection/{connection_id}/operations/{operation_id}/unpublish")
def unpublish_op(
    account_id: str,
    connection_id: str,
    operation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disable a published operation and deactivate its Tool row."""
    check_account_permission(user, account_id, "integrations.manage", db)
    _get_connection(db, account_id, connection_id)

    try:
        unpublish_operation(
            db=db,
            account_id=account_id,
            connection_id=connection_id,
            operation_id=operation_id,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("unpublish_op failed: %s", exc)
        raise HTTPException(status_code=500, detail="Unpublish failed")

    return {"status": "disabled"}


# ---------------------------------------------------------------------------
# Tool preview + published tools list
# ---------------------------------------------------------------------------


@router.get("/api/integrations/account/{account_id}/connection/{connection_id}/operations/{operation_id}/tool-preview")
def tool_preview(
    account_id: str,
    connection_id: str,
    operation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Preview the LLM tool schema that would be generated if this operation were published."""
    check_account_permission(user, account_id, "integrations.view", db)
    connection = _get_connection(db, account_id, connection_id)
    endpoint = _get_endpoint(db, connection, operation_id)

    from botelier.services.operation_publisher import _build_llm_input_schema
    from botelier.utils import sanitize_function_name

    variables = endpoint.get("variables") or []
    param_ownership = {v["name"]: v.get("ownership", "llm") for v in variables}
    input_schema = _build_llm_input_schema(variables, param_ownership)

    fn_name = endpoint.get("name") or sanitize_function_name(operation_id)
    description = (endpoint.get("description") or endpoint.get("summary") or fn_name)[:500]

    return {
        "type": "function",
        "function": {
            "name": fn_name,
            "description": description,
            "parameters": input_schema,
        },
    }


@router.get("/api/integrations/account/{account_id}/connection/{connection_id}/tools")
def list_published_tools(
    account_id: str,
    connection_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all published DYNAMIC_OPERATION tools for a connection."""
    check_account_permission(user, account_id, "integrations.view", db)
    _get_connection(db, account_id, connection_id)

    actions = (
        db.query(IntegrationAction)
        .filter(
            IntegrationAction.account_id == account_id,
            IntegrationAction.connection_id == connection_id,
            IntegrationAction.kind == IntegrationActionKind.IMPORTED,
            IntegrationAction.status == IntegrationActionStatus.PUBLISHED,
        )
        .all()
    )

    results = []
    for action in actions:
        tool = (
            db.query(Tool)
            .filter(
                Tool.tool_type == ToolType.DYNAMIC_OPERATION.value,
                Tool.config["integration_action_id"].astext == str(action.id),
            )
            .first()
        )
        results.append({
            **action.to_dict(include_config=True),
            "tool_id": str(tool.id) if tool else None,
            "tool_is_active": (tool.is_active == "true") if tool else False,
        })

    return {"tools": results, "total": len(results)}


@router.get("/api/integrations/types/importable")
def list_importable_types(
    account_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List IntegrationTypes with origin=customer_imported for a specific account."""
    check_account_permission(user, account_id, "integrations.view", db)
    results = (
        db.query(IntegrationType)
        .filter(
            IntegrationType.origin == "customer_imported",
            IntegrationType.created_by_account_id == account_id,
        )
        .all()
    )
    return {
        "integration_types": [
            {
                "id": str(it.id),
                "slug": it.slug,
                "name": it.name,
                "source_type": it.source_type,
                "spec_version": it.spec_version,
                "endpoint_count": len(it.get_endpoints()),
                "origin": it.origin,
            }
            for it in results
        ]
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_spec_url(url: str) -> None:
    """Raise HTTPException if spec_url is unsafe (SSRF guard).

    Allows only http/https to public hostnames.  Blocks:
      - Non-http(s) schemes
      - Localhost / loopback (127.x, ::1)
      - RFC-1918 private ranges (10.x, 172.16-31.x, 192.168.x)
      - Link-local (169.254.x)
      - Metadata endpoints (169.254.169.254)
    """
    import ipaddress
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid spec_url")

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="spec_url must use http or https")

    hostname = (parsed.hostname or "").lower().strip()
    if not hostname:
        raise HTTPException(status_code=400, detail="spec_url missing hostname")

    # Block obvious internal names
    blocked_names = {"localhost", "localhost.localdomain", "metadata.google.internal"}
    if hostname in blocked_names:
        raise HTTPException(status_code=400, detail="spec_url hostname is not allowed")

    # Block private/loopback IP ranges by literal IP address
    try:
        addr = ipaddress.ip_address(hostname)
        if (
            addr.is_loopback
            or addr.is_private
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            raise HTTPException(status_code=400, detail="spec_url hostname is not allowed")
    except ValueError:
        pass  # Not a literal IP — DNS hostname; resolve and check below

    # DNS-rebinding protection: resolve the hostname NOW and validate every resolved
    # IP before the fetch.  A hostname like evil.example.com could resolve to
    # 192.168.1.1 even though the literal hostname passed the string check above.
    import socket

    try:
        addr_infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError:
        raise HTTPException(status_code=400, detail="spec_url hostname could not be resolved")

    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        resolved_ip = sockaddr[0]
        try:
            resolved_addr = ipaddress.ip_address(resolved_ip)
        except ValueError:
            continue
        if (
            resolved_addr.is_loopback
            or resolved_addr.is_private
            or resolved_addr.is_link_local
            or resolved_addr.is_reserved
            or resolved_addr.is_multicast
            or resolved_addr.is_unspecified
        ):
            raise HTTPException(
                status_code=400,
                detail="spec_url resolves to a disallowed address",
            )


def _get_connection(db: Session, account_id: str, connection_id: str) -> AccountIntegration:
    conn = (
        db.query(AccountIntegration)
        .filter(
            AccountIntegration.id == connection_id,
            AccountIntegration.account_id == account_id,
        )
        .first()
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


def _get_endpoint(db: Session, connection: AccountIntegration, operation_id: str) -> dict:
    it = db.query(IntegrationType).filter(IntegrationType.id == connection.integration_type_id).first()
    if not it:
        raise HTTPException(status_code=404, detail="Integration type not found")
    endpoint = next((e for e in it.get_endpoints() if e.get("id") == operation_id), None)
    if not endpoint:
        raise HTTPException(status_code=404, detail=f"Operation {operation_id!r} not found")
    return endpoint


def _verify_operation_exists(db: Session, connection_id: str, operation_id: str) -> None:
    conn = db.query(AccountIntegration).filter(AccountIntegration.id == connection_id).first()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    it = db.query(IntegrationType).filter(IntegrationType.id == conn.integration_type_id).first()
    if not it:
        raise HTTPException(status_code=404, detail="Integration type not found")
    if not any(e.get("id") == operation_id for e in it.get_endpoints()):
        raise HTTPException(status_code=404, detail=f"Operation {operation_id!r} not found")


def _get_or_create_policy(
    db: Session,
    connection_id: str,
    operation_id: str,
) -> ConnectionOperationPolicy:
    import uuid
    policy = (
        db.query(ConnectionOperationPolicy)
        .filter(
            ConnectionOperationPolicy.account_integration_id == connection_id,
            ConnectionOperationPolicy.operation_id == operation_id,
        )
        .first()
    )
    if not policy:
        policy = ConnectionOperationPolicy(
            id=uuid.uuid4(),
            account_integration_id=connection_id,
            operation_id=operation_id,
        )
        db.add(policy)
    return policy
