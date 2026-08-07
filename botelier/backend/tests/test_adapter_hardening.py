"""Tests for Task #463 — API tool adapter hardening (connect → test → channels).

Covers the runtime guardrails added to the certified integration client and
the legacy custom-HTTP executor:

  • URL path substitution is URL-encoded (no "/", "?", "#" injection).
  • Config/draft headers can never override adapter auth headers.
  • timeout / retry_count are clamped to sane bounds.
  • Response bodies are capped at the transport level (pre-parse).
  • Rendered request bodies are capped.
  • Legacy 429 responses normalize to RATE_LIMITED.
  • Legacy executor supports HEAD/OPTIONS.
  • Published tool slugs are a fixed point of sanitize_function_name.
"""

import uuid
from unittest.mock import MagicMock

import httpx
import pytest
from cryptography.fernet import Fernet

from botelier import crypto
from botelier.database import Base, engine
from botelier.models.integration import (
    AccountIntegration,
    IntegrationStatus,
    IntegrationType,
)
from botelier.models.integration_resilience import (  # noqa: F401 - registers tables
    IntegrationCircuitBreaker,
    IntegrationRateLimit,
)
from botelier.services.integration_client import IntegrationAPIConfig, IntegrationClient
from botelier.services.integration_runtime.types import APIErrorType
from botelier.utils import sanitize_function_name

ACCOUNT_ID = "00000000-0000-0000-0000-000000000063"


@pytest.fixture(scope="module", autouse=True)
def _ensure_tables():
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


def _bearer_integration(*, path="/items/{{item_id}}", method="GET"):
    """A customer-imported style integration using the bearer strategy."""
    itype = IntegrationType(
        slug="importedapi", name="Imported", provider="custom", auth_type="none"
    )
    itype.set_auth_config(
        {"base_url": "https://api.imported.test", "auth_strategy": "bearer"}
    )
    itype.set_endpoints(
        [
            {
                "id": "op1",
                "path": path,
                "method": method,
                "description": "op1",
            }
        ]
    )
    integ = AccountIntegration()
    integ.id = uuid.uuid4()
    integ.account_id = ACCOUNT_ID
    integ.status = IntegrationStatus.CONNECTED
    integ.integration_type = itype
    integ.set_credentials({"token": "real-token"})
    return integ


def _client_with(integ):
    client = IntegrationClient(account_id=ACCOUNT_ID, db=MagicMock())
    client._integration_cache[str(integ.id)] = integ
    return client


# ── URL path encoding ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_path_substitution_url_encodes_variables(monkeypatch):
    integ = _bearer_integration()
    client = _client_with(integ)
    captured = _install_capture(monkeypatch, lambda _r: httpx.Response(200, json={}))

    config = IntegrationAPIConfig(
        integration_id=str(integ.id), endpoint_id="op1", method="GET"
    )
    result = await client.execute_request(config, {"item_id": "a/b?c=1#frag"})

    assert result.success is True
    url = str(captured[0].url)
    # The raw separators must not appear; the value stays one path segment.
    assert "a%2Fb%3Fc%3D1%23frag" in url
    assert "?" not in url


@pytest.mark.asyncio
async def test_hotel_id_path_substitution_is_encoded(monkeypatch):
    integ = _bearer_integration(path="/hotels/{{hotel_id}}/rooms")
    integ.set_connection_config({"hotel_id": "H/1"})
    client = _client_with(integ)
    captured = _install_capture(monkeypatch, lambda _r: httpx.Response(200, json={}))

    config = IntegrationAPIConfig(
        integration_id=str(integ.id), endpoint_id="op1", method="GET"
    )
    result = await client.execute_request(config, {})

    assert result.success is True
    assert "/hotels/H%2F1/rooms" in str(captured[0].url)


