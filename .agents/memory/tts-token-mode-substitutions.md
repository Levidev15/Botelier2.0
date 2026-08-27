---
name: TTS token-mode text processing
description: Why per-word regex substitutions (and any whole-word text processing) silently fail in pipecat TOKEN aggregation mode, and how to fix it.
---

# Token-mode TTS breaks whole-word text processing

- In pipecat (v1.1) `text_aggregation_mode="token"`, `SimpleTextAggregator.aggregate()`
  yields **each raw LLM token immediately** — `run_tts` receives sub-word fragments
  ("wash" / "cloth" / "s"), so any `\bword\b` regex substitution applied per `run_tts`
  call never sees the whole word and silently no-ops. SENTENCE mode works because whole
  sentences arrive.
- Pipecat has only SENTENCE and TOKEN modes — there is NO word-boundary mode. Whole-word
  processing in token mode requires buffering in your own subclass: carry the trailing
  partial word until the next whitespace, flush at end-of-response, clear on interruption
  (or stale text leaks into the next response).
- **Why:** the "washcloth-es" mispronunciation bug — substitutions were correctly wired
  but only ever tested/working in sentence mode; token mode is the low-latency default.
- **How to apply:** any text transform in a TTS `run_tts` override (substitutions,
  redaction, SSML-ish rewriting) must be word-boundary-safe under token streaming, or be
  applied at a layer that sees complete text.

**Speech-normalization lesson:** any text transform for TTS must (a) run only on whitespace-complete text (token mode delivers sub-word fragments), (b) never raise — a failed transform kills synthesis mid-call, pass unsupported values through verbatim, and (c) leave identifier-like digit strings (confirmation numbers, 7+ digit sequences) as digits so callers can write them down. Every TTS provider path needs the transform wired separately — adding it to one wrapper silently leaves other providers unnormalized.
