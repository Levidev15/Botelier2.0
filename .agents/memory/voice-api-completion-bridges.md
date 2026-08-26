---
name: Voice API completion bridges
description: Caller-safe speech after flow API wait messages when LLM follow-up is delayed or cancelled.
---

After a live flow API node speaks a thinking/wait message, emit a short caller-safe completion bridge as soon as the request returns, while retaining the full API result for the LLM to narrate structured data.

**Why:** Thinking messages are pushed directly to TTS, but detailed API response instructions often require an LLM continuation. If that continuation is delayed or cancelled, callers otherwise hear a wait message followed by silence despite the request finishing.

**How to apply:** Keep the bridge free of raw mapped payloads and internal response instructions. Speak a configured error message directly on failures, and a generic successful completion only on success; preserve the normal function result so the LLM can present detailed options. When transcript context order disagrees with captured elapsed times, reorder only timestamp-backed text entries and retain tool actions as context anchors.