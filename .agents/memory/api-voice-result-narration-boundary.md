---
name: API voice_result narration boundary
description: An API-node result field meant only as LLM context got spoken to callers verbatim because nothing distinguished it from genuine designer narration.
---

# API voice_result narration boundary

`FlowExecutor` (`botelier/backend/botelier/flow_executor.py`) builds a single
`voice_result` string for every completed API_REQUEST node, from one of two
very different sources:

1. **Designer-authored `responseInstructions`** — genuine natural-language
   text (with `{{variable}}` substitutions) meant to be spoken to the caller
   verbatim.
2. **`_build_api_voice_result` fallback** — used only when
   `responseInstructions` is blank; a compact `"<success_msg>. Extracted
   data — field: value; field2: value2"` digest of the raw extracted
   variables, built so the LLM still has the numbers/names to narrate
   naturally. This is internal data shape, not prose (e.g.
   `room_price: 8000, 7500; rooms_name: Double, Family`).

`FunctionMapper` (`botelier/voice/function_mapper.py`) used to treat any
non-empty `voice_result` identically: push it straight to `TTSSpeakFrame`
and suppress the follow-up LLM turn (`run_llm=False`). Because both sources
shared one field with no marker, the raw fallback digest got read aloud to a
live caller verbatim ("Extracted data — room_price: 8000, 7500...").

**Fix pattern:** the *source* of a string, not just its presence, must gate
whether it can reach TTS directly. `voice_result` is now paired with a
sibling boolean (`voice_result_is_auto_summary`) set by whichever branch
built it; `FunctionMapper` only speaks `voice_result` directly when that flag
is False. When True, it falls back to the ordinary silence-safety completion
bridge (`api.onComplete` / default "I've completed that check…") and lets a
real LLM turn narrate the data — the digest still reaches the LLM via
`result["result"]`, it just never hits TTS unfiltered. The flag itself is
stripped before promotion to `result["result"]` so it never leaks into LLM
context as noise.

**Why:** any field whose only purpose is "context for the LLM to speak
about" must never be assumed safe to pipe straight to TTS just because a
*different* code path also stores genuine spoken text under the same key.
One shared field name for two different trust levels is the recurring
failure shape here.

**How to apply:** when adding a new "spoken immediately" branch on some
result field, check every producer of that field — if any producer can also
emit raw/structured/internal data (JSON-ish digests, id lists, raw field
dumps) under the same key, split the trust signal into its own boolean
rather than trusting non-emptiness alone.
