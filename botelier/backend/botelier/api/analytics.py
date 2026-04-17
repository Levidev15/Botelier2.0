"""
Analytics API — rich aggregated metrics for Call Analytics dashboard.

GET /api/analytics/calls            — All call metrics in one response.
GET /api/analytics/calls/drilldown  — Paginated call records for a given metric slice.
"""

from datetime import datetime, timedelta
from typing import Optional, List
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy import desc, func, case
from sqlalchemy.orm import Session, joinedload

from botelier.database import get_db
from botelier.models import CallLog, CallLeg, CallStatus, Assistant, AssistantDisposition, PhoneNumber
from botelier.models.user import User
from botelier.auth.middleware import get_current_user, check_account_permission

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

_DRILLDOWN_PAGE_LIMIT = 50


_MAX_RANGE_DAYS = 365


# Task #97 partition — mutually exclusive and exhaustive over every
# (CallStatus × {True, False}) pair. Buckets per spec:
#   ai_handled  : greeted=True AND status IN (completed, in_progress, ringing).
#                 Defensive: (ended_early, greeted=True) also routes here
#                 (edge case #4 — forbidden shape, absorb into ai_handled).
#   ended_early : greeted=False AND status = ended_early.
#   missed      : status IN (no_answer, busy, canceled).
#   failed      : status = failed.
#   unresolved  : gap / catch-all bucket — the spec's canonical placement for
#                 (a) greeted=False AND status IN (initiated, ringing,
#                 in_progress), and (b) "any new enum member added in the
#                 future, until explicitly classified" (spec scope #1). Also
#                 absorbs the two anomalous shapes (completed, greeted=False)
#                 and (initiated, greeted=True) so the partition stays MECE
#                 and partition_integrity_ok is a pure reconciliation check
#                 (sum(buckets) == total_calls), not an anomaly sentinel.
# Classifier and predicate share this contract so overview and drilldown
# can never drift.
_PARTITION_BUCKETS = ("ai_handled", "ended_early", "missed", "failed", "unresolved")
_MISSED_STATUSES = (
    CallStatus.NO_ANSWER.value,
    CallStatus.BUSY.value,
    CallStatus.CANCELED.value,
)
_AI_GREETED_STATUSES = (
    CallStatus.COMPLETED.value,
    CallStatus.IN_PROGRESS.value,
    CallStatus.RINGING.value,
)


def _classify_partition(
    status: str,
    ai_greeting_completed: bool,
    caller_spoke: Optional[bool] = None,
) -> str:
    """
    Pure classifier — returns exactly one bucket for every
    (status, greeted, caller_spoke) triple.

    Task #98: a row that *would* be ai_handled (greeted=TRUE on a non-terminal
    or completed/ended_early status) is reclassified into ``unresolved`` if
    ``caller_spoke is False`` — the AI greeted into a silent line and the
    caller never produced any audio. ``caller_spoke is None`` (legacy rows
    pre-dating this column) is treated as TRUE so historical metrics do not
    silently shift.
    """
    if status == CallStatus.FAILED.value:
        return "failed"
    if status in _MISSED_STATUSES:
        return "missed"
    silent = caller_spoke is False  # explicit FALSE only (NULL → ignore)
    if status == CallStatus.ENDED_EARLY.value:
        if ai_greeting_completed and not silent:
            return "ai_handled"
        # Either greeted=False (canonical ended_early) OR greeted=True but the
        # caller never spoke (silent line) → fold into unresolved/ended_early.
        if not ai_greeting_completed:
            return "ended_early"
        return "unresolved"  # greeted=True + silent caller
    if ai_greeting_completed and status in _AI_GREETED_STATUSES:
        return "unresolved" if silent else "ai_handled"
    # Everything else → unresolved (spec scope #1 catch-all):
    #   (initiated/ringing/in_progress, greeted=False) — gap bucket;
    #   (initiated, greeted=True) + (completed, greeted=False) — anomalies;
    #   any unknown/future CallStatus value — until explicitly classified.
    return "unresolved"


