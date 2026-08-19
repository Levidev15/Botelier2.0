"""Parity snapshot tests pinning the exact outgoing HTTP request shape.

These are the NO-BEHAVIOR-CHANGE gate for the ``integration_client`` refactor
(Task #326). They capture — via ``httpx.MockTransport`` — the method, full URL
(including query params), headers, and body the client produces for:

  • Opera (oauth2_client_credentials) data requests
  • GuestCentric (basic_or_jwt) data requests, BOTH basic_auth and jwt
  • the token-refresh request shapes: OAuth token, JWT login, JWT refresh

They intercept at ``httpx.AsyncClient`` (module level), so they stay valid
regardless of which module the request/refresh code physically lives in after
the runtime is split into an ``integration_runtime`` package + adapters.
"""

import base64
import json
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.fernet import Fernet

from botelier import crypto
from botelier.models.integration import (
    AccountIntegration,
    IntegrationStatus,
    IntegrationType,
)
from botelier.seeds.guestcentric_integration import GUESTCENTRIC_INTEGRATION
from botelier.seeds.opera_integration import OPERA_CLOUD_INTEGRATION
from botelier.services.integration_client import (
    IntegrationAPIConfig,
    IntegrationClient,
)

ACCOUNT_ID = "00000000-0000-0000-0000-000000000001"

OPERA_GATEWAY = "https://sandbox.hospitality-api.ocs.oc-test.com"
GC_BASE_URL = "https://crs-api.guestcentric.net/v1.0"


@pytest.fixture(autouse=True)
def _cipher(monkeypatch):
    """Provide a stable, isolated Fernet cipher for credential encrypt/decrypt."""
    monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    crypto.reset_cipher_cache()
    yield
    crypto.reset_cipher_cache()


def _install_capture(monkeypatch, responder):
    """Patch httpx.AsyncClient so every outgoing request is captured.

    The real transport (``SSRFSafeTransport``) is dropped and replaced with an
    ``httpx.MockTransport`` that records the fully-built request (auth headers
    applied) and returns whatever ``responder(request)`` yields.
    """
    real_async_client = httpx.AsyncClient
    captured: list[httpx.Request] = []

    class _CapturingAsyncClient(real_async_client):
        def __init__(self, *args, **kwargs):
            kwargs.pop("transport", None)

            def handler(request: httpx.Request) -> httpx.Response:
                # Read the body eagerly so it is available after send().
                _ = request.content
                captured.append(request)
                return responder(request)

            super().__init__(
                *args, transport=httpx.MockTransport(handler), **kwargs
            )

    monkeypatch.setattr(httpx, "AsyncClient", _CapturingAsyncClient)
    return captured


def _json_response(payload):
    def _responder(_request):
        return httpx.Response(200, json=payload)

    return _responder


