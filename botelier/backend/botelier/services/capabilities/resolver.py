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

    def _build_request(
        self,
        resolution: Resolution,
        vendor_vars: Dict[str, Any],
        capability_name: str,
        channel: str,
        call_sid: Optional[str],
        source_label: Optional[str],
    ):
        from botelier.services.action_executor import ActionContext, ActionExecutionRequest
        from botelier.services.integration_runtime.types import IntegrationAPIConfig

        config = IntegrationAPIConfig(
            integration_id=resolution.integration_id,
            endpoint_id=resolution.endpoint_id,
            method=resolution.method,
        )
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
        )

    async def execute(
        self,
        capability_name: str,
        *,
        channel: str,
        arguments: Optional[Dict[str, Any]] = None,
        extra_variables: Optional[Dict[str, Any]] = None,
        call_sid: Optional[str] = None,
        source_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resolve + execute a capability (async). Returns the LLM-facing payload."""
        from botelier.services.action_executor import ActionExecutor

        prepared, error = self._prepare(capability_name, arguments, extra_variables)
        if error:
            return error
        resolution, vendor_vars = prepared
        request = self._build_request(
            resolution, vendor_vars, capability_name, channel, call_sid, source_label
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
        source_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Synchronous bridge for the SMS path (no running event loop)."""
        from botelier.services.action_executor import execute_action_sync

        prepared, error = self._prepare(capability_name, arguments, extra_variables)
        if error:
            return error
        resolution, vendor_vars = prepared
        request = self._build_request(
            resolution, vendor_vars, capability_name, channel, call_sid, source_label
        )
        result = execute_action_sync(self.db, request)
        return format_capability_result(result)
