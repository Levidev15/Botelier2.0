"""Audited reconciliation of historical call durations against Twilio."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import joinedload

from botelier.database import SessionLocal
from botelier.integrations.twilio.client import BotelierTwilioClient
from botelier.models.account import Account
from botelier.models.billing import (
    AccountBillingConfig,
    CallBillingItem,
    CallDurationReconciliationResult,
    CallDurationReconciliationRun,
)
from botelier.models.call_event import CallEvent
from botelier.models.call_log import CallLeg, CallLog, LegType
from botelier.services.call_duration_billing import CallDurationBillingService


_TERMINAL_STATUSES = {
    "completed",
    "ended_early",
    "busy",
    "failed",
    "no_answer",
    "no-answer",
    "canceled",
}
_WARM_TRANSFER_TYPES = {
    LegType.TRANSFER_EXTERNAL.value,
    LegType.TRANSFER_SIP.value,
}


@dataclass(frozen=True)
class CallCandidate:
    call_log_id: UUID
    account_id: UUID
    call_sid: str
    account_sid: Optional[str]
    auth_token: Optional[str]
    child_sids: tuple[str, ...]
    parent_event_duration: Optional[int]
    child_event_durations: dict[str, int]


@dataclass(frozen=True)
class ProviderEvidence:
    parent_duration: Optional[int]
    parent_source: Optional[str]
    child_durations: dict[str, int]
    child_sources: dict[str, str]
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return self.parent_duration is not None and not self.errors


def _parse_duration(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _event_evidence(events: list[CallEvent]) -> tuple[Optional[int], dict[str, int]]:
    parent_duration = None
    child_durations: dict[str, int] = {}
    for event in events:
        details = event.details or {}
        if event.event_type == "call_ended" and event.event_source == "twilio":
            parsed = _parse_duration(details.get("CallDuration"))
            if parsed is not None:
                parent_duration = parsed
        elif (
            event.event_type == "transfer_ended"
            and event.event_source == "twilio"
        ):
            child_sid = details.get("ChildCallSid")
            parsed = _parse_duration(details.get("CallDuration"))
            if child_sid and parsed is not None:
                child_durations[str(child_sid)] = parsed
    return parent_duration, child_durations


def _fetch_provider_evidence(candidate: CallCandidate) -> ProviderEvidence:
    errors: list[str] = []
    warnings: list[str] = []
    parent_duration = None
    parent_source = None
    child_durations: dict[str, int] = {}
    child_sources: dict[str, str] = {}

    client = None
    if candidate.account_sid and candidate.auth_token:
        try:
            client = BotelierTwilioClient(
                account_sid=candidate.account_sid,
                auth_token=candidate.auth_token,
            ).client
            parent = client.calls(candidate.call_sid).fetch()
            parent_duration = _parse_duration(parent.duration)
            if parent_duration is not None:
                parent_source = "twilio_api"
        except Exception as exc:
            warnings.append(f"parent REST fetch failed: {type(exc).__name__}")
    else:
        warnings.append("Twilio subaccount credentials unavailable")

    if parent_duration is None and candidate.parent_event_duration is not None:
        parent_duration = candidate.parent_event_duration
        parent_source = "twilio_webhook"
    if parent_duration is None:
        errors.append("authoritative parent duration unavailable")

    for child_sid in candidate.child_sids:
        if child_sid.startswith("__missing_leg_"):
            errors.append(f"transfer leg is missing a child CallSid: {child_sid}")
            continue
        child_duration = None
        if client is not None:
            try:
                child = client.calls(child_sid).fetch()
                provider_parent = getattr(child, "parent_call_sid", None)
                if provider_parent and provider_parent != candidate.call_sid:
                    errors.append(
                        f"child {child_sid} parent mismatch: {provider_parent}"
                    )
                    continue
                child_duration = _parse_duration(child.duration)
                if child_duration is not None:
                    child_durations[child_sid] = child_duration
                    child_sources[child_sid] = "twilio_api"
            except Exception as exc:
                warnings.append(
                    f"child {child_sid} REST fetch failed: {type(exc).__name__}"
                )

        if child_duration is None and child_sid in candidate.child_event_durations:
            child_durations[child_sid] = candidate.child_event_durations[child_sid]
            child_sources[child_sid] = "twilio_webhook"
        if child_sid not in child_durations:
            errors.append(f"authoritative child duration unavailable: {child_sid}")

    return ProviderEvidence(
        parent_duration=parent_duration,
        parent_source=parent_source,
        child_durations=child_durations,
        child_sources=child_sources,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _billing_snapshot(items: list[CallBillingItem]) -> list[dict]:
    return [
        {
            "id": str(item.id),
            "item_type": item.item_type,
            "call_leg_id": str(item.call_leg_id) if item.call_leg_id else None,
            "source_duration_seconds": item.source_duration_seconds,
            "duration_source": item.duration_source,
            "quantity_minutes": item.quantity_minutes,
            "rate_per_unit_usd": float(item.rate_per_unit_usd),
            "cost_usd": float(item.cost_usd),
            "billing_config_id": str(item.billing_config_id)
            if item.billing_config_id
            else None,
        }
        for item in items
    ]


def _evidence_from_audit(value: dict[str, Any]) -> ProviderEvidence:
    return ProviderEvidence(
        parent_duration=_parse_duration(value.get("parent_duration")),
        parent_source=value.get("parent_source"),
        child_durations={
            str(call_sid): int(duration)
            for call_sid, duration in (value.get("child_durations") or {}).items()
        },
        child_sources={
            str(call_sid): str(source)
            for call_sid, source in (value.get("child_sources") or {}).items()
        },
        errors=tuple(str(error) for error in (value.get("errors") or [])),
        warnings=tuple(str(error) for error in (value.get("warnings") or [])),
    )


def _normalized_old_values(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "duration_seconds": value.get("duration_seconds"),
        "duration_source": value.get("duration_source"),
        "estimated_cost_usd": _decimal(value.get("estimated_cost_usd")),
        "legs": sorted(
            [
                {
                    "id": leg.get("id"),
                    "call_sid": leg.get("call_sid"),
                    "leg_type": leg.get("leg_type"),
                    "duration_seconds": leg.get("duration_seconds"),
                    "duration_source": leg.get("duration_source"),
                }
                for leg in (value.get("legs") or [])
            ],
            key=lambda leg: leg["id"] or "",
        ),
        "billing_items": sorted(
            [
                {
                    "id": item.get("id"),
                    "item_type": item.get("item_type"),
                    "call_leg_id": item.get("call_leg_id"),
                    "source_duration_seconds": item.get("source_duration_seconds"),
                    "duration_source": item.get("duration_source"),
                    "quantity_minutes": int(item.get("quantity_minutes") or 0),
                    "rate_per_unit_usd": _decimal(item.get("rate_per_unit_usd")),
                    "cost_usd": _decimal(item.get("cost_usd")),
                    "billing_config_id": item.get("billing_config_id"),
                }
                for item in (value.get("billing_items") or [])
            ],
            key=lambda item: item["id"] or "",
        ),
    }


def _resolve_item_rate(
    *,
    item: Optional[CallBillingItem],
    config: Optional[AccountBillingConfig],
    inbound_rate: Decimal,
    is_transfer: bool,
) -> Decimal:
    if config is not None:
        if not is_transfer:
            return _decimal(config.inbound_rate_usd)
        outbound = _decimal(config.outbound_rate_usd)
        if (config.voice_rate_model or "combined") == "combined":
            return max(Decimal("0"), outbound - _decimal(config.inbound_rate_usd))
        return outbound
    if item is None:
        return Decimal("0")
    stored = _decimal(item.rate_per_unit_usd)
    return max(Decimal("0"), stored - inbound_rate) if is_transfer else stored


class CallDurationReconciler:
    """Run dry-run or apply reconciliation batches with per-call transactions."""

    def __init__(self, *, concurrency: int = 4):
        self.concurrency = max(1, min(int(concurrency), 16))

    def _load_candidates(
        self,
        *,
        account_id: Optional[UUID],
        date_from: Optional[datetime],
        date_to: Optional[datetime],
        call_sid: Optional[str],
        batch_size: int,
        resume_after: Optional[str],
    ) -> list[CallCandidate]:
        db = SessionLocal()
        try:
            query = (
                db.query(CallLog)
                .options(joinedload(CallLog.legs))
                .filter(CallLog.status.in_(_TERMINAL_STATUSES))
            )
            if account_id:
                query = query.filter(CallLog.account_id == account_id)
            if date_from:
                query = query.filter(CallLog.started_at >= date_from)
            if date_to:
                query = query.filter(CallLog.started_at <= date_to)
            if call_sid:
                query = query.filter(CallLog.call_sid == call_sid)
            if resume_after:
                query = query.filter(CallLog.call_sid > resume_after)
            logs = query.order_by(CallLog.call_sid).limit(batch_size).all()

            account_ids = {log.account_id for log in logs}
            accounts = {
                account.id: account
                for account in db.query(Account).filter(Account.id.in_(account_ids)).all()
            }
            candidates = []
            for log in logs:
                events = (
                    db.query(CallEvent)
                    .filter(CallEvent.call_log_id == log.id)
                    .order_by(CallEvent.occurred_at)
                    .all()
                )
                parent_event, child_events = _event_evidence(events)
                warm_legs = [
                    leg
                    for leg in (log.legs or [])
                    if leg.leg_type in _WARM_TRANSFER_TYPES
                ]
                missing_sid = [leg for leg in warm_legs if not leg.call_sid]
                child_sids = tuple(leg.call_sid for leg in warm_legs if leg.call_sid)
                if missing_sid:
                    child_sids += tuple(
                        f"__missing_leg_{leg.id}" for leg in missing_sid
                    )
                account = accounts.get(log.account_id)
                candidates.append(
                    CallCandidate(
                        call_log_id=log.id,
                        account_id=log.account_id,
                        call_sid=log.call_sid,
                        account_sid=account.twilio_sub_account_sid if account else None,
                        auth_token=account.twilio_sub_auth_token if account else None,
                        child_sids=child_sids,
                        parent_event_duration=parent_event,
                        child_event_durations=child_events,
                    )
                )
            return candidates
        finally:
            db.close()

    def _reconcile_one(
        self,
        *,
        run_id: UUID,
        candidate: CallCandidate,
        evidence: ProviderEvidence,
        apply: bool,
        approved_old_values: Optional[dict[str, Any]] = None,
        approved_new_values: Optional[dict[str, Any]] = None,
    ) -> str:
        db = SessionLocal()
        try:
            query = (
                db.query(CallLog)
                .filter(CallLog.id == candidate.call_log_id)
            )
            if apply:
                query = query.with_for_update()
            call_log = query.first()
            if call_log is None:
                return "missing"

            items = (
                db.query(CallBillingItem)
                .filter(CallBillingItem.call_log_id == call_log.id)
                .order_by(CallBillingItem.created_at, CallBillingItem.id)
                .all()
            )
            old_values = {
                "duration_seconds": call_log.duration_seconds,
                "duration_source": call_log.duration_source,
                "estimated_cost_usd": float(call_log.estimated_cost_usd or 0),
                "legs": [
                    {
                        "id": str(leg.id),
                        "call_sid": leg.call_sid,
                        "leg_type": leg.leg_type,
                        "duration_seconds": leg.duration_seconds,
                        "duration_source": leg.duration_source,
                    }
                    for leg in (call_log.legs or [])
                ],
                "billing_items": _billing_snapshot(items),
            }
            if apply and approved_old_values is not None:
                if _normalized_old_values(old_values) != _normalized_old_values(
                    approved_old_values
                ):
                    raise ValueError(
                        "call state changed after the approved dry run"
                    )

            if not evidence.complete:
                result = CallDurationReconciliationResult(
                    run_id=run_id,
                    call_log_id=call_log.id,
                    account_id=call_log.account_id,
                    call_sid=call_log.call_sid,
                    status="unresolved",
                    duration_source=evidence.parent_source,
                    old_values=old_values,
                    new_values={},
                    provider_evidence={
                        "parent_duration": evidence.parent_duration,
                        "parent_source": evidence.parent_source,
                        "child_durations": evidence.child_durations,
                        "child_sources": evidence.child_sources,
                        "errors": list(evidence.errors),
                        "warnings": list(evidence.warnings),
                    },
                    error_message="; ".join(evidence.errors),
                )
                db.add(result)
                db.commit()
                return "unresolved"

            configs = {
                config.id: config
                for config in db.query(AccountBillingConfig)
                .filter(
                    AccountBillingConfig.id.in_(
                        [item.billing_config_id for item in items if item.billing_config_id]
                    )
                )
                .all()
            }
            inbound_items = [item for item in items if item.item_type == "inbound_call"]
            transfer_items = [
                item for item in items if item.item_type == "outbound_transfer"
            ]
            inbound_item = inbound_items[0] if inbound_items else None
            inbound_config = (
                configs.get(inbound_item.billing_config_id) if inbound_item else None
            )
            if inbound_config is None:
                inbound_config = (
                    db.query(AccountBillingConfig)
                    .filter(
                        AccountBillingConfig.account_id == call_log.account_id,
                        AccountBillingConfig.effective_from
                        <= (call_log.started_at or datetime.utcnow()),
                    )
                    .order_by(AccountBillingConfig.effective_from.desc())
                    .first()
                )
            if inbound_config is None:
                inbound_config = (
                    db.query(AccountBillingConfig)
                    .filter(
                        AccountBillingConfig.account_id.is_(None),
                        AccountBillingConfig.effective_from
                        <= (call_log.started_at or datetime.utcnow()),
                    )
                    .order_by(AccountBillingConfig.effective_from.desc())
                    .first()
                )
            inbound_rate = _resolve_item_rate(
                item=inbound_item,
                config=inbound_config,
                inbound_rate=Decimal("0"),
                is_transfer=False,
            )
            approved_rates = (
                (approved_new_values or {}).get("rates") if apply else None
            )
            if approved_rates is not None:
                if "inbound" not in approved_rates:
                    raise ValueError("approved dry run is missing the inbound rate")
                inbound_rate = _decimal(approved_rates["inbound"])
            approved_transfer_rates = (
                approved_rates.get("outbound_by_leg") or {}
                if approved_rates is not None
                else {}
            )

            warm_legs = sorted(
                [
                    leg
                    for leg in (call_log.legs or [])
                    if leg.leg_type in _WARM_TRANSFER_TYPES
                ],
                key=lambda leg: leg.leg_number,
            )
            explicit_items = {
                item.call_leg_id: item for item in transfer_items if item.call_leg_id
            }
            legacy_items = [item for item in transfer_items if not item.call_leg_id]
            transfer_plan = []
            retained_item_ids = set()
            for leg in warm_legs:
                item = explicit_items.get(leg.id)
                if item is None and legacy_items:
                    item = legacy_items.pop(0)
                if item is not None:
                    retained_item_ids.add(item.id)
                config = configs.get(item.billing_config_id) if item else None
                if config is None:
                    config = inbound_config
                rate = _resolve_item_rate(
                    item=item,
                    config=config,
                    inbound_rate=inbound_rate,
                    is_transfer=True,
                )
                if approved_rates is not None:
                    approved_rate = approved_transfer_rates.get(str(leg.id))
                    if approved_rate is None:
                        raise ValueError(
                            f"approved dry run is missing the rate for leg {leg.id}"
                        )
                    rate = _decimal(approved_rate)
                transfer_plan.append((leg, item, config, rate))

            new_values = {
                "duration_seconds": evidence.parent_duration,
                "duration_source": evidence.parent_source,
                "legs": [
                    {
                        "id": str(leg.id),
                        "call_sid": leg.call_sid,
                        "leg_type": leg.leg_type,
                        "duration_seconds": evidence.child_durations[leg.call_sid],
                        "duration_source": evidence.child_sources[leg.call_sid],
                    }
                    for leg in warm_legs
                ],
                "rates": {
                    "inbound": float(inbound_rate),
                    "outbound_by_leg": {
                        str(leg.id): float(rate)
                        for leg, _item, _config, rate in transfer_plan
                    },
                },
            }

            if apply:
                for duplicate in inbound_items[1:]:
                    db.delete(duplicate)
                for extra in transfer_items:
                    if extra.id not in retained_item_ids:
                        db.delete(extra)
                for leg, item, _config, _rate in transfer_plan:
                    if item is not None:
                        item.call_leg_id = leg.id
                db.flush()

                service = CallDurationBillingService(db)
                service.finalize_parent(
                    call_log,
                    evidence.parent_duration,
                    source=evidence.parent_source or "twilio_api",
                    rate=inbound_rate,
                    billing_config_id=inbound_config.id if inbound_config else None,
                )
                for leg, _item, config, rate in transfer_plan:
                    service.finalize_transfer_leg(
                        call_log,
                        leg,
                        evidence.child_durations[leg.call_sid],
                        source=evidence.child_sources[leg.call_sid],
                        rate=rate,
                        billing_config_id=config.id if config else None,
                    )
                service.recompute_estimated_cost(call_log)
                db.flush()
                refreshed_items = (
                    db.query(CallBillingItem)
                    .filter(CallBillingItem.call_log_id == call_log.id)
                    .order_by(CallBillingItem.created_at, CallBillingItem.id)
                    .all()
                )
                new_values["estimated_cost_usd"] = float(
                    call_log.estimated_cost_usd or 0
                )
                new_values["billing_items"] = _billing_snapshot(refreshed_items)
            else:
                parent_minutes = (
                    (evidence.parent_duration + 59) // 60
                    if evidence.parent_duration
                    else 0
                )
                projected_items = [
                    {
                        "item_type": "inbound_call",
                        "source_duration_seconds": evidence.parent_duration,
                        "quantity_minutes": parent_minutes,
                        "rate_per_unit_usd": float(inbound_rate),
                        "cost_usd": float(Decimal(parent_minutes) * inbound_rate),
                    }
                ]
                for leg, _item, _config, rate in transfer_plan:
                    duration = evidence.child_durations[leg.call_sid]
                    minutes = (duration + 59) // 60 if duration else 0
                    projected_items.append(
                        {
                            "item_type": "outbound_transfer",
                            "call_leg_id": str(leg.id),
                            "source_duration_seconds": duration,
                            "quantity_minutes": minutes,
                            "rate_per_unit_usd": float(rate),
                            "cost_usd": float(Decimal(minutes) * rate),
                        }
                    )
                new_values["billing_items"] = projected_items
                new_values["estimated_cost_usd"] = sum(
                    item["cost_usd"] for item in projected_items
                )

            db.add(
                CallDurationReconciliationResult(
                    run_id=run_id,
                    call_log_id=call_log.id,
                    account_id=call_log.account_id,
                    call_sid=call_log.call_sid,
                    status="applied" if apply else "planned",
                    duration_source=evidence.parent_source,
                    old_values=old_values,
                    new_values=new_values,
                    provider_evidence={
                        "parent_duration": evidence.parent_duration,
                        "parent_source": evidence.parent_source,
                        "child_durations": evidence.child_durations,
                        "child_sources": evidence.child_sources,
                        "errors": list(evidence.errors),
                        "warnings": list(evidence.warnings),
                    },
                )
            )
            db.commit()
            return "applied" if apply else "planned"
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _record_failed_result(
        self,
        *,
        run_id: UUID,
        candidate: CallCandidate,
        error: Exception,
    ) -> None:
        db = SessionLocal()
        try:
            call_log = db.query(CallLog).filter(
                CallLog.id == candidate.call_log_id
            ).first()
            db.add(
                CallDurationReconciliationResult(
                    run_id=run_id,
                    call_log_id=candidate.call_log_id,
                    account_id=candidate.account_id,
                    call_sid=candidate.call_sid,
                    status="failed",
                    old_values={
                        "duration_seconds": call_log.duration_seconds
                        if call_log
                        else None,
                        "duration_source": call_log.duration_source
                        if call_log
                        else None,
                    },
                    new_values={},
                    provider_evidence={},
                    error_message=f"{type(error).__name__}: {error}",
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                f"Failed to audit reconciliation error for {candidate.call_sid}"
            )
        finally:
            db.close()

    def _add_result_totals(self, run_id: UUID, summary: dict[str, Any]) -> None:
        db = SessionLocal()
        try:
            results = db.query(CallDurationReconciliationResult).filter(
                CallDurationReconciliationResult.run_id == run_id
            ).all()
            inbound_before = 0
            inbound_after = 0
            transfer_before = 0
            transfer_after = 0
            cost_before = Decimal("0")
            cost_after = Decimal("0")
            corrected = 0
            provider_failures = 0

            for result in results:
                old_values = result.old_values or {}
                new_values = result.new_values or {}
                old_items = old_values.get("billing_items") or []
                resolved = result.status in ("planned", "applied")
                new_items = (
                    new_values.get("billing_items") or []
                    if resolved
                    else old_items
                )

                old_inbound = sum(
                    int(item.get("quantity_minutes") or 0)
                    for item in old_items
                    if item.get("item_type") == "inbound_call"
                )
                new_inbound = sum(
                    int(item.get("quantity_minutes") or 0)
                    for item in new_items
                    if item.get("item_type") == "inbound_call"
                )
                old_transfer = sum(
                    int(item.get("quantity_minutes") or 0)
                    for item in old_items
                    if item.get("item_type") == "outbound_transfer"
                )
                new_transfer = sum(
                    int(item.get("quantity_minutes") or 0)
                    for item in new_items
                    if item.get("item_type") == "outbound_transfer"
                )
                old_cost = _decimal(old_values.get("estimated_cost_usd"))
                new_cost = (
                    _decimal(new_values.get("estimated_cost_usd"))
                    if resolved
                    else old_cost
                )
                inbound_before += old_inbound
                inbound_after += new_inbound
                transfer_before += old_transfer
                transfer_after += new_transfer
                cost_before += old_cost
                cost_after += new_cost
                old_warm_legs = sorted(
                    [
                        {
                            "id": leg.get("id"),
                            "call_sid": leg.get("call_sid"),
                            "leg_type": leg.get("leg_type"),
                            "duration_seconds": leg.get("duration_seconds"),
                            "duration_source": leg.get("duration_source"),
                        }
                        for leg in (old_values.get("legs") or [])
                        if leg.get("leg_type") in _WARM_TRANSFER_TYPES
                    ],
                    key=lambda leg: leg["id"] or "",
                )
                new_warm_legs = sorted(
                    new_values.get("legs") or [],
                    key=lambda leg: leg["id"] or "",
                )

                if resolved and (
                    old_values.get("duration_seconds")
                    != new_values.get("duration_seconds")
                    or old_values.get("duration_source")
                    != new_values.get("duration_source")
                    or old_warm_legs != new_warm_legs
                    or old_inbound != new_inbound
                    or old_transfer != new_transfer
                    or old_cost != new_cost
                ):
                    corrected += 1
                evidence = result.provider_evidence or {}
                provider_failures += len(evidence.get("warnings") or [])
                provider_failures += len(evidence.get("errors") or [])

            summary.update(
                {
                    "corrected_calls": corrected,
                    "provider_failures": provider_failures,
                    "inbound_minutes_before": inbound_before,
                    "inbound_minutes_after": inbound_after,
                    "inbound_minutes_delta": inbound_after - inbound_before,
                    "transfer_minutes_before": transfer_before,
                    "transfer_minutes_after": transfer_after,
                    "transfer_minutes_delta": transfer_after - transfer_before,
                    "cost_before_usd": float(cost_before),
                    "cost_after_usd": float(cost_after),
                    "cost_delta_usd": float(cost_after - cost_before),
                }
            )
        finally:
            db.close()

    def run(
        self,
        *,
        mode: str,
        account_id: Optional[UUID] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        call_sid: Optional[str] = None,
        batch_size: int = 100,
        resume_after: Optional[str] = None,
        approved_run_id: Optional[UUID] = None,
    ) -> CallDurationReconciliationRun:
        apply = mode == "apply"
        if mode not in {"dry_run", "apply"}:
            raise ValueError("mode must be dry_run or apply")
        if apply and approved_run_id is None:
            raise ValueError("--apply requires --approved-run-id from a completed dry run")

        approved_evidence_by_id: dict[UUID, ProviderEvidence] = {}
        approved_old_values_by_id: dict[UUID, dict[str, Any]] = {}
        approved_new_values_by_id: dict[UUID, dict[str, Any]] = {}
        db = SessionLocal()
        try:
            if approved_run_id:
                approved = db.query(CallDurationReconciliationRun).filter(
                    CallDurationReconciliationRun.id == approved_run_id,
                    CallDurationReconciliationRun.mode == "dry_run",
                    CallDurationReconciliationRun.status == "completed",
                ).first()
                if approved is None:
                    raise ValueError("approved dry-run record was not found or is incomplete")
                if int((approved.summary or {}).get("failed", 0)) > 0:
                    raise ValueError("approved dry run contains failed call audits")
                if (
                    approved.account_id != account_id
                    or approved.date_from != date_from
                    or approved.date_to != date_to
                    or approved.call_sid != call_sid
                    or approved.batch_size != batch_size
                    or approved.resume_after != resume_after
                ):
                    raise ValueError("apply scope must exactly match the approved dry run")
                approved_results = (
                    db.query(CallDurationReconciliationResult)
                    .filter(
                        CallDurationReconciliationResult.run_id == approved_run_id
                    )
                    .all()
                )
                if not approved_results:
                    raise ValueError("approved dry run has no audited call results")
                if any(result.status == "failed" for result in approved_results):
                    raise ValueError("approved dry run contains failed call audits")
                approved_evidence_by_id = {
                    result.call_log_id: _evidence_from_audit(
                        result.provider_evidence or {}
                    )
                    for result in approved_results
                }
                approved_old_values_by_id = {
                    result.call_log_id: result.old_values or {}
                    for result in approved_results
                }
                approved_new_values_by_id = {
                    result.call_log_id: result.new_values or {}
                    for result in approved_results
                }

            run = CallDurationReconciliationRun(
                mode=mode,
                status="running",
                account_id=account_id,
                date_from=date_from,
                date_to=date_to,
                call_sid=call_sid,
                batch_size=batch_size,
                resume_after=resume_after,
                summary={},
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            run_id = run.id
        finally:
            db.close()

        summary = {
            "scanned": 0,
            "planned": 0,
            "applied": 0,
            "unresolved": 0,
            "failed": 0,
        }
        try:
            candidates = self._load_candidates(
                account_id=account_id,
                date_from=date_from,
                date_to=date_to,
                call_sid=call_sid,
                batch_size=max(1, min(batch_size, 1000)),
                resume_after=resume_after,
            )
            summary["scanned"] = len(candidates)
            if candidates:
                summary["last_call_sid"] = candidates[-1].call_sid
            if apply:
                candidate_ids = {candidate.call_log_id for candidate in candidates}
                approved_ids = set(approved_evidence_by_id)
                if candidate_ids != approved_ids:
                    raise ValueError(
                        "apply candidate set no longer matches the approved dry run"
                    )
                evidence_by_id = approved_evidence_by_id
            else:
                evidence_by_id = {}
                with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                    futures = {
                        executor.submit(_fetch_provider_evidence, candidate): candidate
                        for candidate in candidates
                    }
                    for future in as_completed(futures):
                        candidate = futures[future]
                        try:
                            evidence_by_id[candidate.call_log_id] = future.result()
                        except Exception as exc:
                            evidence_by_id[candidate.call_log_id] = ProviderEvidence(
                                parent_duration=None,
                                parent_source=None,
                                child_durations={},
                                child_sources={},
                                errors=(
                                    "provider resolution failed: "
                                    f"{type(exc).__name__}",
                                ),
                                warnings=(),
                            )

            for candidate in candidates:
                try:
                    outcome = self._reconcile_one(
                        run_id=run_id,
                        candidate=candidate,
                        evidence=evidence_by_id[candidate.call_log_id],
                        apply=apply,
                        approved_old_values=approved_old_values_by_id.get(
                            candidate.call_log_id
                        ),
                        approved_new_values=approved_new_values_by_id.get(
                            candidate.call_log_id
                        ),
                    )
                    summary[outcome] = summary.get(outcome, 0) + 1
                except Exception as exc:
                    logger.exception(
                        f"Duration reconciliation failed for {candidate.call_sid}: {exc}"
                    )
                    self._record_failed_result(
                        run_id=run_id,
                        candidate=candidate,
                        error=exc,
                    )
                    summary["failed"] += 1

            self._add_result_totals(run_id, summary)
            db = SessionLocal()
            try:
                run = db.query(CallDurationReconciliationRun).filter(
                    CallDurationReconciliationRun.id == run_id
                ).one()
                run.status = "completed"
                run.summary = summary
                run.completed_at = datetime.utcnow()
                db.commit()
                db.refresh(run)
                return run
            finally:
                db.close()
        except Exception as exc:
            db = SessionLocal()
            try:
                run = db.query(CallDurationReconciliationRun).filter(
                    CallDurationReconciliationRun.id == run_id
                ).one()
                run.status = "failed"
                run.error_message = str(exc)
                run.summary = summary
                run.completed_at = datetime.utcnow()
                db.commit()
            finally:
                db.close()
            raise
