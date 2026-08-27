"""Database configuration for Botelier backend.

Uses SQLAlchemy with PostgreSQL for multi-tenant data persistence.
"""

import os
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

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

# Task #122 — explicit pool sizing for dev/prod parity.
#
# Concurrency model per call (worst case):
#   1 short-lived session in the /api/calls/incoming webhook
#   1 short-lived session in the prewarm background task (runs in
#     asyncio.to_thread → checks out a connection on a worker thread)
#   1 short-lived session in handle_call when the WebSocket opens
#   plus dashboard/API traffic on other coroutines
#
# So at peak we expect ~3 concurrent connections per in-flight call.
# Defaults of pool_size=10 + max_overflow=20 = 30 concurrent connections
# headroom support a sustained ~10 concurrent calls per pod with margin
# for analytics queries — well below Neon's default 100-conn ceiling for
# a single pod, and below SQLAlchemy's default total of 15 (5+10) which
# is too tight once prewarm doubles the per-call session count.
# All three knobs are env-overridable for horizontal scaling.
_pool_size = int(os.environ.get("DB_POOL_SIZE", "10"))
_max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", "20"))
_pool_timeout = float(os.environ.get("DB_POOL_TIMEOUT", "10"))

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=_pool_size,
    max_overflow=_max_overflow,
    pool_timeout=_pool_timeout,
    connect_args=_connect_args,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for all models
Base = declarative_base()


