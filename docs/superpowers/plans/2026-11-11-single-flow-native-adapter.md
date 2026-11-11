# Single-flow Native Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the approved read-only saved graph through native Pipecat Flows and the actual guarded voice pipeline, without activating it for production calls.

**Architecture:** A pure admission compiler freezes one six-node graph and its call identity. A separate adapter uses native dynamic handlers, the existing action executor, and the host's filtered MCP handlers. Native pre-actions replace only adapter-owned guidance after committed tool results and issue the next prompt without another inference.

**Tech Stack:** Python 3.11, Pipecat 1.5.0 native Flows, existing FastAPI/SQLAlchemy action services, pytest, strict offline provider/storage fixtures, credential-free candidate CI.

**Spec:** `docs/superpowers/specs/2026-11-11-single-flow-native-adapter-design.md`

## Global Constraints

- Work only on `candidate/azure-flow-image-checks` in the existing isolated worktree. Keep the production runner, editor and saved definitions unchanged.
- Keep Pipecat 1.5.0, the approved candidate-only MCP 1.26.0 constraint and the three declared Flux overlays unchanged.
- No main merge, Azure deployment, registry publication, phone-routing change, local package installation or running-workflow restart.
- No real model, STT/TTS, carrier, business API/MCP request, customer database, paid call, SMS, payment link or payment.
- Use existing strict offline fixtures and the credential-free fresh-image gate. Keep failed checks visible and report before another checkpoint.
- No legacy executor, production activation flag, editor changes, session migration or business-write guarantee in this slice.
- Unsupported configuration fails admission; automatic API/presentation private instructions cannot be silently ignored.

## File boundaries

- `botelier/backend/botelier/voice/flows/pilot_contract.py`: pure validation, frozen call identity, immutable compiled collection/action/presentation contract.
- `botelier/backend/botelier/voice/flows/pilot_adapter.py`: native manager, validated handlers, owned cancellation, context replacement and direct speech.
- `botelier/backend/botelier/voice/flows/pilot_cancellation.py`: ordered reconciliation for actual native cancelled call IDs, without SDK or mute-policy changes.
- `botelier/backend/botelier/voice/flows/pilot_mcp.py`: schema/handler-format bridge for an already authorized host catalogue; no discovery, credentials or transport.
- `examples/features/botelier-flow-trial/pilot_io.py`: test-only host attachment and synthetic graph, reusing the real coordinator/worker and existing low-level fixture boundaries.
- `examples/features/botelier-flow-trial/test_pilot_contract.py`: graph admission, immutable identity/configuration, rendering and rejection diagnostics.
- `examples/features/botelier-flow-trial/test_pilot_pipeline.py`: actual STT/model/native action/TTS, context, error, duplicate/stale and cancellation checks.
- `examples/features/botelier-flow-trial/test_pilot_mcp.py`: actual filtered catalogue and synthetic MCP protocol through native globals.
- `.github/workflows/voice-flow-candidate.yml` and `tests/voice_release/test_workflow_isolation.py`: mandatory adapter gate before export, with retained evidence.
- `examples/features/botelier-flow-trial/PILOT_ADAPTER.md`: supported subset, commands, exact evidence and limitations.

## Task 1: Admit and freeze the supported graph

**Interfaces**

```python
@dataclass(frozen=True)
class PilotIdentity:
    account_id: str
    property_id: str
    tool_id: str
    flow_version_id: str
    call_sid: str

def compile_pilot(config: dict, identity: PilotIdentity) -> CompiledPilot: ...
class PilotAdmissionError(ValueError): ...
```

`CompiledPilot` contains frozen collection specs, saved API/presentation IDs, serialized immutable API/presentation configuration and the full reserved native-name set. It never stores the caller's mutable graph. Collection tools are `collect_<saved-node-id>`. All three collection names are reserved, including the two pause boundaries.

- [x] Write real admission tests before the compiler. A changed graph must fail rather than vanish from the supported subset:

```python
def test_rejects_automatic_private_instructions():
    config = pilot_config()
    config["nodes"][2]["data"]["instructions"] = "Private API instructions"
    with pytest.raises(PilotAdmissionError, match="automatic_instructions"):
        compile_pilot(config, IDENTITY)
```

- [x] Run the tests under `lifecycle_guard.py`; confirm the missing compiler is the initial red result.
- [x] Implement exact topology validation: six distinct nodes, all six expected edges, no extras, unambiguous handles, one initial node, one first collection, one GET, one presentation and two distinct terminal collection pauses. Validate required text slots, variable declarations, safe IDs, relative templates and response mappings. Reject nonempty unsupported request/speech/instruction fields. Use immutable dataclasses and serialized copies.
- [x] Run admission cases for duplicate/missing IDs, cycles, dangling/ambiguous edges, disconnected nodes, greetings/waits, custom/mutating requests, secret/override fields, invalid slots, missing declarations and conflicting outros.
- [x] Verify source graph and identity mutation cannot change the compiled consumer-visible prompt, request or scope.

## Task 2: Run the native dynamic-handler path

**Interfaces**

```python
class NativePilotAdapter:
    def __init__(self, compiled, *, llm, worker, context_aggregator,
                 session_factory, global_functions=()): ...
    async def start(self): ...
    async def close(self): ...
```

The adapter owns its pending task and shutdown, so `close()` is a production lifecycle operation, not a test-only cleanup hook. The test host is the only attachment point in this checkpoint. `manager`, `facts` (copy), and `closed` expose truthful inspection without activating any default path.

- [x] Write a failing pipeline test using actual `OfflineCall`, native `FlowManager`, connected `ActionExecutor.execute_and_log`, SDK tool dispatch and TTS:

