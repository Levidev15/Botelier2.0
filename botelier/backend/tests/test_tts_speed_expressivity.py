"""Tests for TTS speed/expressivity controls (Task #595).

Covers:
  - Aura branch (_BotelierDeepgramTTSService): speed/expressivity read from
    tts_config, appended to the /v1/speak WebSocket URL, and omitted at
    default values.
  - Flux branch (_BotelierDeepgramFluxTTSService): same behaviour against
    /v2/speak.
  - Invalid tts_config values fall back to the documented defaults instead
    of raising.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from botelier.voice.agent import VoiceAgentConfig
from botelier.voice.engine import VoiceEngineFactory


def _config(**overrides) -> VoiceAgentConfig:
    data = {
        "agent_id": "assistant-1",
        "account_id": "account-1",
        "name": "Desk",
        "stt_provider": "deepgram",
        "stt_model": "flux-general-en",
        "stt_config": {},
        "llm_provider": "openai",
        "llm_model": "gpt-4.1-mini",
        "llm_config": {},
        "tts_provider": "deepgram",
        "tts_model": "aura-2",
        "tts_voice_id": "aura-2-helena-en",
        "tts_config": {},
        "enable_vad": False,
        "vad_provider": None,
        "vad_config": {},
        "enable_interruptions": True,
    }
    data.update(overrides)
    return VoiceAgentConfig(**data)


API_KEYS = {"deepgram_api_key": "test-key"}


class _FakeWSResponse:
    headers: dict = {}


class _FakeWebSocket:
    class _State:
        pass

    def __init__(self):
        self.response = _FakeWSResponse()

    @property
    def state(self):
        from websockets.protocol import State

        return State.OPEN


async def _connect_and_capture_url(svc, module_path: str) -> str:
    """Run svc._connect_websocket() with the outbound websocket connect
    mocked, and return the URL it attempted to connect to."""
    captured = {}

    async def fake_connect(url, **kwargs):
        captured["url"] = url
        return _FakeWebSocket()

    with patch(f"{module_path}.connect", new=fake_connect):
        await svc._connect_websocket()
    return captured["url"]


# ---------------------------------------------------------------------------
# Aura (/v1/speak)
# ---------------------------------------------------------------------------


def _make_aura_tts(tts_config=None):
    return VoiceEngineFactory.create_tts_service(
        _config(tts_config=tts_config or {}), API_KEYS
    )


class TestAuraSpeedAndExpressivity:
    @pytest.mark.asyncio
    async def test_defaults_omit_both_params_from_url(self):
        svc = _make_aura_tts({})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "/v1/speak" in url
        assert "speed=" not in url
        assert "expressivity=" not in url

    @pytest.mark.asyncio
    async def test_nonzero_speed_is_appended(self):
        svc = _make_aura_tts({"speed": 0.5})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "speed=0.5" in url

    @pytest.mark.asyncio
    async def test_negative_speed_is_appended(self):
        svc = _make_aura_tts({"speed": -0.75})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "speed=-0.75" in url

    @pytest.mark.asyncio
    async def test_zero_speed_is_omitted(self):
        svc = _make_aura_tts({"speed": 0})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "speed=" not in url

    @pytest.mark.asyncio
    async def test_expressivity_0_flat_is_appended(self):
        svc = _make_aura_tts({"expressivity": 0})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "expressivity=0" in url

    @pytest.mark.asyncio
    async def test_expressivity_2_expressive_is_appended(self):
        svc = _make_aura_tts({"expressivity": 2})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "expressivity=2" in url

    @pytest.mark.asyncio
    async def test_expressivity_1_default_is_omitted(self):
        svc = _make_aura_tts({"expressivity": 1})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "expressivity=" not in url

    @pytest.mark.asyncio
    async def test_both_params_together(self):
        svc = _make_aura_tts({"speed": 0.3, "expressivity": 2})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "speed=0.3" in url
        assert "expressivity=2" in url

    def test_invalid_speed_value_falls_back_to_zero(self):
        svc = _make_aura_tts({"speed": "not-a-number"})
        assert svc._tts_speed == 0.0

    def test_invalid_expressivity_value_falls_back_to_none(self):
        svc = _make_aura_tts({"expressivity": "not-a-number"})
        assert svc._tts_expressivity is None

    def test_missing_config_defaults_to_no_overrides(self):
        svc = _make_aura_tts(None)
        assert svc._tts_speed == 0.0
        assert svc._tts_expressivity is None


# ---------------------------------------------------------------------------
# Flux (/v2/speak)
# ---------------------------------------------------------------------------


def _make_flux_tts(tts_config=None):
    return VoiceEngineFactory.create_tts_service(
        _config(
            tts_provider="deepgram-flux",
            tts_model="flux",
            tts_voice_id="flux-alexis-en",
            tts_config=tts_config or {},
        ),
        API_KEYS,
    )


class TestFluxSpeed:
    @pytest.mark.asyncio
    async def test_defaults_omit_speed_from_url(self):
        svc = _make_flux_tts({})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "/v2/speak" in url
        assert "speed=" not in url

    @pytest.mark.asyncio
    async def test_nonzero_speed_is_appended(self):
        svc = _make_flux_tts({"speed": -0.4})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "speed=-0.4" in url

    @pytest.mark.asyncio
    async def test_expressivity_is_never_sent_to_flux(self):
        # Deepgram does not document expressivity for /v2/speak — Flux must
        # never carry this parameter, even if an assistant's tts_config has
        # a stale/API-provided expressivity value from before this
        # capability boundary was enforced.
        svc = _make_flux_tts({"expressivity": 0})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "expressivity=" not in url
        assert not hasattr(svc, "_tts_expressivity")

    def test_invalid_speed_value_falls_back_to_zero(self):
        svc = _make_flux_tts({"speed": None})
        assert svc._tts_speed == 0.0


# ---------------------------------------------------------------------------
# Shared resolver — range clamping + capability boundary
# ---------------------------------------------------------------------------


class TestSharedResolverClampingAndCapabilityBoundary:
    def test_speed_is_clamped_to_supported_range(self):
        from botelier.voice.tts_tuning import resolve_tts_speed

        assert resolve_tts_speed({"speed": 5.0}) == 1.0
        assert resolve_tts_speed({"speed": -9.0}) == -1.0
        assert resolve_tts_speed({"speed": 0.25}) == 0.25

    def test_expressivity_is_clamped_to_supported_range(self):
        from botelier.voice.tts_tuning import resolve_tts_expressivity

        assert resolve_tts_expressivity({"expressivity": 99}, "aura-2-helena-en") == 2
        assert resolve_tts_expressivity({"expressivity": -5}, "aura-2-helena-en") == 0

    def test_expressivity_is_none_for_non_aura2_voices(self):
        from botelier.voice.tts_tuning import resolve_tts_expressivity

        assert resolve_tts_expressivity({"expressivity": 2}, "aura-asteria-en") is None
        assert resolve_tts_expressivity({"expressivity": 2}, "flux-alexis-en") is None
        assert resolve_tts_expressivity({"expressivity": 2}, "") is None

    def test_expressivity_applies_for_aura2_voices(self):
        from botelier.voice.tts_tuning import resolve_tts_expressivity

        assert resolve_tts_expressivity({"expressivity": 2}, "aura-2-helena-en") == 2


# ---------------------------------------------------------------------------
# Greeting cache/prewarm parity — the cached greeting must match the live
# call's speed/expressivity, and changing either must invalidate the cache.
# ---------------------------------------------------------------------------


class TestGreetingCacheSpeedExpressivityParity:
    def test_cache_key_changes_with_speed(self):
        from botelier.voice.greeting_cache import _cache_key

        base = _cache_key("Hello!", {"voice": "aura-2-helena-en"})
        faster = _cache_key("Hello!", {"voice": "aura-2-helena-en", "speed": 0.5})
        assert base != faster

    def test_cache_key_changes_with_expressivity(self):
        from botelier.voice.greeting_cache import _cache_key

        base = _cache_key("Hello!", {"voice": "aura-2-helena-en"})
        flat = _cache_key("Hello!", {"voice": "aura-2-helena-en", "expressivity": 0})
        assert base != flat

    def test_cache_key_ignores_expressivity_for_non_aura2_voice(self):
        # resolve_tts_expressivity returns None for non-Aura-2 voices, so an
        # expressivity value on e.g. a Flux tts_config must not perturb the
        # key (there's nothing for it to affect).
        from botelier.voice.greeting_cache import _cache_key

        base = _cache_key("Hello!", {"voice": "flux-alexis-en"})
        with_expressivity = _cache_key(
            "Hello!", {"voice": "flux-alexis-en", "expressivity": 2}
        )
        assert base == with_expressivity

    def test_cache_key_stable_for_default_values(self):
        from botelier.voice.greeting_cache import _cache_key

        implicit_default = _cache_key("Hello!", {"voice": "aura-2-helena-en"})
        explicit_default = _cache_key(
            "Hello!", {"voice": "aura-2-helena-en", "speed": 0, "expressivity": 1}
        )
        assert implicit_default == explicit_default

    @pytest.mark.asyncio
    async def test_rest_call_includes_speed_and_expressivity_for_aura(self, tmp_path, monkeypatch):
        from botelier.voice import greeting_cache

        monkeypatch.setattr(greeting_cache, "_CACHE_DIR", str(tmp_path))

        captured = {}

        class _FakeResponse:
            content = b"\x00\x01" * 200

            def raise_for_status(self):
                pass

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, headers=None, json=None):
                captured["url"] = url
                return _FakeResponse()

        monkeypatch.setattr(greeting_cache.httpx, "AsyncClient", _FakeAsyncClient)

        await greeting_cache.get_or_generate_greeting_audio(
            "Hello!",
            {"voice": "aura-2-helena-en", "speed": 0.5, "expressivity": 0},
            api_key="test-key",
        )
        assert "speed=0.5" in captured["url"]
        assert "expressivity=0" in captured["url"]

    @pytest.mark.asyncio
    async def test_rest_call_never_sends_expressivity_for_flux(self, tmp_path, monkeypatch):
        from botelier.voice import greeting_cache

        monkeypatch.setattr(greeting_cache, "_CACHE_DIR", str(tmp_path))

        captured = {}

        class _FakeResponse:
            content = b"\x00\x01" * 200

            def raise_for_status(self):
                pass

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, headers=None, json=None):
                captured["url"] = url
                return _FakeResponse()

        monkeypatch.setattr(greeting_cache.httpx, "AsyncClient", _FakeAsyncClient)

        await greeting_cache.get_or_generate_greeting_audio(
            "Hello!",
            {"voice": "flux-alexis-en", "speed": 0.3, "expressivity": 2},
            api_key="test-key",
        )
        assert "/v2/speak" in captured["url"]
        assert "speed=0.3" in captured["url"]
        assert "expressivity=" not in captured["url"]