def get_db():
    """Dependency for FastAPI routes to get database session.

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
    # Task #538 — atomic cross-worker SAVE_RECORD deduplication.
    "ALTER TABLE records ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)",
    """CREATE UNIQUE INDEX IF NOT EXISTS ix_records_idempotency_key
       ON records(idempotency_key) WHERE idempotency_key IS NOT NULL""",
    # sms_conversations — handler_mode (AI vs human takeover)
    "ALTER TABLE sms_conversations ADD COLUMN IF NOT EXISTS handler_mode VARCHAR(10) NOT NULL DEFAULT 'ai'",
    # sms_conversations — first_response_at (first outbound message timestamp for response-time analytics)
    "ALTER TABLE sms_conversations ADD COLUMN IF NOT EXISTS first_response_at TIMESTAMP",
    # sms_conversations — needs_attention (true when AI handed off but no agent has replied yet)
    "ALTER TABLE sms_conversations ADD COLUMN IF NOT EXISTS needs_attention BOOLEAN NOT NULL DEFAULT FALSE",
    # call_logs — transfer_mode ('warm' or 'cold') — null means no transfer or legacy warm
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS transfer_mode VARCHAR",
    # Task #397 — LLM-generated call topic (3 words or less), produced by post-call QA.
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS acw_topic VARCHAR",
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS duration_source VARCHAR(32) NOT NULL DEFAULT 'unknown'",
    "ALTER TABLE call_legs ADD COLUMN IF NOT EXISTS duration_source VARCHAR(32) NOT NULL DEFAULT 'unknown'",
    "ALTER TABLE account_billing_config ADD COLUMN IF NOT EXISTS voice_rate_model VARCHAR(16) NOT NULL DEFAULT 'combined'",
    "ALTER TABLE account_billing_config ALTER COLUMN voice_rate_model SET DEFAULT 'separate'",
    "ALTER TABLE account_billing_config ALTER COLUMN outbound_rate_usd SET DEFAULT 0.03",
    "ALTER TABLE call_billing_items ADD COLUMN IF NOT EXISTS call_leg_id UUID REFERENCES call_legs(id) ON DELETE CASCADE",
    "ALTER TABLE call_billing_items ADD COLUMN IF NOT EXISTS source_duration_seconds INTEGER",
    "ALTER TABLE call_billing_items ADD COLUMN IF NOT EXISTS duration_source VARCHAR(32) NOT NULL DEFAULT 'unknown'",
    # Task #477 — per-flow-tool LLM overrides. All nullable; NULL = fall back to assistant-level settings.
    "ALTER TABLE tools ADD COLUMN IF NOT EXISTS llm_provider VARCHAR(64)",
    "ALTER TABLE tools ADD COLUMN IF NOT EXISTS llm_model VARCHAR(128)",
    "ALTER TABLE tools ADD COLUMN IF NOT EXISTS llm_temperature FLOAT",
    "ALTER TABLE tools ADD COLUMN IF NOT EXISTS llm_max_tokens INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_call_billing_items_call_leg_id ON call_billing_items(call_leg_id)",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_call_billing_inbound_per_call
       ON call_billing_items(call_log_id) WHERE item_type = 'inbound_call'""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_call_billing_transfer_per_leg
       ON call_billing_items(call_leg_id)
       WHERE item_type = 'outbound_transfer' AND call_leg_id IS NOT NULL""",
    # Task #339 — PMS-native review+pay: link a payment back to its durable flow
    # session (for page pre-fill) and keep the raw session key for late resolve.
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS flow_session_id UUID REFERENCES flow_sessions(id) ON DELETE SET NULL",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS source_session_key VARCHAR(255)",
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
    # Task #98 — Silent caller detection.
    # caller_spoke is intentionally tri-state (NULL/TRUE/FALSE):
    #   NULL  = legacy row that pre-dates this column (before this migration ran).
    #   TRUE  = Pipecat observed at least one caller utterance.
    #   FALSE = call ended without any caller utterance (set forward-only by
    #           CallLogger.complete_call() so historical rows stay NULL).
    # Analytics treats `caller_spoke IS NOT FALSE` (TRUE or NULL) as eligible
    # for ai_handled — this preserves historical AI-handled counts while
    # routing newly-detected silent calls into the unresolved bucket.
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS caller_spoke BOOLEAN",
    # acw_skip_reason records why the post-call QA was skipped by the system
    # (e.g. "no_caller_audio") — distinct from acw_resolution which is the
    # LLM-picked outcome string.
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS acw_skip_reason VARCHAR",
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
    # Task #329 — add the CAPABILITY value to the native `tooltype` PG enum so
    # capability tools can be persisted. SQLAlchemy's create_all never alters an
    # existing enum, so this is required on every already-provisioned database.
    # The runner commits each statement in its own transaction and only ADDs the
    # value here (it is not used until a later transaction), so PG 12+ accepts it.
    "ALTER TYPE tooltype ADD VALUE IF NOT EXISTS 'CAPABILITY'",
    # call_events — event timeline table for every call.
    # The table itself is created by Base.metadata.create_all, but we ensure the
    # indexes exist here so they are present even on pre-existing deployments that
    # ran create_all before this model was added.
    # Task #123 — offset_ms is BIGINT from the first CREATE TABLE so a fresh
    # deploy never depends on the follow-up Task #115 ALTER (which can fail
    # silently and leave int4 in place, dropping writes for calls older than
    # ~24.85 days). The startup invariant
    # _assert_call_events_offset_ms_bigint() verifies this hard.
    """
    CREATE TABLE IF NOT EXISTS call_events (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        call_log_id UUID NOT NULL REFERENCES call_logs(id) ON DELETE CASCADE,
        event_type VARCHAR NOT NULL,
        event_source VARCHAR NOT NULL DEFAULT 'app',
        severity VARCHAR NOT NULL DEFAULT 'info',
        occurred_at TIMESTAMP NOT NULL DEFAULT NOW(),
        offset_ms BIGINT,
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
    # integration_actions — reusable certified/custom no-code action library
    """
    CREATE TABLE IF NOT EXISTS integration_actions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id UUID REFERENCES accounts(id) ON DELETE CASCADE,
        integration_type_id UUID REFERENCES integration_types(id) ON DELETE SET NULL,
        source_endpoint_id VARCHAR(255),
        name VARCHAR(255) NOT NULL,
        description TEXT,
        slug VARCHAR(255) NOT NULL,
        kind VARCHAR(32) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'draft',
        published_version_id UUID,
        last_tested_at TIMESTAMP,
        last_test_success BOOLEAN,
        last_error TEXT,
        created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_integration_actions_account_status ON integration_actions(account_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_integration_actions_integration_type ON integration_actions(integration_type_id)",
    """
    CREATE TABLE IF NOT EXISTS integration_action_versions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        action_id UUID NOT NULL REFERENCES integration_actions(id) ON DELETE CASCADE,
        version_number INTEGER NOT NULL,
        status VARCHAR(32) NOT NULL,
        config JSONB NOT NULL DEFAULT '{}',
        input_schema JSONB NOT NULL DEFAULT '{}',
        output_schema JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        published_at TIMESTAMP,
        UNIQUE(action_id, version_number)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_integration_action_versions_action_status ON integration_action_versions(action_id, status)",
    """
    CREATE TABLE IF NOT EXISTS integration_action_invocations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        action_id UUID REFERENCES integration_actions(id) ON DELETE SET NULL,
        action_version_id UUID REFERENCES integration_action_versions(id) ON DELETE SET NULL,
        integration_id UUID REFERENCES account_integrations(id) ON DELETE SET NULL,
        channel VARCHAR(32) NOT NULL DEFAULT 'api',
        call_sid VARCHAR(64),
        call_log_id UUID,
        tool_id VARCHAR(36),
        flow_version_id UUID,
        node_id VARCHAR(255),
        request_id VARCHAR(64) NOT NULL,
        endpoint_called VARCHAR(500),
        method VARCHAR(10),
        status_code INTEGER,
        success BOOLEAN NOT NULL DEFAULT FALSE,
        latency_ms INTEGER,
        error_type VARCHAR(64),
        error_message TEXT,
        response_metadata JSONB,
        called_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_integration_action_invocations_account_called ON integration_action_invocations(account_id, called_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_integration_action_invocations_action_called ON integration_action_invocations(action_id, called_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_integration_action_invocations_call_sid ON integration_action_invocations(call_sid)",
    "CREATE INDEX IF NOT EXISTS ix_integration_action_invocations_request_id ON integration_action_invocations(request_id)",
    "ALTER TABLE integration_action_invocations ADD COLUMN IF NOT EXISTS flow_tool_id UUID",
    "ALTER TABLE integration_action_invocations ADD COLUMN IF NOT EXISTS source_label VARCHAR(255)",
    "CREATE INDEX IF NOT EXISTS ix_integration_action_invocations_flow_tool_id ON integration_action_invocations(flow_tool_id)",
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
    # Task #115 — Fix 1: widen call_events.offset_ms from int4 to int8 (BIGINT).
    # Calls stuck for >24.8 days produce offset_ms values that exceed int4 max
    # (2 147 483 647 ms). The stuck-call sweeper then fails with
    # NumericValueOutOfRange every 5 min, keeping those rows stuck forever.
    # The ALTER is wrapped in a DO block so it is a no-op once the column is
    # already BIGINT (idempotent across repeated startup runs).
    #
    # Migration approach note: this project does NOT use Alembic. All schema
    # evolution lives in this _ADDITIVE_MIGRATIONS list (see header comment
    # above) and runs on every backend startup. Adding an Alembic file here
    # would be inconsistent with the rest of the codebase.
    """DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'call_events'
      AND column_name = 'offset_ms'
      AND data_type = 'integer'
  ) THEN
    ALTER TABLE call_events ALTER COLUMN offset_ms TYPE BIGINT;
  END IF;
END $$""",
    # Task #115 — Fix 2: zero out fabricated durations left by the sweeper on
    # unanswered calls (answered_at IS NULL). Before this fix, complete_call()
    # computed leg duration as (datetime.utcnow() - leg.started_at), turning an
    # overnight stuck call into an 800+ minute duration.
    #
    # Scope decision (intentionally broader than the Apr-17 cohort):
    #   The original investigation identified 9 inflated rows from the Apr-17
    #   05:59 UTC sweeper run, but a timestamp-bounded WHERE would not catch
    #   the same class of bug from earlier or future sweeper runs that may
    #   have produced inflated durations on this same data shape (unanswered
    #   call + non-trivial duration_seconds). We use a conservative duration
    #   threshold (>7 200 s = 2 h) because no real hotel AI call legitimately
    #   runs that long, and the answered_at IS NULL filter narrows the target
    #   to exactly the failure mode the code fix prevents. This is idempotent:
    #   after one successful run no rows match the predicate.
    """UPDATE call_logs
SET duration_seconds = 0
WHERE answered_at IS NULL
  AND duration_seconds > 7200
  AND status IN ('completed', 'ended_early')""",
    # Task #162 — Billing threshold alert tracking.
    # last_threshold_alert_at records when the most recent threshold-crossing
    # email was sent for this account. The alert service uses it to suppress
    # duplicate alerts within the same calendar month.
    "ALTER TABLE account_billing_config ADD COLUMN IF NOT EXISTS last_threshold_alert_at TIMESTAMP",
    # Task #162 (fix) — Dedicated per-account, per-month alert table.
    # Replaces stamping on the shared platform-default config row.
    # Unique constraint on (account_id, alert_year, alert_month) enables
    # atomic INSERT ON CONFLICT DO NOTHING for race-safe deduplication.
    """CREATE TABLE IF NOT EXISTS account_billing_alerts (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        alert_year INTEGER NOT NULL,
        alert_month INTEGER NOT NULL,
        alerted_at TIMESTAMP NOT NULL,
        spend_usd NUMERIC(10,4),
        threshold_usd NUMERIC(10,4),
        UNIQUE(account_id, alert_year, alert_month)
    )""",
    # Task #176 — Platform internal cost rates configurable via DB.
    # Operator-editable wholesale rates for LLM, TTS, STT, and Twilio.
    # Append-only: new row per change preserves a full audit trail of rate
    # changes.  The effective row for cost calculations is the most recent
    # with effective_from <= now(). No rows → backend falls back to hardcoded
    # compile-time defaults so a fresh deployment works without seeding.
    # NOTE: admin report queries always use the currently-effective row; they
    # do not pin per-call rates at call time (that requires follow-up #178).
    """CREATE TABLE IF NOT EXISTS platform_internal_rates (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        llm_prompt_rate_per_1k NUMERIC(12,8) NOT NULL,
        llm_completion_rate_per_1k NUMERIC(12,8) NOT NULL,
        tts_rate_per_1k_chars NUMERIC(12,8) NOT NULL,
        stt_rate_per_second NUMERIC(12,8) NOT NULL,
        twilio_inbound_per_min NUMERIC(12,8) NOT NULL,
        twilio_outbound_per_min NUMERIC(12,8) NOT NULL,
        twilio_sms_in_rate NUMERIC(12,8) NOT NULL,
        twilio_sms_out_rate NUMERIC(12,8) NOT NULL,
        note VARCHAR(500),
        effective_from TIMESTAMP NOT NULL DEFAULT NOW(),
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_platform_internal_rates_effective ON platform_internal_rates(effective_from DESC)",
    # Task #190 — Pipecat-native usage observer: record which LLM and TTS model
    # was used per call so per-model billing rates can be applied in follow-on work.
    # VARCHAR(100) matches the assistant model name columns (e.g. "gpt-4o", "sonic-2").
    # Populated at call-end from UsageObserver.llm_model / .tts_model.
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS llm_model VARCHAR(100)",
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS tts_model VARCHAR(100)",
    # Task #225 — Track OpenAI prompt-cache hits for accurate COGS.
    # OpenAI bills cached prompt tokens at ~50% of the standard rate.
    # llm_cached_tokens is the subset of llm_prompt_tokens that were served from
    # the prompt cache. NULL for calls that predate this migration; 0 when the
    # call ran but no tokens were cached.
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS llm_cached_tokens BIGINT",
    # Task #155 — Billing snapshot columns written at call-end by BillingService.
    # direction: 'inbound' (default) or 'outbound' (click-to-call, future).
    # NOT NULL with server_default so existing rows get 'inbound' automatically.
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS direction VARCHAR(10) NOT NULL DEFAULT 'inbound'",
    # COGS usage counters — NULL for calls predating this migration.
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS llm_prompt_tokens BIGINT",
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS llm_completion_tokens BIGINT",
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS tts_characters BIGINT",
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS stt_seconds NUMERIC(10,2)",
    # Account-facing cost sum of call_billing_items for this call.
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS estimated_cost_usd NUMERIC(10,6)",
    # SMS AI configuration on assistants — added after initial table creation.
    # Keys: enabled, llm_model, max_response_length, welcome_message, etc.
    "ALTER TABLE assistants ADD COLUMN IF NOT EXISTS sms_config JSONB DEFAULT '{}'",
    # ── Structured output records (record_types + records) ──────────────────
    # Tables are created by Base.metadata.create_all; these statements ensure the
    # indexes and idempotency constraints exist even on pre-existing deployments
    # that ran create_all before these models were added.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_record_types_account_slug ON record_types(account_id, slug)",
    "CREATE INDEX IF NOT EXISTS ix_record_types_account_active ON record_types(account_id, is_active)",
    "CREATE INDEX IF NOT EXISTS ix_records_account_type_created ON records(account_id, record_type_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_records_account_created ON records(account_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_records_source_call_log ON records(source_call_log_id)",
    "CREATE INDEX IF NOT EXISTS ix_records_source_conversation ON records(source_conversation_id)",
    # Idempotency backstop for automatic extraction: at most one auto-extracted
    # record per (record_type, source conversation). Partial so manual and
    # flow_node records (which may legitimately repeat) are unconstrained. These
    # are the ON CONFLICT arbiters used by the extraction service.
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_records_autoextract_call
       ON records(record_type_id, source_call_log_id)
       WHERE capture_method = 'auto_extract' AND source_call_log_id IS NOT NULL""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_records_autoextract_conversation
       ON records(record_type_id, source_conversation_id)
       WHERE capture_method = 'auto_extract' AND source_conversation_id IS NOT NULL""",
    # ── Per-property data isolation (Task #327) ─────────────────────────────
    # New `properties` table + nullable property_id FK on the three resources
    # that determine or are resolved during a live session. The table is also
    # created by Base.metadata.create_all; the CREATE TABLE IF NOT EXISTS here
    # guarantees it exists before the ALTER TABLE ... REFERENCES properties(id)
    # statements run on a pre-existing deployment. All statements are additive.
    """
    CREATE TABLE IF NOT EXISTS properties (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        address TEXT,
        timezone VARCHAR(50),
        is_default BOOLEAN NOT NULL DEFAULT FALSE,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_properties_account_id ON properties(account_id)",
    # property_id is nullable everywhere — NULL means account-global / shared.
    "ALTER TABLE phone_numbers ADD COLUMN IF NOT EXISTS property_id UUID REFERENCES properties(id) ON DELETE SET NULL",
    "ALTER TABLE assistants ADD COLUMN IF NOT EXISTS property_id UUID REFERENCES properties(id) ON DELETE SET NULL",
    "ALTER TABLE account_integrations ADD COLUMN IF NOT EXISTS property_id UUID REFERENCES properties(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_phone_numbers_property_id ON phone_numbers(property_id)",
    "CREATE INDEX IF NOT EXISTS ix_assistants_property_id ON assistants(property_id)",
    "CREATE INDEX IF NOT EXISTS ix_account_integrations_property_id ON account_integrations(property_id)",
    # Task #331 — cross-worker integration resilience state (rate limiter +
    # circuit breaker). Keyed by integration_id; deliberately NO foreign keys so
    # these ephemeral operational counters remain writable even for detached
    # (test-injected) integrations and never block an integration delete. Also
    # created by Base.metadata.create_all; the IF NOT EXISTS keeps pre-existing
    # deployments in sync. account_id is stored for observability only.
    """
    CREATE TABLE IF NOT EXISTS integration_rate_limits (
        integration_id UUID PRIMARY KEY,
        account_id UUID,
        tokens DOUBLE PRECISION NOT NULL DEFAULT 0,
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_integration_rate_limits_account_id ON integration_rate_limits(account_id)",
    """
    CREATE TABLE IF NOT EXISTS integration_circuit_breakers (
        integration_id UUID PRIMARY KEY,
        account_id UUID,
        state VARCHAR(16) NOT NULL DEFAULT 'closed',
        failure_count INTEGER NOT NULL DEFAULT 0,
        opened_at TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_integration_circuit_breakers_account_id ON integration_circuit_breakers(account_id)",
    # Universal API Adapter (Task #356) — DYNAMIC_OPERATION ToolType enum value
    "ALTER TYPE tooltype ADD VALUE IF NOT EXISTS 'DYNAMIC_OPERATION'",
    # IntegrationActionKind.IMPORTED enum value
    "ALTER TYPE integrationactionkind ADD VALUE IF NOT EXISTS 'imported'",
    "ALTER TYPE integrationactionkind ADD VALUE IF NOT EXISTS 'IMPORTED'",
    # MCP Streamable HTTP transport (MCP spec 2025-03-26)
    "ALTER TYPE mcptransporttype ADD VALUE IF NOT EXISTS 'streamable_http'",
    # IntegrationType new columns for imported specs
    "ALTER TABLE integration_types ADD COLUMN IF NOT EXISTS origin VARCHAR(32) NOT NULL DEFAULT 'botelier_certified'",
    "ALTER TABLE integration_types ADD COLUMN IF NOT EXISTS source_type VARCHAR(32)",
    "ALTER TABLE integration_types ADD COLUMN IF NOT EXISTS raw_spec JSONB",
    "ALTER TABLE integration_types ADD COLUMN IF NOT EXISTS spec_version VARCHAR(64)",
    "ALTER TABLE integration_types ADD COLUMN IF NOT EXISTS spec_url VARCHAR(2048)",
    # AccountIntegration new columns
    "ALTER TABLE account_integrations ADD COLUMN IF NOT EXISTS environment VARCHAR(32) NOT NULL DEFAULT 'production'",
    "ALTER TABLE account_integrations ADD COLUMN IF NOT EXISTS allowed_base_domains JSONB NOT NULL DEFAULT '[]'",
    # IntegrationAction new columns
    "ALTER TABLE integration_actions ADD COLUMN IF NOT EXISTS connection_id UUID REFERENCES account_integrations(id) ON DELETE SET NULL",
    "ALTER TABLE integration_actions ADD COLUMN IF NOT EXISTS source_endpoint_id VARCHAR(255)",
    "ALTER TABLE integration_actions ADD COLUMN IF NOT EXISTS param_ownership JSONB",
    "ALTER TABLE integration_actions ADD COLUMN IF NOT EXISTS response_policy JSONB",
    "CREATE INDEX IF NOT EXISTS ix_integration_actions_connection ON integration_actions(connection_id)",
    # created_by_account_id on integration_types for account-scoped imported spec queries
    "ALTER TABLE integration_types ADD COLUMN IF NOT EXISTS created_by_account_id UUID REFERENCES accounts(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_integration_types_created_by_account ON integration_types(created_by_account_id)",
    # connection_operation_policies — per-connection operation control table
    # enabled defaults FALSE (safe-default: operators must explicitly enable each operation)
    """
    CREATE TABLE IF NOT EXISTS connection_operation_policies (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        account_integration_id UUID NOT NULL REFERENCES account_integrations(id) ON DELETE CASCADE,
        operation_id VARCHAR(255) NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT FALSE,
        risk_level VARCHAR(32),
        confirm_required BOOLEAN NOT NULL DEFAULT FALSE,
        approval_required BOOLEAN NOT NULL DEFAULT FALSE,
        max_amount DOUBLE PRECISION,
        max_executions_per_conv INTEGER,
        allowed_channels JSONB,
        response_size_bytes INTEGER NOT NULL DEFAULT 32768,
        redact_field_patterns JSONB,
        test_status VARCHAR(16),
        tested_at TIMESTAMP,
        test_passed BOOLEAN,
        test_error TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP,
        UNIQUE(account_integration_id, operation_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_connection_operation_policies_integration ON connection_operation_policies(account_integration_id)",
    # Fix enabled DEFAULT for existing tables created with DEFAULT TRUE
    "ALTER TABLE connection_operation_policies ALTER COLUMN enabled SET DEFAULT FALSE",
    # approval_requests — pending human approvals for high-risk operations
    # Schema matches ApprovalRequest ORM model exactly
    """
    CREATE TABLE IF NOT EXISTS approval_requests (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        integration_id UUID REFERENCES account_integrations(id) ON DELETE SET NULL,
        action_id UUID REFERENCES integration_actions(id) ON DELETE SET NULL,
        channel VARCHAR(32) NOT NULL,
        call_sid VARCHAR(64),
        requested_args JSONB,
        amount NUMERIC(12,2),
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        resolved_by UUID REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        resolved_at TIMESTAMP,
        expires_at TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_approval_requests_account_status ON approval_requests(account_id, status)",
    # Additive column migrations for DBs where approval_requests was created with
    # the old migration schema (pre-model-alignment).  All IF NOT EXISTS so they
    # are no-ops on fresh DBs where create_all already produced the correct schema.
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS integration_id UUID REFERENCES account_integrations(id) ON DELETE SET NULL",
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS action_id UUID REFERENCES integration_actions(id) ON DELETE SET NULL",
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS call_sid VARCHAR(64)",
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS requested_args JSONB",
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS amount NUMERIC(12,2)",
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS resolved_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP",
    "CREATE INDEX IF NOT EXISTS ix_approval_requests_call_sid ON approval_requests(call_sid)",
    "CREATE INDEX IF NOT EXISTS ix_approval_requests_integration ON approval_requests(integration_id)",
    "CREATE INDEX IF NOT EXISTS ix_approval_requests_action ON approval_requests(action_id)",
    # Task #390 — per-record audit trail. record_id deliberately has NO foreign
    # key so the "deleted" entry survives the record row's deletion.
    """
    CREATE TABLE IF NOT EXISTS record_activity (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        record_id UUID NOT NULL,
        actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
        action VARCHAR(32) NOT NULL,
        old_status VARCHAR(60),
        new_status VARCHAR(60),
        changed_fields JSONB,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_record_activity_account_id ON record_activity(account_id)",
    "CREATE INDEX IF NOT EXISTS ix_record_activity_record_created ON record_activity(record_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_record_activity_account_created ON record_activity(account_id, created_at)",
    # Task #390 — per-user UI preferences (e.g. saved dashboard timezone).
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS ui_preferences JSONB NOT NULL DEFAULT '{}'",
    # Per-assistant barge-in control: when FALSE, callers cannot interrupt the
    # bot mid-response (AlwaysUserMuteStrategy suppresses caller audio while
    # the bot is speaking). Applies to both Silero-VAD and Deepgram Flux paths.
    "ALTER TABLE assistants ADD COLUMN IF NOT EXISTS allow_interruptions BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE assistants ADD COLUMN IF NOT EXISTS allowed_connection_ids JSONB DEFAULT '[]'",
    # Task #538 — IANA timezone used for assistant-local date/time interpretation.
    "ALTER TABLE assistants ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) NOT NULL DEFAULT 'UTC'",
    # Task #450 — Response field projection for imported API operations.
    # response_mapping: {variable_name: jsonpath} — only extracted fields sent to LLM.
    # param_ownership_overrides: {param_name: "llm"|"connection"|"fixed"} — overrides seed.
    "ALTER TABLE connection_operation_policies ADD COLUMN IF NOT EXISTS response_mapping JSONB",
    "ALTER TABLE connection_operation_policies ADD COLUMN IF NOT EXISTS param_ownership_overrides JSONB",
    "ALTER TABLE connection_operation_policies ADD COLUMN IF NOT EXISTS request_overrides JSONB",
]


def _run_hotel_account_migration():
    """Pre-cutover hotel → account data integrity step (fail-fast).

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
        result = conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'hotels')"
            )
        )
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
        hotels_cols_res = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'hotels' ORDER BY ordinal_position"
            )
        )
        hotels_cols = {r[0] for r in hotels_cols_res}

        accounts_cols_res = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'accounts' ORDER BY ordinal_position"
            )
        )
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
                exists = conn.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                        f"WHERE table_name = '{table}' AND column_name = '{candidate}')"
                    )
                ).scalar()
                if exists:
                    col = candidate
                    break
            if col is None:
                logger.warning(
                    f"Hotel→account migration: no hotel_id/account_id column in {table} — skipping."
                )
                continue
            count = conn.execute(
                text(
                    f"SELECT COUNT(*) FROM {table} t "
                    f"WHERE t.{col} IS NOT NULL "
                    f"AND NOT EXISTS (SELECT 1 FROM accounts a WHERE a.id = t.{col})"
                )
            ).scalar()
            if count > 0:
                logger.error(
                    f"Hotel→account migration: INTEGRITY FAILURE — "
                    f"{count} orphan rows in {table}.{col}"
                )
                orphan_found = True
            else:
                logger.debug(f"Hotel→account migration: {table}.{col} ✓ (no orphans)")

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


def _convert_combined_voice_rates():
    """Append one outbound-only config for each active combined-rate config.

    Existing rows remain immutable for historical reconciliation. A PostgreSQL
    advisory transaction lock prevents multiple ACA replicas from appending the
    same conversion row concurrently during a rolling deployment.
    """
    from decimal import Decimal

    from botelier.models.billing import AccountBillingConfig

    db = SessionLocal()
    try:
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext('botelier_voice_rate_model_v1'))"))
        now = datetime.utcnow()
        rows = (
            db.query(AccountBillingConfig)
            .filter(AccountBillingConfig.effective_from <= now)
            .order_by(
                AccountBillingConfig.account_id,
                AccountBillingConfig.effective_from.desc(),
                AccountBillingConfig.created_at.desc(),
            )
            .all()
        )
        latest_by_account = {}
        for row in rows:
            key = str(row.account_id) if row.account_id is not None else "__platform_default__"
            latest_by_account.setdefault(key, row)

        converted = 0
        for row in latest_by_account.values():
            if (row.voice_rate_model or "combined") != "combined":
                continue
            outbound_only = max(
                Decimal("0"),
                Decimal(str(row.outbound_rate_usd)) - Decimal(str(row.inbound_rate_usd)),
            )
            db.add(
                AccountBillingConfig(
                    account_id=row.account_id,
                    inbound_rate_usd=row.inbound_rate_usd,
                    outbound_rate_usd=outbound_only,
                    voice_rate_model="separate",
                    sms_inbound_rate_usd=row.sms_inbound_rate_usd,
                    sms_outbound_rate_usd=row.sms_outbound_rate_usd,
                    monthly_alert_threshold_usd=row.monthly_alert_threshold_usd,
                    effective_from=now,
                )
            )
            converted += 1
        db.commit()
        if converted:
            logger.info(
                f"Voice billing rate conversion complete: appended {converted} outbound-only configs"
            )
    except Exception:
        db.rollback()
        logger.exception(
            "Voice billing rate conversion failed; refusing startup to avoid "
            "charging combined outbound rates as outbound-only rates"
        )
        raise
    finally:
        db.close()


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
    """Idempotent data sync: align all system role permission rows with DEFAULT_ROLES.

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
    from botelier.auth.permissions import DEFAULT_ROLES
    from botelier.models.role import Role

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
                f"Syncing system role permissions: {role.slug} (account_id={role.account_id})"
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


_SILERO_VAD_DEFAULTS = {
    "confidence": 0.7,
    "start_secs": 0.2,
    # stop_secs=0.2 matches pipecat's recommended VAD_STOP_SECS default; the
    # bundled STT TTFS p99 latency tables (used by TurnAnalyzerUserTurnStop
    # Strategy to size the post-VAD wait window) are calibrated against this
    # value.  SmartTurn V3 (smart_turn_stop_secs) handles the soft "is the
    # caller really done?" decision, so a tighter VAD silence threshold does
    # not cut off slow speakers.
    "stop_secs": 0.2,
    # Baseline tuned for typical hotel ambient noise; in noisier environments
    # operators usually land in the ~0.35–0.45 range to reduce false barge-in.
    "min_volume": 0.4,
    "smart_turn_stop_secs": 0.5,
}
# Optional guard in vad_config for rolling out min_volume tuning changes.
_SILERO_MIN_VOLUME_TUNING_FLAG = "enable_min_volume_tuning_v2"


def _backfill_silero_vad_config():
    """Idempotent data backfill: populate vad_config for Silero assistants that
    have a null or empty JSON object stored.

    WHY THIS EXISTS
    The engine reads VAD parameters from ``assistant.vad_config`` and falls
    back to hardcoded defaults when the key is absent.  Prior to this fix the
    fallback values were wrong (start_secs=0.0, min_volume=0.0), causing any
    background noise to immediately interrupt the bot.  Assistants created or
    saved before the fix have ``vad_config = {}`` in the DB and therefore ran
    with the broken defaults.

    HOW IT WORKS
    On every startup this function finds all silero assistants whose
    vad_config is null or ``{}``, and writes the full set of canonical
    defaults.  Rows that already have at least one key set are left untouched
    (the frontend merge logic handles missing keys at runtime).  Idempotent —
    safe to re-run.
    """
    db = SessionLocal()
    try:
        from sqlalchemy import cast, or_
        from sqlalchemy.dialects.postgresql import JSONB

        from botelier.models.assistant import Assistant

        candidates = (
            db.query(Assistant)
            .filter(Assistant.vad_provider == "silero")
            .filter(
                or_(
                    Assistant.vad_config.is_(None),
                    cast(Assistant.vad_config, JSONB) == cast("{}", JSONB),
                )
            )
            .all()
        )
        updated = []
        for asst in candidates:
            asst.vad_config = _SILERO_VAD_DEFAULTS.copy()
            updated.append(asst.name)
            logger.info(
                f"VAD config backfill: set defaults for assistant '{asst.name}' ({asst.id})"
            )

        # Task #107: normalize any Silero assistants whose explicit
        # vad_config.stop_secs would collapse the post-VAD STT wait window
        # in TurnAnalyzerUserTurnStopStrategy.  Pipecat's bundled
        # DEEPGRAM_TTFS_P99 (~0.35 s) is calibrated against
        # VAD_STOP_SECS=0.2; anything >= 0.35 s makes the wait timeout
        # collapse to 0 s and triggers the recurring warnings.  We clamp
        # to 0.2 s only when the operator has NOT provided a measured
        # stt_config.ttfs_p99_latency override (in which case they
        # intentionally accept the higher silence threshold and have
        # widened the STT wait window themselves).
        normalize_candidates = (
            db.query(Assistant)
            .filter(Assistant.vad_provider == "silero")
            .filter(Assistant.vad_config.isnot(None))
            .all()
        )
        normalized_stop_secs = []
        normalized_min_volume = []
        for asst in normalize_candidates:
            cfg = asst.vad_config or {}
            stop_secs = cfg.get("stop_secs")
            if stop_secs is None:
                continue
            try:
                stop_secs_f = float(stop_secs)
            except (TypeError, ValueError):
                continue
            stt_cfg = asst.stt_config or {}
            has_ttfs_override = stt_cfg.get("ttfs_p99_latency") is not None
            if stop_secs_f >= 0.35 and not has_ttfs_override:
                new_cfg = dict(cfg)
                new_cfg["stop_secs"] = 0.2
                prev_notes = cfg.get("_notes", "")
                normalize_note = (
                    f"Task #107 backfill: stop_secs {stop_secs_f} -> 0.2 "
                    f"(would collapse STT wait window against bundled "
                    f"DEEPGRAM_TTFS_P99). Set stt_config.ttfs_p99_latency "
                    f"above the new stop_secs to raise it again."
                )
                new_cfg["_notes"] = (
                    f"{prev_notes} | {normalize_note}".strip(" |") if prev_notes else normalize_note
                )
                asst.vad_config = new_cfg
                normalized_stop_secs.append(f"{asst.name} ({stop_secs_f}->0.2)")
                logger.info(
                    f"VAD config backfill: clamped stop_secs {stop_secs_f}->0.2 "
                    f"for assistant '{asst.name}' ({asst.id})"
                )

        # Optional guarded normalization for legacy min_volume defaults.
        # Only runs when the assistant has explicitly opted into the new
        # tuning behavior via _SILERO_MIN_VOLUME_TUNING_FLAG.
        for asst in normalize_candidates:
            cfg = asst.vad_config or {}
            if not cfg.get(_SILERO_MIN_VOLUME_TUNING_FLAG, False):
                continue

            min_volume = cfg.get("min_volume")
            if min_volume is None:
                continue
            try:
                min_volume_f = float(min_volume)
            except (TypeError, ValueError):
                continue

            # 0.6 is treated as a legacy default-like value that can be safely
            # normalized for opted-in assistants. Any other value is preserved.
            if min_volume_f != 0.6:
                continue

            new_cfg = dict(cfg)
            new_cfg["min_volume"] = _SILERO_VAD_DEFAULTS["min_volume"]
            asst.vad_config = new_cfg
            normalized_min_volume.append(
                f"{asst.name} ({min_volume_f}->{_SILERO_VAD_DEFAULTS['min_volume']})"
            )
            logger.info(
                "VAD config backfill: normalized legacy min_volume "
                f"{min_volume_f}->{_SILERO_VAD_DEFAULTS['min_volume']} for assistant "
                f"'{asst.name}' ({asst.id})"
            )

        if updated or normalized_stop_secs or normalized_min_volume:
            db.commit()
            if updated:
                logger.info(
                    f"VAD config backfill complete — defaulted {len(updated)} "
                    f"assistant(s): {', '.join(updated)}"
                )
            if normalized_stop_secs:
                logger.info(
                    f"VAD config backfill complete — normalized stop_secs on "
                    f"{len(normalized_stop_secs)} assistant(s): {', '.join(normalized_stop_secs)}"
                )
            if normalized_min_volume:
                logger.info(
                    "VAD config backfill complete — normalized legacy min_volume on "
                    f"{len(normalized_min_volume)} assistant(s): {', '.join(normalized_min_volume)}"
                )
        else:
            logger.info("VAD config backfill — all Silero assistants already configured")

    except Exception as e:
        logger.error(f"VAD config backfill failed (non-fatal): {e}")
        db.rollback()
    finally:
        db.close()


def _backfill_smart_turn_stop_secs_default():
    """Idempotent data backfill for legacy SmartTurn stop default drift.

    Assistants created before the lower-latency default may still store
    ``vad_config.smart_turn_stop_secs = 1.0``. That exact value historically
    came from system defaults, so we treat it as legacy default and backfill to
    0.5. Explicit custom values (anything other than 1.0, including null/missing)
    are preserved.
    """
    db = SessionLocal()
    try:
        from botelier.models.assistant import Assistant

        candidates = (
            db.query(Assistant)
            .filter(Assistant.vad_provider == "silero")
            .filter(Assistant.vad_config.isnot(None))
            .all()
        )

        updated = []
        for asst in candidates:
            cfg = asst.vad_config or {}
            if "smart_turn_stop_secs" not in cfg:
                continue
            try:
                current = float(cfg.get("smart_turn_stop_secs"))
            except (TypeError, ValueError):
                continue
            if current != 1.0:
                continue

            new_cfg = dict(cfg)
            new_cfg["smart_turn_stop_secs"] = 0.5
            asst.vad_config = new_cfg
            updated.append(asst.name)
            logger.info(
                f"VAD config backfill: updated smart_turn_stop_secs 1.0->0.5 "
                f"for assistant '{asst.name}' ({asst.id})"
            )

        if updated:
            db.commit()
            logger.info(
                "VAD config backfill complete — updated legacy "
                f"smart_turn_stop_secs on {len(updated)} assistant(s): {', '.join(updated)}"
            )
        else:
            logger.info("VAD config backfill — no legacy smart_turn_stop_secs defaults found")

    except Exception as e:
        logger.error(f"VAD smart_turn_stop_secs backfill failed (non-fatal): {e}")
        db.rollback()
    finally:
        db.close()


def _backfill_billing_tool_data():
    """Idempotent data fix: set account_id and tighten description on any FLOW
    tool named 'billing' that still has account_id=NULL.

    WHY THIS EXISTS
    The billing FLOW tool was created without an account_id, leaving it as an
    apparent platform-level tool with a vague description ("Double charge for
    room service.").  That vagueness caused the LLM to invoke start_billing
    speculatively on every call before the caller mentioned any billing issue.

    HOW IT WORKS
    Finds every Tool row where name='billing', tool_type='FLOW', and
    account_id IS NULL.  For each such row it resolves the owning account via
    the tool's tool_set and sets:
      - account_id  = tool_set.account_id
      - description = guard-railed trigger language
    Idempotent: once account_id is set the row is skipped on subsequent runs.
    """
    db = SessionLocal()
    try:
        from botelier.models.tool import Tool

        orphaned = (
            db.query(Tool)
            .filter(Tool.name == "billing", Tool.tool_type == "FLOW", Tool.account_id.is_(None))
            .all()
        )

        if not orphaned:
            logger.debug("Billing tool data fix — no orphaned billing tools found, skipping")
            return

        updated = []
        for tool in orphaned:
            if not tool.tool_set_id:
                logger.warning(
                    f"Billing tool data fix — tool {tool.id} has no tool_set_id, skipping"
                )
                continue

            result = db.execute(
                __import__("sqlalchemy").text(
                    "SELECT account_id FROM tool_sets WHERE id = :id"
                ),
                {"id": str(tool.tool_set_id)},
            ).fetchone()

            if not result or not result[0]:
                logger.warning(
                    f"Billing tool data fix — tool_set {tool.tool_set_id} "
                    "has no account_id, skipping"
                )
                continue

            tool.account_id = result[0]
            tool.description = (
                "Handle a caller complaint about being charged twice for room service "
                "or an incorrect billing charge on their account. "
                "Only invoke this flow when the caller explicitly mentions a duplicate charge, "
                "an incorrect charge, or a billing dispute — "
                "do not invoke for general questions, complaints about other matters, "
                "or requests unrelated to billing."
            )
            updated.append(str(tool.id))
            logger.info(
                f"Billing tool data fix — set account_id={result[0]} "
                f"and updated description for tool {tool.id}"
            )

        if updated:
            db.commit()
            logger.info(
                f"Billing tool data fix complete — updated {len(updated)} tool(s): "
                + ", ".join(updated)
            )

    except Exception as e:
        logger.error(f"Billing tool data fix failed (non-fatal): {e}")
        db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GuestCentric availability-narration backfill
#
# WHY THIS EXISTS
# An early GuestCentric flow seed described the API response fields incorrectly:
# the per-node responseInstructions named "room_type_name" and "rate_plan_name"
# as fields inside each room_rates item, but GuestCentric's API only returns
# "room_type_code" and "rate_plan_code" in room_rates.  Room/rate display names
# live in the separate "rooms" and "rates" top-level arrays.
#
# Any flow version saved from that seed will produce silent or wrong narration
# on a live call because the LLM receives a narration script referencing fields
# that don't exist.  The corrected seed references "available_rooms" for the
# name list and "rooms"/"rates" for per-code name lookups.
#
# HOW IT WORKS
# On startup, queries every flow_versions row whose serialised JSON contains
# "room_type_name" (fast DB-side filter) and checks each node for the exact
# broken pattern (api_request + GC slug + hotel_rooms + old instructions).
# Affected nodes are patched to the corrected responseInstructions text.
# Idempotent: re-running is safe (old text is absent after the first run).
# ---------------------------------------------------------------------------

# The old seed text used this phrase to describe a nonexistent field.
_GC_OLD_NARRATION_MARKER = "room_type_name"

# Corrected responseInstructions that reference fields that actually exist in GC data.
_GC_CORRECTED_NARRATION = (
    "ROOM AVAILABILITY RESULTS\n\n"
    "Available room names (speak these): {{available_rooms}}\n\n"
    "Room + rate combinations: {{room_rates}}\n"
    "  NOTE: each item has room_type_code and rate_plan_code (internal codes, never speak).\n"
    "  total_price = total stay price. currency = price currency.\n\n"
    "Room name lookup (room_type_code \u2192 name): {{rooms}}\n"
    "Rate plan lookup (rate_plan_code \u2192 name): {{rates}}\n\n"
    "IF available_rooms IS EMPTY OR room_rates IS EMPTY OR NULL:\n"
    "  Say: 'I\u2019m sorry, I wasn\u2019t able to find any rooms available for those dates. "
    "Would you like to try different check-in and check-out dates?'\n"
    "  Do NOT proceed to room selection.\n\n"
    "IF available_rooms AND room_rates HAVE RESULTS:\n"
    "  1. Say: 'Great news \u2014 I found [N] room type(s) available for your dates.'\n"
    "  2. List each room by its display name from available_rooms (or the name field in rooms).\n"
    "  3. For each room, state the price by matching room_type_code in room_rates.\n"
    "  4. Look up the rate plan display name from the rates array using rate_plan_code.\n"
    "  5. Ask: 'Which room type would you prefer?'\n"
    "  Important: always speak display names (from rooms/rates); store only codes."
)

# Integration slug + endpoint ID that unambiguously identify the GC availability node.
_GC_INTEGRATION_SLUGS = {"guestcentric-crs", "guestcentric"}
_GC_AVAILABILITY_ENDPOINT = "hotel_rooms"


def _patch_gc_availability_node(node: dict) -> bool:
    """Patch a single flow node in-place if it has the old GC availability instructions.

    Returns True if the node was modified, False otherwise.

    The function is deliberately conservative: it only touches api_request nodes
    that have both the GC integration slug and the hotel_rooms endpoint, and whose
    responseInstructions still contain the old marker phrase.  Any node that has
    already been updated (marker absent) is left untouched.
    """
    if node.get("type") != "api_request":
        return False
    api_cfg = (node.get("data") or {}).get("api") or {}
    slug = api_cfg.get("integrationSlug", "")
    endpoint = api_cfg.get("endpointId", "")
    ri = api_cfg.get("responseInstructions", "")
    if slug not in _GC_INTEGRATION_SLUGS:
        return False
    if endpoint != _GC_AVAILABILITY_ENDPOINT:
        return False
    if _GC_OLD_NARRATION_MARKER not in ri:
        return False
    api_cfg["responseInstructions"] = _GC_CORRECTED_NARRATION
    return True


def _backfill_gc_availability_instructions():
    """Idempotent startup backfill: fix old GC availability responseInstructions.

    Finds every flow_versions row containing 'room_type_name' in its serialised
    JSON (a fast DB-side text scan), then patches any api_request node that has
    the GuestCentric hotel_rooms endpoint configured with the old incorrect
    responseInstructions that reference non-existent room_type_name fields.
    """
    from botelier.models.flow_version import FlowVersion

    db = SessionLocal()
    try:
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('botelier_gc_availability_narration_v1'))")
        )
        candidates = (
            db.query(FlowVersion)
            .filter(
                FlowVersion.flow_config.cast(__import__("sqlalchemy").Text).like(
                    f"%{_GC_OLD_NARRATION_MARKER}%"
                )
            )
            .all()
        )
        if not candidates:
            logger.debug(
                "GC availability narration backfill — no legacy flow versions found, skipping"
            )
            return

        patched_count = 0
        for fv in candidates:
            cfg = fv.flow_config or {}
            nodes = cfg.get("nodes") or []
            changed = False
            for node in nodes:
                if _patch_gc_availability_node(node):
                    changed = True
                    patched_count += 1
            if changed:
                # Trigger SQLAlchemy to detect the JSONB mutation
                from sqlalchemy.orm.attributes import flag_modified

                flag_modified(fv, "flow_config")

        db.commit()
        if patched_count:
            logger.info(
                f"GC availability narration backfill — patched {patched_count} node(s) "
                f"across {len(candidates)} flow version(s)"
            )
        else:
            logger.debug(
                "GC availability narration backfill — candidates found but no nodes needed patching"
            )
    except Exception:
        db.rollback()
        logger.exception("GC availability narration backfill — failed (non-fatal)")
    finally:
        db.close()


def run_stuck_call_sweeper(skip_call_sids: Optional[set] = None, age_minutes: int = 30) -> dict:
    """Task #96: periodic safety-net that finalizes CallLog rows abandoned in any
    non-terminal status (``initiated`` / ``ringing`` / ``in_progress``).

    Runs at startup (``init_db``) with ``skip_call_sids=None`` (nothing is in
    memory yet) and again every 5 minutes from the main app lifespan loop,
    with the set of in-flight ``call_sid``s passed in so we never close a row
    under a healthy pipeline.

    Each reclassified row goes through ``CallLogger.complete_call`` with
    ``forced_by="sweeper"`` so a ``finalization_forced`` CallEvent is emitted
    for leak-rate observability (read by Task #97).

    Guards:
      * ``age_minutes`` (default 30 min): calls younger than this are always
        skipped — a conservative upper bound that comfortably exceeds any
        realistic AI conversation length and avoids finalizing a real
        in-flight call if the in-memory liveness signal ever misses one.
      * ``skip_call_sids``: call_sids registered in ``CallHandler.active_calls``
        / ``call_tasks``. Never finalized by the sweeper even if age exceeds
        threshold.
      * Transfer legs: rows with ``has_transfer=TRUE`` AND a transfer CallLeg
        still in a non-terminal state are skipped — an external warm transfer
        can legitimately outlive the AI pipeline.

    Returns a summary dict with counts keyed by final status, suitable for
    logging and future metrics.
    """
    from botelier.models.call_log import CallLeg, CallLog
    from botelier.models.call_log import CallStatus as _CS
    from botelier.models.call_log import LegType as _LT
    from botelier.services.call_logger import CallLogger

    _TRANSFER_LEG_TYPES = [
        _LT.TRANSFER_EXTERNAL.value,
        _LT.TRANSFER_SIP.value,
        _LT.TRANSFER_INTERNAL.value,
        _LT.TRANSFER_COLD.value,
    ]

    summary = {
        "scanned": 0,
        "finalized": 0,
        "skipped_active": 0,
        "skipped_transfer": 0,
        "errors": 0,
    }
    skip_set = set(skip_call_sids or ())

    _NON_TERMINAL_LEG_STATUSES = (
        _CS.INITIATED.value,
        _CS.RINGING.value,
        _CS.IN_PROGRESS.value,
    )

    db = SessionLocal()
    try:
        candidates = (
            db.query(CallLog)
            .filter(
                CallLog.status.in_(_NON_TERMINAL_LEG_STATUSES),
                CallLog.ended_at.is_(None),
                CallLog.started_at < datetime.utcnow() - timedelta(minutes=age_minutes),
            )
            .all()
        )
        summary["scanned"] = len(candidates)

        for row in candidates:
            if row.call_sid in skip_set:
                summary["skipped_active"] += 1
                continue

            if row.has_transfer:
                transfer_active = (
                    db.query(CallLeg.id)
                    .filter(
                        CallLeg.call_log_id == row.id,
                        CallLeg.leg_type.in_(_TRANSFER_LEG_TYPES),
                        CallLeg.status.in_(_NON_TERMINAL_LEG_STATUSES),
                    )
                    .first()
                    is not None
                )
                if transfer_active:
                    summary["skipped_transfer"] += 1
                    continue

            age_seconds = (
                int((datetime.utcnow() - row.started_at).total_seconds())
                if row.started_at
                else None
            )
            try:
                _ok = CallLogger(db).complete_call(
                    call_sid=row.call_sid,
                    forced_by="sweeper",
                    sweeper_age_seconds=age_seconds,
                )
                if _ok:
                    summary["finalized"] += 1
                else:
                    summary["errors"] += 1
                    logger.warning(f"Sweeper: complete_call returned False for {row.call_sid}")
            except Exception as e:
                summary["errors"] += 1
                db.rollback()
                logger.warning(f"Sweeper: failed to finalize {row.call_sid}: {e}")
    except Exception as e:
        logger.error(f"run_stuck_call_sweeper failed: {e}")
        summary["errors"] += 1
    finally:
        db.close()

    if summary["scanned"] or summary["finalized"]:
        logger.info(f"Stuck-call sweeper: {summary}")
    return summary


def _backfill_stuck_initiated_calls():
    """One-time-style data backfill: reclassify CallLog rows that are stuck on
    status='initiated' with ended_at=NULL.

    WHY THIS EXISTS
    A bug in incoming_call_webhook (now fixed) returned an empty TwiML on
    terminal-status webhook re-POSTs without updating the existing CallLog row.
    The result is rows that stay on status='initiated', ended_at=NULL forever
    and show up as perpetually-running ghost calls in the dashboard.

    HOW IT WORKS
    On every startup this function finds any CallLog rows where
        status='initiated' AND ended_at IS NULL AND started_at < NOW() - 5 min
    and updates them to a sane terminal state:
        status='no_answer', ended_early=TRUE,
        ended_at = started_at + 30s, duration_seconds = 0.
    Status is the canonical underscore form (CallStatus.NO_ANSWER.value), which
    is what the rest of the application reads/filters/renders.
    The 5-minute guard ensures an in-progress call is never touched.
    The leg update is tightly scoped to ONLY the rows updated by this run via a
    CTE + RETURNING id, so pre-existing no_answer rows are never re-touched.
    Idempotent — safe to re-run; no-op once data is clean.
    """
    with engine.connect() as conn:
        try:
            # CTE returns the IDs of rows we just backfilled, then the second
            # statement updates legs strictly belonging to those IDs.
            result = conn.execute(
                text(
                    """
                WITH backfilled AS (
                    UPDATE call_logs
                       SET status = 'no_answer',
                           ended_early = TRUE,
                           ended_at = started_at + INTERVAL '30 seconds',
                           duration_seconds = 0
                     WHERE status = 'initiated'
                       AND ended_at IS NULL
                       AND started_at < NOW() - INTERVAL '5 minutes'
                 RETURNING id, started_at
                ),
                leg_update AS (
                    UPDATE call_legs cl
                       SET status = 'no_answer',
                           ended_at = b.started_at + INTERVAL '30 seconds',
                           duration_seconds = 0
                      FROM backfilled b
                     WHERE cl.call_log_id = b.id
                       AND cl.leg_type = 'ai_conversation'
                       AND cl.ended_at IS NULL
                 RETURNING cl.id
                )
                SELECT
                    (SELECT COUNT(*) FROM backfilled) AS call_count,
                    (SELECT COUNT(*) FROM leg_update) AS leg_count
                """
                )
            )
            row = result.fetchone()
            call_count = (row[0] if row else 0) or 0
            leg_count = (row[1] if row else 0) or 0
            conn.commit()
            if call_count > 0:
                logger.info(
                    f"Stuck-initiated backfill: reclassified {call_count} call_log row(s) "
                    f"and {leg_count} matching ai_conversation leg(s) "
                    f"as no_answer/ended_early."
                )
            else:
                logger.info("Stuck-initiated backfill — no orphan rows found")
        except Exception as e:
            logger.error(f"Stuck-initiated backfill failed (non-fatal): {e}")
            try:
                conn.rollback()
            except Exception:
                pass


def _backfill_default_properties():
    """Task #327 — idempotent per-property isolation backfill.

    WHY THIS EXISTS
    The properties table and the nullable ``property_id`` FK on phone_numbers,
    assistants, and account_integrations are added additively. Existing accounts
    have no property rows and NULL property_ids. To preserve current
    single-property behavior with zero operator action, every account that owns
    any of those resources gets exactly one default property, and its existing
    resources are stamped with that property.

    HOW IT WORKS (all statements idempotent, safe to re-run every startup)
    1. Create one ``is_default=TRUE`` property for each account that owns
       resources but has no property yet.
    2. For accounts whose ONLY property is that single default, stamp NULL
       property_ids on their resources with that property id.

    Step 2 is deliberately scoped to accounts that have exactly one property.
    Once an operator adds a second property to an account, that account has
    opted into multi-property mode and a NULL property_id becomes an
    intentional "account-global / shared" marker — so we must NOT auto-stamp
    those NULLs, or we would silently bind a shared connection to one property.
    For a single-property account, "global" and "the one default property" are
    functionally identical, so stamping is behavior-preserving.
    """
    statements = [
        # 1. Default property for resource-owning accounts that have none.
        """
        INSERT INTO properties (id, account_id, name, is_default, is_active, created_at)
        SELECT gen_random_uuid(), a.id, 'Default', TRUE, TRUE, NOW()
        FROM accounts a
        WHERE NOT EXISTS (SELECT 1 FROM properties p WHERE p.account_id = a.id)
          AND (
                EXISTS (SELECT 1 FROM phone_numbers pn WHERE pn.account_id = a.id)
             OR EXISTS (SELECT 1 FROM assistants asst WHERE asst.account_id = a.id)
             OR EXISTS (SELECT 1 FROM account_integrations ai WHERE ai.account_id = a.id)
          )
        """,
        # 2. Stamp NULL property_ids for single-(default-)property accounts only.
        """
        WITH single_prop AS (
            SELECT p.account_id, p.id AS property_id
            FROM properties p
            WHERE p.is_default = TRUE
              AND (SELECT COUNT(*) FROM properties p2 WHERE p2.account_id = p.account_id) = 1
        )
        UPDATE phone_numbers pn
        SET property_id = sp.property_id
        FROM single_prop sp
        WHERE pn.account_id = sp.account_id AND pn.property_id IS NULL
        """,
        """
        WITH single_prop AS (
            SELECT p.account_id, p.id AS property_id
            FROM properties p
            WHERE p.is_default = TRUE
              AND (SELECT COUNT(*) FROM properties p2 WHERE p2.account_id = p.account_id) = 1
        )
        UPDATE assistants asst
        SET property_id = sp.property_id
        FROM single_prop sp
        WHERE asst.account_id = sp.account_id AND asst.property_id IS NULL
        """,
        """
        WITH single_prop AS (
            SELECT p.account_id, p.id AS property_id
            FROM properties p
            WHERE p.is_default = TRUE
              AND (SELECT COUNT(*) FROM properties p2 WHERE p2.account_id = p.account_id) = 1
        )
        UPDATE account_integrations ai
        SET property_id = sp.property_id
        FROM single_prop sp
        WHERE ai.account_id = sp.account_id AND ai.property_id IS NULL
        """,
    ]
    with engine.connect() as conn:
        for sql in statements:
            try:
                result = conn.execute(text(sql))
                conn.commit()
                if result.rowcount and result.rowcount > 0:
                    logger.info(
                        f"Default-property backfill: {result.rowcount} row(s) affected"
                    )
            except Exception as e:
                logger.warning(
                    f"Default-property backfill skipped (non-fatal): {sql[:60]}... — {e}"
                )
                try:
                    conn.rollback()
                except Exception:
                    pass


def _assert_call_events_offset_ms_bigint() -> None:
    """Task #123 — fail loudly if ``call_events.offset_ms`` is not BIGINT.

    The fresh CREATE TABLE now declares BIGINT and the Task #115 ALTER widens
    legacy deployments. Both are idempotent SQL; both can fail silently inside
    the additive-migrations runner if a lock or permission issue strikes.
    A silent int4 schema means writes for calls older than ~24.85 days will
    raise NumericValueOutOfRange — which on the sweeper path silently rolls
    back the entire finalization transaction every 5 min forever.

    Verifying the column type at startup converts that latent failure mode
    into a loud one. Refuses to start the app on mismatch — a degraded mode
    is worse than a crash here, since the sweeper is the only thing that
    rescues stuck calls and it would be silently broken.
    """
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name='call_events' AND column_name='offset_ms'"
                )
            ).first()
    except Exception as e:
        # Don't mask DB-connectivity errors here; init_db will surface them.
        logger.error(f"call_events.offset_ms invariant check failed to query schema: {e}")
        raise

    if row is None:
        # Table missing entirely — create_all + additive migrations should
        # have created it earlier in init_db; reaching here is a bug.
        msg = (
            "call_events.offset_ms invariant: column not found "
            "(call_events table missing after migrations)"
        )
        logger.error(msg)
        raise RuntimeError(msg)

    data_type = row[0]
    if data_type != "bigint":
        msg = (
            f"call_events.offset_ms invariant FAILED: data_type='{data_type}', "
            f"expected 'bigint'. Writes for calls older than ~24.85 days will "
            f"overflow int4 and silently roll back finalization. Refusing to "
            f"start. Run: ALTER TABLE call_events ALTER COLUMN offset_ms TYPE BIGINT"
        )
        logger.error(msg)
        raise RuntimeError(msg)

    logger.debug("call_events.offset_ms invariant ✓ (bigint)")


def init_db():
    """Initialize the database at application startup.

    Runs idempotent startup steps in order:

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

    5. ``_backfill_silero_vad_config`` — ensures all Silero assistants with a
       null or empty vad_config get the canonical VAD parameter defaults so
       the voice engine never falls back to misconfigured hardcoded values.

    6. ``_backfill_smart_turn_stop_secs_default`` — updates legacy Silero assistants that still store ``smart_turn_stop_secs=1.0`` from historical defaults to ``0.5`` while preserving explicit custom values.
    7. ``_backfill_billing_tool_data`` — one-time idempotent fix: sets account_id and tightens the LLM trigger description on any FLOW tool named ``billing`` that was created without an account_id.
    8. ``run_stuck_call_sweeper`` — unified safety-net that reclassifies any
       CallLog rows left in a non-terminal status (initiated / ringing /
       in_progress) with no active pipeline. Emits a ``finalization_forced``
       CallEvent per closed row for leak-rate observability. Supersedes the
       old one-shot ``_backfill_stuck_initiated_calls`` which is kept only
       for backward compatibility in external scripts.
    """
    from botelier.models import (
        account,  # noqa: F401
        assistant,  # noqa: F401
        call_event,  # noqa: F401
        call_log,  # noqa: F401
        flow_session,  # noqa: F401
        flow_version,  # noqa: F401
        integration,  # noqa: F401
        integration_resilience,  # noqa: F401
        invitation,  # noqa: F401
        knowledge_entry,  # noqa: F401
        mcp_connection,  # noqa: F401
        operation_idempotency,  # noqa: F401
        payment,  # noqa: F401
        payment_page_template,  # noqa: F401
        phone_number,  # noqa: F401
        property,  # noqa: F401
        record,  # noqa: F401
        record_type,  # noqa: F401
        resolution_option,  # noqa: F401
        role,  # noqa: F401
        tool,  # noqa: F401
        user,  # noqa: F401
    )

    Base.metadata.create_all(bind=engine)
    _run_hotel_account_migration()
    _run_additive_migrations()
    _convert_combined_voice_rates()
    # Task #123 — verify the schema invariant the additive migrations are
    # supposed to guarantee, AFTER they have had a chance to run. Failing
    # here is intentional: a silent int4 schema breaks the sweeper forever.
    _assert_call_events_offset_ms_bigint()
    _sync_system_role_permissions()
    _backfill_silero_vad_config()
    _backfill_smart_turn_stop_secs_default()
    _backfill_billing_tool_data()
    # Fix old GC availability flow_versions that have incorrect responseInstructions
    # referencing nonexistent room_type_name/rate_plan_name fields.
    _backfill_gc_availability_instructions()
    # Task #327 — one default property per resource-owning account + stamp
    # existing resources so current single-property behavior is preserved.
    _backfill_default_properties()
    # Task #96: the unified stuck-call sweeper supersedes the legacy
    # _backfill_stuck_initiated_calls. It covers initiated, ringing and
    # in_progress (not just initiated) AND emits finalization_forced
    # CallEvents so the Task #97 leak-rate dashboard observes every
    # startup-driven reclassification. Pipeline state is empty at this
    # point, so skip_call_sids=None is safe.
    run_stuck_call_sweeper(skip_call_sids=None)
