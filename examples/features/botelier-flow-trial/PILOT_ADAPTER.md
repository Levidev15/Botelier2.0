# Inactive single-flow native adapter checkpoint

## What this builds

This is an explicitly attached offline proof, not a production engine switch.
It admits one graph in the existing saved format:

`INITIAL → COLLECT_SLOT → connected GET → API_RESPONSE → COLLECT_SLOT`

An API error or an explicitly empty result goes to a separate fallback
collection. Both final collections are pauses, not bookings, saved records,
transfers, payments or completed calls.

Native Pipecat Flows owns the waiting nodes and transitions. The existing
`ActionExecutor.execute_and_log` / `IntegrationClient` still owns connection
authorization, serialization, response mapping, retries and invocation logging.
The legacy flow executor is not attached alongside the pilot.

Only `pilot_io.PilotCall`, a test host around the real call coordinator and
factory, constructs the adapter. No default call handler, editor, assistant
flag, saved definition, package constraint, phone routing or deployment is
changed by this checkpoint.

## Admission and runtime boundaries

- Exactly six distinct saved nodes and the reviewed six-edge topology; reject
  cycles, missing/dangling/ambiguous branches and omitted/unsupported steps.
- Required declared text variables, safe native names and nonempty public
  prompts. Copy and freeze the definition, account/property/tool/version and
  call identity before runtime work.
- Connected GET only. No custom HTTP, mutations, credential/body/header or
  connection-constant overrides. Only the collected text variable may appear
  in the supported relative request template.
- Explicit response-variable paths override response mappings, using the
  existing integration extraction semantics. Mapped outputs cannot overwrite
  caller facts or reserved execution fields.
- Collection instructions become private node guidance. Nonempty private
  instructions on automatic API/presentation nodes fail admission.
- The presentation owns result speech. Conflicting API success/narration
  settings or a different outro question fail admission. An empty/equivalent
  outro results in the canonical next prompt exactly once.
- Validate arguments before any fact, wait announcement or request. Claim
  ownership before the first await, and check it again after I/O. Repeated,
  competing, spent and stale handlers cannot reissue the action.
- Preserve zero and false. Only an actual empty list means no results.
  Missing/malformed lists, missing/non-scalar template fields, unbounded output,
  HTTP failures and transport/total-read timeout use the explicit failure path.
- Keep original host policy and valid history; replace only the exact prior
  adapter-owned guidance object after native tool results have committed.
  The host's existing volatile local-time tail continues to refresh.
- Reuse the actual host's authorized/enabled MCP catalogue and isolated handler.
  Reserve every logical pilot collection name, including future/pause nodes,
  and the entire `pilot_collect_` visit namespace before adding native globals.
  Structured results and error status remain tool data.

The proof bounds caller text at 2,048 characters, a definition at 100,000
serialized characters, presented results at 50 items, mapped data at 50,000
serialized characters and one result utterance at 8,000 characters. Each
configured read is 1–30 seconds with 0–2 existing client retries; an additional
total deadline covers those attempts and logging. Expiry remains a failure
even when a broken transport returns success after swallowing cancellation.

## Native lifecycle findings addressed by the adapter

### Node entry cannot depend on audio finishing

The pinned framework's built-in `tts_say` pre-action waits for its
`ActionFinishedFrame` before committing the next node's tools/context. Holding
result audio exposed the previous collection node remaining active. The
adapter's custom native entry action issues one `TTSSpeakFrame` without that
wait, and native Flows updates its own node/tools normally. A synthetic caller
can interrupt result audio and supply the next collection without repeating
the read.

This guarantees issued text and tested control behavior, not that a real
caller heard every word. Audio contexts, carrier marks and teardown are
checked separately.

### Transport cancellation and native bookkeeping are different

