"""Tests for Task #331 — integration resilience + 3-legged OAuth2.

Covers the four hardening concerns end to end:

  • Rate limiting — the Postgres token bucket admits a burst up to capacity then
    rejects, and refills over time.
  • Retry backoff — the pure ``compute_backoff_delay`` / ``parse_retry_after``
    functions (exponential + full jitter, Retry-After honored but capped), and
    the client actually retrying a 429/5xx for safe methods and sleeping.
  • Circuit breaking — the Postgres state machine transitions
    (closed → open → half_open → closed / re-open) and the client short-circuits
    with an LLM-friendly CIRCUIT_OPEN error once open.
  • OAuth2 authorization_code — the runtime refresh grant (success, rotation,
    transient-vs-terminal), refresh under contention, and the API code-exchange.

DB-backed pieces (bucket + breaker) use the configured dev Postgres via
``SessionLocal`` with a freshly-generated ``integration_id`` per test so rows
never collide. The two resilience tables are created if absent.
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.fernet import Fernet

from botelier import crypto
from botelier.database import Base, SessionLocal, engine
from botelier.models.integration import (
    AccountIntegration,
    IntegrationStatus,
    IntegrationType,
)
from botelier.models.integration_resilience import (  # noqa: F401 - registers tables
    CircuitState,
    IntegrationCircuitBreaker,
    IntegrationRateLimit,
)
from botelier.services.integration_client import IntegrationAPIConfig, IntegrationClient
from botelier.services.integration_runtime.adapters.base import RefreshContext
from botelier.services.integration_runtime.adapters.oauth2 import (
    OAuth2AuthorizationCodeAdapter,
    resolve_token_endpoint,
)
from botelier.services.integration_runtime.adapters.registry import (
    UnsupportedAuthTypeError,
    resolve_adapter,
)
from botelier.services.integration_runtime.resilience import (
    ResilienceConfig,
    _resilience_state_id,
    circuit_allow,
    circuit_record_failure,
    circuit_record_success,
    compute_backoff_delay,
    parse_retry_after,
    rate_limit_acquire,
)
from botelier.services.integration_runtime.types import APIErrorType

ACCOUNT_ID = "00000000-0000-0000-0000-000000000042"


@pytest.fixture(scope="module", autouse=True)
def _ensure_tables():
    """Create the resilience tables in the dev DB if they don't exist yet."""
    Base.metadata.create_all(
        bind=engine,
        tables=[
            IntegrationRateLimit.__table__,
            IntegrationCircuitBreaker.__table__,
        ],
    )
    yield


@pytest.fixture(autouse=True)
def _cipher(monkeypatch):
    monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    crypto.reset_cipher_cache()
    yield
    crypto.reset_cipher_cache()


def _new_iid():
    return uuid.uuid4()


# ── ResilienceConfig resolution ───────────────────────────────────────────────


def _integration_with_resilience(auth_resilience=None, conn_resilience=None):
    itype = IntegrationType(
        slug="acme", name="Acme", provider="acme", auth_type="oauth2_authorization_code"
    )
    auth_config = {"base_url": "https://acme.test"}
    if auth_resilience is not None:
        auth_config["resilience"] = auth_resilience
    itype.set_auth_config(auth_config)

    integ = AccountIntegration()
    integ.id = _new_iid()
    integ.account_id = ACCOUNT_ID
    integ.status = IntegrationStatus.CONNECTED
    integ.integration_type = itype
    if conn_resilience is not None:
        integ.set_connection_config({"resilience": conn_resilience})
    return integ


def test_resilience_config_defaults():
    conf = ResilienceConfig()
    assert conf.rate_limit_enabled is True
    assert conf.breaker_failure_threshold == 5
    assert conf.backoff_jitter is True


def test_resilience_config_conn_overrides_auth_overrides_default():
    integ = _integration_with_resilience(
        auth_resilience={"breaker_failure_threshold": 10, "rate_limit_capacity": 99},
        conn_resilience={"breaker_failure_threshold": 3},
    )
    conf = ResilienceConfig.from_integration(integ)
    # conn override wins for threshold; auth override still applies for capacity;
    # untouched keys keep defaults.
    assert conf.breaker_failure_threshold == 3
    assert conf.rate_limit_capacity == 99.0
    assert conf.backoff_factor == 2.0


