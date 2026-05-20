---
id: quick-start
title: Quick Start
sidebar_label: Quick Start
---

# Quick Start — First Live Call in 5 Steps

This guide walks you from first login to your first AI-handled call.

**Prerequisites**
- A Botelier account (contact your platform administrator)
- A Twilio account with an active sub-account provisioned by your Botelier admin
- At least one Twilio phone number available

---

## Step 1 — Create a Knowledge Base

1. Navigate to **Knowledge Base** in the left sidebar.
2. Click **New Knowledge Base**, give it a name (e.g. "Company FAQ"), and save.
3. Add entries using **+ Add Entry**. Each entry is a question–answer pair.
   - *Question:* What are your hours?
   - *Answer:* We're open Monday through Friday, 9 AM to 6 PM Eastern.
4. Optionally, import entries from a CSV file or crawl your website using **Import → From URL**.

:::tip
Start with 10–20 high-confidence Q&A pairs. You can expand the knowledge base any time.
:::

---

## Step 2 — Create an Assistant

1. Navigate to **Assistants** → **New Assistant**.
2. Fill in the required fields:

| Field | Recommended value |
|---|---|
| **Name** | "Support Agent" |
| **System Prompt** | A description of the agent's role and behavior |
| **First Message** | The greeting spoken when a caller connects |
| **Language** | en |
| **STT Provider** | Deepgram |
| **LLM Provider** | OpenAI |
| **LLM Model** | gpt-4o-mini (balanced cost/quality) |
| **TTS Provider** | Cartesia or Deepgram |

3. Under **Knowledge Base**, select the KB you created in Step 1.
4. Click **Save**.

---

## Step 3 — Provision a Phone Number

1. Navigate to **Phone Numbers** → **Buy Number**.
2. Search by area code or toll-free prefix.
3. Select a number and click **Purchase**.
4. In the **Assign To** dropdown, select your new assistant.
5. Click **Save Assignment**.

---

## Step 4 — Wire the Twilio Webhook

Botelier automatically sets the Twilio webhook URL when you assign a number to an assistant. Verify this by checking:

1. Go to **Phone Numbers** and click your number.
2. Confirm **Voice URL** shows:
   ```
   https://<your-botelier-domain>/api/calls/inbound
   ```
3. Confirm **Status Callback** shows:
   ```
   https://<your-botelier-domain>/api/calls/status
   ```

If these URLs are missing, click **Re-sync Webhook** on the number detail page.

---

## Step 5 — Place a Test Call

1. Dial the phone number you provisioned from any phone.
2. You should hear the assistant's **First Message** within 1–2 seconds.
3. Ask a question that matches an entry in your knowledge base.
4. After the call ends, check **Call Logs** to see the transcript, duration, and cost.

:::note ACW / QA
If After-Call Work is enabled on the assistant, a QA summary and score will appear in the call log within a few seconds of the call ending.
:::

---

## What's Next?

- [Configure voice providers](../assistants/creating-an-assistant) — tune STT, LLM, and TTS settings
- [Build a Flow](../flows/flow-editor-overview) — create structured conversation logic
- [Set up SMS](../sms/sms-ai-config) — enable the same assistant on SMS
- [Enable ACW](../assistants/acw-and-qa) — add automated QA scoring