In Pipecat 1.5.0 a priority `FunctionCallCancelFrame` can reach the assistant
before its earlier non-priority in-progress frame. The transport stops, but
the assistant can retain `IN_PROGRESS`. A narrowly scoped application-owned
control barrier reconciles the actual cancelled call IDs at the assistant
boundary after earlier control frames. It never mutates SDK internals,
rebroadcasts a duplicate cancellation to the user mute strategy, selects a
node or starts a second transition loop.

Tests cover interruption before/after in-progress bookkeeping, both a queued
native control frame and the preceding real processor's
`broadcast_interruption()`, cancelled transport reads and deliberately late
successful responses. Hangup must dispose all call-created tasks and sessions.

### Queued node updates must survive interruption

Native RESET message and tool updates are ordinary interruptible data frames
in this SDK. The manager can already report the new node while these updates
are still queued before their actual user-aggregator consumer. An interruption
can drop them, leaving old tools/guidance active. A cancellation-recovery
barrier is also useless if that barrier can itself be dropped.

A small call-scoped queue facade forwards lifecycle, events and frames to the
same real worker. Only the native RESET message/tool frames receive the SDK's
`UninterruptibleFrame` marker, as does the cancellation barrier. Native Flows
still chooses transitions and builds their contents. Speech, caller input and
model runs are deliberately not protected and remain interruptible.

Two forced-order regressions pause the real processor before the actual
consumer, queue these frames, and deliver the actual receiver interruption.
They require the next caller turn to work with the right tools/guidance, the
cancelled call to settle, no repeated read and no replayed result speech.
Both fail when the protections are removed; simple favorable-timing passes
are not used as evidence for this race.

### The existing tool-call mute policy is unchanged

The actual application mutes caller input during a function call. Therefore
the pending-read interruption checks deliberately enter at the native control
boundary **after** user mute; they do not prove that saying “stop” interrupts
an active API lookup. The separate result-audio interruption uses actual
synthetic STT after the action has completed. A change to the caller/tool
interruption policy is a separate design and verification decision.

### Re-entering a node uses the current visit's data

Native Flows caches a custom action handler on its first registration by type.
A new node config with the same action type does not replace that handler.
The previous per-node entry closure captured its original question and message
list: a later fresh config could speak the old question while RESET consumed
the new, empty list, losing host policy and history.

The adapter now uses one stable native entry handler. Each entry action carries
its own immutable collection spec, utterance and the exact task-message list
that the native context updater will consume. The handler reads that payload,
preserves existing host policy/history, and replaces only its own previous
guidance. Repeated visits do not grow the native action-handler registry.

Five offline regressions drive the public native host API after successful,
failed and empty reads, plus nine repeated visits with fresh or reused configs.
They check current private instructions, actual speech/tools, preserved policy
and committed user/assistant/tool history, no duplicate API request, retained
spent-node rejection and full cleanup. A test-only queue fence observes the
actual assistant consumer before issuing another visit: seeing the user
consumer's new tools alone does not prove the earlier tool frame has finished
at the later assistant consumer.

This fixes the entry mechanism only. These host-driven tests do not enable
caller corrections, graph backtracking, repeated actions, changed mute policy
or production attachment. The existing admission and accepted-node guards are
unchanged; a previously accepted query remains spent after re-entry.

### Visit revisions protect dispatch, reads and deferred entry

Node identity alone does not establish authority: the same logical node can be
entered more than once. Each actual entry now creates a fresh immutable,
call-owned execution revision and a unique native function name. The logical
saved node ID is preserved. Wire names stay within the provider's 64-character
limit even for a maximum-length saved ID; their UUID suffix is execution
metadata, not a secret or a caller fact.

This requires more than putting a new token in same-named function arguments.
The installed SDK both resolves queued handlers again at execution time and
retains the first auto-registered handler while its name stays advertised.
Reusing a name with a fresh closure could either reuse old authority or reject
all new answers. Distinct visit names avoid both cases. Normal native context
sync installs the new handler and removes obsolete auto-registered names;
there is no SDK registry patch, manual re-registration or growing action type.

