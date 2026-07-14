"""Per-property data isolation tests (Task #327).

These pin the fail-closed guarantees that keep one property from ever receiving
another property's integration data within a single account:

  • ``_is_property_allowed`` — the authorization predicate (legacy allow-all,
    account-global allow, matching-property allow, cross-property reject).
  • ``execute_request`` — a cross-property integration is rejected BEFORE any
    outbound HTTP request or credential use (AUTH_ERROR, no network call).
  • ``_apply_endpoint_defaults`` — property-identity keys are re-forced from the
    connection's config on top of caller/LLM-supplied values, so a caller can
    never redirect a request to another property by supplying its own hotel_id.
  • ``resolve_session_property_id`` — server-side precedence (dialed number →
    assistant → None), derived only from trusted signals.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from botelier.services.integration_client import (
    APIErrorType,
    IntegrationAPIConfig,
    IntegrationClient,
)
from botelier.services.integration_runtime.client import PROPERTY_IDENTITY_KEYS
from botelier.services.property_scope import resolve_session_property_id

ACCOUNT_ID = "00000000-0000-0000-0000-000000000001"
PROP_A = "11111111-1111-1111-1111-111111111111"
PROP_B = "22222222-2222-2222-2222-222222222222"


class _StubIntegration:
    """Minimal AccountIntegration stand-in for the pure-logic helpers."""

    def __init__(self, *, property_id=None, connection_config=None):
        self.id = uuid.uuid4()
        self.property_id = property_id
        self._connection_config = connection_config or {}

    def get_connection_config(self):
        return self._connection_config


def _no_network(monkeypatch):
    """Fail the test if any outbound HTTP request is attempted."""

    class _Boom(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            def handler(request):
                raise AssertionError(
                    f"unexpected outbound request to {request.url}"
                )

            kwargs.pop("transport", None)
            super().__init__(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _Boom)


# ── _is_property_allowed ──────────────────────────────────────────────────────


def test_legacy_session_allows_every_integration():
    """A session with no resolved property keeps account-only (allow-all) scope."""
    client = IntegrationClient(account_id=ACCOUNT_ID, db=MagicMock(), property_id=None)
    assert client._is_property_allowed(_StubIntegration(property_id=None)) is True
    assert client._is_property_allowed(_StubIntegration(property_id=PROP_A)) is True
    assert client._is_property_allowed(_StubIntegration(property_id=PROP_B)) is True


def test_account_global_integration_is_allowed_for_any_property():
    """An integration with NULL property_id is shared across the account."""
    client = IntegrationClient(account_id=ACCOUNT_ID, db=MagicMock(), property_id=PROP_A)
    assert client._is_property_allowed(_StubIntegration(property_id=None)) is True


def test_matching_property_is_allowed():
    client = IntegrationClient(account_id=ACCOUNT_ID, db=MagicMock(), property_id=PROP_A)
    assert client._is_property_allowed(_StubIntegration(property_id=PROP_A)) is True


def test_cross_property_integration_is_rejected():
    client = IntegrationClient(account_id=ACCOUNT_ID, db=MagicMock(), property_id=PROP_A)
    assert client._is_property_allowed(_StubIntegration(property_id=PROP_B)) is False


# ── execute_request fail-closed (no HTTP) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_request_rejects_cross_property_without_network(monkeypatch):
    """Cross-property resolution fails closed before any outbound request."""
    _no_network(monkeypatch)

    integ = _StubIntegration(property_id=PROP_B)
    integ.status = MagicMock()  # never reached; property check precedes status
    client = IntegrationClient(account_id=ACCOUNT_ID, db=MagicMock(), property_id=PROP_A)
    client._integration_cache[str(integ.id)] = integ

    config = IntegrationAPIConfig(
        integration_id=str(integ.id),
        endpoint_id="get_reservation",
        method="GET",
    )
    result = await client.execute_request(config, {"confirmation_number": "ABC123"})

    assert result.success is False
    assert result.error_type == APIErrorType.AUTH_ERROR
    assert result.error_message == "Cross-property access rejected"


# ── identity-key forcing ──────────────────────────────────────────────────────


def test_identity_keys_forced_over_caller_values():
    """A caller/LLM-supplied hotel_id cannot override the connection's own."""
    client = IntegrationClient(account_id=ACCOUNT_ID, db=MagicMock())
    integ = _StubIntegration(connection_config={"hotel_id": "REAL_HOTEL"})

    merged = client._apply_endpoint_defaults(
        {"hotel_id": "ATTACKER_HOTEL", "guest_name": "Ada"},
        endpoint_def=None,
        integration=integ,
    )

    assert merged["hotel_id"] == "REAL_HOTEL"
    assert merged["guest_name"] == "Ada"


def test_identity_keys_not_forced_when_absent_from_connection_config():
    """Account-global connections (no identity key) keep the caller's value."""
    client = IntegrationClient(account_id=ACCOUNT_ID, db=MagicMock())
    integ = _StubIntegration(connection_config={})

    merged = client._apply_endpoint_defaults(
        {"hotelId": "CALLER_CHOICE"},
        endpoint_def=None,
        integration=integ,
    )

    assert merged["hotelId"] == "CALLER_CHOICE"


def test_plural_hotels_array_is_not_an_identity_key():
    """Multi-hotel flows using the plural ``hotels`` param are unaffected."""
    assert "hotels" not in PROPERTY_IDENTITY_KEYS
    client = IntegrationClient(account_id=ACCOUNT_ID, db=MagicMock())
    integ = _StubIntegration(connection_config={"hotel_id": "REAL_HOTEL"})

    merged = client._apply_endpoint_defaults(
        {"hotels": ["A", "B"]},
        endpoint_def=None,
        integration=integ,
    )

    assert merged["hotels"] == ["A", "B"]
    assert merged["hotel_id"] == "REAL_HOTEL"


# ── resolve_session_property_id ───────────────────────────────────────────────


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeSession:
    def __init__(self, phone):
        self._phone = phone

    def query(self, *args, **kwargs):
        return _FakeQuery(self._phone)

    def close(self):
        pass


def test_dialed_number_property_takes_precedence_over_assistant():
    phone = SimpleNamespace(property_id=PROP_A)
    assistant = SimpleNamespace(property_id=PROP_B)
    assert (
        resolve_session_property_id("+15551234567", assistant, _FakeSession(phone))
        == PROP_A
    )


def test_falls_back_to_assistant_when_number_has_no_property():
    phone = SimpleNamespace(property_id=None)
    assistant = SimpleNamespace(property_id=PROP_B)
    assert (
        resolve_session_property_id("+15551234567", assistant, _FakeSession(phone))
        == PROP_B
    )


def test_falls_back_to_assistant_when_no_phone_row():
    assistant = SimpleNamespace(property_id=PROP_B)
    assert (
        resolve_session_property_id("+15551234567", assistant, _FakeSession(None))
        == PROP_B
    )


def test_returns_none_for_legacy_session():
    assert resolve_session_property_id(None, SimpleNamespace(property_id=None), None) is None
    assert resolve_session_property_id(None, None, None) is None
