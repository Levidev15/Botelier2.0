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

## Voices
36 voices, format `flux-{name}-en`. Featured for IVR: alexis, haley, heather (female); miles, cole (male). All listed in `providers.py` `DEEPGRAM_FLUX` config.
