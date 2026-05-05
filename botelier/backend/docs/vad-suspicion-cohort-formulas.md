# VAD suspicion cohort formulas

Use these formulas to compare before/after rollouts for the new call-event types:

- `vad_false_start_suspected`
- `vad_missed_speech_suspected`

## False-start suspected rate

- **Numerator:** count of `vad_false_start_suspected` events in cohort window.
- **Denominator:** count of `turn_finalized` events in same cohort window.
- **Formula:** `false_start_rate = numerator / denominator`

## Missed-speech suspected rate

- **Numerator:** count of `vad_missed_speech_suspected` events in cohort window.
- **Denominator:** count of `turn_finalized` events in same cohort window.
- **Formula:** `missed_speech_rate = numerator / denominator`

## Notes for reliable comparison

1. Keep denominator fixed to `turn_finalized` for pre/post comparability.
2. Filter cohorts by `assistant_id` and (if needed) `vad_provider`.
3. Optionally segment by `min_volume` to isolate threshold effects.
4. Compare equal-length windows and similar traffic mixes.
