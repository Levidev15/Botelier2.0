"""Unified Action Executor.

Runs custom HTTP actions, legacy API_REQUEST tools, and certified integration
endpoint calls behind one guarded runtime contract.
"""

import asyncio
import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import httpx
from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from botelier.models.integration import (
    AccountSecret,
    IntegrationAction,
    IntegrationActionInvocation,
    IntegrationActionStatus,
    IntegrationActionVersion,
    IntegrationCallLog,
)
from botelier.services.integration_client import (
    APIErrorType,
    APIResponse,
    IntegrationAPIConfig,
    IntegrationClient,
    ResponseVariable,
    _sanitize_endpoint_for_log,
)
from botelier.services.ssrf_safe_transport import SSRFSafeTransport

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")
_SECRET_RE = re.compile(r"\{\{secrets\.(\w+)\}\}")
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


@dataclass
class ActionContext:
    account_id: str
    channel: str = "api"
    call_sid: Optional[str] = None
    call_log_id: Optional[str] = None
    tool_id: Optional[str] = None
    flow_version_id: Optional[str] = None
    flow_tool_id: Optional[str] = None
    node_id: Optional[str] = None
    source_label: Optional[str] = None
    # Per-property isolation (Task #327). Resolved once at contact start and
    # carried through the session; scopes integration resolution to
    # (account_id, property_id). None = legacy / account-only scoping.
    property_id: Optional[str] = None


@dataclass
class ActionExecutionRequest:
    context: ActionContext
    variables: dict[str, Any] = field(default_factory=dict)
    action_id: Optional[str] = None
    action_version_id: Optional[str] = None
    legacy_config: Optional[dict[str, Any]] = None
    integration_config: Optional[IntegrationAPIConfig] = None
    test_config: Optional[dict[str, Any]] = None
    # Cross-session idempotency (Task #330). When set, ``execute_and_log`` runs
    # the operation through the durable ledger so a reconnect/retry with the same
    # key returns the stored result instead of firing the write twice. Callers
    # set this only for mutating operations (the resolver keys it off
    # ``CapabilitySpec.mutating``); reads leave it None so they stay fresh.
    idempotency_key: Optional[str] = None
    operation: Optional[str] = None
    args_hash: Optional[str] = None
    # Universal Adapter — response bounding + redaction policy forwarded from
    # ConnectionOperationPolicy or IntegrationAction.response_policy.
    response_policy: Optional[dict[str, Any]] = None


@dataclass
class ActionExecutionResult:
    success: bool
    status_code: int
    data: Any = None
    error_type: APIErrorType = APIErrorType.UNKNOWN
    error_message: Optional[str] = None
    extracted_variables: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    latency_ms: int = 0
    # Vendor-agnostic canonical envelope surfaced from the integration runtime.
    # None for legacy/custom actions and un-tagged endpoints. Additive.
    canonical: Optional[dict] = None
    # Human-readable warnings from Universal Adapter response bounding/redaction.
    # Non-empty only for IMPORTED-kind operations; certified adapters never set this.
    warnings: list[str] = field(default_factory=list)


