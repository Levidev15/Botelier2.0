"""Regression tests for call-logs export & list timezone support.

Guards two contracts:

  1. /api/call-logs/export with tz=<IANA zone>
       - Date/Time (Local) column renders in the selected zone.
       - date_from / date_to are treated as wall-clock midnights in that zone
         (not UTC), so "yesterday in Pacific" exports Pacific-day rows.

  2. /api/call-logs (list) with tz=<IANA zone>
       - Same wall-clock boundary semantics as the export, so the on-screen
         table and the downloaded CSV always return the same row set.

  3. Without tz: existing UTC-boundary behaviour is unchanged.

Isolation strategy mirrors test_analytics_overview_duration.py: a throwaway
Account is created, every fixture row is tagged with its account_id, and
teardown deletes unconditionally so the suite runs against the live dev DB
without touching real data.

Scenario
--------
Two calls straddle a Pacific midnight:

  A = 2026-06-15 01:00 UTC  →  2026-06-14 18:00 PDT  (Pacific June 14)
  B = 2026-06-15 10:00 UTC  →  2026-06-15 03:00 PDT  (Pacific June 15)

Filter: date_from=2026-06-15T00:00:00, date_to=2026-06-16T00:00:00

  UTC interpretation  → both A and B lie within [06-15 00:00 UTC, 06-16 00:00 UTC)
  PDT interpretation  → only B lies within   [06-15 07:00 UTC, 06-16 07:00 UTC)
"""

import csv
import io
import os
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

if not os.environ.get("DATABASE_URL"):
    raise RuntimeError(
        "test_call_logs_export_tz requires DATABASE_URL to be set. "
        "These tests guard the Call Logs timezone contract and must not "
        "be silently skipped — point DATABASE_URL at a test or dev database."
    )

from botelier.api import call_logs as call_logs_api
from botelier.database import SessionLocal
from botelier.models import CallLog, CallStatus
from botelier.models.account import Account, AccountStatus, SubscriptionTier


# ── Constants ─────────────────────────────────────────────────────────────────

# Call A: 01:00 UTC on 2026-06-15 = June 14 in PDT (UTC-7)
CALL_A_UTC = datetime(2026, 6, 15, 1, 0, 0)

# Call B: 10:00 UTC on 2026-06-15 = June 15 03:00 in PDT (UTC-7)
CALL_B_UTC = datetime(2026, 6, 15, 10, 0, 0)

# Wall-clock filter sent by the browser as "June 15 midnight"
FILTER_FROM = datetime(2026, 6, 15, 0, 0, 0)
FILTER_TO   = datetime(2026, 6, 16, 0, 0, 0)

TZ_PACIFIC = "America/Los_Angeles"


# ── Fixture ───────────────────────────────────────────────────────────────────

def _make_account(db) -> Account:
    suffix = uuid.uuid4().hex[:12]
    acct = Account(
        name=f"tz-test-{suffix}",
        slug=f"tz-test-{suffix}",
        email=f"tz-test-{suffix}@example.invalid",
        status=AccountStatus.ACTIVE,
        subscription_tier=SubscriptionTier.FREE,
    )
    db.add(acct)
    db.flush()
    return acct


@pytest.fixture(scope="module")
def account_with_calls():
    db = SessionLocal()
    acct = _make_account(db)
    try:
        db.add(CallLog(
            account_id=acct.id,
            call_sid=f"TZ-TEST-A-{uuid.uuid4().hex}",
            status=CallStatus.COMPLETED.value,
            started_at=CALL_A_UTC,
            caller_number="+15550000001",
            duration_seconds=30,
        ))
        db.add(CallLog(
            account_id=acct.id,
            call_sid=f"TZ-TEST-B-{uuid.uuid4().hex}",
            status=CallStatus.COMPLETED.value,
            started_at=CALL_B_UTC,
            caller_number="+15550000002",
            duration_seconds=60,
        ))
        db.commit()
        yield acct.id
    finally:
        db.query(CallLog).filter(CallLog.account_id == acct.id).delete()
        db.query(Account).filter(Account.id == acct.id).delete()
        db.commit()
        db.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _run_export(account_id, *, date_from=None, date_to=None, tz=None):
    """Invoke export_call_logs directly with auth bypassed; return parsed CSV rows."""
    db = SessionLocal()
    try:
        with (
            patch.object(call_logs_api, "check_account_permission"),
            patch.object(call_logs_api, "_can_view_transcripts", return_value=False),
        ):
            resp = await call_logs_api.export_call_logs(
                account_id=account_id,
                status=None,
                assistant_id=None,
                assistant_ids=None,
                date_from=date_from,
                date_to=date_to,
                bucket=None,
                disposition_id=None,
                caller_spoke=None,
                tz=tz,
                db=db,
                user=MagicMock(),
            )
        body = "".join([chunk async for chunk in resp.body_iterator])
        return list(csv.DictReader(io.StringIO(body)))
    finally:
        db.close()


