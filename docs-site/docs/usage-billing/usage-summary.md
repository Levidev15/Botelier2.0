---
id: usage-summary
title: Usage Summary
sidebar_label: Usage Summary
---

# Usage Summary

The **Usage** page provides a real-time view of your account's call and SMS costs for the current period, including a paginated per-call cost list and a cost timeseries chart.

## Required Permissions

| Action | Permission Required |
|---|---|
| View usage summary and timeseries | `usage.view` |
| View per-call cost list | `usage.view` |
| Export call list as CSV | `usage.export` |
| View billing rate config | `usage.view` |

These permissions are granted to the **Admin** role by default and can be extended to **Staff** by your account admin.

## Accessing the Usage Page

Navigate to **Billing** → **Usage** in the left sidebar.

## MTD Call Cost

The top summary card shows **month-to-date** totals:

| Metric | Description |
|---|---|
| **Inbound Calls** | Number of inbound calls billed this month |
| **Inbound Minutes** | Total billable minutes (rounded up per call) |
| **Inbound Cost** | Inbound minutes × your inbound rate |
| **Outbound Transfers** | Number of transfer legs billed |
| **Outbound Minutes** | Total transfer leg minutes |
| **Outbound Cost** | Outbound minutes × your outbound rate |
| **SMS (In/Out)** | Count of inbound and outbound messages |
| **SMS Cost** | Message counts × your SMS rates |
| **Total Cost** | Sum of all line items |

## Period Selector

Change the period using the selector in the top-right:

| Period | Description |
|---|---|
| `7d` | Rolling 7 days |
| `30d` | Rolling 30 days (default) |
| `mtd` | Month-to-date (1st of month to now) |
| `custom` | Custom date range — requires both start and end dates |

## Per-Call Cost List

Below the summary, a paginated table shows individual calls with:

| Column | Description |
|---|---|
| **Time** | Call start timestamp |
| **Reference ID** | Twilio Call SID |
| **Direction** | Inbound / Outbound |
| **Caller** | Customer's phone number |
| **Assistant** | Handling assistant name |
| **Duration** | Total call seconds |
| **Billable Minutes** | Rounded-up inbound minutes |
| **Inbound Cost** | Billable minutes × inbound rate |
| **Transfers** | Whether the call had a transfer leg |
| **Total Cost** | All billing items for this call |

Click any row to expand the billing item breakdown (inbound call + each transfer leg separately).

## How Costs Are Calculated

```
Inbound Cost = ceil(duration_seconds / 60) × inbound_rate_per_minute
Transfer Cost = ceil(transfer_duration_seconds / 60) × outbound_rate_per_minute
SMS Cost = inbound_messages × sms_inbound_rate + outbound_messages × sms_outbound_rate
Total = Inbound Cost + Transfer Cost + SMS Cost
```

Rates are set in the billing configuration by your platform administrator. View your current rates on the **Billing** → **Rates** page.

## Cost Timeseries Chart

The timeseries chart shows daily or weekly cost broken down by:
- **Inbound** (blue)
- **Outbound transfers** (orange)
- **SMS** (green)

Toggle **Daily / Weekly** using the bucket selector. Weekly view is useful for spotting long-term trends without daily noise.

## CSV Export

Click **Export CSV** to download the full filtered call list as a CSV file. The export contains all calls in the selected period without pagination.

**Required permission:** `usage.export`
