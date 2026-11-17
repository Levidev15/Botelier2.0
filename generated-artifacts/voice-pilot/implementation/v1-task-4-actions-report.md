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
  `map_project_response(config, response, declared_variables=None,
  *, variable_declarations=())`

`CompiledFlow.variable_declarations` is an immutable tuple of frozen
declarations (`key`, `origin`, `.data()`). Explicit declarations remain
authoritative; validated API/capability response mappings and
`responseVariables` contribute output-only declarations. Unknown output types
remain bounded JSON (`type=None`) and never become caller slots. `config()` is
unchanged. Mapping defaults preserve falsy values such as `0` and `False`, and
required explicit outputs still fail when missing. Output-only values are
available to downstream presentation, selection, conditions, and templates;
array consumers reject explicit non-array declarations and defer unknown JSON
shape checks to runtime.

`channel` accepts only `"voice"` or `"simulation"`. Simulation selects the
existing `"test"` operation-policy channel and is always preview-only, even if
the caller passes `execution_mode="execute"`. Preview validates current
bindings, typed request arguments, recipient, confirmation and mapping policy,
then returns `preview_required`; it does not send, create Records, or execute a
provider request. Host-supplied sample responses can use the public pure
`map_project_response` helper.

## Implemented safeguards

- Rechecks the active flow tool, account-owned ToolSet, immutable flow-version
  status, and active property before every action. A host-admitted published
  version remains usable if a newer version becomes the current pointer during
  the call; current connection/account/property revocations still block.
- Custom HTTP uses the existing `ActionExecutor`, request-template helpers,
  secret loading, and SSRF-safe transport. Output mapping and projection are
  bounded; custom API origin is not caller-controlled through path values.
- Imported integrations use current owned connection metadata and operation
  policy. Legacy ID-less `integrationSlug` binding is permitted only when the
  account/property-scoped connected integration resolves uniquely and the
  exact method/path and declared query keys resolve one enabled permitted
  endpoint. Missing, disabled, foreign, or ambiguous connections/endpoints fail
  closed. Integration channel policy receives `"voice"` or `"test"`, never
  `"voice"` for TestLab.
- Both direct `apiSource="capability"` and selected `CAPABILITY` Tool sources
  use the existing `CapabilityResolver`/registry, current property-owned
  connection, endpoint, and operation policy. Canonical arguments are schema
  checked and translated through current endpoint metadata. Integration-backed
  reads and confirmed writes use the strict native effect ledger; service-backed
  payment is rejected at compile and runtime.
- Selected `API_REQUEST` Tools resolve from the current account-owned ToolSet,
  use the existing `ActionExecutor`, pinned HTTPS origin/template rendering,
  stored output-map policy, confirmation for writes, and strict native effect
  ledger. Selected `DYNAMIC_OPERATION` Tools recheck current connection,
  published action/version, endpoint, operation policy, allowed channel,
  confirmation, response policy, and output mapping before reusing the existing
  `build_operation_api_config`/`ActionExecutor` path. Nested FLOW and terminal
  Tool types are not dispatched; payment-classified operations remain blocked.
- Node-level MCP reads the current account-owned connection and explicit
  property/global scope, checks the configured enabled tool list, ignores
  server `readOnly` annotations, validates the current tool schema and args,
  and bounds total execution time, JSON structure, and result size. Full JSON
  content blocks are preserved internally; only configured mappings and
  projection can reach LLM-facing data.
- SAVE_RECORD validates current RecordType and typed fields, required/status
  constraints, and the account-owned call/assistant association before
  idempotent creation. Record mutation and encrypted known receipt are committed
  atomically in one transaction using the existing unique
  `OperationIdempotency` table; internal Record claims never commit pending.
  Same-input creation replays its receipt, while changed create arguments are
  blocked. A separate versioned correction path is available only through
  `updateSourceNodeId`, bound to a reachable same-type source-node Record and
  prior `updated_at`+data+status compare-and-set. Its typed operation key binds
  that prior revision and intended replacement. Fresh confirmation is required;
  external booking/message/API effect-ledger rules are unchanged. Zero and
  false values are preserved.
- SMS and email use deterministic configured templates and current
  confirmation. SMS sender/recipient and email sender/recipient/subject/body
  are validated; only supported Gmail/Microsoft sender connections are
  accepted. Provider timeouts remain ambiguous, and acceptance is not reported
  as delivery or a completed booking.
- Financial/payment actions and unsupported Tool types fail closed.
- API mapping/projection uses `map_project_response`, which preserves zero and
  false while exposing only configured outputs.

### MCP connection configuration policy

`connection_config` must contain either:

- `property_id`: UUID exactly matching the current flow property; or
- `account_global: true`: explicit account-global binding.

`native_enabled_tools` is a required, unique list of exact enabled server tool
names (maximum 128). `native_read_only_tools` is an optional unique list of
exact names that must be a subset of `native_enabled_tools`. Every enabled tool
not in `native_read_only_tools` is treated as a write and requires confirmation.
Remote server read-only annotations are not trusted. This is node-level MCP
only; parent-owned assistant-global/shared MCP integration is not included.

## Guard evidence

The scoped `editor_guard.py` suite was run under
`flock /tmp/botelier-flow-v1-guard.lock` with:
`test_native_graph.py`, `test_native_actions.py`,
`test_native_capabilities.py`, `test_native_integration_resolution.py`,
`test_native_record_actions.py`, and `test_native_tool_sources.py`.

Result: **80 passed; 0 guard blocks**. Coverage includes compiler declarations,
output-only JSON downstream use and explicit non-array rejection, source
binding, actual scoped capability/API/dynamic-operation execution, slug
resolution, typed/default mapping, actual disposable Record storage, encrypted
atomic receipts, acknowledgement-loss replay, and correction CAS.
The parent separately owns the host fixture and strict external-ledger
integration; no host/fixture files are included in this scoped change.

## Limitations and handoff

- Preview does not invent sample provider results; hosts may project an
  operator-supplied sample with the pure helper above.
- No live provider credentials, calls, messages, or production services were
  used.
- Runtime ownership is returned to the parent after separate commit
  `9b2e6c064`; further runtime speech/terminal work remains parent-owned.
