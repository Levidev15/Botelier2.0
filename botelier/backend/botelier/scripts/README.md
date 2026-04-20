# `botelier/scripts/` — Maintenance jobs (in-package)

## Purpose

Admin / cleanup jobs runnable as Python modules within the `botelier` package. Different from `backend/scripts/` (one level up), which holds repo-local backfill scripts that aren't part of the importable package.

## Main files

| File | Role |
|---|---|
| `cleanup_duplicate_legs.py` | Removes duplicate transfer legs from historical `call_logs`. Has `--dry-run` (default) and `--execute` modes. |

## How it connects

- Imports `botelier.database.SessionLocal` and `botelier.models.call_log.*`.
- Read-only by default (`--dry-run`); destructive only with `--execute`.

## Conventions

- All scripts default to dry-run.
- Prefix log lines with `loguru` (not `print`) so output flows through the centralised sinks.

## Setup

Run from `backend/`:

```
python -m botelier.scripts.cleanup_duplicate_legs            # dry-run
python -m botelier.scripts.cleanup_duplicate_legs --execute  # apply
```

## Gotchas

- Never re-run a script with `--execute` without a fresh dry-run on current data — the row set may have changed.
