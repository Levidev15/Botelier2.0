"""Shared Deepgram TTS speed/expressivity resolution.

Centralizes the coercion, range clamping, and capability-boundary rules for
the ``speed`` and ``expressivity`` knobs so the live WebSocket engine
(``engine.py``) and the greeting prewarm/cache REST path
(``greeting_cache.py``) apply *exactly* the same rules. Without this, the
cached/prewarmed greeting — the first thing every caller hears — can
silently diverge from the rest of the call.

Capability boundary: Deepgram documents ``expressivity`` (Beta) for Flux TTS
voices only (/v2/speak, both streaming and batch).  Aura and Aura-2 voices
(/v1/speak) do not support it.  The parameter shifts a Flux voice's delivery
register along a calm-to-animated axis (-2 calm → 0 natural default → 2
animated).
"""

from typing import Optional


def resolve_tts_speed(tts_config: dict) -> float:
    """Coerce and clamp ``tts_config['speed']`` to the supported [-1.0, 1.0]
    range. Invalid or missing values resolve to 0.0 (provider default,
    omitted from the request by the caller)."""
    try:
        speed = float((tts_config or {}).get("speed", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(-1.0, min(1.0, speed))


def resolve_tts_expressivity(tts_config: dict, voice: str) -> Optional[int]:
    """Coerce and clamp ``tts_config['expressivity']`` to [-2, 2].

    Returns ``None`` when unset, invalid, or when *voice* is not a Flux voice.
    Expressivity is a Flux-only Beta parameter; Aura and Aura-2 voices do not
    support it on /v1/speak.
    """
    if not voice or not voice.startswith("flux-"):
        return None
    raw = (tts_config or {}).get("expressivity")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return max(-2, min(2, value))


def build_tuning_params(speed: float, expressivity: Optional[int]) -> list[str]:
    """Build the ``speed=``/``expressivity=`` URL query fragments, omitting
    values that equal the provider default (0 for speed, 0 for
    expressivity) so unmodified assistants never send an override."""
    params: list[str] = []
    if speed:
        params.append(f"speed={speed}")
    if expressivity is not None and expressivity != 0:
        params.append(f"expressivity={expressivity}")
    return params
