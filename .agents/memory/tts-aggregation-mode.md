---
name: TTS text_aggregation_mode default and gap symptoms
description: Both Aura and Flux engines default to "token" mode; explicit "sentence" overrides cause audible gaps.
---

## The rule
`text_aggregation_mode` in an assistant's `tts_config` must be `"token"` (or
absent) for streaming TTS providers (Deepgram Aura, Deepgram Flux). The engine
defaults are already `"token"` for both providers, but a stored explicit
`"sentence"` value overrides that default.

## Why
"sentence" mode buffers the entire sentence before sending to TTS, producing
audible pauses mid-response. On the production call CA9d7f…c Deepgram reported
320 audio gaps (worst 190 ms) in turn 28 and 72 gaps (worst 1,650 ms) in turn 30.
The assistant's `tts_config` had `"text_aggregation_mode": "sentence"` stored
explicitly. Fixed by updating the row to `"token"` directly in the DB.

## How to apply
- `_CURRENCY_RE` uses `\b` word boundaries; "3000EUR" without a space does NOT
  trigger currency expansion (0 and E are both word chars in Python regex).
- When diagnosing TTS gaps: check `assistant.tts_config->>'text_aggregation_mode'`
  before assuming an engine bug.
- The fix for a single assistant is:
  `UPDATE assistants SET tts_config = jsonb_set(tts_config, '{text_aggregation_mode}', '"token"') WHERE id = <id>;`
- Task #197 ("Surface all Deepgram STT and TTS settings in the assistant UI") is
  the long-term fix so users don't accidentally set "sentence" via the UI.
