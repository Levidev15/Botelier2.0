---
name: TTS config knobs need dual propagation and precise capability gating
description: A voice-tuning knob added to the live call engine often has an independent prewarm/cache construction path that is easy to miss, and UI/behavior gating for a knob must check the specific capability it depends on, not a broader provider category.
---

## Two independent construction paths

A live voice pipeline may build its provider request in more than one
place: once for the real call, and again — independently — wherever
audio is pre-generated or cached ahead of time (e.g. a greeting prewarm).
These paths are easy to keep in sync when they're created together but
easy to let drift apart afterward, since a change to one doesn't visibly
break the other in dev — it just makes the *first* impression of a call
quietly diverge from the rest of it.

**Why this matters:** a caller/user experiences these paths back-to-back
as one seamless thing. A knob applied to only the live path produces an
audible or behavioral seam right at the point they connect.

**How to apply:** whenever a tuning knob is added to a live-request
construction path, actively search for other places that build the same
kind of request (prewarm, cache, preview, test-call) and thread the knob
through all of them identically. If a cache key is derived from request
parameters, the new knob must be part of that key too, or a settings
change won't invalidate stale cached output.

## Gate on the real capability, not the provider

A control or code path that only some models/voices under a provider
support must check that specific capability (e.g. by inspecting the
selected model/voice string), not a coarser "is this provider X" check
that also matches sibling models/voices which don't support it. Prefer
centralizing the coercion + capability-boundary + range-clamping logic for
such a knob in one shared helper used by every construction path, so the
boundary can't drift out of sync between call sites.

**Expressivity:** Flux-only Beta on `/v2/speak`. `resolve_tts_expressivity`
checks `voice.startswith("flux-")`. Range −2 to 2; default 0 is omitted.

## Deepgram Flux speed format — multiplier, not delta

Flux `/v2/speak` uses `speed` as a **multiplier** (`0.5`–`1.5`, `0.05`
increments, default `1.0`). Out-of-range or unknown parameters are
**rejected** at WebSocket upgrade time, silencing the voice. The old UI
stored speed as a **delta** (`-1.0` to `+1.0`, 0 = default).

`resolve_tts_speed(tts_config, voice)` now dispatches on `voice`:
- **Flux** (`voice.startswith("flux-")`): raw value ≥ 0.5 → multiplier
  as-is; raw < 0.5 (legacy delta) → `1.0 + raw/2`; result clamped to
  [0.5, 1.5], rounded to 0.05; 1.0 → sentinel 0.0 (omit).
- **Aura/non-Flux**: legacy delta format, clamped to [-1.0, +1.0].

Always pass `voice` when calling `resolve_tts_speed` so both code paths
(live WebSocket engine and greeting cache REST) apply the correct format.
The cache key naturally invalidates when the resolved speed changes (key
is built from `build_tuning_params(speed, expressivity)`, which uses the
resolved value, not the raw stored value).

**Why:** Deepgram rejects unknown/out-of-range params at connection time —
a negative delta like -0.3 reaches Deepgram as-is and kills the WebSocket
upgrade → voice goes silent for the entire call.
