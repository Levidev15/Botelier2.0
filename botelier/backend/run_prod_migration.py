"""
One-time hotel_id → account_id migration script.

IMPORTANT — verify the target database before running:
  - This script reads DATABASE_URL from the environment (preferred).
  - Falls back to NEON_DATABASE_URL if DATABASE_URL is not set.
  - NEON_DATABASE_URL may point to a staging/dev branch that does NOT have
    the SMS tables. If that is the case, run against the correct production
    branch using DATABASE_URL instead.

Pre-flight check: before running, confirm the target DB has these tables:
  sms_conversations, sms_notification_settings, sms_templates

Run with: DATABASE_URL=<prod-url> python run_prod_migration.py
"""
import os
import sys
import psycopg2

db_url = os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")
if not db_url:
    print("ERROR: Neither DATABASE_URL nor NEON_DATABASE_URL is set")
    sys.exit(1)

conn_check = psycopg2.connect(db_url)
cur_check = conn_check.cursor()
cur_check.execute("SELECT current_database(), current_user")
dbname, dbuser = cur_check.fetchone()
cur_check.execute("""
    SELECT count(*) FROM information_schema.tables
    WHERE table_schema='public' AND table_name IN
    ('sms_conversations','sms_notification_settings','sms_templates')
""")
sms_count = cur_check.fetchone()[0]
cur_check.close()
conn_check.close()

print(f"Target database: {dbname} (user: {dbuser})")
if sms_count < 3:
    print(f"WARNING: Only {sms_count}/3 SMS tables found. This may be a dev/staging branch.")
    print("Set DATABASE_URL to the production branch URL and retry.")
    print("Continuing anyway — missing tables will be skipped safely.")

print(f"Connecting to production database...")

conn = psycopg2.connect(db_url)
conn.autocommit = False
cur = conn.cursor()