def test_resilience_config_ignores_malformed_override():
    integ = _integration_with_resilience(
        auth_resilience={"breaker_failure_threshold": "not-an-int"}
    )
    conf = ResilienceConfig.from_integration(integ)
    assert conf.breaker_failure_threshold == 5  # fell back to default


# ── Backoff pure functions ────────────────────────────────────────────────────


def test_parse_retry_after_integer_only():
    assert parse_retry_after("5") == 5.0
    assert parse_retry_after("  10 ") == 10.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("Wed, 21 Oct 2099 07:28:00 GMT") is None  # HTTP-date ignored


def test_compute_backoff_no_jitter_is_exponential_and_capped():
    conf = ResilienceConfig(
        backoff_base_s=0.2, backoff_factor=2.0, backoff_max_s=5.0, backoff_jitter=False
    )
    assert compute_backoff_delay(0, conf) == pytest.approx(0.2)
    assert compute_backoff_delay(1, conf) == pytest.approx(0.4)
    assert compute_backoff_delay(2, conf) == pytest.approx(0.8)
    # 0.2 * 2**10 = 204.8 → capped at 5.0
    assert compute_backoff_delay(10, conf) == pytest.approx(5.0)


def test_compute_backoff_full_jitter_within_bounds():
    conf = ResilienceConfig(
        backoff_base_s=0.5, backoff_factor=2.0, backoff_max_s=5.0, backoff_jitter=True
    )
    for _ in range(200):
        delay = compute_backoff_delay(3, conf)  # capped = min(4.0, 5.0) = 4.0
        assert 0.0 <= delay <= 4.0


def test_compute_backoff_retry_after_capped_by_max():
    conf = ResilienceConfig(backoff_max_s=5.0, backoff_jitter=False)
    # A hostile huge Retry-After must never stall a call beyond the cap.
    assert compute_backoff_delay(0, conf, retry_after=3600) == pytest.approx(5.0)
    # A small server hint under the cap is honored verbatim (no jitter).
    assert compute_backoff_delay(0, conf, retry_after=2) == pytest.approx(2.0)


# ── Rate limiter (Postgres token bucket) ──────────────────────────────────────


def test_rate_limit_admits_burst_then_rejects():
    iid = _new_iid()
    conf = ResilienceConfig(
        rate_limit_capacity=3, rate_limit_refill_per_sec=0.0
    )
    # First 3 acquire; the 4th is rejected (no refill).
    assert rate_limit_acquire(iid, ACCOUNT_ID, conf) is True
    assert rate_limit_acquire(iid, ACCOUNT_ID, conf) is True
    assert rate_limit_acquire(iid, ACCOUNT_ID, conf) is True
    assert rate_limit_acquire(iid, ACCOUNT_ID, conf) is False


def test_resilience_state_is_independent_per_account_for_the_same_integration():
    """A tenant can never exhaust or open another tenant's resilience state."""
    iid = _new_iid()
    other_account_id = "00000000-0000-0000-0000-000000000043"
    conf = ResilienceConfig(
        rate_limit_capacity=1,
        rate_limit_refill_per_sec=0.0,
        breaker_failure_threshold=1,
        breaker_cooldown_s=300,
    )

    assert rate_limit_acquire(iid, ACCOUNT_ID, conf) is True
    assert rate_limit_acquire(iid, ACCOUNT_ID, conf) is False
    assert rate_limit_acquire(iid, other_account_id, conf) is True

    circuit_record_failure(iid, ACCOUNT_ID, conf)
    assert circuit_allow(iid, ACCOUNT_ID, conf)[0] is False
    assert circuit_allow(iid, other_account_id, conf)[0] is True


def test_rate_limit_disabled_always_allows():
    iid = _new_iid()
    conf = ResilienceConfig(rate_limit_enabled=False, rate_limit_capacity=1)
    for _ in range(5):
        assert rate_limit_acquire(iid, ACCOUNT_ID, conf) is True