async def _run_list(account_id, *, date_from=None, date_to=None, tz=None):
    """Invoke get_call_logs directly with auth bypassed; return the result dict."""
    db = SessionLocal()
    try:
        with patch.object(call_logs_api, "check_account_permission"):
            result = await call_logs_api.get_call_logs(
                account_id=account_id,
                status=None,
                assistant_id=None,
                phone_number_id=None,
                date_from=date_from,
                date_to=date_to,
                tz=tz,
                search=None,
                has_transfer=None,
                disposition_id=None,
                acw_resolution=None,
                acw_completed=None,
                quality_min=None,
                quality_max=None,
                hour=None,
                bucket=None,
                page=1,
                limit=100,
                db=db,
                user=MagicMock(),
            )
        return result
    finally:
        db.close()


# ── Export tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_without_tz_includes_both_utc_day_calls(account_with_calls):
    """Without tz, boundaries are UTC — both calls on 2026-06-15 UTC are returned."""
    rows = await _run_export(
        account_with_calls,
        date_from=FILTER_FROM,
        date_to=FILTER_TO,
        tz=None,
    )
    assert len(rows) == 2, f"Expected 2 rows (UTC filter); got {len(rows)}"
    # No Date/Time (UTC) companion column without tz.
    assert "Date/Time (UTC)" not in (rows[0] if rows else {}), (
        "Date/Time (UTC) companion column must be absent when tz is not provided"
    )


@pytest.mark.asyncio
async def test_export_with_pacific_tz_excludes_utc_june14_call(account_with_calls):
    """With tz=America/Los_Angeles, Call A (01:00 UTC = June 14 PDT) is excluded."""
    rows = await _run_export(
        account_with_calls,
        date_from=FILTER_FROM,
        date_to=FILTER_TO,
        tz=TZ_PACIFIC,
    )
    assert len(rows) == 1, (
        f"Expected 1 row (Pacific June-15 filter); got {len(rows)}. "
        "Call A (01:00 UTC = Pacific June 14) must be excluded."
    )


@pytest.mark.asyncio
async def test_export_with_tz_adds_utc_companion_column(account_with_calls):
    """When tz is supplied the CSV must have both Date/Time (Local) and Date/Time (UTC)."""
    rows = await _run_export(
        account_with_calls,
        date_from=FILTER_FROM,
        date_to=FILTER_TO,
        tz=TZ_PACIFIC,
    )
    assert len(rows) == 1
    assert "Date/Time (UTC)" in rows[0], (
        "Date/Time (UTC) companion column must be present when tz is supplied"
    )
    assert "Date/Time (Local)" in rows[0], (
        "Date/Time (Local) column must be present when tz is supplied"
    )


@pytest.mark.asyncio
async def test_export_local_timestamp_renders_pacific_time(account_with_calls):
    """Call B (10:00 UTC) must appear as 03:00 in PDT (UTC-7 during June)."""
    rows = await _run_export(
        account_with_calls,
        date_from=FILTER_FROM,
        date_to=FILTER_TO,
        tz=TZ_PACIFIC,
    )
    assert len(rows) == 1
    local_dt = rows[0]["Date/Time (Local)"]
    # 10:00 UTC - 7h = 03:00 PDT; header format: "YYYY-MM-DD HH:MM:SS <tz>"
    assert "2026-06-15 03:00:00" in local_dt, (
        f"Expected '2026-06-15 03:00:00' in local timestamp; got {local_dt!r}"
    )
    assert TZ_PACIFIC in local_dt, (
        f"Expected timezone name in local timestamp; got {local_dt!r}"
    )


# ── List endpoint tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_without_tz_includes_both_utc_day_calls(account_with_calls):
    """Without tz, the list endpoint returns both calls on 2026-06-15 UTC."""
    result = await _run_list(
        account_with_calls,
        date_from=FILTER_FROM,
        date_to=FILTER_TO,
        tz=None,
    )
    assert result["total"] == 2, f"Expected 2 calls (UTC filter); got {result['total']}"


@pytest.mark.asyncio
async def test_list_with_pacific_tz_excludes_utc_june14_call(account_with_calls):
    """With tz=America/Los_Angeles, only Call B (Pacific June 15) is returned."""
    result = await _run_list(
        account_with_calls,
        date_from=FILTER_FROM,
        date_to=FILTER_TO,
        tz=TZ_PACIFIC,
    )
    assert result["total"] == 1, (
        f"Expected 1 call (Pacific June-15 filter); got {result['total']}. "
        "Call A (01:00 UTC = Pacific June 14) must be excluded."
    )


@pytest.mark.asyncio
async def test_list_and_export_agree_on_same_tz_filter(account_with_calls):
    """List and export must return the same row count for an identical tz filter."""
    list_result = await _run_list(
        account_with_calls,
        date_from=FILTER_FROM,
        date_to=FILTER_TO,
        tz=TZ_PACIFIC,
    )
    export_rows = await _run_export(
        account_with_calls,
        date_from=FILTER_FROM,
        date_to=FILTER_TO,
        tz=TZ_PACIFIC,
    )
    assert list_result["total"] == len(export_rows), (
        f"List returned {list_result['total']} rows but export returned "
        f"{len(export_rows)} rows for the same tz filter — they must agree."
    )
