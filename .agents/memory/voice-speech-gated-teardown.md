---
name: Speech-gated call teardown (end_call / transfer)
description: Any voice tool that speaks a message then terminates/redirects the call must defer termination to a two-stage post-speech chain; safety watchdogs must be speech-aware.
---

**Rule:** A handler must never issue a Twilio REST hangup / transfer update / EndFrame in-line after pushing a `TTSSpeakFrame`. The terminal action must run as a post-speech callback through the **two-stage chain** described below, and inside that callback await a Twilio playback mark (`send_mark_and_wait`) before the REST call — the mark ack is proof Twilio has drained its outbound audio buffer.

**Two-stage chain (required):**
`_run_after_speech` uses context-ID binding + BotStopped together:
1. Context-ID (`on_audio_context_completed`) fires when TTS has pushed all audio frames into the pipeline — NOT when they've reached the transport. This stage provides "which utterance" identity and handles interruption discard (wrapper is discarded if context is interrupted).
2. The wrapper resets `TtsCompletionWatcher` and calls `schedule_after_speech(real_callback)`. The real callback fires when `BotStoppedSpeakingFrame` arrives upstream from `transport.output()` — i.e. after audio bytes are confirmed written to the Twilio WebSocket.

Using `on_audio_context_completed` alone as the terminal trigger (without chaining to BotStopped) is wrong: audio frames still have 4-5 pipeline hops to travel. A mark injected at that point races past the audio frames to the transport queue and arrives at Twilio before the audio.

**Why:** Four distinct clipping mechanisms have been fixed:
1. In-line REST hangup right after `TTSSpeakFrame` kills the PSTN leg in milliseconds.
2. An unconditional N-second watchdog on `schedule_after_speech` fires mid-sentence for any message longer than N seconds. The watchdog must be speech-aware: track bot-speaking via `BotStartedSpeakingFrame`/`BotStoppedSpeakingFrame`, apply the short grace timeout only while the bot is silent, keep a hard `max_wait` cap.
3. A too-small playback-mark timeout (2 s) clips buffered tail audio — budget 10 s since a received mark returns immediately.
4. Using `on_audio_context_completed` directly as the hangup trigger: fires at TTS layer before audio reaches `transport.output()`. Mark injected mid-pipeline races past in-flight audio frames and arrives at Twilio first. **Fix: two-stage chain above.**

**How to apply:** Any new voice tool that "says something then ends/redirects the call" must use `_run_after_speech` (which implements the two-stage chain automatically) rather than sequencing in-line. Inside the real callback: `_await_twilio_playback_mark` → REST hangup/transfer → `EndFrame`. Teardown must clear both the pending callback and the watchdog task (`clear_callback`), and the guard detaches itself before awaiting the callback so teardown can't cancel an in-flight hangup/transfer.
