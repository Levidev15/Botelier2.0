# Offline API/MCP node-contract checkpoint

This checkpoint checks **existing Botelier runtime code**, not a newly activated
Pipecat Flows controller. It is confined to the candidate branch. It does not
authorize a merge, registry publication, Azure release, routing change or paid call.

## Observed boundaries

| Boundary | Receives | Sends / owns | Checks |
| --- | --- | --- | --- |
| STT → LLM | Finalized synthetic transcript through actual STT/turn aggregation | A normal user message; not a configured URL/method or an instruction override | Native streaming model request serialization remains active |
| Collect node → API | Slot facts and designer node configuration | An empty-argument `execute_<node>` schema; the server chooses transport configuration | Extra model URL/method arguments cannot replace the configured destination |
| API → action executor → transport | Resolved slots, connection/account/property scope, mapping and retry configuration | Actual HTTP request serialization; action/integration logging | Custom and connected requests; read and write method policy; timeout and HTTP errors |
| HTTP response → flow state | Parsed JSON, mapping paths, HTTP outcome | Mapped slots and success/error transition | Array index/wildcard/dot-index parity; zero/false; no-results arrays; missing paths |
| API result → LLM / TTS | Designer narration or an internally generated digest | Designer narration may go directly to TTS; a raw digest remains tool-result data for the LLM | No raw digest, private node guidance or raw provider error in direct speech |
| API response presentation → next node | Response arrays and presentation template | One presentation, then acknowledgement and fresh next-node guidance | No second API narration or generic completion bridge; both result branches |
| MCP discovery → current tools | Connected, enabled server tools plus native names | Native names win; surviving MCP schemas remain non-flow tools across node refresh | Disabled names cannot invoke the server; native collision retained once |
| MCP tool → LLM | Parsed MCP `CallToolResult` | Text-only success retains its legacy string; structured/error results retain text content, `structuredContent` when present, and `isError` | Structured-only, text-only, mixed error, empty error, zero/false |
| Pending API/MCP → hangup | Real pipeline cancellation | Cancel owned I/O and close sessions; no late result or follow-up speech | Native worker/coordinator teardown with each synthetic request held open |

The actual voice handler, factories, worker, aggregators, model serialization,
MCP protocol client, action executor, integration client, flow executor and TTS
pipeline remain active. There is no MCP graph-node type in the current saved
flow format: MCP is an assistant-level tool catalogue. This checkpoint does not
invent a new node or silently claim that MCP calls follow graph edges.

## Corrections and compatibility

1. Custom actions now use the same JSONPath-lite extractor as connected
   integrations and flow mappings, rather than losing bracket-index values.
2. An API_RESPONSE presentation owns that result's direct speech. Its
   acknowledgement updates the returned node/context before the model sees it.
3. Rejected stale API handlers neither repeat wait/error announcements nor
   consume an unrelated response node. The executor still rejects the action.
   Already-spoken wait metadata is removed from the final model tool result.
4. Filtered/enabled MCP schemas survive the flow mapper's current-tool refresh.
   Disabled and native-colliding tools are not reintroduced. All registered
   native handlers reserve their names, including those whose schemas are still
   gated until a later node; a connection cannot replace a future collect action.
5. MCP protocol-level errors and structured-only data are preserved in a
   **tool result**, never promoted into system instructions or direct TTS.
   Legacy successful text concatenation is unchanged. Non-text content is not
   newly supported or certified by this voice-specific correction.
6. The shared integration client retries transport failures only for GET, HEAD
   and OPTIONS. POST, PUT, PATCH and DELETE are not automatically reissued after
   an uncertain response, regardless of configured retry count. A definitive
   auth rejection followed by token refresh is a separate existing path.

A timed-out write may still have succeeded remotely. Do not tell a caller it
definitely failed or retry it manually without reconciling with the provider.
This change is not an exactly-once guarantee, a provider idempotency contract,
or certification of retries after process restart.

