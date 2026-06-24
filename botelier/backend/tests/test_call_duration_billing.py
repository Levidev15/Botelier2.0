"""Regression coverage for canonical provider/Pipecat duration ownership."""

import uuid
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from botelier.models.billing import AccountBillingConfig, CallBillingItem
from botelier.models.call_log import CallLeg, CallLog, CallStatus, LegType
from botelier.services.call_duration_billing import CallDurationBillingService
from botelier.services.call_duration_reconciliation import (
    CallCandidate,
    CallDurationReconciler,
    _evidence_from_audit,
    _fetch_provider_evidence,
    _normalized_old_values,
    _resolve_item_rate,
)
from botelier.services.call_logger import CallLogger


def _query(first=None, scalar=None):
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.with_for_update.return_value = query
    query.first.return_value = first
    query.scalar.return_value = scalar
    return query


def _call_log(duration=0):
    call = CallLog()
    call.id = uuid.uuid4()
    call.account_id = uuid.uuid4()
    call.call_sid = f"CA{uuid.uuid4().hex}"
    call.duration_seconds = duration
    call.duration_source = "unknown"
    call.estimated_cost_usd = Decimal("0")
    return call


def _transfer_leg(call):
    leg = CallLeg()
    leg.id = uuid.uuid4()
    leg.call_log_id = call.id
    leg.leg_number = 2
    leg.leg_type = LegType.TRANSFER_EXTERNAL.value
    leg.call_sid = f"CA{uuid.uuid4().hex}"
    leg.status = CallStatus.IN_PROGRESS.value
    leg.duration_seconds = 0
    leg.duration_source = "unknown"
    return leg


@pytest.mark.parametrize(
    ("duration_seconds", "expected_minutes"),
    [(1, 1), (59, 1), (60, 1), (61, 2)],
)
def test_parent_duration_updates_transferred_call_and_rounds_provider_minutes(
    duration_seconds,
    expected_minutes,
):
    call = _call_log(duration=240)
    call.has_transfer = True
    config = AccountBillingConfig(
        id=uuid.uuid4(),
        account_id=call.account_id,
        inbound_rate_usd=Decimal("0.05"),
        outbound_rate_usd=Decimal("0.03"),
        voice_rate_model="separate",
        sms_inbound_rate_usd=Decimal("0.01"),
        sms_outbound_rate_usd=Decimal("0.01"),
    )
    db = MagicMock()

    def query(entity):
        if entity is CallBillingItem:
            return _query(first=None)
        if entity is AccountBillingConfig:
            return _query(first=config)
        return _query(scalar=Decimal("0.10"))

    db.query.side_effect = query

    item = CallDurationBillingService(db).finalize_parent(
        call,
        duration_seconds,
        source="twilio_webhook",
    )

    assert call.duration_seconds == duration_seconds
    assert call.duration_source == "twilio_webhook"
    assert item.source_duration_seconds == duration_seconds
    assert item.quantity_minutes == expected_minutes
    assert item.cost_usd == Decimal(expected_minutes) * Decimal("0.05")
    assert item.call_leg_id is None


def test_transfer_duration_is_tied_to_exact_leg_and_does_not_touch_parent():
    call = _call_log(duration=181)
    call.duration_source = "twilio_webhook"
    leg = _transfer_leg(call)
    config = AccountBillingConfig(
        id=uuid.uuid4(),
        account_id=call.account_id,
        inbound_rate_usd=Decimal("0.05"),
        outbound_rate_usd=Decimal("0.03"),
        voice_rate_model="separate",
        sms_inbound_rate_usd=Decimal("0.01"),
        sms_outbound_rate_usd=Decimal("0.01"),
    )
    db = MagicMock()

    def query(entity):
        if entity is CallBillingItem:
            return _query(first=None)
        if entity is AccountBillingConfig:
            return _query(first=config)
        return _query(scalar=Decimal("0.06"))

    db.query.side_effect = query

    item = CallDurationBillingService(db).finalize_transfer_leg(
        call,
        leg,
        60,
        source="twilio_webhook",
    )

    assert call.duration_seconds == 181
    assert call.duration_source == "twilio_webhook"
    assert leg.duration_seconds == 60
    assert leg.duration_source == "twilio_webhook"
    assert item.call_leg_id == leg.id
    assert item.quantity_minutes == 1
    assert item.cost_usd == Decimal("0.03")


def test_parent_terminal_callback_is_authoritative_even_after_transfer():
    call = _call_log(duration=999)
    call.has_transfer = True
    call.status = CallStatus.IN_PROGRESS.value
    ai_leg = CallLeg(
        id=uuid.uuid4(),
        call_log_id=call.id,
        leg_number=1,
        leg_type=LegType.AI_CONVERSATION.value,
        call_sid=call.call_sid,
        status=CallStatus.COMPLETED.value,
        duration_seconds=40,
        duration_source="pipecat",
    )
    db = MagicMock()
    call_query = _query(first=call)
    leg_query = _query(first=ai_leg)
    db.query.side_effect = lambda entity: call_query if entity is CallLog else leg_query

    with patch.object(CallLogger, "_upsert_inbound_billing") as upsert:
        assert CallLogger(db).update_status(call.call_sid, "completed", 83)

    upsert.assert_called_once_with(call, 83, source="twilio_webhook")
    assert ai_leg.duration_seconds == 40
    assert ai_leg.duration_source == "pipecat"