# Task #98 — predicate for "definitely silent": caller_spoke IS FALSE.
# NULL is intentionally treated as "assume spoke" (legacy rows).
_CALLER_SILENT = CallLog.caller_spoke.is_(False)
_CALLER_NOT_SILENT = ~CallLog.caller_spoke.is_(False)  # TRUE or NULL


def _bucket_predicate(bucket: str):
    """SQLAlchemy predicate mirroring `_classify_partition` — single source of truth."""
    if bucket == "failed":
        return CallLog.status == CallStatus.FAILED.value
    if bucket == "missed":
        return CallLog.status.in_(_MISSED_STATUSES)
    if bucket == "ai_handled":
        # Task #98 — exclude rows where the caller demonstrably never spoke.
        return (
            (CallLog.ai_greeting_completed == True)  # noqa: E712
            & CallLog.status.in_(_AI_GREETED_STATUSES + (CallStatus.ENDED_EARLY.value,))
            & _CALLER_NOT_SILENT
        )
    if bucket == "ended_early":
        return (
            (CallLog.status == CallStatus.ENDED_EARLY.value)
            & (CallLog.ai_greeting_completed == False)  # noqa: E712
        )
    if bucket == "unresolved":
        # Complement of the other four buckets — everything not already
        # claimed falls here. Expressed as a NOT-OR to mirror the classifier's
        # catch-all semantics exactly (spec scope #1). Picks up both the
        # legacy gap-row case and the new (greeted=True, caller_spoke=FALSE)
        # silent-caller case rejected above.
        other = (
            _bucket_predicate("failed")
            | _bucket_predicate("missed")
            | _bucket_predicate("ai_handled")
            | _bucket_predicate("ended_early")
        )
        return ~other
    raise ValueError(f"Unknown partition bucket: {bucket}")


# Task #98 — sub-category predicates for the Unresolved StatCard tooltip
# breakdown. Each predicate is evaluated against the same date+account window
# as the overview query and is a strict subset of `_bucket_predicate("unresolved")`.
def _unresolved_subbucket_predicates() -> dict:
    silent_caller = (
        (CallLog.ai_greeting_completed == True)  # noqa: E712
        & CallLog.status.in_(_AI_GREETED_STATUSES + (CallStatus.ENDED_EARLY.value,))
        & _CALLER_SILENT
    )
    non_terminal_gap = (
        CallLog.status.in_(
            (CallStatus.INITIATED.value, CallStatus.RINGING.value, CallStatus.IN_PROGRESS.value)
        )
        & (CallLog.ai_greeting_completed == False)  # noqa: E712
    )
    return {
        "silent_caller": silent_caller,
        "non_terminal_gap": non_terminal_gap,
    }


def _resolve_date_range(
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    default_days: int = 7,
) -> tuple[datetime, datetime]:
    """Return (date_from, date_to) with sensible defaults and a 365-day max range."""
    now = datetime.utcnow()
    if date_from is None and date_to is None:
        date_from = now - timedelta(days=default_days)
        date_to = now
    elif date_from is None:
        date_from = date_to - timedelta(days=default_days)  # type: ignore[operator]
    elif date_to is None:
        date_to = now
    # Clamp range to maximum allowed window
    if (date_to - date_from).days > _MAX_RANGE_DAYS:  # type: ignore[operator]
        date_from = date_to - timedelta(days=_MAX_RANGE_DAYS)  # type: ignore[operator]
    return date_from, date_to


