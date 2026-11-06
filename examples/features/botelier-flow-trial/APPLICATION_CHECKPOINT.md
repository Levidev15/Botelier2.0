# Actual voice-component and offline call-lifecycle checkpoints

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

There are 30 component cases, plus the 14 lifecycle cases below. Results
belong to the exact checked commit and image, not this document. The CI log and
retained evidence determine pass/fail.

## First whole-call slice

The separate lifecycle entry point imports the actual `CallHandler` and runs its
cold-path setup, real factory, real native runner/worker, real ASGI websocket
transport, real STT dispatcher, OpenAI request/response processing, TTS context
workers, transcript extractor and coordinator cleanup. No application method
bodies are extracted, mirrored or replaced with a no-op runner.

One import check establishes that the actual coordinator can load under the
guard. Two complete synthetic-call cases exercise caller hangup through the
real cancellation entry point, and graceful native-worker termination. Each
requires the greeting, one accepted user turn, exactly one streaming model
request with the right messages, one spoken reply, the ordered three-message
transcript at the persistence boundary, closed sessions/event queue, cleared
call state and no newly created asynchronous tasks left running.

This is a no-tools/no-MCP, no-recording, cache-miss, Flux STT/OpenAI/Flux TTS
fixture. It does not certify the remaining call/flow combinations.

## Startup, interruption and retained-callback slice

Eleven additional cases extend the actual coordinator/native-worker harness:
- Caller hangup before task registration records and consumes its pending
  cancellation; hangup during provider startup uses the registered worker.
  Both must terminate and dispose resources without a completed greeting or
  streaming model request.
- Hangup while greeting audio is buffered must not mark that speech as heard.
- Barge-in enabled emits one provider Interrupt and carrier clear, marks the
  interrupted reply, then answers the next finalized turn once. Disabled
  interruptions preserve the current speech without clearing or replaying it.
- Five retained callbacks (LLM response, user turn, interruption, greeting and
  first speech) cannot recreate state or reopen persistence after shutdown.
  Each is also invoked during a subsequent real synthetic call with the same
  SID to check that old callbacks cannot mutate the replacement generation.
- A separate ownership-input check replaces a running call's capture buffer
  while its callback scope is still open. Old callbacks must reject that
  ownership change. Removing only the identity check reproduced stale writes;
  this is not a claim of full concurrent reconnect-handler certification.

All lifecycle cases require no unexpected error logs, leftover call-created
tasks or unexpected guard denials. Synthetic usage chunks verify that real
model-token/TTS usage still reaches the persistence handoff; actual billing
remains outside this checkpoint.

## Boundaries replaced by test fixtures

- Websocket and HTTP I/O are replaced at their transport boundaries. The
  component request fixture uses `httpx.MockTransport` and an empty SSE stream.
  The lifecycle fixture intercepts the HTTP transport for both actual clients,
  including prompt-cache warmup, and returns a fixed synthetic streaming reply.
  Real SDK serialization, response parsing and frame propagation remain active;
  no model generates a reply.
- Real SDK setup starts the TTS service and its context worker. Fake sockets
  remain open until teardown; an exhausted finite iterator would incorrectly
  simulate a dropped provider connection and trigger reconnects.
- Carrier updates are recorded in memory. Playback acknowledgements are
  synthetic frames; nobody places or hears a phone call.
- An in-memory empty database lookup lets the real terminal tool-usage logger
  run in the component suite. Lifecycle checks instead use strictly enumerated
  synthetic records/sessions. Real event queue and greeting/caller-mark logic
  execute; transcript persistence/billing finalization is explicitly a fake
  `CallLogger.complete_call` boundary. This does not test billing, ACW or actual
  database commit/idempotency behavior. Real drivers/connections, SQLite
  connections and server startup remain denied. ORM declarations use real
  SQLAlchemy, not a database connection.
- The voice package is bootstrapped as a test-only namespace to avoid its eager
  initializer. The component launcher still denies CallHandler import; the
  separate lifecycle launcher narrowly admits that real module, not the API
  server/database. Engine, agent, mapper, executor and coordinator use real files.