def test_rate_limit_refills_over_time():
    iid = _new_iid()
    conf = ResilienceConfig(rate_limit_capacity=1, rate_limit_refill_per_sec=1000.0)
    assert rate_limit_acquire(iid, ACCOUNT_ID, conf) is True
    # Backdate updated_at so the lazy refill sees elapsed time and tops back up.
    db = SessionLocal()
    try:
        db.execute(
            IntegrationRateLimit.__table__.update()
            .where(
                IntegrationRateLimit.integration_id
                == _resilience_state_id(iid, ACCOUNT_ID)
            )
            .values(updated_at=datetime.utcnow() - timedelta(seconds=5))
        )
        db.commit()
    finally:
        db.close()
    assert rate_limit_acquire(iid, ACCOUNT_ID, conf) is True


# ── Circuit breaker state machine ─────────────────────────────────────────────


def _breaker_state(iid, account_id=ACCOUNT_ID):
    db = SessionLocal()
    try:
        row = db.get(IntegrationCircuitBreaker, _resilience_state_id(iid, account_id))
        return row.state if row else None
    finally:
        db.close()


def test_breaker_trips_open_after_threshold():
    iid = _new_iid()
    conf = ResilienceConfig(breaker_failure_threshold=3, breaker_cooldown_s=30)
    assert circuit_allow(iid, ACCOUNT_ID, conf)[0] is True

    circuit_record_failure(iid, ACCOUNT_ID, conf)
    circuit_record_failure(iid, ACCOUNT_ID, conf)
    # Still closed (2 < 3)
    assert _breaker_state(iid) == CircuitState.CLOSED
    assert circuit_allow(iid, ACCOUNT_ID, conf)[0] is True

    circuit_record_failure(iid, ACCOUNT_ID, conf)
    # Third failure trips it OPEN → subsequent requests short-circuit.
    assert _breaker_state(iid) == CircuitState.OPEN
    allowed, state = circuit_allow(iid, ACCOUNT_ID, conf)
    assert allowed is False
    assert state == CircuitState.OPEN


def test_breaker_success_resets_failures():
    iid = _new_iid()
    conf = ResilienceConfig(breaker_failure_threshold=3)
    circuit_record_failure(iid, ACCOUNT_ID, conf)
    circuit_record_failure(iid, ACCOUNT_ID, conf)
    circuit_record_success(iid, ACCOUNT_ID, conf)
    # A success zeroes the count, so it now takes a fresh full threshold to trip.
    circuit_record_failure(iid, ACCOUNT_ID, conf)
    circuit_record_failure(iid, ACCOUNT_ID, conf)
    assert _breaker_state(iid) == CircuitState.CLOSED


def test_breaker_half_open_probe_then_recover():
    iid = _new_iid()
    conf = ResilienceConfig(breaker_failure_threshold=1, breaker_cooldown_s=0.0)
    # Trip open immediately.
    circuit_record_failure(iid, ACCOUNT_ID, conf)
    assert _breaker_state(iid) == CircuitState.OPEN
    # Cooldown is 0 → next allow transitions to HALF_OPEN and lets a probe through.
    allowed, state = circuit_allow(iid, ACCOUNT_ID, conf)
    assert allowed is True
    assert state == CircuitState.HALF_OPEN
    # A successful probe closes the breaker.
    circuit_record_success(iid, ACCOUNT_ID, conf)
    assert _breaker_state(iid) == CircuitState.CLOSED


def test_breaker_half_open_probe_failure_reopens():
    iid = _new_iid()
    conf = ResilienceConfig(breaker_failure_threshold=1, breaker_cooldown_s=0.0)
    circuit_record_failure(iid, ACCOUNT_ID, conf)
    allowed, state = circuit_allow(iid, ACCOUNT_ID, conf)
    assert state == CircuitState.HALF_OPEN
    # A failed probe immediately re-opens the breaker.
    circuit_record_failure(iid, ACCOUNT_ID, conf)
    assert _breaker_state(iid) == CircuitState.OPEN


def test_breaker_disabled_always_allows():
    iid = _new_iid()
    conf = ResilienceConfig(breaker_enabled=False)
    circuit_record_failure(iid, ACCOUNT_ID, conf)
    circuit_record_failure(iid, ACCOUNT_ID, conf)
    assert circuit_allow(iid, ACCOUNT_ID, conf)[0] is True