Each collection handler also captures its immutable visit. It rejects an old
wrapper even when the same saved node is current and not yet accepted. An
owned read checks both its claim and visit after I/O before saving mapped
results. Its returned native node configuration carries the source visit
through the deferred tool-result callback. The stable entry pre-action checks
that source before altering guidance, tools, node state or issuing speech.
A superseded callback fails closed through the SDK's normal action/FlowError
path with the safe `pilot_stale_entry` category. The forced-order regression
retains and explicitly matches those native diagnostics; it does not suppress
errors or accept unrelated task failures.

MCP filtering and the adapter constructor both reserve the visit namespace,
including unknown/future identities. Cancellation bookkeeping recognizes
actual cancelled native names in that call-owned namespace as well as the
existing authorized globals. Caller muting, transport retry policy, action
authorization and MCP global transport/side-effect policy are unchanged.

The model-provider fixture selects actual advertised wire tools from its
serialized request; readable logical names are only test-script aliases.
Queued replies retain that request's original wire identity. Separate raw-name
tests bypass aliasing to prove stale, forged and bare logical names cannot
gain native or MCP action authority. This is synthetic provider data, not
runtime argument repair or proof that a real model follows instructions.

These protections do not implement editable answers, dependency invalidation,
new retries, general graph loops, durable revisions or an interruptible API/MCP
policy. The existing spent-node guard and forward-only admission remain in
place.

## Test coverage and evidence

- `test_pilot_contract.py`: exact admission/rejection and immutable scope.
- `test_pilot_pipeline.py`: actual coordinator/factory/worker, synthetic STT,
  actual model SDK serialization/dispatch, native manager, existing connected
  action, direct TTS, tool history, duplicate/stale calls, failure/deadline,
  cancellation, result-audio interruption and complete teardown.
- `test_pilot_mcp.py`: actual account/connection/enablement filtering, synthetic
  MCP protocol round trips after transition, structured/error results and
  disabled/current/future/spent collisions.
- `test_pilot_interruption_order.py`: the two forced native queue-reset windows,
  actual consumer readiness, cancellation and the next caller turn.
- `test_pilot_reentry.py`: fresh per-visit data, preserved policy/history,
  bounded registration, actual consumer settlement and unchanged spent guards.
- `test_pilot_revisions.py`: retained and actually queued calls across same-ID
  visits, superseded reads, deferred native entry, disposed-call identities,
  forged names, native/MCP namespace protection, maximum-length saved IDs and
  actual-inference stale-handler pruning with fresh or reused configs.
- The actual model request keeps `parallel_tool_calls=False`. The adversarial
  duplicate-call test emits separately indexed call deltas in one response,
  a layout the pinned parser supports. This checkpoint does not certify the
  SDK's handling of several tool calls inside one individual delta.
- The mandatory candidate CI step `native_pilot_adapter` runs all nine files
  with disabled container networking, read-only root and cleared environment
  before exact-image export. It retains `native-pilot-adapter.log` and
  `native-pilot-checkpoint.json`. No prior regression step was removed.

Run from the isolated worktree:

```bash
TRIAL="$PWD/examples/features/botelier-flow-trial"
ASSETS="$PWD/generated-artifacts/voice-pilot/offline-assets/nltk_data"
env -i PATH="$PATH" HOME=/tmp/botelier-native-flow-trial \
  PYTHONPATH=/home/runner/workspace/.pythonlibs/lib/python3.11/site-packages \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  DO_NOT_TRACK=1 LOGURU_LEVEL=ERROR NLTK_DATA="$ASSETS" \
  python -B "$TRIAL/lifecycle_guard.py" \
  --backend-root "$PWD/botelier/backend" \
  --package-root /home/runner/workspace/.pythonlibs/lib/python3.11/site-packages/pipecat \
  --tests "$TRIAL/test_pilot_contract.py" "$TRIAL/test_pilot_pipeline.py" \
  "$TRIAL/test_pilot_mcp.py" "$TRIAL/test_pilot_interruption_order.py" \
  "$TRIAL/test_pilot_reentry.py" "$TRIAL/test_pilot_revisions.py" \
  "$TRIAL/test_pilot_late_speech.py" "$TRIAL/test_pilot_replacement.py" \
  "$TRIAL/test_pilot_replacement_edges.py" "$TRIAL/test_pilot_handoff_input.py" \
  "$TRIAL/test_pilot_input_preservation.py"
python -B -m unittest discover -s tests/voice_release -v
git diff --check
```

