# `components/analytics/` — Analytics dashboard widgets

## Purpose

Building blocks for the analytics page: stat cards, the call drilldown modal, filters, and a customizable widget layout.

## Main files

| File | Role |
|---|---|
| `StatCard.tsx` | KPI card primitive. |
| `DashboardWidget.tsx` | Wrapper that gives any widget a title, loading / error state, and layout slot. |
| `useWidgetLayout.ts` | Hook that persists the user's customized widget layout (which widgets, what order). |
| `CustomizePanel.tsx` | UI for adding / removing / reordering widgets. |
| `CallDrilldownModal.tsx` | Per-call detail modal: timeline, transcript, events. |
| `AssistantFilter.tsx`, `DateRangePicker.tsx`, `TimeRangePicker.tsx`, `TimezonePicker.tsx` | Shared filter controls. |

## How it connects

- Consumed by `app/(dashboard)/dashboard/analytics/` and `app/(standalone)/dashboard/analytics/`.
- Backed by `api/analytics.py` and `api/call_logs.py`.
- Drilldown reads `call_logs`, `call_legs`, `call_events`; transcript display assumes the format produced by `services/call_logger.complete_call`.

## Conventions

- New widgets implement `DashboardWidget` and are registered with `useWidgetLayout` so they appear in `CustomizePanel`.
- Filters are colocated with the analytics page and passed down — no global filter state.

## Setup

No standalone setup.

## Gotchas

- Drilldown timestamps in the transcript come from the capture layer, not the save layer (`services/call_logger.py` deliberately preserves caller-provided timestamps). If they look wrong, fix at the source — overwriting them in the modal would mask real bugs.
- The timeline depends on `CallEvent.offset_ms`. The column is `bigint` (Task #123 enforces this at startup via `database._assert_call_events_offset_ms_bigint`) and writers compute the true value via `services/_event_offset.compute_offset_ms`. No clamping — long-stuck calls display the real elapsed time.
