# `voice/` — Real-time call pipeline

Pipecat wrapper that runs the live audio pipeline for every call.

## Purpose

Owns everything that happens between the Twilio media-stream WebSocket opening and the call ending: pipeline assembly, greeting, STT/LLM/TTS orchestration, tool dispatch, transcript capture, and pre-warming.

## Main files

| File | Role |
|---|---|
| `engine.py` | Builds the Pipecat pipeline: Silero VAD + `LocalSmartTurnAnalyzerV3` + Deepgram + OpenAI + TTS. Defines `LLMUserAggregatorParams` (turn aggregation tuning). |
| `call_handler.py` | Per-call orchestration: pop prewarm bundle, run pipeline, capture transcript from `LLMContext.get_messages()`, finalize on disconnect. Singleton `call_handler` exposed to `api/websockets.py`. |
| `agent.py` | System-prompt assembly from assistant + account + flow context. |
| `function_mapper.py` | Maps OpenAI tool calls to executors (MCP / HTTP integrations / KB lookups / transfer / hangup / DTMF). |
| `knowledge_handler.py` | KB lookup tool implementation. |
| `greeting_cache.py` | Pre-rendered TTS PCM cache; greeting playback bypasses live TTS. |
| `prewarm.py` | `PreWarmCache` (LRU + TTL) + `prewarm_call_config()`. Called from `api/calls.py` webhook to pre-load assistant/account/tools/MCP/greeting before the WS connects (Task #111). |
| `flows/` | Conversation-flow runtime — see [`flows/README.md`](flows/README.md) |

## How it connects

- **Inbound webhook** (`api/calls.py`) writes `CallLog`, then schedules `prewarm.prewarm_call_config()` and returns TwiML.
- **WebSocket** (`api/websockets.py`) hands the connection to `call_handler.handle_call()`, which pops the prewarm bundle (≤500 ms wait) and assembles the pipeline via `engine.py`.
- **Tool calls** from the LLM go through `function_mapper.py` → `services/mcp_client.py` / `services/integration_client.py` / `knowledge_handler.py`.
- **Lifecycle writes** flow through `services/call_logger.py` and `services/call_event_queue.py`.
- **Teardown** goes through `services/shutdown_finalizer.py`; `database.run_stuck_call_sweeper` is the safety net.

## Conventions

- Anything that needs the cached prewarm bundle reads it through `call_handler`, never directly from `prewarm.PreWarmCache` outside the consumer path.
- `engine.py` is the only place that imports Pipecat audio/transport modules.
- Greeting PCM is generated once per assistant + voice combo; cache invalidation is explicit (frontend `GreetingCacheButton.tsx` triggers a regenerate endpoint).

## Setup

Loaded as part of `main.py` startup. Pipecat's heavy models (Silero VAD, SmartTurn) are pre-warmed at process start (`main.py:137-145`) to avoid first-call latency.

## Gotchas

- **Transcript capture uses `LLMContext.get_messages()`** at `call_handler.py:1677-1679`, NOT Pipecat's `TranscriptProcessor`. The `_extract_transcript` helper faithfully reproduces whatever the LLM saw — including fragmentation caused by overly aggressive turn finalization.
- Turn fragmentation is driven by `LLMUserAggregatorParams` in `engine.py` plus `LocalSmartTurnAnalyzerV3(stop_secs=...)` and Silero VAD `stop_secs`. Tune carefully — lowering finalizes faster (snappier) but breaks long sentences mid-thought.
- Greeting is injected as TTSAudioRawFrames; before Task #110 these were transcribed by Deepgram and counted as "user speech", flipping `caller_spoke = TRUE` on calls where the human never spoke. The `FirstUserSpeechTracker` now guards against this.
- Prewarm cache miss is silent — code falls back to the cold path and emits a `cold_path_fallback` event. Watch for an elevated rate of these.
