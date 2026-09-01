"""Greeting audio cache for Botelier voice assistants.

Generates TTS audio via the Deepgram REST API and persists it locally as raw
PCM bytes (linear16, 8 kHz, mono) so subsequent calls replay the cached file
directly, saving per-call Deepgram TTS tokens.

Audio format : linear16 PCM, 8 kHz, mono (16 bits / sample, 2 bytes / sample)
Cache key    : SHA-256(greeting_text | tts_model | tts_voice | "8000" | "linear16")
Cache dir    : <project_root>/uploads/greeting_cache/
File ext     : .pcm  (raw int16-LE, 8 kHz, mono, no container header)
Sidecar      : assistant_<id>.json — records the most-recently-cached key so the
               status endpoint can detect outdated (stale) cached audio.

Rationale for PCM instead of μ-law
-----------------------------------
Pipecat's TwilioFrameSerializer.serialize() calls pcm_to_ulaw() internally when
it processes OutputAudioRawFrame / TTSAudioRawFrame.  If we stored μ-law and
fed it as an AudioRawFrame, the serializer would double-encode and produce
corrupted output.  Storing PCM lets the normal serialization path work without
modification.
"""

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from loguru import logger

_CACHE_DIR: Optional[str] = None


def _get_cache_dir() -> str:
    global _CACHE_DIR
    if _CACHE_DIR is None:
        # __file__ → botelier/backend/botelier/voice/greeting_cache.py
        # dirname x3 → botelier/backend/
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _CACHE_DIR = os.path.join(base, "uploads", "greeting_cache")
        os.makedirs(_CACHE_DIR, exist_ok=True)
    return _CACHE_DIR


def _cache_key(greeting_text: str, tts_config: dict) -> str:
    """Deterministic cache key from greeting text and TTS configuration.

    Incorporates ``model``, ``voice``, fixed ``"8000"`` sample-rate, fixed
    ``"linear16"`` encoding, and the resolved ``speed``/``expressivity``
    tuning values.  The cache always stores 8 kHz linear16 PCM regardless of
    the runtime encoding the assistant may use — but speed/expressivity DO
    change what's synthesised, so they must be part of the key: otherwise
    changing an assistant's speaking rate or expressivity would keep serving
    stale audio generated under the old settings.
    """
    from .tts_tuning import build_tuning_params, resolve_tts_expressivity, resolve_tts_speed

    tts_config = tts_config or {}
    model = tts_config.get("voice") or tts_config.get("model") or "aura-2-helena-en"
    voice = tts_config.get("voice") or "aura-2-helena-en"
    speed = resolve_tts_speed(tts_config)
    expressivity = resolve_tts_expressivity(tts_config, voice)
    # Hash the same tuning params that actually get sent on the wire (via
    # build_tuning_params) rather than the raw resolved values — settings
    # that are functionally equivalent (e.g. expressivity unset vs.
    # explicit 1, the provider default) must hash identically so they don't
    # create redundant cache entries for audio that would sound the same.
    tuning = "&".join(build_tuning_params(speed, expressivity))
    raw = f"{greeting_text}|{model}|{voice}|8000|linear16|{tuning}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_path(key: str) -> str:
    return os.path.join(_get_cache_dir(), f"{key}.pcm")


def _sidecar_path(assistant_id: str) -> str:
    return os.path.join(_get_cache_dir(), f"assistant_{assistant_id}.json")


def _write_sidecar(assistant_id: str, key: str) -> None:
    """Record the most-recently-cached key for *assistant_id*."""
    path = _sidecar_path(assistant_id)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump({"last_key": key}, fh)
    os.replace(tmp, path)


