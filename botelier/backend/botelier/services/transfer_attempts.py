"""Fenced transfer attempts in the existing operation ledger.

Unlike generic business operations, an issued carrier update has NO lease
takeover. Losing its response is not evidence that it is safe to repeat.
Only a definite rejection, or cancellation before dispatch, permits a new
attempt. No target number, credential or transcript is stored here.
"""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import text


@dataclass(frozen=True)
class TransferAttempt:
    attempt_id: str
    phase: str
    owned: bool = False


class TransferAttempts:
    def __init__(self, session_factory=None):
        self.session_factory = session_factory

    def _session(self):
        if self.session_factory is not None:
            return self.session_factory()
        from botelier.database import SessionLocal
        return SessionLocal()

    @staticmethod
    def _scope(account_id, call_sid):
        account = str(UUID(str(account_id)))
        if (
            not isinstance(call_sid, str) or not 1 <= len(call_sid) <= 128
            or not all(c.isascii() and (c.isalnum() or c in "_-") for c in call_sid)
        ):
            raise ValueError("Invalid call identity")
        digest = hashlib.sha256(f"{account}:{call_sid}".encode()).hexdigest()
        return {"key": "voice-transfer:" + digest, "account_id": account}

    @staticmethod
    def _read(db, scope):
        row = db.execute(text("""
            /* voice_transfer.read */
            SELECT result FROM operation_idempotency
            WHERE idempotency_key = :key AND account_id = CAST(:account_id AS UUID)
              AND operation = 'voice_transfer'
            FOR UPDATE
        """), scope).fetchone()
        if row is None:
            return None
        data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        if (
            not isinstance(data, dict)
            or data.get("phase") not in {"reserved", "issued", "unconfirmed", "accepted", "rejected"}
            or str(UUID(data.get("attempt_id", ""))) != data.get("attempt_id")
        ):
            raise ValueError("Invalid persisted transfer state")
        return data

    @staticmethod
    def _write(db, scope, data):
        status = (
            "succeeded" if data["phase"] == "accepted"
            else "failed" if data["phase"] == "rejected" else "pending"
        )
        changed = db.execute(text("""
            /* voice_transfer.write */
            UPDATE operation_idempotency SET result = CAST(:result AS JSONB),
                status = :status, updated_at = :now
            WHERE idempotency_key = :key AND account_id = CAST(:account_id AS UUID)
              AND operation = 'voice_transfer'
        """), {**scope, "result": json.dumps(data), "status": status, "now": datetime.utcnow()})
        if changed.rowcount != 1:
            raise RuntimeError("Transfer state disappeared")

    def claim(self, account_id, call_sid):
        scope = self._scope(account_id, call_sid)
        data = {"attempt_id": str(uuid4()), "phase": "reserved"}
        db = self._session()
        try:
            inserted = db.execute(text("""
                /* voice_transfer.insert */
                INSERT INTO operation_idempotency (
                    id, idempotency_key, account_id, operation, status, result,
                    created_at, updated_at, expires_at
                ) VALUES (
                    CAST(:id AS UUID), :key, CAST(:account_id AS UUID),
                    'voice_transfer', 'pending', CAST(:result AS JSONB),
                    :now, :now, NULL
                ) ON CONFLICT (idempotency_key) DO NOTHING
            """), {**scope, "id": str(uuid4()), "result": json.dumps(data), "now": datetime.utcnow()})
            owned = inserted.rowcount == 1
            if not owned:
                data = self._read(db, scope)
                if data is None:
                    raise RuntimeError("Transfer claim conflict without an owned row")
                if data["phase"] == "rejected":
                    data = {"attempt_id": str(uuid4()), "phase": "reserved"}
                    self._write(db, scope, data)
                    owned = True
            db.commit()
            return TransferAttempt(data["attempt_id"], data["phase"], owned)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, account_id, call_sid):
        db = self._session()
        try:
            data = self._read(db, self._scope(account_id, call_sid))
            return TransferAttempt(data["attempt_id"], data["phase"]) if data else None
        finally:
            db.close()

    def issue(self, account_id, call_sid, attempt_id):
        """Commit the issued marker BEFORE entering the external SDK."""
        return self._change(account_id, call_sid, attempt_id, "issued")

    def settle(self, account_id, call_sid, attempt_id, outcome, *, definite_rejection=False):
        if outcome not in {"accepted", "unconfirmed", "rejected"}:
            raise ValueError("Invalid transfer outcome")
        return self._change(
            account_id, call_sid, attempt_id, outcome,
            definite_rejection=definite_rejection,
        )

    def observe(self, account_id, call_sid, attempt_id, child_sid, status):
        # A signed parent alone does not identify the issued attempt.
        ranks = {"initiated": 0, "ringing": 1, "in-progress": 2,
                 "completed": 3, "busy": 3, "failed": 3, "no-answer": 3, "canceled": 3}
        if (
            status not in ranks or child_sid == call_sid
            or not isinstance(child_sid, str) or not 1 <= len(child_sid) <= 128
            or not all(c.isascii() and (c.isalnum() or c in "_-") for c in child_sid)
        ):
            return False

        def callback(data):
            if data["phase"] not in {"issued", "unconfirmed", "accepted"}:
                return False
            if data.get("child_sid") not in (None, child_sid):
                return False
            old = data.get("callback_status")
            if old is not None and ranks[old] >= ranks[status]:
                return True
            data.update(phase="accepted", child_sid=child_sid, callback_status=status)
            return True

        return self._change(account_id, call_sid, attempt_id, callback)

    def _change(self, account_id, call_sid, attempt_id, outcome, *, definite_rejection=False):
        scope = self._scope(account_id, call_sid)
        if str(UUID(str(attempt_id))) != attempt_id:
            raise ValueError("Invalid attempt identity")
        db = self._session()
        try:
            data = self._read(db, scope)
            if data is None or data["attempt_id"] != attempt_id:
                return False
            if callable(outcome):
                if not outcome(data):
                    return False
            elif outcome == "issued":
                if data["phase"] != "reserved":
                    return False
                data["phase"] = "issued"
            elif data["phase"] != "accepted":
                if outcome == "rejected" and data["phase"] != "reserved" and not definite_rejection:
                    data["phase"] = "unconfirmed"
                else:
                    data["phase"] = outcome
            self._write(db, scope, data)
            db.commit()
            return TransferAttempt(data["attempt_id"], data["phase"])
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
