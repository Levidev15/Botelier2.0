import base64
import secrets
from datetime import datetime, timedelta
from typing import List, Optional
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import Integer, func as sqlfunc
from sqlalchemy.orm import Session, joinedload

from botelier.auth.middleware import (
    check_account_permission,
    get_current_user,
)
from botelier.config.domain import get_frontend_url, get_public_base_url
from botelier.database import get_db
from botelier.services.integration_runtime.adapters.oauth2 import resolve_token_endpoint
from botelier.services.property_scope import property_belongs_to_account
from botelier.models.integration import (
    AccountIntegration,
    IntegrationAction,
    IntegrationActionInvocation,
    IntegrationCallLog,
    IntegrationStatus,
    IntegrationType,
)
from botelier.models.operation_policy import ConnectionOperationPolicy
from botelier.services.integration_client import (
    _validate_opera_gateway_url as _validate_opera_gateway_url_shared,
    build_auth_request_query_params,
)
from botelier.services.ssrf_safe_transport import SSRFSafeTransport

# Reserved connection_config key for the in-flight 3-legged OAuth2 flow.
# The nonce is cleared once the exchange completes so a state value can't be
# replayed.
_OAUTH_STATE_NONCE_KEY = "_oauth_state_nonce"

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

def _validate_opera_gateway_url(gateway_url: str) -> None:
    """API-edge wrapper around the single shared Oracle gateway-URL validator.

    The allow-list and validation logic live once in the integration runtime's
    Opera adapter (re-exported via ``integration_client``); this wrapper only
    translates the ValueError it raises into an HTTP 400 for connect-flow
    callers, keeping a single source of truth for the SSRF allow-list.
    """
    try:
        _validate_opera_gateway_url_shared(gateway_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _assert_account_access(
    current_user,
    account_id: str,
    db: Session,
    permission: str = "integrations.view",
) -> None:
    """Authorize the caller for an account-scoped integrations endpoint
    (Task #144).

    Delegates to ``check_account_permission`` so role-based gating is
    uniform with the rest of the codebase: the user must have an active
    membership in ``account_id`` AND the membership's resolved permissions
    must grant ``permission``.  Platform admins bypass both checks.

    The default ``permission`` is ``integrations.view``, granted to the
    ``account_admin``, ``staff`` and ``viewer`` system roles.  Privileged
    routes that mutate third-party connections, exercise outbound API
    traffic, or expose detailed integration call-log error bodies must
    pass ``permission="integrations.manage"``, granted only to
    ``account_admin`` by default.

    Raises ``HTTPException(400)`` on a malformed ``account_id`` and
    ``HTTPException(403)`` on permission failure.
    """
    try:
        UUID(str(account_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid account_id")
    check_account_permission(current_user, account_id, permission, db)


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
    property_id: Optional[str] = None

    class Config:
        from_attributes = True


class ConnectIntegrationRequest(BaseModel):
    integration_type_id: str
    credentials: dict
    connection_name: Optional[str] = None
    property_id: Optional[str] = None


class UpdateCredentialsRequest(BaseModel):
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
    variables: List[dict] = []
    query_params: List[dict] = []
    response_mapping: dict = {}
    response_mapping_labels: dict = {}
    source: str = "seeded"


class IntegrationTypeDetail(BaseModel):
    id: str
    name: str
    slug: str
    endpoints: List[IntegrationEndpointDetail]
    origin: str = "platform_certified"


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
    account_id: Optional[str] = Query(None),
    assistant_id: Optional[str] = Query(None, description="When supplied, only return connections assigned to this assistant (empty assignment = all connections)"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return connected integrations for the requested account.

    Flow-editor callers send their selected dashboard account.  Omitting it
    intentionally returns no catalog rather than guessing from the first
    active membership, which could expose another dashboard account's
    connections to a multi-account user.

    When ``assistant_id`` is supplied the results are further filtered to the
    connections assigned to that assistant.  An assistant with an empty
    ``allowed_connection_ids`` list sees all connections (backwards-compatible
    default for assistants that pre-date per-assistant scoping).
    """
    if not account_id:
        return []
    _assert_account_access(current_user, account_id, db)

    # Resolve assistant-level connection filter when requested.
    allowed_ids: Optional[set] = None
    if assistant_id:
        from botelier.models.assistant import Assistant as AssistantModel
        assistant_obj = (
            db.query(AssistantModel)
            .filter(
                AssistantModel.id == assistant_id,
                AssistantModel.account_id == account_id,
            )
            .first()
        )
        if assistant_obj is None:
            raise HTTPException(status_code=404, detail="Assistant not found for this account")
        if assistant_obj.allowed_connection_ids:
            allowed_ids = set(str(cid) for cid in assistant_obj.allowed_connection_ids)

    integrations = (
        db.query(AccountIntegration).filter(AccountIntegration.account_id == account_id).all()
    )
    # Apply per-assistant filter when a non-empty allow-list exists.
    if allowed_ids is not None:
        integrations = [i for i in integrations if str(i.id) in allowed_ids]
    policies_by_connection: dict[str, dict[str, ConnectionOperationPolicy]] = {}
    if integrations:
        connection_ids = [i.id for i in integrations]
        for policy in (
            db.query(ConnectionOperationPolicy)
            .filter(ConnectionOperationPolicy.account_integration_id.in_(connection_ids))
            .all()
        ):
            policies_by_connection.setdefault(
                str(policy.account_integration_id), {}
            )[policy.operation_id] = policy

    result = []
    for i in integrations:
        endpoints = i.integration_type.get_endpoints()
        endpoint_details = []
        endpoint_source = (
            "imported"
            if i.integration_type.origin == "customer_imported"
            else "seeded"
        )
        connection_policies = policies_by_connection.get(str(i.id), {})
        for ep in endpoints:
            policy = connection_policies.get(ep.get("id", ""))
            endpoint_details.append(
                IntegrationEndpointDetail(
                    id=ep.get("id", ""),
                    name=ep.get("name", ""),
                    method=ep.get("method", "GET"),
                    path=ep.get("path", ""),
                    description=ep.get("description"),
                    request_schema=ep.get("request_schema"),
                    response_schema=ep.get("response_schema"),
                    variables=ep.get("variables", []),
                    query_params=ep.get("query_params", []),
                    # The API Builder's per-connection mapping takes precedence
                    # over the type-level seed, so the flow node receives the
                    # same projection configuration an operator tested there.
                    response_mapping=(
                        policy.response_mapping
                        if policy and policy.response_mapping is not None
                        else ep.get("response_mapping", {})
                    ),
                    response_mapping_labels=ep.get("response_mapping_labels", {}),
                    source=endpoint_source,
                )
            )

        result.append(
            AccountIntegrationWithEndpoints(
                id=str(i.id),
                integration_type_id=str(i.integration_type_id),
                integration_type=IntegrationTypeDetail(
                    id=str(i.integration_type.id),
                    name=i.integration_type.name,
                    slug=i.integration_type.slug,
                    endpoints=endpoint_details,
                    origin=i.integration_type.origin or "platform_certified",
                ),
                connection_name=i.connection_name,
                status=i.status.value,
                connected_at=i.connected_at,
            )
        )

    return result


@router.get("/types", response_model=List[IntegrationTypeResponse])
async def list_integration_types(db: Session = Depends(get_db)):
    types = db.query(IntegrationType).filter(IntegrationType.is_enabled == True).all()

    result = []
    for t in types:
        result.append(
            IntegrationTypeResponse(
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
            )
        )

    return result


@router.get("/types/{type_id}", response_model=IntegrationTypeResponse)
async def get_integration_type(type_id: str, db: Session = Depends(get_db)):
    integration_type = db.query(IntegrationType).filter(IntegrationType.id == type_id).first()

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
    account_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)
):
    _assert_account_access(current_user, account_id, db)
    integrations = (
        db.query(AccountIntegration).filter(AccountIntegration.account_id == account_id).all()
    )

    result = []
    for i in integrations:
        result.append(
            AccountIntegrationResponse(
                id=str(i.id),
                integration_type_id=str(i.integration_type_id),
                integration_slug=i.integration_type.slug,
                integration_name=i.integration_type.name,
                connection_name=i.connection_name,
                status=i.status.value,
                connected_at=i.connected_at,
                last_sync_at=i.last_sync_at,
                last_error=i.last_error,
                property_id=str(i.property_id) if i.property_id else None,
            )
        )

    return result


@router.get("/account/{account_id}/connected", response_model=List[AccountIntegrationResponse])
async def list_connected_integrations(
    account_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)
):
    _assert_account_access(current_user, account_id, db)
    integrations = (
        db.query(AccountIntegration)
        .filter(
            AccountIntegration.account_id == account_id,
            AccountIntegration.status == IntegrationStatus.CONNECTED,
        )
        .all()
    )

    result = []
    for i in integrations:
        result.append(
            AccountIntegrationResponse(
                id=str(i.id),
                integration_type_id=str(i.integration_type_id),
                integration_slug=i.integration_type.slug,
                integration_name=i.integration_type.name,
                connection_name=i.connection_name,
                status=i.status.value,
                connected_at=i.connected_at,
                last_sync_at=i.last_sync_at,
                last_error=i.last_error,
                property_id=str(i.property_id) if i.property_id else None,
            )
        )

    return result


@router.get(
    "/account/{account_id}/integration/{integration_id}/endpoints",
    response_model=List[IntegrationEndpointResponse],
)
async def get_integration_endpoints(
    account_id: str,
    integration_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_account_access(current_user, account_id, db)
    integration = (
        db.query(AccountIntegration)
        .filter(
            AccountIntegration.id == integration_id, AccountIntegration.account_id == account_id
        )
        .first()
    )

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    if integration.status != IntegrationStatus.CONNECTED:
        raise HTTPException(status_code=400, detail="Integration not connected")

    endpoints = integration.integration_type.get_endpoints()

    result = []
    for ep in endpoints:
        result.append(
            IntegrationEndpointResponse(
                id=ep.get("id", ""),
                category=ep.get("category", "General"),
                name=ep.get("name", ""),
                description=ep.get("description", ""),
                method=ep.get("method", "GET"),
                path=ep.get("path", ""),
                variables=ep.get("variables", []),
            )
        )

    return result


def _split_fields_by_storage(
    integration_type: IntegrationType, values: dict
) -> tuple[dict, dict]:
    """Partition submitted field values into (credentials, connection_config).

    Any ``required_field`` flagged ``"storage": "connection_config"`` is a
    non-secret, property-level constant (e.g. a hotel id) and belongs on the
    connection's plaintext ``connection_config`` JSON instead of the encrypted
    credentials blob. Everything else stays in credentials. Keys not declared on
    the type default to credentials so unknown/legacy values are never dropped.
    """
    config_keys = {
        f["key"]
        for f in (integration_type.get_required_fields() or [])
        if f.get("storage") == "connection_config"
    }
    credentials_part = {k: v for k, v in values.items() if k not in config_keys}
    connection_config_part = {k: v for k, v in values.items() if k in config_keys}
    return credentials_part, connection_config_part


@router.post("/account/{account_id}/connect", response_model=AccountIntegrationResponse)
async def connect_integration(
    account_id: str,
    request: ConnectIntegrationRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_account_access(current_user, account_id, db, permission="integrations.manage")
    integration_type = (
        db.query(IntegrationType).filter(IntegrationType.id == request.integration_type_id).first()
    )

    if not integration_type:
        raise HTTPException(status_code=404, detail="Integration type not found")

    if integration_type.auth_type == "oauth2_client_credentials":
        gateway_url = request.credentials.get("gateway_url", "")
        _validate_opera_gateway_url(gateway_url)

    user_id = getattr(current_user, "id", None)

    if request.property_id is not None and not property_belongs_to_account(
        db, account_id, request.property_id
    ):
        raise HTTPException(status_code=400, detail="Property not found for this account")

    integration = AccountIntegration(
        account_id=account_id,
        property_id=request.property_id,
        integration_type_id=request.integration_type_id,
        connection_name=request.connection_name or integration_type.name,
        status=IntegrationStatus.CONNECTING,
    )
    cred_part, conn_config_part = _split_fields_by_storage(
        integration_type, request.credentials
    )
    integration.set_credentials(cred_part)
    if conn_config_part:
        integration.set_connection_config(conn_config_part)
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
                # Always write token_expires_at — _compute_jwt_expires_in guarantees > 0;
                # a zero/missing expires_in must never leave a stale past timestamp in place.
                if token_result.get("expires_in"):
                    integration.token_expires_at = datetime.utcnow() + timedelta(
                        seconds=token_result["expires_in"]
                    )

                integration.status = IntegrationStatus.CONNECTED
                integration.connected_at = datetime.utcnow()
                integration.connected_by_user_id = user_id
                integration.last_error = None
                logger.info(
                    f"Successfully connected integration {integration_type.slug} for account {account_id}"
                )
            else:
                integration.status = IntegrationStatus.ERROR
                integration.last_error = token_result.get("error", "Failed to obtain access token")
                logger.error(
                    f"Failed to connect integration {integration_type.slug}: {integration.last_error}"
                )

        elif auth_type == "basic_or_jwt":
            auth_method = request.credentials.get("auth_method", "basic_auth")

            if auth_method == "basic_auth":
                validation_result = await validate_basic_auth(integration_type, request.credentials)

                if validation_result.get("success"):
                    integration.status = IntegrationStatus.CONNECTED
                    integration.connected_at = datetime.utcnow()
                    integration.connected_by_user_id = user_id
                    integration.last_error = None
                    logger.info(
                        f"Successfully connected integration {integration_type.slug} (basic_auth) for account {account_id}"
                    )
                else:
                    integration.status = IntegrationStatus.ERROR
                    integration.last_error = validation_result.get(
                        "error", "Basic auth validation failed"
                    )
                    logger.error(
                        f"Failed to connect integration {integration_type.slug}: {integration.last_error}"
                    )

            elif auth_method == "jwt":
                token_result = await obtain_jwt_token(integration_type, request.credentials)

                if token_result.get("success"):
                    integration.set_access_token(token_result["access_token"])
                    if token_result.get("refresh_token"):
                        integration.set_refresh_token(token_result["refresh_token"])
                    # _compute_jwt_expires_in always returns > 0 — unconditionally stamp
                    # token_expires_at so a stale past value never survives a reconnect.
                    integration.token_expires_at = datetime.utcnow() + timedelta(
                        seconds=token_result["expires_in"]
                    )

                    integration.status = IntegrationStatus.CONNECTED
                    integration.connected_at = datetime.utcnow()
                    integration.connected_by_user_id = user_id
                    integration.last_error = None
                    logger.info(
                        f"Successfully connected integration {integration_type.slug} (jwt) for account {account_id}"
                    )
                else:
                    integration.status = IntegrationStatus.ERROR
                    integration.last_error = token_result.get("error", "Failed to obtain JWT token")
                    logger.error(
                        f"Failed to connect integration {integration_type.slug}: {integration.last_error}"
                    )
            else:
                integration.status = IntegrationStatus.ERROR
                integration.last_error = f"Unsupported auth method: {auth_method}"

        elif auth_type == "default":
            from botelier.services.integration_runtime.adapters import DEFAULT_ADAPTER

            auth_config = integration_type.get_auth_config() or {}
            connect_result = await DEFAULT_ADAPTER.connect(request.credentials, auth_config)
            if connect_result.success:
                if connect_result.access_token:
                    integration.set_access_token(connect_result.access_token)
                    if connect_result.refresh_token:
                        integration.set_refresh_token(connect_result.refresh_token)
                    if connect_result.expires_in:
                        integration.token_expires_at = datetime.utcnow() + timedelta(
                            seconds=connect_result.expires_in
                        )
                integration.status = IntegrationStatus.CONNECTED
                integration.connected_at = datetime.utcnow()
                integration.connected_by_user_id = user_id
                integration.last_error = None
                logger.info(
                    f"Successfully connected integration {integration_type.slug} for account {account_id}"
                )
            else:
                integration.status = IntegrationStatus.ERROR
                integration.last_error = connect_result.error or "Connection failed"
                logger.error(
                    f"Failed to connect integration {integration_type.slug}: {integration.last_error}"
                )

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
        last_error=integration.last_error,
        property_id=str(integration.property_id) if integration.property_id else None,
    )


@router.get("/account/{account_id}/integration/{integration_id}/credentials")
async def get_integration_credentials(
    account_id: str,
    integration_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return decrypted credential values for the edit form.

    Password-type fields are returned as empty strings so the UI can pre-fill
    non-sensitive fields (gateway URL, client ID, hotel ID, etc.) while never
    exposing stored secrets to the browser.
    """
    _assert_account_access(current_user, account_id, db, permission="integrations.manage")
    integration = (
        db.query(AccountIntegration)
        .filter(
            AccountIntegration.id == integration_id,
            AccountIntegration.account_id == account_id,
        )
        .first()
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    credentials = integration.get_credentials()
    conn_config = integration.get_connection_config()
    required_fields = integration.integration_type.get_required_fields()

    safe_credentials: dict = {}
    for field in required_fields:
        key = field["key"]
        if field.get("type") == "password":
            safe_credentials[key] = ""
        elif field.get("storage") == "connection_config":
            # Non-secret; prefer connection_config, fall back to any legacy copy
            # still living in the credentials blob so the edit form pre-fills it.
            safe_credentials[key] = conn_config.get(key, credentials.get(key, ""))
        else:
            safe_credentials[key] = credentials.get(key, "")

    return {
        "connection_name": integration.connection_name,
        "credentials": safe_credentials,
    }


@router.patch(
    "/account/{account_id}/integration/{integration_id}/credentials",
    response_model=AccountIntegrationResponse,
)
async def update_integration_credentials(
    account_id: str,
    integration_id: str,
    request: UpdateCredentialsRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update credentials for an existing integration and re-authenticate.

    Password fields left blank in the request retain their current stored value —
    the caller only needs to supply a new value to rotate a secret.
    All non-password fields are overwritten. After merging, a fresh token fetch
    is attempted and the status is updated accordingly.
    """
    _assert_account_access(current_user, account_id, db, permission="integrations.manage")
    integration = (
        db.query(AccountIntegration)
        .filter(
            AccountIntegration.id == integration_id,
            AccountIntegration.account_id == account_id,
        )
        .first()
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    integration_type = integration.integration_type
    existing_credentials = integration.get_credentials()
    existing_conn_config = integration.get_connection_config()
    required_fields = integration_type.get_required_fields()
    config_keys = {
        f["key"] for f in required_fields if f.get("storage") == "connection_config"
    }

    merged = dict(existing_credentials)
    merged_conn_config = dict(existing_conn_config)
    for field in required_fields:
        key = field["key"]
        incoming = request.credentials.get(key)
        # Password fields: blank means "unchanged" (user didn't re-type the secret).
        # All other fields: treat an empty-string submission the same — preserve the
        # stored value rather than overwriting it with "".  This prevents a common
        # UX pattern where the Edit form pre-fills non-sensitive fields but leaves
        # sensitive ones (e.g. apikey) blank, which would silently wipe the credential
        # and break token refresh on the next expiry cycle.
        if not incoming:
            continue
        if key in config_keys:
            merged_conn_config[key] = incoming
        else:
            merged[key] = incoming

    # Lazily migrate legacy values: once a field is stored in connection_config,
    # drop any stale copy from the encrypted credentials blob so the two stores
    # cannot diverge (connection_config is the source of truth for these keys).
    for key in config_keys:
        merged.pop(key, None)

    if integration_type.auth_type == "oauth2_client_credentials":
        gateway_url = merged.get("gateway_url", "")
        _validate_opera_gateway_url(gateway_url)

    if request.connection_name is not None:
        integration.connection_name = request.connection_name or integration.connection_name

    integration.set_credentials(merged)
    integration.set_connection_config(merged_conn_config)
    # Validation/token calls read from a combined view so a connection_config
    # field (e.g. hotelId used to scope a Basic Auth test) is still visible.
    auth_input = {**merged_conn_config, **merged}
    integration.status = IntegrationStatus.CONNECTING
    integration.last_error = None
    db.commit()

    try:
        auth_type = integration_type.auth_type

        if auth_type == "oauth2_client_credentials":
            token_result = await obtain_oauth_token(integration_type, auth_input)
            if token_result.get("success"):
                integration.set_access_token(token_result["access_token"])
                if token_result.get("refresh_token"):
                    integration.set_refresh_token(token_result["refresh_token"])
                if token_result.get("expires_in"):
                    integration.token_expires_at = datetime.utcnow() + timedelta(
                        seconds=token_result["expires_in"]
                    )
                integration.status = IntegrationStatus.CONNECTED
                integration.last_error = None
                logger.info(
                    f"Credentials updated for {integration_type.slug} integration {integration_id}"
                )
            else:
                integration.status = IntegrationStatus.ERROR
                integration.last_error = token_result.get("error", "Failed to obtain access token")
                logger.error(
                    f"Credential update failed for {integration_type.slug}: {integration.last_error}"
                )

        elif auth_type == "basic_or_jwt":
            auth_method = merged.get("auth_method", "basic_auth")
            if auth_method == "basic_auth":
                validation_result = await validate_basic_auth(integration_type, auth_input)
                if validation_result.get("success"):
                    integration.status = IntegrationStatus.CONNECTED
                    integration.last_error = None
                else:
                    integration.status = IntegrationStatus.ERROR
                    integration.last_error = validation_result.get("error", "Auth validation failed")
            elif auth_method == "jwt":
                token_result = await obtain_jwt_token(integration_type, auth_input)
                if token_result.get("success"):
                    integration.set_access_token(token_result["access_token"])
                    if token_result.get("refresh_token"):
                        integration.set_refresh_token(token_result["refresh_token"])
                    # _compute_jwt_expires_in always returns > 0 — unconditionally stamp
                    # token_expires_at so a stale past value never survives a reconnect.
                    integration.token_expires_at = datetime.utcnow() + timedelta(
                        seconds=token_result["expires_in"]
                    )
                    integration.status = IntegrationStatus.CONNECTED
                    integration.last_error = None
                else:
                    integration.status = IntegrationStatus.ERROR
                    integration.last_error = token_result.get("error", "Failed to obtain JWT token")
            else:
                integration.status = IntegrationStatus.ERROR
                integration.last_error = f"Unsupported auth method: {auth_method}"

        elif auth_type == "default":
            from botelier.services.integration_runtime.adapters import DEFAULT_ADAPTER

            auth_config = integration_type.get_auth_config() or {}
            connect_result = await DEFAULT_ADAPTER.connect(auth_input, auth_config)
            if connect_result.success:
                if connect_result.access_token:
                    integration.set_access_token(connect_result.access_token)
                    if connect_result.refresh_token:
                        integration.set_refresh_token(connect_result.refresh_token)
                    if connect_result.expires_in:
                        integration.token_expires_at = datetime.utcnow() + timedelta(
                            seconds=connect_result.expires_in
                        )
                integration.status = IntegrationStatus.CONNECTED
                integration.last_error = None
                logger.info(
                    f"Credential update reconnected integration {integration_type.slug} for account {account_id}"
                )
            else:
                integration.status = IntegrationStatus.ERROR
                integration.last_error = connect_result.error or "Connection failed"
                logger.error(
                    f"Credential update failed for {integration_type.slug}: {integration.last_error}"
                )

        else:
            integration.status = IntegrationStatus.ERROR
            integration.last_error = f"Unsupported auth type: {auth_type}"

        db.commit()

    except Exception as e:
        logger.error(f"Error updating integration credentials: {e}")
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
        last_error=integration.last_error,
        property_id=str(integration.property_id) if integration.property_id else None,
    )


class UpdateIntegrationPropertyRequest(BaseModel):
    property_id: Optional[str] = None


@router.patch(
    "/account/{account_id}/integration/{integration_id}/property",
    response_model=AccountIntegrationResponse,
)
async def update_integration_property(
    account_id: str,
    integration_id: str,
    request: UpdateIntegrationPropertyRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bind an integration connection to a property (or null for account-global).

    Per-property data isolation: this is the operator-facing way to scope a
    certified integration connection to a single property. ``IntegrationClient``
    then fails closed on any cross-property use at runtime.
    """
    _assert_account_access(current_user, account_id, db, permission="integrations.manage")
    integration = (
        db.query(AccountIntegration)
        .filter(
            AccountIntegration.id == integration_id,
            AccountIntegration.account_id == account_id,
        )
        .first()
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    if request.property_id is not None and not property_belongs_to_account(
        db, account_id, request.property_id
    ):
        raise HTTPException(status_code=400, detail="Property not found for this account")

    integration.property_id = request.property_id
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
        last_error=integration.last_error,
        property_id=str(integration.property_id) if integration.property_id else None,
    )


@router.post(
    "/account/{account_id}/integration/{integration_id}/test", response_model=TestConnectionResponse
)
async def test_integration_connection(
    account_id: str,
    integration_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_account_access(current_user, account_id, db, permission="integrations.manage")
    integration = (
        db.query(AccountIntegration)
        .filter(
            AccountIntegration.id == integration_id, AccountIntegration.account_id == account_id
        )
        .first()
    )

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
                    # Mark the DB so the UI badge reflects reality immediately.
                    integration.status = IntegrationStatus.TOKEN_EXPIRED
                    integration.last_error = (
                        "Session expired — please reconnect via the Edit button. "
                        f"Detail: {refresh_result.get('error', 'unknown')}"
                    )
                    db.add(integration)
                    db.commit()
                    return TestConnectionResponse(
                        success=False,
                        message=(
                            "Session expired — please reconnect by clicking the "
                            "Edit (pencil) button on this connection."
                        ),
                        details={"error": refresh_result.get("error")},
                    )
                _persist_refreshed_tokens(integration, refresh_result)
                db.commit()

            test_result = await test_api_connection(integration_type, integration, credentials)

            # One-shot forced refresh + retry on 401/403, mirroring the live
            # runtime: a stored token can be revoked provider-side long before
            # our local expiry clock says so.
            if (
                not test_result.get("success")
                and (test_result.get("details") or {}).get("status_code") in (401, 403)
            ):
                refresh_result = await refresh_oauth_token(integration_type, integration)
                if refresh_result.get("success"):
                    _persist_refreshed_tokens(integration, refresh_result)
                    db.commit()
                    test_result = await test_api_connection(
                        integration_type, integration, credentials
                    )
                else:
                    # Provider-side revocation confirmed — stamp the status.
                    integration.status = IntegrationStatus.TOKEN_EXPIRED
                    integration.last_error = (
                        "Provider rejected token — please reconnect via the Edit button. "
                        f"Detail: {refresh_result.get('error', 'unknown')}"
                    )
                    db.add(integration)
                    db.commit()
                    return TestConnectionResponse(
                        success=False,
                        message=(
                            "Provider rejected the credential — please reconnect by "
                            "clicking the Edit (pencil) button on this connection."
                        ),
                        details={"error": refresh_result.get("error")},
                    )

        return TestConnectionResponse(
            success=test_result.get("success", False),
            message=test_result.get("message", "Unknown result"),
            details=test_result.get("details"),
        )

    except Exception as e:
        logger.error(f"Error testing integration: {e}")
        return TestConnectionResponse(success=False, message=f"Connection test failed: {str(e)}")


@router.delete("/account/{account_id}/integration/{integration_id}")
async def disconnect_integration(
    account_id: str,
    integration_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_account_access(current_user, account_id, db, permission="integrations.manage")
    integration = (
        db.query(AccountIntegration)
        .filter(
            AccountIntegration.id == integration_id, AccountIntegration.account_id == account_id
        )
        .first()
    )

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

    logger.info(
        f"Disconnected integration {integration.integration_type.slug} for account {account_id}"
    )

    return {"status": "disconnected"}


@router.delete("/account/{account_id}/integration/{integration_id}/permanent")
async def delete_integration(
    account_id: str,
    integration_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_account_access(current_user, account_id, db, permission="integrations.manage")
    integration = (
        db.query(AccountIntegration)
        .filter(
            AccountIntegration.id == integration_id, AccountIntegration.account_id == account_id
        )
        .first()
    )

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    slug = integration.integration_type.slug
    db.delete(integration)
    db.commit()

    logger.info(
        f"Deleted integration {slug} ({integration_id}) for account {account_id}"
    )

    return {"status": "deleted"}


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


@router.get(
    "/account/{account_id}/integration/{integration_id}/call-logs",
    response_model=List[CallLogEntry],
)
async def get_integration_call_logs(
    account_id: str,
    integration_id: str,
    limit: int = 20,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Detailed call-log payloads include outbound URLs, request/response
    # bodies and upstream error messages — gate behind integrations.manage
    # so read-only users (viewer / staff) cannot harvest secrets that
    # leaked into a 4xx/5xx response body. (Task #144)
    _assert_account_access(current_user, account_id, db, permission="integrations.manage")
    integration = (
        db.query(AccountIntegration)
        .filter(
            AccountIntegration.id == integration_id, AccountIntegration.account_id == account_id
        )
        .first()
    )

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
    _assert_account_access(current_user, account_id, db)
    integration = (
        db.query(AccountIntegration)
        .filter(
            AccountIntegration.id == integration_id, AccountIntegration.account_id == account_id
        )
        .first()
    )

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    from sqlalchemy import func as sqlfunc

    row = (
        db.query(
            sqlfunc.count(IntegrationCallLog.id).label("total"),
            sqlfunc.sum(sqlfunc.cast(IntegrationCallLog.success, Integer)).label("successes"),
            sqlfunc.max(IntegrationCallLog.called_at).label("last_called_at"),
        )
        .filter(
            IntegrationCallLog.account_id == account_id,
            IntegrationCallLog.integration_id == integration_id,
        )
        .one()
    )

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


@router.get("/account/{account_id}/api-logs")
async def get_account_api_logs(
    account_id: str,
    success: Optional[bool] = None,
    channel: Optional[str] = None,
    integration_id: Optional[str] = None,
    action_id: Optional[str] = None,
    flow_tool_id: Optional[str] = None,
    node_id: Optional[str] = None,
    call_sid: Optional[str] = None,
    request_id: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    page: int = 1,
    per_page: int = 50,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Account-level API invocation monitor.

    Returns metadata only. Request headers, bodies, response bodies, and secret
    values are intentionally not persisted or returned.
    """
    _assert_account_access(current_user, account_id, db, permission="integrations.manage")
    page = max(page, 1)
    per_page = min(max(per_page, 1), 100)

    query = db.query(IntegrationActionInvocation).filter(
        IntegrationActionInvocation.account_id == account_id
    )
    if success is not None:
        query = query.filter(IntegrationActionInvocation.success == success)
    if channel:
        query = query.filter(IntegrationActionInvocation.channel == channel)
    if integration_id:
        query = query.filter(IntegrationActionInvocation.integration_id == integration_id)
    if action_id:
        query = query.filter(IntegrationActionInvocation.action_id == action_id)
    if flow_tool_id:
        query = query.filter(IntegrationActionInvocation.flow_tool_id == flow_tool_id)
    if node_id:
        query = query.filter(IntegrationActionInvocation.node_id == node_id)
    if call_sid:
        query = query.filter(IntegrationActionInvocation.call_sid == call_sid)
    if request_id:
        query = query.filter(IntegrationActionInvocation.request_id == request_id)
    if from_date:
        query = query.filter(IntegrationActionInvocation.called_at >= from_date)
    if to_date:
        query = query.filter(IntegrationActionInvocation.called_at <= to_date)

    total = query.count()
    summary_row = query.with_entities(
        sqlfunc.count(IntegrationActionInvocation.id).label("total"),
        sqlfunc.sum(sqlfunc.cast(IntegrationActionInvocation.success, Integer)).label("successes"),
        sqlfunc.avg(IntegrationActionInvocation.latency_ms).label("avg_latency_ms"),
        sqlfunc.max(IntegrationActionInvocation.called_at).label("last_called_at"),
    ).one()
    last_failed = (
        query.filter(IntegrationActionInvocation.success == False)  # noqa: E712
        .order_by(IntegrationActionInvocation.called_at.desc())
        .first()
    )

    rows = (
        query.order_by(
            IntegrationActionInvocation.called_at.desc(),
            IntegrationActionInvocation.id.desc(),
        )
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    action_ids = {row.action_id for row in rows if row.action_id}
    integration_ids = {row.integration_id for row in rows if row.integration_id}
    actions = {
        action.id: action
        for action in db.query(IntegrationAction).filter(IntegrationAction.id.in_(action_ids)).all()
    } if action_ids else {}
    integrations = {
        integration.id: integration
        for integration in db.query(AccountIntegration)
        .filter(AccountIntegration.id.in_(integration_ids))
        .all()
    } if integration_ids else {}

    def source_label(row: IntegrationActionInvocation) -> str:
        if row.source_label:
            return row.source_label
        if row.action_id in actions:
            return actions[row.action_id].name
        if row.integration_id in integrations:
            integration = integrations[row.integration_id]
            return integration.connection_name or integration.integration_type.name
        return "Custom API"

    successes = int(summary_row.successes or 0)
    return {
        "items": [
            {
                "id": str(row.id),
                "source_label": source_label(row),
                "channel": row.channel,
                "method": row.method,
                "endpoint_called": row.endpoint_called,
                "status_code": row.status_code,
                "success": row.success,
                "latency_ms": row.latency_ms,
                "error_type": row.error_type,
                "error_message": row.error_message,
                "request_id": row.request_id,
                "call_sid": row.call_sid,
                "tool_id": row.tool_id,
                "flow_tool_id": str(row.flow_tool_id) if row.flow_tool_id else None,
                "node_id": row.node_id,
                "action_id": str(row.action_id) if row.action_id else None,
                "integration_id": str(row.integration_id) if row.integration_id else None,
                "response_metadata": row.response_metadata or {},
                "called_at": row.called_at.isoformat() if row.called_at else None,
            }
            for row in rows
        ],
        "page": page,
        "per_page": per_page,
        "total": total,
        "summary": {
            "total": int(summary_row.total or 0),
            "successful": successes,
            "failed": int(summary_row.total or 0) - successes,
            "avg_latency_ms": round(float(summary_row.avg_latency_ms or 0), 1),
            "last_called_at": summary_row.last_called_at.isoformat()
            if summary_row.last_called_at
            else None,
            "last_error": last_failed.error_message if last_failed else None,
        },
    }


# ── 3-legged OAuth2 (authorization_code) connect flow (Task #331) ─────────────


class OAuthAuthorizeRequest(BaseModel):
    integration_type_id: str
    credentials: dict
    connection_name: Optional[str] = None
    property_id: Optional[str] = None


def _oauth_redirect_uri() -> str:
    """The redirect_uri the provider calls back to after user consent.

    This is always the *API host* path — the value that must be pre-registered
    with every OAuth provider.  It must be identical on both the authorize
    request and the token exchange (the OAuth2 spec requires it).

    The ``/oauth/callback`` endpoint is a stateless hop that immediately 302s to
    ``/oauth/complete`` on the *dashboard* origin (see two-hop design below).
    Only ``/oauth/callback`` is the registered URI; ``/oauth/complete`` never
    appears in provider configuration.
    """
    return f"{get_public_base_url()}/api/integrations/oauth/callback"


def _dashboard_integrations_url() -> str:
    """URL of the integrations page on the dashboard (frontend) host."""
    return f"{get_frontend_url()}/dashboard/integrations"


def _build_authorization_url(
    auth_config: dict, credentials: dict, redirect_uri: str, state: str
) -> str:
    authorize_url = (auth_config.get("authorization_endpoint") or "").strip()
    if not authorize_url:
        raise HTTPException(
            status_code=400,
            detail="Integration type has no authorization_endpoint configured",
        )
    params = {
        "response_type": "code",
        "client_id": credentials.get("client_id"),
        "redirect_uri": redirect_uri,
        "state": state,
    }
    scope = credentials.get("scope") or auth_config.get("scope")
    if scope:
        params["scope"] = scope
    # Allow seeds to declare provider-specific extra params (e.g. Google's
    # access_type=offline&prompt=consent to force a refresh token).
    extra = auth_config.get("extra_authorize_params", {})
    if isinstance(extra, dict):
        params.update(extra)
    separator = "&" if "?" in authorize_url else "?"
    return f"{authorize_url}{separator}{urlencode(params)}"


async def exchange_authorization_code(
    integration_type: IntegrationType, credentials: dict, code: str, redirect_uri: str
) -> dict:
    """Exchange an authorization code for access + refresh tokens."""
    auth_config = integration_type.get_auth_config()
    token_url = resolve_token_endpoint(auth_config)
    client_id = credentials.get("client_id")
    client_secret = credentials.get("client_secret")

    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if client_id:
        form["client_id"] = client_id
    # Confidential clients use HTTP Basic; public clients send only client_id.
    basic_auth = (client_id, client_secret) if client_secret else None

    try:
        async with httpx.AsyncClient(transport=SSRFSafeTransport()) as client:
            response = await client.post(
                token_url,
                data=form,
                auth=basic_auth,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                timeout=30.0,
            )
    except Exception as exc:
        logger.error(f"OAuth2 code exchange network error: {exc}")
        return {"success": False, "error": str(exc)}

    if response.status_code == 200:
        token_data = response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return {"success": False, "error": "Token response missing access_token"}
        return {
            "success": True,
            "access_token": access_token,
            "refresh_token": token_data.get("refresh_token"),
            "expires_in": token_data.get("expires_in", 3600),
        }
    logger.error(
        f"OAuth2 code exchange failed: {response.status_code} - {response.text[:300]}"
    )
    return {
        "success": False,
        "error": f"Token exchange failed: {response.status_code}",
    }


@router.post("/account/{account_id}/oauth/authorize")
async def start_oauth_authorization(
    account_id: str,
    request: OAuthAuthorizeRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Begin a 3-legged OAuth2 connection: create the (CONNECTING) integration
    and return the provider consent URL the operator's browser must visit.

    The encrypted credentials (client_id/secret/scope) are persisted now; the
    access/refresh tokens are stored later by the authenticated POST /oauth/complete
    endpoint after the user grants consent.  A random CSRF nonce is stashed in
    connection_config and encoded into the OAuth ``state`` so the completion
    endpoint can bind the response back to this exact pending integration.

    State format (3 colon-separated segments):
        {account_id}:{integration_id}:{nonce}

    where nonce = secrets.token_urlsafe(24) and account_id / integration_id are
    UUIDs (no colons).  No user-controlled data rides in state.
    """
    _assert_account_access(current_user, account_id, db, permission="integrations.manage")

    integration_type = (
        db.query(IntegrationType)
        .filter(IntegrationType.id == request.integration_type_id)
        .first()
    )
    if not integration_type:
        raise HTTPException(status_code=404, detail="Integration type not found")
    if integration_type.auth_type != "oauth2_authorization_code":
        raise HTTPException(
            status_code=400,
            detail="Integration type does not use authorization_code OAuth2",
        )
    if not request.credentials.get("client_id"):
        raise HTTPException(status_code=400, detail="Missing client_id")

    if request.property_id is not None and not property_belongs_to_account(
        db, account_id, request.property_id
    ):
        raise HTTPException(status_code=400, detail="Property not found for this account")

    auth_config = integration_type.get_auth_config()

    integration = AccountIntegration(
        account_id=account_id,
        property_id=request.property_id,
        integration_type_id=request.integration_type_id,
        connection_name=request.connection_name or integration_type.name,
        status=IntegrationStatus.CONNECTING,
    )
    cred_part, conn_config_part = _split_fields_by_storage(
        integration_type, request.credentials
    )
    integration.set_credentials(cred_part)

    nonce = secrets.token_urlsafe(24)
    conn_config = conn_config_part or {}
    conn_config[_OAUTH_STATE_NONCE_KEY] = nonce
    integration.set_connection_config(conn_config)

    db.add(integration)
    db.commit()

    state = f"{account_id}:{integration.id}:{nonce}"
    redirect_uri = _oauth_redirect_uri()
    authorization_url = _build_authorization_url(
        auth_config, request.credentials, redirect_uri, state
    )

    logger.info(
        f"Started OAuth2 authorization for integration {integration.id} "
        f"({integration_type.slug}) account {account_id}"
    )

    return {"integration_id": str(integration.id), "authorization_url": authorization_url}


# ── OAuth2 callback design ─────────────────────────────────────────────────────
#
# Registered redirect_uri: {PUBLIC_BASE_URL}/api/integrations/oauth/callback
#
# The provider redirects the browser here after consent.  This endpoint is a
# stateless hop — it immediately 302s to the dashboard's /oauth/complete page
# (a Next.js route rendered inside the authenticated dashboard shell) so that
# the user's session cookie is present.  The frontend page then POSTs the code
# and state to the authenticated backend POST /api/integrations/oauth/complete.
#
# Trusted hop target: get_frontend_url()
# ──────────────────────────────────────
# The dashboard origin comes ONLY from server configuration (FRONTEND_URL env
# or get_public_base_url() fallback) — never from request headers, OAuth state,
# or any user-controlled input.  This prevents code-leak / open-redirect.
#
# Security model
# ──────────────
# No cookie is needed.  The completion endpoint requires a valid Bearer token
# (get_current_user), so only a user authenticated to the same account can
# complete the exchange.  A forwarded callback link fails unless the recipient
# is logged into the same Botelier account.


@router.get("/oauth/callback")
async def oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Stateless hop — registered OAuth2 redirect_uri.

    Immediately 302s to the dashboard's /oauth/complete page, forwarding all
    provider-supplied parameters.  The hop target is fixed from server
    configuration (FRONTEND_URL / get_public_base_url()) — nothing from the
    request influences the redirect destination.
    """
    completion_page = f"{get_frontend_url()}/dashboard/integrations/oauth/complete"

    params: dict = {}
    if code:
        params["code"] = code
    if state:
        params["state"] = state
    if error:
        params["error"] = error

    query = urlencode(params) if params else ""
    target = f"{completion_page}?{query}" if query else completion_page

    logger.info(
        f"OAuth hop → {completion_page} "
        f"(code={'yes' if code else 'no'}, error={error!r})"
    )
    return RedirectResponse(url=target, status_code=302)


class OAuthCompleteRequest(BaseModel):
    code: Optional[str] = None
    state: Optional[str] = None
    error: Optional[str] = None


async def _fetch_email_sender_email(slug: str, access_token: str) -> Optional[str]:
    """Fetch the authenticated user's email address from the provider after OAuth.

    Called inline inside oauth_complete for email-sender-* slugs.  Defined here
    (not in email_senders.py) to avoid a circular import — email_senders.py
    imports helpers from this module.
    """
    _USERINFO: dict = {
        "email-sender-gmail": (
            "https://www.googleapis.com/oauth2/v2/userinfo",
            "email",
            None,
        ),
        "email-sender-microsoft": (
            "https://graph.microsoft.com/v1.0/me",
            "mail",
            "userPrincipalName",
        ),
    }
    if slug not in _USERINFO:
        return None
    url, field, fallback = _USERINFO[slug]
    try:
        async with httpx.AsyncClient(
            transport=SSRFSafeTransport(), timeout=10.0
        ) as client:
            resp = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )
        if resp.status_code == 200:
            data = resp.json()
            return data.get(field) or (data.get(fallback) if fallback else None)
    except Exception as exc:
        logger.warning(f"[_fetch_email_sender_email] {slug}: {exc}")
    return None


@router.post("/oauth/complete")
async def oauth_complete(
    request: OAuthCompleteRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Authenticated OAuth2 completion — called by the frontend after the provider hop.

    The dashboard page at /dashboard/integrations/oauth/complete forwards the
    code and state here via an authenticated POST (Bearer token).  Requiring
    authentication means only the user who initiated the flow (or another user
    in the same account) can complete it — a forwarded link is harmless without
    a valid session.

    Security layers (enforced in this order — no exceptions)
    ---------------
    1. Bearer authentication (get_current_user) — unauthenticated callers get 401.
    2. State parse + UUID validation — malformed state is rejected before any DB access.
    3. Account binding — account_id in state must be an account the caller has
       integrations.manage on.  Checked before touching the integration row, so a
       caller from a different account cannot read, mutate, or burn the nonce of
       another account's pending integration even by supplying error= or a bad code.
    4. Integration ownership — integration_id must belong to the state's account_id.
    5. One-time CSRF nonce — constant-time compare, consumed before any commit.
    6. Provider error / missing code / code exchange — only reachable after all
       checks above pass.
    """
    def _fail(reason: str, http_status: int = 400) -> HTTPException:
        return HTTPException(status_code=http_status, detail=reason)

    # ── 1. Parse and validate state ───────────────────────────────────────────
    if not request.state or request.state.count(":") < 2:
        raise _fail("invalid_state")

    parts = request.state.split(":", 2)
    account_id_from_state = parts[0]
    integration_id = parts[1]
    nonce = parts[2]

    try:
        UUID(account_id_from_state)
        UUID(integration_id)
    except (ValueError, TypeError):
        raise _fail("invalid_state")

    # ── 2. Account access (authenticated) ────────────────────────────────────
    # Raises 403 if current_user has no integrations.manage permission on
    # account_id_from_state — covers mismatched-account and hostile callers.
    # This runs BEFORE loading the integration row so that a caller from a
    # different account cannot enumerate, mutate, or burn the nonce of another
    # account's pending integration by supplying error= or a fabricated state.
    try:
        _assert_account_access(
            current_user, account_id_from_state, db, permission="integrations.manage"
        )
    except HTTPException:
        raise _fail("account_mismatch", http_status=403)

    # ── 3. Load the pending integration ──────────────────────────────────────
    integration = (
        db.query(AccountIntegration)
        .options(joinedload(AccountIntegration.integration_type))
        .filter(AccountIntegration.id == integration_id)
        .first()
    )
    if not integration:
        raise _fail("invalid_state")

    # Defend against a state value crafted to target an integration that
    # belongs to a different account than the one in state (e.g., caller has
    # integrations.manage on two accounts and crafts a cross-account state).
    if str(integration.account_id) != account_id_from_state:
        raise _fail("invalid_state")

    # ── 4. One-time CSRF nonce ────────────────────────────────────────────────
    conn_config = integration.get_connection_config() or {}
    expected_nonce = conn_config.get(_OAUTH_STATE_NONCE_KEY)
    if not expected_nonce or not nonce or not secrets.compare_digest(
        str(expected_nonce), str(nonce)
    ):
        raise _fail("invalid_state")

    # Consume the nonce before any DB commit — even if the steps below fail,
    # the state cannot be replayed.
    conn_config.pop(_OAUTH_STATE_NONCE_KEY, None)

    # ── 5. Provider-reported error ────────────────────────────────────────────
    # Only reached after all security checks have passed, so the caller is
    # authorised to mutate this integration row.
    if request.error:
        integration.status = IntegrationStatus.ERROR
        integration.last_error = f"Authorization denied: {request.error}"[:500]
        integration.set_connection_config(conn_config)
        db.commit()
        raise _fail(f"access_denied: {request.error}")

    # ── 6. Require code ───────────────────────────────────────────────────────
    if not request.code:
        integration.status = IntegrationStatus.ERROR
        integration.last_error = "Authorization callback missing code"
        integration.set_connection_config(conn_config)
        db.commit()
        raise _fail("missing_code")

    # ── 7. Exchange code for tokens ───────────────────────────────────────────
    credentials = integration.get_credentials()
    # redirect_uri must match exactly what was sent during authorization.
    redirect_uri = _oauth_redirect_uri()
    result = await exchange_authorization_code(
        integration.integration_type, credentials, request.code, redirect_uri
    )

    if result.get("success"):
        integration.set_access_token(result["access_token"])
        if result.get("refresh_token"):
            integration.set_refresh_token(result["refresh_token"])
        integration.token_expires_at = datetime.utcnow() + timedelta(
            seconds=result.get("expires_in", 3600)
        )
        integration.status = IntegrationStatus.CONNECTED
        integration.connected_at = datetime.utcnow()
        integration.last_error = None

        # For email sender connections, fetch and cache the authenticated email
        # address so the Settings > Email tab can show it without an extra call.
        _it_slug = integration.integration_type.slug if integration.integration_type else ""
        if _it_slug.startswith("email-sender-"):
            try:
                _sender_email = await _fetch_email_sender_email(
                    _it_slug, result["access_token"]
                )
                if _sender_email:
                    conn_config["email"] = _sender_email
                    # Auto-name the connection with the actual email address
                    # (overrides the generic "Gmail Sender" / "Microsoft Sender"
                    # placeholder set at connect-start time).
                    integration.connection_name = _sender_email
            except Exception as _exc:
                logger.warning(
                    f"[oauth_complete] Could not fetch sender email for "
                    f"{integration.id}: {_exc}"
                )

        integration.set_connection_config(conn_config)
        db.commit()
        slug = _it_slug
        logger.info(f"Completed OAuth2 connection for integration {integration.id}")
        return {
            "status": "connected",
            "integration_id": str(integration.id),
            "integration_slug": slug,
            "integration_name": integration.connection_name,
        }

    integration.status = IntegrationStatus.ERROR
    integration.last_error = result.get("error", "Token exchange failed")[:500]
    integration.set_connection_config(conn_config)
    db.commit()
    raise _fail("token_exchange_failed")


async def obtain_oauth_token(integration_type: IntegrationType, credentials: dict) -> dict:
    auth_config = integration_type.get_auth_config()

    gateway_url = credentials.get("gateway_url", "").rstrip("/")
    client_id = credentials.get("client_id")
    client_secret = credentials.get("client_secret")
    enterprise_id = credentials.get("enterprise_id")
    # OHIP sandbox does not issue a separate app_key — the client_id doubles as
    # the x-app-key header. Production accounts may supply a distinct app_key;
    # use it when present, otherwise fall back to client_id.
    app_key = credentials.get("app_key") or client_id

    if not all([gateway_url, client_id, client_secret, enterprise_id]):
        return {"success": False, "error": "Missing required credentials"}

    try:
        _validate_opera_gateway_url(gateway_url)
    except HTTPException as exc:
        return {"success": False, "error": exc.detail}

    token_url = f"{gateway_url}{auth_config.get('token_endpoint_path', '/oauth/v1/tokens')}"

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "x-app-key": app_key,
        "enterpriseId": enterprise_id,
    }

    data = {
        "grant_type": "client_credentials",
        "scope": auth_config.get("scope", "urn:opc:hgbu:ws:__myscopes__"),
    }

    masked_app_key = f"...{app_key[-4:]}" if app_key and len(app_key) > 4 else "***"
    logger.debug(
        f"OHIP token request → {token_url} | x-app-key={masked_app_key} | "
        f"enterpriseId={enterprise_id} | scope={data['scope']}"
    )

    try:
        async with httpx.AsyncClient(transport=SSRFSafeTransport()) as client:
            response = await client.post(
                token_url, headers=headers, data=data, auth=(client_id, client_secret), timeout=30.0
            )

            if response.status_code == 200:
                token_data = response.json()
                return {
                    "success": True,
                    "access_token": token_data.get("access_token"),
                    "refresh_token": token_data.get("refresh_token"),
                    "expires_in": token_data.get("expires_in", 3600),
                }
            else:
                body_snippet = (response.text or "")[:200]
                logger.error(
                    f"OHIP token request failed: {response.status_code} - {body_snippet} "
                    f"(url={token_url}, x-app-key={masked_app_key}, x-enterpriseid={enterprise_id})"
                )
                return {
                    "success": False,
                    "error": f"Token request failed: {response.status_code} - {body_snippet}",
                }

    except Exception as e:
        logger.error(f"OHIP token request exception: {e}")
        return {"success": False, "error": str(e)}


def _compute_jwt_expires_in(token_data: dict, max_lifetime_hours: int) -> int:
    """Return the number of seconds until the JWT expires.

    Always returns a positive integer — callers can unconditionally store it.
    Priority: provider's ``expired_time`` datetime string > provider's
    ``expires_in`` seconds > configured ``max_lifetime_hours`` default.
    """
    expired_time_str = token_data.get("expired_time")
    if expired_time_str:
        try:
            expired_dt = datetime.strptime(expired_time_str, "%Y-%m-%d %H:%M:%S")
            seconds_remaining = int((expired_dt - datetime.utcnow()).total_seconds())
            if seconds_remaining > 0:
                return seconds_remaining
        except (ValueError, TypeError):
            pass
    explicit = token_data.get("expires_in")
    if explicit and int(explicit) > 0:
        return int(explicit)
    # Absolute fallback — provider gave no usable expiry hint.
    return max_lifetime_hours * 3600


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

    try:
        auth_query_params = build_auth_request_query_params(auth_config, credentials)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    expired_time = (datetime.utcnow() + timedelta(hours=max_lifetime_hours)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    try:
        async with httpx.AsyncClient(transport=SSRFSafeTransport()) as client:
            response = await client.post(
                login_url,
                params=auth_query_params or None,
                json={"username": username, "password": password, "expired_time": expired_time},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=30.0,
            )

            if response.status_code == 200:
                token_data = response.json()
                expires_in = _compute_jwt_expires_in(token_data, max_lifetime_hours)
                return {
                    "success": True,
                    "access_token": token_data.get("token") or token_data.get("access_token"),
                    "refresh_token": token_data.get("refresh_token"),
                    "expires_in": expires_in,
                }
            else:
                body_snippet = (response.text or "")[:200]
                logger.error(f"JWT login request failed: {response.status_code} - {body_snippet}")
                return {
                    "success": False,
                    "error": f"JWT login failed: {response.status_code} - {body_snippet}",
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
        return {
            "success": False,
            "error": "Missing required credentials (username, password, apikey)",
        }

    test_url = f"{base_url}/hotels"
    basic_token = base64.b64encode(f"{username}:{password}".encode()).decode()

    headers = {
        "Authorization": f"Basic {basic_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    params = {"apikey": apikey}
    if hotel_id:
        params["hotelId"] = hotel_id

    try:
        async with httpx.AsyncClient(transport=SSRFSafeTransport()) as client:
            response = await client.get(test_url, headers=headers, params=params, timeout=30.0)

            if response.status_code == 200:
                return {"success": True}
            elif response.status_code == 401:
                return {"success": False, "error": "Invalid credentials"}
            else:
                return {
                    "success": False,
                    "error": f"Validation request failed: {response.status_code} - {response.text[:500]}",
                }

    except Exception as e:
        logger.error(f"Basic auth validation exception: {e}")
        return {"success": False, "error": str(e)}


def _persist_refreshed_tokens(integration: AccountIntegration, refresh_result: dict) -> None:
    """Store tokens returned by refresh_oauth_token on the integration.

    The refresh-token grant path persists tokens itself and returns only
    {"success": True}; the fallback paths (fresh client_credentials or JWT
    login) return the raw token payload without persisting — this bridges
    that gap. Caller commits.
    """
    if refresh_result.get("access_token"):
        integration.set_access_token(refresh_result["access_token"])
        if refresh_result.get("refresh_token"):
            integration.set_refresh_token(refresh_result["refresh_token"])
        # _compute_jwt_expires_in always returns > 0; unconditionally stamp
        # token_expires_at so a zero/missing value never leaves a stale past
        # timestamp that would make is_token_expired() fire immediately.
        if refresh_result.get("expires_in"):
            integration.token_expires_at = datetime.utcnow() + timedelta(
                seconds=refresh_result["expires_in"]
            )


async def refresh_oauth_token(
    integration_type: IntegrationType, integration: AccountIntegration
) -> dict:
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
        expired_time = (datetime.utcnow() + timedelta(hours=max_lifetime_hours)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        try:
            auth_query_params = build_auth_request_query_params(auth_config, credentials)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        if refresh_token:
            try:
                async with httpx.AsyncClient(transport=SSRFSafeTransport()) as client:
                    response = await client.post(
                        f"{base_url}{refresh_endpoint}",
                        params=auth_query_params or None,
                        json={"refresh_token": refresh_token, "expired_time": expired_time},
                        headers={"Content-Type": "application/json", "Accept": "application/json"},
                        timeout=30.0,
                    )

                    if response.status_code == 200:
                        token_data = response.json()
                        integration.set_access_token(
                            token_data.get("token") or token_data.get("access_token")
                        )
                        if token_data.get("refresh_token"):
                            integration.set_refresh_token(token_data["refresh_token"])
                        expires_in = _compute_jwt_expires_in(token_data, max_lifetime_hours)
                        integration.token_expires_at = datetime.utcnow() + timedelta(
                            seconds=expires_in
                        )
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
    # OHIP sandbox uses client_id as app_key; prefer explicit app_key if supplied.
    app_key = credentials.get("app_key") or client_id

    try:
        _validate_opera_gateway_url(gateway_url)
    except HTTPException as exc:
        return {"success": False, "error": exc.detail}

    token_url = f"{gateway_url}{auth_config.get('token_endpoint_path', '/oauth/v1/tokens')}"

    headers = {"Content-Type": "application/x-www-form-urlencoded", "x-app-key": app_key}

    enterprise_id = credentials.get("enterprise_id")
    headers["enterpriseId"] = enterprise_id
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    try:
        async with httpx.AsyncClient(transport=SSRFSafeTransport()) as client:
            response = await client.post(
                token_url, headers=headers, data=data, auth=(client_id, client_secret), timeout=30.0
            )

            if response.status_code == 200:
                token_data = response.json()
                integration.set_access_token(token_data.get("access_token"))
                if token_data.get("refresh_token"):
                    integration.set_refresh_token(token_data["refresh_token"])
                if token_data.get("expires_in"):
                    integration.token_expires_at = datetime.utcnow() + timedelta(
                        seconds=token_data["expires_in"]
                    )
                return {"success": True}
            else:
                return await obtain_oauth_token(integration_type, credentials)

    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
        return await obtain_oauth_token(integration_type, credentials)


async def test_api_connection(
    integration_type: IntegrationType, integration: AccountIntegration, credentials: dict
) -> dict:
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
            "Accept": "application/json",
        }
        params = {"apikey": apikey} if apikey else {}
        hotel_id = credentials.get("hotelId")
        if hotel_id:
            params["hotelId"] = hotel_id

        try:
            async with httpx.AsyncClient(transport=SSRFSafeTransport()) as client:
                response = await client.get(test_url, headers=headers, params=params, timeout=30.0)

                if response.status_code == 200:
                    return {
                        "success": True,
                        "message": "Connection successful",
                        "details": {"status_code": 200},
                    }
                else:
                    return {
                        "success": False,
                        "message": f"API returned {response.status_code}",
                        # status_code must be present for the 401/403 forced-retry
                        # block in test_integration_connection to fire.
                        "details": {
                            "status_code": response.status_code,
                            "response": response.text[:500],
                        },
                    }
        except Exception as e:
            return {"success": False, "message": f"Connection failed: {str(e)}"}

    gateway_url = credentials.get("gateway_url", "").rstrip("/")
    hotel_id = credentials.get("hotel_id")
    # Same fallback as token acquisition: explicit app_key, else client_id.
    app_key = credentials.get("app_key") or credentials.get("client_id")
    access_token = integration.get_access_token()

    if not all([gateway_url, hotel_id, app_key, access_token]):
        return {"success": False, "message": "Missing required credentials or token"}

    try:
        _validate_opera_gateway_url(gateway_url)
    except HTTPException as exc:
        return {"success": False, "message": exc.detail}

    # Health-check against an endpoint the integration actually uses in flows
    # (seeded get_room_types). The previous fof/v1 path belongs to a module many
    # OHIP app subscriptions don't include, causing false-negative 401s.
    test_url = f"{gateway_url}/lov/v1/listOfValues/hotels/{hotel_id}/roomTypes"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-app-key": app_key,
        "x-hotelid": hotel_id,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(transport=SSRFSafeTransport()) as client:
            response = await client.get(test_url, headers=headers, timeout=30.0)

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "Connection successful",
                    "details": {"hotel_id": hotel_id, "status_code": 200},
                }
            else:
                return {
                    "success": False,
                    "message": f"API returned {response.status_code}",
                    "details": {
                        "response": response.text[:500],
                        "status_code": response.status_code,
                    },
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
        "Accept": "application/json",
    }

    params = {"apikey": apikey}
    if hotel_id:
        params["hotelId"] = hotel_id

    try:
        async with httpx.AsyncClient(transport=SSRFSafeTransport()) as client:
            response = await client.get(test_url, headers=headers, params=params, timeout=30.0)

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "Connection successful",
                    "details": {"status_code": 200},
                }
            else:
                return {
                    "success": False,
                    "message": f"API returned {response.status_code}",
                    "details": {"response": response.text[:500]},
                }

    except Exception as e:
        return {"success": False, "message": f"Connection failed: {str(e)}"}