# ── Auth header precedence ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_config_headers_cannot_override_auth_headers(monkeypatch):
    integ = _bearer_integration(path="/ping")
    client = _client_with(integ)
    captured = _install_capture(monkeypatch, lambda _r: httpx.Response(200, json={}))

    config = IntegrationAPIConfig(
        integration_id=str(integ.id),
        endpoint_id="op1",
        method="GET",
        # Case-insensitive spoof attempt via stored config headers.
        headers={"authorization": "Bearer attacker", "X-Extra": "kept"},
    )
    result = await client.execute_request(config, {})

    assert result.success is True
    req = captured[0]
    assert req.headers["Authorization"] == "Bearer real-token"
    assert req.headers["X-Extra"] == "kept"


# ── Clamps ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_timeout_and_retry_count_are_clamped(monkeypatch):
    integ = _bearer_integration(path="/ping")
    client = _client_with(integ)
    _install_capture(monkeypatch, lambda _r: httpx.Response(200, json={}))

    config = IntegrationAPIConfig(
        integration_id=str(integ.id),
        endpoint_id="op1",
        method="GET",
        timeout=9999,
        retry_count=99,
    )
    result = await client.execute_request(config, {})

    assert result.success is True
    assert config.timeout == 60
    assert config.retry_count == 5


@pytest.mark.asyncio
async def test_non_numeric_timeout_falls_back(monkeypatch):
    integ = _bearer_integration(path="/ping")
    client = _client_with(integ)
    _install_capture(monkeypatch, lambda _r: httpx.Response(200, json={}))

    config = IntegrationAPIConfig(
        integration_id=str(integ.id),
        endpoint_id="op1",
        method="GET",
        timeout="not-a-number",  # type: ignore[arg-type]
        retry_count=-3,
    )
    result = await client.execute_request(config, {})

    assert result.success is True
    assert config.timeout == 30
    assert config.retry_count == 0


# ── Response size cap ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oversized_response_is_rejected_pre_parse(monkeypatch):
    monkeypatch.setattr(
        "botelier.services.integration_runtime.client._MAX_RESPONSE_BYTES", 1024
    )
    integ = _bearer_integration(path="/ping")
    client = _client_with(integ)
    captured = _install_capture(
        monkeypatch, lambda _r: httpx.Response(200, content=b"x" * 4096)
    )

    config = IntegrationAPIConfig(
        integration_id=str(integ.id), endpoint_id="op1", method="GET", retry_count=3
    )
    result = await client.execute_request(config, {})

    assert result.success is False
    assert result.error_type == APIErrorType.SERVER_ERROR
    assert "exceeded" in (result.error_message or "").lower()
    # Oversized bodies are not retried — same size next time.
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_normal_response_still_parses_after_streaming(monkeypatch):
    integ = _bearer_integration(path="/ping")
    client = _client_with(integ)
    _install_capture(monkeypatch, lambda _r: httpx.Response(200, json={"ok": True}))

    config = IntegrationAPIConfig(
        integration_id=str(integ.id), endpoint_id="op1", method="GET"
    )
    result = await client.execute_request(config, {})

    assert result.success is True
    assert result.data == {"ok": True}


class _CountingStream(httpx.AsyncByteStream):
    """A stream that counts how many chunks were actually pulled."""

    def __init__(self, chunk: bytes, n: int):
        self.chunk = chunk
        self.n = n
        self.pulled = 0

    async def __aiter__(self):
        for _ in range(self.n):
            self.pulled += 1
            yield self.chunk

    async def aclose(self):
        pass


def _install_streaming(monkeypatch, headers: dict, stream: _CountingStream):
    """Patch httpx.AsyncClient with a transport that returns a true async stream."""
    real_async_client = httpx.AsyncClient

    class _StreamTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(200, headers=headers, stream=stream)

    class _StreamingAsyncClient(real_async_client):
        def __init__(self, *args, **kwargs):
            kwargs.pop("transport", None)
            super().__init__(*args, transport=_StreamTransport(), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _StreamingAsyncClient)


@pytest.mark.asyncio
async def test_declared_content_length_rejected_before_reading_body(monkeypatch):
    """An oversized Content-Length must be rejected without pulling any bytes."""
    monkeypatch.setattr(
        "botelier.services.integration_runtime.client._MAX_RESPONSE_BYTES", 4096
    )
    integ = _bearer_integration(path="/ping")
    client = _client_with(integ)
    stream = _CountingStream(b"x" * 1024, n=1000)
    _install_streaming(monkeypatch, {"content-length": "99999999"}, stream)

    config = IntegrationAPIConfig(
        integration_id=str(integ.id), endpoint_id="op1", method="GET"
    )
    result = await client.execute_request(config, {})

    assert result.success is False
    assert "exceeded" in (result.error_message or "").lower()
    assert stream.pulled == 0  # precheck fired before any body read


