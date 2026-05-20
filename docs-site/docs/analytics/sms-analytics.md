---
id: sms-analytics
title: SMS Analytics
sidebar_label: SMS Analytics
---

# SMS Analytics Dashboard

The **SMS Analytics** dashboard shows message volume, conversation trends, and cost data for your SMS channel.

## Accessing the Dashboard

Navigate to **Analytics** → **SMS** in the left sidebar.

## Filters

| Filter | Options |
|---|---|
| **Date Range** | Last 7 days, Last 30 days, Month-to-date, Custom range |
| **Assistant** | All assistants or a specific one |

## Key Metrics

| Metric | Description |
|---|---|
| **Messages Received** | Total inbound SMS/MMS from customers |
| **Messages Sent** | Total outbound SMS from AI + agents |
| **New Conversations** | Conversations started in the period |
| **AI-Handled Conversations** | Conversations that never required a human takeover |
| **Human Takeovers** | Conversations where an agent took over |
| **Opt-Outs** | New STOP requests received |
| **SMS Cost** | Estimated cost for the period based on message rates |

## Message Volume Chart

The timeseries chart shows inbound vs. outbound message volume per day or week. Use this to identify traffic spikes, off-hours patterns, or the effect of marketing campaigns.

## Conversation Status Breakdown

A breakdown of conversations by final status:
- **Closed by AI** — resolved without human intervention
- **Closed by Agent** — human agent closed the conversation
- **Open** — still active at end of period
- **Opted Out** — customer sent a STOP keyword

## Cost Calculation

SMS costs are calculated as:
```
SMS Cost = (Inbound Messages × SMS Inbound Rate) + (Outbound Messages × SMS Outbound Rate)
```

Rates are set per account in the platform billing configuration. Default rates are defined in the platform settings by your Botelier administrator.

This cost reflects Botelier's platform fee, not the underlying Twilio carrier cost. Twilio's own per-message fees appear separately in your Twilio account.

## Filtering by Assistant

Selecting a specific assistant shows only conversations handled by that assistant's phone number(s). This is useful for comparing SMS performance across different bot configurations.
