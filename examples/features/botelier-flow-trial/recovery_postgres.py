"""Synthetic CI database only. Never imports application database startup."""

import json

import psycopg2
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from recovery_guard import FIXTURE_CONNECTION


ACCOUNT = "00000000-0000-0000-0000-000000000001"
OTHER_ACCOUNT = "00000000-0000-0000-0000-000000000002"


class PostgresTransferStorage:
    def __init__(self, *, reset=True):
        self.engine = create_engine(
            "postgresql+psycopg2://",
            creator=lambda: psycopg2.connect(**FIXTURE_CONNECTION),
            poolclass=NullPool,
        )
        self.factory = sessionmaker(bind=self.engine)
        with self.engine.begin() as connection:
            identity = connection.execute(text(
                "SELECT current_database(), inet_server_addr(), current_user"
            )).one()
            assert tuple(identity) == ("voice_recovery_fixture", None, "postgres")
            connection.execute(text("CREATE TABLE IF NOT EXISTS accounts (id UUID PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS properties (id UUID PRIMARY KEY)"))
            for account in (ACCOUNT, OTHER_ACCOUNT):
                connection.execute(text(
                    "INSERT INTO accounts(id) VALUES (CAST(:id AS UUID)) ON CONFLICT DO NOTHING"
                ), {"id": account})
        # Create the actual application's ledger schema, not an approximation.
        from botelier.models.operation_idempotency import OperationIdempotency
        OperationIdempotency.__table__.create(self.engine, checkfirst=True)
        if reset:
            with self.engine.begin() as connection:
                connection.execute(text(
                    "DELETE FROM operation_idempotency WHERE operation = 'voice_transfer'"
                ))

    def __call__(self):
        return self.factory()

    def payload(self, account=ACCOUNT):
        with self.engine.connect() as connection:
            value = connection.execute(text("""
                SELECT result FROM operation_idempotency
                WHERE operation = 'voice_transfer' AND account_id = CAST(:account AS UUID)
            """), {"account": account}).scalar_one()
            return json.loads(value) if isinstance(value, str) else value

    def close(self):
        self.engine.dispose()
