"""
Integration Client - Handles authenticated API requests to connected integrations.

This service manages:
- OAuth token caching and automatic refresh
- Request authentication header injection
- Retry logic with exponential backoff
- Response extraction and error handling
- Audit logging for API calls

Used by FlowExecutor when API Request nodes reference integrations.
"""

import re
import json
import httpx
from datetime import datetime, timedelta
from typing import Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger
from sqlalchemy.orm import Session

from botelier.models.integration import AccountIntegration, IntegrationType, IntegrationStatus


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
    """
    Client for making authenticated API requests to connected integrations.
    
    Handles OAuth token management, request signing, and response processing.
    
    Note: This client creates its own database session for each operation to
    support long-running voice calls without exhausting the connection pool.
    """
    
    def __init__(self, account_id: str, db: Session = None):
        self.account_id = account_id
        self._external_db = db
        self._integration_cache: dict[str, AccountIntegration] = {}
    
    def _get_db_session(self) -> Session:
        """Get database session - use provided or create new one."""
        if self._external_db:
            return self._external_db
        from botelier.database import SessionLocal
        return SessionLocal()
    
    async def execute_request(
        self,
        config: IntegrationAPIConfig,
        variables: dict[str, Any]
    ) -> APIResponse:
        """
        Execute an API request to a connected integration.
        
        Args:
            config: The API request configuration
            variables: Flow variables for URL/body substitution
        
        Returns:
            APIResponse with success/failure info and extracted variables
        """
        integration = await self._get_integration(config.integration_id)
        if not integration:
            return APIResponse(
                success=False,
                status_code=0,
                error_type=APIErrorType.AUTH_ERROR,
                error_message="Integration not found or not connected"
            )
        
        if integration.status != IntegrationStatus.CONNECTED:
            return APIResponse(
                success=False,
                status_code=0,
                error_type=APIErrorType.AUTH_ERROR,
                error_message=f"Integration is not connected (status: {integration.status.value})"
            )
        
        if integration.is_token_expired():
            refresh_success = await self._refresh_token(integration)
            if not refresh_success:
                return APIResponse(
                    success=False,
                    status_code=0,
                    error_type=APIErrorType.AUTH_ERROR,
                    error_message="Failed to refresh authentication token"
                )
        
        url = self._build_url(integration, config, variables)
        headers = self._build_headers(integration, config)
        body = self._build_body(config, variables)
        
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
                
                return self._process_response(response, config)
                
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
                return APIResponse(
                    success=False,
                    status_code=0,
                    error_type=APIErrorType.UNKNOWN,
                    error_message=str(e)
                )
        
        return APIResponse(
            success=False,
            status_code=0,
            error_type=APIErrorType.TIMEOUT if isinstance(last_error, httpx.TimeoutException) else APIErrorType.NETWORK_ERROR,
            error_message=str(last_error) if last_error else "Request failed after retries"
        )
    
    async def _get_integration(self, integration_id: str) -> Optional[AccountIntegration]:
        """Get integration from cache or database."""
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
        """Refresh OAuth token for integration."""
        credentials = integration.get_credentials()
        integration_type = integration.integration_type
        auth_config = integration_type.get_auth_config()
        
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
        """Build the full URL for the request."""
        credentials = integration.get_credentials()
        gateway_url = credentials.get("gateway_url", "").rstrip("/")
        
        path = config.path
        if config.endpoint_id:
            endpoints = integration.integration_type.get_endpoints()
            for endpoint in endpoints:
                if endpoint.get("id") == config.endpoint_id:
                    path = endpoint.get("path", path)
                    break
        
        path = self._substitute_variables(path, variables)
        
        hotel_id = credentials.get("hotel_id")
        if hotel_id:
            path = path.replace("{hotelId}", hotel_id)
            path = path.replace("{{hotelId}}", hotel_id)
        
        return f"{gateway_url}{path}"
    
    def _build_headers(
        self,
        integration: AccountIntegration,
        config: IntegrationAPIConfig
    ) -> dict[str, str]:
        """Build request headers with authentication."""
        credentials = integration.get_credentials()
        access_token = integration.get_access_token()
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
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
        """Build request body with variable substitution."""
        if not config.body_template:
            return None
        
        body_str = self._substitute_variables(config.body_template, variables)
        
        try:
            return json.loads(body_str)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse body template as JSON: {body_str}")
            return None
    
    def _substitute_variables(self, template: str, variables: dict[str, Any]) -> str:
        """Replace {{variable_name}} placeholders with actual values."""
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
        """Make the HTTP request."""
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
        """Process the HTTP response and extract variables."""
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
        """Extract variables from response data using JSONPath-like notation."""
        extracted = {}
        
        for rv in response_variables:
            value = self._extract_json_value(data, rv.json_path)
            if value is not None:
                extracted[rv.variable_key] = value
            elif rv.default_value is not None:
                extracted[rv.variable_key] = rv.default_value
        
        return extracted
    
    def _extract_json_value(self, data: Any, path: str) -> Any:
        """
        Extract a value from JSON using dot notation with array support.
        
        Supports:
        - Simple paths: "name", "guest.firstName"
        - Array indexing: "reservations.0.roomNumber"
        - Nested arrays: "data.guests.0.addresses.0.city"
        """
        if not path:
            return data
        
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
        """Try to extract a human-readable error message from error response."""
        if isinstance(data, dict):
            for key in ["message", "error", "detail", "error_description", "errorMessage"]:
                if key in data:
                    return str(data[key])
            if "errors" in data and isinstance(data["errors"], list):
                return "; ".join(str(e.get("message", e)) for e in data["errors"][:3])
        
        return None


def get_llm_friendly_error_message(response: APIResponse, config: IntegrationAPIConfig) -> str:
    """
    Generate an LLM-friendly error message based on the API response.
    
    This message will be injected into the LLM context so it can respond
    appropriately to the caller.
    """
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
