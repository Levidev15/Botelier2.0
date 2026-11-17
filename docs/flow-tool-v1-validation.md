# Flow Tool V1: development validation and manual acceptance

## Status and boundaries

The candidate uses Pipecat Flows as the conversation controller for all 15
existing node types. Botelier supplies the editor, configuration compiler,
integration/action brokers, validation, privacy controls and host lifecycle.
It does not delegate a selected native flow to the legacy flow executor.

This is an isolated development candidate, not a production cutover. Automated
provider doubles prove application behavior, not real speech quality, vendor
behavior or delivery. The normal production runtime and phone routing have
not been switched by this work. Keep the compatibility runtime until its
remaining callers and replacement release gates have been migrated explicitly.

The reservation example stops at an authoritative quote and sending a review
link. A quote is not a reservation, provider acceptance is not confirmed
delivery, and sending a link is not payment completion. This milestone does
not authorize checkout-session creation, charging, card collection or PCI Proxy
integration.

## Node execution contract

STT supplies caller utterances; it does not decide transitions. The active
node's schema, validated facts and current visit/revision determine what the
LLM can request. Private node guidance is not a speech template. Scripted
speech and guided wording have separate delivery paths.

| Node | Input and decision | Output and advancement |
| --- | --- | --- |
| Initial | Published flow settings, private system guidance and greeting configuration | Configured greeting; enter the next node according to the wait setting |
| Message | Static template or active-node guidance; caller response when required | Scripted or guided speech; wait/advance under the node's completion rules |
| Collect Slot | Current caller evidence and the declared field schema | Typed, constrained value or a retry; advance only after acceptance |
| Collect Form | Declared ordered fields and current caller evidence | Atomically validated facts; one utterance may supply multiple fields |
| API Request | Current validated facts and a configured custom/integrated API, capability, saved Tool or MCP binding | Bounded typed request/result, mapped facts and configured result branch |
| API Response | Configured source data and presentation templates | Caller-safe presentation or the explicit no-results branch |
| Condition | Declared facts, operator and comparison value | Server-selected true/false branch |
| Router | Declared routing value, options and fallback | Server-selected configured branch |
| Confirmation | Current summary/facts, caller response and action consent requirements | Confirm, edit or retry; a qualified “yes, but…” cannot authorize a write |
| Set Variable | Static value, typed template or bounded expression | Validated assignment before the next node |
| Save Record | Owned RecordType, typed field/status mappings and create/update configuration | Truthful persisted result with ownership and duplicate checks |
| Transfer | Configured destination/mode and announcement | Playback-aware host transfer callback and known outcome; real carrier behavior needs manual acceptance |
| Capability | Declared capability schema and binding | Validated capability result and configured continuation |
| Option Picker | Current option list, caller selection and configured bindings | One validated selection with atomic related values; no implicit first-room choice |
| End | Closing template and current terminal state | Closing speech, then the host's terminal lifecycle; no repeated terminal action |

Unsupported or invalid meaningful configuration must produce node/field
diagnostics, not be silently discarded. Natural-language grounding supports
bounded formats and explicit correction safeguards; it is not a guarantee
that every possible utterance is unambiguous. Ambiguous input needs clarification.
Keep API-result descriptions in the presentation node and the next question in
the collection/selection node. Configuring the same question in both places
intentionally speaks it twice; the runtime must not silently remove authored
speech just because the text matches.

## Configure and inspect external data

1. Use an account/property-owned connection or Tool. Credentials remain on
   the server; do not paste them into prompts, variables or sample JSON.
2. For MCP, use the manager-approved tool grant. Read-only resource tools and
   tools that may write are distinct; a tool being discoverable is not consent
   to execute it. Writes require the action's current confirmation and
   durable effect protections.
3. Declare the request parameters and typed outputs. Nested JSON is supported.
   A whole unquoted variable token retains its JSON type; quoting it makes a
   string. For declared object `stay` and number `children`, for example:

   ```text
   {"stay": {{stay}}, "guests": {"children": {{children}}}}
   ```

4. Configure response mappings separately from the LLM-facing projection and
   bounded cleanup. Preserve objects, arrays, `0`, `false` and missing/null
   distinctions. Do not turn financial cleanup into inferred prices or taxes.
5. Inspect a synthetic sample with the owned-flow response preview. This is
   local data processing, not an API/MCP request. The preview describes the
   application-controlled data supplied to the model, not hidden provider
   processing or an entire vendor model request.
6. Connect explicit success, empty-result and failure paths as applicable.
   Test expired credentials, missing fields and timeouts without allowing
   the model to invent a successful business outcome.

## Reservation-link reference contract

- Availability binds the selected room/rate/offer, including a non-first choice.
- A verified booking/quote operation supplies the selected stay, currency,
  pricing basis, subtotal, tax total/treatment, fee total/treatment and total.
  Due-now amounts and terms are retained when supplied. No tax rate, total or
  missing financial field is guessed.
- The native quote validator checks that authoritative snapshot against the
  current selection. The booking system must supply a supported non-charging
  link; do not infer that an endpoint is read-only from its name.
- The recipient, required public quote facts and protected fingerprint
  participate in current confirmation. Changes invalidate stale authority.
- The private URL/fingerprint stay outside model context and speech. The
  deterministic SMS/email template receives the validated link at the
  server-side send boundary.
