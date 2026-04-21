"""
Tests for Task #139 — Voice Webhook Authenticity.

Regression guard for the Twilio signature validation added to the public
voice lifecycle HTTP endpoints and the media WebSocket call binding.

Coverage:
1. HTTP 403 returned by each voice webhook when validate_twilio_signature()
   reports an invalid signature (invalid_sig path).
2. HTTP 200 / normal processing when the signature is valid (happy path).
3. WebSocket /api/ws/call rejected with close-code 1008 when:
   a) The callSid has no matching CallLog row (forged start frame).
   b) The to_number in the start frame does not match the CallLog row.
   c) The stream token is invalid (bad HMAC) when a secret IS configured.
4. HMAC stream-token unit tests: mint → verify round-trip, expiry, tamper.
"""

import asyncio
import sys
import time
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from botelier.api._twilio_auth import mint_stream_token, verify_stream_token


# ---------------------------------------------------------------------------
# Stub the voice pipeline modules so WebSocket-endpoint imports succeed in
# the test environment (pipecat.turns and related native extensions are not
# installed here).  We replace botelier.voice.call_handler with a thin mock
# BEFORE importing botelier.api.websockets; Python's import cache means the
# mock is reused for all subsequent imports in the same process.
# ---------------------------------------------------------------------------
def _ensure_voice_stubs():
    """Insert minimal stubs for the voice-pipeline import chain.

    We always force ``botelier.voice.call_handler`` to a mock so the test
    process never tries to load pipecat's native extension modules.  The
    ``botelier.voice`` package itself may already be in sys.modules from
    other test files; that is fine — we only replace the call_handler leaf.
    """
    if "botelier.voice" not in sys.modules:
        pkg = types.ModuleType("botelier.voice")
        pkg.__path__ = []
        pkg.__package__ = "botelier.voice"
        sys.modules["botelier.voice"] = pkg

    mock_ch = types.ModuleType("botelier.voice.call_handler")
    mock_ch.CallHandler = MagicMock()
    sys.modules["botelier.voice.call_handler"] = mock_ch


_ensure_voice_stubs()


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

class _FakeFormData(dict):
    """dict that also satisfies Starlette's ImmutableMultiDict contract."""


class _FakeRequest:
    """Minimal starlette Request stand-in for synchronous form-based webhooks."""

    def __init__(self, form: dict, headers: dict | None = None):
        self._form = _FakeFormData(form)
        self.headers = headers or {}

    async def form(self):
        return self._form


def _make_call_log(call_sid: str, to_number: str = "+15551234567") -> MagicMock:
    cl = MagicMock()
    cl.id = uuid.uuid4()
    cl.call_sid = call_sid
    cl.to_number = to_number
    cl.account_id = uuid.uuid4()
    cl.started_at = None
    return cl


def _make_db_with_no_call_log():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    return db


def _make_db_with_call_log(call_log: MagicMock):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = call_log
    return db


# ---------------------------------------------------------------------------
# 1. HTTP endpoints — invalid signature → 403
# ---------------------------------------------------------------------------

