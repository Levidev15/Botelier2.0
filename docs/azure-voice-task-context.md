# Azure Voice Pipeline Task Context

Last updated: 2026-06-01

## Purpose

This file is a durable handoff for the next Codex session. The goal is to continue reviewing and planning the migration of Botelier's backend voice runtime to Azure Container Apps, with special attention to the live-call voice pipeline and Twilio Media Streams behavior.

No code changes have been made for these findings yet.

## Current Objective

Scan and harden all code used during a live voice call before switching backend voice traffic to Azure Container Apps.

Primary goals:

- Identify concrete, source-backed risks in the call path.
- Recommend changes that make Azure Container Apps deployment safer.
- Standardize inefficient or fragile voice-pipeline behavior.
- Preserve low-latency call handling and avoid clipped speech, broken transfer flows, or call state loss.

## Important Local Context

Repository root:

```text
C:\Users\Corey\Documents\Botelier2.0
```

Important project memory/docs:

- `replit.md`
- `botelier/README.md`
- `botelier/backend/README.md`
- `botelier/backend/botelier/voice/README.md`
- `botelier/backend/botelier/api/README.md`
- `botelier/backend/botelier/services/README.md`

Main voice-call path:

- `botelier/backend/botelier/api/calls.py`
  - Handles `/api/calls/incoming`
  - Creates `CallLog`
  - Schedules `prewarm_call_config`
  - Returns TwiML with `<Connect><Stream>`
- `botelier/backend/botelier/api/websockets.py`
  - Accepts Twilio WebSocket
  - Reads `connected` and `start`
  - Validates `CallLog` binding and HMAC stream token
  - Delegates to singleton `call_handler`
- `botelier/backend/botelier/voice/call_handler.py`
  - Orchestrates per-call pipeline
  - Uses prewarm cache, DB lookup, tools, MCP, serializer, transport, pipeline runner, transcript save, and cleanup
  - Holds process-local call state in dictionaries
- `botelier/backend/botelier/voice/engine.py`
  - Builds the Pipecat pipeline
  - Flow includes transport input, VAD/STT/user context/LLM/TTS/output, interruption handling, greeting, idle tracking, latency tracking, and TTS completion watcher
- `botelier/backend/botelier/voice/function_mapper.py`
  - Handles transfer, end-call, API, and flow tools
  - Warm/cold transfer logic updates Twilio call TwiML through Twilio REST
- `botelier/backend/botelier/voice/prewarm.py`
  - In-memory prewarm cache for assistant/tools/greeting
- `botelier/backend/botelier/voice/greeting_cache.py`
  - Caches Deepgram greeting PCM under `uploads/greeting_cache`
- `botelier/backend/botelier/services/call_logger.py`
- `botelier/backend/botelier/services/call_event_queue.py`
- `botelier/backend/botelier/services/shutdown_finalizer.py`
- `botelier/backend/botelier/services/recording_sync.py`

Azure deployment files:

- `botelier/backend/Dockerfile`
- `scripts/azure-voice-setup.sh`
- `.github/workflows/deploy-voice.yml`
- `.dockerignore`

## Source-Backed Findings To Resume

### 1. Keep Azure voice at one replica until call state is externalized

Current code evidence:

- `CallHandler` is a singleton with process-local dictionaries such as active calls, call mappers, call contexts, call tasks, pending cancels, and precomputed configs.
- Azure setup currently uses `--min-replicas 1` and `--max-replicas 10`.
- Azure sticky sessions are not a complete correctness boundary for live call state.

Trusted-source evidence:

- Azure Container Apps supports WebSocket over HTTP ingress.
- Azure Container Apps sticky sessions are cookie-based and limited to HTTP ingress behavior; they can route to a different replica when the previous replica is unavailable.

Suggested change:

- For the first Azure voice migration, set voice ACA `max-replicas=1`.
- Only enable multiple replicas after externalizing live-call state and coordination to Redis/Postgres or another shared store.

Source links:

- https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview
- https://learn.microsoft.com/en-us/azure/container-apps/sticky-sessions

### 2. Remove `<Stop><Stream>` from bidirectional transfer TwiML

Current code evidence:

- Incoming voice uses Twilio `<Connect><Stream>` in `botelier/backend/botelier/api/calls.py`.
- Transfer paths in `botelier/backend/botelier/voice/function_mapper.py` insert `<Stop><Stream name="..."/></Stop>` before `<Dial>` in some warm/flow transfer TwiML.