@pytest.mark.asyncio
async def test_chunked_stream_is_cancelled_at_the_cap(monkeypatch):
    """A chunked (no Content-Length) stream must stop reading at the cap."""
    monkeypatch.setattr(
        "botelier.services.integration_runtime.client._MAX_RESPONSE_BYTES", 4096
    )
    integ = _bearer_integration(path="/ping")
    client = _client_with(integ)
    stream = _CountingStream(b"x" * 1024, n=1000)
    _install_streaming(monkeypatch, {}, stream)

    config = IntegrationAPIConfig(
        integration_id=str(integ.id), endpoint_id="op1", method="GET"
    )
    result = await client.execute_request(config, {})

    assert result.success is False
    assert "exceeded" in (result.error_message or "").lower()
    # Cap is 4 chunks (4096B) — the read must stop right after crossing it,
    # not drain all 1000 chunks.
    assert stream.pulled <= 6


# ── Spec-derived origin validation ────────────────────────────────────────────


def test_validate_imported_origin_rejects_unsafe_origins():
    from fastapi import HTTPException

    from botelier.api.integration_builder import _validate_imported_origin

    # Public IP literal passes (no DNS needed).
    _validate_imported_origin("https://8.8.8.8/api")

    for bad in [
        "ftp://api.example.com",  # scheme
        "https://user:pw@8.8.8.8",  # embedded credentials
        "https://127.0.0.1:8080",  # loopback
        "https://169.254.169.254",  # metadata endpoint
        "https://10.1.2.3",  # RFC-1918
        "not-a-url",  # no scheme/host
    ]:
        with pytest.raises(HTTPException):
            _validate_imported_origin(bad)


# ── Request body cap ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oversized_rendered_body_is_validation_error(monkeypatch):
    monkeypatch.setattr(
        "botelier.services.integration_runtime.client._MAX_BODY_BYTES", 64
    )
    integ = _bearer_integration(path="/ping", method="POST")
    client = _client_with(integ)
    captured = _install_capture(monkeypatch, lambda _r: httpx.Response(200, json={}))

    config = IntegrationAPIConfig(
        integration_id=str(integ.id),
        endpoint_id="op1",
        method="POST",
        body_template='{"blob": "{{blob}}"}',
    )
    result = await client.execute_request(config, {"blob": "y" * 500})

    assert result.success is False
    assert result.error_type == APIErrorType.VALIDATION_ERROR
    assert captured == []  # rejected before any outbound request


# ── Legacy executor normalization ─────────────────────────────────────────────


def test_legacy_429_maps_to_rate_limited():
    from botelier.services.action_executor import ActionExecutor

    executor = ActionExecutor(MagicMock())
    response = httpx.Response(429, json={"message": "slow down"})
    result = executor._process_http_response(response, {}, "rid", 0)

    assert result.success is False
    assert result.error_type == APIErrorType.RATE_LIMITED


@pytest.mark.asyncio
async def test_legacy_executor_supports_head_and_options(monkeypatch):
    from botelier.services.action_executor import ActionContext, ActionExecutor

    executor = ActionExecutor(MagicMock())
    captured = _install_capture(monkeypatch, lambda _r: httpx.Response(200, json={}))

    for method in ("HEAD", "OPTIONS"):
        result = await executor._execute_custom_http(
            {"method": method, "url": "https://api.custom.test/ping"},
            {},
            ActionContext(account_id=ACCOUNT_ID, channel="test"),
            "rid",
            0,
        )
        assert result.success is True

    assert [r.method for r in captured] == ["HEAD", "OPTIONS"]


