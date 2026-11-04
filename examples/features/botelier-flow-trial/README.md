# Offline Pipecat Flows compatibility trial

This is an **isolated engineering trial**, not a Botelier runtime, migration,
saved-JSON adapter or production fix. Nothing here is imported by the backend.
No dependency, application, workflow or deployment setting is changed.

## Current decision

The installed `pipecat-ai==1.5.0` wheel supports the inspected Flows API.
The production-prioritized `src/pipecat` target does not have `pipecat.flows`,
and its base `FunctionSchema` does not accept the handlers that native Flows
requires. The gate therefore stops production integration. Do not work around
this by extending package paths, copying framework files or upgrading the
active voice runtime.

Wheel-only characterization exercises **real FlowManager, schemas, callbacks,
frames and LLMContext**, with test doubles for pipeline scheduling and context
delivery. It makes no model, HTTP/MCP, database, TTS or telephony calls.
It does not run a real pipeline, LLM service, aggregator or playback transport.

## Run from the project root

An existing **public** NLTK `punkt_tab` tokenizer cache must be supplied.
The current workspace has it at `/home/runner/nltk_data`. Point `NLTK_DATA` at
another existing public cache if needed; do not let a missing asset cause a
download. A clean HOME otherwise hides that cache, and Pipecat's import path
tries to download it. The network guard blocks such attempts.

```bash
TRIAL="$PWD/examples/features/botelier-flow-trial"
CLEAN=(env -i PATH="$PATH" HOME=/tmp/botelier-native-flow-trial \
  PYTHONPATH="$PWD/.pythonlibs/lib/python3.11/site-packages" \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  DO_NOT_TRACK=1 LOGURU_LEVEL=ERROR NLTK_DATA=/home/runner/nltk_data)

# All gate and native characterization tests; expected exit 0.
"${CLEAN[@]}" python -B "$TRIAL/guard.py" --target wheel \
  --tests "$TRIAL/test_runtime_gate.py" "$TRIAL/test_native_contracts.py"

# Actual module/API probes; expected wheel exit 0, vendored exit 2.
"${CLEAN[@]}" python -B "$TRIAL/guard.py" --target wheel --probe
"${CLEAN[@]}" python -B "$TRIAL/guard.py" --target vendored --probe

# Four deliberately denied operations; separate from ordinary zero-denial runs.
"${CLEAN[@]}" python -B "$TRIAL/guard.py" --target wheel --self-test
```

`--diagnose` prints safe import stack locations for denied operations.
Generated test files stay under `/tmp/botelier-native-flow-trial`.
The Nix interpreter injects `LD_LIBRARY_PATH` even under `env -i`; the launcher
permits that runtime key but rejects secret/unrecognized environment keys.
Values of secret keys are never read.

## How to interpret the checks

- `test_runtime_gate.py` tests fail-closed classification, exact import target
  and supported API requirements, error categories and clean-environment keys.
- `test_native_contracts.py` characterizes framework behavior. A **passing**
  test can demonstrate that the framework lacks a required business safeguard:
  schema declarations are not server-side argument validation, a false business
  result does not veto a returned next node, APPEND retains prior guidance,
  RESET drops conversation history, and an enqueued EndFrame is not playback
  acknowledgement.
- Global functions survive framework tool refresh; complete structured MCP-like
  result payloads survive Flows callback delivery. That does **not** fix or
  exercise Botelier's existing MCP transport/result mapper.
- Callback results here are measured **before** the real assistant aggregator.
  This does not contradict the vendored aggregator's separate falsey-result
  conversion described in the audit.
- The suite intentionally captures the installed built-in end action's legacy
  handler deprecation. The Python 3.11 runtime also emits the upstream `audioop`
  deprecation; neither is hidden by changing dependencies or warning filters.

The guard uses Python audit/import hooks, **not an OS security sandbox**.
It denies network/DNS, subprocess operations, application/database imports,
secret files, and writes outside `/tmp`. Its self-test deliberately proves
four denial paths; ordinary probes/tests must report zero blocked attempts.

See `.local/tasks/flow-engine-trial-report.md` for the measured result and
deferred representative-flow requirements. Runtime alignment must be separately
reviewed and tested before resuming a saved-definition/business adapter.
