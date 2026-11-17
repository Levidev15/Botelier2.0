"""Fail-closed durable claims for native external effects.

Unlike the compatibility ledger, an abandoned native write never gets a timed
lease takeover. A timeout or lost acknowledgment requires reconciliation, not
another booking/message. The existing table/unique constraint is reused without
a schema migration. Only encrypted bounded mapped outcomes are retained.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime
import hashlib
import json
import re
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from botelier.services.request_templates import PreparedRequestBody
from botelier.voice.flows.native_execution import NativeActionResult
from botelier.voice.flows.pilot_contract import PilotIdentity


_NODE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_AMBIGUOUS = frozenset({
    "effect_outcome_unknown", "outcome_unknown", "timeout", "transport_error", "cancelled",
})


@dataclass(frozen=True)
class NativeEffectClaim:
    outcome: str
    failure_reason: str | None = None
    result: NativeActionResult | None = None
    node_id: str | None = field(default=None, repr=False)
    key: str | None = field(default=None, repr=False)
    token: str | None = field(default=None, repr=False)
    args_hash: str | None = field(default=None, repr=False)


class NativeEffectLedger:
    """Each claim/completion owns and closes its own short-lived transaction."""

    def __init__(self, session_factory, identity):
        if not callable(session_factory) or not isinstance(identity, PilotIdentity):
            raise ValueError("native_effect_identity")
        self.session_factory = session_factory
        # Key scope and database scope must use identical UUID spellings.
        # Uppercase or compact aliases must not acquire a second unique key.
        self.identity = replace(
            identity,
            account_id=str(UUID(identity.account_id)),
            property_id=str(UUID(identity.property_id)),
        )

    def _key(self, node_id):
        if not isinstance(node_id, str) or not _NODE.fullmatch(node_id):
            raise ValueError("native_effect_node")
        identity = self.identity
        encoded = json.dumps([
            "native-effect-v1", identity.account_id, identity.property_id,
            identity.call_sid, identity.tool_id, node_id,
        ], separators=(",", ":"))
        return "native-v1:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _operation(self, node_id):
        # Version is a binding on the existing claim, not a new write key. A
        # reconnect selecting a different version must not repeat an old write.
        version = hashlib.sha256(self.identity.flow_version_id.encode("utf-8")).hexdigest()[:32]
        return f"native:{node_id}:{version}"

    def _scope_matches(self, row, node_id):
        return (
            str(row.account_id) == str(UUID(self.identity.account_id))
            and str(row.property_id) == str(UUID(self.identity.property_id))
            and row.operation == self._operation(node_id)
        )

    @staticmethod
    def _quiet_cleanup(db, method):
        if db is not None:
            try:
                getattr(db, method)()
            except Exception:
                # No cleanup error may leak credentials or reopen permission.
                pass

    @staticmethod
    def _blocked(reason):
        return NativeEffectClaim("blocked", failure_reason=reason)

    def claim(self, node_id, arguments):
        """Commit unique ownership before allowing any external side effect."""
        db = None
        try:
            if not isinstance(arguments, dict):
                return self._blocked("effect_arguments_invalid")
            bounded = PreparedRequestBody("json", arguments).value()
            args_hash = hashlib.sha256(json.dumps(
                bounded, ensure_ascii=False, allow_nan=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            key = self._key(node_id)
            # If outcome encryption is unavailable, do not allow a write first.
            from botelier.crypto import get_cipher
            from botelier.models.operation_idempotency import OperationIdempotency

            get_cipher().encrypt(b"native-effect-preflight")
            db = self.session_factory()
            row_id = uuid4()
            row = OperationIdempotency(
                id=row_id, idempotency_key=key,
                account_id=UUID(self.identity.account_id),
                property_id=UUID(self.identity.property_id),
                operation=self._operation(node_id), args_hash=args_hash,
                status="pending", expires_at=None,
            )
            db.add(row)
            try:
                db.commit()
                return NativeEffectClaim(
                    "execute", node_id=node_id, key=key, token=str(row_id),
                    args_hash=args_hash,
                )
            except IntegrityError:
                db.rollback()
            existing = db.query(OperationIdempotency).filter(
                OperationIdempotency.idempotency_key == key,
            ).first()
            if existing is None:
                # A missing/corrupt conflict row is never permission to write.
                return self._blocked("effect_storage_unavailable")
            if not self._scope_matches(existing, node_id):
                return self._blocked("effect_scope_mismatch")
            if existing.args_hash != args_hash:
                return self._blocked("effect_arguments_changed")
            if existing.status not in {"succeeded", "failed"}:
                return self._blocked("effect_outcome_unknown")
            try:
                sealed = existing.result["sealed"]
                if not isinstance(sealed, str) or len(sealed) > 1_000_000:
                    return self._blocked("effect_result_unavailable")
                payload = json.loads(get_cipher().decrypt(sealed.encode("ascii")).decode("utf-8"))
                result = NativeActionResult(
                    success=payload["success"], branch=payload["branch"],
                    variables=payload["variables"], llm_data=payload["llm_data"],
                    failure_reason=payload["failure_reason"],
                )
                if result.success != (existing.status == "succeeded"):
                    return self._blocked("effect_result_unavailable")
            except Exception:
                return self._blocked("effect_result_unavailable")
            return NativeEffectClaim("replay", result=result)
        except Exception:
            self._quiet_cleanup(db, "rollback")
            return self._blocked("effect_storage_unavailable")
        finally:
            self._quiet_cleanup(db, "close")

    def complete(self, claim, result, *, outcome_known=False):
        """Seal an explicitly classified, known provider/business outcome.

        The broker positively classifies acceptance or definitive rejection;
        uncertain responses leave the claim pending regardless of the
        particular failure_reason string.
        """
        if (
            outcome_known is not True
            or not isinstance(claim, NativeEffectClaim) or claim.outcome != "execute"
            or not isinstance(result, NativeActionResult)
            or result.failure_reason in _AMBIGUOUS
        ):
            return False
        db = None
        try:
            if claim.key != self._key(claim.node_id):
                return False
            from botelier.crypto import get_cipher
            from botelier.models.operation_idempotency import OperationIdempotency

            payload = {
                "success": result.success, "branch": result.branch,
                "variables": result.variables, "llm_data": result.llm_data,
                "failure_reason": result.failure_reason,
            }
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            sealed = get_cipher().encrypt(encoded.encode("utf-8")).decode("ascii")
            db = self.session_factory()
            updated = db.query(OperationIdempotency).filter(
                OperationIdempotency.id == UUID(claim.token),
                OperationIdempotency.idempotency_key == claim.key,
                OperationIdempotency.account_id == UUID(self.identity.account_id),
                OperationIdempotency.property_id == UUID(self.identity.property_id),
                OperationIdempotency.operation == self._operation(claim.node_id),
                OperationIdempotency.args_hash == claim.args_hash,
                OperationIdempotency.status == "pending",
            ).update({
                OperationIdempotency.status: "succeeded" if result.success else "failed",
                OperationIdempotency.result: {"sealed": sealed},
                OperationIdempotency.updated_at: datetime.utcnow(),
            }, synchronize_session=False)
            if updated != 1:
                db.rollback()
                return False
            db.commit()
            return True
        except Exception:
            self._quiet_cleanup(db, "rollback")
            return False
        finally:
            self._quiet_cleanup(db, "close")
