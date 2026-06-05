# `backend/scripts/` — Backend-local backfill scripts

## Purpose

One-off backfill / migration scripts that sit alongside the package but are not part of the importable `botelier` namespace. Use these for historical data fixes that don't belong in `botelier/scripts/` (the in-package maintenance jobs).

## Main files

| File | Role |
|---|---|
| `backfill_phantom_caller_spoke.py` | Clears `caller_spoke=TRUE` on calls where `user_first_speech` was actually the bot's own greeting transcribed by Deepgram (pre-Task #110 bug). Guards on absence of `turn_finalized` events to avoid clobbering real caller speech. |
| `reconcile_call_durations.py` | Audits and repairs canonical parent, AI, and transfer durations plus billing items using Twilio REST data or captured provider webhook evidence. |

## How it connects

- Imports `botelier.database.SessionLocal` from the installed package; runs from `backend/` with `python scripts/<name>.py`.
- Reads `call_logs` joined to `call_events` (`event_type='user_first_speech'` and `event_type='turn_finalized'`).

## Conventions

- Default to dry-run; require an explicit flag to apply.
- Document the bug being fixed at the top of the script (see `backfill_phantom_caller_spoke.py:1-25` for the pattern).

## Setup

```
cd botelier/backend
python scripts/backfill_phantom_caller_spoke.py --help
python scripts/reconcile_call_durations.py --help
```

## Gotchas

- These scripts touch historical data; always run against a backup or with an explicit dry-run first.
- Duration reconciliation defaults to dry-run. Apply requires the completed dry-run ID and an exactly matching account/date/call/batch/resume scope:

  ```
  python scripts/reconcile_call_durations.py --account-id <uuid> --from 2026-05-01 --batch-size 100
  python scripts/reconcile_call_durations.py --account-id <uuid> --from 2026-05-01 --batch-size 100 --apply --approved-run-id <dry-run-id>
  ```

- Review `call_duration_reconciliation_runs.summary` and its result rows before applying. Unresolved calls remain unchanged; local timestamps are never substituted for missing provider evidence.
- Once a script has been run in prod, prefer leaving it in place as forensic record rather than deleting it — future audits will want to know what was applied.