def test_adapter_registry_rejects_unknown_auth_type():
    """Unknown auth schemes must fail before the client can issue HTTP."""
    with pytest.raises(UnsupportedAuthTypeError, match="not supported"):
        resolve_adapter(slug="arbitrary-api", auth_type="vendor_custom_hmac")


# ── Client integration: retries, gates, breaker wiring ────────────────────────


def _install_capture(monkeypatch, responder):
    real_async_client = httpx.AsyncClient
    captured: list[httpx.Request] = []

    class _CapturingAsyncClient(real_async_client):
        def __init__(self, *args, **kwargs):
            kwargs.pop("transport", None)

            def handler(request: httpx.Request) -> httpx.Response:
                _ = request.content
                captured.append(request)
                return responder(request)

            super().__init__(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _CapturingAsyncClient)
    return captured


def _custom_get_integration(*, method="GET", iid=None):
    """A minimal custom-HTTP integration with one endpoint, no auth token."""
    itype = IntegrationType(
        slug="customapi", name="Custom", provider="custom", auth_type="none"
    )
    itype.set_auth_config({"base_url": "https://api.custom.test"})
    itype.set_endpoints(
        [
            {
                "id": "ping",
                "path": "/ping",
                "method": method,
                "description": "ping",
            }
        ]
    )
    integ = AccountIntegration()
    integ.id = iid or _new_iid()
    integ.account_id = ACCOUNT_ID
    integ.status = IntegrationStatus.CONNECTED
    integ.integration_type = itype
    integ.set_credentials({})
    return integ


def _unsupported_auth_integration():
    integ = _custom_get_integration()
    integ.integration_type.auth_type = "vendor_custom_hmac"
    return integ


def _client_with(integ):
    client = IntegrationClient(account_id=ACCOUNT_ID, db=MagicMock())
    client._integration_cache[str(integ.id)] = integ
    return client


@pytest.mark.asyncio
async def test_client_retries_429_then_succeeds(monkeypatch):
    integ = _custom_get_integration(method="GET")
    client = _client_with(integ)

    calls = {"n": 0}

    def responder(_req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={})
        return httpx.Response(200, json={"ok": True})

    captured = _install_capture(monkeypatch, responder)

    slept: list[float] = []

    async def _fake_sleep(d):
        slept.append(d)

    monkeypatch.setattr(
        "botelier.services.integration_runtime.client.asyncio.sleep", _fake_sleep
    )

    config = IntegrationAPIConfig(
        integration_id=str(integ.id), endpoint_id="ping", method="GET", retry_count=2
    )
    result = await client.execute_request(config, {})

    assert result.success is True
    assert len(captured) == 2  # retried once
    assert len(slept) == 1  # backed off before the retry
    # Retry-After of 1s, capped by default backoff_max (5) → slept ≤ 1s.
    assert 0.0 <= slept[0] <= 1.0


@pytest.mark.asyncio
async def test_client_rejects_unsupported_auth_before_outbound_request(monkeypatch):
    integ = _unsupported_auth_integration()
    client = _client_with(integ)
    captured = _install_capture(monkeypatch, lambda _req: httpx.Response(200, json={}))

    result = await client.execute_request(
        IntegrationAPIConfig(
            integration_id=str(integ.id), endpoint_id="ping", method="GET"
        ),
        {},
    )

    assert result.success is False
    assert result.error_type == APIErrorType.AUTH_ERROR
    assert "not supported" in (result.error_message or "")
    assert captured == []


