"""
Database configuration for Botelier backend.

Uses SQLAlchemy with PostgreSQL for multi-tenant data persistence.
"""

import os
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from loguru import logger

# Get database URL from environment
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

# SQLAlchemy requires 'postgresql://' not 'postgres://' (the latter is common in Heroku/Render URLs)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Create SQLAlchemy engine
# connect_args: pass SSL settings for hosted databases that require it
_connect_args = {}
if "sslmode=require" in DATABASE_URL or "sslmode=verify" in DATABASE_URL:
    _connect_args["sslmode"] = "require"

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # Verify connections before using
    pool_recycle=300,     # Recycle connections after 5 minutes
    connect_args=_connect_args,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for all models
Base = declarative_base()


def get_db():
    """
    Dependency for FastAPI routes to get database session.
    
    Usage:
        @app.get("/tools")
        def get_tools(db: Session = Depends(get_db)):
            return db.query(Tool).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Additive column migrations
#
# Each entry is a safe "ADD COLUMN IF NOT EXISTS" statement. These run at
# startup and are idempotent — safe to re-run as many times as needed.
#
# To add a new column in the future:
#   1. Add the SQLAlchemy Column() to the model
#   2. Append an ALTER TABLE statement here
# ---------------------------------------------------------------------------
_ADDITIVE_MIGRATIONS = [
    # sms_conversations — handler_mode (AI vs human takeover)
    "ALTER TABLE sms_conversations ADD COLUMN IF NOT EXISTS handler_mode VARCHAR(10) NOT NULL DEFAULT 'ai'",
    # sms_conversations — first_response_at (first outbound message timestamp for response-time analytics)
    "ALTER TABLE sms_conversations ADD COLUMN IF NOT EXISTS first_response_at TIMESTAMP",

    # sms_conversations — needs_attention (true when AI handed off but no agent has replied yet)
    "ALTER TABLE sms_conversations ADD COLUMN IF NOT EXISTS needs_attention BOOLEAN NOT NULL DEFAULT FALSE",

    # call_logs — transfer_mode ('warm' or 'cold') — null means no transfer or legacy warm
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS transfer_mode VARCHAR",

    # Indexes (CREATE INDEX IF NOT EXISTS is idempotent)
    "CREATE INDEX IF NOT EXISTS ix_sms_conv_started_at ON sms_conversations(hotel_id, started_at DESC)",

    # --- Pricing columns (deferred — uncomment when ready to capture Twilio costs) ---
    # "ALTER TABLE sms_messages ADD COLUMN IF NOT EXISTS price NUMERIC(10,4)",
    # "ALTER TABLE sms_messages ADD COLUMN IF NOT EXISTS price_unit VARCHAR(3)",

    # Fix disposition FK to allow deletion of dispositions used by call logs
    """ALTER TABLE call_logs DROP CONSTRAINT IF EXISTS call_logs_disposition_id_fkey""",
    """ALTER TABLE call_logs ADD CONSTRAINT call_logs_disposition_id_fkey FOREIGN KEY (disposition_id) REFERENCES assistant_dispositions(id) ON DELETE SET NULL""",

    # Post Call QA / After-Call Work columns
    "ALTER TABLE assistants ADD COLUMN IF NOT EXISTS acw_config JSONB DEFAULT '{}'",
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS acw_resolution VARCHAR",
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS acw_quality_score INTEGER",
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS acw_completed_at TIMESTAMP",

    # Friendly reference IDs — short 8-char uppercase identifiers for support/search
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS reference_id VARCHAR(8)",
    # Backfill: derive from each row's own UUID (removes dashes, takes first 8 chars, uppercases)
    "UPDATE call_logs SET reference_id = UPPER(SUBSTRING(REPLACE(id::text, '-', ''), 1, 8)) WHERE reference_id IS NULL",
    # Enforce NOT NULL after backfill guarantees all rows are populated
    "ALTER TABLE call_logs ALTER COLUMN reference_id SET NOT NULL",
    # Drop old composite index if it exists (replaced below with a global unique index)
    "DROP INDEX IF EXISTS ix_call_logs_hotel_ref",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_call_logs_ref ON call_logs(reference_id)",

    "ALTER TABLE sms_conversations ADD COLUMN IF NOT EXISTS reference_id VARCHAR(8)",
    "UPDATE sms_conversations SET reference_id = UPPER(SUBSTRING(REPLACE(id::text, '-', ''), 1, 8)) WHERE reference_id IS NULL",
    # Enforce NOT NULL after backfill guarantees all rows are populated
    "ALTER TABLE sms_conversations ALTER COLUMN reference_id SET NOT NULL",
    "DROP INDEX IF EXISTS ix_sms_conv_hotel_ref",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_sms_conv_ref ON sms_conversations(reference_id)",

    # Allow email-registered users (invited members) to have no replit_id.
    # The SQLAlchemy model has nullable=True but the original DB column was NOT NULL.
    "ALTER TABLE users ALTER COLUMN replit_id DROP NOT NULL",
]


def _run_additive_migrations():
    """Run idempotent schema additions that SQLAlchemy create_all won't handle."""
    with engine.connect() as conn:
        for sql in _ADDITIVE_MIGRATIONS:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception as e:
                logger.warning(f"Migration skipped (non-fatal): {sql[:60]}... — {e}")
                conn.rollback()


def init_db():
    """
    Initialize database tables.
    Call this once at application startup.
    """
    from botelier.models import tool  # noqa: F401
    from botelier.models import hotel  # noqa: F401
    from botelier.models import account  # noqa: F401
    from botelier.models import user  # noqa: F401
    from botelier.models import role  # noqa: F401
    from botelier.models import invitation  # noqa: F401
    from botelier.models import phone_number  # noqa: F401
    from botelier.models import assistant  # noqa: F401
    from botelier.models import knowledge_entry  # noqa: F401
    from botelier.models import flow_version  # noqa: F401
    from botelier.models import call_log  # noqa: F401
    from botelier.models import resolution_option  # noqa: F401
    from botelier.models import integration  # noqa: F401
    from botelier.models import mcp_connection  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _run_additive_migrations()
