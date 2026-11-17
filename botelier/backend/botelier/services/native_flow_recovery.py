"""Optimistic, tenant-scoped snapshots for native voice flow recovery."""

from copy import deepcopy
import hashlib
import json
from uuid import UUID

_CHANNEL = "native"
_KEY = "native_flow"
_MAX_SNAPSHOT_BYTES = 250_000
_ACTIVE = "active"
_COMPLETE = "complete"
_ABANDONED = "abandoned"


class NativeFlowRecoveryError(ValueError):
    """Safe fail-closed category for invalid or conflicting recovery state."""


def native_flow_source_digest(compiled):
    source = compiled._config_json
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def native_flow_identity(compiled):
    identity = compiled.identity
    return {
        "account_id": identity.account_id,
        "property_id": identity.property_id,
        "tool_id": identity.tool_id,
        "flow_version_id": identity.flow_version_id,
        "call_sid": identity.call_sid,
    }


def _uuid(value, code):
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise NativeFlowRecoveryError(code) from None


def _json_copy(value):
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
        )
        if len(encoded.encode("utf-8")) > _MAX_SNAPSHOT_BYTES:
            raise ValueError
        copied = json.loads(encoded)
    except (TypeError, ValueError, RecursionError, OverflowError):
        raise NativeFlowRecoveryError("native_recovery_snapshot_invalid") from None
    if not isinstance(copied, dict):
        raise NativeFlowRecoveryError("native_recovery_snapshot_invalid")
    return copied