class ActionExecutor:
    """Execute reusable and legacy API actions with consistent logging."""

    def __init__(self, db: Session):
        self.db = db

    async def execute(self, request: ActionExecutionRequest) -> ActionExecutionResult:
        request_id = uuid.uuid4().hex
        start_ms = int(time.time() * 1000)
        action = None
        version = None
        integration_id = None
        method = None
        endpoint = None

        try:
            if request.integration_config:
                config = request.integration_config
                integration_id = config.integration_id
                method = config.method.upper()
                endpoint = config.endpoint_template or config.path
                response = await self._execute_integration(request, config)
                result = self._from_api_response(response, request_id, start_ms)
                return result

            config = request.test_config
            if request.action_id:
                action, version = self._load_action_version(
                    request.context.account_id,
                    request.action_id,
                    request.action_version_id,
                )
                if not action or not version:
                    return self._error(
                        request_id,
                        start_ms,
                        APIErrorType.NOT_FOUND,
                        "Action not found",
                    )
                if (
                    action.status != IntegrationActionStatus.PUBLISHED
                    and version.status != IntegrationActionStatus.DRAFT
                ):
                    return self._error(
                        request_id,
                        start_ms,
                        APIErrorType.AUTH_ERROR,
                        "Action is not published",
                    )
                config = version.config

            if request.legacy_config:
                config = request.legacy_config

            if not config:
                return self._error(
                    request_id,
                    start_ms,
                    APIErrorType.VALIDATION_ERROR,
                    "Missing action configuration",
                )

            method = str(config.get("method", "GET")).upper()
            endpoint = config.get("url") or config.get("path")
            result = await self._execute_custom_http(
                config=config,
                variables=request.variables,
                context=request.context,
                request_id=request_id,
                start_ms=start_ms,
            )
            return result
        finally:
            # Success/error logging is handled after the result is known below.
            pass

    async def execute_and_log(self, request: ActionExecutionRequest) -> ActionExecutionResult:
        action = None
        version = None
        if request.action_id:
            action, version = self._load_action_version(
                request.context.account_id,
                request.action_id,
                request.action_version_id,
            )
        config = request.legacy_config or request.test_config or (version.config if version else {})
        if request.integration_config:
            method = request.integration_config.method
            endpoint = request.integration_config.endpoint_template or request.integration_config.path
            integration_id = request.integration_config.integration_id
        else:
            method = str(config.get("method", "GET")).upper() if config else None
            endpoint = (config or {}).get("url") or (config or {}).get("path")
            integration_id = (config or {}).get("integration_id")

        # Task #330 — durable cross-session dedup for mutating operations. The
        # in-memory flow guard only covers a single worker; this makes a booking
        # or charge fire at most once even after a websocket dropout + reconnect
        # on a fresh worker. Reads (GET / non-mutating capabilities) never get a
        # key and always run fresh.
        idem_key, operation, args_hash = self._resolve_idempotency(request, method)
        if idem_key:
            result = await self._execute_with_idempotency(
                request, idem_key, operation, args_hash
            )
        else:
            result = await self.execute(request)

        self._write_logs(
            request=request,
            result=result,
            action=action,
            version=version,
            integration_id=integration_id,
            method=method,
            endpoint=endpoint,
        )
        return result

    def _resolve_idempotency(
        self, request: ActionExecutionRequest, method: Optional[str]
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Decide whether this operation is guarded and under what key.

        Precedence:
        1. An explicit ``request.idempotency_key`` (set by the capability
           resolver for mutating capabilities — it knows ``spec.mutating`` and
           the canonical args).
        2. Otherwise, auto-derive a stable key for a mutating *flow node* from
           ``call_sid + flow_tool_id + node_id``. That triple is invariant across
           a reconnect (flow_sessions is keyed the same way), so the retried node
           dedups. GETs and simulator/testing runs (no call_sid) are unguarded.
        """
        if request.idempotency_key:
            return (
                request.idempotency_key,
                request.operation or "operation",
                request.args_hash,
            )

        ctx = request.context
        if (
            method
            and method.upper() not in _SAFE_METHODS
            and ctx.call_sid
            and ctx.node_id
            and ctx.flow_tool_id
        ):
            raw = f"flow:{ctx.call_sid}:{ctx.flow_tool_id}:{ctx.node_id}"
            key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            args_hash = hashlib.sha256(
                json.dumps(request.variables or {}, sort_keys=True, default=str).encode(
                    "utf-8"
                )
            ).hexdigest()
            return key, f"flow_node:{ctx.node_id}", args_hash

        return None, None, None

    async def _execute_with_idempotency(
        self,
        request: ActionExecutionRequest,
        key: str,
        operation: Optional[str],
        args_hash: Optional[str],
    ) -> ActionExecutionResult:
        from botelier.services.idempotency import (
            IN_PROGRESS,
            RETURN_STORED,
            IdempotencyLedger,
        )

        ledger = IdempotencyLedger()
        request_id = uuid.uuid4().hex
        start_ms = int(time.time() * 1000)
        try:
            claim = ledger.claim(
                key,
                request.context.account_id,
                request.context.property_id,
                operation,
                args_hash,
            )
        except Exception as exc:  # noqa: BLE001 - ledger must fail closed
            # A ledger outage must not silently drop to an unguarded double-write
            # for a booking/charge. Fail closed: refuse rather than risk a dup.
            logger.error(f"Idempotency claim failed for {operation} — refusing: {exc}")
            return self._error(
                request_id,
                start_ms,
                APIErrorType.UNKNOWN,
                "This request could not be safely processed. Please try again.",
            )

        if claim.outcome == RETURN_STORED:
            stored = self._deserialize_result(claim.stored_result)
            if stored is not None:
                logger.info(f"Idempotent replay ({operation}) — returning stored result")
                return stored
            # Row said succeeded but the payload was unreadable — treat as an
            # in-progress/ambiguous state and refuse rather than re-fire.
            return self._error(
                request_id,
                start_ms,
                APIErrorType.UNKNOWN,
                "This request was already processed.",
            )

        if claim.outcome == IN_PROGRESS:
            logger.info(f"Idempotent duplicate ({operation}) — already in progress")
            return self._error(
                request_id,
                start_ms,
                APIErrorType.UNKNOWN,
                "This request is already being processed.",
            )

        # We own the key: execute exactly once, then record the outcome.
        try:
            result = await self.execute(request)
        except Exception:
            ledger.fail(key)
            raise

        if result.success:
            ledger.complete(key, self._serialize_result(result))
        else:
            ledger.fail(key)
        return result

    @staticmethod
    def _serialize_result(result: ActionExecutionResult) -> dict[str, Any]:
        return {
            "success": result.success,
            "status_code": result.status_code,
            "data": result.data,
            "error_type": result.error_type.value if result.error_type else None,
            "error_message": result.error_message,
            "extracted_variables": result.extracted_variables,
            "canonical": result.canonical,
            "latency_ms": result.latency_ms,
        }

    @staticmethod
    def _deserialize_result(
        data: Optional[dict[str, Any]],
    ) -> Optional[ActionExecutionResult]:
        if not data:
            return None
        error_type_value = data.get("error_type")
        try:
            error_type = (
                APIErrorType(error_type_value)
                if error_type_value
                else APIErrorType.SUCCESS
            )
        except ValueError:
            error_type = APIErrorType.UNKNOWN
        return ActionExecutionResult(
            success=bool(data.get("success")),
            status_code=int(data.get("status_code") or 0),
            data=data.get("data"),
            error_type=error_type,
            error_message=data.get("error_message"),
            extracted_variables=data.get("extracted_variables") or {},
            request_id=uuid.uuid4().hex,
            latency_ms=int(data.get("latency_ms") or 0),
            canonical=data.get("canonical"),
        )

    async def _execute_integration(
        self, request: ActionExecutionRequest, config: IntegrationAPIConfig
    ) -> APIResponse:
        self._lock_integration_refresh(config.integration_id)
        client = IntegrationClient(
            request.context.account_id,
            db=self.db,
            property_id=request.context.property_id,
        )
        response = await client.execute_request(config, request.variables)

        # Apply response bounding + field-level redaction for IMPORTED (Universal
        # Adapter) operations.  The policy is forwarded by callers that load it from
        # ConnectionOperationPolicy or IntegrationAction.response_policy.  For
        # certified adapters (Opera, GuestCentric) request.response_policy is None,
        # so this block is a no-op for them.
        if request.response_policy is not None and response.data is not None:
            from botelier.services.integration_runtime.redaction import bound_and_redact_response

            # Normalize policy field names: ConnectionOperationPolicy.to_dict() uses
            # `response_size_bytes` + `redact_field_patterns`; bound_and_redact_response
            # expects `size_limit_bytes` + `redact_patterns`.  Support both shapes so
            # operator-configured policies are actually applied.
            raw_policy = request.response_policy
            normalized_policy = {
                "size_limit_bytes": (
                    raw_policy.get("size_limit_bytes") or raw_policy.get("response_size_bytes")
                ),
                "redact_patterns": (
                    raw_policy.get("redact_patterns") or raw_policy.get("redact_field_patterns")
                ),
                "strip_secret_keys": raw_policy.get("strip_secret_keys", True),
            }
            bounded_data, redact_warnings = bound_and_redact_response(response.data, normalized_policy)
            for w in redact_warnings:
                logger.warning(
                    "Response policy applied (integration=%s endpoint=%s): %s",
                    config.integration_id,
                    config.endpoint_id,
                    w,
                )
            response = APIResponse(
                success=response.success,
                status_code=response.status_code,
                data=bounded_data,
                error_type=response.error_type,
                error_message=response.error_message,
                extracted_variables=response.extracted_variables,
                canonical=getattr(response, "canonical", None),
                warnings=redact_warnings,
            )

        return response

    async def _execute_custom_http(
        self,
        config: dict[str, Any],
        variables: dict[str, Any],
        context: ActionContext,
        request_id: str,
        start_ms: int,
    ) -> ActionExecutionResult:
        method = str(config.get("method", "GET")).upper()
        if method not in _ALLOWED_METHODS:
            return self._error(
                request_id,
                start_ms,
                APIErrorType.VALIDATION_ERROR,
                f"Unsupported HTTP method: {method}",
            )

        timeout = min(int(config.get("timeout") or 5), 10 if context.channel in {"voice", "flow"} else 30)
        retry_count = int(config.get("retryCount", config.get("retry_count", 0)) or 0)
        if method not in _SAFE_METHODS:
            retry_count = 0

        try:
            url = self._render(config.get("url", ""), variables, context.account_id)
            headers = {
                k: self._render(str(v), variables, context.account_id)
                for k, v in (config.get("headers") or {}).items()
                if k
            }
            body = self._build_body(config, variables, context.account_id)

            last_error: Optional[Exception] = None
            for _attempt in range(retry_count + 1):
                try:
                    async with httpx.AsyncClient(
                        transport=SSRFSafeTransport(), timeout=timeout
                    ) as client:
                        response = await self._send(client, method, url, headers, body)
                    return self._process_http_response(
                        response,
                        config,
                        request_id,
                        start_ms,
                    )
                except httpx.TimeoutException as exc:
                    last_error = exc
                except httpx.NetworkError as exc:
                    last_error = exc

            error_type = (
                APIErrorType.TIMEOUT
                if isinstance(last_error, httpx.TimeoutException)
                else APIErrorType.NETWORK_ERROR
            )
            return self._error(
                request_id,
                start_ms,
                error_type,
                str(last_error) if last_error else "Request failed",
            )
        except Exception as exc:
            logger.warning(f"Action execution failed: {exc}")
            return self._error(request_id, start_ms, APIErrorType.UNKNOWN, str(exc))

    async def _send(self, client, method: str, url: str, headers: dict, body: Any):
        if method == "GET":
            return await client.get(url, headers=headers)
        if method == "POST":
            return await client.post(url, headers=headers, json=body)
        if method == "PUT":
            return await client.put(url, headers=headers, json=body)
        if method == "PATCH":
            return await client.patch(url, headers=headers, json=body)
        if method == "DELETE":
            return await client.delete(url, headers=headers)
        raise ValueError(f"Unsupported HTTP method: {method}")

    def _process_http_response(
        self,
        response: httpx.Response,
        config: dict[str, Any],
        request_id: str,
        start_ms: int,
    ) -> ActionExecutionResult:
        try:
            data = response.json()
        except json.JSONDecodeError:
            data = response.text
        status_code = response.status_code
        error_type = APIErrorType.SUCCESS
        error_message = None
        if status_code in (401, 403):
            error_type = APIErrorType.AUTH_ERROR
            error_message = config.get("onAuthError") or "Authentication failed"
        elif status_code == 404:
            error_type = APIErrorType.NOT_FOUND
            error_message = config.get("onNotFound") or "Not found"
        elif status_code in (400, 422):
            error_type = APIErrorType.VALIDATION_ERROR
            error_message = self._extract_error_message(data) or config.get("onError")
        elif status_code >= 500:
            error_type = APIErrorType.SERVER_ERROR
            error_message = config.get("onError") or "Upstream system failed"
        elif not 200 <= status_code < 300:
            error_type = APIErrorType.UNKNOWN
            error_message = config.get("onError") or "Request failed"

        mappings = (
            config.get("responseVariables")
            or config.get("response_mapping")
            or config.get("responseMapping")
            or {}
        )
        extracted = self._extract_mappings(data, mappings)
        return ActionExecutionResult(
            success=200 <= status_code < 300,
            status_code=status_code,
            data=data,
            error_type=error_type,
            error_message=error_message,
            extracted_variables=extracted,
            request_id=request_id,
            latency_ms=int(time.time() * 1000) - start_ms,
        )

    def _from_api_response(
        self, response: APIResponse, request_id: str, start_ms: int
    ) -> ActionExecutionResult:
        return ActionExecutionResult(
            success=response.success,
            status_code=response.status_code,
            data=response.data,
            error_type=response.error_type,
            error_message=response.error_message,
            extracted_variables=response.extracted_variables,
            request_id=request_id,
            latency_ms=int(time.time() * 1000) - start_ms,
            canonical=response.canonical,
            warnings=list(getattr(response, "warnings", None) or []),
        )

    def _build_body(self, config: dict[str, Any], variables: dict[str, Any], account_id: str):
        template = config.get("bodyTemplate") or config.get("body_template")
        if template:
            rendered = self._render(template, variables, account_id)
            return json.loads(rendered) if rendered else None
        return config.get("body")

    def _render(self, template: str, variables: dict[str, Any], account_id: str) -> str:
        if not template:
            return ""
        rendered = self._substitute_secrets(str(template), account_id)

        def replace_var(match):
            key = match.group(1)
            return str(variables.get(key, match.group(0)))

        return _VAR_RE.sub(replace_var, rendered)

    def _substitute_secrets(self, text_value: str, account_id: str) -> str:
        keys = set(_SECRET_RE.findall(text_value or ""))
        if not keys:
            return text_value
        secrets = (
            self.db.query(AccountSecret)
            .filter(AccountSecret.account_id == account_id, AccountSecret.key.in_(list(keys)))
            .all()
        )
        secret_map = {s.key: s.get_value() for s in secrets}

        def replace_secret(match):
            key = match.group(1)
            if key not in secret_map:
                logger.warning(f"Secret '{{secrets.{key}}}' not found for account {account_id}")
                return match.group(0)
            return secret_map[key]

        return _SECRET_RE.sub(replace_secret, text_value)

    def _extract_mappings(self, data: Any, mappings: Any) -> dict[str, Any]:
        if isinstance(mappings, list):
            iterable = [
                (
                    m.get("variableKey") or m.get("variable"),
                    m.get("jsonPath") or m.get("path"),
                )
                for m in mappings
            ]
        else:
            iterable = list((mappings or {}).items())
        extracted = {}
        for key, path in iterable:
            if not key or not path:
                continue
            value = self._extract_json_value(data, path)
            if value is not None:
                extracted[key] = value
        return extracted

    def _extract_json_value(self, data: Any, path: str) -> Any:
        if path.startswith("$."):
            path = path[2:]
        current = data
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                idx = int(part)
                current = current[idx] if 0 <= idx < len(current) else None
            else:
                return None
        return current

    def _extract_error_message(self, data: Any) -> Optional[str]:
        if isinstance(data, dict):
            for key in ("message", "error", "detail", "error_description", "errorMessage"):
                if key in data:
                    return str(data[key])
        return None

    def _load_action_version(self, account_id: str, action_id: str, version_id: Optional[str]):
        action = (
            self.db.query(IntegrationAction)
            .filter(
                IntegrationAction.id == action_id,
                (IntegrationAction.account_id == account_id) | (IntegrationAction.account_id.is_(None)),
            )
            .first()
        )
        if not action:
            return None, None
        if version_id:
            version = (
                self.db.query(IntegrationActionVersion)
                .filter(
                    IntegrationActionVersion.id == version_id,
                    IntegrationActionVersion.action_id == action.id,
                )
                .first()
            )
        elif action.published_version_id:
            version = (
                self.db.query(IntegrationActionVersion)
                .filter(IntegrationActionVersion.id == action.published_version_id)
                .first()
            )
        else:
            version = (
                self.db.query(IntegrationActionVersion)
                .filter(
                    IntegrationActionVersion.action_id == action.id,
                    IntegrationActionVersion.status == IntegrationActionStatus.DRAFT,
                )
                .order_by(IntegrationActionVersion.version_number.desc())
                .first()
            )
        return action, version

    def _lock_integration_refresh(self, integration_id: Optional[str]) -> None:
        if not integration_id:
            return
        try:
            self.db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"integration-token-refresh:{integration_id}"},
            )
        except Exception:
            # Non-Postgres tests or degraded DBs still execute; refresh remains best-effort.
            pass

    def _write_logs(
        self,
        request: ActionExecutionRequest,
        result: ActionExecutionResult,
        action: Optional[IntegrationAction],
        version: Optional[IntegrationActionVersion],
        integration_id: Optional[str],
        method: Optional[str],
        endpoint: Optional[str],
    ) -> None:
        try:
            invocation = IntegrationActionInvocation(
                id=uuid.uuid4(),
                account_id=request.context.account_id,
                action_id=str(action.id) if action else None,
                action_version_id=str(version.id) if version else None,
                integration_id=integration_id,
                channel=request.context.channel,
                call_sid=request.context.call_sid,
                call_log_id=request.context.call_log_id,
                tool_id=request.context.tool_id,
                flow_version_id=request.context.flow_version_id,
                flow_tool_id=request.context.flow_tool_id,
                node_id=request.context.node_id,
                source_label=request.context.source_label or (action.name if action else None),
                request_id=result.request_id or uuid.uuid4().hex,
                endpoint_called=_sanitize_endpoint_for_log(endpoint),
                method=method,
                status_code=result.status_code,
                success=result.success,
                latency_ms=result.latency_ms,
                error_type=None if result.success else result.error_type.value,
                error_message=None if result.success else (result.error_message or "")[:500],
                response_metadata=self._response_metadata(result.data),
                called_at=datetime.utcnow(),
            )
            self.db.add(invocation)
            legacy_log = IntegrationCallLog(
                id=uuid.uuid4(),
                account_id=request.context.account_id,
                integration_id=integration_id,
                endpoint_called=_sanitize_endpoint_for_log(endpoint),
                method=method,
                status_code=result.status_code,
                success=result.success,
                latency_ms=result.latency_ms,
                error_type=None if result.success else result.error_type.value,
                error_message=None if result.success else (result.error_message or "")[:500],
                called_at=datetime.utcnow(),
            )
            self.db.add(legacy_log)
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            logger.warning(f"Failed to write action invocation log (non-fatal): {exc}")

    def _response_metadata(self, data: Any) -> dict[str, Any]:
        if isinstance(data, dict):
            return {"type": "object", "keys": list(data.keys())[:20]}
        if isinstance(data, list):
            return {"type": "array", "length": len(data)}
        if data is None:
            return {"type": "null"}
        return {"type": type(data).__name__}

    def _error(
        self,
        request_id: str,
        start_ms: int,
        error_type: APIErrorType,
        error_message: str,
    ) -> ActionExecutionResult:
        return ActionExecutionResult(
            success=False,
            status_code=0,
            error_type=error_type,
            error_message=error_message,
            request_id=request_id,
            latency_ms=int(time.time() * 1000) - start_ms,
        )


def execute_action_sync(db: Session, request: ActionExecutionRequest) -> ActionExecutionResult:
    """Synchronous bridge for legacy SMS/tool paths."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(ActionExecutor(db).execute_and_log(request))
    raise RuntimeError("execute_action_sync cannot run inside an active event loop")
