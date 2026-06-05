"""Reconcile historical call durations and billing against Twilio.

Examples:
    python scripts/reconcile_call_durations.py --account-id UUID --from 2026-05-01
    python scripts/reconcile_call_durations.py --account-id UUID --from 2026-05-01 \
        --apply --approved-run-id UUID
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from botelier.services.call_duration_reconciliation import CallDurationReconciler


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-id", type=UUID)
    parser.add_argument("--from", dest="date_from", type=_datetime)
    parser.add_argument("--to", dest="date_to", type=_datetime)
    parser.add_argument("--call-sid")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--resume-after")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approved-run-id", type=UUID)
    args = parser.parse_args()

    reconciler = CallDurationReconciler(concurrency=args.concurrency)
    run = reconciler.run(
        mode="apply" if args.apply else "dry_run",
        account_id=args.account_id,
        date_from=args.date_from,
        date_to=args.date_to,
        call_sid=args.call_sid,
        batch_size=args.batch_size,
        resume_after=args.resume_after,
        approved_run_id=args.approved_run_id,
    )
    print(
        json.dumps(
            {
                "run_id": str(run.id),
                "mode": run.mode,
                "status": run.status,
                "summary": run.summary,
                "resume_after": run.resume_after,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