Run guards sequentially because their temporary report directory is shared.
Use the verified public tokenizer cache. If its old temporary location is
lost, prepare only the exact checksum-pinned public data already declared by
`Dockerfile.flow-pilot`, outside the guarded run, under ignored workspace
storage. Asset preparation is not a test pass. Do not permit library/runtime
auto-downloads, install packages, expose credentials or weaken guards to clear
a failure. Normal test runs require zero unexpected denials.

The complete fresh-image run, exact commit, actual test counts and guard
reports must be inspected before this checkpoint is reported as passed.
Local results alone do not certify the image. SDK deprecation warnings remain
visible, and injected failure cases are not a claim of warning-free behavior.

The first local verification on 2026-11-11 had **97 adapter tests passed**, with
`APPLICATION_GUARD_BLOCKED_ATTEMPTS=0`; **70 release-policy tests passed**;
`git diff --check` passed. The adapter test split is 50 admission, 41 actual
pipeline and 6 MCP cases. Expected SDK deprecations produced 150 warnings.
The two subsequently demonstrated native queue-reset cases are mandatory
additional regressions; that earlier pass and its candidate image do not
certify the strengthened implementation.

Final strengthened local verification on 2026-11-11: **99 tests passed**
(50 admission, 41 pipeline, 6 MCP, 2 forced-order pipeline regressions),
**zero unexpected guard denials**, 156 visible SDK deprecation warnings;
**70 release-policy tests passed**, and `git diff --check` passed. A new
exact-commit fresh-image run is still required before checkpoint acceptance.

One earlier complete run timed out before pilot initialization while waiting
for greeting completion; a diagnostic rerun did not reproduce a runtime fault.
The test host now treats cold worker-start and playback/DB greeting completion
as separate four-second readiness phases, matching the existing lifecycle
fixture, and reports their actual states on failure. It still waits for the
real completed greeting before starting the adapter. No assertion, guard,
provider/script budget or application timeout was removed.

Node-entry safety local verification: **104 adapter cases passed** in 82.02
seconds, including the five new entry regressions, with **zero unexpected
guard denials** and 171 visible SDK deprecation warnings. **70 release-policy
checks passed**. The new regressions first reproduced lost policy and stale
questions against the unchanged adapter. The final tests wait for the real
assistant consumer as well as checking actual context, tools and TTS output.
A fresh exact-commit image run is required separately; these local results do
not authorize production attachment or the next correction-handling stage.

Visit-revision safety local verification: **120 adapter cases passed** in
81.21 seconds, including 15 new revision cases and one additional enabled MCP
namespace-collision case. There were **zero unexpected guard denials** and
228 visible SDK deprecation warnings. **70 release-policy checks passed**.
Before runtime changes the new checks reproduced ten ownership/control
failures. A same-name argument-token attempt then exposed the SDK's
first-handler retention; the final implementation uses distinct visit tool
identities instead. The final checks prove a fresh answer can still execute
after stale work is rejected, not merely that all handlers become unusable.
These are local results; exact-commit container acceptance is a separate gate.

## Earlier blocking finding: a new visit does not cancel old plain speech

The subsequent offline speech-authority check reproduced a separate gap:
host-driven node changes do not cancel an existing model stream or revoke a
model text already queued at TTS. The old text can create a new provider
`Speak` request after the new visit was established, before the replacement
question. This is not a request to retract audio already issued while valid.
The collection/read/transition visit fences remain useful, but do not protect
this non-tool speech path.

