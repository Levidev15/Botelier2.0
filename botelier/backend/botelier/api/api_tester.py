import time
from typing import Optional, Dict, Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from botelier.auth.middleware import get_current_user
from botelier.services.ssrf_safe_transport import SSRFSafeTransport, _BLOCKED_LITERAL_HOSTS

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
        raise HTTPException(status_code=400, detail="Requests to internal addresses are not allowed")


class ApiTestRequest(BaseModel):
    url: str = Field(..., description="URL to test")
    method: str = Field("GET", description="HTTP method")
    headers: Optional[Dict[str, str]] = Field(default=None)
    body: Optional[str] = Field(default=None, description="Request body as string")
    timeout: Optional[int] = Field(default=30)


class ApiTestResponse(BaseModel):
    status_code: int
    headers: Dict[str, str]
    body: Any
    elapsed_ms: float
    error: Optional[str] = None


@router.post("/test", response_model=ApiTestResponse)
async def test_api_request(
    request: ApiTestRequest,
    current_user=Depends(get_current_user),
):
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
                raise HTTPException(
                    status_code=400, detail=f"Unsupported method: {request.method}"
                )

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