def _read_sidecar(assistant_id: str) -> Optional[str]:
    """Return the last-cached key for *assistant_id*, or ``None``."""
    path = _sidecar_path(assistant_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            return json.load(fh).get("last_key")
    except Exception:
        return None


def get_cache_status(
    greeting_text: str,
    tts_config: dict,
    assistant_id: Optional[str] = None,
) -> dict:
    """Return the cache status for the given greeting + TTS configuration.

    Returns a dict:
      cached            : bool      – current text+voice is cached
      cached_at         : datetime | None – UTC timestamp of the active cache file
                          (or the old file when outdated)
      text_matches_cache: bool      – True when ``cached=True``; False otherwise
      outdated          : bool      – True when an older cache exists for a
                          different text (only detectable if *assistant_id* is
                          provided and a sidecar was previously written)
      cache_key         : str       – hex digest for the current parameters
    """
    key = _cache_key(greeting_text, tts_config)
    path = _cache_path(key)
    current_cached = os.path.exists(path)
    outdated = False
    cached_at = None

    if current_cached:
        cached_at = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    elif assistant_id:
        last_key = _read_sidecar(assistant_id)
        if last_key and last_key != key:
            old_path = _cache_path(last_key)
            if os.path.exists(old_path):
                outdated = True
                cached_at = datetime.fromtimestamp(os.path.getmtime(old_path), tz=timezone.utc)

    return {
        "cached": current_cached,
        "cached_at": cached_at,
        "text_matches_cache": current_cached,
        "outdated": outdated,
        "cache_key": key,
    }


async def get_or_generate_greeting_audio(
    greeting_text: str,
    tts_config: dict,
    api_key: str,
    assistant_id: Optional[str] = None,
) -> bytes:
    """Return raw linear16 PCM audio bytes (8 kHz, mono) for *greeting_text*.

    Cache hit  → reads and returns the cached .pcm file (no API call).
    Cache miss → calls the Deepgram TTS REST API (linear16, 8 kHz), writes the
                 result atomically, updates the per-assistant sidecar, returns bytes.

    The returned bytes are suitable for direct use in ``TTSAudioRawFrame``
    (sample_rate=8000, num_channels=1).  The Pipecat TwilioFrameSerializer
    will then encode them to μ-law for transmission to Twilio.

    Args:
        greeting_text: Text to synthesise.
        tts_config:    Dict with optional keys ``model`` and ``voice``.
                       Both must be a Deepgram model name (e.g. ``"aura-2-helena-en"``).
        api_key:       Deepgram API key (``DEEPGRAM_API_KEY``).
        assistant_id:  Optional assistant UUID; used to write the sidecar for
                       outdated-cache detection.
    """
    key = _cache_key(greeting_text, tts_config)
    path = _cache_path(key)

    if os.path.exists(path):
        size = os.path.getsize(path)
        logger.info(f"🎙️ Cache HIT — greeting PCM {size} bytes (key={key[:8]}…)")
        _hit_path = path  # capture before entering thread

        def _read_cache():
            with open(_hit_path, "rb") as fh:
                return fh.read()

        return await asyncio.to_thread(_read_cache)

    from .tts_tuning import build_tuning_params, resolve_tts_expressivity, resolve_tts_speed

    model = tts_config.get("voice") or tts_config.get("model") or "aura-2-helena-en"
    voice = tts_config.get("voice") or "aura-2-helena-en"

    # Always generate at 8 kHz linear16 PCM, no container, mono.
    # The TwilioFrameSerializer handles PCM→μ-law encoding during playback.
    #
    # Flux TTS uses /v2/speak; Aura uses /v1/speak.  Detect by voice-name prefix.
    speak_version = "v2" if model.startswith("flux-") else "v1"

    # Speed/expressivity must mirror the live engine (engine.py) exactly, or
    # the cached greeting audibly diverges from the rest of the call. Uses
    # the same shared resolver — resolve_tts_expressivity already enforces
    # the Aura-2-only capability boundary, so Flux/Aura-1 voices never get
    # an expressivity param here either.
    speed = resolve_tts_speed(tts_config)
    expressivity = resolve_tts_expressivity(tts_config, voice)
    tuning_params = build_tuning_params(speed, expressivity)
    tuning_qs = ("&" + "&".join(tuning_params)) if tuning_params else ""

    logger.info(
        f"🎙️ Cache MISS — calling Deepgram TTS REST "
        f"(model={model}, sr=8000/linear16, speed={speed}, expressivity={expressivity}, key={key[:8]}…)"
    )

    url = (
        f"https://api.deepgram.com/{speak_version}/speak"
        f"?model={model}&encoding=linear16&sample_rate=8000&container=none{tuning_qs}"
    )
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=headers, json={"text": greeting_text})
        resp.raise_for_status()
        pcm_bytes = resp.content

    # Atomic write offloaded to thread — open/write/os.replace are blocking syscalls.
    # _write_sidecar is also a file write; kept inside the same thread call.
    _write_path = path
    _write_pcm = pcm_bytes
    _write_key = key
    _write_aid = assistant_id

    def _write_cache():
        tmp = _write_path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(_write_pcm)
        os.replace(tmp, _write_path)
        if _write_aid:
            _write_sidecar(_write_aid, _write_key)

    await asyncio.to_thread(_write_cache)

    logger.info(f"🎙️ Greeting PCM cached — {len(pcm_bytes)} bytes (key={key[:8]}…)")
    return pcm_bytes
