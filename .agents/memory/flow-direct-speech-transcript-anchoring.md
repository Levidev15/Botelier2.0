---
name: Direct TTS speech needs real-timestamp anchoring for transcript ordering
description: Any assistant text spoken by pushing a TTS frame directly (bypassing a normal LLM completion) must get the same real-elapsed-time anchor genuine LLM turns get, or the saved transcript can invert question/answer order.
---

## The problem

When the context aggregator that commits assistant text to the LLM context
sits after TTS/transport output in the pipeline, it only reliably flushes
manually-pushed speech (pushed outside a normal LLM completion cycle) once
the *next* real LLM completion commits — while a caller's spoken reply gets
added to context immediately. So a manually-pushed line can end up committed
merged with, or positioned behind, content that lands after the caller's
next turn, even though it was actually spoken earlier.

Transcript reconstruction that sorts by real elapsed time already exists for
genuine LLM turns (captured at generation time) and for tool/action calls
(captured at invocation time). A manually-pushed line with no equivalent
capture has no real anchor, so the sort falls back to positional
interpolation based on the (possibly delayed) commit order — which is wrong
exactly when this defect triggers.

## The fix pattern

**Rule:** every code path that speaks text by pushing a TTS frame directly,
instead of letting a normal LLM completion produce it, must independently
record that text with a real elapsed-time anchor at the moment it is pushed
— the same capture buffer genuine LLM responses use — not rely on being
inferred from raw commit order later.

**Why:** without that anchor, chronological reconstruction has nothing to
work with for that entry and can only guess by position, which silently
inverts prompt/answer order whenever the aggregator's flush is delayed.

**How to apply:** treat this as a checklist for *every* current and future
direct-speech push site in a voice pipeline, not just the obvious ones —
they're easy to add without realizing the transcript needs a matching
capture call. A push site can be skipped only if it already has its own
established out-of-band anchoring mechanism (e.g. a message queued
separately for context injection) or it is truly terminal (nothing else is
ever transcribed after it). When in doubt, anchor it.
