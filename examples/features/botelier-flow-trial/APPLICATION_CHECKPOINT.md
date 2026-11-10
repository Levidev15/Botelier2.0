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

There are 30 component cases, 41 lifecycle cases and 28 selected legacy
extractor/mapper regression cases below. The lifecycle command runs the latter
two groups together; it must not be described as 69 whole-call cases. Results
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
  earlier race slice completes the fake handshake after hangup; the separate
  provider-failure slice below never releases its stalled I/O before asserting
  disposal. A queued cancellation is not treated as completed disposal.
  Held speech uses synthetic PCM with its SpeechMetadata withheld until
  explicit completion or interruption, without application sleeps or speech retries.
- Genuine retained callback functions are invoked as delayed work; their bodies
  are not copied into test helpers. Any wrongly started tasks are awaited so a
  regression cannot escape behind fixture teardown.
- Failure tests observe actual worker error events and retain every ERROR log.
  They accept only an exact multiset of patterns for deliberately injected
  errors; any additional error still fails. Emergency fixture teardown cancels
  surviving tasks before restoring I/O patches, but never counts as evidence
  that the application disposed of them.

The Python guard is not an OS sandbox. CI additionally runs with `--network none`,
`--read-only`, clean environment variables, read-only test mounts and a temporary
filesystem. Unexpected guard denials fail the checkpoint even if the application
catches them. Guard self-tests deliberately exercise their own denial paths.

## Offline provider-failure slice

Sixteen additional cases use the same actual coordinator and worker:
- Initial STT/TTS connection refusal must reach the real worker error event.
  Transient refusal recovers through the actual service and produces one reply.
- Repeated initial STT failure gets one startup retry, then a fatal error that
  actually ends the AI worker without a caller hangup. This is tested with
  interruptions enabled and disabled; it is not a retry loop or mid-call
  reconnect-policy change.
- A rejected model request and a timed-out SSE stream cannot invent a reply;
  a new finalized user turn can recover. Only the successful model usage reaches
  the save handoff.
- A provider-rejected synthesis reports its real error and disposes of the
  unfinished speech context on hangup. This does not claim automatic TTS
  failover or certify that generated transcript text was audible.
- Hangup disposes of seven deliberately stalled I/O paths: STT connect,
  STT server confirmation, TTS connect, model response headers, model stream,
  speech metadata and independent prompt-cache warmup. No gate is released to
  manufacture success. Tests allow the native 20-second cancellation-drain
  deadline plus bounded scheduling margin; this is not a low-latency guarantee.
- Optional cache warmup failure cannot abort normal conversation. The warmer
  closes its actual SDK client, is cancelled by its owning call at shutdown,
  and has a five-second whole-operation deadline. A stalled warmer independently
  times out while the conversation worker remains active.

Checks require the known error events, exactly one save handoff, closed opened
provider sockets and warmup clients, no surviving call-created tasks, closed
sessions/event queues, removed call state and zero unexpected guard denials.
All provider/carrier audio and records remain synthetic.

## Offline transcript slice

Eleven new cases run through the real coordinator and native worker:
- Repeated caller and assistant utterances retain their individual chronological
  positions. The opening greeting has its own anchor even when a later model
  reply intentionally repeats its words.
- Interrupting one reply marks that occurrence, not a later completed reply
  with identical words or the same long opening sentence.
- The real legacy flow trigger speaks its initial messages with and without a
  model preface. Direct prompts precede the next caller answer, occur once and
  suppress an unnecessary post-function model completion.
- A preface plus a tool call, result and model narration retain their order.
  Model transport fixtures cover separate deltas, one delta containing both
  text and a tool call, and usage attached to that mixed delta. Usage is counted
  once. Raw tool-result data reaches the model but not speech or conversation
  transcript text.
- Hangup after a mixed delta while its HTTP stream is blocked cancels and closes
  the real SDK/HTTP reader. The fault gate remains unset, no unfinished tool is
  executed, and no completed result is fabricated.

