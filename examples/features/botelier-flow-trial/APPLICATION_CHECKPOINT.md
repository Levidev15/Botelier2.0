# Actual voice-component compatibility checkpoint

## What is tested

The separate candidate workflow builds a fresh image, verifies its wheel sources
and three declared Flux overlays, runs the original native characterization,
then imports the actual application code from that same image.

| Boundary | Actual implementation exercised | Offline observation |
| --- | --- | --- |
| STT → frames | `VoiceEngineFactory`, its gated Flux subclass and the SDK JSON event dispatcher | Eight cases: word threshold, one clear per turn, final/eager reset, new turn, interruptions disabled, zero/invalid threshold. Eager text stays interim; final text is finalized. |
| Context → LLM HTTP | Real pipeline construction, both context aggregators, `FunctionMapper`, `FlowExecutor`, Pipecat's adapter and the OpenAI client | Four cases: interruptions on/off, same-context refresh, real mapper replacing stale tools. Inspect serialized request JSON, model, instructions, token limit and disabled parallel tool calls. |
| LLM fragments → TTS | Both real custom Deepgram subclasses and real parent `run_tts`/flush methods | Fragmented substitutions, operator overrides, batching, final tail before Flush, sentence mode, cancellation and context-specific one-shot callbacks. |
| Provider → TTS completion | Started real Flux service, native audio-context worker and real receive loop | Synthetic PCM preserves 8 kHz/context identity. Flushed alone cannot complete speech; SpeechMetadata completes the actual context. |
| Speech → hangup | Actual end-call handler with real `FunctionCallParams`, native direct-speech dispatch, real completion/mark watchers and `_finalize_call_end` | No hangup on enqueue, early stop, completed synthesis alone, or wrong mark. Exactly one hangup/EndFrame after matching playback acknowledgement. Interrupted goodbye does not end the call. No extra LLM generation. |
| Failure paths | Actual custom Aura/Flux connect-error handlers and carrier mark waiter | Both providers must emit an ErrorFrame and connection-error notification, not a NameError. Unacknowledged carrier marks time out and remove their waiter. |

There are 30 application cases. Results belong to the exact checked commit and
image, not this document. The CI log and retained evidence determine pass/fail.

## Boundaries replaced by test fixtures

- Websocket and HTTP I/O use recording sockets and `httpx.MockTransport`.
  The real OpenAI SDK serializes the JSON; the fake server returns only an empty
  SSE stream. No model generates a reply.
- Real SDK setup starts the TTS service and its context worker. Fake sockets
  remain open until teardown; an exhausted finite iterator would incorrectly
  simulate a dropped provider connection and trigger reconnects.
- Carrier updates are recorded in memory. Playback acknowledgements are
  synthetic frames; nobody places or hears a phone call.
- An in-memory empty database lookup lets the real terminal tool-usage logger
  run. All actual sessions, drivers, SQLite connections and server startup are
  denied. ORM model declarations use real SQLAlchemy, not a database connection.
- The voice package is bootstrapped as a test-only namespace to avoid its eager
  CallHandler/database initializer. The engine, agent model, mapper and executor
  are imported from their real files; no method bodies are extracted or copied.
- OpenAI's OS-header fingerprint uses a fixed test host string. That metadata
  probe otherwise executes `uname` on some hosts. The subprocess guard remains
  enabled, and the actual request builder and JSON serializer are not replaced.
- During the carrier SDK import only, IPv6 capability is declared absent.
  Otherwise urllib3 probes it by binding a loopback socket on IPv6-capable hosts.
  Socket binding remains forbidden; no guard denial is ignored.

The Python guard is not an OS sandbox. CI additionally runs with `--network none`,
`--read-only`, clean environment variables, read-only test mounts and a temporary
filesystem. Unexpected guard denials fail the checkpoint even if the application
catches them. Guard self-tests deliberately exercise their own denial paths.

## Minimal application change

Both custom Deepgram connection-error paths referenced `ErrorFrame` without
importing it. Injected provider failures reproduced a NameError in each branch.
The isolated candidate adds that import; tests assert the expected error frame
and asynchronous error notification. No dependency or production runtime is
changed by this fix.

## What a pass does not establish

- No full FastAPI/CallHandler boot, customer database, Azure staging environment,
  phone route, paid speech/model request or acoustic quality check is exercised.
- This is not a continuous STT → LLM → TTS replay through the entire live worker.
  The real components and selected connections are tested separately, with a
  continuous terminal-handler → TTS → carrier-ack path.
- Full transcript reconciliation, the complete transfer handler, carrier failure
  recovery and every assistant/provider configuration remain to be checked.
- API/MCP requests, booking writes, SMS and payment links are not executed.
- No saved-definition compiler, deterministic native flow controller, UI
  controls, node-order fix or migration is activated.
- Existing deprecation warnings are visible. Their presence is not approval to
  upgrade the SDK or replace speech-context classes in this checkpoint.

Finish the outstanding application/lifecycle checks and report their evidence
before advancing to node contracts or a native adapter. No production merge,
Azure deployment or paid rehearsal is authorized by this checkpoint.