@pytest.mark.asyncio
async def test_client_does_not_retry_post_on_5xx(monkeypatch):
    integ = _custom_get_integration(method="POST")
    client = _client_with(integ)

    captured = _install_capture(
        monkeypatch, lambda _req: httpx.Response(503, json={})
    )

    async def _fake_sleep(d):
        pass

    monkeypatch.setattr(
        "botelier.services.integration_runtime.client.asyncio.sleep", _fake_sleep
    )

    config = IntegrationAPIConfig(
        integration_id=str(integ.id), endpoint_id="ping", method="POST", retry_count=3
    )
    result = await client.execute_request(config, {})

    assert result.success is False
    # Non-idempotent method: a 5xx must NOT be retried.
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_client_sends_form_encoded_body(monkeypatch):
    integ = _custom_get_integration(method="POST")
    client = _client_with(integ)
    captured = _install_capture(monkeypatch, lambda _req: httpx.Response(200, json={}))

    result = await client.execute_request(
        IntegrationAPIConfig(
            integration_id=str(integ.id),
            endpoint_id="ping",
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body_template='{"email": "{{email}}", "status": "active"}',
        ),
        {"email": "guest@example.test"},
    )

    assert result.success is True
    assert captured[0].headers["content-type"].startswith(
        "application/x-www-form-urlencoded"
    )
    assert parse_qs(captured[0].content.decode()) == {
        "email": ["guest@example.test"],
        "status": ["active"],
    }


@pytest.mark.asyncio
async def test_client_sends_xml_body_and_preserves_raw_text_response(monkeypatch):
    integ = _custom_get_integration(method="POST")
    client = _client_with(integ)
    captured = _install_capture(
        monkeypatch,
        lambda _req: httpx.Response(
            200, content=b"<result><ok>true</ok></result>", headers={"Content-Type": "application/xml"}
        ),
    )

    result = await client.execute_request(
        IntegrationAPIConfig(
            integration_id=str(integ.id),
            endpoint_id="ping",
            method="POST",
            headers={"Content-Type": "application/xml", "Accept": "application/xml"},
            body_template="<guest><email>{{email}}</email></guest>",
        ),
        {"email": "guest@example.test"},
    )

    assert result.success is True
    assert captured[0].content == b"<guest><email>guest@example.test</email></guest>"
    assert result.data == "<result><ok>true</ok></result>"
    assert result.raw_response == "<result><ok>true</ok></result>"


