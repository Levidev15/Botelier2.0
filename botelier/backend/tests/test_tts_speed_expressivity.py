"""Tests for TTS speed/expressivity controls.

Covers:
  - Aura branch (_BotelierDeepgramTTSService): speed read from tts_config and
    appended to the /v1/speak WebSocket URL as a legacy delta [-1.0, +1.0].
    Expressivity is NOT sent to Aura — Deepgram documents it as a Flux-only
    Beta parameter.
  - Flux branch (_BotelierDeepgramFluxTTSService): speed stored as a
    multiplier [0.5, 1.5] (new UI) or converted from a legacy delta (< 0.5),
    AND expressivity read from tts_config and appended to the /v2/speak URL.
    Expressivity range is [-2, 2]; default (0) is omitted so unmodified
    assistants never send a redundant override.
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
# Aura (/v1/speak) — speed only (legacy delta format); expressivity not sent
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
    async def test_expressivity_never_sent_to_aura_regardless_of_config(self):
        # Expressivity is a Flux-only Beta parameter; Aura must never receive
        # it even when an assistant's tts_config contains a value (e.g.
        # migrated from an old save).
        for expr_value in (0, 1, 2, -1):
            svc = _make_aura_tts({"expressivity": expr_value})
            url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
            assert "expressivity=" not in url, (
                f"Aura must not send expressivity={expr_value} to /v1/speak"
            )

    @pytest.mark.asyncio
    async def test_speed_still_works_when_expressivity_configured(self):
        # Expressivity in config must not suppress speed for Aura.
        svc = _make_aura_tts({"speed": 0.3, "expressivity": 2})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "speed=0.3" in url
        assert "expressivity=" not in url

    def test_invalid_speed_value_falls_back_to_zero(self):
        svc = _make_aura_tts({"speed": "not-a-number"})
        assert svc._tts_speed == 0.0

    def test_invalid_expressivity_value_falls_back_to_none(self):
        # Aura resolver always returns None; bad values must also give None.
        svc = _make_aura_tts({"expressivity": "not-a-number"})
        assert svc._tts_expressivity is None

    def test_missing_config_defaults_to_no_overrides(self):
        svc = _make_aura_tts(None)
        assert svc._tts_speed == 0.0
        assert svc._tts_expressivity is None


# ---------------------------------------------------------------------------
# Flux (/v2/speak) — speed as multiplier [0.5, 1.5] + expressivity (Beta)
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


class TestFluxSpeedAndExpressivity:
    @pytest.mark.asyncio
    async def test_defaults_omit_both_params_from_url(self):
        svc = _make_flux_tts({})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "/v2/speak" in url
        assert "speed=" not in url
        assert "expressivity=" not in url

    @pytest.mark.asyncio
    async def test_multiplier_faster_is_appended(self):
        # New UI stores multiplier directly: 1.1 = 10% faster.
        svc = _make_flux_tts({"speed": 1.1})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "speed=1.1" in url

    @pytest.mark.asyncio
    async def test_multiplier_slower_is_appended(self):
        # New UI stores multiplier directly: 0.7 = 30% slower.
        svc = _make_flux_tts({"speed": 0.7})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "speed=0.7" in url

    @pytest.mark.asyncio
    async def test_multiplier_min_is_appended(self):
        svc = _make_flux_tts({"speed": 0.5})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "speed=0.5" in url

    @pytest.mark.asyncio
    async def test_multiplier_max_is_appended(self):
        svc = _make_flux_tts({"speed": 1.5})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "speed=1.5" in url

    @pytest.mark.asyncio
    async def test_multiplier_default_one_is_omitted(self):
        # 1.0 is the Deepgram Flux default — omit it so unmodified assistants
        # never send a redundant override.
        svc = _make_flux_tts({"speed": 1.0})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "speed=" not in url

    @pytest.mark.asyncio
    async def test_legacy_negative_delta_is_converted_to_multiplier(self):
        # Legacy delta stored by old UI: -0.4 → multiplier = 1.0 + (-0.4)/2 = 0.8.
        svc = _make_flux_tts({"speed": -0.4})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "speed=0.8" in url
        assert "speed=-0.4" not in url

    @pytest.mark.asyncio
    async def test_legacy_max_negative_delta_converts_to_min_multiplier(self):
        # Old delta -1.0 (slowest) → multiplier = 1.0 + (-1.0)/2 = 0.5.
        svc = _make_flux_tts({"speed": -1.0})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "speed=0.5" in url

    @pytest.mark.asyncio
    async def test_legacy_zero_delta_is_omitted(self):
        # Old default (0) resolves to multiplier 1.0 (provider default) → omit.
        svc = _make_flux_tts({"speed": 0})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "speed=" not in url

    @pytest.mark.asyncio
    async def test_expressivity_positive_animated_is_appended(self):
        svc = _make_flux_tts({"expressivity": 2})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "expressivity=2" in url

    @pytest.mark.asyncio
    async def test_expressivity_negative_calm_is_appended(self):
        svc = _make_flux_tts({"expressivity": -2})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "expressivity=-2" in url

    @pytest.mark.asyncio
    async def test_expressivity_minus_one_subdued_is_appended(self):
        svc = _make_flux_tts({"expressivity": -1})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "expressivity=-1" in url

    @pytest.mark.asyncio
    async def test_expressivity_default_zero_is_omitted(self):
        # 0 is the Deepgram Flux default — omit it so unmodified assistants
        # never send a redundant override.
        svc = _make_flux_tts({"expressivity": 0})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "expressivity=" not in url

    @pytest.mark.asyncio
    async def test_expressivity_unset_is_omitted(self):
        svc = _make_flux_tts({})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "expressivity=" not in url

    @pytest.mark.asyncio
    async def test_speed_and_expressivity_together(self):
        # 1.2x speed + calm expressivity.
        svc = _make_flux_tts({"speed": 1.2, "expressivity": -2})
        url = await _connect_and_capture_url(svc, "websockets.asyncio.client")
        assert "speed=1.2" in url
        assert "expressivity=-2" in url

    def test_invalid_speed_value_falls_back_to_zero(self):
        svc = _make_flux_tts({"speed": None})
        assert svc._tts_speed == 0.0

    def test_invalid_expressivity_value_falls_back_to_none(self):
        svc = _make_flux_tts({"expressivity": "not-a-number"})
        assert svc._tts_expressivity is None

    def test_missing_config_defaults_to_no_overrides(self):
        svc = _make_flux_tts(None)
        assert svc._tts_speed == 0.0
        assert svc._tts_expressivity is None


# ---------------------------------------------------------------------------
# Shared resolver — range clamping + capability boundary
# ---------------------------------------------------------------------------


class TestSharedResolverClampingAndCapabilityBoundary:
    # ── Aura (non-Flux): legacy delta format ─────────────────────────────────

    def test_aura_speed_clamped_to_delta_range(self):
        from botelier.voice.tts_tuning import resolve_tts_speed

        assert resolve_tts_speed({"speed": 5.0}, "aura-2-helena-en") == 1.0
        assert resolve_tts_speed({"speed": -9.0}, "aura-2-helena-en") == -1.0
        assert resolve_tts_speed({"speed": 0.25}, "aura-2-helena-en") == 0.25

    def test_aura_speed_without_voice_uses_delta_format(self):
        # No voice → non-Flux path; matches Aura behaviour.
        from botelier.voice.tts_tuning import resolve_tts_speed

        assert resolve_tts_speed({"speed": 5.0}) == 1.0
        assert resolve_tts_speed({"speed": -9.0}) == -1.0
        assert resolve_tts_speed({"speed": 0.25}) == 0.25

    # ── Flux: multiplier format [0.5, 1.5] ────────────────────────────────────

    def test_flux_multiplier_stored_directly(self):
        from botelier.voice.tts_tuning import resolve_tts_speed

        assert resolve_tts_speed({"speed": 1.2}, "flux-haley-en") == 1.2
        assert resolve_tts_speed({"speed": 0.7}, "flux-haley-en") == 0.7
        assert resolve_tts_speed({"speed": 0.5}, "flux-haley-en") == 0.5
        assert resolve_tts_speed({"speed": 1.5}, "flux-haley-en") == 1.5

    def test_flux_multiplier_default_one_returns_zero_sentinel(self):
        # 1.0 is Deepgram's default → resolver returns 0.0 so callers omit it.
        from botelier.voice.tts_tuning import resolve_tts_speed

        assert resolve_tts_speed({"speed": 1.0}, "flux-haley-en") == 0.0

    def test_flux_legacy_negative_delta_converted(self):
        # Old delta -0.4 → multiplier = 1.0 + (-0.4)/2 = 0.8.
        from botelier.voice.tts_tuning import resolve_tts_speed

        assert resolve_tts_speed({"speed": -0.4}, "flux-haley-en") == 0.8

    def test_flux_legacy_max_negative_delta_gives_min_multiplier(self):
        from botelier.voice.tts_tuning import resolve_tts_speed

        assert resolve_tts_speed({"speed": -1.0}, "flux-haley-en") == 0.5

    def test_flux_legacy_positive_delta_below_range_converted(self):
        # Old delta 0.3 (positive, < 0.5) → multiplier = 1.0 + 0.3/2 = 1.15.
        from botelier.voice.tts_tuning import resolve_tts_speed

        assert resolve_tts_speed({"speed": 0.3}, "flux-haley-en") == 1.15

    def test_flux_speed_clamped_above_max(self):
        from botelier.voice.tts_tuning import resolve_tts_speed

        assert resolve_tts_speed({"speed": 2.0}, "flux-haley-en") == 1.5

    def test_flux_speed_rounded_to_nearest_005(self):
        # Any stored value that doesn't land on a 0.05 increment is rounded.
        from botelier.voice.tts_tuning import resolve_tts_speed

        # 1.17 → nearest 0.05 step → 1.15
        assert resolve_tts_speed({"speed": 1.17}, "flux-haley-en") == 1.15
        # 1.13 → nearest 0.05 step → 1.15
        assert resolve_tts_speed({"speed": 1.13}, "flux-haley-en") == 1.15

    # ── Expressivity: Flux-only capability boundary ───────────────────────────

    def test_expressivity_is_clamped_to_flux_range(self):
        from botelier.voice.tts_tuning import resolve_tts_expressivity

        # Values beyond [-2, 2] are clamped, not rejected.
        assert resolve_tts_expressivity({"expressivity": 99}, "flux-haley-en") == 2
        assert resolve_tts_expressivity({"expressivity": -99}, "flux-haley-en") == -2

    def test_expressivity_is_none_for_non_flux_voices(self):
        from botelier.voice.tts_tuning import resolve_tts_expressivity

        # Expressivity is Flux-only; Aura, Aura-2, and blank must return None.
        assert resolve_tts_expressivity({"expressivity": 2}, "aura-2-helena-en") is None
        assert resolve_tts_expressivity({"expressivity": 2}, "aura-asteria-en") is None
        assert resolve_tts_expressivity({"expressivity": 2}, "") is None
        assert resolve_tts_expressivity({"expressivity": 2}, None) is None

    def test_expressivity_applies_for_flux_voices(self):
        from botelier.voice.tts_tuning import resolve_tts_expressivity

        assert resolve_tts_expressivity({"expressivity": -1}, "flux-alexis-en") == -1
        assert resolve_tts_expressivity({"expressivity": 2}, "flux-haley-en") == 2

    def test_expressivity_none_when_unset_for_flux(self):
        from botelier.voice.tts_tuning import resolve_tts_expressivity

        assert resolve_tts_expressivity({}, "flux-alexis-en") is None

    def test_build_tuning_params_omits_zero_expressivity(self):
        from botelier.voice.tts_tuning import build_tuning_params

        # 0 is the Flux provider default — omit it.
        params = build_tuning_params(0.0, 0)
        assert "expressivity=" not in " ".join(params)

    def test_build_tuning_params_includes_nonzero_expressivity(self):
        from botelier.voice.tts_tuning import build_tuning_params

        assert "expressivity=-2" in build_tuning_params(0.0, -2)
        assert "expressivity=2" in build_tuning_params(0.0, 2)
        assert "expressivity=-1" in build_tuning_params(0.0, -1)
        assert "expressivity=1" in build_tuning_params(0.0, 1)


# ---------------------------------------------------------------------------
# Greeting cache/prewarm parity — the cached greeting must match the live
# call's speed/expressivity, and changing either must invalidate the cache.
# ---------------------------------------------------------------------------


class TestGreetingCacheSpeedExpressivityParity:
    def test_cache_key_changes_with_speed(self):
        from botelier.voice.greeting_cache import _cache_key

        base = _cache_key("Hello!", {"voice": "flux-haley-en"})
        faster = _cache_key("Hello!", {"voice": "flux-haley-en", "speed": 1.2})
        assert base != faster

    def test_cache_key_changes_with_expressivity_for_flux(self):
        from botelier.voice.greeting_cache import _cache_key

        # Default (no expressivity) vs. expressivity=-2 must produce different keys.
        base = _cache_key("Hello!", {"voice": "flux-haley-en"})
        calm = _cache_key("Hello!", {"voice": "flux-haley-en", "expressivity": -2})
        assert base != calm

    def test_cache_key_ignores_expressivity_for_aura_voice(self):
        # Expressivity is not sent to Aura, so any expressivity value in
        # tts_config must not perturb the cache key for Aura voices.
        from botelier.voice.greeting_cache import _cache_key

        base = _cache_key("Hello!", {"voice": "aura-2-helena-en"})
        with_expressivity = _cache_key(
            "Hello!", {"voice": "aura-2-helena-en", "expressivity": 2}
        )
        assert base == with_expressivity

    def test_cache_key_stable_for_default_speed_variants_on_flux(self):
        # speed=0 (legacy default), speed=1.0 (multiplier default), and no
        # speed key at all all resolve to "omit" → cache key must be identical.
        from botelier.voice.greeting_cache import _cache_key

        implicit = _cache_key("Hello!", {"voice": "flux-haley-en"})
        legacy_zero = _cache_key(
            "Hello!", {"voice": "flux-haley-en", "speed": 0, "expressivity": 0}
        )
        multiplier_one = _cache_key(
            "Hello!", {"voice": "flux-haley-en", "speed": 1.0, "expressivity": 0}
        )
        assert implicit == legacy_zero
        assert implicit == multiplier_one

    @pytest.mark.asyncio
    async def test_rest_call_sends_speed_and_expressivity_for_flux(self, tmp_path, monkeypatch):
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
            {"voice": "flux-haley-en", "speed": 1.1, "expressivity": -2},
            api_key="test-key",
        )
        assert "/v2/speak" in captured["url"]
        assert "speed=1.1" in captured["url"]
        assert "expressivity=-2" in captured["url"]

    @pytest.mark.asyncio
    async def test_rest_call_never_sends_expressivity_for_aura(self, tmp_path, monkeypatch):
        # Aura (/v1/speak) must not receive an expressivity param even if
        # tts_config has one stored.
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
            {"voice": "aura-2-helena-en", "speed": 0.5, "expressivity": 2},
            api_key="test-key",
        )
        assert "/v1/speak" in captured["url"]
        assert "speed=0.5" in captured["url"]
        assert "expressivity=" not in captured["url"]
