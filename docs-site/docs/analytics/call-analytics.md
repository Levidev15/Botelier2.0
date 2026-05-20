---
id: call-analytics
title: Call Analytics
sidebar_label: Call Analytics
---

# Call Analytics Dashboard

The **Call Analytics** dashboard provides an aggregated view of your call volume, AI performance, resolution rates, and costs over any time period.

## Accessing the Dashboard

Navigate to **Analytics** → **Calls** in the left sidebar.

## Filters

| Filter | Options |
|---|---|
| **Date Range** | Last 7 days, Last 30 days, Month-to-date, Custom range |
| **Assistant** | All assistants or a specific one |
| **Channel** | All, Voice, SMS |

## Key Metrics

| Metric | Description |
|---|---|
| **Total Calls** | Number of inbound calls in the period |
| **Avg Duration** | Average call duration in seconds |
| **AI Handled** | Calls where the AI fully resolved the caller's need |
| **Unresolved** | Calls where the issue was not resolved |
| **Transfer Rate** | Percentage of calls transferred to a human agent |
| **Resolution Rate** | AI Handled ÷ Total Calls (excluding silent calls) |
| **Avg QA Score** | Average ACW quality score across scored calls |
| **Total Cost** | Sum of Botelier call costs for the period |

## `ai_handled` and `unresolved` Classifications

The analytics system classifies each completed call:

**`ai_handled = TRUE`** when:
- The call disposition maps to a "resolved" resolution option, AND
- `caller_spoke` is `TRUE` or `NULL` (caller produced speech)

**`ai_handled = FALSE` (Unresolved)** when:
- The disposition maps to "unresolved" or "transferred"
- OR `caller_spoke = FALSE` (no caller audio detected — silent call, dropped call, spam bot)

Silent calls (`caller_spoke = FALSE`) are excluded from the denominator of the AI Handled Rate so that spam or dropped calls don't distort the metric. They appear in the call log and count toward total call volume.

## Timeseries Chart

The chart shows daily or weekly call volume and cost trends. Toggle **Daily / Weekly** using the bucket selector.

## Disposition Breakdown

Below the timeseries, a bar or pie chart shows the distribution of call dispositions for the period. This reveals the most common call reasons handled by the AI.

## CSV Export

Click **Export CSV** to download the full call log for the selected period. This requires the `usage.export` permission.

The CSV includes: reference ID, timestamp, direction, caller number, assistant, duration, disposition, resolution, AI handled flag, QA score, and cost.

## Filtering by Assistant

When you select a specific assistant, all metrics recalculate for calls handled by that assistant only. This is useful for comparing performance across different AI configurations.