def test_unanswered_transfer_is_zero_billed_without_overwriting_parent_duration():
    call = _call_log(duration=75)
    call.duration_source = "twilio_webhook"
    leg = _transfer_leg(call)
    db = MagicMock()
    leg_query = _query(first=leg)
    call_query = _query(first=call)
    db.query.side_effect = lambda entity: leg_query if entity is CallLeg else call_query

    with patch.object(CallLogger, "_write_transfer_billing") as write_transfer:
        assert CallLogger(db).update_leg_status(
            leg.call_sid,
            "no-answer",
            duration_seconds=None,
            parent_call_sid=call.call_sid,
        )

    assert leg.duration_seconds == 0
    assert leg.duration_source == "twilio_webhook"
    assert call.duration_seconds == 75
    write_transfer.assert_called_once_with(call, leg)


def test_reconciliation_uses_webhook_evidence_when_rest_is_unavailable():
    candidate = CallCandidate(
        call_log_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        call_sid="CAparent",
        account_sid="ACsub",
        auth_token="secret",
        child_sids=("CAchild",),
        parent_event_duration=83,
        child_event_durations={"CAchild": 41},
    )

    with patch(
        "botelier.services.call_duration_reconciliation.BotelierTwilioClient",
        side_effect=RuntimeError("network unavailable"),
    ):
        evidence = _fetch_provider_evidence(candidate)

    assert evidence.complete
    assert evidence.parent_duration == 83
    assert evidence.parent_source == "twilio_webhook"
    assert evidence.child_durations == {"CAchild": 41}
    assert evidence.child_sources == {"CAchild": "twilio_webhook"}
    assert evidence.warnings == ("parent REST fetch failed: RuntimeError",)


def test_reconciliation_rejects_child_from_different_parent():
    parent = SimpleNamespace(duration="83")
    child = SimpleNamespace(duration="41", parent_call_sid="CAother")
    calls = MagicMock()
    calls.side_effect = lambda sid: SimpleNamespace(fetch=lambda: parent if sid == "CAparent" else child)
    twilio = SimpleNamespace(client=SimpleNamespace(calls=calls))
    candidate = CallCandidate(
        call_log_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        call_sid="CAparent",
        account_sid="ACsub",
        auth_token="secret",
        child_sids=("CAchild",),
        parent_event_duration=None,
        child_event_durations={},
    )

    with patch(
        "botelier.services.call_duration_reconciliation.BotelierTwilioClient",
        return_value=twilio,
    ):
        evidence = _fetch_provider_evidence(candidate)

    assert not evidence.complete
    assert any("parent mismatch" in error for error in evidence.errors)


def test_approved_evidence_round_trips_without_refetching_provider():
    evidence = _evidence_from_audit(
        {
            "parent_duration": 83,
            "parent_source": "twilio_api",
            "child_durations": {"CAchild": 41},
            "child_sources": {"CAchild": "twilio_api"},
            "errors": [],
            "warnings": ["provider fallback used"],
        }
    )

    assert evidence.complete
    assert evidence.parent_duration == 83
    assert evidence.child_durations == {"CAchild": 41}
    assert evidence.warnings == ("provider fallback used",)


def test_reconciliation_records_missing_credentials_but_accepts_event_evidence():
    candidate = CallCandidate(
        call_log_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        call_sid="CAparent",
        account_sid=None,
        auth_token=None,
        child_sids=("CAchild",),
        parent_event_duration=83,
        child_event_durations={"CAchild": 41},
    )

    evidence = _fetch_provider_evidence(candidate)

    assert evidence.complete
    assert evidence.warnings == ("Twilio subaccount credentials unavailable",)


def test_combined_transfer_rate_is_converted_to_outbound_only():
    config = AccountBillingConfig(
        inbound_rate_usd=Decimal("0.05"),
        outbound_rate_usd=Decimal("0.08"),
        voice_rate_model="combined",
    )

    assert _resolve_item_rate(
        item=None,
        config=config,
        inbound_rate=Decimal("0.05"),
        is_transfer=True,
    ) == Decimal("0.03")


def test_apply_requires_an_approved_dry_run():
    with pytest.raises(ValueError, match="approved-run-id"):
        CallDurationReconciler().run(mode="apply")


def test_call_api_hides_non_authoritative_legacy_duration():
    call = _call_log(duration=240)
    call.legs = []

    assert call.to_dict(include_legs=True)["duration_seconds"] == 0

    call.duration_source = "twilio_api"
    assert call.to_dict(include_legs=True)["duration_seconds"] == 240


def test_default_transfer_rate_is_outbound_only():
    assert CallDurationBillingService.DEFAULT_OUTBOUND_RATE == Decimal("0.03")