Trusted-source evidence:

- Twilio says `<Stop>` applies to streams started with `<Start>`.
- For bidirectional streams started with `<Connect><Stream>`, Twilio says the stream is stopped by ending the call or updating the call with new TwiML.

Suggested change:

- Do not include `<Stop><Stream>` for bidirectional Media Streams.
- For transfer, update the live call directly with replacement TwiML such as `<Response><Dial>...</Dial></Response>` or the correct `<Refer>` flow.

Source link:

- https://www.twilio.com/docs/voice/twiml/stream

### 3. Use Twilio `mark` messages for critical audio boundaries

Current code evidence:

- `src/pipecat/serializers/twilio.py` sends `media` messages for audio and `clear` for interruptions.
- It does not appear to send Twilio `mark` messages.
- Transfer code uses a fixed warm-transfer PSTN drain sleep, currently around `0.7` seconds, before updating Twilio.

Trusted-source evidence:

- Twilio Media Streams supports sending `mark` after `media`.
- Twilio sends a `mark` event back after the corresponding buffered audio has completed playback.
- Twilio `clear` empties buffered audio and returns pending marks.

Suggested change:

- Add mark tracking for important boundaries such as transfer preamble, goodbye, and potentially greeting completion.
- Wait for the matching Twilio `mark` callback before updating the call or ending it, with a bounded timeout fallback.
- Replace fixed sleep-based drain logic for transfer/end-call paths.

Source link:

- https://www.twilio.com/docs/voice/media-streams/websocket-messages

### 4. Fix End Call tool so goodbye audio is not clipped

Current code evidence:

- `_map_end_call` pushes `TTSSpeakFrame(goodbye_message)` and then immediately pushes `EndFrame`.
- This risks ending the pipeline before the goodbye audio fully plays to the caller.

Suggested change:

- Use the existing `TtsCompletionWatcher.schedule_after_speech()` pattern or Twilio `mark` tracking before pushing `EndFrame` or hanging up.
- Prefer Twilio `mark` for the final boundary if the audio must be guaranteed at the caller side, because TTS completion does not necessarily prove Twilio playback finished.

### 5. Make flow-transfer failure behavior match normal transfer behavior

Current code evidence:

- Normal transfer only pushes `EndFrame` if Twilio update succeeded or the call already ended.
- Flow transfer currently pushes `EndFrame` in a `finally` block even if transfer update fails.

Suggested change:

- Gate flow-transfer `EndFrame` on a successful Twilio update or already-ended condition.
- If transfer fails, keep the voice pipeline alive and tell the caller the transfer could not be completed.

### 6. Wire or remove dead TTS service context repair path

Current code evidence:

- `FunctionMapper.set_tts_service()` exists.
- `_tts_service` is used to create a fresh audio context before transfer phrase playback.
- `call_handler.py` sets the TTS completion watcher but does not appear to call `set_tts_service()`.
- `VoiceEngineFactory.create_pipeline()` does not appear to return the TTS service object.

Suggested change:

- Either return the TTS service from pipeline creation and call `set_tts_service(tts)`, or remove the dead branch.
- Prefer wiring it if the context-repair path is still valuable for transfer reliability.

### 7. Build TwiML with XML-safe APIs or escaping

Current code evidence:

- TwiML is built with raw f-strings in several places, including incoming stream response and transfer TwiML.
- Most values are currently phone numbers, SIDs, URLs, and tokens, but some tool-configured values may become unsafe if not escaped.

Suggested change:

- Prefer `twilio.twiml.voice_response.VoiceResponse`, `Connect`, `Stream`, `Dial`, `Number`, etc.
- If a Twilio helper cannot express a specific construct, use a shared XML escape helper for attributes and text.

### 8. Add a real readiness check for Azure

Current code evidence:

- Deployment health check uses `/api/health`.
- `/api/health` is a static-style liveness endpoint and does not prove DB/secrets/provider readiness.

Suggested change:

- Add `/api/ready` for Azure readiness.
- Check required voice env vars, database connectivity, and any minimal provider configuration needed to accept calls.
- Keep `/api/health` as cheap liveness.

### 9. Fix deployment/runtime packaging risks

Current code evidence:

- Root `.dockerignore` is used by the Docker build context.
- Root `.dockerignore` does not exclude `botelier/backend/uploads/`.
- `greeting_cache.py` writes runtime greeting cache under `uploads/greeting_cache`.

