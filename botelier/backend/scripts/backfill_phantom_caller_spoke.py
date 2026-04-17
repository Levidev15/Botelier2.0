"""
One-shot backfill: clear ``caller_spoke`` on calls whose ``user_first_speech``
transcript is actually the bot's own greeting (Task #110).

Background
----------
Before Task #110, the cached greeting was injected at the head of the Pipecat
pipeline via ``PipelineTask.queue_frames``. The cached TTSAudioRawFrames
flowed through the STT processor and Deepgram transcribed them, emitting a
``TranscriptionFrame`` that the ``FirstUserSpeechTracker`` recorded as
``user_first_speech`` and then flipped ``call_logs.caller_spoke = TRUE``.

This script walks ``call_logs`` joined to ``call_events`` (event_type =
'user_first_speech') and — for every row where the transcript is sufficiently
similar to the assistant's ``first_message`` — sets ``caller_spoke = FALSE``.
The event itself is retained for forensic comparison.

Similarity metric: longest-common-substring length divided by the length of
the (shorter of the two) normalized strings. Threshold default 0.35 catches
the observed garbled transcripts ("Welcome to Ping Binder's rights…" vs.
"Welcome to primm valley resorts…" shares "Welcome to " plus scattered
fragments, similarity ≈ 0.40) while avoiding real caller utterances.

Usage
-----
    cd botelier/backend
    python -m scripts.backfill_phantom_caller_spoke            # dry run
    python -m scripts.backfill_phantom_caller_spoke --apply    # actually update
    python -m scripts.backfill_phantom_caller_spoke --days 30  # widen window

Run OUT OF BAND of the deploy. Idempotent — re-running after an --apply
finds nothing to fix.
"""

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone

# Add backend root so ``botelier.*`` imports resolve when run as a module.
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from botelier.database import SessionLocal
from botelier.models.assistant import Assistant
from botelier.models.call import CallLog
from botelier.models.call_event import CallEvent
from loguru import logger


_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def _normalize(text: str) -> str:
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def _longest_common_substring_len(a: str, b: str) -> int:
    """Classic DP LCS-substring. O(len(a) * len(b)) but inputs are short."""
    if not a or not b:
        return 0
    # Use a rolling 1D array to keep memory bounded.
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        curr = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
                if curr[j] > best:
                    best = curr[j]
        prev = curr
    return best


def _similarity(transcript: str, greeting: str) -> float:
    t = _normalize(transcript)
    g = _normalize(greeting)
    if not t or not g:
        return 0.0
    lcs = _longest_common_substring_len(t, g)
    return lcs / min(len(t), len(g))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply", action="store_true", help="Actually update rows (default: dry run).")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days.")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.35,
        help="Similarity threshold (0..1). Lower catches more; default 0.35.",
    )
    args = parser.parse_args()

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=args.days)
    db = SessionLocal()
    try:
        candidates = (
            db.query(CallLog, CallEvent, Assistant)
            .join(CallEvent, CallEvent.call_log_id == CallLog.id)
            .join(Assistant, Assistant.id == CallLog.assistant_id)
            .filter(
                CallEvent.event_type == "user_first_speech",
                CallLog.created_at >= cutoff,
                CallLog.caller_spoke.is_(True),
            )
            .all()
        )

        logger.info(
            f"Scanned {len(candidates)} candidate rows (lookback {args.days}d, "
            f"caller_spoke=TRUE with a user_first_speech event)"
        )

        to_fix = []
        for call_log, event, assistant in candidates:
            details = event.details or {}
            transcript = details.get("transcript") if isinstance(details, dict) else None
            if not transcript:
                continue
            greeting = assistant.first_message or ""
            sim = _similarity(transcript, greeting)
            if sim >= args.threshold:
                to_fix.append((call_log, sim, transcript, greeting))

        logger.info(
            f"Matched {len(to_fix)} call_logs whose user_first_speech transcript "
            f"resembles the assistant greeting (threshold={args.threshold})"
        )

        for call_log, sim, transcript, greeting in to_fix[:20]:
            logger.info(
                f"  {call_log.id}  sim={sim:.2f}  transcript={transcript[:70]!r}"
            )
        if len(to_fix) > 20:
            logger.info(f"  … and {len(to_fix) - 20} more")

        if not args.apply:
            logger.warning("DRY RUN — re-run with --apply to commit changes")
            return

        for call_log, _sim, _t, _g in to_fix:
            call_log.caller_spoke = False
        db.commit()
        logger.success(f"Cleared caller_spoke on {len(to_fix)} rows")
    finally:
        db.close()


if __name__ == "__main__":
    main()
