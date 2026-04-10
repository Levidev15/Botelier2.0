-- ============================================================
-- hotel_id → account_id production migration
-- ============================================================
--
-- PRE-FLIGHT CHECKLIST (complete before running):
--   1. Log into neon.tech and open the correct Neon project.
--   2. Verify you are on the MAIN (production) branch — NOT a dev/staging branch.
--      The production branch should have these SMS tables:
--        sms_conversations, sms_notification_settings, sms_templates,
--        sms_compliance_campaigns
--      If those tables are MISSING, you are on the wrong branch. Stop.
--   3. Run the verification query at the bottom first (in isolation) to
--      capture the before-state as deployment evidence.
--   4. Only then run the full script.
--
-- All statements are idempotent — safe to re-run if interrupted.
-- ============================================================

-- Step 1: Drop legacy FK constraints pointing at hotels table
ALTER TABLE assistants DROP CONSTRAINT IF EXISTS assistants_hotel_id_fkey;
ALTER TABLE call_logs DROP CONSTRAINT IF EXISTS call_logs_hotel_id_fkey;
ALTER TABLE knowledge_entries DROP CONSTRAINT IF EXISTS knowledge_entries_hotel_id_fkey;
ALTER TABLE phone_numbers DROP CONSTRAINT IF EXISTS phone_numbers_hotel_id_fkey;
ALTER TABLE sms_compliance_campaigns DROP CONSTRAINT IF EXISTS sms_compliance_campaigns_hotel_id_fkey;
ALTER TABLE sms_conversations DROP CONSTRAINT IF EXISTS sms_conversations_hotel_id_fkey;
ALTER TABLE sms_notification_settings DROP CONSTRAINT IF EXISTS sms_notification_settings_hotel_id_fkey;
ALTER TABLE sms_templates DROP CONSTRAINT IF EXISTS sms_templates_hotel_id_fkey;

-- Step 2: Rename hotel_id → account_id (3-state DO blocks — safe to re-run)
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
END $$;

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
END $$;

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
END $$;

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
END $$;

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
END $$;

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
END $$;

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
END $$;

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
END $$;

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
END $$;

-- Step 3: Add new FK constraints pointing at accounts (idempotent)
DO $$ BEGIN ALTER TABLE assistants ADD CONSTRAINT assistants_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE call_logs ADD CONSTRAINT call_logs_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE knowledge_entries ADD CONSTRAINT knowledge_entries_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE phone_numbers ADD CONSTRAINT phone_numbers_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE sms_compliance_campaigns ADD CONSTRAINT sms_compliance_campaigns_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE sms_conversations ADD CONSTRAINT sms_conversations_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE sms_notification_settings ADD CONSTRAINT sms_notification_settings_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE sms_templates ADD CONSTRAINT sms_templates_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Step 4: Recreate indexes under new names
DROP INDEX IF EXISTS ix_call_logs_hotel_started;
CREATE INDEX IF NOT EXISTS ix_call_logs_account_started ON call_logs(account_id, started_at);
DROP INDEX IF EXISTS ix_call_logs_hotel_status;
CREATE INDEX IF NOT EXISTS ix_call_logs_account_status ON call_logs(account_id, status);
DROP INDEX IF EXISTS ix_sms_conv_hotel_status;
CREATE INDEX IF NOT EXISTS ix_sms_conv_account_status ON sms_conversations(account_id, status);
DROP INDEX IF EXISTS ix_sms_conv_hotel_last_msg;
CREATE INDEX IF NOT EXISTS ix_sms_conv_account_last_msg ON sms_conversations(account_id, last_message_at);
DROP INDEX IF EXISTS ix_sms_conv_customer_number;
CREATE INDEX IF NOT EXISTS ix_sms_conv_account_customer_number ON sms_conversations(account_id, customer_number, botelier_number);
DROP INDEX IF EXISTS ix_sms_template_hotel;
CREATE INDEX IF NOT EXISTS ix_sms_template_account ON sms_templates(account_id);

-- Step 5: Drop legacy hotels table
DROP TABLE IF EXISTS hotels;

-- Verification
SELECT 'Remaining hotel_id columns: ' || count(*)
FROM information_schema.columns
WHERE column_name = 'hotel_id' AND table_schema = 'public';

SELECT 'Hotels table gone: ' || CASE WHEN count(*) = 0 THEN 'YES' ELSE 'NO' END
FROM information_schema.tables
WHERE table_name = 'hotels' AND table_schema = 'public';
