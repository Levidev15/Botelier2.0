import re
import json
import base64
import time
import uuid
import httpx
from datetime import datetime, timedelta
from typing import Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse
from loguru import logger
from sqlalchemy.orm import Session

from botelier.models.integration import AccountIntegration, IntegrationType, IntegrationStatus, IntegrationCallLog


_SECRETS_PLACEHOLDER_RE = re.compile(r"\{\{secrets\.[^}]+\}\}")
_COMMON_SECRET_PARAMS = re.compile(
    r"(?i)(api[_-]?key|apikey|token|access[_-]?token|secret|password|passwd|auth|authorization|bearer)=[^&]*",
    re.IGNORECASE,
)


def _sanitize_endpoint_for_log(endpoint: Optional[str]) -> Optional[str]:
    """
    Sanitize a URL or path before persisting to call logs.

    Steps:
    1. Strip the query string entirely (can contain API keys, secrets, etc.)
    2. Remove any residual {{secrets.*}} placeholders that were not substituted.
    3. Truncate to 500 characters.

    This ensures that even if a secret value was resolved into the URL,
    only the path portion is stored.
    """
    if not endpoint:
        return endpoint
    try:
        parsed = urlparse(endpoint)
        sanitized = urlunparse(parsed._replace(query="", fragment=""))
    except Exception:
        sanitized = endpoint
    sanitized = _SECRETS_PLACEHOLDER_RE.sub("[REDACTED]", sanitized)
    return sanitized[:500]


class APIErrorType(str, Enum):
    SUCCESS = "success"
    AUTH_ERROR = "auth_error"
    NOT_FOUND = "not_found"
    VALIDATION_ERROR = "validation_error"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


@dataclass
class APIResponse:
    success: bool
    status_code: int
    data: Optional[Any] = None
    error_type: APIErrorType = APIErrorType.UNKNOWN
    error_message: Optional[str] = None
    extracted_variables: dict = field(default_factory=dict)
    raw_response: Optional[str] = None


@dataclass
class ResponseVariable:
    variable_key: str
    json_path: str
    default_value: Optional[str] = None


@dataclass
class IntegrationAPIConfig:
    integration_id: str
    endpoint_id: Optional[str] = None
    method: str = "GET"
    path: str = ""
    endpoint_template: Optional[str] = None
    headers: Optional[dict[str, str]] = None
    body_template: Optional[str] = None
    timeout: int = 30
    retry_count: int = 2
    response_variables: list[ResponseVariable] = field(default_factory=list)
    on_success_message: str = "Request completed successfully"
    on_error_message: str = "There was an issue processing your request"
    on_not_found_message: str = "The requested information was not found"
    on_auth_error_message: str = "There was an authentication issue with the system"


