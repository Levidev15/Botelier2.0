---
name: Deepgram Flux TTS integration
description: How Flux TTS differs from Aura and where all the wiring lives
---

# Deepgram Flux TTS integration

## Rule
Flux TTS uses `/v2/speak` (not `/v1/speak`), sends `Interrupt` for barge-in (not `Clear`), and ends a turn on `SpeechMetadata` (not `Flushed`). Never send a `Close` message on disconnect — just close the socket.

**Why:** Different protocol from Aura; mixing them silently drops audio or leaves hung audio contexts.

## How to apply
- `src/pipecat/services/deepgram/flux/tts_base.py` — the service class (also copied to pip pipecat for dev)
- Provider registered as `TTSProvider.DEEPGRAM_FLUX = "deepgram-flux"` in `providers.py`
- Engine factory at `engine.py` `create_tts_service` — `elif provider == "deepgram-flux":` branch
- Greeting cache auto-detects Flux voices by `model.startswith("flux-")` and uses `/v2/speak`
- Greeting condition in `call_handler.py` extended to `in ("deepgram", "deepgram-flux")`

## Dev/prod path
- Pip pipecat 1.5.0 in dev **does not** ship Flux TTS; files must be copied to the pip location manually after any tts_base.py change: `cp src/pipecat/services/deepgram/flux/tts_base.py ~/.../site-packages/pipecat/services/deepgram/flux/`
- Production Docker uses `src/pipecat/` via PYTHONPATH — fork already has the files

## Conversation context
Flux is conversation-aware through the **persistent WebSocket connection** — no explicit transcript-passing is needed. The connection stays open for the call duration and Flux maintains acoustic state internally.

## Expressivity (Beta)
Flux supports `expressivity` as a connection query param (`-2` calm → `0` default → `2` animated); Aura/Aura-2 do NOT. Omit when `== 0` (the provider default). `resolve_tts_expressivity` in `tts_tuning.py` enforces this boundary by checking `voice.startswith("flux-")`.

## Speed scale mismatch
Deepgram Flux expects speed as a **discrete multiplier** (`0.85`, `0.9` … `1.15` in 0.05 steps), not the internal −1..+1 offset our UI exposes. Sending an out-of-range value returns `SPEED_NOT_SUPPORTED`. Aura `/v1/speak` uses a different (relative offset) scale that our code already handles correctly — the mismatch is Flux-specific.

## Voices
36 voices, format `flux-{name}-en`. Featured for IVR: alexis, haley, heather (female); miles, cole (male). All listed in `providers.py` `DEEPGRAM_FLUX` config.
