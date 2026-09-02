"""Shared Deepgram TTS speed/expressivity resolution.

Centralizes the coercion, range clamping, and capability-boundary rules for
the ``speed`` and ``expressivity`` knobs so the live WebSocket engine
(``engine.py``) and the greeting prewarm/cache REST path
(``greeting_cache.py``) apply *exactly* the same rules.  Without this, the
cached/prewarmed greeting — the first thing every caller hears — can
silently diverge from the rest of the call.

Speed format
------------
Deepgram Flux (/v2/speak) uses a **multiplier** format: ``0.5`` to ``1.5``
in ``0.05`` increments, default ``1.0`` (normal speed).  Out-of-range or
unknown values are **rejected** by Deepgram at WebSocket upgrade time,
silencing the voice for the entire call.

The UI stores the multiplier directly (``0.5``–``1.5``, step ``0.05``).
Legacy assistants may have speed stored as a **delta** in the old
``[-1.0, +1.0]`` range (where ``0`` = normal); any value below ``0.5``
(including negatives) is treated as a legacy delta and converted:
``multiplier = 1.0 + delta / 2``  (maps ``[-1, +1]`` → ``[0.5, 1.5]``).

Aura / Aura-2 (/v1/speak) speed handling is unchanged (original delta
format, ``[-1.0, +1.0]``) pending format verification (tracked in #637).

Expressivity
------------
Deepgram documents ``expressivity`` (Beta) for Flux TTS voices only
(/v2/speak, both streaming and batch).  Aura and Aura-2 voices (/v1/speak)
do not support it.  The parameter shifts a Flux voice's delivery register
along a calm-to-animated axis (-2 calm → 0 natural default → 2 animated).
"""

from typing import Optional


def resolve_tts_speed(tts_config: dict, voice: str = "") -> float:
    """Resolve ``tts_config['speed']`` to the value that should be sent to Deepgram.

    **Flux voices** (``voice.startswith("flux-")``) — multiplier format:

    * Stored values in ``[0.5, 1.5]`` are used as the multiplier directly.
    * Values below ``0.5`` (including negatives and ``0``) are treated as
      legacy delta values and converted: ``multiplier = 1.0 + delta / 2``.
    * The result is clamped to ``[0.5, 1.5]`` and rounded to the nearest
      ``0.05`` increment (Deepgram's documented step).
    * Returns ``0.0`` (falsy sentinel) when the resolved multiplier equals
      ``1.0`` so callers can omit the parameter with ``if speed:`` — ``1.0``
      is the Deepgram default and sending it is a no-op.

    **Non-Flux voices** (Aura / Aura-2) — legacy delta format:

    * Coerces and clamps to ``[-1.0, +1.0]``.
    * Returns ``0.0`` when missing or invalid (omits the param).

    Pass *voice* so both the live WebSocket engine (``engine.py``) and the
    greeting REST path (``greeting_cache.py``) apply the same rule for the
    same voice, keeping the prewarm greeting sonically identical to the call.
    """
    try:
        raw = float((tts_config or {}).get("speed", 0) or 0)
    except (TypeError, ValueError):
        return 0.0

    if (voice or "").startswith("flux-"):
        # ── Flux: multiplier format [0.5, 1.5] ──────────────────────────────
        if raw == 0.0:
            return 0.0  # legacy stored default — omit

        if raw < 0.5:
            # Legacy delta stored by the old UI: convert to multiplier.
            # delta/2 maps [-1, +1] → [-0.5, +0.5]; offset by 1.0 → [0.5, 1.5].
            multiplier = 1.0 + raw / 2.0
        else:
            # New multiplier stored directly by the updated UI.
            multiplier = raw

        # Clamp to Deepgram's documented range (out-of-range → rejected).
        multiplier = max(0.5, min(1.5, multiplier))

        # Round to the nearest 0.05 increment (multiply by 20, round, divide).
        multiplier = round(round(multiplier * 20) / 20, 2)

        # 1.0 is the provider default — omit it so unmodified assistants
        # never send a redundant override.
        if multiplier == 1.0:
            return 0.0

        return multiplier

    else:
        # ── Aura / Aura-2: legacy delta format [-1.0, +1.0] ─────────────────
        return max(-1.0, min(1.0, raw))


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
    """Build the ``speed=``/``expressivity=`` URL query fragments.

    Omits values that equal the provider default so unmodified assistants
    never send a redundant override:

    * ``speed``: ``0.0`` is the sentinel for "use provider default" (``1.0``
      for Flux, omit for Aura).  A non-zero *speed* is always appended.
    * ``expressivity``: ``0`` is the Flux provider default; omitted when
      ``None`` or ``0``.
    """
    params: list[str] = []
    if speed:
        params.append(f"speed={speed}")
    if expressivity is not None and expressivity != 0:
        params.append(f"expressivity={expressivity}")
    return params