@pytest.mark.asyncio
async def test_legacy_retry_count_is_clamped(monkeypatch):
    """A huge stored retryCount must not spin dozens of attempts."""
    from botelier.services.action_executor import ActionContext, ActionExecutor

    executor = ActionExecutor(MagicMock())

    calls = {"n": 0}

    def _responder(_r):
        calls["n"] += 1
        raise httpx.ConnectError("boom")

    _install_capture(monkeypatch, _responder)

    result = await executor._execute_custom_http(
        {"method": "GET", "url": "https://api.custom.test/ping", "retryCount": 500},
        {},
        ActionContext(account_id=ACCOUNT_ID, channel="test"),
        "rid",
        0,
    )
    assert result.success is False
    assert calls["n"] == 6  # 1 initial + max 5 retries


# ── Tested ↔ published request-shape parity ───────────────────────────────────


def test_normalize_request_overrides_shapes_and_clamps():
    from botelier.services.operation_publisher import normalize_request_overrides

    assert normalize_request_overrides(None) == {}
    assert normalize_request_overrides({}) == {}

    out = normalize_request_overrides(
        {
            "headers": {"X-Env": "prod"},
            "content_type": "application/xml",
            "body_template": {"a": 1},  # non-str → json-dumped
            "timeout": 999,
            "retry_count": -4,
        }
    )
    assert out["headers"] == {"X-Env": "prod", "Content-Type": "application/xml"}
    assert out["body_template"] == '{"a": 1}'
    assert out["timeout"] == 30
    assert out["retry_count"] == 0

    # Idempotent: normalizing its own output changes nothing.
    assert normalize_request_overrides(out) == out

    with pytest.raises(ValueError):
        normalize_request_overrides({"headers": "not-a-dict"})
    with pytest.raises(ValueError):
        normalize_request_overrides({"timeout": "soon"})


@pytest.mark.asyncio
async def test_tested_and_published_request_shapes_match(monkeypatch):
    """The exact outgoing request (method, URL, headers, body) must be
    identical between the test path (policy request_overrides via the shared
    builder) and a channel executing the published version config."""
    from botelier.services.operation_publisher import (
        _build_execution_config,
        build_operation_api_config,
        normalize_request_overrides,
    )

    integ = _bearer_integration(path="/bookings", method="POST")
    client = _client_with(integ)

    policy = MagicMock()
    policy.request_overrides = normalize_request_overrides(
        {
            "headers": {"X-Env": "prod"},
            "content_type": "application/json",
            "body_template": '{"guest": "{{guest}}"}',
            "timeout": 12,
            "retry_count": 1,
        }
    )
    policy.response_mapping = {}
    policy.to_dict.return_value = {}

    endpoint = {"id": "op1", "path": "/bookings", "method": "POST", "variables": []}
    exec_config = _build_execution_config(
        endpoint, integ, integ.integration_type, {}, policy
    )
    # Publish persists the SAME normalized overrides the test path uses.
    assert exec_config["request_overrides"] == policy.request_overrides

    captured = _install_capture(monkeypatch, lambda _r: httpx.Response(200, json={}))

    # Channel side: voice/SMS/simulator all build from the published config.
    channel_config = build_operation_api_config(exec_config)
    assert channel_config.timeout == 12
    assert channel_config.retry_count == 1
    channel_result = await client.execute_request(channel_config, {"guest": "Ana"})

    # Test side: test_operation builds through the same shared builder with the
    # saved policy overrides (no draft).
    test_config = build_operation_api_config(
        {
            "integration_id": str(integ.id),
            "method": endpoint["method"],
            "path": endpoint["path"],
            "endpoint_id": endpoint["id"],
            "request_overrides": policy.request_overrides,
        }
    )
    test_result = await client.execute_request(test_config, {"guest": "Ana"})

    assert channel_result.success is True and test_result.success is True
    assert len(captured) == 2
    a, b = captured
    assert (a.method, str(a.url)) == (b.method, str(b.url))
    assert dict(a.headers) == dict(b.headers)
    assert a.content == b.content
    import json as _json

    assert _json.loads(a.content) == {"guest": "Ana"}
    assert a.headers["X-Env"] == "prod"
    assert a.headers["Authorization"] == "Bearer real-token"


