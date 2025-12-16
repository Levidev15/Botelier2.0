"""
Integration Management API.

Endpoints for managing third-party integrations like Oracle Opera Cloud.
Supports multi-tenant access where each account manages their own connections.
"""

from datetime import datetime, timedelta
from typing import Optional, List
from uuid import UUID
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from loguru import logger

from botelier.database import get_db
from botelier.models.integration import IntegrationType, AccountIntegration, IntegrationStatus
from botelier.auth.middleware import get_current_user


router = APIRouter(prefix="/api/integrations", tags=["integrations"])


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
    
    class Config:
        from_attributes = True


class AccountIntegrationResponse(BaseModel):
    id: str
    integration_type_id: str
    integration_slug: str
    integration_name: str
    status: str
    connected_at: Optional[datetime]
    last_sync_at: Optional[datetime]
    last_error: Optional[str]
    
    class Config:
        from_attributes = True


class ConnectIntegrationRequest(BaseModel):
    integration_type_id: str
    credentials: dict


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
    status: str
    connected_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


@router.get("/connections", response_model=List[AccountIntegrationWithEndpoints])
async def get_my_connections(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get current user's account integrations with full integration type details.
    
    Used by the flow editor to show available integration endpoints.
    Returns active integrations with their integration type and endpoints.
    """
    account_id = current_user.get("account_id")
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
            status=i.status.value,
            connected_at=i.connected_at
        ))
    
    return result


@router.get("/types", response_model=List[IntegrationTypeResponse])
async def list_integration_types(
    db: Session = Depends(get_db)
):
    """
    List all available integration types.
    
    Returns all enabled integration types that accounts can connect to.
    """
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
            required_fields=t.get_required_fields()
        ))
    
    return result


@router.get("/types/{type_id}", response_model=IntegrationTypeResponse)
async def get_integration_type(
    type_id: str,
    db: Session = Depends(get_db)
):
    """Get details of a specific integration type."""
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
        required_fields=integration_type.get_required_fields()
    )


@router.get("/account/{account_id}", response_model=List[AccountIntegrationResponse])
async def list_account_integrations(
    account_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all integrations for an account.
    
    Returns both connected and available integrations.
    """
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
            status=i.status.value,
            connected_at=i.connected_at,
            last_sync_at=i.last_sync_at,
            last_error=i.last_error
        ))
    
    return result


@router.get("/account/{account_id}/connected", response_model=List[AccountIntegrationResponse])
async def list_connected_integrations(
    account_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List only connected integrations for an account.
    
    Used by flow editor to show available integration endpoints.
    """
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
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get available endpoints for a connected integration.
    
    Returns the pre-configured API endpoints for the integration type.
    Only works for connected integrations.
    """
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
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Connect an integration for an account.
    
    Validates credentials by attempting to obtain an OAuth token,
    then stores encrypted credentials.
    """
    integration_type = db.query(IntegrationType).filter(
        IntegrationType.id == request.integration_type_id
    ).first()
    
    if not integration_type:
        raise HTTPException(status_code=404, detail="Integration type not found")
    
    existing = db.query(AccountIntegration).filter(
        AccountIntegration.account_id == account_id,
        AccountIntegration.integration_type_id == request.integration_type_id
    ).first()
    
    if existing:
        existing.set_credentials(request.credentials)
        existing.status = IntegrationStatus.CONNECTING
        existing.last_error = None
        db.commit()
        integration = existing
    else:
        integration = AccountIntegration(
            account_id=account_id,
            integration_type_id=request.integration_type_id,
            status=IntegrationStatus.CONNECTING
        )
        integration.set_credentials(request.credentials)
        db.add(integration)
        db.commit()
    
    try:
        token_result = await obtain_oauth_token(integration_type, request.credentials)
        
        if token_result.get("success"):
            integration.set_access_token(token_result["access_token"])
            if token_result.get("refresh_token"):
                integration.set_refresh_token(token_result["refresh_token"])
            if token_result.get("expires_in"):
                integration.token_expires_at = datetime.utcnow() + timedelta(seconds=token_result["expires_in"])
            
            integration.status = IntegrationStatus.CONNECTED
            integration.connected_at = datetime.utcnow()
            integration.connected_by_user_id = UUID(current_user["id"]) if current_user.get("id") else None
            integration.last_error = None
            
            logger.info(f"Successfully connected integration {integration_type.slug} for account {account_id}")
        else:
            integration.status = IntegrationStatus.ERROR
            integration.last_error = token_result.get("error", "Failed to obtain access token")
            logger.error(f"Failed to connect integration {integration_type.slug}: {integration.last_error}")
        
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
        status=integration.status.value,
        connected_at=integration.connected_at,
        last_sync_at=integration.last_sync_at,
        last_error=integration.last_error
    )


@router.post("/account/{account_id}/integration/{integration_id}/test", response_model=TestConnectionResponse)
async def test_integration_connection(
    account_id: str,
    integration_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Test an integration connection.
    
    Verifies the stored credentials are still valid by making a test API call.
    """
    integration = db.query(AccountIntegration).filter(
        AccountIntegration.id == integration_id,
        AccountIntegration.account_id == account_id
    ).first()
    
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    credentials = integration.get_credentials()
    integration_type = integration.integration_type
    
    try:
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
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Disconnect an integration.
    
    Removes stored credentials and marks the integration as disconnected.
    """
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


async def obtain_oauth_token(integration_type: IntegrationType, credentials: dict) -> dict:
    """
    Obtain OAuth access token for OHIP.
    
    Uses OAuth 2.0 Resource Owner Password Grant as per OHIP documentation.
    """
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


async def refresh_oauth_token(integration_type: IntegrationType, integration: AccountIntegration) -> dict:
    """
    Refresh an expired OAuth token.
    """
    credentials = integration.get_credentials()
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
    """
    Test the API connection by making a simple request.
    """
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