steps = [
    # ── Step 1: Drop legacy FK constraints pointing at hotels ──────────────────
    ("Drop FK assistants_hotel_id_fkey",
     "ALTER TABLE assistants DROP CONSTRAINT IF EXISTS assistants_hotel_id_fkey"),
    ("Drop FK call_logs_hotel_id_fkey",
     "ALTER TABLE call_logs DROP CONSTRAINT IF EXISTS call_logs_hotel_id_fkey"),
    ("Drop FK knowledge_entries_hotel_id_fkey",
     "ALTER TABLE knowledge_entries DROP CONSTRAINT IF EXISTS knowledge_entries_hotel_id_fkey"),
    ("Drop FK phone_numbers_hotel_id_fkey",
     "ALTER TABLE phone_numbers DROP CONSTRAINT IF EXISTS phone_numbers_hotel_id_fkey"),
    ("Drop FK sms_compliance_campaigns_hotel_id_fkey",
     "ALTER TABLE sms_compliance_campaigns DROP CONSTRAINT IF EXISTS sms_compliance_campaigns_hotel_id_fkey"),
    ("Drop FK sms_conversations_hotel_id_fkey",
     "ALTER TABLE sms_conversations DROP CONSTRAINT IF EXISTS sms_conversations_hotel_id_fkey"),
    ("Drop FK sms_notification_settings_hotel_id_fkey",
     "ALTER TABLE sms_notification_settings DROP CONSTRAINT IF EXISTS sms_notification_settings_hotel_id_fkey"),
    ("Drop FK sms_templates_hotel_id_fkey",
     "ALTER TABLE sms_templates DROP CONSTRAINT IF EXISTS sms_templates_hotel_id_fkey"),

    # ── Step 2: Rename hotel_id → account_id (3-state idempotent DO blocks) ───
    ("Rename assistants.hotel_id → account_id", """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='assistants' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='assistants' AND column_name='account_id') THEN
      UPDATE assistants SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE assistants DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE assistants RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$"""),
    ("Rename call_logs.hotel_id → account_id", """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='call_logs' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='call_logs' AND column_name='account_id') THEN
      UPDATE call_logs SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE call_logs DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE call_logs RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$"""),
    ("Rename knowledge_entries.hotel_id → account_id", """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='knowledge_entries' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='knowledge_entries' AND column_name='account_id') THEN
      UPDATE knowledge_entries SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE knowledge_entries DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE knowledge_entries RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$"""),
    ("Rename phone_numbers.hotel_id → account_id", """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='phone_numbers' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='phone_numbers' AND column_name='account_id') THEN
      UPDATE phone_numbers SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE phone_numbers DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE phone_numbers RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$"""),
    ("Rename sms_compliance_campaigns.hotel_id → account_id", """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sms_compliance_campaigns' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sms_compliance_campaigns' AND column_name='account_id') THEN
      UPDATE sms_compliance_campaigns SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE sms_compliance_campaigns DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE sms_compliance_campaigns RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$"""),
    ("Rename sms_conversations.hotel_id → account_id", """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sms_conversations' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sms_conversations' AND column_name='account_id') THEN
      UPDATE sms_conversations SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE sms_conversations DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE sms_conversations RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$"""),
    ("Rename sms_notification_settings.hotel_id → account_id", """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sms_notification_settings' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sms_notification_settings' AND column_name='account_id') THEN
      UPDATE sms_notification_settings SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE sms_notification_settings DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE sms_notification_settings RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$"""),
    ("Rename sms_templates.hotel_id → account_id", """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sms_templates' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sms_templates' AND column_name='account_id') THEN
      UPDATE sms_templates SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE sms_templates DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE sms_templates RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$"""),
    ("Rename tools.hotel_id → account_id", """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tools' AND column_name='hotel_id') THEN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tools' AND column_name='account_id') THEN
      UPDATE tools SET account_id = hotel_id WHERE account_id IS NULL;
      ALTER TABLE tools DROP COLUMN hotel_id;
    ELSE
      ALTER TABLE tools RENAME COLUMN hotel_id TO account_id;
    END IF;
  END IF;
END $$"""),

    # ── Step 3: Add new FK constraints pointing at accounts ────────────────────
    ("Add FK assistants_account_id_fkey",
     "DO $$ BEGIN ALTER TABLE assistants ADD CONSTRAINT assistants_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$"),
    ("Add FK call_logs_account_id_fkey",
     "DO $$ BEGIN ALTER TABLE call_logs ADD CONSTRAINT call_logs_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$"),
    ("Add FK knowledge_entries_account_id_fkey",
     "DO $$ BEGIN ALTER TABLE knowledge_entries ADD CONSTRAINT knowledge_entries_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; END $$"),
    ("Add FK phone_numbers_account_id_fkey",
     "DO $$ BEGIN ALTER TABLE phone_numbers ADD CONSTRAINT phone_numbers_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$"),
    ("Add FK sms_compliance_campaigns_account_id_fkey",
     "DO $$ BEGIN ALTER TABLE sms_compliance_campaigns ADD CONSTRAINT sms_compliance_campaigns_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$"),
    ("Add FK sms_conversations_account_id_fkey",
     "DO $$ BEGIN ALTER TABLE sms_conversations ADD CONSTRAINT sms_conversations_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$"),
    ("Add FK sms_notification_settings_account_id_fkey",
     "DO $$ BEGIN ALTER TABLE sms_notification_settings ADD CONSTRAINT sms_notification_settings_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$"),
    ("Add FK sms_templates_account_id_fkey",
     "DO $$ BEGIN ALTER TABLE sms_templates ADD CONSTRAINT sms_templates_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$"),

    # ── Step 4: Recreate indexes under new names ───────────────────────────────
    ("Drop old index ix_call_logs_hotel_started",
     "DROP INDEX IF EXISTS ix_call_logs_hotel_started"),
    ("Create ix_call_logs_account_started",
     "CREATE INDEX IF NOT EXISTS ix_call_logs_account_started ON call_logs(account_id, started_at)"),
    ("Drop old index ix_call_logs_hotel_status",
     "DROP INDEX IF EXISTS ix_call_logs_hotel_status"),
    ("Create ix_call_logs_account_status",
     "CREATE INDEX IF NOT EXISTS ix_call_logs_account_status ON call_logs(account_id, status)"),
    ("Drop old index ix_sms_conv_hotel_status",
     "DROP INDEX IF EXISTS ix_sms_conv_hotel_status"),
    ("Create ix_sms_conv_account_status",
     "CREATE INDEX IF NOT EXISTS ix_sms_conv_account_status ON sms_conversations(account_id, status)"),
    ("Drop old index ix_sms_conv_hotel_last_msg",
     "DROP INDEX IF EXISTS ix_sms_conv_hotel_last_msg"),
    ("Create ix_sms_conv_account_last_msg",
     "CREATE INDEX IF NOT EXISTS ix_sms_conv_account_last_msg ON sms_conversations(account_id, last_message_at)"),
    ("Drop old index ix_sms_conv_customer_number",
     "DROP INDEX IF EXISTS ix_sms_conv_customer_number"),
    ("Create ix_sms_conv_account_customer_number",
     "CREATE INDEX IF NOT EXISTS ix_sms_conv_account_customer_number ON sms_conversations(account_id, customer_number, botelier_number)"),
    ("Drop old index ix_sms_template_hotel",
     "DROP INDEX IF EXISTS ix_sms_template_hotel"),
    ("Create ix_sms_template_account",
     "CREATE INDEX IF NOT EXISTS ix_sms_template_account ON sms_templates(account_id)"),

    # ── Step 5: Drop the legacy hotels table ───────────────────────────────────
    ("Drop legacy hotels table",
     "DROP TABLE IF EXISTS hotels"),
]

try:
    for label, sql in steps:
        print(f"  → {label}...", end=" ", flush=True)
        cur.execute(sql.strip())
        print("OK")
    conn.commit()
    print("\n✅ All migration steps committed successfully.")
except Exception as e:
    conn.rollback()
    print(f"\n❌ FAILED: {e}")
    print("Transaction rolled back — no changes were made.")
    sys.exit(1)
finally:
    cur.close()
    conn.close()

# ── Step 6: Verify ─────────────────────────────────────────────────────────────
print("\nVerifying...")
conn2 = psycopg2.connect(db_url)
cur2 = conn2.cursor()

cur2.execute("""
    SELECT table_name, column_name
    FROM information_schema.columns
    WHERE column_name = 'hotel_id' AND table_schema = 'public'
    ORDER BY table_name
""")
remaining = cur2.fetchall()
if remaining:
    print(f"⚠️  hotel_id columns still present: {remaining}")
else:
    print("✅ No hotel_id columns remain.")

cur2.execute("SELECT table_name FROM information_schema.tables WHERE table_name = 'hotels' AND table_schema = 'public'")
hotels_exists = cur2.fetchone()
if hotels_exists:
    print("⚠️  hotels table still exists!")
else:
    print("✅ hotels table is gone.")

cur2.close()
conn2.close()
print("\nDone.")
