---
name: Speech-gated call teardown (end_call / transfer)
description: Any voice tool that speaks a message then terminates/redirects the call must defer termination to a post-speech callback + Twilio playback mark; safety watchdogs must be speech-aware.
---

**Rule:** A handler must never issue a Twilio REST hangup / transfer update / EndFrame in-line after pushing a `TTSSpeakFrame`. The terminal action must run as a post-speech callback (`TtsCompletionWatcher.schedule_after_speech`, `reset()` first when the handler initiates the speech), and inside that callback await a Twilio playback mark (`send_mark_and_wait`) before the REST call — the mark ack is the only proof the caller actually heard the buffered audio (Twilio acks a mark only after all prior outbound media played).

**Why:** The end_call goodbye and pre-transfer messages were audibly clipped in dev and production. Three distinct clipping mechanisms:
1. In-line REST hangup right after `TTSSpeakFrame` kills the PSTN leg in milliseconds.
2. An unconditional N-second watchdog on `schedule_after_speech` fires mid-sentence for any message longer than N seconds of audio. The watchdog must be speech-aware: track bot-speaking via `BotStartedSpeakingFrame`/`BotStoppedSpeakingFrame`, apply the short grace timeout only while the bot is silent (covers the real failure case — TTS context wiped, speech never starts), and keep a hard `max_wait` cap so a stuck pipeline never strands a caller.
3. A too-small playback-mark timeout (2 s) clips buffered tail audio — the mark is sent after `BotStoppedSpeakingFrame`, so the wait only covers Twilio's outbound jitter buffer; budget generously (10 s) since a received mark returns immediately.

**How to apply:** Any new voice tool that "says something then ends/redirects the call" must reuse the shared finalize pattern (post-speech callback → playback mark → REST action → EndFrame) rather than sequencing in-line. Watch the pre-existing accepted race: registering the callback while upstream speech is still playing can fire on the upstream `BotStoppedSpeakingFrame`; the playback-mark wait still drains buffered audio in that case. Teardown must clear both the pending callback and the watchdog task (`clear_callback`), and the guard detaches itself before awaiting the callback so teardown can't cancel an in-flight hangup/transfer.
