# Single-flow native adapter: offline checkpoint design

## Goal and status

Implement the approved next proof: one synthetic definition in Botelier's
existing saved graph format runs through native Pipecat Flows, performs one
existing connected API lookup, presents its result once, and asks the next
question without an extra caller turn.

The user approved this detailed contract on 2026-11-11 for isolated
implementation. It refines the existing Azure Voice Flow Pilot; it does not
authorize the rest of that pilot or a production migration.

## Unchanged safety boundary

- Work only on `candidate/azure-flow-image-checks` in the existing isolated
  worktree. Keep the production runner, editor and saved definitions unchanged.
- Keep Pipecat 1.5.0, the approved candidate-only MCP 1.26.0 constraint and the
  three declared Flux overlays unchanged.
- No main merge, Azure deployment, registry publication, phone-routing change,
  local package installation or running-workflow restart.
- No real model, STT/TTS, carrier, business API/MCP request, customer database,
  paid call, SMS, payment link or payment.
- Use existing strict offline fixtures and the credential-free fresh-image
  gate. Keep failed checks visible and report before another checkpoint.

## Approach and alternatives

**Recommended: native conversational nodes with a controlled action handler.**
Use actual `FlowManager` and `FlowsFunctionSchema`. A validated collection
handler performs the saved automatic API/presentation segment through the
existing action boundary, then returns the next native conversational node.
This is the native dynamic-handler pattern, not a second general-purpose
graph executor.

Two alternatives were considered:

1. Make every automatic saved node require another LLM function call. This
   adds model turns to work already determined by the graph and reintroduces
   unnecessary opportunities to wait or narrate instead of acting.
2. Keep the legacy executor advancing while native Flows also advances.
   This creates two owners for one conversation and defeats the pilot.

The existing older Flows-named wrapper is not evidence of native integration.
Do not activate it, patch the SDK, subclass a replacement execution loop, or
implement a second controller to make this proof pass.

## Exact first graph subset

The supported synthetic graph is:

`INITIAL → COLLECT_SLOT → API_REQUEST → API_RESPONSE → COLLECT_SLOT`

The API error edge and response no-results edge lead to one fallback
`COLLECT_SLOT`. The last two collection nodes are explicit pause boundaries,
not proof of completed selection, booking, saving, ending or transferring.

Native waiting nodes retain their saved collection-node IDs. The API request
and response retain their saved IDs as named action/presentation phases in
results and diagnostics; they are not represented as extra model turns.
This is deliberately not a claim of one native waiting node per saved node.

Preflight rejects, before inference or action:

- Duplicate/missing IDs, dangling edges, cycles, ambiguous branch handles,
  unsupported node types, extra reachable steps or silently omitted nodes.
- Nonempty initial greetings or initial wait-for-response behavior in this
  first subset; the existing host greeting remains separately owned.
- Unsupported slot types/validation, missing variable declarations, missing
  prompts, or tool names that cannot be represented safely.
- Custom HTTP actions, mutations, secret/body/header/connection-constant
  overrides and unsupported request-template features. The first action is a
  connected **GET** using existing account/property authorization.
- Nonempty private instructions on automatic API/presentation nodes. This
  first proof cannot pretend an instruction is enforced where no model turn
  occurs. Collection-node instructions are supported as private guidance.
- Conflicting speech configuration that cannot provide one unambiguous next
  question. A presentation outro may be empty or match the next prompt after
  whitespace folding and case-insensitive comparison; it must not silently
  replace a different next question.

Other definitions still use the existing legacy path. There is no activation
flag, production call-site change or mid-call fallback in this checkpoint.

## Node and data contracts

| Stage | Input | Output and control |
| --- | --- | --- |
| Collection | Complete synthetic STT turn, native tool call, current node guidance | Validate required nonempty text and reject wrong types, unknown arguments and stale ownership before accepting facts |
| API action | Immutable saved GET configuration, validated facts, frozen account/property/definition identity | Existing `ActionExecutor.execute_and_log` and `IntegrationClient`; the model cannot replace connection, method, path or scope |
| Result | Actual action outcome and mapped variables | Explicit success, empty-results or failure; missing/malformed results are not silently treated as empty availability |
| Presentation | Existing response template and supported mapped scalar fields | Designer-owned caller text only; preserve zero/false; never fall back to speaking raw dictionaries, errors or private guidance |
| Next collection | Selected branch, validated facts and fresh private guidance | One native transition and one issued next question, without requiring another caller utterance |

