# `backend/scripts/` — Backend-local backfill scripts

## Purpose

One-off backfill / migration scripts that sit alongside the package but are not part of the importable `botelier` namespace. Use these for historical data fixes that don't belong in `botelier/scripts/` (the in-package maintenance jobs).

## Main files

| File | Role |
|---|---|
| `backfill_phantom_caller_spoke.py` | Clears `caller_spoke=TRUE` on calls where `user_first_speech` was actually the bot's own greeting transcribed by Deepgram (pre-Task #110 bug). Guards on absence of `turn_finalized` events to avoid clobbering real caller speech. |

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
```

## Gotchas

- These scripts touch historical data; always run against a backup or with an explicit dry-run first.
- Once a script has been run in prod, prefer leaving it in place as forensic record rather than deleting it — future audits will want to know what was applied.