- OpenAI's OS-header fingerprint uses a fixed test host string. That metadata
  probe otherwise executes `uname` on some hosts. The subprocess guard remains
  enabled, and the actual request builder and JSON serializer are not replaced.
- During the carrier SDK import only, IPv6 capability is declared absent.
  Otherwise urllib3 probes it by binding a loopback socket on IPv6-capable hosts.
  Socket binding remains forbidden; no guard denial is ignored.
- The synthetic Flux connection emits the required Connected event, then stays
  open until teardown. The carrier streams 20 ms media packets, so a packet
  correctly dropped while greeting-mute release propagates is not mistaken for
  a broken input path. Provider transcription and PCM remain synthetic.
- Greeting disk/HTTP cache access is a forced cache miss. Its actual TTS fallback
  runs; cache-hit/prewarm-bundle and recording paths are not covered.
- Startup gates are at the greeting-cache/provider socket boundaries. The
  cancellation tests then complete the fake provider handshake; they do not
  establish bounded recovery from a permanently stalled external provider.
  Held speech uses synthetic PCM with its SpeechMetadata withheld until
  explicit completion or interruption. No production sleep/retry is added.
- Genuine retained callback functions are invoked as delayed work; their bodies
  are not copied into test helpers. Any wrongly started tasks are awaited so a
  regression cannot escape behind fixture teardown.

The Python guard is not an OS sandbox. CI additionally runs with `--network none`,
`--read-only`, clean environment variables, read-only test mounts and a temporary
filesystem. Unexpected guard denials fail the checkpoint even if the application
catches them. Guard self-tests deliberately exercise their own denial paths.

## Minimal candidate application changes

Both custom Deepgram connection-error paths referenced `ErrorFrame` without
importing it. Injected provider failures reproduced a NameError in each branch.
The isolated candidate adds that import; tests assert the expected error frame
and asynchronous error notification. No dependency or production runtime is
changed by this fix.

The whole-call regression also reproduced a pending idle-processor input task
after both ordinary work and pipeline cancellation. Pinned Pipecat's idle
cleanup cancels its timer but omits base frame-processor cleanup. A small
application-owned subclass calls both cleanups, leaving the verified vendor
files unchanged. Tests require actual task disposal, not just a finished-worker
flag or stopped event callbacks. The fix remains candidate-only.

The race tests reproduced late callbacks raising KeyError, recreating deleted
interruption/greeting-task state and starting fresh status I/O. The candidate
binds those five callbacks to their capture generation and closes their scope
before final cleanup awaits. Current-call callbacks still capture normal turns,
greetings and caller speech; delayed old callbacks cannot update a successor.

Pre-start cancellation also exposed native RTVI receiving zero-valued bootstrap
metrics before its StartFrame. The candidate disables only initial empty metric
injection. Real service metrics and usage stay enabled, with nonzero synthetic
LLM token counts and TTS character counts checked at the actual save handoff.
No vendor source or dependency is modified for either fix.

## What a pass does not establish

- No full FastAPI server boot, customer database, Azure staging environment,
  phone route, paid speech/model request or acoustic quality check is exercised.
- The continuous synthetic worker path above does not prove real provider,
  carrier playback or production behavior. Authenticated webhook delivery is
  not exercised by calling the handler's cancellation method.
- The interruption slice covers the stated synthetic turn and callbacks, not
  exhaustive timing races or real acoustics. Direct-prompt/tool transcript
  reconciliation, permanent provider stalls, exceptional termination, complete
  transfer handling, carrier recovery, concurrent reconnects and every
  assistant/provider configuration still need separate checks.
- API/MCP requests, booking writes, SMS and payment links are not executed.
- No saved-definition compiler, deterministic native flow controller, UI
  controls, node-order fix or migration is activated.
- Existing deprecation warnings are visible. Their presence is not approval to
  upgrade the SDK or replace speech-context classes in this checkpoint.

Finish the outstanding application/lifecycle checks and report their evidence
before advancing to node contracts or a native adapter. No production merge,
Azure deployment or paid rehearsal is authorized by this checkpoint.