- Known pre-submit failure is different from an uncertain post-submit outcome.
  An uncertain send is not automatically replayed.
- The reference Record says `link_accepted` after provider acceptance, not
  `delivered`, `booked` or `paid`.

## Existing test entrypoints

### Text Test Lab

On a controlled development deployment, open
`/dashboard/tools/{toolId}/flow`, select **Native development** as the Test Lab
engine, and use the published version and linked assistant. The request uses
`POST /api/simulate/start` with `engine: native_pilot`; the historical engine
identifier is not a restriction to the old fixed pilot graph.

**Start Test is not an offline model check:** it uses the configured model and
can incur model costs. Native business actions are preview-only; they do not
contact API/MCP providers, send messages, move calls or write real Records.
The automated browser/SDK checks replace model/provider IO as well; starting
the development Test Lab yourself is different from those offline checks.

1. Enter synthetic caller answers normally. When an external action is reached,
   the current SDK callback pauses at a **Waiting for a sample response** card.
   Caller input is paused while that sample is outstanding.
2. For HTTP/integrated APIs and saved API Tools, paste synthetic result JSON
   before response mapping and choose the outcome/status. The published node's
   actual mapping and projection run on it. Raw JSON source is submitted without
   browser reserialization, preserving large integer IDs, zero, false and
   decimal strings. Do not paste credentials or customer data.
3. MCP samples use the normalized SDK result envelope, for example:
   `{"isError":false,"structuredContent":{"rooms":[]},"content":[]}`.
   `content` is required. Samples do not run discovery or contact a server;
   existing ownership, tool grants, argument validation and write confirmation
   still apply.
4. SMS/email and transfer cards accept only an outcome/status, not a body,
   private URL, provider text or caller confirmation. Accepted messages use the
   same canonical receipt mapping as a real accepted send. Network/server
   failures of writes remain uncertain and cannot be automatically replayed.
5. The matching one-use sample resumes the same SDK callback/turn; it is not
   another caller answer or consent. The next node follows the saved graph.
   Record schemas and updates are validated against session-local simulated
   data, isolated by flow/version; no real Record or effect ledger is written.
6. Reset/close clears the samples and simulated effects. Expired, repeated,
   foreign-session or stale-visit responses are rejected. Changing the selected
   flow/version requires a fresh rehearsal.

The separate sample-only response preview on an inspector tests mapping without
starting/resuming a conversation. Neither preview proves actual credentials,
network delivery, vendor response shape or carrier behavior; validate those
later against the approved sandbox/development setup.

### Voice development entry

Voice selection is separate from the Test Lab. The development backend requires
`BOTELIER_ENV=development`, `BOTELIER_NATIVE_FLOWS_DEV=1` and an explicit
`assistant.call_settings.native_flow_tool_id` selecting an owned published
FLOW. Do not imply that selecting the text engine changes phone routing.

There is not yet a dedicated live-call destination provisioned by this
candidate. Before manual calls, agree on an isolated development destination,
synthetic guest data, sandbox booking/MCP services, controlled recipients and
the permitted real voice/message costs. Provisioning, deploying or repointing
a number requires separate approval. Do not call a production number expecting
this isolated candidate to be active.

## User-led manual acceptance

After current candidate-image and authenticated editor checks pass, run these
against the approved development destination. The user places the calls.

| Scenario | Required outcome |
| --- | --- |
| Normal stay, spoken dates/counts, zero children | Correct structured facts, natural prompts and ordered nodes |
| Complete stay in one sentence; facts in a different order | Accepted facts without needless repeated collection |
| Choose the second room | Quote, summary, link and Record refer to that room/rate |
| Correct dates, room or recipient | Old selection/quote/consent cannot authorize a stale send |
| Say “yes, but change the room” | No send or business write until fresh explicit confirmation |
| Interrupt speech or answer during a node handoff | No lost caller answer, stale speech or repeated action |
| No availability; missing tax/link; wrong currency/origin; timeout | Explicit configured fallback; no fabricated price/link/success |
| Repeat, retry, reconnect or hang up | No duplicate message/Record; truthful known/unknown outcome and clean lifecycle |
| Accept the review link by SMS and by email | One correct selected-stay summary and authoritative price/tax/fee snapshot |
| End or transfer | Closing/announcement is heard; no cut-off or duplicated terminal action |

Capture redacted node/order/outcome evidence and the candidate commit/version.
Keep contact details, bearer links, credentials and complete provider payloads
out of shared reports. Fix manual findings, add regression tests and rerun the
affected checks before a separate release proposal.

## Automated evidence

The required suite registration is
[`check_full_flow_v1.sh`](../scripts/voice_release/check_full_flow_v1.sh).
It separates pure application, actual SDK lifecycle, authenticated editor/API
and MCP-management boundaries. Unexpected guard denials fail a run; the
deliberate-denial MCP self-test is isolated from the zero-denial suites.

The complete synthetic booking journeys use the actual SDK/controller,
compiled broker and disposable ORM, replacing only provider IO. They cover
split/single-turn stay intake × HTTP/MCP availability × SMS/email delivery,
qualified refusal, exact pricing, replay prevention, privacy and shutdown.
Neither these checks nor a successful container build certifies real audio or
authorizes production activation.
