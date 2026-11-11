# Offline Pipecat Flows compatibility trial

This is an **isolated engineering trial**, not an activated Botelier runtime,
saved-JSON adapter or production rollout. The backend does not import this harness.
The candidate workflow now runs framework-only and actual-application checks.
The application checkpoint includes candidate-only compatibility and regression
corrections. The API/MCP input, output, speech and retry contracts are documented
in [the node-contract checkpoint](NODE_CONTRACTS.md). Main and production are not
changed by these checks.

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
That framework-only suite does not run a real pipeline, LLM service, aggregator or
playback transport. The separate application suite exercises the real factories,
services and selected handlers; see [its scope and limits](APPLICATION_CHECKPOINT.md).

## Run from the project root

An existing **public** NLTK `punkt_tab` tokenizer cache must be supplied.
The current workspace has it at `/home/runner/nltk_data`. Point `NLTK_DATA` at
another existing public cache if needed; do not let a missing asset cause a
download. A clean HOME otherwise hides that cache, and Pipecat's import path
tries to download it. The network guard blocks such attempts.

```bash
TRIAL="$PWD/examples/features/botelier-flow-trial"
CLEAN=(env -i PATH="$PATH" HOME=/tmp/botelier-native-flow-trial \
  PYTHONPATH="/home/runner/workspace/.pythonlibs/lib/python3.11/site-packages" \
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

For a different host, replace the explicit site-packages and public tokenizer
cache paths with existing installations. CI tests the dependencies inside the
checked candidate image plus a separately mounted pytest installation.

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
  exercise Botelier's existing MCP transport/result mapper. The separate
  [node-contract suite](NODE_CONTRACTS.md) now exercises that actual voice path.
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

## Actual application component checkpoint

```bash
"${CLEAN[@]}" python -B "$TRIAL/application_guard.py" \
  --backend-root "$PWD/botelier/backend" \
  --package-root /home/runner/workspace/.pythonlibs/lib/python3.11/site-packages/pipecat \
  --tests "$TRIAL/test_application_stt.py" "$TRIAL/test_application_pipeline.py" \
  "$TRIAL/test_application_tts.py" "$TRIAL/test_application_terminal.py"
```

This command must pass **and** report `APPLICATION_GUARD_BLOCKED_ATTEMPTS=0`.
A caught guard denial still fails the command. The original framework guard is
unchanged and continues to reject all application imports. CI adds read-only
mounts and disabled networking around the application guard and retains its log
even when a test fails.

## Signed callback checkpoint

```bash
"${CLEAN[@]}" python -B "$TRIAL/callback_guard.py" \
  --backend-root "$PWD/botelier/backend" \
  --package-root /home/runner/workspace/.pythonlibs/lib/python3.11/site-packages/pipecat \
  --tests "$TRIAL/test_application_callbacks.py" \
  "$TRIAL/test_application_callback_delivery.py" \
  "$TRIAL/test_application_callback_lifecycle.py" \
  "$TRIAL/test_application_transfer_recovery.py"
```

Run guards sequentially: they share a temporary output directory. This separate
launcher admits the real calls router and signature helper, not the full server
or unrelated APIs. Dashboard JWT dependencies always deny, database/provider I/O
is synthetic, and real Twilio request validation is retained. A pass requires
zero unexpected guard denials. See `APPLICATION_CHECKPOINT.md` for the exact
scope, unconfirmed-transfer protection and remaining recovery/production gates.

## Disposable PostgreSQL recovery gate (CI only)

The candidate workflow runs `scripts/voice_release/check_transfer_recovery.sh`
before exact-image export. It creates a temporary PostgreSQL fixture with no
network or published ports and shares only its Unix socket with three independent
test containers. One tests real ledger SQL/locking; the next two test a committed
issued request across independent native worker processes. Database cleanup runs
on failure as well as success.

Do not start this database in the workspace, point it at an existing database,
pass a customer connection string, or relax the ordinary offline guards. The
new recovery guard allows only the fixed CI Unix-socket fixture and still denies
providers, subprocesses, credentials and full server/database startup. Synthetic
commit/outcome loss is not a certification of real carrier or database failover.
