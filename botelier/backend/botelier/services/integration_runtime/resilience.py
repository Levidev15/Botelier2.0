"""Cross-worker resilience primitives for the integration runtime (Task #331).

Three concerns live here, all keyed by ``integration_id`` and all backed by
Postgres so state is shared across every stateless replica:

  1. **Rate limiting** — a lazy token bucket (``rate_limit_acquire``). Protects a
     provider (and our own outbound budget) from a runaway flow / burst.
  2. **Retry backoff** — pure functions (``compute_backoff_delay``,
     ``parse_retry_after``) the client uses to space out retries with
     exponential backoff + full jitter, honoring a server ``Retry-After``.
  3. **Circuit breaking** — a per-integration breaker (``circuit_allow`` /
     ``circuit_record_success`` / ``circuit_record_failure``). Trips OPEN after
     repeated provider failures so we stop hammering a down vendor and instead
     surface a fast, LLM-friendly "temporarily unavailable" error.

Cross-worker correctness: every stateful op runs in its OWN short-lived
``SessionLocal`` transaction and takes ``SELECT ... FOR UPDATE`` on the single
row, so concurrent workers serialize on Postgres row locks — never on
per-process memory. These ops NEVER reuse the caller's DB session (committing it
would flush the caller's unrelated pending work, and in unit tests the caller's
``db`` may be a ``MagicMock``).

Fail-open by design: if the resilience infrastructure itself errors (DB blip,
etc.) we allow the request rather than block a live call — a resilience bug must
never take down the integration path it is meant to protect.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Optional, Tuple

from loguru import logger
from sqlalchemy import text

from botelier.models.integration_resilience import CircuitState

# --- Defaults ---------------------------------------------------------------
# Generous by design: the bucket rarely trips for a single healthy connection
# during a call, but a runaway loop or a genuinely-down vendor is still caught.
_DEFAULT_RATE_LIMIT_ENABLED = True
_DEFAULT_RATE_CAPACITY = 30.0
_DEFAULT_RATE_REFILL_PER_SEC = 15.0

_DEFAULT_BREAKER_ENABLED = True
_DEFAULT_BREAKER_THRESHOLD = 5
_DEFAULT_BREAKER_COOLDOWN_S = 30.0

_DEFAULT_BACKOFF_BASE_S = 0.2
_DEFAULT_BACKOFF_FACTOR = 2.0
_DEFAULT_BACKOFF_MAX_S = 5.0
_DEFAULT_BACKOFF_JITTER = True


SessionFactory = Callable[[], Any]


def _default_session_factory():
    # Imported lazily to avoid a circular import at module load and to always
    # bind to the app's configured engine.
    from botelier.database import SessionLocal

    return SessionLocal()


def _open_session(session_factory: Optional[SessionFactory]):
    return (session_factory or _default_session_factory)()


@dataclass
class ResilienceConfig:
    """Per-integration resilience knobs, with safe defaults.

    Resolved by merging (lowest → highest priority):
      1. built-in defaults
      2. the integration type's ``auth_config["resilience"]``
      3. the connection's ``connection_config["resilience"]``
    so an operator can tune a specific connection without a code change.
    """

    rate_limit_enabled: bool = _DEFAULT_RATE_LIMIT_ENABLED
    rate_limit_capacity: float = _DEFAULT_RATE_CAPACITY
    rate_limit_refill_per_sec: float = _DEFAULT_RATE_REFILL_PER_SEC

    breaker_enabled: bool = _DEFAULT_BREAKER_ENABLED
    breaker_failure_threshold: int = _DEFAULT_BREAKER_THRESHOLD
    breaker_cooldown_s: float = _DEFAULT_BREAKER_COOLDOWN_S

    backoff_base_s: float = _DEFAULT_BACKOFF_BASE_S
    backoff_factor: float = _DEFAULT_BACKOFF_FACTOR
    backoff_max_s: float = _DEFAULT_BACKOFF_MAX_S
    backoff_jitter: bool = _DEFAULT_BACKOFF_JITTER

    @classmethod
    def _coerce(cls, base: "ResilienceConfig", overrides: dict) -> "ResilienceConfig":
        if not isinstance(overrides, dict):
            return base
        merged = {**base.__dict__}
        for key in merged:
            if key in overrides and overrides[key] is not None:
                merged[key] = overrides[key]
        try:
            return cls(
                rate_limit_enabled=bool(merged["rate_limit_enabled"]),
                rate_limit_capacity=float(merged["rate_limit_capacity"]),
                rate_limit_refill_per_sec=float(merged["rate_limit_refill_per_sec"]),
                breaker_enabled=bool(merged["breaker_enabled"]),
                breaker_failure_threshold=int(merged["breaker_failure_threshold"]),
                breaker_cooldown_s=float(merged["breaker_cooldown_s"]),
                backoff_base_s=float(merged["backoff_base_s"]),
                backoff_factor=float(merged["backoff_factor"]),
                backoff_max_s=float(merged["backoff_max_s"]),
                backoff_jitter=bool(merged["backoff_jitter"]),
            )
        except (TypeError, ValueError):
            # A malformed operator override must never break the request path.
            logger.warning("Invalid resilience override; falling back to defaults")
            return base

    @classmethod
    def from_integration(cls, integration) -> "ResilienceConfig":
        config = cls()
        try:
            auth_config = integration.integration_type.get_auth_config() or {}
            config = cls._coerce(config, auth_config.get("resilience") or {})
        except Exception:
            pass
        try:
            conn_config = integration.get_connection_config() or {}
            config = cls._coerce(config, conn_config.get("resilience") or {})
        except Exception:
            pass
        return config


# --- Retry backoff (pure functions) -----------------------------------------


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse a ``Retry-After`` header value into seconds.

    Supports the delta-seconds form (an integer). The HTTP-date form is
    intentionally ignored (returns None) — during a live call we prefer our own
    bounded backoff over sleeping until an absolute wall-clock time.
    """
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        try:
            return float(int(value))
        except ValueError:
            return None
    return None