def test_approved_state_comparison_is_order_independent():
    left = {
        "duration_seconds": 83,
        "duration_source": "twilio_api",
        "estimated_cost_usd": 0.1,
        "legs": [
            {"id": "2", "duration_seconds": 41},
            {"id": "1", "duration_seconds": 40},
        ],
        "billing_items": [
            {"id": "b", "quantity_minutes": 1, "cost_usd": 0.03},
            {"id": "a", "quantity_minutes": 2, "cost_usd": 0.1},
        ],
    }
    right = {
        **left,
        "legs": list(reversed(left["legs"])),
        "billing_items": list(reversed(left["billing_items"])),
    }

    assert _normalized_old_values(left) == _normalized_old_values(right)


def _ai_leg(call, *, ended_at=None, started_at=None, duration_seconds=0, duration_source="unknown"):
    leg = CallLeg()
    leg.id = uuid.uuid4()
    leg.call_log_id = call.id
    leg.leg_number = 1
    leg.leg_type = LegType.AI_CONVERSATION.value
    leg.call_sid = call.call_sid
    leg.status = CallStatus.IN_PROGRESS.value
    leg.started_at = started_at
    leg.ended_at = ended_at
    leg.duration_seconds = duration_seconds
    leg.duration_source = duration_source
    return leg


def test_ensure_ai_leg_duration_recovers_pipecat_span_from_timestamps():
    """A transferred call whose pipeline never reported a pipecat duration must
    recover the caller's AI-only time from ``answered_at -> ai_leg.ended_at`` —
    the later parent call-end (transfer hangup) is deliberately ignored so the
    transfer span is not folded into the AI duration."""
    call = _call_log(duration=0)
    call.has_transfer = True
    call.answered_at = datetime(2026, 6, 24, 10, 0, 0)
    call.ended_at = datetime(2026, 6, 24, 10, 5, 0)
    ai_leg = _ai_leg(
        call,
        ended_at=datetime(2026, 6, 24, 10, 0, 47),
        duration_seconds=0,
        duration_source="unknown",
    )

    CallLogger(MagicMock())._ensure_ai_leg_duration(call, ai_leg)

    assert ai_leg.duration_seconds == 47
    assert ai_leg.duration_source == "pipecat"
    assert call.duration_seconds == 0


def test_ensure_ai_leg_duration_never_overwrites_existing_pipecat():
    """Recovery is idempotent: a real pipecat measurement always wins."""
    call = _call_log(duration=0)
    call.answered_at = datetime(2026, 6, 24, 10, 0, 0)
    ai_leg = _ai_leg(
        call,
        ended_at=datetime(2026, 6, 24, 10, 10, 0),
        duration_seconds=40,
        duration_source="pipecat",
    )

    CallLogger(MagicMock())._ensure_ai_leg_duration(call, ai_leg)

    assert ai_leg.duration_seconds == 40
    assert ai_leg.duration_source == "pipecat"


def test_ensure_ai_leg_duration_skips_when_call_never_answered():
    """No fabricated duration when the call was never answered."""
    call = _call_log(duration=0)
    call.answered_at = None
    call.ended_at = datetime(2026, 6, 24, 10, 5, 0)
    ai_leg = _ai_leg(
        call,
        started_at=datetime(2026, 6, 24, 10, 0, 0),
        ended_at=datetime(2026, 6, 24, 10, 5, 0),
        duration_seconds=0,
        duration_source="unknown",
    )

    CallLogger(MagicMock())._ensure_ai_leg_duration(call, ai_leg)

    assert ai_leg.duration_seconds == 0
    assert ai_leg.duration_source == "unknown"


def test_update_status_recovers_ai_duration_when_terminal_webhook_finalized_first():
    """Documented bug: when the terminal Twilio webhook arrives before the
    pipeline finalizes its leg, the AI leg already has ``ended_at`` but no
    pipecat duration. ``update_status`` must recover the caller's AI time so a
    transferred call never shows 0:00, while the parent (billing) total stays
    owned by the Twilio webhook and is never touched by AI-leg recovery."""
    call = _call_log(duration=0)
    call.has_transfer = True
    call.status = CallStatus.IN_PROGRESS.value
    call.answered_at = datetime(2026, 6, 24, 10, 0, 0)
    ai_leg = _ai_leg(
        call,
        ended_at=datetime(2026, 6, 24, 10, 1, 23),
        duration_seconds=0,
        duration_source="unknown",
    )
    db = MagicMock()
    call_query = _query(first=call)
    leg_query = _query(first=ai_leg)
    db.query.side_effect = lambda entity: call_query if entity is CallLog else leg_query

    with patch.object(CallLogger, "_upsert_inbound_billing") as upsert:
        assert CallLogger(db).update_status(call.call_sid, "completed", 300)

    upsert.assert_called_once_with(call, 300, source="twilio_webhook")
    assert ai_leg.duration_seconds == 83
    assert ai_leg.duration_source == "pipecat"
    assert call.duration_seconds == 0
