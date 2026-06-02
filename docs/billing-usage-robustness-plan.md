# Billing and Usage Robustness Plan

Date: 2026-06-01

## Context

Botelier runs on top of upstream Pipecat for live voice calls. Pipecat emits usage metrics through `MetricsFrame`s, and Botelier currently captures those metrics with `UsageObserver` attached to `PipelineTask` with `enable_usage_metrics=True`.

The product goal is two views over the same accurate usage foundation:

- Platform admin overview: cross-account billable usage, internal cost of goods, and margin.
- Account billing view: tenant-scoped usage and charges that account users can trust.

The current implementation already has a good base for voice calls:

- Customer-facing voice charges are frozen as `call_billing_items`.
- Account billing rates are append-only through `account_billing_config`.
- Twilio authoritative durations correct inbound and warm-transfer billing.
- Pipecat LLM/TTS usage is captured at call teardown into `call_logs`.
- Account-facing APIs do not expose internal COGS.

## Current Strengths

1. Pipecat usage capture is placed at the right layer.

   `UsageObserver` listens to Pipecat `MetricsFrame`s as a task observer, not as a pipeline processor. This keeps usage capture low-latency and avoids disturbing the voice path.

2. Voice call customer charges are frozen.

   `call_billing_items` store quantity, rate, cost, and billing config id. Rate changes do not mutate past voice call charges.

3. Twilio duration corrections are handled.

   Inbound billing is upserted from resolved/Twilio duration. Warm-transfer legs write separate outbound transfer billing items once the transfer callback provides authoritative leg duration.

4. Admin and tenant surfaces are separated.

   Admin APIs include internal cost and margin. Account APIs show only account-facing usage and charges.

## Main Gaps

1. SMS billing is recomputed instead of frozen.

   Voice calls use immutable billing items, but SMS totals are calculated from message counts using the current effective SMS rate. Historical SMS charges can change when rates are edited.

2. Transfer billing items are not directly linked to transfer legs.

   Outbound transfer items are inferred by timing and displayed by zipping billing items to transfer legs by creation order. This is workable but not audit-grade.

3. Admin internal COGS is recalculated with current platform rates.

   Customer charges are frozen, but internal COGS uses the currently effective `platform_internal_rates`. This is fine for "current-rate margin" reporting, but not immutable historical margin.

4. OpenAI prompt-cache prewarm usage is not captured.

   `_prewarm_llm_cache()` calls OpenAI outside the Pipecat pipeline, so `UsageObserver` cannot see its token usage. Admin COGS is undercounted by that prewarm cost.

5. SMS AI token cost is not included in admin COGS.

   SMS messages have `tokens_used`, but admin internal cost currently counts SMS transport cost, not SMS LLM cost.

6. `CallLog.estimated_cost_usd` exists but is not maintained.

   Current APIs correctly sum `call_billing_items`, but the column is misleading if future code assumes it is authoritative.

## Recommended Design

Move toward a ledger-based usage and billing model.

### Usage Events

Create an append-only raw metering table, for example `usage_events`.

Each event should capture:

- `account_id`
- source type: `voice_call`, `voice_transfer`, `sms_message`, `llm_prewarm`, `sms_llm`
- source id: call id, call leg id, SMS message id, or generated event id
- provider: `twilio`, `openai`, `deepgram`, etc.
- model or SKU where applicable
- raw quantity and unit: tokens, cached tokens, characters, seconds, minutes, messages
- observed timestamp
- metadata JSON for provider IDs and diagnostics

This separates raw metering from what the customer is charged.

### Customer Billing Items

Keep customer-facing charges as immutable line items, but generalize the current call-only shape.

Recommended line item types:

- `voice_inbound`
- `voice_transfer`
- `sms_inbound`
- `sms_outbound`
- future: `voice_outbound`, `number_rental`, etc.

Each billing item should include:

- `account_id`
- `source_usage_event_id` where possible
- `call_log_id` nullable
- `call_leg_id` nullable
- `sms_message_id` nullable
- frozen quantity
- frozen unit
- frozen rate
- frozen cost
- billing config id

Add uniqueness constraints to prevent duplicate charges:

- one inbound voice charge per call
- one transfer charge per transfer leg
- one SMS charge per message and direction

### Internal Cost Items

Create immutable internal COGS records if historical margin needs to stay fixed.

Each internal cost item should include:

- source usage event id
- platform internal rate id
- provider/model/SKU
- frozen quantity
- frozen rate
- frozen internal cost

Admin reports can then choose:

- historical margin: sum frozen internal cost items
- current-rate margin: recalculate with current platform rates, clearly labeled

### Off-Pipeline Usage Capture

Capture usage for operations that do not flow through Pipecat:

- OpenAI prompt-cache prewarm
- SMS AI replies
- any future background AI task

For `_prewarm_llm_cache()`, store the OpenAI response usage as an internal-only usage event and internal cost item. Do not expose it to tenant billing unless the product intentionally charges for it.

### API Strategy

Keep the current endpoints and frontend contracts where possible:

- `/api/admin/billing/accounts`
- `/api/admin/billing/accounts/{account_id}/detail`
- `/api/admin/billing/accounts/{account_id}/timeseries`
- `/api/billing/usage/summary`
- `/api/billing/usage/calls`
- `/api/billing/usage/timeseries`

Change the implementation behind them to aggregate from the ledger. This avoids a major frontend rewrite while improving correctness.

## Implementation Plan

1. Add schema.

   - Add `usage_events`.
   - Add `internal_cost_items`.
   - Extend or replace `call_billing_items` with nullable `call_leg_id`, `sms_message_id`, `source_usage_event_id`, and a more general item type set.
   - Add indexes on account/time and source IDs.

2. Backfill current voice billing.

   - Create usage events for existing call billing items.
   - Link inbound items to call logs.
   - Link transfer items to transfer legs where deterministic; mark uncertain matches in metadata.

3. Freeze SMS billing.

   - On inbound/outbound SMS creation or status completion, write SMS usage and billing items.
   - Use the effective account billing config at message time.

4. Capture off-pipeline AI usage.

   - Record OpenAI prewarm response usage.
   - Record SMS AI prompt/completion usage with model and provider.

5. Snapshot internal costs.

   - At usage event creation, resolve current platform internal rates and write internal cost items.
   - Keep the current-rate recalculation available only if useful and label it clearly.

6. Update aggregation queries.

   - Admin overview aggregates customer billing items and internal cost items.
   - Account view aggregates only customer billing items.
   - Timeseries uses item timestamps/source timestamps consistently.

7. Add tests.

   - Rate edits do not mutate past SMS or voice charges.
   - Duplicate Twilio callbacks do not create duplicate billing items.
   - Transfer billing item links to the correct call leg.
   - Prewarm usage affects admin COGS but not account billable total.
   - Account users cannot see internal cost fields.

## Recommended Priority

Do this in three safe passes:

1. Add `call_leg_id` to transfer billing items and enforce idempotency by source.
2. Freeze SMS billing into line items.
3. Add raw usage/internal cost ledgers for audit-grade admin margin.

That order fixes the highest billing correctness risks first while preserving the current admin and account UI contracts.