`test_pilot_late_speech.py` and its test-only `pilot_speech_io.py` use the real
coordinator, streaming model SDK, native host API, TTS receiver and cleanup.
They hold only external model bytes or the actual TTS receiver before
delegating to it. Positive controls keep normal speech, subsequent current
answers and hangup disposal observable. No runtime behavior is mocked into a
pass.

The pre-fix focused run had **three failing desired-behavior checks and seven
passing controls**, with **31 visible SDK warnings** and zero unexpected guard denials.
The failing cases are a same-node new visit before first model text, a
different node after an already-issued valid prefix, and old model text
waiting at TTS. All three matched controls passed when the test explicitly
requested and acknowledged the existing native `InterruptionFrame` before
changing the visit. The adapter did not yet request it at that point.
The failures were not skipped, marked expected, or converted into assertions
that accept stale speech.

That was **local characterization**, not new exact-container acceptance.
No runtime, dependency, caller-mute, graph, editor or CI workflow change
accompanied that investigation. The earlier checked image omitted these tests.
Caller corrections remain disabled. The guarded host-entry checkpoint below
addresses this demonstrated output gap; it does not authorize correction or
backtracking features. Do not unconditionally interrupt unknown side-effecting
globals or replay their operations.

## Guarded host replacement using the existing native cancellation path

`NativePilotAdapter.replace_node(slot, utterance)` is the application-owned
entry for an explicitly authorized host replacement. It is **not** registered
as an LLM tool, API route, caller-edit feature or production runtime choice.
Raw `manager.set_node_from_config` remains a framework primitive, not the safe
application replacement contract. Existing raw-manager revision probes still
deliberately bypass this entry to verify independent defense in depth.

The host can replace only an already admitted collection specification, with
the same binding and saved prompt; only its private instructions may vary.
The explicit utterance is bounded to a nonblank string. Both instruction and
utterance limits are 8,000 characters. Admission/start/close failures occur
before any cancellation or manager state change. Spent-node facts and the
compiled graph are not reset or expanded.

The call-owned guard in `pilot_replacement.py`:

1. Refuses concurrent replacement, active reads, active global handlers,
   native queued function calls and accepted deferred native entry **before**
   requesting interruption or touching native pending state.
2. Observes the SDK's synchronous function-start frame hook, rather than a
   later asynchronous notification or private runner registry. Native final
   result/cancellation consumers release that work's lease. Wrapped globals
   retain their native signatures/options and original business handler.
3. Closes last-mile handler admission during handoff, so a retained/racing
   native collection or MCP wrapper cannot start new business I/O. The
   original clients still own authorization, sessions, retries and results.
4. Requests a normal native `InterruptionFrame`, acknowledges that exact frame
   at the worker's downstream boundary, and drains ordered control work before
   entering a replacement through the **same** native manager.
5. Defers the new direct-speech prompt until both real message/tool consumers
   acknowledge the new native context. The host entry does **not** wait for
   that prompt's audio to finish. Native automatic result transitions keep
   their existing behavior and caller mute strategies remain unchanged.
6. Bounds the whole handoff to five seconds. Timeout or host cancellation
   fails closed rather than reopening tool admission while an unacknowledged
   interruption remains in flight. Native terminal frames invalidate pending
   acknowledgment early; late acknowledgments cannot publish a new prompt
   after hangup. A failed handoff is not a successful rollback or retry.

Native manager setup replaces the worker's initial reached-frame filter set.
The guard therefore installs its acknowledgment filters **after** that setup.
The first implementation's real downstream trace caught an otherwise silent
lost-ack timeout; no SDK source or timeout extension was used to fix it.

The speech tests now drive the guarded application entry. Their forbidden
obsolete-speech assertions remain, and their observation boundary was
**strengthened** to include output issued while the replacement itself awaits
acknowledgment. The separate manual-native-interruption controls remain as
double-interruption regressions. Nothing is skipped or marked expected.

