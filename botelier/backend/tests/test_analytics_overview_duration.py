"""Analytics overview Duration semantics regression tests.

These lock in the contract that the Call Analytics *overview* aggregates
report the caller's AI-conversation time (summed from `ai_conversation`
legs whose `duration_source == "pipecat"`), NOT the Twilio parent
`CallLog.duration_seconds`. They guard two regressions:

  * The legacy keys `avg_duration_seconds` / `total_duration_seconds` must
    equal the explicit AI keys (`avg_ai_duration_seconds` /
    `total_ai_duration_seconds`) so every dashboard surface shows the same
    number. They used to be sourced from a Twilio-only parent-duration sum.
  * Cold-transfer calls — whose *parent* `duration_source` is NOT a Twilio
    source — must still contribute their AI leg to the totals. The old
    parent-duration filter silently dropped them.

Transfer (outbound) time is reported separately via
`total_outbound_duration_seconds` and must never be folded into the AI total.

Isolation strategy mirrors test_analytics_partition.py: a throwaway Account
is created, every fixture row is tagged with its account_id, and teardown
deletes unconditionally, so the suite runs against the live development
PostgreSQL database without colliding with real data.
"""

import os
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

if not os.environ.get("DATABASE_URL"):
    raise RuntimeError(
        "test_analytics_overview_duration requires DATABASE_URL to be set. "
        "These tests guard the Call Analytics Duration contract and must not "
        "be silently skipped — point DATABASE_URL at a test database."
    )

from botelier.api import analytics as analytics_api
from botelier.database import SessionLocal
from botelier.models import CallLog, CallStatus
from botelier.models.call_log import CallLeg
from botelier.models.account import Account, AccountStatus, SubscriptionTier


def _make_account(db) -> Account:
    suffix = uuid.uuid4().hex[:12]
    acct = Account(
        name=f"ovr-dur-test-{suffix}",
        slug=f"ovr-dur-test-{suffix}",
        email=f"ovr-dur-test-{suffix}@example.invalid",
        status=AccountStatus.ACTIVE,
        subscription_tier=SubscriptionTier.FREE,
    )
    db.add(acct)
    db.flush()
    return acct


def _make_call(db, account_id, *, has_transfer, parent_source, parent_duration):
    log = CallLog(
        account_id=account_id,
        call_sid=f"TEST-{uuid.uuid4().hex}",
        status=CallStatus.COMPLETED.value,
        ai_greeting_completed=True,
        caller_spoke=True,
        started_at=datetime.utcnow(),
        has_transfer=has_transfer,
        duration_seconds=parent_duration,
        duration_source=parent_source,
    )
    db.add(log)
    db.flush()
    return log


def _add_leg(db, call_log_id, *, leg_number, leg_type, duration, source):
    db.add(
        CallLeg(
            call_log_id=call_log_id,
            leg_number=leg_number,
            leg_type=leg_type,
            status=CallStatus.COMPLETED.value,
            started_at=datetime.utcnow(),
            ended_at=datetime.utcnow(),
            duration_seconds=duration,
            duration_source=source,
        )
    )


# AI-leg durations per call (the values the overview must report).
AI_NORMAL = 60
AI_WARM = 80
AI_COLD = 50
TOTAL_AI = AI_NORMAL + AI_WARM + AI_COLD  # 190
AI_CALLS = 3

# Transfer-leg durations (reported separately, never in the AI total).
XFER_WARM = 120
XFER_COLD = 30
TOTAL_XFER = XFER_WARM + XFER_COLD  # 150