Suggested change:

- Exclude `botelier/backend/uploads/` from the root `.dockerignore`.
- Treat generated greeting cache and uploads as runtime data, not image contents.
- For Azure, prefer ephemeral local cache or Azure storage depending on whether cache persistence matters.

### 10. Budget DB connections for Azure replica count

Current code evidence:

- Azure setup sets `DB_POOL_SIZE=5` and `DB_MAX_OVERFLOW=10`.
- With `max-replicas=10`, this can allow up to 150 DB connections from the voice app alone.

Suggested change:

- For single replica, current values may be acceptable.
- If scaling beyond one replica, reduce pool/overflow or use an external pooler, and confirm the Neon/Postgres connection limit.

### 11. Avoid startup migrations/backfills in every replica

Current code evidence:

- App startup calls DB initialization.
- Initialization includes table creation/migrations/backfills/sweeper-style work.

Suggested change:

- For Azure, separate migrations/backfills into a one-off release task or CI/CD migration step.
- Keep app startup limited to lightweight readiness/startup checks.

## Things That Look Good

- WebSocket start message verifies `CallLog` binding and HMAC stream token.
- Twilio `<Stream>` custom metadata is passed through nested `<Parameter>`, which matches Twilio's restriction that stream URLs cannot include query strings.
- Transport sample rates are explicitly configured for 8 kHz in/out.
- Greeting injection is downstream of STT, avoiding phantom user transcript.
- API request tools use SSRF-safe transport and HTTP timeouts.
- Call event queue is bounded and avoids synchronous DB writes in the audio hot path.
- `call_handler.handle_call` closes the initial FastAPI dependency DB session after setup, so do not claim a long-lived session leak unless new evidence is found.

## Suggested Test Commands

Run focused backend tests from:

```powershell
cd C:\Users\Corey\Documents\Botelier2.0\botelier\backend
$env:PYTHONPATH=".;..\..\src"
$env:PYTHONDONTWRITEBYTECODE="1"
python -m pytest tests/test_prewarm_cache.py tests/test_voice_webhook_authenticity.py -q -p no:cacheprovider
```

Run the broader backend suite with a real test DB:

```powershell
cd C:\Users\Corey\Documents\Botelier2.0\botelier\backend
$env:PYTHONPATH=".;..\..\src"
$env:DATABASE_URL="postgresql://USER:PASSWORD@HOST/TEST_DB?sslmode=require"
python -m pytest tests/ -q -p no:cacheprovider
```

Build the backend container:

```powershell
cd C:\Users\Corey\Documents\Botelier2.0
docker build -f botelier/backend/Dockerfile -t botelier-voice:test .
```

Suggested future targeted tests:

- Unit test transfer TwiML generation does not include `<Stop><Stream>` for bidirectional streams.
- Unit test end-call schedules hangup/end only after completion callback or mark timeout.
- Unit test flow-transfer failure does not end the pipeline.
- Unit test XML escaping/helper behavior for TwiML attributes.
- Integration-style test for WebSocket start validation and token rejection.

## Next Session Instructions

Start by reading this file, then inspect the relevant code paths before making changes. Do not rely only on this summary.

Recommended next action:

1. Confirm the exact line numbers for each finding in the current working tree.
2. Decide whether the immediate goal is a review report, a concrete implementation plan, or actual code changes.
3. If code changes are requested, implement in this priority order:
   - Azure single-replica and deployment safety settings.
   - Remove bidirectional `<Stop><Stream>` usage.
   - Fix end-call and transfer audio completion using TTS watcher or Twilio marks.
   - Fix flow-transfer failure behavior.
   - Wire/remove TTS service context repair path.
   - Convert risky TwiML f-strings to Twilio helper classes or escaped XML.
   - Add `/api/ready`.
   - Update Docker ignore/runtime cache handling.
4. Run focused tests first, then broader tests/build if credentials and Docker are available.

## Trusted Sources Already Consulted

- Azure Container Apps ingress overview:
  - https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview
- Azure Container Apps sticky sessions:
  - https://learn.microsoft.com/en-us/azure/container-apps/sticky-sessions
- Twilio `<Stream>` TwiML:
  - https://www.twilio.com/docs/voice/twiml/stream
- Twilio Media Streams WebSocket messages:
  - https://www.twilio.com/docs/voice/media-streams/websocket-messages