Local final verification passed **155 adapter cases**, including all 120 prior
regressions and 35 new speech/replacement cases, with 340 visible SDK warnings
and **zero unexpected guard denials**. All **70 release-policy checks passed**.
The new cases cover active/queued API and MCP work, pending native entry,
retained/racing wrappers, real hangup, overlapping replacement, failed or
cancelled acknowledgment, invalid configuration, before-start/after-close
entry, new-node collection during held prompt audio, and bounded registrations.
Controlled removal of the preflight and of native cancellation each made the
relevant real-pipeline regression fail; the original source was restored
byte-for-byte and the targeted cases rechecked.

All three new suites are mandatory in the existing network-disabled,
read-only fresh-image adapter gate before export. The policy test also rejects
a workflow that omits them. Local results are not fresh-image certification:
inspect the complete exact-commit candidate workflow before claiming that gate.

This establishes a controlled host-entry boundary, **not** arbitrary
simultaneous caller-turn/model-input handoff, correction semantics, mutating
business-operation cancellation, a provider/acoustic rehearsal or Azure
readiness. Those remain separate gates before any caller-edit activation.

## Caller-input gap reproduced before input-guard implementation

The separately approved **test-only** caller-input checkpoint adds
`handoff_input_io.py` and `test_pilot_handoff_input.py`. It runs actual Flux
start/end-of-turn messages, the real call coordinator, native model parsing
and function dispatch, the existing clients, actual TTS consumers and teardown.
Only synthetic external bytes and specific real receiver timings are held.
Model request observations come from the actual serialized HTTP request;
function decisions are captured from actual native result frames.

On the prior guarded candidate, **four desired-behavior cases failed and
four controls passed**, with 28 visible SDK warnings, 20.09 seconds and zero
unexpected guard denials:

| Timing window | Observed behavior |
| --- | --- |
| New caller turn after model cancellation but before its final TTS acknowledgment | A new model request carries the old private guidance/tool. Holding that new stream triggers the real five-second handoff timeout and leaves admission failed closed. The stream is still open at that failure. |
| Same window, with a fast model response | Old-context speech is issued while replacement is pending, before the replacement question. This is not a claim that speech escaped after the new visit committed. |
| New guidance/tools installed, final readiness acknowledgment still held | A genuine current-node API answer is rejected as `busy_or_stale`; no fact or API request is committed. |
| Same final-readiness window, current MCP answer | The original enabled native MCP wrapper rejects the valid answer; no MCP request is sent. |

Positive controls verify the same API and MCP inputs succeed **after** the
handoff, with current private guidance/current tool identity and exactly one
request; a slow current-context plain reply can finish after acknowledgment;
and real caller hangup disposes new inference plus pending replacement without
publishing the replacement prompt. Every scenario reaches actual coordinator/
worker teardown and strict disposal assertions before its final contract
assertions. Internal private instructions/results are not routed to speech.

The first two tests allow either deferred input or cancellation of obsolete
inference. They do not demand that a future correct input gate admit the model
early. The positive slow-current-reply control releases its external stream
after **handoff completion**, not after audible prompt completion: the prompt
traverses the same LLM processor and cannot be used to release a deliberately
blocked current inference.

### Root cause

The prior replacement guard coordinated existing output and native business
work, but not admission of new model-context frames. A caller turn could start a new
old-context completion after the one interruption has passed the LLM. A slow
completion then blocks an ordered readiness frame; a fast completion can
issue speech before replacement finishes. Conversely, the guard's intentionally
closed handler admission rejects valid new-node input during final readiness.
Removing that business guard is not a safe fix.

Before caller corrections are enabled, coordinate **model admission** with
the call-owned handoff: preserve incoming caller input, keep native control/
context/tool updates flowing, and release the preserved input once under
confirmed current-node authority. Retain bounded lifetime, hangup invalidation,
the configured mute policy and the existing API/MCP side-effect ownership.
Do not retry/replay business actions to compensate for lost input.