class IntegrationClient:
    
    def __init__(self, account_id: str, db: Session = None):
        self.account_id = account_id
        self._external_db = db
        self._integration_cache: dict[str, AccountIntegration] = {}
    
    def _get_db_session(self) -> Session:
        if self._external_db:
            return self._external_db
        from botelier.database import SessionLocal
        return SessionLocal()
    
    async def execute_request(
        self,
        config: IntegrationAPIConfig,
        variables: dict[str, Any]
    ) -> APIResponse:
        start_ms = int(time.time() * 1000)

        integration = await self._get_integration(config.integration_id)
        if not integration:
            self._write_call_log(
                integration_id=config.integration_id,
                endpoint_called=config.path,
                method=config.method,
                status_code=0,
                success=False,
                latency_ms=0,
                error_type=APIErrorType.AUTH_ERROR.value,
                error_message="Integration not found or not connected",
            )
            return APIResponse(
                success=False,
                status_code=0,
                error_type=APIErrorType.AUTH_ERROR,
                error_message="Integration not found or not connected"
            )
        
        if integration.status != IntegrationStatus.CONNECTED:
            self._write_call_log(
                integration_id=str(integration.id),
                endpoint_called=config.path,
                method=config.method,
                status_code=0,
                success=False,
                latency_ms=0,
                error_type=APIErrorType.AUTH_ERROR.value,
                error_message=f"Integration is not connected (status: {integration.status.value})",
            )
            return APIResponse(
                success=False,
                status_code=0,
                error_type=APIErrorType.AUTH_ERROR,
                error_message=f"Integration is not connected (status: {integration.status.value})"
            )
        
        credentials = integration.get_credentials()
        auth_method = credentials.get("auth_method", "")
        auth_type = integration.integration_type.auth_type

        needs_token = not (auth_type == "basic_or_jwt" and auth_method == "basic_auth")

        if needs_token and integration.is_token_expired():
            refresh_success = await self._refresh_token(integration)
            if not refresh_success:
                self._write_call_log(
                    integration_id=str(integration.id),
                    endpoint_called=config.path,
                    method=config.method,
                    status_code=0,
                    success=False,
                    latency_ms=int(time.time() * 1000) - start_ms,
                    error_type=APIErrorType.AUTH_ERROR.value,
                    error_message="Failed to refresh authentication token",
                )
                return APIResponse(
                    success=False,
                    status_code=0,
                    error_type=APIErrorType.AUTH_ERROR,
                    error_message="Failed to refresh authentication token"
                )
        
        url = self._build_url(integration, config, variables)
        headers = self._build_headers(integration, config)
        body = self._build_body(config, variables)
        log_endpoint = config.endpoint_template or config.path
        
        attempt = 0
        last_error: Optional[Exception] = None
        
        while attempt <= config.retry_count:
            try:
                response = await self._make_request(
                    method=config.method,
                    url=url,
                    headers=headers,
                    body=body,
                    timeout=config.timeout
                )
                
                result = self._process_response(response, config)
                self._write_call_log(
                    integration_id=str(integration.id),
                    endpoint_called=log_endpoint,
                    method=config.method,
                    status_code=result.status_code,
                    success=result.success,
                    latency_ms=int(time.time() * 1000) - start_ms,
                    error_type=None if result.success else result.error_type.value,
                    error_message=None if result.success else (result.error_message or "")[:500],
                )
                return result
                
            except httpx.TimeoutException:
                logger.warning(f"Request timeout (attempt {attempt + 1}/{config.retry_count + 1}): {url}")
                last_error = httpx.TimeoutException(f"Request timed out after {config.timeout}s")
                attempt += 1
                
            except httpx.NetworkError as e:
                logger.warning(f"Network error (attempt {attempt + 1}/{config.retry_count + 1}): {e}")
                last_error = e
                attempt += 1
                
            except Exception as e:
                logger.error(f"Unexpected error during API request: {e}")
                self._write_call_log(
                    integration_id=str(integration.id),
                    endpoint_called=log_endpoint,
                    method=config.method,
                    status_code=0,
                    success=False,
                    latency_ms=int(time.time() * 1000) - start_ms,
                    error_type=APIErrorType.UNKNOWN.value,
                    error_message=str(e)[:500],
                )
                return APIResponse(
                    success=False,
                    status_code=0,
                    error_type=APIErrorType.UNKNOWN,
                    error_message=str(e)
                )

        error_type = APIErrorType.TIMEOUT if isinstance(last_error, httpx.TimeoutException) else APIErrorType.NETWORK_ERROR
        self._write_call_log(
            integration_id=str(integration.id),
            endpoint_called=url,
            method=config.method,
            status_code=0,
            success=False,
            latency_ms=int(time.time() * 1000) - start_ms,
            error_type=error_type.value,
            error_message=str(last_error)[:500] if last_error else "Request failed after retries",
        )
        return APIResponse(
            success=False,
            status_code=0,
            error_type=error_type,
            error_message=str(last_error) if last_error else "Request failed after retries"
        )

    def _write_call_log(
        self,
        integration_id: Optional[str],
        endpoint_called: Optional[str],
        method: str,
        status_code: int,
        success: bool,
        latency_ms: int,
        error_type: Optional[str],
        error_message: Optional[str],
    ) -> None:
        """Write an IntegrationCallLog row fire-and-forget; never raises."""
        try:
            db = self._get_db_session()
            try:
                log = IntegrationCallLog(
                    id=uuid.uuid4(),
                    account_id=self.account_id,
                    integration_id=integration_id,
                    endpoint_called=_sanitize_endpoint_for_log(endpoint_called),
                    method=method,
                    status_code=status_code,
                    success=success,
                    latency_ms=latency_ms,
                    error_type=error_type,
                    error_message=error_message,
                    called_at=datetime.utcnow(),
                )
                db.add(log)
                db.commit()
            finally:
                if not self._external_db:
                    db.close()
        except Exception as exc:
            logger.warning(f"Failed to write integration call log (non-fatal): {exc}")
    
    async def _get_integration(self, integration_id: str) -> Optional[AccountIntegration]:
        if integration_id in self._integration_cache:
            return self._integration_cache[integration_id]
        
        db = self._get_db_session()
        try:
            integration = db.query(AccountIntegration).filter(
                AccountIntegration.id == integration_id,
                AccountIntegration.account_id == self.account_id
            ).first()
            
            if integration:
                self._integration_cache[integration_id] = integration
            
            return integration
        finally:
            if not self._external_db:
                db.close()
    
    async def _refresh_token(self, integration: AccountIntegration) -> bool:
        credentials = integration.get_credentials()
        integration_type = integration.integration_type
        auth_config = integration_type.get_auth_config()
        auth_type = integration_type.auth_type
        auth_method = credentials.get("auth_method", "")

        if auth_type == "basic_or_jwt" and auth_method == "basic_auth":
            return True

        if auth_type == "basic_or_jwt" and auth_method == "jwt":
            return await self._refresh_jwt_token(integration, credentials, auth_config)

        return await self._refresh_oauth_token(integration, credentials, auth_config)

    def _compute_jwt_expires_in(self, token_data: dict, max_lifetime_hours: int) -> int:
        expired_time_str = token_data.get("expired_time")
        if expired_time_str:
            try:
                expired_dt = datetime.strptime(expired_time_str, "%Y-%m-%d %H:%M:%S")
                seconds_remaining = int((expired_dt - datetime.utcnow()).total_seconds())
                if seconds_remaining > 0:
                    return seconds_remaining
            except (ValueError, TypeError):
                pass
        return token_data.get("expires_in", max_lifetime_hours * 3600)

    async def _refresh_jwt_token(self, integration: AccountIntegration, credentials: dict, auth_config: dict) -> bool:
        base_url = auth_config.get("base_url", "").rstrip("/")
        refresh_endpoint = auth_config.get("jwt_refresh_endpoint", "/authentication/refresh")
        login_endpoint = auth_config.get("jwt_login_endpoint", "/authentication/login")
        max_lifetime_hours = auth_config.get("jwt_max_lifetime_hours", 3)

        refresh_token = integration.get_refresh_token()
        expired_time = (datetime.utcnow() + timedelta(hours=max_lifetime_hours)).strftime("%Y-%m-%d %H:%M:%S")

        db = self._get_db_session()
        try:
            if refresh_token:
                try:
                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            f"{base_url}{refresh_endpoint}",
                            json={"refresh_token": refresh_token, "expired_time": expired_time},
                            headers={"Content-Type": "application/json", "Accept": "application/json"},
                            timeout=30.0
                        )

                        if response.status_code == 200:
                            token_data = response.json()
                            integration.set_access_token(token_data.get("token") or token_data.get("access_token"))
                            if token_data.get("refresh_token"):
                                integration.set_refresh_token(token_data["refresh_token"])
                            expires_in = self._compute_jwt_expires_in(token_data, max_lifetime_hours)
                            integration.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                            integration.status = IntegrationStatus.CONNECTED
                            integration.last_error = None
                            db.add(integration)
                            db.commit()
                            logger.info(f"Successfully refreshed JWT token for integration {integration.id}")
                            return True
                except Exception as e:
                    logger.error(f"JWT refresh failed, falling back to login: {e}")

            username = credentials.get("username")
            password = credentials.get("password")

            if not all([base_url, username, password]):
                logger.error("Missing credentials for JWT login")
                return False

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{base_url}{login_endpoint}",
                        json={"username": username, "password": password, "expired_time": expired_time},
                        headers={"Content-Type": "application/json", "Accept": "application/json"},
                        timeout=30.0
                    )

                    if response.status_code == 200:
                        token_data = response.json()
                        integration.set_access_token(token_data.get("token") or token_data.get("access_token"))
                        if token_data.get("refresh_token"):
                            integration.set_refresh_token(token_data["refresh_token"])
                        expires_in = self._compute_jwt_expires_in(token_data, max_lifetime_hours)
                        integration.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                        integration.status = IntegrationStatus.CONNECTED
                        integration.last_error = None
                        db.add(integration)
                        db.commit()
                        logger.info(f"Successfully re-authenticated JWT for integration {integration.id}")
                        return True
                    else:
                        logger.error(f"JWT login failed: {response.status_code} - {response.text}")
                        integration.status = IntegrationStatus.TOKEN_EXPIRED
                        integration.last_error = f"JWT login failed: {response.status_code}"
                        db.add(integration)
                        db.commit()
                        return False
            except Exception as e:
                logger.error(f"JWT login exception: {e}")
                integration.last_error = str(e)
                db.add(integration)
                db.commit()
                return False
        finally:
            if not self._external_db:
                db.close()

    async def _refresh_oauth_token(self, integration: AccountIntegration, credentials: dict, auth_config: dict) -> bool:
        gateway_url = credentials.get("gateway_url", "").rstrip("/")
        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")
        app_key = credentials.get("app_key")
        
        if not all([gateway_url, client_id, client_secret, app_key]):
            logger.error("Missing credentials for token refresh")
            return False
        
        token_url = f"{gateway_url}{auth_config.get('token_endpoint_path', '/oauth/v1/tokens')}"
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "x-app-key": app_key
        }
        
        refresh_token = integration.get_refresh_token()
        if refresh_token:
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }
        else:
            data = {
                "grant_type": "client_credentials",
                "scope": auth_config.get("scope", "oraclecloud")
            }
        
        db = self._get_db_session()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    token_url,
                    headers=headers,
                    data=data,
                    auth=(client_id, client_secret),
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    token_data = response.json()
                    integration.set_access_token(token_data.get("access_token"))
                    if token_data.get("refresh_token"):
                        integration.set_refresh_token(token_data["refresh_token"])
                    if token_data.get("expires_in"):
                        integration.token_expires_at = datetime.utcnow() + timedelta(seconds=token_data["expires_in"])
                    
                    integration.status = IntegrationStatus.CONNECTED
                    integration.last_error = None
                    db.add(integration)
                    db.commit()
                    
                    logger.info(f"Successfully refreshed token for integration {integration.id}")
                    return True
                else:
                    logger.error(f"Token refresh failed: {response.status_code} - {response.text}")
                    integration.status = IntegrationStatus.TOKEN_EXPIRED
                    integration.last_error = f"Token refresh failed: {response.status_code}"
                    db.add(integration)
                    db.commit()
                    return False
                    
        except Exception as e:
            logger.error(f"Token refresh exception: {e}")
            integration.last_error = str(e)
            db.add(integration)
            db.commit()
            return False
        finally:
            if not self._external_db:
                db.close()
    
    def _build_url(
        self,
        integration: AccountIntegration,
        config: IntegrationAPIConfig,
        variables: dict[str, Any]
    ) -> str:
        credentials = integration.get_credentials()
        auth_type = integration.integration_type.auth_type
        auth_config = integration.integration_type.get_auth_config()

        if auth_type == "basic_or_jwt":
            base_url = auth_config.get("base_url", "").rstrip("/")
        else:
            base_url = credentials.get("gateway_url", "").rstrip("/")
        
        path = config.path
        if config.endpoint_id:
            endpoints = integration.integration_type.get_endpoints()
            for endpoint in endpoints:
                if endpoint.get("id") == config.endpoint_id:
                    path = endpoint.get("path", path)
                    break
        
        path = self._substitute_variables(path, variables)
        
        hotel_id = credentials.get("hotel_id") or credentials.get("hotelId")
        if hotel_id:
            path = path.replace("{hotelId}", hotel_id)
            path = path.replace("{{hotelId}}", hotel_id)
            path = path.replace("{hotel_id}", hotel_id)
            path = path.replace("{{hotel_id}}", hotel_id)

        url = f"{base_url}{path}"

        if auth_type == "basic_or_jwt":
            basic_auth_query_params = auth_config.get("basic_auth_query_params", [])
            if basic_auth_query_params:
                params = {}
                for param_key in basic_auth_query_params:
                    param_value = credentials.get(param_key)
                    if param_value:
                        params[param_key] = param_value
                if params:
                    separator = "&" if "?" in url else "?"
                    url = f"{url}{separator}{urlencode(params)}"
        
        return url
    
    def _build_headers(
        self,
        integration: AccountIntegration,
        config: IntegrationAPIConfig
    ) -> dict[str, str]:
        credentials = integration.get_credentials()
        auth_type = integration.integration_type.auth_type
        auth_method = credentials.get("auth_method", "")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        if auth_type == "basic_or_jwt" and auth_method == "basic_auth":
            username = credentials.get("username", "")
            password = credentials.get("password", "")
            basic_token = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {basic_token}"
        else:
            access_token = integration.get_access_token()
            if access_token:
                headers["Authorization"] = f"Bearer {access_token}"
        
        if auth_type == "oauth2_client_credentials":
            app_key = credentials.get("app_key")
            if app_key:
                headers["x-app-key"] = app_key
            hotel_id = credentials.get("hotel_id")
            if hotel_id:
                headers["x-hotelid"] = hotel_id
        
        if config.headers:
            headers.update(config.headers)
        
        return headers
    
    def _build_body(
        self,
        config: IntegrationAPIConfig,
        variables: dict[str, Any]
    ) -> Optional[dict]:
        if not config.body_template:
            return None
        
        body_str = self._substitute_variables(config.body_template, variables)
        
        try:
            return json.loads(body_str)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse body template as JSON: {body_str}")
            return None
    
    def _substitute_variables(self, template: str, variables: dict[str, Any]) -> str:
        def replace_var(match):
            var_name = match.group(1)
            value = variables.get(var_name)
            if value is None:
                return match.group(0)
            return str(value)
        
        return re.sub(r'\{\{(\w+)\}\}', replace_var, template)
    
    async def _make_request(
        self,
        method: str,
        url: str,
        headers: dict,
        body: Optional[dict],
        timeout: int
    ) -> httpx.Response:
        async with httpx.AsyncClient() as client:
            if method.upper() == "GET":
                return await client.get(url, headers=headers, timeout=timeout)
            elif method.upper() == "POST":
                return await client.post(url, headers=headers, json=body, timeout=timeout)
            elif method.upper() == "PUT":
                return await client.put(url, headers=headers, json=body, timeout=timeout)
            elif method.upper() == "PATCH":
                return await client.patch(url, headers=headers, json=body, timeout=timeout)
            elif method.upper() == "DELETE":
                return await client.delete(url, headers=headers, timeout=timeout)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
    
    def _process_response(
        self,
        response: httpx.Response,
        config: IntegrationAPIConfig
    ) -> APIResponse:
        status_code = response.status_code
        
        try:
            data = response.json()
        except json.JSONDecodeError:
            data = response.text
        
        if 200 <= status_code < 300:
            extracted = self._extract_variables(data, config.response_variables)
            return APIResponse(
                success=True,
                status_code=status_code,
                data=data,
                error_type=APIErrorType.SUCCESS,
                extracted_variables=extracted
            )
        
        elif status_code == 401 or status_code == 403:
            return APIResponse(
                success=False,
                status_code=status_code,
                data=data,
                error_type=APIErrorType.AUTH_ERROR,
                error_message=config.on_auth_error_message
            )
        
        elif status_code == 404:
            return APIResponse(
                success=False,
                status_code=status_code,
                data=data,
                error_type=APIErrorType.NOT_FOUND,
                error_message=config.on_not_found_message
            )
        
        elif status_code == 400 or status_code == 422:
            error_detail = self._extract_error_message(data)
            return APIResponse(
                success=False,
                status_code=status_code,
                data=data,
                error_type=APIErrorType.VALIDATION_ERROR,
                error_message=error_detail or config.on_error_message
            )
        
        elif status_code >= 500:
            return APIResponse(
                success=False,
                status_code=status_code,
                data=data,
                error_type=APIErrorType.SERVER_ERROR,
                error_message=config.on_error_message
            )
        
        else:
            return APIResponse(
                success=False,
                status_code=status_code,
                data=data,
                error_type=APIErrorType.UNKNOWN,
                error_message=config.on_error_message
            )
    
    def _extract_variables(
        self,
        data: Any,
        response_variables: list[ResponseVariable]
    ) -> dict[str, Any]:
        extracted = {}
        
        for rv in response_variables:
            value = self._extract_json_value(data, rv.json_path)
            if value is not None:
                extracted[rv.variable_key] = value
            elif rv.default_value is not None:
                extracted[rv.variable_key] = rv.default_value
        
        return extracted
    
    def _extract_json_value(self, data: Any, path: str) -> Any:
        if not path:
            return data
        
        if path.startswith("$."):
            path = path[2:]
        
        parts = path.split(".")
        current = data
        
        for part in parts:
            if current is None:
                return None
            
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                if part.isdigit():
                    idx = int(part)
                    if 0 <= idx < len(current):
                        current = current[idx]
                    else:
                        return None
                else:
                    return None
            else:
                return None
        
        return current
    
    def _extract_error_message(self, data: Any) -> Optional[str]:
        if isinstance(data, dict):
            for key in ["message", "error", "detail", "error_description", "errorMessage"]:
                if key in data:
                    return str(data[key])
            if "errors" in data and isinstance(data["errors"], list):
                return "; ".join(str(e.get("message", e)) for e in data["errors"][:3])
        
        return None


def get_llm_friendly_error_message(response: APIResponse, config: IntegrationAPIConfig) -> str:
    if response.success:
        return config.on_success_message
    
    if response.error_type == APIErrorType.AUTH_ERROR:
        return "I'm having trouble connecting to our system right now. Let me transfer you to someone who can help."
    
    elif response.error_type == APIErrorType.NOT_FOUND:
        return config.on_not_found_message
    
    elif response.error_type == APIErrorType.VALIDATION_ERROR:
        if response.error_message:
            return f"There was an issue with the information provided: {response.error_message}"
        return "The information provided doesn't match what we need. Could you please verify and try again?"
    
    elif response.error_type == APIErrorType.SERVER_ERROR:
        return "Our system is experiencing some difficulties right now. Please try again in a moment."
    
    elif response.error_type == APIErrorType.TIMEOUT:
        return "I'm taking a bit longer than expected to look that up. Please hold on."
    
    elif response.error_type == APIErrorType.NETWORK_ERROR:
        return "I'm having trouble connecting to our system. Let me try again."
    
    return config.on_error_message