# ── Channel dispatchers: successful dynamic-operation execution ───────────────


@pytest.fixture()
def dynop_env():
    """Account + connected integration in the dev DB, best-effort cleaned up.

    The executor path may commit mid-test, so teardown explicitly deletes the
    created rows instead of relying on rollback alone.
    """
    from botelier.database import SessionLocal
    from botelier.models.account import Account, AccountStatus, SubscriptionTier

    db = SessionLocal()
    suffix = uuid.uuid4().hex[:12]
    acct = itype = conn = None
    try:
        acct = Account(
            name=f"dynop-{suffix}",
            slug=f"dynop-{suffix}",
            email=f"dynop-{suffix}@example.invalid",
            status=AccountStatus.ACTIVE,
            subscription_tier=SubscriptionTier.FREE,
        )
        db.add(acct)
        db.flush()

        itype = IntegrationType(
            slug=f"dynop-type-{suffix}",
            name="DynOp Type",
            provider="test",
            auth_type="none",
        )
        itype.set_auth_config(
            {"base_url": "https://api.dynop.test", "auth_strategy": "bearer"}
        )
        itype.set_endpoints(
            [{"id": "op1", "path": "/rooms", "method": "GET", "description": "rooms"}]
        )
        db.add(itype)
        db.flush()

        conn = AccountIntegration(
            account_id=acct.id,
            integration_type_id=itype.id,
            status=IntegrationStatus.CONNECTED,
        )
        conn.set_credentials({"token": "real-token"})
        db.add(conn)
        db.flush()

        yield db, acct, itype, conn
    finally:
        try:
            db.rollback()
            from botelier.models.integration import (
                IntegrationAction,
                IntegrationActionVersion,
            )
            from botelier.models.tool import Tool

            if acct is not None:
                action_ids = [
                    row[0]
                    for row in db.query(IntegrationAction.id)
                    .filter(IntegrationAction.account_id == acct.id)
                    .all()
                ]
                if action_ids:
                    db.query(IntegrationActionVersion).filter(
                        IntegrationActionVersion.action_id.in_(action_ids)
                    ).delete(synchronize_session=False)
                    db.query(IntegrationAction).filter(
                        IntegrationAction.id.in_(action_ids)
                    ).delete(synchronize_session=False)
                db.query(Tool).filter(Tool.account_id == acct.id).delete(
                    synchronize_session=False
                )
                if conn is not None:
                    db.query(AccountIntegration).filter(
                        AccountIntegration.id == conn.id
                    ).delete(synchronize_session=False)
                if itype is not None:
                    db.query(IntegrationType).filter(
                        IntegrationType.id == itype.id
                    ).delete(synchronize_session=False)
                db.query(Account).filter(Account.id == acct.id).delete(
                    synchronize_session=False
                )
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


def _publish_dynop(db, acct, itype, conn, response_mapping, request_overrides=None):
    """Create a published DYNAMIC_OPERATION action/version/tool chain."""
    from botelier.models.integration import (
        IntegrationAction,
        IntegrationActionKind,
        IntegrationActionStatus,
        IntegrationActionVersion,
    )
    from botelier.models.tool import Tool, ToolType

    suffix = uuid.uuid4().hex[:8]
    action = IntegrationAction(
        account_id=acct.id,
        integration_type_id=itype.id,
        name="List Rooms",
        slug=f"list-rooms-{suffix}",
        kind=IntegrationActionKind.IMPORTED,
        status=IntegrationActionStatus.PUBLISHED,
        connection_id=conn.id,
        source_endpoint_id="op1",
    )
    db.add(action)
    db.flush()

    exec_config = {
        "integration_id": str(conn.id),
        "integration_type_id": str(itype.id),
        "method": "GET",
        "path": "/rooms",
        "endpoint_id": "op1",
        "connection_params": {},
        "fixed_params": {},
        "variables": [],
        "risk_level": "read",
        "response_policy": {},
        "response_mapping": response_mapping or {},
        "request_overrides": request_overrides or {},
    }
    version = IntegrationActionVersion(
        action_id=action.id,
        version_number=1,
        status=IntegrationActionStatus.PUBLISHED,
        config=exec_config,
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={},
    )
    db.add(version)
    db.flush()
    action.published_version_id = version.id

    tool = Tool(
        id=str(uuid.uuid4()),
        name=f"dynop_tool_{suffix}",
        description="dynop test tool",
        tool_type=ToolType.DYNAMIC_OPERATION,
        config={
            "integration_action_id": str(action.id),
            "connection_id": str(conn.id),
            "operation_id": "op1",
        },
        account_id=acct.id,
        is_active="true",
    )
    db.add(tool)
    db.flush()
    return tool


