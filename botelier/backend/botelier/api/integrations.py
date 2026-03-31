from datetime import datetime, timedelta
from typing import Optional, List
from uuid import UUID
import base64
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import Integer
from sqlalchemy.orm import Session
from loguru import logger

from botelier.database import get_db
from botelier.models.integration import IntegrationType, AccountIntegration, IntegrationStatus, IntegrationCallLog
from botelier.auth.middleware import get_current_user


router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _assert_account_access(current_user, account_id: str) -> None:
    """
    Raise 403 if the authenticated user does not have an active membership
    for the requested account_id.  Platform admins bypass this check.

    Call this at the top of every endpoint that takes {account_id} as a path
    parameter so users cannot read or modify another account's data.
    """
    if getattr(current_user, "user_type", None) == "platform_admin":
        return
    memberships = getattr(current_user, "account_memberships", None) or []
    allowed = {str(getattr(m, "account_id", "")) for m in memberships if getattr(m, "is_active", False)}
    if account_id not in allowed:
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this account",
        )


class IntegrationTypeResponse(BaseModel):
    id: str
    slug: str
    name: str
    description: Optional[str]
    logo_url: Optional[str]
    provider: str
    auth_type: str
    documentation_url: Optional[str]
    is_enabled: bool
    required_fields: List[dict]
    endpoint_count: int = 0
    
    class Config:
        from_attributes = True


class AccountIntegrationResponse(BaseModel):
    id: str
    integration_type_id: str
    integration_slug: str
    integration_name: str
    connection_name: Optional[str] = None
    status: str
    connected_at: Optional[datetime]
    last_sync_at: Optional[datetime]
    last_error: Optional[str]
    
    class Config:
        from_attributes = True


class ConnectIntegrationRequest(BaseModel):
    integration_type_id: str
    credentials: dict
    connection_name: Optional[str] = None


class IntegrationEndpointResponse(BaseModel):
    id: str
    category: str
    name: str
    description: str
    method: str
    path: str
    variables: List[dict]


class TestConnectionResponse(BaseModel):
    success: bool
    message: str
    details: Optional[dict] = None


class IntegrationEndpointDetail(BaseModel):
    id: str
    name: str
    method: str
    path: str
    description: Optional[str] = None
    request_schema: Optional[dict] = None
    response_schema: Optional[dict] = None


class IntegrationTypeDetail(BaseModel):
    id: str
    name: str
    slug: str
    endpoints: List[IntegrationEndpointDetail]


class AccountIntegrationWithEndpoints(BaseModel):
    id: str
    integration_type_id: str
    integration_type: IntegrationTypeDetail
    connection_name: Optional[str] = None
    status: str
    connected_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