@router.get("/calls")
async def get_call_analytics(
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    date_from: Optional[datetime] = Query(None, description="Start of window (ISO 8601). Defaults to 7 days ago."),
    date_to: Optional[datetime] = Query(None, description="End of window (ISO 8601). Defaults to now."),
    assistant_ids: Optional[List[UUID]] = Query(None, description="Filter to these assistants (repeat param for multiple)."),
    timezone: str = Query("UTC", description="IANA timezone name for time-bucketed aggregations (e.g. America/Los_Angeles)."),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, str(account_id), "call_logs.view", db)
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, KeyError):
        raise HTTPException(status_code=400, detail=f"Invalid timezone: {timezone!r}")
    try:
        since, until = _resolve_date_range(date_from, date_to)

        def _base():
            q = db.query(CallLog).filter(
                CallLog.account_id == account_id,
                CallLog.started_at >= since,
                CallLog.started_at <= until,
            )
            if assistant_ids:
                q = q.filter(CallLog.assistant_id.in_(assistant_ids))
            return q

        # Task #97: one GROUP BY (status, ai_greeting_completed) replaces the
        # six legacy COUNT queries. `_classify_partition` is exhaustive, so
        # `partition_integrity_ok` is a pure reconciliation check (should
        # always be True under normal operation).
        # Task #98 — group by caller_spoke as well so the classifier can
        # separate the silent-caller case (greeted=True, caller_spoke=False)
        # from real AI-handled calls. NULL is preserved (legacy rows treated
        # as "assume spoke").
        partition_rows = (
            _base()
            .with_entities(
                CallLog.status,
                CallLog.ai_greeting_completed,
                CallLog.caller_spoke,
                func.count(CallLog.id).label("cnt"),
            )
            .group_by(CallLog.status, CallLog.ai_greeting_completed, CallLog.caller_spoke)
            .all()
        )
        buckets = {name: 0 for name in _PARTITION_BUCKETS}
        partition_counts_by_status: dict = {}
        # Task #98 — sub-breakdown of the unresolved bucket for the StatCard
        # tooltip. silent_caller = (greeted=True, spoke=False); the rest is
        # the existing finalization-gap / anomaly content.
        unresolved_breakdown = {"silent_caller": 0, "non_terminal_gap": 0, "other": 0}
        total = 0
        completed = 0
        ended_early_status_total = 0  # rows with status=ended_early (any greeted)
        _non_terminal_statuses = (
            CallStatus.INITIATED.value,
            CallStatus.RINGING.value,
            CallStatus.IN_PROGRESS.value,
        )
        for r in partition_rows:
            cnt = int(r.cnt)
            total += cnt
            partition_counts_by_status[r.status] = (
                partition_counts_by_status.get(r.status, 0) + cnt
            )
            cs = r.caller_spoke  # Optional[bool]
            bucket = _classify_partition(r.status, bool(r.ai_greeting_completed), cs)
            buckets[bucket] += cnt
            if bucket == "unresolved":
                if (
                    r.ai_greeting_completed
                    and cs is False
                    and r.status
                    in _AI_GREETED_STATUSES + (CallStatus.ENDED_EARLY.value,)
                ):
                    unresolved_breakdown["silent_caller"] += cnt
                elif (
                    not r.ai_greeting_completed
                    and r.status in _non_terminal_statuses
                ):
                    unresolved_breakdown["non_terminal_gap"] += cnt
                else:
                    unresolved_breakdown["other"] += cnt
            if r.status == CallStatus.COMPLETED.value:
                completed += cnt
            elif r.status == CallStatus.ENDED_EARLY.value:
                ended_early_status_total += cnt

        ai_handled_count = buckets["ai_handled"]
        ended_early_count = buckets["ended_early"]
        missed_count = buckets["missed"]
        failed_count = buckets["failed"]
        unresolved_count = buckets["unresolved"]
        partition_sum = sum(buckets.values())
        partition_integrity_ok = partition_sum == total
        if not partition_integrity_ok:
            logger.warning(
                "Analytics partition integrity fail for account {}: "
                "total={} sum={} buckets={} per_status={}",
                account_id, total, partition_sum, buckets,
                partition_counts_by_status,
            )

        # Legacy (pre-#97) aliases. Kept for backward compat this release;
        # see replit.md deprecation note.
        missed = missed_count
        failed = failed_count
        ended_early = ended_early_status_total
        ai_handled_legacy = completed

        transferred = _base().filter(CallLog.has_transfer == True).count()

        dur_row = (
            _base()
            .with_entities(
                func.coalesce(func.avg(CallLog.duration_seconds), 0).label("avg"),
                func.coalesce(func.sum(CallLog.duration_seconds), 0).label("total"),
            )
            .one()
        )

        call_ids_subq = _base().with_entities(CallLog.id).subquery()

        ai_dur = (
            db.query(
                func.coalesce(func.sum(CallLeg.duration_seconds), 0).label("total"),
                func.count(func.distinct(CallLeg.call_log_id)).label("calls"),
            )
            .filter(
                CallLeg.call_log_id.in_(call_ids_subq),
                CallLeg.leg_type == "ai_conversation",
            )
            .one()
        )
        ai_calls = int(ai_dur.calls) or 1
        avg_ai_duration = round(float(ai_dur.total) / ai_calls, 1)
        total_ai_duration = int(ai_dur.total)

        outbound_dur = (
            db.query(
                func.coalesce(func.sum(CallLeg.duration_seconds), 0).label("total"),
                func.count(func.distinct(CallLeg.call_log_id)).label("calls"),
            )
            .filter(
                CallLeg.call_log_id.in_(call_ids_subq),
                CallLeg.leg_type.in_(["transfer_external", "transfer_sip", "transfer_internal", "transfer_cold"]),
            )
            .one()
        )
        outbound_calls = int(outbound_dur.calls) or 1
        avg_outbound_duration = round(float(outbound_dur.total) / outbound_calls, 1)
        total_outbound_duration = int(outbound_dur.total)

        overview = {
            "total_calls": total,
            "completed": completed,
            # --- Task #97 partition (new canonical keys) ---
            "ai_handled_count": ai_handled_count,
            "ended_early_count": ended_early_count,
            "missed_count": missed_count,
            "failed_count": failed_count,
            "unresolved_count": unresolved_count,
            "unresolved_rate": round(unresolved_count / total * 100, 1) if total else 0,
            # Task #98 — sub-breakdown of the unresolved bucket. Sums to
            # unresolved_count. Surfaced in the StatCard tooltip so users
            # can tell silent-caller drops apart from finalization-lag rows.
            "unresolved_breakdown": unresolved_breakdown,
            "partition_integrity_ok": partition_integrity_ok,
            "partition_counts_by_status": partition_counts_by_status,
            # --- Legacy aliases (deprecated, preserved this release) ---
            "ai_handled_calls": ai_handled_legacy,
            "missed": missed,
            "failed": failed,
            "transferred": transferred,
            "ended_early_calls": ended_early,
            # Per spec: preserve existing ai_handled_rate / ended_early_rate
            # formulas but compute them from the new counts.
            "ended_early_rate": round(ended_early_count / total * 100, 1) if total else 0,
            "ai_handled_rate": round(ai_handled_count / total * 100, 1) if total else 0,
            "completion_rate": round(completed / total * 100, 1) if total else 0,
            "transfer_rate": round(transferred / total * 100, 1) if total else 0,
            "avg_duration_seconds": round(float(dur_row.avg), 1),
            "total_duration_seconds": int(dur_row.total),
            "avg_ai_duration_seconds": avg_ai_duration,
            "total_ai_duration_seconds": total_ai_duration,
            "avg_outbound_duration_seconds": avg_outbound_duration,
            "total_outbound_duration_seconds": total_outbound_duration,
            "outbound_calls_count": int(outbound_dur.calls),
        }

        # Timezone-aware local timestamp.
        # started_at is stored as timestamp WITHOUT time zone (naive UTC).
        # Explicitly anchor the naive timestamp to UTC using timezone('UTC', ts),
        # which yields a timestamptz. Then timezone(target, timestamptz) converts
        # it to local time. This two-step form is independent of the DB session
        # timezone setting, making it portable across any PostgreSQL environment.
        local_ts = func.timezone(timezone, func.timezone("UTC", CallLog.started_at))

        day_label = func.date_trunc("day", local_ts).label("day")
        vol_rows = (
            _base()
            .with_entities(day_label, func.count(CallLog.id).label("cnt"))
            .group_by("day")
            .order_by("day")
            .all()
        )
        volume_by_day = [
            {"date": r.day.date().isoformat(), "calls": r.cnt}
            for r in vol_rows
        ]

        hour_label = func.extract("hour", local_ts).label("hr")
        hour_rows = (
            _base()
            .with_entities(hour_label, func.count(CallLog.id).label("cnt"))
            .group_by("hr")
            .order_by("hr")
            .all()
        )
        calls_by_hour = [
            {"hour": int(r.hr), "calls": r.cnt}
            for r in hour_rows
        ]

        status_rows = (
            _base()
            .with_entities(CallLog.status, func.count(CallLog.id).label("cnt"))
            .group_by(CallLog.status)
            .order_by(desc("cnt"))
            .all()
        )
        status_distribution = [
            {"status": r.status, "count": r.cnt}
            for r in status_rows
        ]

        asst_rows = (
            _base()
            .filter(CallLog.assistant_id.isnot(None))
            .with_entities(CallLog.assistant_id, func.count(CallLog.id).label("cnt"))
            .group_by(CallLog.assistant_id)
            .order_by(desc("cnt"))
            .all()
        )
        asst_ids = [r.assistant_id for r in asst_rows]
        asst_names: dict = {}
        if asst_ids:
            arows = db.query(Assistant.id, Assistant.name).filter(Assistant.id.in_(asst_ids)).all()
            asst_names = {str(a.id): a.name for a in arows}

        by_assistant = [
            {
                "assistant_id": str(r.assistant_id),
                "assistant_name": asst_names.get(str(r.assistant_id), "Unknown"),
                "calls": r.cnt,
            }
            for r in asst_rows
        ]

        disp_rows = (
            _base()
            .filter(CallLog.disposition_id.isnot(None))
            .with_entities(CallLog.disposition_id, func.count(CallLog.id).label("cnt"))
            .group_by(CallLog.disposition_id)
            .order_by(desc("cnt"))
            .all()
        )
        disp_ids = [r.disposition_id for r in disp_rows]
        disp_info: dict = {}
        if disp_ids:
            disps = db.query(AssistantDisposition).filter(AssistantDisposition.id.in_(disp_ids)).all()
            disp_info = {str(d.id): {"name": d.name, "color": d.color} for d in disps}

        dispositions = [
            {
                "disposition_id": str(r.disposition_id),
                "name": disp_info.get(str(r.disposition_id), {}).get("name", "Unknown"),
                "color": disp_info.get(str(r.disposition_id), {}).get("color"),
                "count": r.cnt,
            }
            for r in disp_rows
        ]

        acw_base = _base().filter(CallLog.acw_completed_at.isnot(None))
        acw_total = acw_base.count()

        score_row = acw_base.with_entities(
            func.avg(CallLog.acw_quality_score).label("avg"),
            func.min(CallLog.acw_quality_score).label("mn"),
            func.max(CallLog.acw_quality_score).label("mx"),
        ).one()

        res_rows = (
            acw_base
            .filter(CallLog.acw_resolution.isnot(None))
            .with_entities(CallLog.acw_resolution, func.count(CallLog.id).label("cnt"))
            .group_by(CallLog.acw_resolution)
            .order_by(desc("cnt"))
            .all()
        )

        buckets = [
            ("0-20", 0, 20),
            ("21-40", 21, 40),
            ("41-60", 41, 60),
            ("61-80", 61, 80),
            ("81-100", 81, 100),
        ]
        score_dist_cases = [
            func.sum(
                case(
                    (
                        (CallLog.acw_quality_score >= lo) & (CallLog.acw_quality_score <= hi),
                        1,
                    ),
                    else_=0,
                )
            ).label(label)
            for label, lo, hi in buckets
        ]

        score_dist_row = acw_base.with_entities(*score_dist_cases).one() if acw_total else None

        score_distribution = []
        if score_dist_row:
            for i, (label, _, _) in enumerate(buckets):
                score_distribution.append({"range": label, "count": int(score_dist_row[i] or 0)})

        acw_completion_rate = round(acw_total / total * 100, 1) if total else 0

        acw = {
            "acw_completed": acw_total,
            "acw_completion_rate": acw_completion_rate,
            "avg_quality_score": round(float(score_row.avg), 1) if score_row.avg else None,
            "min_quality_score": int(score_row.mn) if score_row.mn is not None else None,
            "max_quality_score": int(score_row.mx) if score_row.mx is not None else None,
            "resolution_distribution": [
                {"resolution": r.acw_resolution, "count": r.cnt}
                for r in res_rows
            ],
            "score_distribution": score_distribution,
        }

        return {
            "date_from": since.isoformat() + "Z",
            "date_to": until.isoformat() + "Z",
            "overview": overview,
            "volume_by_day": volume_by_day,
            "calls_by_hour": calls_by_hour,
            "status_distribution": status_distribution,
            "by_assistant": by_assistant,
            "dispositions": dispositions,
            "acw": acw,
        }

    except Exception as e:
        logger.exception(f"Error generating call analytics: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate call analytics")