class NativeFlowSnapshotStore:
    """Persist only provenance-bearing caller facts and a pinned source identity.

    The existing FlowSession row is keyed by call and root tool. The JSONB value
    carries the native revision and active subflow identity. Updates compare the
    complete prior JSON document in the database, so an expired worker cannot
    overwrite a newer snapshot.
    """

    def __init__(self, session_factory, flow_session_model=None):
        if not callable(session_factory):
            raise NativeFlowRecoveryError("native_recovery_storage_unavailable")
        self._session_factory = session_factory
        self._flow_session_model = flow_session_model

    @property
    def _model(self):
        if self._flow_session_model is None:
            from botelier.models.flow_session import FlowSession

            self._flow_session_model = FlowSession
        return self._flow_session_model

    def load_pinned(self, *, call_sid, account_id, property_id, assigned_tool_ids):
        """Load a call snapshot before selecting a version; reject scope drift."""
        model = self._model
        db = self._session_factory()
        try:
            rows = db.query(model).filter(
                model.session_key == str(call_sid),
                model.channel == _CHANNEL,
            ).all()
            if not rows:
                return None
            if len(rows) != 1:
                raise NativeFlowRecoveryError("native_recovery_ambiguous")
            row = rows[0]
            payload = self._payload(row)
            identity = payload["root"]
            expected_row_status = (
                _COMPLETE if payload["state"] == "complete"
                else _ABANDONED if payload["state"] in {"failed", "closed"}
                else _ACTIVE
            )
            if (
                row.status != expected_row_status
                or row.account_id is None
                or str(row.account_id) != str(account_id)
                or row.property_id is None
                or str(row.property_id) != str(property_id)
                or str(row.tool_id) != identity["tool_id"]
                or str(row.flow_version_id) != identity["flow_version_id"]
                or str(row.session_key) != identity["call_sid"]
                or identity["account_id"] != str(account_id)
                or identity["property_id"] != str(property_id)
                or identity["call_sid"] != str(call_sid)
                or identity["tool_id"] not in {
                    str(item) for item in assigned_tool_ids
                }
            ):
                raise NativeFlowRecoveryError("native_recovery_scope_mismatch")
            return payload
        finally:
            db.close()

    def save(self, snapshot, expected_revision):
        """Create or CAS-update one native call snapshot in a short transaction."""
        payload = _json_copy(snapshot)
        root = payload.get("root")
        if not isinstance(root, dict):
            raise NativeFlowRecoveryError("native_recovery_snapshot_invalid")
        if type(expected_revision) is not int or expected_revision < 0:
            raise NativeFlowRecoveryError("native_recovery_revision")
        next_revision = expected_revision + 1
        payload["revision"] = next_revision
        payload = _json_copy({_KEY: payload})
        identity = payload[_KEY]["root"]
        account_id = _uuid(identity.get("account_id"), "native_recovery_identity")
        property_id = _uuid(identity.get("property_id"), "native_recovery_identity")
        tool_id = _uuid(identity.get("tool_id"), "native_recovery_identity")
        version_id = _uuid(identity.get("flow_version_id"), "native_recovery_identity")
        session_key = identity.get("call_sid")
        if not isinstance(session_key, str) or not session_key or len(session_key) > 255:
            raise NativeFlowRecoveryError("native_recovery_identity")
        if identity.get("account_id") != str(account_id) or identity.get("property_id") != str(property_id):
            raise NativeFlowRecoveryError("native_recovery_identity")
        state = payload[_KEY].get("state")
        status = (
            _COMPLETE if state == "complete"
            else _ABANDONED if state in {"failed", "closed"}
            else _ACTIVE
        )

        model = self._model
        db = self._session_factory()
        try:
            row = db.query(model).filter(
                model.session_key == session_key,
                model.channel == _CHANNEL,
                model.tool_id == tool_id,
            ).first()
            if row is None:
                if expected_revision != 0:
                    raise NativeFlowRecoveryError("native_recovery_stale_update")
                row = model(
                    account_id=account_id,
                    property_id=property_id,
                    channel=_CHANNEL,
                    session_key=session_key,
                    tool_id=tool_id,
                    flow_version_id=version_id,
                    current_node_id=payload[_KEY].get("current_node_id"),
                    collected_slots=payload,
                    status=status,
                )
                db.add(row)
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                    raise NativeFlowRecoveryError(
                        "native_recovery_stale_update",
                    ) from None
                return next_revision

            old_payload = _json_copy(row.collected_slots or {})
            old_revision = old_payload.get(_KEY, {}).get("revision")
            if (
                old_revision != expected_revision
                or str(row.account_id) != str(account_id)
                or str(row.property_id) != str(property_id)
                or str(row.flow_version_id) != str(version_id)
                or row.status != _ACTIVE
            ):
                raise NativeFlowRecoveryError("native_recovery_stale_update")

            updated = db.query(model).filter(
                model.id == row.id,
                model.status == _ACTIVE,
                model.collected_slots == old_payload,
            ).update({
                model.current_node_id: payload[_KEY].get("current_node_id"),
                model.collected_slots: payload,
                model.status: status,
            }, synchronize_session=False)
            if updated != 1:
                db.rollback()
                raise NativeFlowRecoveryError("native_recovery_stale_update")
            db.commit()
            return next_revision
        except NativeFlowRecoveryError:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _payload(row):
        document = _json_copy(row.collected_slots or {})
        payload = document.get(_KEY)
        if not isinstance(payload, dict):
            raise NativeFlowRecoveryError("native_recovery_snapshot_invalid")
        if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
            raise NativeFlowRecoveryError("native_recovery_version")
        if (
            type(payload.get("revision")) is not int
            or payload["revision"] < 1
            or payload.get("state") not in {
                "active", "pending_effect", "terminal_pending",
                "effect_committed", "complete", "failed", "closed",
            }
        ):
            raise NativeFlowRecoveryError("native_recovery_snapshot_invalid")
        root = payload.get("root")
        active = payload.get("active")
        if not isinstance(root, dict) or not isinstance(active, dict):
            raise NativeFlowRecoveryError("native_recovery_snapshot_invalid")
        identity_keys = {
            "account_id", "property_id", "tool_id", "flow_version_id", "call_sid",
        }
        if (
            set(root) != identity_keys
            or set(active) != identity_keys | {"source_digest"}
            or any(
                not isinstance(value, str) or not value or len(value) > 255
                for value in root.values()
            )
            or any(
                not isinstance(active.get(key), str)
                or not active[key] or len(active[key]) > 255
                for key in identity_keys
            )
            or not isinstance(active.get("source_digest"), str)
            or len(active["source_digest"]) != 64
            or not isinstance(payload.get("source_digest"), str)
            or len(payload["source_digest"]) != 64
        ):
            raise NativeFlowRecoveryError("native_recovery_identity")
        return deepcopy(payload)