def compute_backoff_delay(
    attempt: int,
    config: ResilienceConfig,
    retry_after: Optional[float] = None,
) -> float:
    """Delay (seconds) before retry ``attempt`` (0-indexed for the first retry).

    Exponential: ``base * factor**attempt``, capped at ``backoff_max_s``. With
    full jitter (AWS-style) the actual sleep is uniform in ``[0, capped]`` to
    de-correlate concurrent retriers. A server ``Retry-After`` takes precedence
    but is still capped by ``backoff_max_s`` so a hostile/huge value can't stall
    a call.
    """
    if retry_after is not None and retry_after >= 0:
        capped = min(float(retry_after), config.backoff_max_s)
        # A small jitter still helps spread a herd released by the same header.
        if config.backoff_jitter and capped > 0:
            return random.uniform(capped * 0.5, capped)
        return capped

    base = config.backoff_base_s * (config.backoff_factor ** max(0, attempt))
    capped = min(base, config.backoff_max_s)
    if capped < 0:
        capped = 0.0
    if config.backoff_jitter:
        return random.uniform(0.0, capped)
    return capped


# --- Rate limiting (Postgres token bucket) ----------------------------------


def rate_limit_acquire(
    integration_id,
    account_id,
    config: ResilienceConfig,
    session_factory: Optional[SessionFactory] = None,
) -> bool:
    """Try to consume one token from the integration's bucket.

    Returns True if a token was available (request may proceed), False if the
    bucket is empty (caller should reject with RATE_LIMITED). Fails open.
    """
    if not config.rate_limit_enabled:
        return True

    iid = str(integration_id)
    aid = str(account_id) if account_id is not None else None
    try:
        db = _open_session(session_factory)
        try:
            # Ensure the row exists (start full), then lock + refill + consume.
            db.execute(
                text(
                    """
                    INSERT INTO integration_rate_limits
                        (integration_id, account_id, tokens, updated_at)
                    VALUES (:iid, :aid, :cap, :now)
                    ON CONFLICT (integration_id) DO NOTHING
                    """
                ),
                {"iid": iid, "aid": aid, "cap": config.rate_limit_capacity, "now": datetime.utcnow()},
            )
            row = db.execute(
                text(
                    """
                    SELECT tokens, updated_at
                    FROM integration_rate_limits
                    WHERE integration_id = :iid
                    FOR UPDATE
                    """
                ),
                {"iid": iid},
            ).first()

            now = datetime.utcnow()
            tokens = float(row.tokens)
            elapsed = max(0.0, (now - row.updated_at).total_seconds())
            tokens = min(
                config.rate_limit_capacity,
                tokens + elapsed * config.rate_limit_refill_per_sec,
            )

            if tokens >= 1.0:
                tokens -= 1.0
                allowed = True
            else:
                allowed = False

            db.execute(
                text(
                    """
                    UPDATE integration_rate_limits
                    SET tokens = :tokens, updated_at = :now
                    WHERE integration_id = :iid
                    """
                ),
                {"tokens": tokens, "now": now, "iid": iid},
            )
            db.commit()
            return allowed
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover - infra failure path
        logger.warning(f"rate_limit_acquire failed open for {iid}: {exc}")
        return True


# --- Circuit breaking (Postgres state machine) ------------------------------


def _ensure_breaker_row(db, iid: str, aid: Optional[str], now: datetime) -> None:
    db.execute(
        text(
            """
            INSERT INTO integration_circuit_breakers
                (integration_id, account_id, state, failure_count, updated_at)
            VALUES (:iid, :aid, :closed, 0, :now)
            ON CONFLICT (integration_id) DO NOTHING
            """
        ),
        {"iid": iid, "aid": aid, "closed": CircuitState.CLOSED, "now": now},
    )


