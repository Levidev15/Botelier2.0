# Native action broker implementation report

## Scope and ownership

Implemented the scoped native action broker in `native_actions.py` and
`native_messaging.py`, narrowly extended API source validation in
`native_graph.py`, and added compiler, broker, record, effect, integration,
MCP, messaging, mapping, and preview tests. The runtime consent correction was
committed separately as `9b2e6c064`; no runtime files are included here.

No changes were made to the parent-owned effect ledger/storage or host files.
This report describes implementation evidence, not production activation.

## Public interfaces

- `NativeActionRunner(compiled, session_factory, *, messenger=None,
  execution_mode="execute", channel="voice", http_executor_factory=None,
  mcp_client_factory=None)`
- `await runner.execute(node, facts, *, confirmation=None)`
- `runner.close()`
- `NativeMessenger(*, identity, twilio_client, from_number,
  execution_mode="execute", email_dispatch=None, timeout=8.0)`
- Pure host helper:
  `map_project_response(config, response, declared_variables=None)`

`channel` accepts only `"voice"` or `"simulation"`. Simulation selects the
existing `"test"` operation-policy channel and is always preview-only, even if
the caller passes `execution_mode="execute"`. Preview validates current
bindings, typed request arguments, recipient, confirmation and mapping policy,
then returns `preview_required`; it does not send, create Records, or execute a
provider request. Host-supplied sample responses can use the public pure
`map_project_response` helper.

## Implemented safeguards

- Rechecks the active flow tool, account-owned ToolSet, current flow version,
  and active property before every action; voice requires the currently
  published version, while simulation requires the current draft or published
  binding.
- Custom HTTP uses the existing `ActionExecutor`, request-template helpers,
  secret loading, and SSRF-safe transport. Output mapping and projection are
  bounded; custom API origin is not caller-controlled through path values.
- Imported integrations use current owned connection metadata and operation
  policy. Legacy ID-less binding is permitted only when exact method/path and
  declared query keys resolve one enabled permitted endpoint. Missing,
  disabled, foreign, or ambiguous endpoints fail closed. Integration channel
  policy receives `"voice"` or `"test"`, never `"voice"` for TestLab.
- Node-level MCP reads the current account-owned connection and explicit
  property/global scope, checks the configured enabled tool list, ignores
  server `readOnly` annotations, validates the current tool schema and args,
  and bounds total execution time, JSON structure, and result size. Full JSON
  content blocks are preserved internally; only configured mappings and
  projection can reach LLM-facing data.
- SAVE_RECORD validates current RecordType and typed fields, required/status
  constraints, and the account-owned call/assistant association before
  idempotent creation. Zero and false values are preserved.
- SMS and email use deterministic configured templates and current
  confirmation. SMS sender/recipient and email sender/recipient/subject/body
  are validated; only supported Gmail/Microsoft sender connections are
  accepted. Provider timeouts remain ambiguous, and acceptance is not reported
  as delivery or a completed booking.
- Financial/payment actions and unsupported capability/tool types fail closed.
- API mapping/projection uses `map_project_response`, which preserves zero and
  false while exposing only configured outputs.

### MCP connection configuration policy

`connection_config` must contain either:

- `property_id`: UUID exactly matching the current flow property; or
- `account_global: true`: explicit account-global binding.

`native_enabled_tools` is a required, unique list of exact enabled server tool
names (maximum 128). `native_read_only_tools` is an optional unique list of
exact names that must be a subset of `native_enabled_tools`. Every enabled
tool not in `native_read_only_tools` is treated as a write and requires
confirmation. Remote server read-only annotations are not trusted. This is
node-level MCP only; parent-owned assistant-global/shared MCP integration is
not included.

## Guard evidence

Latest lifecycle guard command (all commands were run under the prescribed
`flock /tmp/botelier-flow-v1-guard.lock`):

```sh
flock /tmp/botelier-flow-v1-guard.lock env -i PATH="$PATH" \
  HOME="$PWD/generated-artifacts/voice-pilot/offline-assets" \
  PYTHONPATH=/home/runner/workspace/.pythonlibs/lib/python3.11/site-packages \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 LOGURU_LEVEL=ERROR \
  python -B examples/features/botelier-flow-trial/lifecycle_guard.py \
  --backend-root "$PWD/botelier/backend" \
  --package-root /home/runner/workspace/.pythonlibs/lib/python3.11/site-packages/pipecat \
  --tests "$PWD/examples/features/botelier-flow-trial/test_native_graph.py" \
          "$PWD/examples/features/botelier-flow-trial/test_native_integration_binding.py" \
          "$PWD/examples/features/botelier-flow-trial/test_native_messaging.py"
```

Result: **62 passed; 0 lifecycle guard blocks**.

The editor guard was also retried after parent changes to
`native_text_host.py`/text-host fixture integration. It currently stops during
fixture setup, before the broker assertions: the parent fixture passes its
plain-dict voice config into `NativeTextHost`, which now requires a
`VoiceAgentConfig`. The attempt reported 7 fixture-setup failures, 2 passes,
and 0 guard blocks. Parent-owned host/fixture code was not modified. Broker
tests that require `NativeEffectsFixture` need that parent-owned fixture
signature synchronized before they can be re-run against the current host.

## Limitations and handoff

- Safe correction/update of an existing Record after caller correction is not
  implemented. The strict ledger correctly blocks changed arguments for the
  same action identity; a separately authorized/versioned update operation is
  needed rather than weakening that invariant.
- `capability` nodes and Tool types other than SMS/email remain unavailable.
- Preview does not invent sample provider results; hosts may project an
  operator-supplied sample with the pure helper above.
- No live provider credentials, calls, messages, or production services were
  used.
- Runtime ownership is returned to the parent after separate commit
  `9b2e6c064`; further runtime speech/terminal work remains parent-owned.
