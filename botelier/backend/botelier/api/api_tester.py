import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from botelier.auth.middleware import check_account_permission, get_current_user
from botelier.database import get_db
from botelier.models.integration import AccountIntegration, IntegrationStatus
from botelier.services.action_executor import ActionContext, ActionExecutionRequest, ActionExecutor
from botelier.services.integration_client import IntegrationAPIConfig, ResponseVariable
from botelier.services.ssrf_safe_transport import _BLOCKED_LITERAL_HOSTS, SSRFSafeTransport

router = APIRouter(prefix="/api/api-tester", tags=["api-tester"])


def _validate_url(url: str) -> None:
    """Fast pre-flight check: scheme and literal-host blocklist."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only HTTP/HTTPS URLs are allowed")
    hostname = parsed.hostname or ""
    if not hostname:
        raise HTTPException(status_code=400, detail="Missing hostname in URL")
    if hostname in _BLOCKED_LITERAL_HOSTS:
        raise HTTPException(
            status_code=400, detail="Requests to internal addresses are not allowed"
        )


class ApiTestRequest(BaseModel):
    url: str = Field(..., description="URL to test")
    method: str = Field("GET", description="HTTP method")
    headers: Optional[Dict[str, str]] = Field(default=None)
    body: Optional[str] = Field(default=None, description="Request body as string")
    bodyTemplate: Optional[str] = Field(default=None)
    timeout: Optional[int] = Field(default=30)
    retryCount: Optional[int] = Field(default=0)
    account_id: Optional[str] = Field(default=None)
    variables: Optional[Dict[str, Any]] = Field(default=None)
    responseMapping: Optional[Dict[str, str]] = Field(default=None)
    apiSource: Optional[str] = Field(default=None)
    integrationId: Optional[str] = Field(default=None)
    endpointId: Optional[str] = Field(default=None)
    queryParamOverrides: Optional[Dict[str, str]] = Field(default=None)
    endpointName: Optional[str] = Field(default=None)
    nodeId: Optional[str] = Field(default=None)
    flowToolId: Optional[str] = Field(default=None)
    sourceLabel: Optional[str] = Field(default=None)


class ApiTestResponse(BaseModel):
    status_code: int
    headers: Dict[str, str]
    body: Any
    elapsed_ms: float
    error: Optional[str] = None
    success: bool = False
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    extracted_variables: Dict[str, Any] = Field(default_factory=dict)
    request_id: Optional[str] = None


@router.post("/test", response_model=ApiTestResponse)
async def test_api_request(
    request: ApiTestRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    if request.account_id:
        check_account_permission(current_user, request.account_id, "integrations.manage", db)
        variables = request.variables or {}
        mapping = request.responseMapping or {}

        execution_request = ActionExecutionRequest(
            context=ActionContext(
                account_id=request.account_id,
                channel="test",
                flow_tool_id=request.flowToolId,
                node_id=request.nodeId,
                source_label=request.sourceLabel or request.endpointName or "API Request test",
            ),
            variables=variables,
        )

        if request.apiSource == "integration" and request.integrationId:
            integration = (
                db.query(AccountIntegration)
                .filter(
                    AccountIntegration.id == request.integrationId,
                    AccountIntegration.account_id == request.account_id,
                )
                .first()
            )
            if not integration or integration.status != IntegrationStatus.CONNECTED:
                raise HTTPException(status_code=404, detail="Connected integration not found")

            endpoint = None
            for candidate in integration.integration_type.get_endpoints():
                if str(candidate.get("id")) == str(request.endpointId):
                    endpoint = candidate
                    break
            if not endpoint:
                raise HTTPException(status_code=404, detail="Integration endpoint not found")

            execution_request.integration_config = IntegrationAPIConfig(
                integration_id=str(integration.id),
                endpoint_id=request.endpointId,
                method=str(endpoint.get("method", request.method)).upper(),
                path=endpoint.get("path", request.url),
                endpoint_template=endpoint.get("path", request.url),
                body_template=request.bodyTemplate or request.body,
                timeout=min(int(request.timeout or 8), 30),
                retry_count=int(request.retryCount or 0),
                query_param_overrides=request.queryParamOverrides or {},
                response_variables=[
                    ResponseVariable(variable_key=key, json_path=path)
                    for key, path in mapping.items()
                    if key and path
                ],
            )
        else:
            execution_request.legacy_config = {
                "url": request.url,
                "method": request.method,
                "headers": request.headers or {},
                "bodyTemplate": request.bodyTemplate or request.body,
                "timeout": request.timeout or 8,
                "retryCount": request.retryCount or 0,
                "responseMapping": mapping,
            }

        result = await ActionExecutor(db).execute_and_log(execution_request)
        return ApiTestResponse(
            status_code=result.status_code,
            headers={},
            body=result.data,
            elapsed_ms=result.latency_ms,
            error=result.error_message,
            success=result.success,
            error_type=result.error_type.value,
            error_message=result.error_message,
            extracted_variables=result.extracted_variables,
            request_id=result.request_id,
        )

    _validate_url(request.url)
    start_time = time.time()

    try:
        req_headers = request.headers or {}

        async with httpx.AsyncClient(
            transport=SSRFSafeTransport(),
            timeout=request.timeout or 30,
        ) as client:
            if request.method.upper() == "GET":
                response = await client.get(request.url, headers=req_headers)
            elif request.method.upper() == "POST":
                if request.body:
                    response = await client.post(
                        request.url, headers=req_headers, content=request.body
                    )
                else:
                    response = await client.post(request.url, headers=req_headers)
            elif request.method.upper() == "PUT":
                if request.body:
                    response = await client.put(
                        request.url, headers=req_headers, content=request.body
                    )
                else:
                    response = await client.put(request.url, headers=req_headers)
            elif request.method.upper() == "DELETE":
                response = await client.delete(request.url, headers=req_headers)
            elif request.method.upper() == "PATCH":
                if request.body:
                    response = await client.patch(
                        request.url, headers=req_headers, content=request.body
                    )
                else:
                    response = await client.patch(request.url, headers=req_headers)
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported method: {request.method}")

        elapsed_ms = (time.time() - start_time) * 1000
        resp_headers = dict(response.headers)

        try:
            body = response.json()
        except Exception:
            body = response.text

        return ApiTestResponse(
            status_code=response.status_code,
            headers=resp_headers,
            body=body,
            elapsed_ms=round(elapsed_ms, 2),
            success=200 <= response.status_code < 300,
        )

    except httpx.TimeoutException:
        elapsed_ms = (time.time() - start_time) * 1000
        return ApiTestResponse(
            status_code=0,
            headers={},
            body=None,
            elapsed_ms=round(elapsed_ms, 2),
            error="Request timed out",
        )
    except httpx.ConnectError as e:
        elapsed_ms = (time.time() - start_time) * 1000
        return ApiTestResponse(
            status_code=0,
            headers={},
            body=None,
            elapsed_ms=round(elapsed_ms, 2),
            error=f"Connection error: {str(e)}",
        )
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        return ApiTestResponse(
            status_code=0,
            headers={},
            body=None,
            elapsed_ms=round(elapsed_ms, 2),
            error=str(e),
        )