_VOICE_ENDPOINTS = [
    ("botelier.api.calls.incoming_call_webhook", {"CallSid": "CA1", "From": "+1", "To": "+15551234567", "CallStatus": "ringing"}, "/incoming"),
    ("botelier.api.calls.call_status_callback",  {"CallSid": "CA1", "CallStatus": "completed"},                                   "/status"),
    ("botelier.api.calls.connect_complete",       {"CallSid": "CA1"},                                                              "/connect-complete"),
    ("botelier.api.calls.transfer_status_callback", {"CallSid": "CA1", "CallStatus": "completed"},                                 "/transfer-status"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint_fn_path,form,path_suffix", _VOICE_ENDPOINTS)
async def test_voice_webhook_returns_403_on_invalid_signature(endpoint_fn_path, form, path_suffix):
    """Each voice lifecycle endpoint must return HTTP 403 when
    validate_twilio_signature() reports an invalid signature."""
    module_path, fn_name = endpoint_fn_path.rsplit(".", 1)
    import importlib
    mod = importlib.import_module(module_path)
    endpoint_fn = getattr(mod, fn_name)

    req = _FakeRequest(form)
    db = _make_db_with_no_call_log()

    with patch("botelier.api.calls.validate_twilio_signature", return_value=(False, f"https://example.com/api/calls{path_suffix}")):
        with patch("botelier.api.calls.get_call_auth_token", return_value="dummy-token"):
            resp = await endpoint_fn(req, db)

    assert resp.status_code == 403, (
        f"{fn_name}: expected 403 on invalid signature, got {resp.status_code}"
    )


@pytest.mark.asyncio
async def test_incoming_webhook_200_on_valid_signature():
    """incoming_call_webhook returns TwiML (200) when the signature is valid."""
    from botelier.api.calls import incoming_call_webhook

    call_sid = "CA-valid-sig-test"
    to_number = "+15559998888"
    form = {"CallSid": call_sid, "From": "+15550001111", "To": to_number, "CallStatus": "ringing"}
    req = _FakeRequest(form, headers={"Host": "example.com"})
    db = _make_db_with_no_call_log()

    with patch("botelier.api.calls.validate_twilio_signature", return_value=(True, f"https://example.com/api/calls/incoming")):
        with patch("botelier.api.calls.get_call_auth_token", return_value=""):
            with patch("botelier.api.calls.mint_stream_token", return_value=("tok", 9999999999)):
                with patch("botelier.api.calls.get_websocket_url", return_value="wss://example.com/api/ws/call"):
                    with patch("botelier.api.calls.get_public_base_url", return_value="https://example.com"):
                        resp = await incoming_call_webhook(req, db)

    assert resp.status_code == 200
    assert b"<Stream" in resp.body


# ---------------------------------------------------------------------------
# 2. WebSocket — rejected when no CallLog exists (forged callSid)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_websocket_rejected_when_no_call_log():
    """The WebSocket endpoint must close with code 1008 when the callSid
    in the start frame has no matching CallLog row."""
    from botelier.api.websockets import websocket_call_endpoint

    call_sid = "CA-not-in-db"
    to_number = "+15550000001"

    messages = [
        '{"event": "connected"}',
        (
            f'{{"event": "start", "start": {{'
            f'"streamSid": "MZ1", "callSid": "{call_sid}", '
            f'"customParameters": {{"to": "{to_number}", "from": "+1", '
            f'"streamToken": "", "streamTokenExp": "0"}}}}}}'
        ),
    ]

    ws = MagicMock()
    ws.client_state = MagicMock()
    ws.client_state.name = "CONNECTED"
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock(side_effect=messages)
    ws.close = AsyncMock()

    db = _make_db_with_no_call_log()

    await websocket_call_endpoint(ws, db)

    ws.close.assert_awaited()
    close_call_kwargs = ws.close.await_args
    code = (
        close_call_kwargs.kwargs.get("code")
        or (close_call_kwargs.args[0] if close_call_kwargs.args else None)
    )
    assert code == 1008, f"Expected close code 1008, got {code}"


@pytest.mark.asyncio
async def test_websocket_rejected_on_to_number_mismatch():
    """The WebSocket endpoint must close with code 1008 when the to_number
    in the start frame does not match the to_number stored in the CallLog."""
    from botelier.api.websockets import websocket_call_endpoint

    call_sid = "CA-mismatch-test"
    real_to = "+15550000001"
    forged_to = "+15559999999"

    call_log = _make_call_log(call_sid, to_number=real_to)

    messages = [
        '{"event": "connected"}',
        (
            f'{{"event": "start", "start": {{'
            f'"streamSid": "MZ2", "callSid": "{call_sid}", '
            f'"customParameters": {{"to": "{forged_to}", "from": "+1", '
            f'"streamToken": "", "streamTokenExp": "0"}}}}}}'
        ),
    ]

    ws = MagicMock()
    ws.client_state = MagicMock()
    ws.client_state.name = "CONNECTED"
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock(side_effect=messages)
    ws.close = AsyncMock()

    db = _make_db_with_call_log(call_log)

    await websocket_call_endpoint(ws, db)

    ws.close.assert_awaited()
    close_call_kwargs = ws.close.await_args
    code = (
        close_call_kwargs.kwargs.get("code")
        or (close_call_kwargs.args[0] if close_call_kwargs.args else None)
    )
    assert code == 1008, f"Expected close code 1008, got {code}"


@pytest.mark.asyncio
async def test_websocket_rejected_on_bad_stream_token():
    """The WebSocket endpoint must close with code 1008 when a real
    TWILIO_AUTH_TOKEN is configured and the stream token HMAC is wrong."""
    from botelier.api.websockets import websocket_call_endpoint

    call_sid = "CA-bad-token"
    to_number = "+15550000002"
    call_log = _make_call_log(call_sid, to_number=to_number)

    bad_token = "0" * 64
    messages = [
        '{"event": "connected"}',
        (
            f'{{"event": "start", "start": {{'
            f'"streamSid": "MZ3", "callSid": "{call_sid}", '
            f'"customParameters": {{"to": "{to_number}", "from": "+1", '
            f'"streamToken": "{bad_token}", "streamTokenExp": "9999999999"}}}}}}'
        ),
    ]

    ws = MagicMock()
    ws.client_state = MagicMock()
    ws.client_state.name = "CONNECTED"
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock(side_effect=messages)
    ws.close = AsyncMock()

    db = _make_db_with_call_log(call_log)

    with patch("botelier.api.websockets.get_call_auth_token", return_value="real-secret-token"):
        await websocket_call_endpoint(ws, db)

    ws.close.assert_awaited()
    close_call_kwargs = ws.close.await_args
    code = (
        close_call_kwargs.kwargs.get("code")
        or (close_call_kwargs.args[0] if close_call_kwargs.args else None)
    )
    assert code == 1008, f"Expected close code 1008, got {code}"


# ---------------------------------------------------------------------------
# 3. HMAC stream token unit tests
# ---------------------------------------------------------------------------

class TestStreamToken:
    _SECRET = "unit-test-secret-key"

    def test_mint_verify_round_trip(self):
        """A freshly minted token verifies successfully."""
        token, exp = mint_stream_token("CA123", "+15550001111", self._SECRET)
        assert token  # not empty
        ok, reason = verify_stream_token("CA123", "+15550001111", token, exp, self._SECRET)
        assert ok, f"Expected ok, got reason={reason}"

    def test_tampered_token_rejected(self):
        """A token with any byte flipped is rejected as signature_mismatch."""
        token, exp = mint_stream_token("CA456", "+15550002222", self._SECRET)
        bad_token = token[:-1] + ("0" if token[-1] != "0" else "1")
        ok, reason = verify_stream_token("CA456", "+15550002222", bad_token, exp, self._SECRET)
        assert not ok
        assert reason == "signature_mismatch"

    def test_expired_token_rejected(self):
        """A token with an expiry in the past is rejected as expired."""
        exp_past = int(time.time()) - 1
        _, _ = mint_stream_token("CA789", "+15550003333", self._SECRET)
        import hmac, hashlib
        payload = f"CA789|+15550003333|{exp_past}".encode()
        digest = hmac.new(self._SECRET.encode(), payload, hashlib.sha256).hexdigest()
        ok, reason = verify_stream_token("CA789", "+15550003333", digest, exp_past, self._SECRET)
        assert not ok
        assert reason == "expired"

    def test_missing_token_rejected_when_secret_configured(self):
        """An empty token is rejected when a secret IS configured."""
        ok, reason = verify_stream_token("CA000", "+1", "", 9999999999, self._SECRET)
        assert not ok
        assert reason == "missing"

    def test_skip_when_no_secret(self):
        """verify_stream_token returns (True, 'skipped_no_secret') when no secret is available."""
        import os
        with patch.dict(os.environ, {"TWILIO_AUTH_TOKEN": "", "STREAM_TOKEN_SECRET": ""}, clear=False):
            ok, reason = verify_stream_token("CA000", "+1", "", 0, "")
        assert ok
        assert reason == "skipped_no_secret"

    def test_wrong_call_sid_rejected(self):
        """Token minted for one CallSid does not verify for another."""
        token, exp = mint_stream_token("CAreal", "+15550004444", self._SECRET)
        ok, reason = verify_stream_token("CAfake", "+15550004444", token, exp, self._SECRET)
        assert not ok

    def test_wrong_to_number_rejected(self):
        """Token minted for one to_number does not verify for another."""
        token, exp = mint_stream_token("CA111", "+15550005555", self._SECRET)
        ok, reason = verify_stream_token("CA111", "+15550006666", token, exp, self._SECRET)
        assert not ok
