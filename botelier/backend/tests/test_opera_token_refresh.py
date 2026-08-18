"""Opera OHIP token-refresh hardening tests (Task #484).

The refresh must distinguish transient provider trouble from definitive
credential rejection:

- 429 / 5xx from the token endpoint  -> transient: status stays CONNECTED so the
  next request retries automatically (no manual reconnect required).
- 400 / 401 / 403                    -> terminal: TOKEN_EXPIRED.
- 200 with malformed JSON or no access_token -> transient, handled explicitly.
- 200 without expires_in             -> a default TTL is stamped so the runtime
  does not re-hit the token endpoint on every request.
- Provider response bodies are truncated in logs (no full-body logging).
"""

import asyncio
from datetime import datetime

import httpx
import pytest

from botelier.models.integration import IntegrationStatus
from botelier.services.integration_runtime.adapters.base import RefreshContext
from botelier.services.integration_runtime.adapters.opera_cloud import (
    _DEFAULT_TOKEN_TTL_S,
    _LOG_BODY_MAX,
    OperaCloudAdapter,
    _truncate_for_log,
)

_CREDS = {
    "gateway_url": "https://env.hospitality.oraclecloud.com",
    "client_id": "cid",
    "client_secret": "secret",
    "enterprise_id": "ENT1",
    "hotel_id": "HOTEL1",
}
_AUTH_CONFIG = {
    "token_endpoint_path": "/oauth/v1/tokens",
    "grant_type": "client_credentials",
    "scope": "urn:opc:hgbu:ws:__myscopes__",
}


class _FakeIntegration:
    def __init__(self):
        self.id = "int-1"
        self.status = IntegrationStatus.CONNECTED
        self.last_error = None
        self.token_expires_at = None
        self._access_token = None
        self._refresh_token = None

    def set_access_token(self, tok):
        self._access_token = tok

    def get_refresh_token(self):
        return self._refresh_token

    def set_refresh_token(self, tok):
        self._refresh_token = tok


class _FakeDB:
    def __init__(self):
        self.committed = False

    def add(self, _obj):
        pass

    def commit(self):
        self.committed = True

    def close(self):
        pass


def _install_token_response(monkeypatch, response_factory):
    real_async_client = httpx.AsyncClient

    class _MockedAsyncClient(real_async_client):
        def __init__(self, *args, **kwargs):
            kwargs.pop("transport", None)

            def handler(request: httpx.Request) -> httpx.Response:
                return response_factory(request)

            super().__init__(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _MockedAsyncClient)


def _run_refresh(monkeypatch, response_factory):
    integration = _FakeIntegration()
    db = _FakeDB()
    ctx = RefreshContext(
        integration=integration,
        credentials=dict(_CREDS),
        auth_config=dict(_AUTH_CONFIG),
        get_db_session=lambda: db,
        owns_session=True,
    )
    _install_token_response(monkeypatch, response_factory)
    ok = asyncio.get_event_loop().run_until_complete(
        OperaCloudAdapter().refresh_oauth(ctx)
    )
    return ok, integration, db


def test_success_sets_token_and_expiry(monkeypatch):
    ok, integration, db = _run_refresh(
        monkeypatch,
        lambda _r: httpx.Response(200, json={"access_token": "T", "expires_in": 3600}),
    )
    assert ok is True
    assert integration._access_token == "T"
    assert integration.status == IntegrationStatus.CONNECTED
    assert integration.token_expires_at is not None
    assert db.committed


def test_missing_expires_in_gets_default_ttl(monkeypatch):
    before = datetime.utcnow()
    ok, integration, _ = _run_refresh(
        monkeypatch, lambda _r: httpx.Response(200, json={"access_token": "T"})
    )
    assert ok is True
    assert integration.token_expires_at is not None
    ttl = (integration.token_expires_at - before).total_seconds()
    # Roughly the default TTL (allow slack for test runtime).
    assert _DEFAULT_TOKEN_TTL_S - 60 < ttl <= _DEFAULT_TOKEN_TTL_S + 60


def test_200_without_access_token_is_transient(monkeypatch):
    ok, integration, _ = _run_refresh(
        monkeypatch, lambda _r: httpx.Response(200, json={"unexpected": "shape"})
    )
    assert ok is False
    # Stays CONNECTED so the next request retries the refresh automatically.
    assert integration.status == IntegrationStatus.CONNECTED
    assert "access_token" in integration.last_error


def test_200_with_non_json_body_is_transient(monkeypatch):
    ok, integration, _ = _run_refresh(
        monkeypatch, lambda _r: httpx.Response(200, content=b"<html>gateway error</html>")
    )
    assert ok is False
    assert integration.status == IntegrationStatus.CONNECTED


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_transient_provider_failure_keeps_connected(monkeypatch, status):
    ok, integration, _ = _run_refresh(
        monkeypatch, lambda _r: httpx.Response(status, json={"error": "throttled"})
    )
    assert ok is False
    assert integration.status == IntegrationStatus.CONNECTED
    assert str(status) in integration.last_error


@pytest.mark.parametrize("status", [400, 401, 403])
def test_credential_rejection_is_terminal(monkeypatch, status):
    ok, integration, _ = _run_refresh(
        monkeypatch,
        lambda _r: httpx.Response(status, json={"error": "invalid_client"}),
    )
    assert ok is False
    assert integration.status == IntegrationStatus.TOKEN_EXPIRED
    assert str(status) in integration.last_error


def test_network_exception_stays_connected(monkeypatch):
    def _boom(_r):
        raise httpx.ConnectError("boom")

    ok, integration, _ = _run_refresh(monkeypatch, _boom)
    assert ok is False
    assert integration.status == IntegrationStatus.CONNECTED


def test_log_truncation_helper():
    assert _truncate_for_log(None) == ""
    assert _truncate_for_log("short") == "short"
    long_body = "x" * (_LOG_BODY_MAX + 500)
    out = _truncate_for_log(long_body)
    assert len(out) == _LOG_BODY_MAX + 1  # cap + ellipsis
    assert out.endswith("…")


def test_refresh_uses_client_credentials_grant(monkeypatch):
    seen = {}

    def factory(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        seen["app_key"] = request.headers.get("x-app-key")
        seen["enterprise"] = request.headers.get("enterpriseId")
        return httpx.Response(200, json={"access_token": "T", "expires_in": 60})

    ok, _, _ = _run_refresh(monkeypatch, factory)
    assert ok is True
    assert "grant_type=client_credentials" in seen["body"]
    assert seen["app_key"] == "cid"  # falls back to client_id
    assert seen["enterprise"] == "ENT1"
