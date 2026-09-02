---
name: complete_call triple-teardown idempotency
description: Three teardown paths fire on every clean call end; the universal terminal guard prevents triple billing/status/leg logic execution.
---

## Rule
`complete_call()` must be idempotent for ALL callers once a call is in a terminal state with `ended_at` set — not just for `forced_by` paths.

## Why
Three paths converge on every clean call end:
1. `/connect-complete` → `save_transcript_for_call` → `_save_call_transcript` → `complete_call`
2. `/connect-complete` → direct `call_logger.complete_call(call_sid)` (line ~937 in api/calls.py)
3. Pipeline teardown → `_save_call_transcript` → `complete_call`

Before the fix, the guard at `call_logger.py` only applied when `forced_by` was set. This let all three execute the full billing/status/leg logic and emit transcript-save attempts on every call.

## How to apply
The guard in `call_logger.complete_call()` now checks `prior_status in _terminal and call_log.ended_at is not None` unconditionally (the `forced_by and` prefix was removed). Any subsequent call after terminal+ended_at is a silent no-op returning True.

The `finalization_forced` event is still correct: it's only emitted after the terminal transition actually fires (the guard returns before event code).

## Test coverage
`tests/test_sweeper_complete_call.py::TestCompleteCallUniversalIdempotency` — 5 tests covering normal-path no-op, ended-early no-op, forced-path no-op, terminal-without-ended-at still finalizes, and in-progress still finalizes.