def circuit_allow(
    integration_id,
    account_id,
    config: ResilienceConfig,
    session_factory: Optional[SessionFactory] = None,
) -> Tuple[bool, str]:
    """Decide whether a request may proceed given the breaker state.

    Returns ``(allowed, state)``. Transitions OPEN → HALF_OPEN once the cooldown
    elapses and lets a single probe through; while OPEN (cooldown not elapsed)
    or while another probe is in flight (HALF_OPEN), it returns False. A probe
    that never resolves (worker crash) self-heals after another cooldown. Fails
    open.
    """
    if not config.breaker_enabled:
        return True, CircuitState.CLOSED

    iid = str(integration_id)
    aid = str(account_id) if account_id is not None else None
    try:
        db = _open_session(session_factory)
        try:
            now = datetime.utcnow()
            _ensure_breaker_row(db, iid, aid, now)
            row = db.execute(
                text(
                    """
                    SELECT state, failure_count, opened_at, updated_at
                    FROM integration_circuit_breakers
                    WHERE integration_id = :iid
                    FOR UPDATE
                    """
                ),
                {"iid": iid},
            ).first()

            state = row.state
            cooldown = timedelta(seconds=config.breaker_cooldown_s)

            if state == CircuitState.CLOSED:
                db.commit()
                return True, state

            if state == CircuitState.OPEN:
                if row.opened_at is not None and now >= row.opened_at + cooldown:
                    db.execute(
                        text(
                            """
                            UPDATE integration_circuit_breakers
                            SET state = :half, updated_at = :now
                            WHERE integration_id = :iid
                            """
                        ),
                        {"half": CircuitState.HALF_OPEN, "now": now, "iid": iid},
                    )
                    db.commit()
                    return True, CircuitState.HALF_OPEN
                db.commit()
                return False, CircuitState.OPEN

            if state == CircuitState.HALF_OPEN:
                # A probe is already in flight. Allow a fresh probe only if the
                # previous one went stale (crashed without recording) so the
                # breaker can never wedge permanently.
                if row.updated_at is not None and now - row.updated_at >= cooldown:
                    db.execute(
                        text(
                            """
                            UPDATE integration_circuit_breakers
                            SET updated_at = :now
                            WHERE integration_id = :iid
                            """
                        ),
                        {"now": now, "iid": iid},
                    )
                    db.commit()
                    return True, CircuitState.HALF_OPEN
                db.commit()
                return False, CircuitState.HALF_OPEN

            # Unknown/legacy state — treat as closed.
            db.commit()
            return True, state
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover - infra failure path
        logger.warning(f"circuit_allow failed open for {iid}: {exc}")
        return True, CircuitState.CLOSED


def circuit_record_success(
    integration_id,
    account_id,
    config: ResilienceConfig,
    session_factory: Optional[SessionFactory] = None,
) -> None:
    """Record a successful outcome: reset the breaker to CLOSED."""
    if not config.breaker_enabled:
        return
    iid = str(integration_id)
    aid = str(account_id) if account_id is not None else None
    try:
        db = _open_session(session_factory)
        try:
            now = datetime.utcnow()
            _ensure_breaker_row(db, iid, aid, now)
            db.execute(
                text(
                    """
                    UPDATE integration_circuit_breakers
                    SET state = :closed, failure_count = 0,
                        opened_at = NULL, updated_at = :now
                    WHERE integration_id = :iid
                    """
                ),
                {"closed": CircuitState.CLOSED, "now": now, "iid": iid},
            )
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover - infra failure path
        logger.warning(f"circuit_record_success failed for {iid}: {exc}")


def circuit_record_failure(
    integration_id,
    account_id,
    config: ResilienceConfig,
    session_factory: Optional[SessionFactory] = None,
) -> None:
    """Record a failed outcome and trip the breaker OPEN when warranted.

    A failure while HALF_OPEN (the probe failed) reopens immediately. Otherwise
    the failure count increments and the breaker trips OPEN once it reaches the
    configured threshold.
    """
    if not config.breaker_enabled:
        return
    iid = str(integration_id)
    aid = str(account_id) if account_id is not None else None
    try:
        db = _open_session(session_factory)
        try:
            now = datetime.utcnow()
            _ensure_breaker_row(db, iid, aid, now)
            row = db.execute(
                text(
                    """
                    SELECT state, failure_count
                    FROM integration_circuit_breakers
                    WHERE integration_id = :iid
                    FOR UPDATE
                    """
                ),
                {"iid": iid},
            ).first()

            threshold = max(1, config.breaker_failure_threshold)

            if row.state == CircuitState.HALF_OPEN:
                new_state = CircuitState.OPEN
                new_count = threshold
                opened_at = now
            else:
                new_count = int(row.failure_count) + 1
                if new_count >= threshold:
                    new_state = CircuitState.OPEN
                    opened_at = now
                else:
                    new_state = CircuitState.CLOSED
                    opened_at = None

            db.execute(
                text(
                    """
                    UPDATE integration_circuit_breakers
                    SET state = :state, failure_count = :count,
                        opened_at = :opened_at, updated_at = :now
                    WHERE integration_id = :iid
                    """
                ),
                {
                    "state": new_state,
                    "count": new_count,
                    "opened_at": opened_at,
                    "now": now,
                    "iid": iid,
                },
            )
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover - infra failure path
        logger.warning(f"circuit_record_failure failed for {iid}: {exc}")
