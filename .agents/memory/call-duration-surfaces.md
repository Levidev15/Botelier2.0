---
name: Call Duration display surfaces
description: How "Duration" is computed/displayed for calls (especially transfers) and the cross-surface lockstep rule.
---

# Call Duration surfaces

The user-facing "Duration" for a call is the **AI-conversation leg** duration (the caller's time with the AI), NOT `CallLog.duration_seconds`. `CallLog.duration_seconds` is the Twilio-authoritative parent total and is owned exclusively by billing — never repurpose it for display.

## The recovery rule
On transferred / early-terminated calls a terminal Twilio webhook can stamp the AI leg's `ended_at` before the pipeline reports its pipecat duration, leaving the leg at duration 0 / `duration_source != "pipecat"`. `_ensure_ai_leg_duration()` (call_logger.py) recovers it from `ai_leg.ended_at|call_log.ended_at - answered_at`. `record_transfer()` stamps the AI leg `ended_at` BEFORE the transfer leg starts, so this span excludes bridged transfer time. The helper is idempotent (skips a real `pipecat` source), requires `answered_at`, and never touches billing.

## Lockstep filter rule
**Why:** the Duration surfaces diverge silently otherwise — transferred or legacy calls show different numbers on different screens.

Every Duration surface must apply the SAME `duration_source` filters:
- AI duration = sum of `ai_conversation` legs WHERE `duration_source == "pipecat"`
- Transfer duration = sum of transfer legs (external/sip/internal/cold) WHERE `duration_source in ("twilio_webhook", "twilio_api")`

Surfaces that must stay in sync (all aggregate from `CallLeg`, never from `CallLog.duration_seconds`): the call-log row + its `to_dict`, analytics overview, analytics drilldown, the call-stats summary card, CSV export, and the call-log/transcript/drilldown modals in the frontend. Backend leg aggregates expose both legacy keys (`total/avg_duration_seconds`) and explicit AI keys; the legacy keys must equal the AI keys. For `has_transfer` calls with no recoverable AI leg, every surface (backend fallback AND frontend display) must show `0`, NOT the parent `duration_seconds` — falling back to the parent re-introduces the AI+transfer double-count.

**How to apply:** any change to one Duration surface (a new transfer leg type, a new source value, fallback logic) must be mirrored across all of the above in the same change.