@router.get("/connections", response_model=List[AccountIntegrationWithEndpoints])
async def get_my_connections(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    account_id = None
    memberships = getattr(current_user, "account_memberships", None) or []
    active = [m for m in memberships if getattr(m, "is_active", False)]
    if active:
        account_id = str(active[0].account_id)
    if not account_id:
        return []
    
    integrations = db.query(AccountIntegration).filter(
        AccountIntegration.account_id == account_id
    ).all()
    
    result = []
    for i in integrations:
        endpoints = i.integration_type.get_endpoints()
        endpoint_details = []
        for ep in endpoints:
            endpoint_details.append(IntegrationEndpointDetail(
                id=ep.get("id", ""),
                name=ep.get("name", ""),
                method=ep.get("method", "GET"),
                path=ep.get("path", ""),
                description=ep.get("description"),
                request_schema=ep.get("request_schema"),
                response_schema=ep.get("response_schema")
            ))
        
        result.append(AccountIntegrationWithEndpoints(
            id=str(i.id),
            integration_type_id=str(i.integration_type_id),
            integration_type=IntegrationTypeDetail(
                id=str(i.integration_type.id),
                name=i.integration_type.name,
                slug=i.integration_type.slug,
                endpoints=endpoint_details
            ),
            connection_name=i.connection_name,
            status=i.status.value,
            connected_at=i.connected_at
        ))
    
    return result


@router.get("/types", response_model=List[IntegrationTypeResponse])
async def list_integration_types(
    db: Session = Depends(get_db)
):
    types = db.query(IntegrationType).filter(
        IntegrationType.is_enabled == True
    ).all()
    
    result = []
    for t in types:
        result.append(IntegrationTypeResponse(
            id=str(t.id),
            slug=t.slug,
            name=t.name,
            description=t.description,
            logo_url=t.logo_url,
            provider=t.provider,
            auth_type=t.auth_type,
            documentation_url=t.documentation_url,
            is_enabled=t.is_enabled,
            required_fields=t.get_required_fields(),
            endpoint_count=len(t.get_endpoints()),
        ))
    
    return result


@router.get("/types/{type_id}", response_model=IntegrationTypeResponse)
async def get_integration_type(
    type_id: str,
    db: Session = Depends(get_db)
):
    integration_type = db.query(IntegrationType).filter(
        IntegrationType.id == type_id
    ).first()
    
    if not integration_type:
        raise HTTPException(status_code=404, detail="Integration type not found")
    
    return IntegrationTypeResponse(
        id=str(integration_type.id),
        slug=integration_type.slug,
        name=integration_type.name,
        description=integration_type.description,
        logo_url=integration_type.logo_url,
        provider=integration_type.provider,
        auth_type=integration_type.auth_type,
        documentation_url=integration_type.documentation_url,
        is_enabled=integration_type.is_enabled,
        required_fields=integration_type.get_required_fields(),
        endpoint_count=len(integration_type.get_endpoints()),
    )


@router.get("/account/{account_id}", response_model=List[AccountIntegrationResponse])
async def list_account_integrations(
    account_id: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    _assert_account_access(current_user, account_id)
    integrations = db.query(AccountIntegration).filter(
        AccountIntegration.account_id == account_id
    ).all()
    
    result = []
    for i in integrations:
        result.append(AccountIntegrationResponse(
            id=str(i.id),
            integration_type_id=str(i.integration_type_id),
            integration_slug=i.integration_type.slug,
            integration_name=i.integration_type.name,
            connection_name=i.connection_name,
            status=i.status.value,
            connected_at=i.connected_at,
            last_sync_at=i.last_sync_at,
            last_error=i.last_error
        ))
    
    return result


@router.get("/account/{account_id}/connected", response_model=List[AccountIntegrationResponse])
async def list_connected_integrations(
    account_id: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    _assert_account_access(current_user, account_id)
    integrations = db.query(AccountIntegration).filter(
        AccountIntegration.account_id == account_id,
        AccountIntegration.status == IntegrationStatus.CONNECTED
    ).all()
    
    result = []
    for i in integrations:
        result.append(AccountIntegrationResponse(
            id=str(i.id),
            integration_type_id=str(i.integration_type_id),
            integration_slug=i.integration_type.slug,
            integration_name=i.integration_type.name,
            connection_name=i.connection_name,
            status=i.status.value,
            connected_at=i.connected_at,
            last_sync_at=i.last_sync_at,
            last_error=i.last_error
        ))
    
    return result


@router.get("/account/{account_id}/integration/{integration_id}/endpoints", response_model=List[IntegrationEndpointResponse])
async def get_integration_endpoints(
    account_id: str,
    integration_id: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    _assert_account_access(current_user, account_id)
    integration = db.query(AccountIntegration).filter(
        AccountIntegration.id == integration_id,
        AccountIntegration.account_id == account_id
    ).first()
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    if integration.status != IntegrationStatus.CONNECTED:
        raise HTTPException(status_code=400, detail="Integration not connected")
    
    endpoints = integration.integration_type.get_endpoints()
    
    result = []
    for ep in endpoints:
        result.append(IntegrationEndpointResponse(
            id=ep.get("id", ""),
            category=ep.get("category", "General"),
            name=ep.get("name", ""),
            description=ep.get("description", ""),
            method=ep.get("method", "GET"),
            path=ep.get("path", ""),
            variables=ep.get("variables", [])
        ))
    
    return result


@router.post("/account/{account_id}/connect", response_model=AccountIntegrationResponse)
async def connect_integration(
    account_id: str,
    request: ConnectIntegrationRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    _assert_account_access(current_user, account_id)
    integration_type = db.query(IntegrationType).filter(
        IntegrationType.id == request.integration_type_id
    ).first()
    
    if not integration_type:
        raise HTTPException(status_code=404, detail="Integration type not found")
    
    user_id = getattr(current_user, "id", None)
    
    integration = AccountIntegration(
        account_id=account_id,
        integration_type_id=request.integration_type_id,
        connection_name=request.connection_name or integration_type.name,
        status=IntegrationStatus.CONNECTING
    )
    integration.set_credentials(request.credentials)
    db.add(integration)
    db.commit()
    
    try:
        auth_type = integration_type.auth_type

        if auth_type == "oauth2_client_credentials":
            token_result = await obtain_oauth_token(integration_type, request.credentials)

            if token_result.get("success"):
                integration.set_access_token(token_result["access_token"])
                if token_result.get("refresh_token"):
                    integration.set_refresh_token(token_result["refresh_token"])
                if token_result.get("expires_in"):
                    integration.token_expires_at = datetime.utcnow() + timedelta(seconds=token_result["expires_in"])

                integration.status = IntegrationStatus.CONNECTED
                integration.connected_at = datetime.utcnow()
                integration.connected_by_user_id = user_id
                integration.last_error = None
                logger.info(f"Successfully connected integration {integration_type.slug} for account {account_id}")
            else:
                integration.status = IntegrationStatus.ERROR
                integration.last_error = token_result.get("error", "Failed to obtain access token")
                logger.error(f"Failed to connect integration {integration_type.slug}: {integration.last_error}")

        elif auth_type == "basic_or_jwt":
            auth_method = request.credentials.get("auth_method", "basic_auth")

            if auth_method == "basic_auth":
                validation_result = await validate_basic_auth(integration_type, request.credentials)

                if validation_result.get("success"):
                    integration.status = IntegrationStatus.CONNECTED
                    integration.connected_at = datetime.utcnow()
                    integration.connected_by_user_id = user_id
                    integration.last_error = None
                    logger.info(f"Successfully connected integration {integration_type.slug} (basic_auth) for account {account_id}")
                else:
                    integration.status = IntegrationStatus.ERROR
                    integration.last_error = validation_result.get("error", "Basic auth validation failed")
                    logger.error(f"Failed to connect integration {integration_type.slug}: {integration.last_error}")

            elif auth_method == "jwt":
                token_result = await obtain_jwt_token(integration_type, request.credentials)

                if token_result.get("success"):
                    integration.set_access_token(token_result["access_token"])
                    if token_result.get("refresh_token"):
                        integration.set_refresh_token(token_result["refresh_token"])
                    if token_result.get("expires_in"):
                        integration.token_expires_at = datetime.utcnow() + timedelta(seconds=token_result["expires_in"])

                    integration.status = IntegrationStatus.CONNECTED
                    integration.connected_at = datetime.utcnow()
                    integration.connected_by_user_id = user_id
                    integration.last_error = None
                    logger.info(f"Successfully connected integration {integration_type.slug} (jwt) for account {account_id}")
                else:
                    integration.status = IntegrationStatus.ERROR
                    integration.last_error = token_result.get("error", "Failed to obtain JWT token")
                    logger.error(f"Failed to connect integration {integration_type.slug}: {integration.last_error}")
            else:
                integration.status = IntegrationStatus.ERROR
                integration.last_error = f"Unsupported auth method: {auth_method}"

        else:
            integration.status = IntegrationStatus.ERROR
            integration.last_error = f"Unsupported auth type: {auth_type}"

        db.commit()
        
    except Exception as e:
        logger.error(f"Error connecting integration: {e}")
        integration.status = IntegrationStatus.ERROR
        integration.last_error = str(e)
        db.commit()
    
    db.refresh(integration)
    
    return AccountIntegrationResponse(
        id=str(integration.id),
        integration_type_id=str(integration.integration_type_id),
        integration_slug=integration.integration_type.slug,
        integration_name=integration.integration_type.name,
        connection_name=integration.connection_name,
        status=integration.status.value,
        connected_at=integration.connected_at,
        last_sync_at=integration.last_sync_at,
        last_error=integration.last_error
    )


@router.post("/account/{account_id}/integration/{integration_id}/test", response_model=TestConnectionResponse)
async def test_integration_connection(
    account_id: str,
    integration_id: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    _assert_account_access(current_user, account_id)
    integration = db.query(AccountIntegration).filter(
        AccountIntegration.id == integration_id,
        AccountIntegration.account_id == account_id
    ).first()
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    credentials = integration.get_credentials()
    integration_type = integration.integration_type
    
    try:
        auth_type = integration_type.auth_type
        auth_method = credentials.get("auth_method", "")

        if auth_type == "basic_or_jwt" and auth_method == "basic_auth":
            test_result = await test_basic_auth_connection(integration_type, credentials)
        else:
            if integration.is_token_expired():
                refresh_result = await refresh_oauth_token(integration_type, integration)
                if not refresh_result.get("success"):
                    return TestConnectionResponse(
                        success=False,
                        message="Token expired and refresh failed",
                        details={"error": refresh_result.get("error")}
                    )
                db.commit()

            test_result = await test_api_connection(integration_type, integration, credentials)
        
        return TestConnectionResponse(
            success=test_result.get("success", False),
            message=test_result.get("message", "Unknown result"),
            details=test_result.get("details")
        )
        
    except Exception as e:
        logger.error(f"Error testing integration: {e}")
        return TestConnectionResponse(
            success=False,
            message=f"Connection test failed: {str(e)}"
        )


@router.delete("/account/{account_id}/integration/{integration_id}")
async def disconnect_integration(
    account_id: str,
    integration_id: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    _assert_account_access(current_user, account_id)
    integration = db.query(AccountIntegration).filter(
        AccountIntegration.id == integration_id,
        AccountIntegration.account_id == account_id
    ).first()
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    integration.credentials_encrypted = None
    integration.access_token_encrypted = None
    integration.refresh_token_encrypted = None
    integration.token_expires_at = None
    integration.status = IntegrationStatus.DISCONNECTED
    integration.connected_at = None
    integration.last_error = None
    
    db.commit()
    
    logger.info(f"Disconnected integration {integration.integration_type.slug} for account {account_id}")
    
    return {"status": "disconnected"}


class CallLogEntry(BaseModel):
    id: str
    integration_id: Optional[str]
    endpoint_called: Optional[str]
    method: Optional[str]
    status_code: Optional[int]
    success: bool
    latency_ms: Optional[int]
    error_type: Optional[str]
    error_message: Optional[str]
    called_at: datetime


@router.get("/account/{account_id}/integration/{integration_id}/call-logs", response_model=List[CallLogEntry])
async def get_integration_call_logs(
    account_id: str,
    integration_id: str,
    limit: int = 20,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_account_access(current_user, account_id)
    integration = db.query(AccountIntegration).filter(
        AccountIntegration.id == integration_id,
        AccountIntegration.account_id == account_id
    ).first()

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    logs = (
        db.query(IntegrationCallLog)
        .filter(
            IntegrationCallLog.account_id == account_id,
            IntegrationCallLog.integration_id == integration_id,
        )
        .order_by(IntegrationCallLog.called_at.desc())
        .limit(min(limit, 100))
        .all()
    )

    return [
        CallLogEntry(
            id=str(l.id),
            integration_id=str(l.integration_id) if l.integration_id else None,
            endpoint_called=l.endpoint_called,
            method=l.method,
            status_code=l.status_code,
            success=l.success,
            latency_ms=l.latency_ms,
            error_type=l.error_type,
            error_message=l.error_message,
            called_at=l.called_at,
        )
        for l in logs
    ]


@router.get("/account/{account_id}/integration/{integration_id}/call-stats")
async def get_integration_call_stats(
    account_id: str,
    integration_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return quick health stats for an integration: total calls, success count, last called_at."""
    _assert_account_access(current_user, account_id)
    integration = db.query(AccountIntegration).filter(
        AccountIntegration.id == integration_id,
        AccountIntegration.account_id == account_id
    ).first()

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    from sqlalchemy import func as sqlfunc

    row = db.query(
        sqlfunc.count(IntegrationCallLog.id).label("total"),
        sqlfunc.sum(
            sqlfunc.cast(IntegrationCallLog.success, Integer)
        ).label("successes"),
        sqlfunc.max(IntegrationCallLog.called_at).label("last_called_at"),
    ).filter(
        IntegrationCallLog.account_id == account_id,
        IntegrationCallLog.integration_id == integration_id,
    ).one()

    total = row.total or 0
    successes = int(row.successes or 0)

    last_failed = (
        db.query(IntegrationCallLog)
        .filter(
            IntegrationCallLog.account_id == account_id,
            IntegrationCallLog.integration_id == integration_id,
            IntegrationCallLog.success == False,  # noqa: E712
        )
        .order_by(IntegrationCallLog.called_at.desc())
        .first()
    )

    return {
        "total_calls": total,
        "successful_calls": successes,
        "failed_calls": total - successes,
        "last_called_at": row.last_called_at,
        "last_error": last_failed.error_message if last_failed else None,
    }


async def obtain_oauth_token(integration_type: IntegrationType, credentials: dict) -> dict:
    auth_config = integration_type.get_auth_config()
    
    gateway_url = credentials.get("gateway_url", "").rstrip("/")
    client_id = credentials.get("client_id")
    client_secret = credentials.get("client_secret")
    enterprise_id = credentials.get("enterprise_id")
    app_key = credentials.get("app_key")
    
    if not all([gateway_url, client_id, client_secret, enterprise_id, app_key]):
        return {"success": False, "error": "Missing required credentials"}
    
    token_url = f"{gateway_url}{auth_config.get('token_endpoint_path', '/oauth/v1/tokens')}"
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "x-app-key": app_key
    }
    
    data = {
        "grant_type": "client_credentials",
        "scope": f"{auth_config.get('scope', 'oraclecloud')}",
    }
    
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
                return {
                    "success": True,
                    "access_token": token_data.get("access_token"),
                    "refresh_token": token_data.get("refresh_token"),
                    "expires_in": token_data.get("expires_in", 3600)
                }
            else:
                logger.error(f"OHIP token request failed: {response.status_code} - {response.text}")
                return {
                    "success": False,
                    "error": f"Token request failed: {response.status_code} - {response.text}"
                }
                
    except Exception as e:
        logger.error(f"OHIP token request exception: {e}")
        return {"success": False, "error": str(e)}


def _compute_jwt_expires_in(token_data: dict, max_lifetime_hours: int) -> int:
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


async def obtain_jwt_token(integration_type: IntegrationType, credentials: dict) -> dict:
    auth_config = integration_type.get_auth_config()
    base_url = auth_config.get("base_url", "").rstrip("/")
    login_endpoint = auth_config.get("jwt_login_endpoint", "/authentication/login")
    max_lifetime_hours = auth_config.get("jwt_max_lifetime_hours", 3)

    username = credentials.get("username")
    password = credentials.get("password")

    if not all([base_url, username, password]):
        return {"success": False, "error": "Missing required credentials (username, password)"}

    login_url = f"{base_url}{login_endpoint}"

    expired_time = (datetime.utcnow() + timedelta(hours=max_lifetime_hours)).strftime("%Y-%m-%d %H:%M:%S")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                login_url,
                json={"username": username, "password": password, "expired_time": expired_time},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=30.0
            )

            if response.status_code == 200:
                token_data = response.json()
                expires_in = _compute_jwt_expires_in(token_data, max_lifetime_hours)
                return {
                    "success": True,
                    "access_token": token_data.get("token") or token_data.get("access_token"),
                    "refresh_token": token_data.get("refresh_token"),
                    "expires_in": expires_in
                }
            else:
                logger.error(f"JWT login request failed: {response.status_code} - {response.text}")
                return {
                    "success": False,
                    "error": f"JWT login failed: {response.status_code} - {response.text}"
                }

    except Exception as e:
        logger.error(f"JWT login request exception: {e}")
        return {"success": False, "error": str(e)}


async def validate_basic_auth(integration_type: IntegrationType, credentials: dict) -> dict:
    auth_config = integration_type.get_auth_config()
    base_url = auth_config.get("base_url", "").rstrip("/")

    username = credentials.get("username")
    password = credentials.get("password")
    apikey = credentials.get("apikey")
    hotel_id = credentials.get("hotelId")

    if not all([base_url, username, password, apikey]):
        return {"success": False, "error": "Missing required credentials (username, password, apikey)"}

    test_url = f"{base_url}/hotels"
    basic_token = base64.b64encode(f"{username}:{password}".encode()).decode()

    headers = {
        "Authorization": f"Basic {basic_token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    params = {"apikey": apikey}
    if hotel_id:
        params["hotelId"] = hotel_id

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                test_url,
                headers=headers,
                params=params,
                timeout=30.0
            )

            if response.status_code == 200:
                return {"success": True}
            elif response.status_code == 401:
                return {"success": False, "error": "Invalid credentials"}
            else:
                return {
                    "success": False,
                    "error": f"Validation request failed: {response.status_code} - {response.text[:500]}"
                }

    except Exception as e:
        logger.error(f"Basic auth validation exception: {e}")
        return {"success": False, "error": str(e)}


async def refresh_oauth_token(integration_type: IntegrationType, integration: AccountIntegration) -> dict:
    credentials = integration.get_credentials()
    auth_type = integration_type.auth_type
    auth_method = credentials.get("auth_method", "")

    if auth_type == "basic_or_jwt" and auth_method == "basic_auth":
        return {"success": True}

    if auth_type == "basic_or_jwt" and auth_method == "jwt":
        auth_config = integration_type.get_auth_config()
        base_url = auth_config.get("base_url", "").rstrip("/")
        refresh_endpoint = auth_config.get("jwt_refresh_endpoint", "/authentication/refresh")
        max_lifetime_hours = auth_config.get("jwt_max_lifetime_hours", 3)
        refresh_token = integration.get_refresh_token()
        expired_time = (datetime.utcnow() + timedelta(hours=max_lifetime_hours)).strftime("%Y-%m-%d %H:%M:%S")

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
                        expires_in = _compute_jwt_expires_in(token_data, max_lifetime_hours)
                        integration.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                        return {"success": True}
            except Exception as e:
                logger.error(f"JWT refresh failed, falling back to login: {e}")

        return await obtain_jwt_token(integration_type, credentials)

    refresh_token = integration.get_refresh_token()
    
    if not refresh_token:
        return await obtain_oauth_token(integration_type, credentials)
    
    auth_config = integration_type.get_auth_config()
    gateway_url = credentials.get("gateway_url", "").rstrip("/")
    client_id = credentials.get("client_id")
    client_secret = credentials.get("client_secret")
    app_key = credentials.get("app_key")
    
    token_url = f"{gateway_url}{auth_config.get('token_endpoint_path', '/oauth/v1/tokens')}"
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "x-app-key": app_key
    }
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    
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
                return {"success": True}
            else:
                return await obtain_oauth_token(integration_type, credentials)
                
    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
        return await obtain_oauth_token(integration_type, credentials)


async def test_api_connection(integration_type: IntegrationType, integration: AccountIntegration, credentials: dict) -> dict:
    auth_type = integration_type.auth_type
    auth_method = credentials.get("auth_method", "")

    if auth_type == "basic_or_jwt" and auth_method == "basic_auth":
        return await test_basic_auth_connection(integration_type, credentials)

    if auth_type == "basic_or_jwt":
        auth_config = integration_type.get_auth_config()
        base_url = auth_config.get("base_url", "").rstrip("/")
        access_token = integration.get_access_token()
        apikey = credentials.get("apikey")

        if not all([base_url, access_token]):
            return {"success": False, "message": "Missing required credentials or token"}

        test_url = f"{base_url}/hotels"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        params = {"apikey": apikey} if apikey else {}
        hotel_id = credentials.get("hotelId")
        if hotel_id:
            params["hotelId"] = hotel_id

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    test_url,
                    headers=headers,
                    params=params,
                    timeout=30.0
                )

                if response.status_code == 200:
                    return {
                        "success": True,
                        "message": "Connection successful",
                        "details": {"status_code": 200}
                    }
                else:
                    return {
                        "success": False,
                        "message": f"API returned {response.status_code}",
                        "details": {"response": response.text[:500]}
                    }
        except Exception as e:
            return {"success": False, "message": f"Connection failed: {str(e)}"}

    gateway_url = credentials.get("gateway_url", "").rstrip("/")
    hotel_id = credentials.get("hotel_id")
    app_key = credentials.get("app_key")
    access_token = integration.get_access_token()
    
    if not all([gateway_url, hotel_id, app_key, access_token]):
        return {"success": False, "message": "Missing required credentials or token"}
    
    test_url = f"{gateway_url}/fof/v1/hotels/{hotel_id}/roomTypes"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-app-key": app_key,
        "x-hotelid": hotel_id,
        "Content-Type": "application/json"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                test_url,
                headers=headers,
                timeout=30.0
            )
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "Connection successful",
                    "details": {"hotel_id": hotel_id, "status_code": 200}
                }
            else:
                return {
                    "success": False,
                    "message": f"API returned {response.status_code}",
                    "details": {"response": response.text[:500]}
                }
                
    except Exception as e:
        return {"success": False, "message": f"Connection failed: {str(e)}"}


async def test_basic_auth_connection(integration_type: IntegrationType, credentials: dict) -> dict:
    auth_config = integration_type.get_auth_config()
    base_url = auth_config.get("base_url", "").rstrip("/")

    username = credentials.get("username")
    password = credentials.get("password")
    apikey = credentials.get("apikey")
    hotel_id = credentials.get("hotelId")

    if not all([base_url, username, password, apikey]):
        return {"success": False, "message": "Missing required credentials"}

    test_url = f"{base_url}/hotels"
    basic_token = base64.b64encode(f"{username}:{password}".encode()).decode()

    headers = {
        "Authorization": f"Basic {basic_token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    params = {"apikey": apikey}
    if hotel_id:
        params["hotelId"] = hotel_id

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                test_url,
                headers=headers,
                params=params,
                timeout=30.0
            )

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "Connection successful",
                    "details": {"status_code": 200}
                }
            else:
                return {
                    "success": False,
                    "message": f"API returned {response.status_code}",
                    "details": {"response": response.text[:500]}
                }

    except Exception as e:
        return {"success": False, "message": f"Connection failed: {str(e)}"}
