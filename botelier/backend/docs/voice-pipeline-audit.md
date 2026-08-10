# Voice Pipeline Audit — Provider-Grade Baseline (Task #473)

Audit of the Pipecat-based voice pipeline (Twilio ⇄ Deepgram Flux STT ⇄ OpenAI LLM ⇄ Deepgram Aura TTS) against practices used by leading voice-AI providers (Vapi / Retell / Bland class). Date: 2026-08-10.

## Target latency budgets (per turn, measured on real calls)

These are the budgets each `turn_latency` CallEvent is judged against. Total
caller-perceived turn gap (end of caller speech → first bot audio) target:
**< 1000 ms p50, < 1500 ms p90** — the range competitive providers advertise.

| Stage | Metric (in `turn_latency` details) | Target p50 | Target p90 |
|---|---|---|---|
| Caller audio → STT final | `inbound_to_stt_ms` | < 300 ms | < 500 ms |
| STT final → LLM first token | `stt_to_llm_start_ms` | < 500 ms | < 900 ms |
| STT TTFB (non-Flux only¹) | `stt_ttfb_ms` | < 300 ms | < 500 ms |
| LLM TTFB (service-level) | `llm_ttfb_ms` | < 600 ms | < 1000 ms |
| LLM last token → TTS first audio | `llm_to_tts_first_audio_ms` | ≤ 0 ms (streaming overlap) | < 200 ms |
| TTS TTFB (service-level) | `tts_ttfb_ms` | < 250 ms | < 400 ms |
| Intra-turn audio gaps | `tts_audio_gap` event (worst gap) | none > 100 ms | none > 100 ms |
| Greeting (webhook → first audio) | `greeting_started.cold_path_latency_ms` | < 500 ms (pre-warm hit) | < 1500 ms (cold) |

¹ **Deepgram Flux does not emit TTFB metrics** (the pipecat fork disables
TTFB start/stop in `services/deepgram/flux/base.py`), so `stt_ttfb_ms` is
absent on the deployed Flux pipeline — `inbound_to_stt_ms` is the STT latency
measure there. The `stt_ttfb_ms` field populates only for the classic
Deepgram STT service.

Prompt-cache health: `cached_tokens / prompt_tokens` ≥ 80 % on turns after the
first (pre-warm fires during greeting; see `llm_prewarm_completed`).

## Per-stage audit vs. provider practice

### Transport (Twilio media WS)
- 8 kHz μ-law/linear16 both directions; `audio_out_10ms_chunks=2` (20 ms
  frames) — **tighter than pipecat's default 4**, favoring barge-in
  responsiveness over buffering. ✅ provider-grade.
- Playback confirmation via Twilio marks before terminal actions (transfer /
  hangup), with length-scaled degraded fallbacks. ✅ ahead of most providers.
- Greeting served from pre-rendered PCM cache, injected downstream of STT
  (never self-transcribed), paced at ~4× real-time. ✅

### STT (Deepgram Flux)
- Flux owns turn detection (eot/eager-eot thresholds configurable per
  assistant); external Silero VAD force-disabled for Flux. ✅
- Word-gated barge-in (`interrupt_min_words`) with eager-EOT resolution. ✅
- Reconnect: the pipecat fork intentionally sets `reconnect_on_error=False`
  for Flux; recovery happens lazily in `send_with_retry` on the continuous
  audio send path, so a dropped WS self-heals within one send. ✅ (accepted;
  autonomous receive-loop reconnect would double-spawn receive tasks).

### LLM (OpenAI, streaming)
- Token streaming into TTS (negative `llm_to_tts_first_audio_ms` expected). ✅
- Prompt-cache pre-warm during the greeting window; `prompt_cache_key`
  pinned; per-turn cache-hit telemetry. ✅ ahead of default provider setups.
- Tool exposure gated per flow node with paired refresh (avoids stale tool
  lists / 400s). ✅

### TTS (Deepgram Aura, websocket)
- TOKEN aggregation mode with word-boundary + clause batching (avoids
  sub-word fragmentation heard as stutter). ✅
- Sample rate clamped/pinned to 8 kHz on all providers. ✅
- Reconnect is lazy (on next send when WS is CLOSED) with a one-retry flush.
  ✅ acceptable; TTS TTFB telemetry (below) now measures any reconnect cost —
  if `tts_ttfb_ms` spikes after long silences, add a keepalive then.

### Observability (this task's additions)
- Per-turn `turn_latency` event: inbound→STT, STT→LLM, LLM generation,
  LLM→TTS first audio, per-service TTFB (`llm_ttfb_ms` / `tts_ttfb_ms`;
  `stt_ttfb_ms` only for non-Flux STT — see ¹), token/cache counters.
  Note: pipecat's websocket Deepgram TTS never stops TTFB itself (audio
  bypasses `tts_process_generator`); our TTS subclass stops it on the first
  received audio chunk per synthesis, so `tts_ttfb_ms` is real on deployed
  calls.
- Per-turn TTS audio-gap aggregation: worst gap + count logged per turn;
  caller-audible stutter (> 100 ms gap) emits a `tts_audio_gap` warning event.
- Pre-warm coverage: `llm_prewarm_completed/failed`, prewarm hit-state and
  wait-ms on every call.

## Ranked gap list (caller impact, high → low) and disposition

1. **No per-service TTFB on real calls** — could not tell whether a slow turn
   was LLM TTFB vs TTS reconnect vs pipeline queuing. **FIXED**: TTFB metrics
   surfaced into `turn_latency`.
2. **Audio-gap stutter invisible in production** (DEBUG-only logs). **FIXED**:
   per-turn aggregation + `tts_audio_gap` event at warning severity.
3. **TTS WS idle-reconnect cost unmeasured** — deferred until telemetry shows
   `tts_ttfb_ms` spikes correlated with long inter-turn silences; the fix
   (keepalive ping) is risky to add blind since Deepgram Speak WS has no
   documented keepalive message.
4. **Flux receive-loop reconnect** — accepted as-is (see STT section); the
   send path self-heals and the fork's design forbids autonomous reconnect.
5. **Pipeline heartbeats** (`enable_heartbeats`) — not enabled; the idle
   tracker + watchdogs already cover stall detection with call-specific
   handling. Revisit only if unexplained stalls appear with clean telemetry.

## Tuning knobs (where to turn what)

- `assistant.stt_config`: `eot_threshold`, `eager_eot_threshold`,
  `eot_timeout_ms`, `interrupt_min_words`, `keyterm`.
- `assistant.tts_config`: `text_aggregation_mode` (token|sentence),
  `token_send_min_chars`, `sample_rate` (clamped to 8000).
- Transport: `audio_out_10ms_chunks` (call_handler; 2 = 20 ms frames).
- Greeting injector pacing: `inject_yield_every_chunks` / `inject_pace_sleep_s`.
- Degraded-playback waits: `_PLAYBACK_CHARS_PER_SEC` / `_PLAYBACK_MAX_SECS`
  (function_mapper).
- Pre-warm: `PreWarmCache(max_size, ttl_secs)`; prewarm wait budget in
  `handle_call` (`pop_and_wait(timeout_secs=0.5)`).

Any change to these must be judged against the budgets above using
`turn_latency` / `tts_audio_gap` events on real calls (before/after).
