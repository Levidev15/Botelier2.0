---
name: ACW advisory lock
description: Why run_acw_in_thread uses pg_try_advisory_lock instead of a read-before-write check.
---

## The rule
`run_acw_in_thread` acquires a Postgres session-level advisory lock
(`pg_try_advisory_lock(int8)`) keyed on a sha256-derived 31-bit integer of the
`call_log_id` before touching the row. If the lock is not acquired it logs and
returns `{"skipped": True, "reason": "concurrent_run"}` immediately.

## Why
The previous guard was `if call_log.acw_completed_at and not call_log.acw_skip_reason`.
This is a TOCTOU race: `connect_complete` and `status_callback` paths arrive within
milliseconds of each other, both read `None`, and both proceed to run a full ACW
pass — including duplicate QA calls and double-stamping `acw_completed_at`.
Confirmed on the production call: both triggers completed with `skip_reason=none`
within 565 ms of each other.

## How to apply
- Lock key: `int(hashlib.sha256(str(call_log_id).encode()).hexdigest()[:16], 16) % (2**31)`
- Lock type: session-level (`pg_try_advisory_lock` / `pg_advisory_unlock` in finally).
- The Task #397 "already completed" check is preserved AFTER the lock is acquired
  as defense-in-depth. Do not remove it.
- Idempotent on unlock failure (pg_advisory_unlock is a no-op if lock was never held).
