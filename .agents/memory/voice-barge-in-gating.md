---
name: Voice barge-in gating & interrupted transcripts
description: Pipecat interruption semantics — InterruptionFrame fires on every user turn; how the barge-in toggle, min-words gating, and interrupted-transcript marking must be built.
---

# Pipecat interruption semantics (v1.1)

- **`InterruptionFrame` is broadcast on EVERY user turn start**, not only during bot
  speech (`llm_response_universal.py` `_on_user_turn_started` → `broadcast_interruption()`).
  Any processor inferring "response was cut short" from InterruptionFrame MUST gate on
  bot-speaking state (`BotStartedSpeakingFrame`/`BotStoppedSpeakingFrame`), or every
  normally-completed response gets flagged as interrupted.
  **Why:** this exact bug shipped once and was caught only in architect review — the old
  code was "protected" by a broken matching key that never matched.
- **Disable barge-in via `AlwaysUserMuteStrategy`** (prepended to `user_mute_strategies`;
  works on Silero AND Flux paths — `_maybe_mute_frame` suppresses audio/VAD/transcriptions/
  InterruptionFrame during bot speech). NEVER express "not interruptible" as
  `enable_interruptions=False` on start strategies — that keeps transcribing caller speech
  during bot speech and queues a response (wrong semantics).
- **Background-noise false interruptions:** Pipecat default start strategies let raw VAD
  energy interrupt with zero transcribed words. `MinWordsUserTurnStartStrategy(min_words=N)`
  (interim transcriptions) requires N words to barge in while bot speaks, 1 word when
  silent. `caller_spoke` analytics is driven by TranscriptionFrame, NOT
  UserStartedSpeakingFrame — dropping the VAD start strategy doesn't break it.
- **Interrupted-transcript matching must be prefix-tolerant in both directions:**
  word-timestamp TTS (Cartesia) commits only the spoken prefix to context; Deepgram Aura
  has no word timestamps so the FULL generated text commits on interruption. Store the
  full generated response, compare overlapping prefixes (cap ~80 chars, require ≥12).
  Known limitation: two responses in one call sharing the same ≥12-char prefix can
  cross-match.
- **Mute-while-bot-speaking windows FLICKER between TTS segments:** one LLM response
  often produces multiple TTS utterance segments, and `BotStoppedSpeakingFrame` fires
  between them (double BotStopped inside one response window is the log signature). On
  the Flux path with interruptions OFF, each flicker lifts `AlwaysUserMuteStrategy`
  mid-response; any caller-side noise then fires Flux StartOfTurn →
  `broadcast_interruption()` (Flux STT keeps `should_interrupt=True`) → Twilio serializer
  sends `clear`, wiping the audio Twilio buffered ahead → the bot audibly cuts out
  (worst when spelling letter-by-letter, since those responses are pause-heavy).
  **Why:** relying on mute windows alone assumes bot-speaking state is continuous per
  response — it isn't. When interruptions are disabled, gate the interruption broadcast
  at the source, not just the audio feed.
- **How to apply:** anything touching `InterruptionTracker`, turn strategies, or
  `_extract_transcript` interrupted/recovery logic — run
  `tests/test_interrupted_transcript.py` (includes the "completed response + next user
  turn ≠ interrupted" regression test).
- Values coming out of `vad_config` (unvalidated JSONB) must be defensively coerced —
  a bad operator value must never crash call setup.