@pytest.fixture(scope="module")
def populated_account():
    """Three completed calls under a fresh account:

      A normal AI call (no transfer, pipecat AI leg).
      A warm transfer (Twilio parent source; AI leg + Twilio transfer leg).
      A cold transfer whose PARENT source is pipecat — the case the old
        Twilio-only parent-duration filter dropped — with an AI leg and a
        Twilio transfer_cold leg.
    """
    db = SessionLocal()
    acct = _make_account(db)
    try:
        a = _make_call(
            db, acct.id, has_transfer=False, parent_source="pipecat", parent_duration=AI_NORMAL
        )
        _add_leg(db, a.id, leg_number=1, leg_type="ai_conversation", duration=AI_NORMAL, source="pipecat")

        b = _make_call(
            db,
            acct.id,
            has_transfer=True,
            parent_source="twilio_webhook",
            parent_duration=AI_WARM + XFER_WARM,
        )
        _add_leg(db, b.id, leg_number=1, leg_type="ai_conversation", duration=AI_WARM, source="pipecat")
        _add_leg(
            db, b.id, leg_number=2, leg_type="transfer_external", duration=XFER_WARM, source="twilio_webhook"
        )

        # Cold transfer: parent duration_source is pipecat (NOT a Twilio
        # source), which the old overview parent-duration sum excluded.
        c = _make_call(
            db, acct.id, has_transfer=True, parent_source="pipecat", parent_duration=AI_COLD
        )
        _add_leg(db, c.id, leg_number=1, leg_type="ai_conversation", duration=AI_COLD, source="pipecat")
        _add_leg(
            db, c.id, leg_number=2, leg_type="transfer_cold", duration=XFER_COLD, source="twilio_api"
        )

        db.commit()
        yield acct.id
    finally:
        ids = [r.id for r in db.query(CallLog.id).filter(CallLog.account_id == acct.id).all()]
        if ids:
            db.query(CallLeg).filter(CallLeg.call_log_id.in_(ids)).delete(synchronize_session=False)
        db.query(CallLog).filter(CallLog.account_id == acct.id).delete()
        db.query(Account).filter(Account.id == acct.id).delete()
        db.commit()
        db.close()


async def _fetch_overview(account_id):
    db = SessionLocal()
    try:
        with patch.object(analytics_api, "check_account_permission"):
            # Sync endpoint (runs in Starlette's threadpool in production so
            # heavy SQL never blocks the live-call event loop) — call directly.
            result = analytics_api.get_call_analytics(
                account_id=account_id,
                date_from=None,
                date_to=None,
                assistant_ids=None,
                timezone="UTC",
                db=db,
                user=MagicMock(),
            )
        return result["overview"]
    finally:
        db.close()


@pytest.mark.asyncio
async def test_overview_duration_is_ai_leg_time_including_cold_transfers(populated_account):
    overview = await _fetch_overview(populated_account)

    # Total/avg Duration come from the AI legs across ALL three calls —
    # including the cold transfer whose parent source is pipecat.
    assert overview["total_ai_duration_seconds"] == TOTAL_AI
    assert overview["avg_ai_duration_seconds"] == round(TOTAL_AI / AI_CALLS, 1)

    # Transfer time is reported separately and is NOT in the AI total.
    assert overview["total_outbound_duration_seconds"] == TOTAL_XFER
    assert overview["total_ai_duration_seconds"] != TOTAL_AI + TOTAL_XFER


@pytest.mark.asyncio
async def test_overview_legacy_duration_keys_alias_ai_keys(populated_account):
    """Legacy keys must equal the AI keys so the table, overview, drilldown,
    CSV and the /stats card all show the same Duration definition — and must
    NOT equal the Twilio-only parent-duration sum the old code produced."""
    overview = await _fetch_overview(populated_account)

    assert overview["total_duration_seconds"] == overview["total_ai_duration_seconds"]
    assert overview["avg_duration_seconds"] == overview["avg_ai_duration_seconds"]

    # Old behavior summed CallLog.duration_seconds WHERE duration_source IN
    # (twilio_webhook, twilio_api) — that would be only the warm transfer's
    # parent total (AI_WARM + XFER_WARM), excluding the pipecat-parented
    # normal and cold-transfer calls. The new total must differ from that.
    old_twilio_parent_sum = AI_WARM + XFER_WARM
    assert overview["total_duration_seconds"] != old_twilio_parent_sum
