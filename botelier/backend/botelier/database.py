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
    "CREATE INDEX IF NOT EXISTS ix_sms_conv_account_started_at ON sms_conversations(account_id, started_at DESC)",

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

    # ended_early — boolean flag, true when a call ends before the AI greeting finishes.
    # Set in real-time by the pipeline (GreetingCompletionTracker) via ai_greeting_completed.
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS ended_early BOOLEAN NOT NULL DEFAULT FALSE",
    # call_settings — per-assistant call control thresholds (max duration, no-response timeout)
    "ALTER TABLE assistants ADD COLUMN IF NOT EXISTS call_settings JSONB NOT NULL DEFAULT '{}'",

    # ai_greeting_completed — true when the AI's greeting TTS finished playing during the call.
    # Set directly from the pipeline so it is reliable regardless of Twilio webhook timing.
    # Source of truth for classifying calls as completed vs ended_early going forward.
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS ai_greeting_completed BOOLEAN NOT NULL DEFAULT FALSE",

    # REPAIR A — Restore calls wrongly classified as ended_early by the old duration-threshold
    # backfill migration. Scoped to calls before pipeline deployment (2026-04-02 17:00 UTC) so
    # future pipeline-classified ended_early calls are never affected. Safe no-op after first run.
    "UPDATE call_logs SET status = 'completed', ended_early = FALSE WHERE status = 'ended_early' AND ai_greeting_completed = FALSE AND started_at < '2026-04-02 17:00:00'",

    # REPAIR B — Restore any calls with confirmed greeting (ai_greeting_completed=TRUE) that were
    # somehow left as ended_early. Pipeline is the source of truth. No-op once data is clean.
    "UPDATE call_logs SET status = 'completed', ended_early = FALSE WHERE ai_greeting_completed = TRUE AND status = 'ended_early'",

    # feature_flags — per-account feature override dict for subscription tier gating.
    # Effective entitlements = tier defaults (from FEATURE_CATALOG) merged with this dict.
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS feature_flags JSONB NOT NULL DEFAULT '{}'",

    # ── hotel_id → account_id unification ────────────────────────────────────
    # Architecture note: the legacy `hotels` table was a 1:1 alias for `accounts`.
    # Every hotels.id IS an accounts.id (same UUID). No data backfill is required;
    # we only rename the FK columns from hotel_id → account_id and repoint them at
    # accounts. The FK constraint additions below serve as the integrity check —
    # they will fail (non-fatally) if any orphan account_ids exist.
    #
    # Drop FK constraints pointing at the legacy hotels table (idempotent).
    "ALTER TABLE assistants DROP CONSTRAINT IF EXISTS assistants_hotel_id_fkey",
    "ALTER TABLE call_logs DROP CONSTRAINT IF EXISTS call_logs_hotel_id_fkey",
    "ALTER TABLE knowledge_entries DROP CONSTRAINT IF EXISTS knowledge_entries_hotel_id_fkey",
    "ALTER TABLE phone_numbers DROP CONSTRAINT IF EXISTS phone_numbers_hotel_id_fkey",
    "ALTER TABLE sms_compliance_campaigns DROP CONSTRAINT IF EXISTS sms_compliance_campaigns_hotel_id_fkey",
    "ALTER TABLE sms_conversations DROP CONSTRAINT IF EXISTS sms_conversations_hotel_id_fkey",
    "ALTER TABLE sms_notification_settings DROP CONSTRAINT IF EXISTS sms_notification_settings_hotel_id_fkey",
    "ALTER TABLE sms_templates DROP CONSTRAINT IF EXISTS sms_templates_hotel_id_fkey",
    # Rename hotel_id → account_id on each table.
    # Three possible states handled per table:
    #   1. Only hotel_id exists           → rename (normal path)
    #   2. Both hotel_id and account_id   → provisioner added a new account_id
    #                                       column; copy data across, drop hotel_id
    #   3. Only account_id exists         → already done; no-op
    """DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='assistants' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='assistants' AND column_name='account_id') THEN
      UPDATE assistants SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE assistants DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE assistants RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$""",
    """DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='call_logs' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='call_logs' AND column_name='account_id') THEN
      UPDATE call_logs SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE call_logs DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE call_logs RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$""",
    """DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='knowledge_entries' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='knowledge_entries' AND column_name='account_id') THEN
      UPDATE knowledge_entries SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE knowledge_entries DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE knowledge_entries RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$""",
    """DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='phone_numbers' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='phone_numbers' AND column_name='account_id') THEN
      UPDATE phone_numbers SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE phone_numbers DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE phone_numbers RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$""",
    """DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sms_compliance_campaigns' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sms_compliance_campaigns' AND column_name='account_id') THEN
      UPDATE sms_compliance_campaigns SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE sms_compliance_campaigns DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE sms_compliance_campaigns RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$""",
    """DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sms_conversations' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sms_conversations' AND column_name='account_id') THEN
      UPDATE sms_conversations SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE sms_conversations DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE sms_conversations RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$""",
    """DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sms_notification_settings' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sms_notification_settings' AND column_name='account_id') THEN
      UPDATE sms_notification_settings SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE sms_notification_settings DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE sms_notification_settings RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$""",
    """DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sms_templates' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sms_templates' AND column_name='account_id') THEN
      UPDATE sms_templates SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE sms_templates DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE sms_templates RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$""",
    # Add FK constraints pointing at accounts (idempotent via DO blocks).
    """DO $$ BEGIN ALTER TABLE assistants ADD CONSTRAINT assistants_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN ALTER TABLE call_logs ADD CONSTRAINT call_logs_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN ALTER TABLE knowledge_entries ADD CONSTRAINT knowledge_entries_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN ALTER TABLE phone_numbers ADD CONSTRAINT phone_numbers_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN ALTER TABLE sms_compliance_campaigns ADD CONSTRAINT sms_compliance_campaigns_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN ALTER TABLE sms_conversations ADD CONSTRAINT sms_conversations_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN ALTER TABLE sms_notification_settings ADD CONSTRAINT sms_notification_settings_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN ALTER TABLE sms_templates ADD CONSTRAINT sms_templates_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    # Recreate indexes under their new names.
    "DROP INDEX IF EXISTS ix_call_logs_hotel_started",
    "CREATE INDEX IF NOT EXISTS ix_call_logs_account_started ON call_logs(account_id, started_at)",
    "DROP INDEX IF EXISTS ix_call_logs_hotel_status",
    "CREATE INDEX IF NOT EXISTS ix_call_logs_account_status ON call_logs(account_id, status)",
    "DROP INDEX IF EXISTS ix_sms_conv_hotel_status",
    "CREATE INDEX IF NOT EXISTS ix_sms_conv_account_status ON sms_conversations(account_id, status)",
    "DROP INDEX IF EXISTS ix_sms_conv_hotel_last_msg",
    "CREATE INDEX IF NOT EXISTS ix_sms_conv_account_last_msg ON sms_conversations(account_id, last_message_at)",
    "DROP INDEX IF EXISTS ix_sms_conv_customer_number",
    "CREATE INDEX IF NOT EXISTS ix_sms_conv_account_customer_number ON sms_conversations(account_id, customer_number, botelier_number)",
    "DROP INDEX IF EXISTS ix_sms_template_hotel",
    "CREATE INDEX IF NOT EXISTS ix_sms_template_account ON sms_templates(account_id)",
    # Drop the legacy hotels table (only after all FKs are gone).
    "DROP TABLE IF EXISTS hotels",
    # Rename the legacy tools.hotel_id column to account_id (orphan column, no FK).
    """DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tools' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tools' AND column_name='account_id') THEN
      UPDATE tools SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE tools DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE tools RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$""",
]


def _run_hotel_account_migration():
    """
    Pre-cutover hotel → account data integrity step (fail-fast).

    Architecture: The legacy `hotels` table was a 1:1 alias for `accounts`.
    Every hotels.id is (or was) an accounts.id — hotels were always created
    alongside their matching account row. This function:

    1. Checks whether `hotels` still exists (no-op if already dropped).
    2. Backfills missing accounts from hotels (safety net for edge cases).
    3. Verifies all dependent tables have zero orphan account_ids.
    4. RAISES if integrity fails — does NOT silently proceed to drop hotels.

    This function must run BEFORE _run_additive_migrations() so that FK
    re-addition and the final DROP TABLE hotels can succeed cleanly.
    """
    with engine.connect() as conn:
        # Step 1: Check if hotels table still exists.
        result = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'hotels')"
        ))
        hotels_exists = result.scalar()
        if not hotels_exists:
            logger.info("Hotel→account migration: hotels table already dropped — skipping.")
            return

        logger.info("Hotel→account migration: hotels table exists — running pre-cutover checks.")

        # Step 2: Backfill any hotels missing from accounts.
        # Hotels were always co-created with accounts in this SaaS, so orphan
        # hotels are rare edge cases. We copy all shared columns to preserve
        # data (Twilio credentials, phone, metadata, etc.) and apply sensible
        # defaults only for accounts columns that hotels never had.
        hotels_cols_res = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'hotels' ORDER BY ordinal_position"
        ))
        hotels_cols = {r[0] for r in hotels_cols_res}

        accounts_cols_res = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'accounts' ORDER BY ordinal_position"
        ))
        accounts_cols = {r[0] for r in accounts_cols_res}

        # Shared columns are copied directly; accounts-only required fields
        # get sensible defaults if not present in hotels.
        shared = sorted(hotels_cols & accounts_cols - {"id"})
        col_list = ["id"] + shared
        select_exprs = ["h.id"] + [f"h.{c}" for c in shared]

        # Required accounts columns not in hotels → inject defaults.
        required_defaults = {
            "name": "COALESCE(h.name, 'Migrated Account')",
            "slug": "COALESCE(h.slug, h.id::text)",
            "email": "COALESCE(h.email, 'migrated@botelier.io')",
            "status": "'active'",
            "subscription_tier": "'free'",
            "created_at": "NOW()",
        }
        for req_col, default_expr in required_defaults.items():
            if req_col not in col_list:
                col_list.append(req_col)
                select_exprs.append(default_expr)
            else:
                # Override the direct copy for required fields with COALESCE.
                idx = col_list.index(req_col)
                if req_col in ("name", "slug", "email"):
                    select_exprs[idx] = default_expr

        col_sql = ", ".join(col_list)
        select_sql = ", ".join(select_exprs)
        backfill_sql = (
            f"INSERT INTO accounts ({col_sql}) "
            f"SELECT {select_sql} "
            f"FROM hotels h "
            f"WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE a.id = h.id) "
            f"ON CONFLICT (id) DO NOTHING"
        )
        result = conn.execute(text(backfill_sql))
        backfill_count = result.rowcount
        conn.commit()
        if backfill_count > 0:
            logger.info(
                f"Hotel→account migration: backfilled {backfill_count} account(s) from hotels. "
                f"Columns copied: {col_sql}"
            )
        else:
            logger.info("Hotel→account migration: no missing accounts — backfill not needed.")

        # Step 3: Verify zero orphan account_ids across all 8 dependent tables.
        # Checks BOTH column name variants: hotel_id (pre-rename) and account_id
        # (post-rename). Each table is checked via whichever column name exists.
        dep_tables = [
            "assistants",
            "call_logs",
            "knowledge_entries",
            "phone_numbers",
            "sms_compliance_campaigns",
            "sms_conversations",
            "sms_notification_settings",
            "sms_templates",
        ]
        orphan_found = False
        for table in dep_tables:
            # Determine the actual column name (may be hotel_id or account_id).
            col: str | None = None
            for candidate in ("hotel_id", "account_id"):
                exists = conn.execute(text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    f"WHERE table_name = '{table}' AND column_name = '{candidate}')"
                )).scalar()
                if exists:
                    col = candidate
                    break
            if col is None:
                logger.warning(
                    f"Hotel→account migration: no hotel_id/account_id column in {table} — skipping."
                )
                continue
            count = conn.execute(text(
                f"SELECT COUNT(*) FROM {table} t "
                f"WHERE t.{col} IS NOT NULL "
                f"AND NOT EXISTS (SELECT 1 FROM accounts a WHERE a.id = t.{col})"
            )).scalar()
            if count > 0:
                logger.error(
                    f"Hotel→account migration: INTEGRITY FAILURE — "
                    f"{count} orphan rows in {table}.{col}"
                )
                orphan_found = True
            else:
                logger.debug(
                    f"Hotel→account migration: {table}.{col} ✓ (no orphans)"
                )

        if orphan_found:
            raise RuntimeError(
                "Hotel→account migration aborted: orphan account_id values detected. "
                "Hotels table preserved — check logs for details."
            )

        logger.info("Hotel→account migration: integrity verified — no orphan rows found.")


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

    Runs four idempotent steps in order:

    1. ``create_all`` — creates any tables that do not yet exist (SQLAlchemy
       inspects the engine and skips tables that are already present).

    2. ``_run_hotel_account_migration`` — fail-fast pre-cutover step that
       backfills any missing accounts from hotels, verifies referential
       integrity, and only then permits the DROP TABLE hotels to proceed.
       No-op if hotels table is already gone.

    3. ``_run_additive_migrations`` — applies schema changes (new columns,
       indexes, constraints, column renames, DROP TABLE hotels) that
       ``create_all`` cannot handle on existing tables.  Safe to re-run.

    4. ``_sync_system_role_permissions`` — brings all system role permission
       rows in line with the DEFAULT_ROLES template in
       ``botelier/auth/permissions.py``.  Ensures that adding a permission to
       the template is automatically reflected in production on the next
       deploy, without a manual SQL update.
    """
    from botelier.models import tool  # noqa: F401
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
    _run_hotel_account_migration()
    _run_additive_migrations()
    _sync_system_role_permissions()