## Test scope and reproducibility

The node-contract gate runs 27 native pipeline cases plus 22 direct
action/client/concurrency cases. The latter execute the real runtime code;
they do not parse method source or mirror its implementation. All expected
results are synthetic literals or externally observable request/speech counts.

Use the same clean environment, existing tokenizer cache and package root as
the application checkpoint, then run:

```bash
python -B examples/features/botelier-flow-trial/lifecycle_guard.py \
  --diagnose \
  --backend-root "$PWD/botelier/backend" \
  --package-root /path/to/site-packages/pipecat \
  --tests examples/features/botelier-flow-trial/test_application_api_contracts.py \
  examples/features/botelier-flow-trial/test_application_mcp_contracts.py \
  examples/features/botelier-flow-trial/test_action_boundary_contracts.py
```

The candidate workflow repeats this as a required step **inside the newly
built candidate image**, with a read-only filesystem, empty inherited
environment and Docker networking disabled. JSON-RPC MCP, model SSE, STT/TTS
sockets, business HTTP/DNS and storage I/O use strictly enumerated synthetic
fixtures. No real server, customer database or external provider is contacted.
The fixtures support exactly the scripted model turn count; an extra model
retry is denied rather than answered indefinitely. Tool-result waits require
native function bookkeeping to settle, not just an in-progress context entry.

## Limits and next design gate

- These checks prove serialization, state/action boundaries, cleanup and
  direct-speech ownership. The LLM reply is scripted: **they do not prove a real
  model obeys instructions**, resists prompt injection, or speaks accurately.
- Node instructions are model guidance today, not a deterministic node
  lifecycle. Automatic API execution can pass through a node without a new
  model turn. Do not equate a stored instruction with an enforced step.
- The next controller design must explicitly separate enter/collect/validate,
  act, present, acknowledge and exit. It needs typed outcomes including
  uncertain writes, one transition owner, bounded waits, and rules for when
  node guidance may be sent to the model versus spoken to the caller.
- No saved-flow adapter, controller activation, simulator parity migration,
  arbitrary request-template/body-format certification or cross-process
  business-action idempotency is included.
- MCP remains a separate voice tool path: protocol errors preserve their
  status, but transport failure still uses the existing generic fallback;
  there is no new MCP failure graph edge or automatic flow advancement.
- SMS/simulator MCP paths, multimodal MCP content and all provider/credential
  combinations remain outside this checkpoint. SMS and payment-link features
  remain deferred rather than mocked as completed.
- The guard is an audit/import hook, not an OS sandbox. Local results do not
  replace the fresh-image no-network gate or future approved Azure staging.

## Fresh-image compatibility finding

The first fresh-image run caught an additional dependency boundary that local
passes did not certify: its open-ended MCP requirement resolved **MCP 2.3.0**,
while the verified local environment used **MCP 1.26.0**. Pipecat 1.5.0 imports
the legacy `streamablehttp_client` symbol; MCP 2.3.0 exports only the renamed
`streamable_http_client`. The optional import path silently marks MCP
unavailable while ordinary voice setup continues.

The gate correctly failed: 42 node cases passed, seven MCP cases failed and
unexpected follow-up model attempts remained guard failures. Later callback/
database checks and image export were skipped, not counted as passes. MCP
fixtures now require the actual SDK import and available voice client before
starting a pipeline, so this mismatch cannot be hidden behind tool-unavailable
fallbacks.

Do not patch SDK files, fake MCP availability, install packages into the running
workspace or relax guards to bypass this. The approved correction is an
explicit **candidate-only** `mcp==1.26.0` constraint, consumed only by
`Dockerfile.flow-pilot`. The Pipecat wheel and Flux overlays remain unchanged.
The complete fresh-image gate must verify this dependency resolution; local
passes alone cannot clear the failed image checkpoint. Further dependency
changes remain an approval boundary. The production requirements, Azure
container, running workspace packages and routing have not been changed.
