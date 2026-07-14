"""Cross-session operation idempotency ledger (Task #330).

Backs the in-memory non-GET guard with a durable row so a mutating operation
(booking, charge) fires at most once even across a websocket dropout + reconnect
on a fresh worker.

Protocol (all keyed by a caller-stable ``idempotency_key``):

1. ``claim`` — ``INSERT ... ON CONFLICT DO NOTHING``.
   - Inserted → **EXECUTE** (this caller owns the key; run the op).
   - Row already ``succeeded`` → **RETURN_STORED** (hand back the saved result).
   - Row ``pending`` and fresh (updated within the lease) → **IN_PROGRESS**
     (another worker is mid-flight; refuse the duplicate).
   - Row ``pending`` and stale (lease elapsed) or ``failed`` → optimistic
     compare-and-swap takeover → **EXECUTE** if we win the CAS, else IN_PROGRESS.
2. ``complete`` — stamp ``succeeded`` + store the result.
3. ``fail`` — stamp ``failed`` so a later retry can take over.

Isolation: every call runs in its own short-lived session (``SessionLocal``),
independent of the caller's business transaction — the ledger is a durable
side-record, committed on its own.

Known limit (documented, accepted for v1): if a worker completes the vendor
write but dies before ``complete``, the row stays ``pending``; a later retry
past the lease takes over and re-executes → a rare double-write. True
exactly-once requires the downstream vendor to honour the same key — which the
payment path does by forwarding ``idempotency_key`` to the processor.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

EXECUTE = "execute"
RETURN_STORED = "return_stored"
IN_PROGRESS = "in_progress"

# How long a worker's execution lease is trusted. A pending row not touched
# within this window is assumed abandoned (worker died) and may be taken over.
LEASE_SECONDS = 30
# How long terminal rows are retained so late duplicates still dedup.
TTL_SECONDS = 24 * 3600


@dataclass
class IdempotencyClaim:
    outcome: str
    stored_result: Optional[dict] = None


class IdempotencyLedger:
    """Durable claim/complete/fail ledger for mutating operations."""

    def __init__(self, session_factory: Optional[Callable[[], Any]] = None):
        self._session_factory = session_factory

    def _session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from botelier.database import SessionLocal

        return SessionLocal()

    def claim(
        self,
        key: str,
        account_id: Optional[str],
        property_id: Optional[str],
        operation: Optional[str],
        args_hash: Optional[str],
    ) -> IdempotencyClaim:
        """Attempt to claim ``key`` for execution. See module docstring."""
        db = self._session()
        try:
            now = datetime.utcnow()
            params = {
                "key": key,
                "account_id": account_id,
                "property_id": property_id,
                "operation": operation,
                "args_hash": args_hash,
                "now": now,
                "expires": now + timedelta(seconds=TTL_SECONDS),
            }
            inserted = db.execute(
                text(
                    """
                    INSERT INTO operation_idempotency (
                        id, idempotency_key, account_id, property_id, operation,
                        args_hash, status, created_at, updated_at, expires_at
                    ) VALUES (
                        gen_random_uuid(), :key, CAST(:account_id AS UUID),
                        CAST(:property_id AS UUID), :operation, :args_hash,
                        'pending', :now, :now, :expires
                    )
                    ON CONFLICT (idempotency_key) DO NOTHING
                    """
                ),
                params,
            )
            db.commit()
            if inserted.rowcount == 1:
                return IdempotencyClaim(EXECUTE)

            row = db.execute(
                text(
                    """
                    SELECT status, result, updated_at
                    FROM operation_idempotency
                    WHERE idempotency_key = :key
                    """
                ),
                {"key": key},
            ).fetchone()
            if row is None:
                # Only reachable if a sweeper deleted the row between the
                # conflict and this read. Re-running is correct (a fresh op).
                logger.warning("idempotency: conflict row vanished for key=%s", key)
                return IdempotencyClaim(EXECUTE)

            status, result, updated_at = row[0], row[1], row[2]
            if status == "succeeded":
                stored = result
                if isinstance(stored, str):
                    try:
                        stored = json.loads(stored)
                    except (ValueError, TypeError):
                        stored = None
                return IdempotencyClaim(RETURN_STORED, stored)

            lease_elapsed = (
                updated_at is None
                or (now - updated_at).total_seconds() > LEASE_SECONDS
            )
            if status == "failed" or lease_elapsed:
                took_over = db.execute(
                    text(
                        """
                        UPDATE operation_idempotency
                        SET status = 'pending', updated_at = :now
                        WHERE idempotency_key = :key AND updated_at = :seen
                        """
                    ),
                    {"now": now, "key": key, "seen": updated_at},
                )
                db.commit()
                if took_over.rowcount == 1:
                    return IdempotencyClaim(EXECUTE)
                return IdempotencyClaim(IN_PROGRESS)

            return IdempotencyClaim(IN_PROGRESS)
        finally:
            db.close()

    def complete(self, key: str, result: dict) -> None:
        """Mark the operation succeeded and persist its result."""
        db = self._session()
        try:
            db.execute(
                text(
                    """
                    UPDATE operation_idempotency
                    SET status = 'succeeded',
                        result = CAST(:result AS JSONB),
                        updated_at = :now
                    WHERE idempotency_key = :key
                    """
                ),
                {
                    "result": json.dumps(result, default=str),
                    "now": datetime.utcnow(),
                    "key": key,
                },
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001 - bookkeeping must not crash caller
            db.rollback()
            logger.warning("idempotency: complete failed for key=%s: %s", key, exc)
        finally:
            db.close()

    def fail(self, key: str) -> None:
        """Mark the operation failed so a later retry can take over."""
        db = self._session()
        try:
            db.execute(
                text(
                    """
                    UPDATE operation_idempotency
                    SET status = 'failed', updated_at = :now
                    WHERE idempotency_key = :key
                    """
                ),
                {"now": datetime.utcnow(), "key": key},
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001 - bookkeeping must not crash caller
            db.rollback()
            logger.warning("idempotency: fail marking failed for key=%s: %s", key, exc)
        finally:
            db.close()
