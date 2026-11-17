# Flow Tool V1 — Task 1 milestone report

## Scope and exported interface

Added a pure, general immutable graph-admission compiler in
`botelier/backend/botelier/voice/flows/native_graph.py`. It does not replace or
modify the pilot compiler, adapter, runtime hosts, legacy executor, or guards.

Exports:

- `compile_flow(config: dict, identity: PilotIdentity) -> CompiledFlow`
- `CompiledFlow` (frozen): `identity`, `initial_node_id`, `nodes` and `edges`
  tuples, `caller_slots` tuple, `native_names` frozenset, and numeric
  `max_nodes`, `max_edges`, `max_revisits`, `max_config_bytes`, and
  `max_total_io_bytes` bounds; `node(node_id)`, `next_node(node_id, handle=None)`
  and `config()` accessors.
- `CompiledNode` (frozen): `node_id`, `type`, and `data()` which returns a fresh
  behavior-data copy.
- `CompiledEdge` (frozen): `edge_id`, `source`, `target`, `source_handle` and
  `target_handle`.
- `CallerSlot` (frozen): `node_id`, `variable`, `prompt`, `type`.
- `NativeGraphError`, with stable, payload-free category/node/field diagnostics.

Compiled behavior data and the original serialized definition are snapshotted;
source mutation and mutation of accessor copies do not alter the active graph.
Positions, styles, React Flow selection/layout metadata are accepted and retained
by `config()` but are not used as behavior. `next_node` resolves only an exact
branch or an unambiguous default. Legacy single unnamed continuation edges are
also used for requested `confirmed` and API/capability `success`/`error`
transitions; ambiguous labeled branches are not silently selected.

Bounds are 128 nodes, 512 edges, 256,000 input-definition bytes, 32,000 bytes
per node data object, 1,000,000 total config/data I/O bytes, and 12 runtime
revisits. These are exposed compile-time limits, not evidence that a runtime
enforces visits or I/O.

The compiler validates all 15 current node kinds, slot declarations and types,
form slot ordering, templates and references, retries/validation shape,
condition/router handles and fallback, API/custom/integration/capability
settings and bounds, mappings/projection, confirmations, deterministic
expression syntax, typed record-mapping shape, transfer/end speech, option
picker writes, selected initial node, reachable nodes, and terminal/branch
topology. Expressions are parsed and constrained but never evaluated. It
performs no provider, integration, record, database, or network lookup.

Caller-input nodes (slot/form/confirmation/option picker and waiting initial or
message) are revisit boundaries. Cycle detection removes their outgoing edges
and rejects cycles that could advance without caller input. This supports
caller-mediated revisits while leaving runtime revisit enforcement to a later
milestone.

## Test-first and verification evidence

The first guarded red test used the clean application-guard runner against the
new test file before `native_graph.py` existed. As expected, the tests failed
on the missing module (27 failed, with no blocked attempts).

Final new-test command, run in the clean environment with the existing installed
Pipecat package:

```sh
cd /home/runner/workspace/.worktrees/azure-flow-pilot
env -i PATH=/home/runner/workspace/.pythonlibs/bin:/usr/bin:/bin \
  HOME=/home/runner PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python -B examples/features/botelier-flow-trial/application_guard.py \
  --backend-root /home/runner/workspace/.worktrees/azure-flow-pilot/botelier/backend \
  --package-root /home/runner/workspace/.pythonlibs/lib/python3.11/site-packages/pipecat \
  --tests examples/features/botelier-flow-trial/test_native_graph.py
```

Actual final output:

```text
..........................................                               [100%]
42 passed in 0.26s
APPLICATION_GUARD_BLOCKED_ATTEMPTS=0
```

Existing guarded baseline command (Pipecat framework characterization):

```sh
cd /home/runner/workspace/.worktrees/azure-flow-pilot
env -i PATH=/home/runner/workspace/.pythonlibs/bin:/usr/bin:/bin \
  HOME=/tmp/botelier-native-flow-trial \
  PYTHONPATH=/home/runner/workspace/.pythonlibs/lib/python3.11/site-packages \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  DO_NOT_TRACK=1 LOGURU_LEVEL=ERROR \
  NLTK_DATA=/tmp/botelier-native-flow-trial/nltk_data \
  python -B examples/features/botelier-flow-trial/guard.py --target wheel \
  --tests examples/features/botelier-flow-trial/test_native_contracts.py
```

The public `punkt_tab.zip` bundled in the candidate was inspected and extracted
only to `/tmp/botelier-native-flow-trial/nltk_data`; no package was installed
and no network fetch was used for that final run. Actual final output:

```text
................                                                         [100%]
16 passed, 1 warning in 12.96s
TRIAL_GUARD_BLOCKED_ATTEMPTS=0
```

The one warning is the installed Pipecat package's upstream Python `audioop`
deprecation warning. The new tests separately cover each node type and slot
type, a combined branch/form/API/projection/selection/confirmation/record flow,
immutable copy behavior, API/confirmation unnamed-edge compatibility,
condition/router/fallback lookup, bounded wait and automatic cycles, false/zero
preservation, malformed input, and diagnostic redaction.

## Parity gaps and limits

- This milestone compiles only; it does **not** execute a flow or prove native
  runtime behavior, provider behavior, or caller experience.
- It does not query the account database to verify record-type ownership,
  record fields, required fields, field types, status options, integration
  connection ownership/endpoint schemas, or capability registration. Runtime
  business-action admission must verify those before effects.
- Custom destination syntax is checked, but hostname/DNS/IP allowlists and
  request authorization remain runtime/action-boundary requirements.
- The schema is intentionally allowlisted: unrecognized behavior settings are
  rejected with safe diagnostics, so future editor controls require explicit
  compiler support before admission.
- The 12 revisit limit is exported for the future adapter; this compiler does
  not itself execute/enforce a runtime revisit counter.
- No UI/editor, adapter, host, or publication integration was changed.

## Guard-execution concern

Two early, corrected invocations did not meet the requested zero-attempt
condition. An initial test import used the eager `botelier.voice` package path;
the application guard blocked 27 attempts to import the live call-handler
module. The test fixture was then changed to load only the pure module paths,
and subsequent application-guard runs report zero blocked attempts.

An initial framework-baseline run omitted an available offline NLTK cache and
Pipecat's import path attempted its downloader; the strict guard denied two
network attempts. No network operation completed. The documented public archive
was then extracted to the isolated `/tmp` cache above, and the final baseline
run reports zero blocked attempts. These final green counts do not erase the
earlier denied attempts; aggregate task history therefore was **not** zero
forbidden attempts. No provider, database, or customer resource was accessed.

## Milestone files

- `botelier/backend/botelier/voice/flows/native_graph.py`
- `examples/features/botelier-flow-trial/test_native_graph.py`
- `generated-artifacts/voice-pilot/implementation/v1-task-1-report.md`
