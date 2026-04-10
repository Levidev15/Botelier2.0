"""
Greeting audio cache for Botelier voice assistants.

Generates TTS audio via the Deepgram REST API and persists it locally as raw
μ-law bytes so that subsequent calls replay the cached file directly, bypassing
Deepgram and saving per-call TTS tokens.

Cache key  : SHA-256(greeting_text | voice | sample_rate)
Cache dir  : <project_root>/uploads/greeting_cache/
File ext   : .ul  (raw μ-law, 8 kHz, mono, no container header)
"""

import hashlib
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
        base = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        _CACHE_DIR = os.path.join(base, "uploads", "greeting_cache")
        os.makedirs(_CACHE_DIR, exist_ok=True)
    return _CACHE_DIR


def _cache_key(greeting_text: str, tts_config: dict) -> str:
    voice = tts_config.get("voice") or "aura-2-helena-en"
    sample_rate = str(tts_config.get("sample_rate", 8000))
    raw = f"{greeting_text}|{voice}|{sample_rate}|mulaw"
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_path(key: str) -> str:
    return os.path.join(_get_cache_dir(), f"{key}.ul")


def get_cache_status(greeting_text: str, tts_config: dict) -> dict:
    """
    Return the current cache status for the given greeting + TTS config.

    Returns a dict:
      cached     : bool     – whether a cached file exists for the current text+voice
      cached_at  : datetime | None – UTC mtime of the cached file
      cache_key  : str      – hex digest used as the cache file name
    """
    key = _cache_key(greeting_text, tts_config)
    path = _cache_path(key)
    if os.path.exists(path):
        mtime = os.path.getmtime(path)
        return {
            "cached": True,
            "cached_at": datetime.fromtimestamp(mtime, tz=timezone.utc),
            "cache_key": key,
        }
    return {"cached": False, "cached_at": None, "cache_key": key}


async def get_or_generate_greeting_audio(
    greeting_text: str,
    tts_config: dict,
    api_key: str,
) -> bytes:
    """
    Return raw μ-law audio bytes (8 kHz, mono) for *greeting_text*.

    Cache hit  → reads and returns the cached .ul file (no API call).
    Cache miss → calls the Deepgram TTS REST API, writes atomically, returns bytes.

    Args:
        greeting_text: The greeting text to synthesise.
        tts_config:    Dict with optional keys ``voice`` and ``sample_rate``.
                       ``voice`` must be a Deepgram model name
                       (e.g. ``"aura-2-helena-en"``).
        api_key:       Deepgram API key (``DEEPGRAM_API_KEY``).
    """
    key = _cache_key(greeting_text, tts_config)
    path = _cache_path(key)

    if os.path.exists(path):
        size = os.path.getsize(path)
        logger.info(f"🎙️ Cache HIT — greeting audio {size} bytes (key={key[:8]}…)")
        with open(path, "rb") as fh:
            return fh.read()

    voice = tts_config.get("voice") or "aura-2-helena-en"
    sample_rate = tts_config.get("sample_rate", 8000)

    logger.info(
        f"🎙️ Cache MISS — calling Deepgram TTS REST "
        f"(voice={voice}, sr={sample_rate}, key={key[:8]}…)"
    )

    url = (
        "https://api.deepgram.com/v1/speak"
        f"?model={voice}&encoding=mulaw&sample_rate={sample_rate}&container=none"
    )
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=headers, json={"text": greeting_text})
        resp.raise_for_status()
        audio_bytes = resp.content

    # Atomic write: temp file → rename so concurrent readers never see partial data.
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(audio_bytes)
    os.replace(tmp, path)

    logger.info(
        f"🎙️ Greeting cached — {len(audio_bytes)} bytes (key={key[:8]}…)"
    )
    return audio_bytes
