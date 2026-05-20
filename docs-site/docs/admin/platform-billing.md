---
id: platform-billing
title: Platform Billing
sidebar_label: Platform Billing
---

# Platform Billing

The **Platform Billing** section gives platform administrators a cross-account view of usage, margin analysis, and the controls to configure billing rates for all accounts.

## Admin Usage Table

Navigate to **Admin** → **Billing** → **Accounts** to see the cross-account usage table.

See [Managing Accounts](./managing-accounts) for a description of all columns including the Twilio internal cost breakdown column.

### Twilio Internal Cost Breakdown

The admin accounts table includes internal cost columns not visible to account-level users:

| Column | Description |
|---|---|
| **Twilio Inbound Cost** | Estimated Twilio carrier cost for inbound minutes |
| **Twilio Outbound Cost** | Estimated Twilio carrier cost for transfer minutes |
| **LLM Cost** | Estimated LLM token cost (prompt + completion) |
| **TTS Cost** | Estimated text-to-speech character cost |
| **STT Cost** | Estimated speech-to-text second cost |
| **Internal Cost (Total)** | Sum of all above |
| **Margin** | Customer billable amount − Internal Cost |

These are **estimated** costs based on the platform's internal rate configuration, not actual Twilio invoice data.

## Per-Account Cost Detail

Click any account row → **Billing** tab for a full breakdown including per-call cost data and the billing summary card strip.

## Platform Rate Configuration

Platform rates are the internal cost-of-goods rates used to calculate margin. These are separate from the per-account billing rates charged to customers.

Navigate to **Admin** → **Billing** → **Platform Rates**.

### Current Rates

| Rate | Description |
|---|---|
| `llm_prompt_rate_per_1k` | Cost per 1,000 LLM prompt tokens |
| `llm_completion_rate_per_1k` | Cost per 1,000 LLM completion tokens |
| `tts_rate_per_1k_chars` | Cost per 1,000 TTS characters synthesized |
| `stt_rate_per_second` | Cost per second of STT audio transcribed |
| `twilio_inbound_per_min` | Twilio's per-minute rate for inbound calls |
| `twilio_outbound_per_min` | Twilio's per-minute rate for outbound calls |
| `twilio_sms_in_rate` | Twilio's per-message rate for inbound SMS |
| `twilio_sms_out_rate` | Twilio's per-message rate for outbound SMS |

### Rate History Table

The **Rate History** panel shows all historical platform rate configurations:

| Column | Description |
|---|---|
| **Effective From** | Date the rate version took effect |
| **Created By** | Admin who set the rates |
| **LLM Prompt** | Prompt token rate in effect |
| **TTS Rate** | TTS character rate |
| **… other rates** | All rate columns |

Rate versions are immutable — you cannot edit a past rate row. To change rates, create a new version.

### Creating a New Rate Version

1. Click **+ New Rate Version**.
2. Fill in all rate fields.
3. Set the **Effective From** date (can be backdated or future-dated).
4. Click **Save**.

The new version takes effect at the specified date. Historical calls are always billed at the rate version active on the date the call occurred.

### Which Rate Version Was Used

In the call detail view, the **Cost Breakdown** tab shows the **Rate Version** field — the identifier of the platform rate row used to calculate internal costs for that call. This allows auditing of historical cost calculations after a rate change.

## Customer Billing Rate Config

To set per-account billing rates (the rates charged to customers), go to:

**Admin** → **Accounts** → select an account → **Billing** tab.

The account-level billing rates determine what the customer sees on their **Usage** page.
