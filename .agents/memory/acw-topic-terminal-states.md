---
name: ACW topic generation & terminal skip states
description: Post-call QA topic field constraints (OpenAI strict mode) and the terminal-skip / manual-re-run contract
---

**Rule:** OpenAI strict `json_schema` mode rejects `maxLength` (and most string constraint keywords) — length/word caps on LLM output fields must be enforced server-side after parsing, never in the schema.
**Why:** Adding `maxLength` to the required `topic` field made attempt-1 (strict) fail with a 400; the sanitizer (`_sanitize_topic`: collapse whitespace, strip edge punctuation, cap 3 words / 60 chars) is the only enforceable cap.
**How to apply:** Any new required field in the ACW response schema (or any strict-mode schema) gets `{"type": "string"}` only; validate/truncate in Python.

**Rule:** ACW failure paths must stamp a terminal state (`acw_skip_reason` + `acw_completed_at`) so rows never look indefinitely pending; the re-run gate is `completed_at AND no skip_reason`, so skip-reason rows stay manually re-runnable and a successful re-run clears the reason.
**Why:** Previously `llm_error` left `acw_completed_at` NULL forever ("pending" UI) — but stamping it also suppresses the incidental auto-retry that later Twilio callbacks used to provide. Recovery from an LLM outage is manual-only by design.
**How to apply:** Any new ACW failure branch must stamp both fields (rollback-guarded); never make the auto-enqueue gate look at skip_reason (that would re-run terminal skips on every callback).

**Also:** Call Logs CSV export contract is strictly additive — new columns append AFTER `Transcript` so existing consumers' column positions never shift. Frontend column-visibility localStorage key is versioned (`_v2`); adding a default-on column requires a key bump + one-time legacy migration.
