---
name: TtsAudioGapTracker mode-aware advice
description: Gap tracker needs aggregation mode at construction; test via logger.info patch not caplog/capfd.
---

## Rule
`TtsAudioGapTracker` accepts `text_aggregation_mode` at construction so `_flush_turn_summary` can emit mode-specific advice in the caller-audible INFO summary:
- TOKEN mode → "increase token_send_min_chars" (batching hint)
- SENTENCE mode → "switch text_aggregation_mode to 'token'"
- None → generic "switch to token" fallback

The mode is derived from `config.tts_config.get("text_aggregation_mode", "token")` inline at the `create_pipeline` instantiation site (inside the try/except to handle missing TextAggregationMode safely).

## Why
The original gap tracker always said "consider switching to token" regardless of mode. Production assistants all have `tts_config: {}` (token mode), so every caller-audible gap event was lying to operators about the fix. This inflated the apparent severity of the gap events and hid the real lever (token_send_min_chars).

## Testing loguru in pytest
pytest's `caplog` and `capfd` do NOT capture loguru output — loguru manages its own sink registry and doesn't write through Python's logging module or raw fd 2 in test environments. The only reliable way to assert on loguru messages in unit tests is to patch the logger object directly:

```python
import botelier.voice.engine as _engine_mod
captured = []
with patch.object(_engine_mod.logger, "info", side_effect=captured.append):
    tracker._flush_turn_summary()
```

This pattern works for any module that does `from loguru import logger` at module level.
