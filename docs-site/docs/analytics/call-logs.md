---
id: call-logs
title: Call Logs
sidebar_label: Call Logs
---

# Call Logs

The **Call Logs** table is the complete, paginated record of every call handled by the platform. Each row links to a full call detail view with transcript, events, ACW, and billing data.

## Accessing Call Logs

Navigate to **Analytics** → **Call Logs** in the left sidebar.

## Table Columns

| Column | Description |
|---|---|
| **Time** | Call start timestamp (local timezone) |
| **Reference ID** | Twilio Call SID — useful for cross-referencing in the Twilio console |
| **Direction** | Inbound or Outbound |
| **Caller** | Caller's phone number |
| **To** | Phone number dialed |
| **Assistant** | Assistant that handled the call |
| **Duration** | Total call duration in seconds |
| **Disposition** | ACW-assigned disposition label |
| **AI Handled** | ✅ or ❌ |
| **QA Score** | 0–100 if ACW ran; blank if not |
| **Cost** | Total Botelier cost for this call |

## Sorting the Table

Click any column header to sort ascending or descending. Sortable columns: **Time**, **Duration**, **Cost**.

## Filtering

Use the filter bar to narrow results by:
- **Date range** — preset or custom
- **Assistant**
- **Direction** (inbound/outbound)
- **AI Handled** (yes/no)
- **Caller number** — partial match search
- **Disposition**

## Drilling into a Single Call

Click any row to open the call detail view.

### Transcript Tab

The full conversation transcript with:
- Speaker labels (AI, Caller)
- Message timestamps
- Turn-level latency data (time from caller stop to AI response)

### Event Timeline Tab

Low-level event log:
- `call_initiated` — Twilio webhook received
- `call_connected` — WebSocket connected
- `stt_started` / `stt_result` — speech recognition events
- `llm_response` — model response received
- `tts_started` / `tts_complete` — audio delivery
- `tool_call` — tool invocations with parameters and results
- `transfer_initiated` / `transfer_complete`
- `call_completed` — call ended
- `acw_complete` — QA results ready

### ACW Summary Tab

If ACW ran:
- **QA Score** with criterion-level breakdown
- **Summary** — prose description of the call
- **Disposition** selected by the AI
- **Resolution** status

### Cost Breakdown Tab

| Line Item | Description |
|---|---|
| **Inbound Call** | Minutes × inbound rate |
| **Outbound Transfer** | Transfer duration × outbound rate (if transferred) |
| **Rate Version** | The rate configuration version used when this call was billed |
| **Twilio Cost** | Carrier cost (admin view only) |
| **Total** | Sum of all line items |

The **Rate Version** field shows which billing rate configuration was active at the time of billing — useful for auditing historical calls after a rate change.

## CSV Export

Click **Export CSV** in the filter bar to download the filtered result set. Requires the `usage.export` permission.

Fields in the export: all table columns plus full transcript text (if enabled in export settings).