The synthetic tool catalogue is supplied at the factory configuration boundary,
without replacing the factory, native dispatcher or timestamp wrapper. Direct
flow speech executes actual `FunctionMapper` and ephemeral `FlowExecutor`
handlers. Lookup business data and persistence are fakes. This does not certify
tool-catalogue authorization/loading, durable flow snapshots or API/MCP calls.

The same guarded image run also exercises 28 selected existing regression cases
from the interrupted-transcript and flow-speech-ordering tests. Those tests use
assembled contexts and/or fake business results: they are extractor/mapper
regressions, not additional actual-worker replays. Their asynchronous bare
processor tests are not included; live interruption is covered by the worker
cases instead. No legacy assertion is weakened.
Fixture preparation runs before collection but only after environment/source
validation and installation of the existing I/O/import guards. A separate
stdlib safety regression proves database and server imports are still denied
during that preparation; collection order does not justify allowing either.

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

The provider-failure slice reproduced a Flux startup failure that returned
nonfatally with no socket: native `run_stt` then silently discarded every packet.
An application-owned Flux subclass now makes one initial retry and reports a
fatal failure if no socket exists after it. Both word-gated and noninterruptible
paths use the same startup policy; native mid-call reconnect behavior is unchanged.

The separate prompt-cache task also outlived its call, and its client stayed open
even after an ordinary failed warmup. It is now call-owned, cancelled and awaited
before event-queue teardown, and uses an async client context within a five-second
operation deadline. Idle/terminal callback shutdown remains before the first
cleanup await. Warmup failure stays optional and never substitutes for a real
conversation turn.

Transcript checks reproduced text-key timestamp reuse, a call-wide interrupted
text set labelling later replies, opening-greeting collisions, and response-end
timestamps moving a preface behind the tool it introduced. The candidate consumes
capture occurrences, records timed interruption events, separately anchors only
the committed opening greeting and timestamps model responses at their start.
All added state is call-owned, removed on cleanup and omitted from saved data.
Legacy extractor inputs without timed interruption events retain their fallback.

A valid mixed text/tool SSE delta also reproduced dropped speech in the pinned
OpenAI consumer's mutually exclusive branches. A small application-owned stream
adapter splits that delta into text followed by tool information. Native tool
dispatch, model requests and context ownership are retained, usage/finish
metadata is emitted once, and nested iterator/HTTP close propagates on cancel.
Vendor sources, the three reviewed overlays and dependencies are unchanged.

## What a pass does not establish

- No full FastAPI server boot, customer database, Azure staging environment,
  phone route, paid speech/model request or acoustic quality check is exercised.
- The continuous synthetic worker path above does not prove real provider,
  carrier playback or production behavior. Authenticated webhook delivery is
  not exercised by calling the handler's cancellation method.
- The interruption/transcript slices cover the stated synthetic turns and
  callbacks, not exhaustive timing races, every coalesced/word-stamped text
  shape or real acoustics. Other exceptional termination, complete transfer handling,
  carrier recovery, concurrent reconnects and every
  assistant/provider configuration still need separate checks.
- Stalled-provider checks above prove bounded disposal after hangup, not
  autonomous failover or a response deadline while the caller stays connected.
  The independent warmup deadline is the explicitly tested exception. Hostile
  I/O that suppresses task cancellation, real provider latency and every error/
  retry/status-code combination are not certified.
- API/MCP requests, booking writes, SMS and payment links are not executed.
- No saved-definition compiler, deterministic native flow controller, UI
  controls, node-order fix or migration is activated.
- Existing deprecation warnings are visible. Their presence is not approval to
  upgrade the SDK or replace speech-context classes in this checkpoint.

Finish the outstanding application/lifecycle checks and report their evidence
before advancing to node contracts or a native adapter. No production merge,
Azure deployment or paid rehearsal is authorized by this checkpoint.
