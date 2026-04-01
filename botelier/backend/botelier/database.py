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
# Schema migrations  (_ADDITIVE_MIGRATIONS / _run_additive_migrations)
#
# Each entry is idempotent SQL that adds or adjusts a schema object.
# These run at every startup and are safe to re-run repeatedly.
#
# Use this list for:
#   • New columns    — "ALTER TABLE t ADD COLUMN IF NOT EXISTS …"
#   • New indexes    — "CREATE INDEX IF NOT EXISTS …"
#   • New tables     — "CREATE TABLE IF NOT EXISTS …"
#   • Constraint tweaks, column type changes (with care)
#
# To add a new column:
#   1. Add the SQLAlchemy Column() to the model file.
#   2. Append an ALTER TABLE statement to _ADDITIVE_MIGRATIONS below.
#
# Do NOT use this list for reference-data changes (e.g. role permissions).
# For that, see _sync_system_role_permissions() further below.
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

    # call_events — event timeline table for every call.
    # The table itself is created by Base.metadata.create_all, but we ensure the
    # indexes exist here so they are present even on pre-existing deployments that
    # ran create_all before this model was added.
    """
    CREATE TABLE IF NOT EXISTS call_events (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        call_log_id UUID NOT NULL REFERENCES call_logs(id) ON DELETE CASCADE,
        event_type VARCHAR NOT NULL,
        event_source VARCHAR NOT NULL DEFAULT 'app',
        severity VARCHAR NOT NULL DEFAULT 'info',
        occurred_at TIMESTAMP NOT NULL DEFAULT NOW(),
        offset_ms INTEGER,
        details JSONB
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_call_events_call_log_id ON call_events(call_log_id)",
    "CREATE INDEX IF NOT EXISTS ix_call_events_call_log_occurred ON call_events(call_log_id, occurred_at)",

    # account_secrets — encrypted per-account key/value credential store
    """
    CREATE TABLE IF NOT EXISTS account_secrets (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        key VARCHAR(255) NOT NULL,
        name VARCHAR(255),
        description TEXT,
        value_encrypted TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(account_id, key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_account_secrets_account_id ON account_secrets(account_id)",

    # integration_call_logs — fire-and-forget audit trail for every integration API call
    """
    CREATE TABLE IF NOT EXISTS integration_call_logs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        integration_id UUID REFERENCES account_integrations(id) ON DELETE SET NULL,
        endpoint_called VARCHAR(2048),
        method VARCHAR(16),
        status_code INTEGER,
        success BOOLEAN NOT NULL DEFAULT FALSE,
        latency_ms INTEGER,
        error_type VARCHAR(64),
        error_message TEXT,
        called_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_integration_call_logs_account_id ON integration_call_logs(account_id)",
    "CREATE INDEX IF NOT EXISTS ix_integration_call_logs_integration_id ON integration_call_logs(integration_id)",
    "CREATE INDEX IF NOT EXISTS ix_integration_call_logs_called_at ON integration_call_logs(account_id, called_at DESC)",

    # ended_early — boolean flag for calls that finished before EARLY_END_THRESHOLD seconds
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS ended_early BOOLEAN NOT NULL DEFAULT FALSE",
    # call_settings — per-assistant call control thresholds (early-end, max duration, no-response timeout)
    "ALTER TABLE assistants ADD COLUMN IF NOT EXISTS call_settings JSONB NOT NULL DEFAULT '{}'",

    # ai_greeting_completed — true when the AI's greeting TTS finished playing during the call.
    # Set directly from the pipeline (GreetingCompletionTracker) so it is reliable regardless
    # of Twilio webhook timing. Used to classify calls as ended_early vs completed.
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS ai_greeting_completed BOOLEAN NOT NULL DEFAULT FALSE",

    # Backfill: for old calls (before ai_greeting_completed tracking), mark short completed calls
    # as ended_early IF the greeting was not confirmed to have played.
    # GUARD: ai_greeting_completed = FALSE ensures we never touch new calls where greeting played.
    "UPDATE call_logs SET ended_early = TRUE WHERE ended_early = FALSE AND ai_greeting_completed = FALSE AND duration_seconds IS NOT NULL AND duration_seconds < 30 AND status IN ('completed', 'no-answer', 'no_answer', 'busy', 'canceled')",

    # Migrate existing ended_early calls: reclassify status column to 'ended_early' as the
    # single source of truth. GUARD: ai_greeting_completed = FALSE ensures we never reclassify
    # calls where the greeting actually played (even if ended_early boolean was set incorrectly).
    "UPDATE call_logs SET status = 'ended_early' WHERE ended_early = TRUE AND ai_greeting_completed = FALSE AND status IN ('completed', 'no_answer', 'no-answer', 'busy', 'canceled')",

    # REPAIR: Restore calls that were wrongly classified as ended_early by the old duration-threshold
    # migration. Any call where the AI greeting completed must be 'completed', not 'ended_early'.
    "UPDATE call_logs SET status = 'completed', ended_early = FALSE WHERE ai_greeting_completed = TRUE AND status = 'ended_early'",
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


# ---------------------------------------------------------------------------
# Reference-data sync  (_sync_system_role_permissions)
#
# Keeps system role permission rows in the database consistent with the
# DEFAULT_ROLES template defined in botelier/auth/permissions.py.
#
# WHY THIS EXISTS
# System roles (account_admin, staff, viewer) are seeded once at account
# creation time.  When a developer adds a new permission to DEFAULT_ROLES,
# the existing DB rows are never automatically updated — only newly created
# accounts get the new permission.  This sync closes that gap.
#
# HOW IT WORKS
# On every startup, this function queries all system-role rows and replaces
# their permissions JSON with the canonical DEFAULT_ROLES template for their
# slug.  If the row already matches, no write is issued (idempotent).
#
# Use this pattern for:
#   • Adding/removing a permission to/from a system role
#   • Renaming a permission key across the board
#   • Any other change to DEFAULT_ROLES that should propagate to prod
#
# Do NOT use _ADDITIVE_MIGRATIONS for this — those are for schema objects
# (tables, columns, indexes), not for seeded application data.
# ---------------------------------------------------------------------------

def _sync_system_role_permissions():
    """
    Idempotent data sync: align all system role permission rows with DEFAULT_ROLES.

    Called during application startup (after schema migrations).  Updates any
    system role whose stored permissions JSON does not exactly match the
    canonical template in DEFAULT_ROLES.  Roles with an unrecognised slug
    (e.g. custom roles) are left untouched.

    This is the proactive half of the two-layer permissions strategy:
    - Proactive (this function): writes correct permissions to the DB at boot
      so every subsequent read returns the right value with no extra logic.
    - Defensive (_get_effective_permissions in api/admin.py): merges the
      DEFAULT_ROLES template at request time as a safety net against races
      or any role rows that were missed here.
    """
    # Deferred imports to avoid circular dependencies at module load time.
    from botelier.models.role import Role
    from botelier.auth.permissions import DEFAULT_ROLES

    db = SessionLocal()
    try:
        system_roles = db.query(Role).filter(Role.is_system_role == True).all()  # noqa: E712
        updated = []

        for role in system_roles:
            template = DEFAULT_ROLES.get(role.slug)
            if template is None:
                # Custom or unrecognised system role — do not touch it.
                continue

            canonical_permissions = template["permissions"]
            if role.permissions == canonical_permissions:
                # Already up to date — skip the write.
                continue

            role.permissions = canonical_permissions
            updated.append(role.slug)
            # Log immediately per role so each update is visible in the audit trail
            # even if a subsequent commit fails.
            logger.info(
                f"Syncing system role permissions: {role.slug} "
                f"(account_id={role.account_id})"
            )

        # All role updates are committed in a single transaction for atomicity.
        # If any update fails the entire batch is rolled back and the error is
        # logged below — no partial state is written to the DB.
        if updated:
            db.commit()
            logger.info(
                f"System role permissions sync complete — "
                f"updated {len(updated)} role(s): {', '.join(updated)}"
            )
        else:
            logger.info("System role permissions sync complete — all roles already up to date")

    except Exception as e:
        logger.error(f"Failed to sync system role permissions: {e}")
        db.rollback()
    finally:
        db.close()


def init_db():
    """
    Initialize the database at application startup.

    Runs three idempotent steps in order:

    1. ``create_all`` — creates any tables that do not yet exist (SQLAlchemy
       inspects the engine and skips tables that are already present).

    2. ``_run_additive_migrations`` — applies schema changes (new columns,
       indexes, constraints) that ``create_all`` cannot handle on existing
       tables.  Safe to re-run on every boot.

    3. ``_sync_system_role_permissions`` — brings all system role permission
       rows in line with the DEFAULT_ROLES template in
       ``botelier/auth/permissions.py``.  Ensures that adding a permission to
       the template is automatically reflected in production on the next
       deploy, without a manual SQL update.
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
    from botelier.models import call_event  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _run_additive_migrations()
    _sync_system_role_permissions()