```python
assert call.adapter.manager.current_node == "choice"
assert speech(call)[1:] == [
    "Which fixture?", "I am checking the fixture.",
    "Here are the fixture options. Standard costs 0. Which option?",
]
assert len(providers.business_requests) == 1
assert sum(bool(body.get("stream")) for body in providers.requests) == 1
```

- [x] Observe red, then implement native `FlowsFunctionSchema` collection handlers with `cancel_on_interruption=True`. Reject missing/blank/wrong-type/unknown arguments. Claim the first invocation before an await, reject competitors, and check node/claim/task ownership after I/O.
- [x] Execute only `ActionExecutor(session).execute_and_log(ActionExecutionRequest(...))`, preserving account/property/tool/version/call/node identity. Close the short session on all outcomes. Do not invoke any legacy flow handler.
- [x] Select explicit success/no-results/failure outcomes. Validate mapped list/scalars before accepting output facts. Preserve zero and false. Render designer templates, never raw payloads/errors. Include the selected next prompt once.
- [x] Build the next native node only after the outcome is known. Its pre-action reads the live, committed context and removes only the adapter's previous guidance object. RESET with that complete retained history plus fresh guidance; do not take a premature IN_PROGRESS snapshot. Issue one TTSSpeakFrame and disable immediate inference.
- [x] Test HTTP error, transport timeout, missing/malformed lists, explicit empty results, scalar zero/false, invalid and stale handlers, concurrent attempts, pending-read interruption/hangup, late completion and complete cleanup.
- [x] Verify baseline instructions and literal final tool results remain in the next actual model request; prior private guidance and raw payloads never become direct speech.

## Task 3: Preserve the existing MCP contract as native globals

**Interfaces**

```python
def native_mcp_globals(schemas, handlers, *, reserved_names) -> list: ...
```

Input is exclusively the actual host's filtered schema/handler catalogue. The bridge forwards only the existing handler's consumed `function_name`, `arguments`, and async `result_callback` fields; it must not fabricate a native model tool-call ID. Native Flows owns the outer callback and real tool-call bookkeeping.

- [x] Write a failing real-protocol test: advance to `choice`, invoke `mcp_lookup`, inspect the actual SDK result in tool history and verify disabled/current/future collisions have no MCP dispatch path.
- [x] Implement one narrow handler-format bridge. Validate uniqueness and filter every reserved native name before passing globals to FlowManager. Keep the original coordinator handler (including timestamping/isolated invocation) as the invocation boundary.
- [x] Test structured successful/error MCP results, persistence across transitions, disabled tools and collisions against `collect_query`, `collect_choice` and the fallback name. No separate MCP session or credential logic.
- [x] Run the complete local adapter suite with zero unexpected guard denials.

## Task 4: Require and inspect the fresh-image checkpoint

- [x] Write a failing release-policy test that requires `native_pilot_adapter` before candidate export, with neither conditional execution nor continue-on-error, disabled network, read-only root and clean environment.
- [x] Add that step to run the three new test files with the existing lifecycle guard and retained `native-pilot-adapter.log`/checkpoint metadata. Keep every prior gate unchanged.
- [x] Run release-policy tests and the complete local adapter suite. Review all changed paths, caller references, cleanup and the spec acceptance list. Update documentation with actual commands/results, not anticipated passes.
- [ ] Commit only explicit candidate files and push only `candidate/azure-flow-image-checks`. Confirm remote main is unchanged. Do not dispatch an extra workflow when push already triggered it.
- [ ] Wait for the exact commit's full fresh-image run. Inspect metadata and full logs for all steps, actual counts, versions, source integrity and zero unexpected guard reports. Keep generated evidence ignored.
- [ ] Report the bounded result before another checkpoint. If blocked, state the failing gate and leave it visible; do not certify staging/production or continue to deployment.

## Local verification command

Run guards sequentially because their temporary report directory is shared:

```bash
TRIAL="$PWD/examples/features/botelier-flow-trial"
env -i PATH="$PATH" HOME=/tmp/botelier-native-flow-trial \
  PYTHONPATH=/home/runner/workspace/.pythonlibs/lib/python3.11/site-packages \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  DO_NOT_TRACK=1 LOGURU_LEVEL=ERROR NLTK_DATA=/home/runner/nltk_data \
  python -B "$TRIAL/lifecycle_guard.py" \
  --backend-root "$PWD/botelier/backend" \
  --package-root /home/runner/workspace/.pythonlibs/lib/python3.11/site-packages/pipecat \
  --tests "$TRIAL/test_pilot_contract.py" "$TRIAL/test_pilot_pipeline.py" \
  "$TRIAL/test_pilot_mcp.py"
python -B -m unittest discover -s tests/voice_release -v
git diff --check
```

## Self-review

All eight spec acceptance groups map to Tasks 1–4. Native conversational control, existing scoped action/MCP reuse, single speech ownership, immutable admission, explicit outcomes, context replacement, cancellation and no default activation each have consumer-visible coverage. The full fresh-image gate is required, not replaced by local test results. Implementation proceeds inline in the approved existing worktree.

## Source-backed implementation findings

Native priority cancellation can overtake its in-progress control frame. A
small ordered cancellation barrier uses actual native call IDs and the native
assistant's idempotent cancel handler; it does not change SDK internals or
rebroadcast into the host mute strategy.

Built-in `tts_say` pre-actions delay node/tools until audio completes. A failing
held-result-audio test exposed the stale-node window. Native custom entry now
issues the owned speech without making native context/control wait for audio.

The host's tool-call user mute policy stays unchanged. Pending-read cancellation
is certified only at the native control boundary, while result-audio interruption
uses actual synthetic STT. The host's volatile clock tail is expected to change;
its policy prefix and unrelated developer guidance must remain intact.