def _basic(username: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


# ── integration builders ──────────────────────────────────────────────────────


def _opera_integration(
    *,
    access_token="opera-access-token",
    refresh_token=None,
    expires_future=True,
    credentials_extra=None,
):
    itype = IntegrationType(
        slug="opera-cloud",
        name="Oracle Opera Cloud",
        provider="oracle",
        auth_type="oauth2_client_credentials",
    )
    itype.set_auth_config(OPERA_CLOUD_INTEGRATION["auth_config"])
    itype.set_endpoints(OPERA_CLOUD_INTEGRATION["endpoints"])
    itype.set_required_fields(OPERA_CLOUD_INTEGRATION["required_fields"])

    integ = AccountIntegration()
    integ.id = uuid.uuid4()
    integ.account_id = ACCOUNT_ID
    integ.status = IntegrationStatus.CONNECTED
    integ.integration_type = itype

    creds = {
        "gateway_url": OPERA_GATEWAY,
        "client_id": "cid",
        "client_secret": "csecret",
        "enterprise_id": "OCR4ENT",
        "hotel_id": "OHIPSB02",
        "chain_code": "CHAIN",
    }
    if credentials_extra:
        creds.update(credentials_extra)
    integ.set_credentials(creds)

    if access_token:
        integ.set_access_token(access_token)
    if refresh_token:
        integ.set_refresh_token(refresh_token)
    integ.token_expires_at = (
        datetime.utcnow() + timedelta(hours=1) if expires_future else None
    )
    return integ


def _guestcentric_integration(
    *,
    auth_method,
    access_token=None,
    refresh_token=None,
    expires_future=True,
):
    itype = IntegrationType(
        slug="guestcentric-crs",
        name="GuestCentric CRS",
        provider="guestcentric",
        auth_type="basic_or_jwt",
    )
    itype.set_auth_config(GUESTCENTRIC_INTEGRATION["auth_config"])
    itype.set_endpoints(GUESTCENTRIC_INTEGRATION["endpoints"])
    itype.set_required_fields(GUESTCENTRIC_INTEGRATION["required_fields"])

    integ = AccountIntegration()
    integ.id = uuid.uuid4()
    integ.account_id = ACCOUNT_ID
    integ.status = IntegrationStatus.CONNECTED
    integ.integration_type = itype

    creds = {
        "auth_method": auth_method,
        "username": "gcuser",
        "password": "gcpass",
        "apikey": "AK",
        "hotelId": "HOTELX",
    }
    integ.set_credentials(creds)

    if access_token:
        integ.set_access_token(access_token)
    if refresh_token:
        integ.set_refresh_token(refresh_token)
    integ.token_expires_at = (
        datetime.utcnow() + timedelta(hours=1) if expires_future else None
    )
    return integ


def _client_with(integ):
    client = IntegrationClient(account_id=ACCOUNT_ID, db=MagicMock())
    client._integration_cache[str(integ.id)] = integ
    return client


# ── Opera data-request parity ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_opera_data_request_shape(monkeypatch):
    integ = _opera_integration()
    client = _client_with(integ)
    captured = _install_capture(monkeypatch, _json_response({}))

    config = IntegrationAPIConfig(
        integration_id=str(integ.id),
        endpoint_id="get_reservation",
        method="GET",
    )
    result = await client.execute_request(config, {"confirmation_number": "ABC123"})

    assert result.success is True
    assert len(captured) == 1
    req = captured[0]
    assert req.method == "GET"
    assert str(req.url) == (
        f"{OPERA_GATEWAY}/rsv/v1/hotels/OHIPSB02/reservations"
        "?confirmationNumbers=ABC123"
    )
    assert req.headers["authorization"] == "Bearer opera-access-token"
    assert req.headers["x-app-key"] == "cid"  # falls back to client_id
    assert req.headers["x-hotelid"] == "OHIPSB02"
    assert req.headers["x-chainid"] == "CHAIN"
    assert req.headers["content-type"] == "application/json"
    assert req.headers["accept"] == "application/json"


@pytest.mark.asyncio
async def test_opera_data_request_prefers_explicit_app_key(monkeypatch):
    integ = _opera_integration(credentials_extra={"app_key": "APPKEY"})
    client = _client_with(integ)
    captured = _install_capture(monkeypatch, _json_response({}))

    config = IntegrationAPIConfig(
        integration_id=str(integ.id),
        endpoint_id="get_reservation",
        method="GET",
    )
    await client.execute_request(config, {"confirmation_number": "ABC123"})

    assert captured[0].headers["x-app-key"] == "APPKEY"


@pytest.mark.asyncio
async def test_opera_availability_request_renders_seed_defaults_and_variables(monkeypatch):
    integ = _opera_integration(credentials_extra={"app_key": "APPKEY"})
    client = _client_with(integ)
    captured = _install_capture(monkeypatch, _json_response({}))

    config = IntegrationAPIConfig(
        integration_id=str(integ.id),
        endpoint_id="check_availability",
        method="GET",
    )
    result = await client.execute_request(
        config,
        {
            "check_in_date": "2026-09-10",
            "check_out_date": "2026-09-12",
            "room_type": "KING",
        },
    )

    assert result.success is True
    assert len(captured) == 1
    assert str(captured[0].url) == (
        f"{OPERA_GATEWAY}/par/v1/hotels/OHIPSB02/availability"
        "?roomStayStartDate=2026-09-10"
        "&roomStayEndDate=2026-09-12"
        "&adults=1"
        "&children=0"
        "&roomType=KING"
    )


# ── GuestCentric data-request parity ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_guestcentric_basic_auth_request_shape(monkeypatch):
    integ = _guestcentric_integration(auth_method="basic_auth")
    client = _client_with(integ)
    captured = _install_capture(monkeypatch, _json_response([]))

    config = IntegrationAPIConfig(
        integration_id=str(integ.id),
        endpoint_id="search_locations",
        method="GET",
    )
    result = await client.execute_request(config, {"text": "lisbon"})

    assert result.success is True
    assert len(captured) == 1
    req = captured[0]
    assert req.method == "GET"
    assert str(req.url) == (
        f"{GC_BASE_URL}/search?text=lisbon&apikey=AK&hotelId=HOTELX"
    )
    assert req.headers["authorization"] == _basic("gcuser", "gcpass")
    assert req.headers["content-type"] == "application/json"
    assert req.headers["accept"] == "application/json"


@pytest.mark.asyncio
async def test_guestcentric_jwt_request_shape(monkeypatch):
    integ = _guestcentric_integration(
        auth_method="jwt", access_token="gc-jwt-token"
    )
    client = _client_with(integ)
    captured = _install_capture(monkeypatch, _json_response([]))

    config = IntegrationAPIConfig(
        integration_id=str(integ.id),
        endpoint_id="search_locations",
        method="GET",
    )
    result = await client.execute_request(config, {"text": "lisbon"})

    assert result.success is True
    assert len(captured) == 1
    req = captured[0]
    assert req.method == "GET"
    # basic_auth_query_params are appended for ANY basic_or_jwt integration
    # (the current _build_url branch keys on auth_type, not auth_method), so a
    # jwt request still carries apikey/hotelId — pin that exact behavior.
    assert str(req.url) == (
        f"{GC_BASE_URL}/search?text=lisbon&apikey=AK&hotelId=HOTELX"
    )
    assert req.headers["authorization"] == "Bearer gc-jwt-token"
    assert req.headers["content-type"] == "application/json"
    assert req.headers["accept"] == "application/json"


# ── OAuth token-refresh request parity ────────────────────────────────────────


@pytest.mark.asyncio
async def test_opera_oauth_refresh_client_credentials_shape(monkeypatch):
    integ = _opera_integration(access_token=None, expires_future=False)
    client = _client_with(integ)
    captured = _install_capture(
        monkeypatch,
        _json_response({"access_token": "newtok", "expires_in": 3600}),
    )

    credentials = integ.get_credentials()
    auth_config = integ.integration_type.get_auth_config()
    ok = await client._refresh_oauth_token(integ, credentials, auth_config)

    assert ok is True
    assert integ.status == IntegrationStatus.CONNECTED
    assert integ.get_access_token() == "newtok"

    assert len(captured) == 1
    req = captured[0]
    assert req.method == "POST"
    assert str(req.url) == f"{OPERA_GATEWAY}/oauth/v1/tokens"
    assert req.headers["content-type"] == "application/x-www-form-urlencoded"
    assert req.headers["x-app-key"] == "cid"
    assert req.headers["enterpriseid"] == "OCR4ENT"
    assert req.headers["authorization"] == _basic("cid", "csecret")

    form = parse_qs(req.content.decode())
    assert form["grant_type"] == ["client_credentials"]
    assert form["scope"] == ["urn:opc:hgbu:ws:__myscopes__"]
    assert "refresh_token" not in form


@pytest.mark.asyncio
async def test_opera_oauth_refresh_uses_refresh_token_grant(monkeypatch):
    integ = _opera_integration(
        access_token=None, refresh_token="opera-rt", expires_future=False
    )
    client = _client_with(integ)
    captured = _install_capture(
        monkeypatch, _json_response({"access_token": "tok2"})
    )

    credentials = integ.get_credentials()
    auth_config = integ.integration_type.get_auth_config()
    ok = await client._refresh_oauth_token(integ, credentials, auth_config)

    assert ok is True
    req = captured[0]
    assert str(req.url) == f"{OPERA_GATEWAY}/oauth/v1/tokens"
    form = parse_qs(req.content.decode())
    assert form["grant_type"] == ["refresh_token"]
    assert form["refresh_token"] == ["opera-rt"]
    assert "scope" not in form


# ── JWT login / refresh request parity ────────────────────────────────────────


@pytest.mark.asyncio
async def test_guestcentric_jwt_login_shape(monkeypatch):
    integ = _guestcentric_integration(
        auth_method="jwt", access_token=None, expires_future=False
    )
    client = _client_with(integ)
    captured = _install_capture(
        monkeypatch, _json_response({"token": "jwt-new"})
    )

    credentials = integ.get_credentials()
    auth_config = integ.integration_type.get_auth_config()
    ok = await client._refresh_jwt_token(integ, credentials, auth_config)

    assert ok is True
    assert integ.get_access_token() == "jwt-new"
    assert integ.status == IntegrationStatus.CONNECTED

    assert len(captured) == 1
    req = captured[0]
    assert req.method == "POST"
    assert str(req.url) == f"{GC_BASE_URL}/authentication/login?apikey=AK"
    assert req.headers["content-type"] == "application/json"
    assert req.headers["accept"] == "application/json"

    body = json.loads(req.content.decode())
    assert body["username"] == "gcuser"
    assert body["password"] == "gcpass"
    assert isinstance(body["expired_time"], str) and body["expired_time"]
    assert "refresh_token" not in body


@pytest.mark.asyncio
async def test_guestcentric_jwt_refresh_shape(monkeypatch):
    integ = _guestcentric_integration(
        auth_method="jwt",
        access_token="old",
        refresh_token="gc-rt",
        expires_future=False,
    )
    client = _client_with(integ)
    captured = _install_capture(
        monkeypatch, _json_response({"token": "jwt-refreshed"})
    )

    credentials = integ.get_credentials()
    auth_config = integ.integration_type.get_auth_config()
    ok = await client._refresh_jwt_token(integ, credentials, auth_config)

    assert ok is True
    assert integ.get_access_token() == "jwt-refreshed"

    assert len(captured) == 1
    req = captured[0]
    assert req.method == "POST"
    assert str(req.url) == f"{GC_BASE_URL}/authentication/refresh?apikey=AK"
    body = json.loads(req.content.decode())
    assert body["refresh_token"] == "gc-rt"
    assert isinstance(body["expired_time"], str) and body["expired_time"]
    assert "username" not in body