_DYNOP_BODY = {"data": {"room": "Suite"}}
_DYNOP_CASES = [
    ({}, _DYNOP_BODY),  # unmapped → full response body
    ({"room": "$.data.room"}, {"room": "Suite"}),  # mapped → projection only
]


@pytest.mark.asyncio
async def test_voice_dynamic_operation_success_mapped_and_unmapped(
    dynop_env, monkeypatch
):
    from types import SimpleNamespace

    from botelier.voice.function_mapper import FunctionMapper

    db, acct, itype, conn = dynop_env
    captured = _install_capture(
        monkeypatch, lambda _r: httpx.Response(200, json=_DYNOP_BODY)
    )

    for mapping, expected in _DYNOP_CASES:
        tool = _publish_dynop(db, acct, itype, conn, mapping, {"headers": {"X-Env": "prod"}})
        mapper = FunctionMapper(db_session=db, account_id=str(acct.id))
        mapped = mapper._map_dynamic_operation(tool)
        assert mapped is not None
        _schema, handler = mapped

        results = []

        async def _cb(payload):
            results.append(payload)

        await handler(SimpleNamespace(arguments={}, result_callback=_cb))
        assert results == [expected]

    # Persisted request_overrides rode along on the live channel request.
    assert all(r.headers.get("X-Env") == "prod" for r in captured)


@pytest.mark.asyncio
async def test_simulator_dynamic_operation_success_mapped_and_unmapped(
    dynop_env, monkeypatch
):
    from types import SimpleNamespace

    from botelier.api.simulation import _execute_sim_dynamic_operation

    db, acct, itype, conn = dynop_env
    _install_capture(monkeypatch, lambda _r: httpx.Response(200, json=_DYNOP_BODY))

    for mapping, expected in _DYNOP_CASES:
        tool = _publish_dynop(db, acct, itype, conn, mapping)
        state = SimpleNamespace(account_id=str(acct.id), executor=None)
        result = await _execute_sim_dynamic_operation(state, tool.name, {}, db)
        assert result == expected


def test_sms_dynamic_operation_success_mapped_and_unmapped(dynop_env, monkeypatch):
    from types import SimpleNamespace

    from botelier.services.sms_service import SMSService

    db, acct, itype, conn = dynop_env
    _install_capture(monkeypatch, lambda _r: httpx.Response(200, json=_DYNOP_BODY))

    service = SMSService(db)
    assistant = SimpleNamespace(account_id=acct.id)
    for mapping, expected in _DYNOP_CASES:
        tool = _publish_dynop(db, acct, itype, conn, mapping)
        result = service._execute_dynamic_operation(assistant, tool, {})
        assert result == expected


# ── Publisher slug fixed point ────────────────────────────────────────────────


def test_derived_tool_name_is_sanitize_fixed_point():
    from botelier.services.operation_publisher import _derive_tool_name

    itype = IntegrationType(
        slug="importedapi", name="Imported", provider="custom", auth_type="none"
    )
    conn = AccountIntegration()

    # Names chosen so a bare [:60] truncation would land on an underscore.
    for conn_name, fn_name in [
        ("My Hotel Connection!!", "get_available_rooms_for_property_and_dates_x"),
        ("acme", "a" * 55 + "_tail"),
        ("trailing", "x" * 51 + "_" + "y" * 20),
    ]:
        conn.connection_name = conn_name
        slug = _derive_tool_name(fn_name, conn, itype)
        assert slug == sanitize_function_name(slug), slug
        assert len(slug) <= 60
