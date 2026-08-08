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
  • OAuth2 security hardening — callback state account-binding, lock-failure
    never runs unlocked, clear transient error surfaced to callers.

DB-backed pieces (bucket + breaker) use the configured dev Postgres via
``SessionLocal`` with a freshly-generated ``integration_id`` per test so rows
never collide. The two resilience tables are created if absent.
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
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
from botelier.services.integration_runtime.locks import (
    _LOCK_ACQUIRE_BACKOFF_S,
    _LOCK_ACQUIRE_RETRIES,
    TokenRefreshLockUnavailableError,
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
OTHER_ACCOUNT_ID = "00000000-0000-0000-0000-000000000099"


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


# ── OAuth2 security hardening (authenticated-completion design) ───────────────
#
# Design: no binding cookie.  The registered redirect_uri (/oauth/callback) is
# a stateless hop that immediately 302s to {FRONTEND_URL}/dashboard/integrations/
# oauth/complete — where {FRONTEND_URL} comes ONLY from server configuration,
# never from request headers or OAuth state.  The frontend page POSTs code+state
# to the authenticated backend POST /api/integrations/oauth/complete endpoint,
# which requires a valid Bearer token (get_current_user) and verifies:
#   1. account_id in state must be an account the caller has integrations.manage on
#   2. integration_id must belong to that account (defence-in-depth)
#   3. one-time CSRF nonce (constant-time compare, cleared on use)
#
# A forwarded callback link is harmless without the victim's session.
#
# Concerns tested:
#   1. Authorize response returns JSON with no Set-Cookie header.
#   2. State is 3 segments only — no user-controlled data.
#   3. /oauth/callback hops to the configured FRONTEND_URL (env-only).
#   4. /oauth/callback never uses request Origin or state content as target.
#   5. POST /oauth/complete rejects unauthenticated callers (401, ASGI).
#   6. POST /oauth/complete rejects callers from a different account (403).
#   7. POST /oauth/complete rejects a wrong nonce (400 invalid_state).
#   8. POST /oauth/complete rejects a provider error (400 access_denied).
#   9. POST /oauth/complete happy path: tokens stored, JSON response.
#  10. Lock-acquire failures surface as transient AUTH_ERROR — never unlocked.


# ── Helpers ───────────────────────────────────────────────────────────────────


def _pending_integration(account_id=ACCOUNT_ID, nonce="test-nonce-abc"):
    """Minimal CONNECTING integration as stored by start_oauth_authorization."""
    itype = IntegrationType(
        slug="acme-oauth",
        name="Acme OAuth",
        provider="acme",
        auth_type="oauth2_authorization_code",
    )
    itype.set_auth_config(
        {
            "base_url": "https://acme.test",
            "token_endpoint": "https://acme.test/oauth/token",
        }
    )
    integ = AccountIntegration()
    integ.id = _new_iid()
    integ.account_id = account_id
    integ.status = IntegrationStatus.CONNECTING
    integ.integration_type = itype
    integ.set_credentials({"client_id": "cid", "client_secret": "csec"})
    from botelier.api.integrations import _OAUTH_STATE_NONCE_KEY
    integ.set_connection_config({_OAUTH_STATE_NONCE_KEY: nonce})
    return integ


def _make_db_mock(integ):
    db = MagicMock()
    # Handles query with joinedload (options): used in the main completion path.
    db.query.return_value.options.return_value.filter.return_value.first.return_value = integ
    # Handles plain query (no options): used in the provider-error best-effort path.
    db.query.return_value.filter.return_value.first.return_value = integ
    return db


def _make_state(account_id, integ, nonce):
    """Build a 3-segment state: {account_id}:{integration_id}:{nonce}."""
    return f"{account_id}:{integ.id}:{nonce}"


# ── 1. Authorize response: no cookie, JSON body ───────────────────────────────


@pytest.mark.asyncio
async def test_authorize_response_returns_json_no_cookie(monkeypatch):
    """start_oauth_authorization returns plain JSON — no Set-Cookie header.

    The old two-hop design set a browser-binding cookie.  The new design
    drops it entirely: security is delegated to the authenticated POST
    /oauth/complete endpoint (Bearer token required).
    """
    import uuid as _uuid_mod
    from botelier.api.integrations import (
        OAuthAuthorizeRequest,
        _OAUTH_STATE_NONCE_KEY,
        start_oauth_authorization,
    )

    itype = IntegrationType(
        slug="acme-oauth",
        name="Acme",
        provider="acme",
        auth_type="oauth2_authorization_code",
    )
    itype.set_auth_config({
        "base_url": "https://acme.test",
        "authorization_endpoint": "https://acme.test/oauth/authorize",
        "token_endpoint": "https://acme.test/oauth/token",
    })

    db_mock = MagicMock()
    db_mock.query.return_value.filter.return_value.first.return_value = itype
    added: list = []
    db_mock.add.side_effect = lambda obj: added.append(obj)

    def _commit():
        for obj in added:
            if not hasattr(obj, "_id_set"):
                obj.id = _uuid_mod.uuid4()
                obj._id_set = True

    db_mock.commit.side_effect = _commit

    monkeypatch.setattr(
        "botelier.api.integrations._oauth_redirect_uri",
        lambda: "https://api.botelier.test/api/integrations/oauth/callback",
    )
    monkeypatch.setattr(
        "botelier.api.integrations.property_belongs_to_account",
        lambda db, account_id, property_id: True,
    )
    monkeypatch.setattr(
        "botelier.api.integrations._assert_account_access",
        lambda *a, **kw: None,
    )

    req = OAuthAuthorizeRequest(
        integration_type_id=str(_uuid_mod.uuid4()),
        credentials={"client_id": "cid"},
        connection_name="Test",
        property_id=None,
    )

    resp = await start_oauth_authorization(
        account_id=ACCOUNT_ID,
        request=req,
        current_user=MagicMock(),
        db=db_mock,
    )

    # Must be a plain dict (FastAPI serialises it to JSON — no Response wrapper).
    assert isinstance(resp, dict), f"Expected dict response; got {type(resp)}"
    assert "authorization_url" in resp, f"Missing authorization_url: {resp}"
    assert "integration_id" in resp, f"Missing integration_id: {resp}"

    # State must be 3 segments only — no user-controlled b64 origin segment.
    from urllib.parse import urlparse, parse_qs
    auth_url = resp["authorization_url"]
    qs = parse_qs(urlparse(auth_url).query)
    state_val = qs.get("state", [""])[0]
    assert state_val.count(":") == 2, (
        f"Expected 3-segment state (account:integration:nonce); got {state_val!r}"
    )

    # Nonce must be stashed in connection_config.
    integration = added[0]
    conn_cfg = integration.get_connection_config() or {}
    assert _OAUTH_STATE_NONCE_KEY in conn_cfg, "Nonce not stored in connection_config"


# ── 2. /oauth/callback: hop uses only configured FRONTEND_URL ─────────────────
#
# These tests use a real ASGI client (httpx.AsyncClient + ASGITransport) against
# the actual integrations router, exercising real HTTP routing — not a bare
# function call.  This catches route-level issues and pins the invariant that
# the hop target is configuration-driven, never request-driven.


@pytest.mark.asyncio
async def test_oauth_callback_hops_to_configured_frontend_url(monkeypatch):
    """When FRONTEND_URL is set in env, /oauth/callback MUST 302 to
    {FRONTEND_URL}/dashboard/integrations/oauth/complete.

    This pins the fix for the broken-topology regression: in deployments where
    PUBLIC_BASE_URL (API host) differs from the dashboard host, the old
    two-hop used the Origin header (user-controlled) to pick the target.
    The new design uses only server configuration.

    Topology simulated
    ------------------
    API host:   https://api.botelier.test   ← where /oauth/callback lives
    FRONTEND_URL: https://app.botelier.test ← configured server-side only
    """
    from httpx import ASGITransport, AsyncClient
    from fastapi import FastAPI
    from botelier.api.integrations import router as integrations_router

    mini_app = FastAPI()
    mini_app.include_router(integrations_router)

    configured_frontend = "https://app.botelier.test"
    api_origin = "https://api.botelier.test"

    monkeypatch.setenv("FRONTEND_URL", configured_frontend)
    # Ensure the cached value in the domain module reflects the env change.
    monkeypatch.setattr(
        "botelier.api.integrations.get_frontend_url",
        lambda: configured_frontend,
    )

    nonce = "topology-test-nonce"
    integration_id = str(uuid.uuid4())
    account_id_val = str(uuid.uuid4())
    state = f"{account_id_val}:{integration_id}:{nonce}"

    async with AsyncClient(
        transport=ASGITransport(app=mini_app),
        base_url=api_origin,
        follow_redirects=False,
    ) as client:
        resp = await client.get(
            "/api/integrations/oauth/callback",
            params={"code": "authcode123", "state": state},
        )

    assert resp.status_code == 302, f"Expected 302; got {resp.status_code}"
    location = resp.headers.get("location", "")

    # Must go to the configured frontend + completion page path.
    expected_prefix = f"{configured_frontend}/dashboard/integrations/oauth/complete"
    assert location.startswith(expected_prefix), (
        f"Expected hop to {expected_prefix!r}; got {location!r}"
    )

    # The API origin must NOT appear as the target.
    assert not location.startswith(api_origin), (
        f"Hop went to API origin — would fail without user session cookie: {location!r}"
    )

    assert "code=authcode123" in location, f"code not forwarded: {location!r}"
    assert "state=" in location, f"state not forwarded: {location!r}"


@pytest.mark.asyncio
async def test_oauth_callback_target_ignores_request_origin_header(monkeypatch):
    """The hop target must NOT change when an attacker supplies a hostile Origin
    header — the redirect destination is pinned to server configuration only.
    """
    from httpx import ASGITransport, AsyncClient
    from fastapi import FastAPI
    from botelier.api.integrations import router as integrations_router

    mini_app = FastAPI()
    mini_app.include_router(integrations_router)

    configured_frontend = "https://legit.botelier.test"
    attacker_origin = "https://evil.attacker.test"

    monkeypatch.setattr(
        "botelier.api.integrations.get_frontend_url",
        lambda: configured_frontend,
    )

    state = f"{uuid.uuid4()}:{uuid.uuid4()}:somonce"

    async with AsyncClient(
        transport=ASGITransport(app=mini_app),
        base_url="https://api.botelier.test",
        follow_redirects=False,
    ) as client:
        resp = await client.get(
            "/api/integrations/oauth/callback",
            params={"code": "code", "state": state},
            headers={"Origin": attacker_origin},
        )

    location = resp.headers.get("location", "")
    assert not location.startswith(attacker_origin), (
        f"Hop used request Origin as target — open redirect: {location!r}"
    )
    assert location.startswith(configured_frontend), (
        f"Expected configured frontend as target; got {location!r}"
    )


# ── 3. POST /oauth/complete: authenticated endpoint ───────────────────────────


@pytest.mark.asyncio
async def test_oauth_complete_rejects_unauthenticated(monkeypatch):
    """POST /oauth/complete without a Bearer token must return 401.

    Uses a real ASGI client so the auth middleware (get_current_user) actually
    runs — a function-level call would bypass it.
    """
    from httpx import ASGITransport, AsyncClient
    from fastapi import FastAPI
    from botelier.api.integrations import router as integrations_router

    # get_current_user is a FastAPI dependency on the endpoint itself — the
    # mini-app is sufficient to exercise it; no extra middleware needed.
    mini_app = FastAPI()
    mini_app.include_router(integrations_router)

    # Ensure get_current_user raises 401 for missing token (it normally does).
    # We simply send no Authorization header and assert the response.
    async with AsyncClient(
        transport=ASGITransport(app=mini_app),
        base_url="https://api.botelier.test",
        follow_redirects=False,
    ) as client:
        resp = await client.post(
            "/api/integrations/oauth/complete",
            json={"code": "code", "state": f"{uuid.uuid4()}:{uuid.uuid4()}:nonce"},
        )

    # No auth header → 401 from get_current_user dependency.
    assert resp.status_code == 401, (
        f"Expected 401 for unauthenticated call; got {resp.status_code}"
    )


@pytest.mark.asyncio
async def test_oauth_complete_rejects_mismatched_account(monkeypatch):
    """POST /oauth/complete with a user from a different account is rejected 403."""
    from fastapi import HTTPException
    from botelier.api.integrations import OAuthCompleteRequest, oauth_complete, _OAUTH_STATE_NONCE_KEY

    nonce = "nonce-account-mismatch"
    integ = _pending_integration(account_id=ACCOUNT_ID, nonce=nonce)
    state = _make_state(OTHER_ACCOUNT_ID, integ, nonce)  # state claims OTHER_ACCOUNT_ID

    # _assert_account_access raises 403 when the user has no access.
    def _deny(*a, **kw):
        raise HTTPException(status_code=403, detail="Forbidden")

    monkeypatch.setattr("botelier.api.integrations._assert_account_access", _deny)

    with pytest.raises(HTTPException) as exc_info:
        await oauth_complete(
            request=OAuthCompleteRequest(code="code", state=state),
            current_user=MagicMock(),
            db=_make_db_mock(integ),
        )

    assert exc_info.value.status_code == 403
    assert "account_mismatch" in exc_info.value.detail


@pytest.mark.asyncio
async def test_oauth_complete_rejects_wrong_nonce(monkeypatch):
    """POST /oauth/complete with a wrong nonce returns 400 invalid_state."""
    from fastapi import HTTPException
    from botelier.api.integrations import OAuthCompleteRequest, oauth_complete

    correct_nonce = "the-real-nonce"
    integ = _pending_integration(account_id=ACCOUNT_ID, nonce=correct_nonce)
    state = _make_state(ACCOUNT_ID, integ, "WRONG-NONCE")

    monkeypatch.setattr(
        "botelier.api.integrations._assert_account_access", lambda *a, **kw: None
    )

    with pytest.raises(HTTPException) as exc_info:
        await oauth_complete(
            request=OAuthCompleteRequest(code="code", state=state),
            current_user=MagicMock(),
            db=_make_db_mock(integ),
        )

    assert exc_info.value.status_code == 400
    assert "invalid_state" in exc_info.value.detail


@pytest.mark.asyncio
async def test_oauth_complete_rejects_provider_error(monkeypatch):
    """POST /oauth/complete with a provider error param stamps ERROR and raises."""
    from fastapi import HTTPException
    from botelier.api.integrations import OAuthCompleteRequest, oauth_complete, _OAUTH_STATE_NONCE_KEY

    nonce = "nonce-provider-error"
    integ = _pending_integration(account_id=ACCOUNT_ID, nonce=nonce)
    state = _make_state(ACCOUNT_ID, integ, nonce)

    monkeypatch.setattr(
        "botelier.api.integrations._assert_account_access", lambda *a, **kw: None
    )

    with pytest.raises(HTTPException) as exc_info:
        await oauth_complete(
            request=OAuthCompleteRequest(error="access_denied", state=state),
            current_user=MagicMock(),
            db=_make_db_mock(integ),
        )

    assert exc_info.value.status_code == 400
    assert "access_denied" in exc_info.value.detail
    # Integration status should be stamped ERROR.
    assert integ.status == IntegrationStatus.ERROR
    # Nonce cleared so the state cannot be replayed.
    assert _OAUTH_STATE_NONCE_KEY not in (integ.get_connection_config() or {})


@pytest.mark.asyncio
async def test_oauth_complete_happy_path(monkeypatch):
    """POST /oauth/complete: all checks pass → tokens stored, JSON response."""
    from botelier.api.integrations import (
        OAuthCompleteRequest,
        _OAUTH_STATE_NONCE_KEY,
        oauth_complete,
    )

    nonce = "nonce-happy-path"
    integ = _pending_integration(account_id=ACCOUNT_ID, nonce=nonce)
    state = _make_state(ACCOUNT_ID, integ, nonce)

    monkeypatch.setattr(
        "botelier.api.integrations._assert_account_access", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "botelier.api.integrations._oauth_redirect_uri",
        lambda: "https://api.botelier.test/api/integrations/oauth/callback",
    )

    async def _fake_exchange(itype, credentials, code, redirect_uri):
        return {
            "success": True,
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        }

    monkeypatch.setattr(
        "botelier.api.integrations.exchange_authorization_code", _fake_exchange
    )

    result = await oauth_complete(
        request=OAuthCompleteRequest(code="goodcode", state=state),
        current_user=MagicMock(),
        db=_make_db_mock(integ),
    )

    # Returns a JSON-serialisable dict, not a redirect.
    assert isinstance(result, dict), f"Expected dict; got {type(result)}"
    assert result["status"] == "connected"
    assert result["integration_id"] == str(integ.id)

    # Tokens stored and status flipped to CONNECTED.
    assert integ.status == IntegrationStatus.CONNECTED
    assert integ.get_access_token() == "new-access-token"

    # One-time nonce consumed.
    assert _OAUTH_STATE_NONCE_KEY not in (integ.get_connection_config() or {})


# ── 5. Cross-tenant DoS regression: error= blocked before integration is touched ──
#
# This test uses a real ASGI client with real FastAPI dependency injection.
# get_current_user is overridden via dependency_overrides (standard FastAPI testing
# practice; we cannot mint a real JWT in unit tests) but _assert_account_access and
# check_account_permission are NOT stubbed — they run for real with a mock DB whose
# AccountMembership query returns None for the target account, exactly as it would in
# production when a user from account B requests access to account A's integration.
#
# The regression being pinned:
#   Before the fix, the provider-error branch ran BEFORE state parsing and account
#   authorization.  Any authenticated caller who knew (or guessed) a pending
#   integration UUID could send error="anything" with a fabricated 3-segment state
#   and mutate the target integration's status to ERROR and burn its one-time nonce
#   (cross-tenant DoS).  After the fix, account authorization runs first — the
#   call is rejected 403 before the integration row is loaded or modified.


@pytest.mark.asyncio
async def test_cross_tenant_error_cannot_mutate_integration_or_burn_nonce():
    """A user authenticated to account B cannot mark account A's integration ERROR
    or consume its nonce by supplying error= in POST /oauth/complete.

    _assert_account_access / check_account_permission run with real logic via
    a mock DB that returns no AccountMembership for the target account — no
    stubbing of the authorization layer.
    """
    import json as _json
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from unittest.mock import MagicMock
    from botelier.api.integrations import router as integrations_router, _OAUTH_STATE_NONCE_KEY
    from botelier.auth.middleware import get_current_user
    from botelier.database import get_db
    from botelier.models.user import User, UserType

    # ── Target integration (belongs to ACCOUNT_ID, the account under attack) ──
    nonce = "precious-one-time-nonce"
    target_integ = _pending_integration(account_id=ACCOUNT_ID, nonce=nonce)
    initial_status = target_integ.status  # CONNECTING

    # ── Attacker: authenticated user who belongs to OTHER_ACCOUNT_ID, NOT ACCOUNT_ID ──
    attacker_user = MagicMock(spec=User)
    attacker_user.id = uuid.uuid4()
    attacker_user.is_platform_admin = False
    attacker_user.is_active = True
    attacker_user.user_type = UserType.ACCOUNT_USER

    # ── Mock DB: check_account_permission queries AccountMembership ──────────
    # Returns None for the membership query so the permission check raises 403.
    # The integration load query is set up (but must never be reached).
    mock_db = MagicMock()
    # AccountMembership query → None (attacker has no access to ACCOUNT_ID)
    mock_db.query.return_value.filter.return_value.first.return_value = None
    # Joinedload query (used for the integration load — must not be reached)
    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = target_integ

    # ── Mini-app with dependency overrides ───────────────────────────────────
    mini_app = FastAPI()
    mini_app.include_router(integrations_router)
    mini_app.dependency_overrides[get_current_user] = lambda: attacker_user
    mini_app.dependency_overrides[get_db] = lambda: mock_db

    # Attacker crafts state claiming ACCOUNT_ID, with target_integ's UUID.
    attacker_state = f"{ACCOUNT_ID}:{target_integ.id}:{nonce}"

    async with AsyncClient(
        transport=ASGITransport(app=mini_app),
        base_url="https://api.botelier.test",
        follow_redirects=False,
    ) as client:
        resp = await client.post(
            "/api/integrations/oauth/complete",
            content=_json.dumps({"error": "access_denied", "state": attacker_state}),
            headers={"Content-Type": "application/json"},
        )

    # Must be rejected — account authorization blocks before touching the row.
    assert resp.status_code == 403, (
        f"Expected 403 account_mismatch; got {resp.status_code}: {resp.text}"
    )

    # Integration status MUST be unchanged — attacker cannot stamp ERROR.
    assert target_integ.status == initial_status, (
        f"Integration status mutated from {initial_status!r} to "
        f"{target_integ.status!r} — cross-tenant DoS not fixed"
    )

    # Nonce MUST still be present — attacker cannot burn it.
    surviving_conn_cfg = target_integ.get_connection_config() or {}
    assert _OAUTH_STATE_NONCE_KEY in surviving_conn_cfg, (
        "Nonce was consumed before authorization check — one-time nonce burned by attacker"
    )
    assert surviving_conn_cfg[_OAUTH_STATE_NONCE_KEY] == nonce, (
        f"Nonce value changed: expected {nonce!r}, got {surviving_conn_cfg[_OAUTH_STATE_NONCE_KEY]!r}"
    )

    # DB commit must NOT have been called.
    mock_db.commit.assert_not_called()


# ── 6. Lock-acquire failures raise — never fall through to unlocked refresh ───


@pytest.mark.asyncio
async def test_refresh_lock_raises_on_connect_failure_after_retries(monkeypatch):
    """engine.connect() failing on every attempt raises TokenRefreshLockUnavailableError."""
    import botelier.services.integration_runtime.client as _client_mod
    import botelier.database as _db_mod

    integ = _oauth_integration()
    client = _client_with(integ)

    slept: list[float] = []

    async def _fake_sleep(d: float) -> None:
        slept.append(d)

    monkeypatch.setattr(_client_mod.asyncio, "sleep", _fake_sleep)

    call_count = {"n": 0}

    def _boom():
        call_count["n"] += 1
        raise Exception("db connection refused")

    # engine is imported locally inside _refresh_token_with_lock via
    # ``from botelier.database import engine``, so patch the source object.
    monkeypatch.setattr(_db_mod.engine, "connect", _boom)

    with pytest.raises(TokenRefreshLockUnavailableError, match="db connection refused"):
        await client._refresh_token_with_lock(integ)

    # connect() called _LOCK_ACQUIRE_RETRIES + 1 times total.
    assert call_count["n"] == _LOCK_ACQUIRE_RETRIES + 1
    # Slept between each attempt: _LOCK_ACQUIRE_RETRIES sleeps.
    assert len(slept) == _LOCK_ACQUIRE_RETRIES
    # Backoff values follow the exponential schedule.
    assert slept[0] == pytest.approx(_LOCK_ACQUIRE_BACKOFF_S)
    assert slept[1] == pytest.approx(_LOCK_ACQUIRE_BACKOFF_S * 2)


@pytest.mark.asyncio
async def test_refresh_lock_raises_on_execute_failure_after_retries(monkeypatch):
    """pg_try_advisory_lock execute failure raises TokenRefreshLockUnavailableError."""
    import botelier.services.integration_runtime.client as _client_mod
    import botelier.database as _db_mod

    integ = _oauth_integration()
    client = _client_with(integ)

    slept: list[float] = []

    async def _fake_sleep(d: float) -> None:
        slept.append(d)

    monkeypatch.setattr(_client_mod.asyncio, "sleep", _fake_sleep)

    execute_count = {"n": 0}

    class _BadConn:
        def execute(self, *a, **kw):
            execute_count["n"] += 1
            raise Exception("advisory lock execute error")

        def close(self):
            pass

        def invalidate(self):
            pass

    monkeypatch.setattr(_db_mod.engine, "connect", lambda: _BadConn())

    with pytest.raises(TokenRefreshLockUnavailableError, match="advisory lock execute error"):
        await client._refresh_token_with_lock(integ)

    # execute() attempted _LOCK_ACQUIRE_RETRIES + 1 times.
    assert execute_count["n"] == _LOCK_ACQUIRE_RETRIES + 1
    assert len(slept) == _LOCK_ACQUIRE_RETRIES


@pytest.mark.asyncio
async def test_execute_request_surfaces_lock_error_as_auth_error_no_breaker(monkeypatch):
    """Lock unavailability is surfaced as a transient AUTH_ERROR; circuit stays closed."""
    import botelier.services.integration_runtime.client as _client_mod
    import botelier.database as _db_mod

    iid = _new_iid()
    # Use an oauth2_authorization_code integration so needs_token=True.
    integ = _oauth_integration()
    integ.id = iid
    # Force token_expires_at to trigger a refresh attempt.
    integ.token_expires_at = datetime.utcnow() - timedelta(hours=1)

    client = _client_with(integ)

    # Stub out sleep to avoid real delays.
    async def _fake_sleep(d: float) -> None:
        pass

    monkeypatch.setattr(_client_mod.asyncio, "sleep", _fake_sleep)

    # Make engine.connect() always fail so the lock is unavailable.
    monkeypatch.setattr(_db_mod.engine, "connect", lambda: (_ for _ in ()).throw(Exception("db down")))

    result = await client.execute_request(
        IntegrationAPIConfig(
            integration_id=str(integ.id), endpoint_id="ping", method="GET"
        ),
        {},
    )

    assert result.success is False
    assert result.error_type == APIErrorType.AUTH_ERROR
    assert "temporarily unavailable" in (result.error_message or "").lower()

    # Circuit breaker must NOT have been tripped — the breaker checks the
    # provider, not our DB; the integration id is fresh so state is CLOSED.
    conf = ResilienceConfig()
    allowed, state = circuit_allow(iid, ACCOUNT_ID, conf)
    assert allowed is True


@pytest.mark.asyncio
async def test_forced_401_refresh_lock_error_surfaces_as_auth_error_no_breaker(monkeypatch):
    """TokenRefreshLockUnavailableError on the 401/403 forced-refresh path
    surfaces as a clear transient AUTH_ERROR and does NOT trip the breaker.

    The 401 forced-refresh is a second call to _refresh_token_with_lock that
    lives INSIDE the retry loop — distinct from the proactive pre-request
    refresh handled in the first fix round.  This test specifically exercises
    that code path.
    """
    import botelier.services.integration_runtime.client as _client_mod
    import botelier.database as _db_mod

    iid = _new_iid()

    # Build a token-auth integration (DefaultAdapter + login_endpoint strategy)
    # whose token is NOT yet expired so the proactive refresh is skipped but
    # the 401 from the provider triggers the forced-refresh path.
    itype = IntegrationType(
        slug="jwt-api",
        name="JWT API",
        provider="jwt",
        auth_type="default",
    )
    itype.set_auth_config({
        "base_url": "https://jwt-api.test",
        "auth_strategy": "login_endpoint",
    })
    itype.set_endpoints([{
        "id": "ping",
        "path": "/ping",
        "method": "GET",
        "description": "ping",
    }])
    integ = AccountIntegration()
    integ.id = iid
    integ.account_id = ACCOUNT_ID
    integ.status = IntegrationStatus.CONNECTED
    integ.integration_type = itype
    integ.set_credentials({})
    # Token is fresh — proactive refresh skipped.
    integ.token_expires_at = datetime.utcnow() + timedelta(hours=1)
    integ.set_access_token("valid-token")

    client = _client_with(integ)

    async def _fake_sleep(d: float) -> None:
        pass

    monkeypatch.setattr(_client_mod.asyncio, "sleep", _fake_sleep)

    # Provider returns 401 → triggers forced refresh → engine.connect() fails.
    call_n = {"n": 0}

    def _responder(req):
        call_n["n"] += 1
        return httpx.Response(401, json={"error": "token_expired"})

    _install_capture(monkeypatch, _responder)

    # engine.connect() always fails → _refresh_token_with_lock raises.
    monkeypatch.setattr(
        _db_mod.engine,
        "connect",
        lambda: (_ for _ in ()).throw(Exception("db degraded")),
    )

    result = await client.execute_request(
        IntegrationAPIConfig(
            integration_id=str(integ.id), endpoint_id="ping", method="GET"
        ),
        {},
    )

    # Must return transient AUTH_ERROR — not a 500 / unhandled exception.
    assert result.success is False
    assert result.error_type == APIErrorType.AUTH_ERROR
    assert "temporarily unavailable" in (result.error_message or "").lower()

    # Only one outbound HTTP attempt: after the 401 the lock error short-circuits
    # before a retry is issued.
    assert call_n["n"] == 1

    # Circuit breaker must stay CLOSED.
    allowed, _st = circuit_allow(iid, ACCOUNT_ID, ResilienceConfig())
    assert allowed is True
