"""Runtime capability resolution (Task #329).

Maps an abstract capability (``search_availability`` …) to the caller's
property-scoped provider connection and executes it through the same
``ActionExecutor`` → ``IntegrationClient`` path certified integrations use — so
the capability layer inherits, unchanged, the Task #327 fail-closed
``(account_id, property_id)`` gating, ``PROPERTY_IDENTITY_KEYS`` re-forcing, and
Task #328 canonical envelopes.

Resolution contract (fail closed):
- Only ``CONNECTED`` integrations whose type has an endpoint tagged with the
  capability are candidates.
- Candidates are filtered by :func:`property_access_allowed`.
- Property-bound connections are preferred over account-global ones.
- Within the chosen tier, **more than one candidate is ambiguous and fails
  closed** — the resolver never arbitrarily picks a provider, because that could
  silently route a caller to the wrong system.
- Vendor-neutral arguments are translated to the endpoint's variable keys via the
  seed's ``capability_params`` map; property-identity keys are never accepted from
  the caller (they are re-forced from the connection by ``IntegrationClient``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from botelier.services.capabilities.registry import get_capability
from botelier.services.property_scope import property_access_allowed

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Resolution:
    """A resolved capability → concrete (connection, endpoint) binding."""

    integration_id: str
    integration_property_id: Optional[str]
    endpoint_id: Optional[str]
    method: str
    capability_params: Dict[str, str]


def format_capability_result(result: Any) -> Dict[str, Any]:
    """Normalize an ``ActionExecutionResult`` into the LLM-facing payload.

    Shared by every channel (voice, SMS, simulator) so a capability call behaves
    identically everywhere. On success prefers the canonical envelope (reads),
    then mapped/raw data. On failure returns a compact error dict.
    """
    if getattr(result, "success", False):
        payload: Dict[str, Any] = {}
        canonical = getattr(result, "canonical", None)
        if canonical:
            payload["canonical"] = canonical
        data = getattr(result, "extracted_variables", None) or getattr(result, "data", None)
        if data:
            payload["data"] = data
        if not payload:
            payload = {"status": "success"}
        return payload
    error_type = getattr(result, "error_type", None)
    return {
        "error": getattr(result, "error_message", None) or "The request could not be completed.",
        "status": "failed",
        "error_type": getattr(error_type, "value", error_type),
        "status_code": getattr(result, "status_code", 0),
    }


class CapabilityResolver:
    """Resolve + execute abstract capabilities for one session's scope."""

    def __init__(self, db: Session, account_id: Any, property_id: Any = None):
        self.db = db
        self.account_id = str(account_id) if account_id else None
        self.property_id = str(property_id) if property_id else None

    # -- candidate discovery -------------------------------------------------
    def _candidates(self, capability_name: str) -> List[Resolution]:
        from botelier.models.integration import AccountIntegration, IntegrationStatus

        if not self.account_id:
            return []

        integrations = (
            self.db.query(AccountIntegration)
            .filter(
                AccountIntegration.account_id == self.account_id,
                AccountIntegration.status == IntegrationStatus.CONNECTED,
            )
            .all()
        )

        candidates: List[Resolution] = []
        for integ in integrations:
            itype = integ.integration_type
            if itype is None:
                continue
            try:
                endpoints = itype.get_endpoints()
            except Exception:  # noqa: BLE001 - malformed seed config must not crash resolution
                logger.warning(
                    "capability resolver: could not parse endpoints for integration type %s",
                    getattr(itype, "slug", "?"),
                )
                continue
            for endpoint in endpoints:
                if endpoint.get("capability") != capability_name:
                    continue
                candidates.append(
                    Resolution(
                        integration_id=str(integ.id),
                        integration_property_id=str(integ.property_id)
                        if integ.property_id
                        else None,
                        endpoint_id=endpoint.get("id"),
                        method=(endpoint.get("method") or "GET").upper(),
                        capability_params=endpoint.get("capability_params") or {},
                    )
                )
        return candidates

    def _card_capture_candidates(self) -> List[Resolution]:
        """Discover connected endpoints tagged ``supports_card_capture`` (#339).

        These are the combined booking+payment endpoints (Opera
        ``create_reservation_with_payment`` / GuestCentric
        ``book_reservation_with_payment``). Deliberately NOT keyed off a
        ``capability`` tag so they never compete with ``book_reservation``.
        """
        from botelier.models.integration import AccountIntegration, IntegrationStatus

        if not self.account_id:
            return []

        integrations = (
            self.db.query(AccountIntegration)
            .filter(
                AccountIntegration.account_id == self.account_id,
                AccountIntegration.status == IntegrationStatus.CONNECTED,
            )
            .all()
        )
        out: List[Resolution] = []
        for integ in integrations:
            itype = integ.integration_type
            if itype is None:
                continue
            try:
                endpoints = itype.get_endpoints()
            except Exception:  # noqa: BLE001
                continue
            for endpoint in endpoints:
                if not endpoint.get("supports_card_capture"):
                    continue
                out.append(
                    Resolution(
                        integration_id=str(integ.id),
                        integration_property_id=str(integ.property_id)
                        if integ.property_id
                        else None,
                        endpoint_id=endpoint.get("id"),
                        method=(endpoint.get("method") or "POST").upper(),
                        capability_params=endpoint.get("capability_params") or {},
                    )
                )
        return out

    def resolve_pms_native_payment(self) -> Optional[Resolution]:
        """Select the single PMS-native review+pay endpoint, or ``None`` (#339).

        Same fail-closed, property-scoped, ambiguity-refusing selection as
        :meth:`resolve`. ``None`` means the property has no unambiguous
        payment-capable PMS connection, so ``collect_payment`` falls back to the
        Stripe SMS link.
        """
        candidates = self._card_capture_candidates()
        allowed = [
            c
            for c in candidates
            if property_access_allowed(self.property_id, c.integration_property_id)
        ]
        if not allowed:
            return None
        if self.property_id is not None:
            bound = [c for c in allowed if c.integration_property_id == self.property_id]
            tier = bound if bound else [c for c in allowed if c.integration_property_id is None]
        else:
            tier = allowed
        if len(tier) > 1:
            logger.warning(
                "capability resolver: ambiguous PMS-native payment provider — %d "
                "candidates (account=%s, property=%s). Falling back to link.",
                len(tier),
                self.account_id,
                self.property_id,
            )
            return None
        return tier[0]

    # -- selection -----------------------------------------------------------
    def resolve(self, capability_name: str) -> Optional[Resolution]:
        """Select the single provider binding for a capability, or ``None``.

        ``None`` means fail closed: unknown capability, no connected provider for
        this property, or an ambiguous tie the resolver refuses to break.
        """
        if get_capability(capability_name) is None:
            logger.warning("capability resolver: unknown capability '%s'", capability_name)
            return None

        candidates = self._candidates(capability_name)
        allowed = [
            c
            for c in candidates
            if property_access_allowed(self.property_id, c.integration_property_id)
        ]
        if not allowed:
            logger.info(
                "capability resolver: no connected provider for '%s' "
                "(account=%s, property=%s)",
                capability_name,
                self.account_id,
                self.property_id,
            )
            return None

        # Prefer property-bound connections over account-global ones. Only
        # meaningful when the session itself is property-scoped.
        if self.property_id is not None:
            bound = [c for c in allowed if c.integration_property_id == self.property_id]
            tier = bound if bound else [c for c in allowed if c.integration_property_id is None]
        else:
            tier = allowed

        if len(tier) > 1:
            logger.warning(
                "capability resolver: ambiguous provider for '%s' — %d candidates in "
                "the same tier (account=%s, property=%s). Failing closed.",
                capability_name,
                len(tier),
                self.account_id,
                self.property_id,
            )
            return None

        return tier[0]

    # -- argument translation ------------------------------------------------
    def translate_variables(
        self, resolution: Resolution, variables: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Translate vendor-neutral arguments to the endpoint's variable keys.

        Unmapped keys pass through unchanged so flow slots that already use a
        vendor's variable name (or connection-config constants) still reach the
        template. Mapped canonical keys overlay last so they win.
        """
        out: Dict[str, Any] = dict(variables or {})
        cap_params = resolution.capability_params or {}
        for canonical_key, vendor_key in cap_params.items():
            if variables and canonical_key in variables:
                out[vendor_key] = variables[canonical_key]
        return out

    # -- execution -----------------------------------------------------------
    def _prepare(
        self,
        capability_name: str,
        arguments: Optional[Dict[str, Any]],
        extra_variables: Optional[Dict[str, Any]],
    ):
        spec = get_capability(capability_name)
        if spec is None:
            return None, {
                "error": f"Unknown capability '{capability_name}'.",
                "status": "failed",
            }
        resolution = self.resolve(capability_name)
        if resolution is None:
            return None, {
                "error": "That capability is not available right now.",
                "status": "unavailable",
            }
        merged: Dict[str, Any] = {}
        if extra_variables:
            merged.update(extra_variables)
        if arguments:
            merged.update(arguments)
        return (resolution, self.translate_variables(resolution, merged)), None

    def _idempotency_for(
        self,
        capability_name: str,
        arguments: Optional[Dict[str, Any]],
        call_sid: Optional[str],
        contact_ref: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Derive a durable dedup key for a *mutating* capability (Task #330).

        Only ``mutating`` capabilities (book/cancel/collect_payment) are guarded
        — reads must stay fresh. ``mutating`` is the single source of truth (a
        capability node has no HTTP method to key off; the method lives on the
        resolved vendor endpoint).

        The key binds the operation to its tenant, property, *contact*, and the
        *canonical* arguments the caller supplied (not the translated vendor vars
        or the full slot dump). The contact component scopes dedup to a single
        conversation so a reconnect/retry dedups while a genuinely different
        contact can legitimately repeat the same operation.

        Voice supplies ``call_sid``. Channels without a call SID (SMS) MUST supply
        a stable per-conversation ``contact_ref`` (the SMS conversation id). If
        neither is present the contact component would be empty and two different
        guests issuing identical arguments (e.g. the same payment amount) would
        collide on one key — the second, genuinely distinct write would then be
        silently deduped to a no-op. Keep at least one of ``call_sid`` /
        ``contact_ref`` populated on every mutating channel.
        """
        import hashlib

        spec = get_capability(capability_name)
        if spec is None or not spec.mutating:
            return None, None, None

        if not call_sid and not contact_ref:
            # Contract guard: with an empty contact component, two different
            # contacts issuing identical args would collide on one key and the
            # second write would be silently deduped. Every channel must supply a
            # call_sid (voice) or contact_ref (SMS conversation id / simulator
            # session id). Warn loudly rather than fail so an existing single
            # contact keeps working, but the regression is visible in logs.
            logger.warning(
                "capability idempotency: mutating '%s' has no call_sid/contact_ref; "
                "dedup key is not contact-scoped and may collide across contacts",
                capability_name,
            )

        args_payload = json.dumps(arguments or {}, sort_keys=True, default=str)
        args_hash = hashlib.sha256(args_payload.encode("utf-8")).hexdigest()
        raw = "|".join(
            [
                "cap",
                str(self.account_id or ""),
                str(self.property_id or ""),
                str(call_sid or contact_ref or ""),
                capability_name,
                args_hash,
            ]
        )
        key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return key, capability_name, args_hash

    def _build_request(
        self,
        resolution: Resolution,
        vendor_vars: Dict[str, Any],
        capability_name: str,
        channel: str,
        call_sid: Optional[str],
        source_label: Optional[str],
        idempotency: tuple[Optional[str], Optional[str], Optional[str]] = (
            None,
            None,
            None,
        ),
    ):
        from botelier.services.action_executor import ActionContext, ActionExecutionRequest
        from botelier.services.integration_runtime.types import IntegrationAPIConfig

        config = IntegrationAPIConfig(
            integration_id=resolution.integration_id,
            endpoint_id=resolution.endpoint_id,
            method=resolution.method,
        )
        idem_key, operation, args_hash = idempotency
        return ActionExecutionRequest(
            context=ActionContext(
                account_id=self.account_id,
                channel=channel,
                call_sid=call_sid,
                property_id=self.property_id,
                source_label=source_label or f"capability:{capability_name}",
            ),
            variables=vendor_vars,
            integration_config=config,
            idempotency_key=idem_key,
            operation=operation,
            args_hash=args_hash,
        )

    def _service_backed_payment(
        self,
        capability_name: str,
        arguments: Optional[Dict[str, Any]],
        channel: str,
        call_sid: Optional[str],
        contact_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Route ``collect_payment`` to :class:`PaymentService` (Task #330).

        Service-backed capabilities do not resolve to a PMS vendor endpoint, so
        they bypass ``resolve → IntegrationClient`` entirely. Property scope and
        durable idempotency are still applied: the payment write is keyed with the
        same ``_idempotency_for`` key so a reconnect/retry dedups to one charge.
        On SMS the per-conversation ``contact_ref`` keeps two guests' identical
        payments from colliding on one dedup key.
        """
        from botelier.services.payments import PaymentService

        args = arguments or {}
        idem_key, _operation, _args_hash = self._idempotency_for(
            capability_name, arguments, call_sid, contact_ref
        )
        service = PaymentService(self.account_id, self.property_id)

        # Task #339: prefer a PMS-native review+pay link when the caller's property
        # has an unambiguous payment-capable PMS connection; otherwise fall back to
        # the Stripe hosted-checkout SMS link. Fail-closed detection reuses the same
        # per-property scoping/ambiguity rules as capability resolution.
        session_key = call_sid or contact_ref
        try:
            pms = self.resolve_pms_native_payment()
        except Exception as exc:  # noqa: BLE001 - detection must never break the charge
            logger.warning("pms-native detection failed, using link fallback: %s", exc)
            pms = None
        if pms is not None:
            vendor_slug = self._integration_slug(pms.integration_id)
            return service.collect_payment_pms_native(
                amount=args.get("amount"),
                currency=args.get("currency", "USD"),
                description=args.get("description"),
                reference=args.get("reference"),
                channel=channel,
                call_sid=call_sid,
                idempotency_key=idem_key,
                pms_integration_id=pms.integration_id,
                pms_endpoint_id=pms.endpoint_id,
                pms_vendor_slug=vendor_slug,
                session_key=session_key,
            )

        return service.collect_payment(
            amount=args.get("amount"),
            currency=args.get("currency", "USD"),
            description=args.get("description"),
            reference=args.get("reference"),
            channel=channel,
            call_sid=call_sid,
            idempotency_key=idem_key,
        )

    def _integration_slug(self, integration_id: str) -> Optional[str]:
        """Best-effort vendor slug for a resolved integration (for provenance)."""
        try:
            from botelier.models.integration import AccountIntegration

            integ = (
                self.db.query(AccountIntegration)
                .filter(AccountIntegration.id == integration_id)
                .one_or_none()
            )
            itype = integ.integration_type if integ is not None else None
            return getattr(itype, "slug", None)
        except Exception:  # noqa: BLE001
            return None

    async def execute(
        self,
        capability_name: str,
        *,
        channel: str,
        arguments: Optional[Dict[str, Any]] = None,
        extra_variables: Optional[Dict[str, Any]] = None,
        call_sid: Optional[str] = None,
        contact_ref: Optional[str] = None,
        source_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resolve + execute a capability (async). Returns the LLM-facing payload.

        ``contact_ref`` is the per-conversation dedup scope for channels without a
        ``call_sid`` (SMS conversation id, simulator session id); see
        :meth:`_idempotency_for`.
        """
        from botelier.services.action_executor import ActionExecutor

        spec = get_capability(capability_name)
        if spec is not None and spec.service_backed:
            # Provider calls may block; keep the event loop free.
            import asyncio

            return await asyncio.to_thread(
                self._service_backed_payment,
                capability_name,
                arguments,
                channel,
                call_sid,
                contact_ref,
            )

        prepared, error = self._prepare(capability_name, arguments, extra_variables)
        if error:
            return error
        resolution, vendor_vars = prepared
        idempotency = self._idempotency_for(
            capability_name, arguments, call_sid, contact_ref
        )
        request = self._build_request(
            resolution,
            vendor_vars,
            capability_name,
            channel,
            call_sid,
            source_label,
            idempotency,
        )
        result = await ActionExecutor(self.db).execute_and_log(request)
        return format_capability_result(result)

    def execute_sync(
        self,
        capability_name: str,
        *,
        channel: str,
        arguments: Optional[Dict[str, Any]] = None,
        extra_variables: Optional[Dict[str, Any]] = None,
        call_sid: Optional[str] = None,
        contact_ref: Optional[str] = None,
        source_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Synchronous bridge for the SMS path (no running event loop).

        SMS has no ``call_sid``; callers MUST pass the SMS conversation id as
        ``contact_ref`` so mutating capabilities dedup per conversation rather than
        colliding across guests (see :meth:`_idempotency_for`).
        """
        from botelier.services.action_executor import execute_action_sync

        spec = get_capability(capability_name)
        if spec is not None and spec.service_backed:
            return self._service_backed_payment(
                capability_name, arguments, channel, call_sid, contact_ref
            )

        prepared, error = self._prepare(capability_name, arguments, extra_variables)
        if error:
            return error
        resolution, vendor_vars = prepared
        idempotency = self._idempotency_for(
            capability_name, arguments, call_sid, contact_ref
        )
        request = self._build_request(
            resolution,
            vendor_vars,
            capability_name,
            channel,
            call_sid,
            source_label,
            idempotency,
        )
        result = execute_action_sync(self.db, request)
        return format_capability_result(result)