The adapter must retain definition/version identity for the call and copy the
input configuration so later mutation cannot change an active proof. API
response mappings use the existing shared extraction semantics. Mapped outputs
cannot overwrite caller facts or reserved execution state.

Only the connected GET subset is certified here. Mutating requests are
rejected rather than assigned a misleading exactly-once or uncertain-write
guarantee. Existing retry behavior remains owned by the integration client.

## Ordering, repetition and cancellation

- Native Flows owns conversational transitions; the legacy `FlowExecutor`
  must not be active in the same pilot call.
- Claim the action before awaiting I/O. A competing or repeated handler cannot
  issue a second request, repeat wait speech or apply another transition.
- Check active node and invocation ownership again after I/O, before accepting
  mapped facts or returning a transition.
- A stale/invalid invocation returns an explicit rejected result, with no API
  request, direct speech or new transition. A native follow-up model turn is
  not evidence of another accepted action.
- Cancel an owned pending read on interruption/hangup where the native worker
  permits it, and close owned work on teardown. A cancelled/late result cannot
  speak, advance or overwrite a newer state.
- These are single-call guarantees. No session snapshot format, process-restart
  recovery policy or cross-worker business-action ledger changes are included.

## Context and speech ownership

Keep baseline assistant instructions and valid user/assistant/tool history.
Replace only adapter-owned prior node guidance; do not leave conflicting
private instructions accumulated by the framework's default append policy.
Do not snapshot an in-progress tool placeholder as though it were a final
result. Upstream content remains data rather than developer/system guidance.

The adapter owns the direct wait announcement and the result/next-question
utterance. Native node entry must not additionally run the model to repeat
them. An outro matching the next prompt is included only once.

`respond_immediately=False` alone is not a spoken prompt. Native `tts_say`
queues speech but does not prove playback. Tests must observe real outgoing
TTS text and synthetic audio/mark cleanup separately; no acoustic or carrier
delivery claim is allowed.

## Existing MCP tools

Reuse the actual coordinator's account/connection/enablement-filtered tool
catalogue and existing isolated MCP invocation handler, with a narrow native
handler-format bridge if needed. Do not introduce another credential or
transport implementation.

Reserve all pilot native function names before merging globals, including
future nodes. Enabled non-colliding MCP tools remain available across the
transition and can return structured/error data through the model tool
channel. Disabled tools and colliding names cannot acquire a dispatch path.

The proof uses only synthetic lookup RPCs. Assistant-level MCP availability
does not establish per-node authorization for future side-effecting tools.
SMS/simulator MCP parity and mutating MCP operations remain outside this slice.

## Test-first implementation and acceptance

Write failing consumer-visible tests before adapter behavior. Keep native
framework dispatch, actual application pipeline/coordinator/worker, existing
action execution, serialization, MCP protocol client and TTS active. Replace
only enumerated external transports and storage, as in the prior checkpoint.

Required cases:

1. Saved graph admission/rejection, frozen identity and unsupported-instruction
   diagnostics before any action or model request.
2. Valid collection through one connected lookup to one presentation and the
   next prompt, with current tools and private context.
3. Missing/wrong-type/extra arguments, duplicate concurrent calls and stale
   calls; zero extra side effects and no repeated direct speech.
4. Zero/false mapping, empty arrays, malformed/missing results, HTTP errors and
   timeout; explicit correct branch and truthful speech.
5. Cancellation while lookup is pending, teardown, and late completion; no
   surviving owned work, late speech, fact mutation or transition.
6. Private-guidance replacement without broken tool history, and no raw
   payload/private instruction in direct TTS.
7. Actual filtered MCP availability and invocation after a native transition,
   structured/error result preservation and current/future native collisions.
8. No active legacy flow executor, no new production activation path, and the
   existing candidate workflow requires this gate before image export.

Run focused checks as components change, then one complete local adapter suite
and the full fresh-image gate including the prior scoped regression suites.
Require zero unexpected guard denials and all mandatory steps to succeed.
Retain logs and report exact executed coverage and remaining limitations.

This checkpoint is not complete until that evidence is inspected and reported.
It is not production readiness, real-model instruction-following certification
or completion of the broader Azure Voice Flow Pilot.

## Verified basis

The design uses the actual installed Pipecat 1.5.0 `flows/manager.py`,
`flows/types.py` and `flows/actions.py`, not newer declarative-editor examples.
The existing native contract tests characterize argument forwarding, deferred
transitions, context policies and enqueued speech. The existing application
checkpoint supplies the actual coordinator/worker and strictly synthetic I/O
boundaries. Those prior checks are the baseline, not evidence that this adapter
has already been implemented or passed its new tests.
