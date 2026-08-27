---
name: Call-scoped flow facts and replay safety
description: Durable rules for sharing caller facts, correcting dependencies, and preventing repeated flow side effects.
---

Share only explicit caller-provided facts across flow executors. Defaults, API outputs, and other derived values remain flow-local even when variable names match.

**Why:** Aliasing every executor to one slot dictionary lets the first flow's defaults or derived results contaminate unrelated flows. Explicit facts need call-wide reuse, but flow-owned state does not.

**How to apply:** Track provenance separately. Validate explicit facts against the destination schema before import, let the newest explicit correction win, and persist enough provenance for reconnects.

Corrections must normalize every supported cross-field dependency shape, invalidate transitive derived results, and resume from the earliest affected collection gate.

**Why:** Editor templates may express the same dependency through different legacy/current shapes; recognizing only one leaves stale dates, availability, or pricing after a correction.

**How to apply:** Resolve dependency metadata through one normalization helper used by validation, prompt/schema guidance, invalidation, and rewind.

Non-idempotent flow side effects require a stable database idempotency key committed atomically with the business record.

**Why:** In-memory locks and flow-session snapshots cannot close the crash window between a business commit and a later dedupe-marker write, especially across workers.

**How to apply:** Derive the key from stable tenant/call/flow/node identity, enforce uniqueness in the database, and treat uniqueness conflicts as successful retrieval of the existing result.