The pinned framework has `GatedLLMContextAggregator` and `GatedAggregator`
primitives, but neither is a proven drop-in solution. The former retains the
latest context per notification rather than exposing a persistent open/close
policy; the latter buffers non-system frames, including controls if used
naively. Lifecycle, queued-context ordering, multiple turns, close/timeout
disposal and ordinary-input behavior need actual integration tests.

Those characterization checks were **not included in the earlier green
image run**. That investigation changed no runtime or workflow and made no
new image-acceptance claim. The implementation below adds them to the mandatory
exact-image gate; a historical image pass cannot certify the new code.

## Call-owned input preservation during guarded replacement

`pilot_input.py` now closes model-context admission **before** the guard's
initial native interruption. It reopens only after the final real readiness
acknowledgment and the entry question have been queued. The same native worker
then receives at most one fresh context notification for retained input.
Native Flows remains the sole node-transition owner.

The application-owned OpenAI service has an optional admission hook; ordinary
non-pilot calls have no policy installed and retain native processing. An
explicit pilot using an unsupported LLM fails admission rather than silently
running without this protection. No SDK source or dependencies changed.

The synchronous native user-aggregator frame hook retains new caller message
objects before a queued RESET can erase them. Missing messages are restored
through the public context API under the confirmed current instructions/tools.
Identity, not text equality, prevents duplication: two genuinely repeated
caller utterances remain two messages. They remain `user` data, never private
instructions. Whole old contexts, tool calls and API/MCP actions are not
replayed.

Context notifications already waiting in the real LLM queue are accounted for
before cancellation can drop them. Deferred notifications carry call-local
frame metadata so a late copy cannot start a second completion after release.
Native interruption, message/tool updates, readiness and terminal frames
continue normally; the guard never pauses the entire LLM processor or changes
the caller's configured mute strategy.

The existing five-second handoff deadline is unchanged. Additional temporary
retention is limited to **32 new user messages and 32,768 UTF-8 bytes**. An
over-budget or unsupported input fails the handoff closed rather than silently
dropping/truncating caller data. Timeout, request cancellation and actual call
termination discard retained references and do not release late inference.
Unconsumed pilot context notifications are also bounded at 32; native
interruption clears their tracked backlog. Nothing in this buffer is logged
or persisted.

The two input suites cover the original slow/fast old-context race, valid
current API/MCP answers before/after readiness, repeated utterances, input
between snapshot and RESET, queued-context cancellation, timeout/cancellation,
hangup, inclusive limits, overflow, malformed text/foreign contexts, late
notification redelivery and exclusive admission ownership. Most cases use actual Flux input.
Queue-specific and count-budget cases use the real native aggregator's public
context API to isolate queue/budget behavior without extending the five-second
deadline. The count case does not claim 33 acoustic turns fit inside that
deadline.

Both input suites are mandatory alongside the existing nine adapter suites
in the network-disabled, read-only exact-image workflow before image export.
Local test results and that exact-commit workflow must be reported separately.
The final local run on 2026-11-13 passed **178 adapter tests** (23 input checks
and 155 prior regressions), with 410 visible SDK deprecation warnings and zero
unexpected guard denials. All **70 release-policy tests** also passed; the
policy rejects omission of either input suite from the image gate.

This implements only the approved input-admission checkpoint; it does not
activate caller corrections, expand admitted graphs or certify production
readiness. Inspect the exact-commit build result before claiming image acceptance.

## Still outside this checkpoint

No real model instruction-following or recognition/acoustic evaluation,
production server boot, Azure staging readiness, live migration, full backend
suite, general graph support, durable cross-worker native sessions, business
writes, custom HTTP, confirmation/correction/selection controls, new editor UX,
SMS, simulator parity, payment links, payments or paid calls are certified.
Main, Azure, the registry, routing and production calls remain untouched.
