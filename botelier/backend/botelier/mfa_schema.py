"""Additive MFA schema changes and a fail-closed startup invariant.

Kept independent of database initialization so the exact statements can be
exercised against a disposable legacy schema without importing app startup.
The existing database migration runner remains the sole startup runner.
"""

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, Uuid, inspect
from sqlalchemy.exc import SQLAlchemyError


MFA_ADDITIVE_MIGRATIONS = (
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_secret_encrypted TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_last_step BIGINT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_version INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_recovery_required BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS primary_credentials_revoked_at TIMESTAMP",
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS require_mfa BOOLEAN NOT NULL DEFAULT FALSE",
    # Existing model tables are created by create_all. This also supports a
    # previously created MFA table without granting recovery to any old session.
    "ALTER TABLE mfa_sessions ADD COLUMN IF NOT EXISTS recovery_grant BOOLEAN NOT NULL DEFAULT FALSE",
)

_REQUIRED_COLUMNS = {
    "users": {
        "mfa_enabled": (Boolean, False),
        "mfa_secret_encrypted": (Text, True),
        "mfa_last_step": (BigInteger, True),
        "mfa_version": (Integer, False),
        "mfa_recovery_required": (Boolean, False),
        "primary_credentials_revoked_at": (DateTime, True),
    },
    "accounts": {"require_mfa": (Boolean, False)},
    "mfa_sessions": {
        "id": (String, False),
        "user_id": (Uuid, False),
        "version": (Integer, False),
        "primary_at": (DateTime, False),
        "verified_at": (DateTime, True),
        "expires_at": (DateTime, False),
        "restricted": (Boolean, False),
        "recovery_grant": (Boolean, False),
        "revoked": (Boolean, False),
        "pending_secret_encrypted": (Text, True),
        "pending_expires_at": (DateTime, True),
        "attempts": (Integer, False),
        "created_at": (DateTime, False),
    },
    "mfa_recovery_codes": {
        "code_hash": (String, False),
        "user_id": (Uuid, False),
        "consumed_at": (DateTime, True),
    },
    "mfa_rate_limits": {
        "key": (String, False),
        "window_started_at": (DateTime, False),
        "attempts": (Integer, False),
    },
    "mfa_audit_events": {
        "id": (Uuid, False),
        "user_id": (Uuid, True),
        "event": (String, False),
        "account_id": (Uuid, True),
        "created_at": (DateTime, False),
    },
}

_PRIMARY_KEYS = {
    "mfa_sessions": ["id"],
    "mfa_recovery_codes": ["code_hash"],
    "mfa_rate_limits": ["key"],
    "mfa_audit_events": ["id"],
}

_SCHEMA_ERROR = (
    "MFA schema is incomplete or incompatible; authentication startup refused."
)


def assert_mfa_schema(connection):
    """Refuse startup if a skipped migration would weaken or break assurance."""
    try:
        inspector = inspect(connection)
        for table, expected in _REQUIRED_COLUMNS.items():
            columns = {
                column["name"]: column for column in inspector.get_columns(table)
            }
            for name, (kind, nullable) in expected.items():
                column = columns.get(name)
                if (
                    column is None
                    or not isinstance(column["type"], kind)
                    or column["nullable"] is not nullable
                ):
                    raise RuntimeError(_SCHEMA_ERROR)
            if table in _PRIMARY_KEYS and (
                inspector.get_pk_constraint(table)["constrained_columns"]
                != _PRIMARY_KEYS[table]
            ):
                raise RuntimeError(_SCHEMA_ERROR)
    except SQLAlchemyError:
        # Do not carry connection strings or driver exception details into
        # authentication errors. The application must not continue without it.
        raise RuntimeError(_SCHEMA_ERROR) from None
