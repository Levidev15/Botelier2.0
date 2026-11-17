"""Actual PostgreSQL schema upgrades, restricted by auth_guard's fixture.

Each case uses a rolled-back private schema on the disposable fixture database.
No application database startup, customer connection or authentication bypass
is involved.
"""

from contextlib import contextmanager
import importlib

import psycopg2
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from auth_guard import FIXTURE_CONNECTION


@contextmanager
def isolated_schema():
    engine = create_engine(
        "postgresql+psycopg2://",
        creator=lambda: psycopg2.connect(**FIXTURE_CONNECTION),
        poolclass=NullPool,
    )
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                identity = connection.execute(text(
                    "SELECT current_database(), inet_server_addr(), current_user"
                )).one()
                assert tuple(identity) == ("voice_auth_fixture", None, "postgres")
                connection.execute(text("CREATE SCHEMA mfa_upgrade_fixture"))
                connection.execute(text("SET LOCAL search_path TO mfa_upgrade_fixture"))
                yield connection
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def mfa_tables(connection):
    # Resolve the real MFA model foreign keys without creating/replacing the
    # legacy identity tables that the test intentionally constructed above.
    from botelier.models.account import Account  # noqa: F401
    from botelier.models.user import User  # noqa: F401
    from botelier.models.mfa import (
        MFAAudit, MFARateLimit, MFARecoveryCode, MFASession,
    )

    for model in (MFASession, MFARecoveryCode, MFARateLimit, MFAAudit):
        model.__table__.create(connection, checkfirst=True)


def legacy_tables(connection):
    # Existing security-relevant identity data must survive, not be recreated.
    connection.execute(text("""
        CREATE TABLE users (
            id UUID PRIMARY KEY, email TEXT NOT NULL, replit_id TEXT,
            password_hash TEXT, user_type TEXT NOT NULL
        )
    """))
    connection.execute(text("""
        CREATE TABLE accounts (id UUID PRIMARY KEY, name TEXT NOT NULL)
    """))
    connection.execute(text("""
        INSERT INTO users (id, email, replit_id, password_hash, user_type)
        VALUES ('00000000-0000-0000-0000-000000000011',
                'migration@fixture.invalid', 'existing-subject',
                'existing-synthetic-password-hash', 'ACCOUNT_USER')
    """))
    connection.execute(text("""
        INSERT INTO accounts (id, name)
        VALUES ('00000000-0000-0000-0000-000000000022', 'Existing fixture')
    """))


def upgrade(connection):
    schema = importlib.import_module("botelier.mfa_schema")
    for statement in schema.MFA_ADDITIVE_MIGRATIONS:
        connection.execute(text(statement))
    schema.assert_mfa_schema(connection)


def test_legacy_upgrade_preserves_identity_and_adds_safe_unenrolled_defaults():
    with isolated_schema() as connection:
        legacy_tables(connection)
        # This is the application's order: create missing model tables before
        # additive columns. create_all alone cannot upgrade users/accounts.
        mfa_tables(connection)
        upgrade(connection)
        row = connection.execute(text("""
            SELECT email, replit_id, password_hash, user_type, mfa_enabled,
                   mfa_secret_encrypted, mfa_last_step, mfa_version,
                   mfa_recovery_required, primary_credentials_revoked_at
            FROM users
        """)).one()
        assert tuple(row) == (
            "migration@fixture.invalid", "existing-subject",
            "existing-synthetic-password-hash", "ACCOUNT_USER",
            False, None, None, 0, False, None,
        )
        assert connection.execute(text("SELECT require_mfa FROM accounts")).scalar_one() is False
        assert set(inspect(connection).get_table_names()) == {
            "users", "accounts", "mfa_sessions", "mfa_recovery_codes",
            "mfa_rate_limits", "mfa_audit_events",
        }


def test_repeated_upgrade_preserves_enrollment_policy_and_recovery_rows():
    with isolated_schema() as connection:
        legacy_tables(connection)
        mfa_tables(connection)
        upgrade(connection)
        connection.execute(text("""
            UPDATE users SET mfa_enabled = TRUE, mfa_version = 7,
                mfa_secret_encrypted = 'synthetic-encrypted-secret',
                mfa_last_step = 60000000, mfa_recovery_required = TRUE,
                primary_credentials_revoked_at = '2026-01-02 03:04:05'
        """))
        connection.execute(text("UPDATE accounts SET require_mfa = TRUE"))
        connection.execute(text("""
            INSERT INTO mfa_recovery_codes (code_hash, user_id)
            VALUES ('synthetic-hash', '00000000-0000-0000-0000-000000000011')
        """))
        upgrade(connection)
        upgrade(connection)
        assert tuple(connection.execute(text("""
            SELECT mfa_enabled, mfa_version, mfa_secret_encrypted, mfa_last_step,
                   mfa_recovery_required,
                   to_char(primary_credentials_revoked_at, 'YYYY-MM-DD HH24:MI:SS')
            FROM users
        """)).one()) == (
            True, 7, "synthetic-encrypted-secret", 60000000, True,
            "2026-01-02 03:04:05",
        )
        assert connection.execute(text("SELECT require_mfa FROM accounts")).scalar_one() is True
        assert connection.execute(text("SELECT count(*) FROM mfa_recovery_codes")).scalar_one() == 1


def test_fresh_actual_model_schema_accepts_the_same_idempotent_upgrade():
    from botelier.models.account import Account
    from botelier.models.user import User

    with isolated_schema() as connection:
        Account.__table__.create(connection)
        User.__table__.create(connection)
        mfa_tables(connection)
        upgrade(connection)
        upgrade(connection)


@pytest.mark.parametrize("missing", [
    "users.mfa_version", "accounts.require_mfa", "mfa_sessions.recovery_grant",
    "mfa_recovery_codes.consumed_at", "mfa_rate_limits.attempts",
])
def test_missing_security_schema_fails_closed_without_exposing_database_details(missing):
    with isolated_schema() as connection:
        legacy_tables(connection)
        mfa_tables(connection)
        upgrade(connection)
        table, column = missing.split(".")
        # Both identifiers come only from this fixed test parameter list.
        connection.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
        schema = importlib.import_module("botelier.mfa_schema")
        with pytest.raises(RuntimeError, match="MFA schema is incomplete or incompatible"):
            schema.assert_mfa_schema(connection)


def test_wrong_security_column_type_fails_closed():
    with isolated_schema() as connection:
        legacy_tables(connection)
        mfa_tables(connection)
        upgrade(connection)
        connection.execute(text("""
            ALTER TABLE users ALTER COLUMN mfa_last_step TYPE TEXT
            USING mfa_last_step::text
        """))
        schema = importlib.import_module("botelier.mfa_schema")
        with pytest.raises(RuntimeError, match="MFA schema is incomplete or incompatible"):
            schema.assert_mfa_schema(connection)


def test_nullable_policy_column_fails_closed():
    with isolated_schema() as connection:
        legacy_tables(connection)
        mfa_tables(connection)
        upgrade(connection)
        connection.execute(text("ALTER TABLE accounts ALTER COLUMN require_mfa DROP NOT NULL"))
        schema = importlib.import_module("botelier.mfa_schema")
        with pytest.raises(RuntimeError, match="MFA schema is incomplete or incompatible"):
            schema.assert_mfa_schema(connection)