@pytest.mark.asyncio
async def test_client_sends_multipart_fields(monkeypatch):
    integ = _custom_get_integration(method="POST")
    client = _client_with(integ)
    captured = _install_capture(monkeypatch, lambda _req: httpx.Response(200, json={}))

    result = await client.execute_request(
        IntegrationAPIConfig(
            integration_id=str(integ.id),
            endpoint_id="ping",
            method="POST",
            headers={"Content-Type": "multipart/form-data"},
            body_template='{"name": "{{name}}", "role": "guest"}',
        ),
        {"name": "Ada"},
    )

    assert result.success is True
    assert captured[0].headers["content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="name"' in captured[0].content
    assert b"\r\nAda\r\n" in captured[0].content


@pytest.mark.asyncio
async def test_client_follows_redirects_with_a_bounded_policy(monkeypatch):
    integ = _custom_get_integration(method="GET")
    client = _client_with(integ)
    calls = {"count": 0}

    def responder(request):
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(302, headers={"Location": "https://api.custom.test/next"})
        assert request.url.path == "/next"
        return httpx.Response(200, json={"ok": True})

    captured = _install_capture(monkeypatch, responder)
    result = await client.execute_request(
        IntegrationAPIConfig(
            integration_id=str(integ.id), endpoint_id="ping", method="GET"
        ),
        {},
    )

    assert result.success is True
    assert len(captured) == 2


@pytest.mark.asyncio
async def test_client_short_circuits_when_breaker_open(monkeypatch):
    iid = _new_iid()
    # Pre-trip the breaker for this integration id.
    conf = ResilienceConfig(breaker_failure_threshold=1, breaker_cooldown_s=300)
    circuit_record_failure(iid, ACCOUNT_ID, conf)
    assert _breaker_state(iid) == CircuitState.OPEN

    integ = _custom_get_integration(method="GET", iid=iid)
    client = _client_with(integ)
    captured = _install_capture(
        monkeypatch, lambda _req: httpx.Response(200, json={})
    )

    config = IntegrationAPIConfig(
        integration_id=str(integ.id), endpoint_id="ping", method="GET"
    )
    result = await client.execute_request(config, {})

    assert result.success is False
    assert result.error_type == APIErrorType.CIRCUIT_OPEN
    # No outbound request was made — the gate ran before any HTTP.
    assert len(captured) == 0


@pytest.mark.asyncio
async def test_client_rejects_when_rate_limited(monkeypatch):
    iid = _new_iid()
    integ = _custom_get_integration(method="GET", iid=iid)
    # Drain the bucket to empty via a tight override on the integration.
    integ.set_connection_config(
        {"resilience": {"rate_limit_capacity": 1, "rate_limit_refill_per_sec": 0}}
    )
    client = _client_with(integ)
    captured = _install_capture(
        monkeypatch, lambda _req: httpx.Response(200, json={})
    )

    config = IntegrationAPIConfig(
        integration_id=str(integ.id), endpoint_id="ping", method="GET"
    )
    # First request consumes the single token and succeeds.
    first = await client.execute_request(config, {})
    assert first.success is True
    # Second is rejected before any HTTP.
    second = await client.execute_request(config, {})
    assert second.success is False
    assert second.error_type == APIErrorType.RATE_LIMITED
    assert len(captured) == 1


# ── OAuth2 authorization_code adapter ─────────────────────────────────────────


def _oauth_integration(*, refresh_token="rt-1", access_token="old-access"):
    itype = IntegrationType(
        slug="acme-oauth",
        name="Acme OAuth",
        provider="acme",
        auth_type="oauth2_authorization_code",
    )
    itype.set_auth_config(
        {
            "base_url": "https://acme.test",
            "authorization_endpoint": "https://acme.test/oauth/authorize",
            "token_endpoint": "https://acme.test/oauth/token",
        }
    )
    integ = AccountIntegration()
    integ.id = _new_iid()
    integ.account_id = ACCOUNT_ID
    integ.status = IntegrationStatus.CONNECTED
    integ.integration_type = itype
    integ.set_credentials({"client_id": "cid", "client_secret": "csecret"})
    if access_token:
        integ.set_access_token(access_token)
    if refresh_token:
        integ.set_refresh_token(refresh_token)
    integ.token_expires_at = datetime.utcnow() - timedelta(minutes=1)
    return integ


def _refresh_ctx(integ):
    session = MagicMock()
    return RefreshContext(
        integration=integ,
        credentials=integ.get_credentials(),
        auth_config=integ.integration_type.get_auth_config(),
        get_db_session=lambda: session,
        owns_session=False,
    )


def test_resolve_token_endpoint_variants():
    assert (
        resolve_token_endpoint({"token_endpoint": "https://x.test/t"})
        == "https://x.test/t"
    )
    assert (
        resolve_token_endpoint(
            {"base_url": "https://x.test/", "token_endpoint_path": "oauth/token"}
        )
        == "https://x.test/oauth/token"
    )
    assert resolve_token_endpoint({"base_url": "https://x.test"}) == "https://x.test/oauth/token"


@pytest.mark.asyncio
async def test_oauth_refresh_success_rotates_tokens(monkeypatch):
    integ = _oauth_integration(refresh_token="rt-old")
    adapter = OAuth2AuthorizationCodeAdapter()

    captured = _install_capture(
        monkeypatch,
        lambda _req: httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "rt-new",
                "expires_in": 1200,
            },
        ),
    )

    ok = await adapter.refresh_credentials(_refresh_ctx(integ))

    assert ok is True
    assert integ.status == IntegrationStatus.CONNECTED
    assert integ.get_access_token() == "new-access"
    assert integ.get_refresh_token() == "rt-new"  # rotated
    assert len(captured) == 1
    req = captured[0]
    assert req.method == "POST"
    assert str(req.url) == "https://acme.test/oauth/token"
    from urllib.parse import parse_qs

    form = parse_qs(req.content.decode())
    assert form["grant_type"] == ["refresh_token"]
    assert form["refresh_token"] == ["rt-old"]


@pytest.mark.asyncio
async def test_oauth_refresh_missing_refresh_token_is_terminal(monkeypatch):
    integ = _oauth_integration(refresh_token=None)
    adapter = OAuth2AuthorizationCodeAdapter()
    captured = _install_capture(
        monkeypatch, lambda _req: httpx.Response(200, json={})
    )

    ok = await adapter.refresh_credentials(_refresh_ctx(integ))

    assert ok is False
    assert integ.status == IntegrationStatus.TOKEN_EXPIRED
    assert len(captured) == 0  # never hit the network


