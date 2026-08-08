"""Token-refresh advisory-lock helpers and tuning constants.

Extracted verbatim from the former ``integration_client`` monolith. The core
``IntegrationClient`` still owns the holder/waiter logic in
``_refresh_token_with_lock``; these are the deterministic key derivation, the
safe raw-connection close, and the timing constants it relies on.
"""

import hashlib
import uuid


class TokenRefreshLockUnavailableError(Exception):
    """Raised when the advisory lock for token refresh cannot be acquired
    after retries due to a database infrastructure failure.

    Callers must treat this as a transient AUTH_ERROR and must NOT run an
    unlocked refresh — doing so risks concurrent double-refresh against
    providers that rotate refresh tokens on use.
    """


def _advisory_lock_key(integration_id) -> int:
    """Derive a stable signed 64-bit Postgres advisory-lock key for a connection.

    Python's built-in hash() is randomized per process (PYTHONHASHSEED), so it
    would produce a different key on every replica and the lock would serialize
    nothing.  We use a namespaced BLAKE2b digest of the integration UUID so the
    key is identical across all workers, and reserve the namespace prefix in
    case advisory locks are used for other purposes later.
    """
    if isinstance(integration_id, uuid.UUID):
        id_bytes = integration_id.bytes
    else:
        id_bytes = uuid.UUID(str(integration_id)).bytes
    digest = hashlib.blake2b(
        b"integ-token-refresh:" + id_bytes, digest_size=8
    ).digest()
    return int.from_bytes(digest, "big", signed=True)


def _safe_close(conn) -> None:
    """Return a raw connection to the pool, swallowing any close error."""
    try:
        conn.close()
    except Exception:
        pass


# Proactively refresh a token this many seconds BEFORE its hard expiry so a
# request never races the expiry boundary and comes back 401 mid-call.
_TOKEN_REFRESH_SKEW_S = 60

# Waiter (non-holder) settings for the cross-worker refresh lock. The timeout
# comfortably exceeds a normal provider login while a burst of waiters poll the
# row (rather than each pinning a DB connection) until the holder finishes.
_REFRESH_WAIT_TIMEOUT_S = 45.0
_REFRESH_POLL_INTERVAL_S = 0.2

# Lock-acquisition retry budget for the holder path. On DB infrastructure
# failures (connection open or pg_try_advisory_lock execute) we retry this many
# times with short exponential backoff before raising
# TokenRefreshLockUnavailableError.  Never fall through to an unlocked refresh.
# Two retries: 0.25 s then 0.5 s — keeps voice-call latency impact under 1 s.
_LOCK_ACQUIRE_RETRIES = 2
_LOCK_ACQUIRE_BACKOFF_S = 0.25