@router.get("/calls/drilldown")
async def get_calls_drilldown(
    account_id: UUID = Query(..., description="Account ID for multi-tenant isolation"),
    date_from: Optional[datetime] = Query(None, description="Start of window (ISO 8601)."),
    date_to: Optional[datetime] = Query(None, description="End of window (ISO 8601)."),
    assistant_ids: Optional[List[UUID]] = Query(None, description="Filter to these assistants."),
    timezone: str = Query("UTC", description="IANA timezone name — used to match hour: filters to the same timezone as the chart."),
    metric: str = Query("all", description=(  # noqa: E501
        "Metric token — one of: all | completed | transferred | acw_completed | "
        "status:<val> | disposition:<uuid> | hour:<0-23> | assistant:<uuid> | "
        "quality_range:<label> | resolution:<val> | "
        "ai_handled | ended_early | missed | failed | unresolved. "
        "The last five are the canonical Task #97 partition bucket tokens and "
        "match the classifier used by GET /api/analytics/calls 1:1."
    )),
    page: int = Query(1, ge=1),
    limit: int = Query(_DRILLDOWN_PAGE_LIMIT, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_account_permission(user, str(account_id), "call_logs.view", db)
    """
    Return a paginated list of individual call records that make up a given
    analytics metric slice.  Supports the same date/assistant filters as
    GET /api/analytics/calls.
    """
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, KeyError):
        raise HTTPException(status_code=400, detail=f"Invalid timezone: {timezone!r}")
    try:
        since, until = _resolve_date_range(date_from, date_to)

        query = db.query(CallLog).filter(
            CallLog.account_id == account_id,
            CallLog.started_at >= since,
            CallLog.started_at <= until,
        )
        if assistant_ids:
            query = query.filter(CallLog.assistant_id.in_(assistant_ids))

        # --- apply metric filter ---
        token = metric.strip()
        if token == "completed":
            query = query.filter(CallLog.status == CallStatus.COMPLETED.value)
        elif token == "missed":
            query = query.filter(CallLog.status.in_([
                CallStatus.NO_ANSWER.value,
                CallStatus.BUSY.value,
                CallStatus.CANCELED.value,
            ]))
        elif token == "failed":
            query = query.filter(CallLog.status == CallStatus.FAILED.value)
        elif token == "transferred":
            query = query.filter(CallLog.has_transfer == True)
        elif token == "acw_completed":
            query = query.filter(CallLog.acw_completed_at.isnot(None))
        elif token.startswith("status:"):
            status_val = token[len("status:"):]
            query = query.filter(CallLog.status == status_val)
        elif token.startswith("disposition:"):
            disp_id = token[len("disposition:"):]
            query = query.filter(CallLog.disposition_id == UUID(disp_id))
        elif token.startswith("hour:"):
            hr = int(token[len("hour:"):])
            query = query.filter(
                func.extract(
                    "hour",
                    func.timezone(timezone, func.timezone("UTC", CallLog.started_at)),
                ) == hr
            )
        elif token.startswith("assistant:"):
            asst_id = token[len("assistant:"):]
            query = query.filter(CallLog.assistant_id == UUID(asst_id))
        elif token.startswith("quality_range:"):
            label = token[len("quality_range:"):]
            _ranges = {
                "0-20": (0, 20), "21-40": (21, 40), "41-60": (41, 60),
                "61-80": (61, 80), "81-100": (81, 100),
            }
            if label in _ranges:
                lo, hi = _ranges[label]
                query = query.filter(
                    CallLog.acw_quality_score >= lo,
                    CallLog.acw_quality_score <= hi,
                )
        elif token.startswith("resolution:"):
            resolution_val = token[len("resolution:"):]
            query = query.filter(CallLog.acw_resolution == resolution_val)
        elif token in ("ai_handled", "ended_early", "unresolved"):
            # Canonical Task #97 partition bucket tokens.
            query = query.filter(_bucket_predicate(token))
        # "all" — no extra filter

        total = query.count()

        call_logs = (
            query
            .order_by(desc(CallLog.started_at))
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )

        # Bulk-load assistant + phone names
        asst_id_set = {log.assistant_id for log in call_logs if log.assistant_id}
        phone_id_set = {log.phone_number_id for log in call_logs if log.phone_number_id}
        disp_id_set = {log.disposition_id for log in call_logs if log.disposition_id}

        asst_map: dict = {}
        if asst_id_set:
            rows = db.query(Assistant.id, Assistant.name).filter(
                Assistant.id.in_(asst_id_set), Assistant.account_id == account_id
            ).all()
            asst_map = {str(r.id): r.name for r in rows}

        phone_map: dict = {}
        if phone_id_set:
            rows = db.query(PhoneNumber.id, PhoneNumber.phone_number).filter(
                PhoneNumber.id.in_(phone_id_set), PhoneNumber.account_id == account_id
            ).all()
            phone_map = {str(r.id): r.phone_number for r in rows}

        disp_map: dict = {}
        if disp_id_set:
            rows = db.query(
                AssistantDisposition.id,
                AssistantDisposition.name,
                AssistantDisposition.color,
            ).filter(AssistantDisposition.id.in_(disp_id_set)).all()
            disp_map = {str(r.id): {"name": r.name, "color": r.color} for r in rows}

        records = []
        for log in call_logs:
            records.append({
                "id": str(log.id),
                "reference_id": log.reference_id,
                "started_at": (log.started_at.isoformat() + "Z") if log.started_at else None,
                "caller_number": log.caller_number,
                "to_number": log.to_number,
                "status": log.status,
                "duration_seconds": log.duration_seconds,
                "has_transfer": log.has_transfer,
                "assistant_id": str(log.assistant_id) if log.assistant_id else None,
                "assistant_name": asst_map.get(str(log.assistant_id)) if log.assistant_id else None,
                "phone_number_display": phone_map.get(str(log.phone_number_id)) if log.phone_number_id else None,
                "disposition_id": str(log.disposition_id) if log.disposition_id else None,
                "disposition_name": disp_map.get(str(log.disposition_id), {}).get("name") if log.disposition_id else None,
                "disposition_color": disp_map.get(str(log.disposition_id), {}).get("color") if log.disposition_id else None,
                "acw_quality_score": log.acw_quality_score,
                "acw_resolution": log.acw_resolution,
                "ended_early": log.ended_early,
            })

        return {
            "records": records,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": max(1, (total + limit - 1) // limit),
            "metric": metric,
            "date_from": since.isoformat() + "Z",
            "date_to": until.isoformat() + "Z",
        }

    except Exception as e:
        logger.exception(f"Error fetching drilldown: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch drilldown data")