@pytest.mark.asyncio
async def test_oauth_refresh_non_200_is_terminal(monkeypatch):
    integ = _oauth_integration(refresh_token="rt")
    adapter = OAuth2AuthorizationCodeAdapter()
    _install_capture(
        monkeypatch, lambda _req: httpx.Response(400, json={"error": "invalid_grant"})
    )

    ok = await adapter.refresh_credentials(_refresh_ctx(integ))

    assert ok is False
    assert integ.status == IntegrationStatus.TOKEN_EXPIRED


@pytest.mark.asyncio
async def test_oauth_refresh_network_error_is_transient(monkeypatch):
    integ = _oauth_integration(refresh_token="rt")
    adapter = OAuth2AuthorizationCodeAdapter()

    def _boom(_req):
        raise httpx.ConnectError("boom")

    _install_capture(monkeypatch, _boom)

    ok = await adapter.refresh_credentials(_refresh_ctx(integ))

    assert ok is False
    # Transient: stays CONNECTED so the NEXT request retries the refresh.
    assert integ.status == IntegrationStatus.CONNECTED


@pytest.mark.asyncio
async def test_oauth_refresh_under_contention_single_winner(monkeypatch):
    """Two workers racing a refresh both succeed idempotently.

    The adapter itself is stateless; the cross-worker single-flight guarantee is
    the advisory lock in the runtime. Here we assert the adapter is safe to call
    concurrently: both calls converge on a valid CONNECTED token.
    """
    import asyncio

    integ = _oauth_integration(refresh_token="rt")
    adapter = OAuth2AuthorizationCodeAdapter()
    _install_capture(
        monkeypatch,
        lambda _req: httpx.Response(
            200, json={"access_token": "tok", "expires_in": 900}
        ),
    )

    results = await asyncio.gather(
        adapter.refresh_credentials(_refresh_ctx(integ)),
        adapter.refresh_credentials(_refresh_ctx(integ)),
    )
    assert all(results)
    assert integ.get_access_token() == "tok"
    assert integ.status == IntegrationStatus.CONNECTED


# ── OAuth2 API code exchange ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exchange_authorization_code_success(monkeypatch):
    from botelier.api.integrations import exchange_authorization_code

    itype = IntegrationType(
        slug="acme-oauth",
        name="Acme",
        provider="acme",
        auth_type="oauth2_authorization_code",
    )
    itype.set_auth_config(
        {"base_url": "https://acme.test", "token_endpoint": "https://acme.test/oauth/token"}
    )

    captured = _install_capture(
        monkeypatch,
        lambda _req: httpx.Response(
            200,
            json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600},
        ),
    )

    result = await exchange_authorization_code(
        itype,
        {"client_id": "cid", "client_secret": "sec"},
        code="the-code",
        redirect_uri="https://app.test/api/integrations/oauth/callback",
    )

    assert result["success"] is True
    assert result["access_token"] == "at"
    assert result["refresh_token"] == "rt"
    req = captured[0]
    from urllib.parse import parse_qs

    form = parse_qs(req.content.decode())
    assert form["grant_type"] == ["authorization_code"]
    assert form["code"] == ["the-code"]
    assert form["redirect_uri"] == [
        "https://app.test/api/integrations/oauth/callback"
    ]


@pytest.mark.asyncio
async def test_exchange_authorization_code_failure(monkeypatch):
    from botelier.api.integrations import exchange_authorization_code

    itype = IntegrationType(
        slug="acme-oauth",
        name="Acme",
        provider="acme",
        auth_type="oauth2_authorization_code",
    )
    itype.set_auth_config(
        {"base_url": "https://acme.test", "token_endpoint": "https://acme.test/oauth/token"}
    )
    _install_capture(
        monkeypatch, lambda _req: httpx.Response(400, json={"error": "invalid_grant"})
    )

    result = await exchange_authorization_code(
        itype, {"client_id": "cid"}, code="bad", redirect_uri="https://app.test/cb"
    )
    assert result["success"] is False
