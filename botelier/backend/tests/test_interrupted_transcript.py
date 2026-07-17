"""Ghost-transcript fixes: interrupted-response marking + recovery skip.

Covers the barge-in transcript pipeline in ``call_handler``:

1. ``mark_response_interrupted`` stores the FULL generated text (not a
   truncated key) so prefix matching works in both directions.
2. ``_extract_transcript`` marks a committed context message as interrupted
   when it is the spoken PREFIX of the stored full response (word-timestamp
   TTS commits only the words actually spoken).
3. Incomplete-response recovery skips a captured response that was
   interrupted and never spoken — appending it would show the AI "saying"
   something the caller never heard.
4. Recovery still appends a genuine incomplete response (caller hung up
   before the LLM context committed, no interruption involved).
"""

from unittest.mock import AsyncMock

import pytest

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InterruptionFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from botelier.voice.call_handler import CallHandler
from botelier.voice.engine import InterruptionTracker

CALL_SID = "CA_test_interrupt"


def _bare_handler() -> CallHandler:
    """CallHandler with only the state _extract_transcript needs."""
    handler = CallHandler.__new__(CallHandler)
    handler.interrupted_responses = {}
    handler.user_turn_timestamps = {}
    handler.pending_responses = {}
    return handler


def _ctx(messages):
    return {"messages": messages}


FULL_RESPONSE = (
    "Thank you for calling Mrs Fields. We are open Monday through Friday "
    "from nine in the morning until six in the evening, and on weekends "
    "from ten until four."
)
SPOKEN_PREFIX = "Thank you for calling Mrs Fields. We are open Monday"


class TestMarkResponseInterrupted:
    def test_stores_full_text(self):
        handler = _bare_handler()
        handler.mark_response_interrupted(CALL_SID, FULL_RESPONSE)
        assert FULL_RESPONSE in handler.interrupted_responses[CALL_SID]

    def test_ignores_blank(self):
        handler = _bare_handler()
        handler.mark_response_interrupted(CALL_SID, "   ")
        assert handler.interrupted_responses[CALL_SID] == set()


class TestInterruptedMarking:
    def test_exact_match_marked(self):
        handler = _bare_handler()
        handler.mark_response_interrupted(CALL_SID, FULL_RESPONSE)
        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx(
                [
                    {"role": "user", "content": "What are your hours?"},
                    {"role": "assistant", "content": FULL_RESPONSE},
                ]
            ),
        )
        assert transcript[1]["interrupted"] is True

    def test_spoken_prefix_marked(self):
        """Committed message is only the spoken prefix of the full response."""
        handler = _bare_handler()
        handler.mark_response_interrupted(CALL_SID, FULL_RESPONSE)
        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx(
                [
                    {"role": "user", "content": "What are your hours?"},
                    {"role": "assistant", "content": SPOKEN_PREFIX},
                ]
            ),
        )
        assert transcript[1]["interrupted"] is True

    def test_unrelated_response_not_marked(self):
        handler = _bare_handler()
        handler.mark_response_interrupted(CALL_SID, FULL_RESPONSE)
        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx(
                [
                    {"role": "assistant", "content": "Goodbye, have a great day and thanks for calling."},
                ]
            ),
        )
        assert transcript[0]["interrupted"] is False

    def test_short_overlap_not_marked(self):
        """< 12 overlapping chars must not count as a prefix match."""
        handler = _bare_handler()
        handler.mark_response_interrupted(CALL_SID, "Thank you.")
        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx([{"role": "assistant", "content": "Thank you for holding, I found your reservation."}]),
        )
        assert transcript[0]["interrupted"] is False

    def test_no_interruptions_no_marking(self):
        handler = _bare_handler()
        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx([{"role": "assistant", "content": FULL_RESPONSE}]),
        )
        assert transcript[0]["interrupted"] is False


class TestIncompleteRecoverySkip:
    def test_interrupted_never_spoken_response_is_skipped(self):
        """Generated-but-cancelled response must NOT be recovered as 'said'."""
        handler = _bare_handler()
        handler.mark_response_interrupted(CALL_SID, FULL_RESPONSE)
        handler.pending_responses[CALL_SID] = [{"text": FULL_RESPONSE, "elapsed_s": 12.0}]
        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx([{"role": "user", "content": "What are your hours?"}]),
        )
        assert len(transcript) == 1
        assert transcript[0]["role"] == "user"

    def test_genuine_incomplete_response_is_recovered(self):
        handler = _bare_handler()
        handler.pending_responses[CALL_SID] = [{"text": FULL_RESPONSE, "elapsed_s": 12.0}]
        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx([{"role": "user", "content": "What are your hours?"}]),
        )
        assert len(transcript) == 2
        assert transcript[1]["role"] == "assistant"
        assert transcript[1]["content"] == FULL_RESPONSE
        assert transcript[1]["incomplete"] is True
        assert transcript[1]["interrupted"] is False

    def test_committed_response_not_duplicated(self):
        handler = _bare_handler()
        handler.pending_responses[CALL_SID] = [{"text": FULL_RESPONSE, "elapsed_s": 12.0}]
        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx(
                [
                    {"role": "assistant", "content": FULL_RESPONSE},
                    {"role": "user", "content": "Great, thanks!"},
                ]
            ),
        )
        assert sum(1 for m in transcript if m["role"] == "assistant") == 1


def _tracker(hits: list) -> InterruptionTracker:
    """InterruptionTracker with pipeline push stubbed out for unit testing."""
    tracker = InterruptionTracker(on_interruption=hits.append)
    tracker.push_frame = AsyncMock()
    return tracker


class TestInterruptionTrackerGating:
    """Pipecat broadcasts InterruptionFrame on EVERY user turn start — the
    tracker must only fire its callback for interruptions that arrive while
    the bot is actually speaking, or every completed response would be
    falsely marked interrupted."""

    D = FrameDirection.DOWNSTREAM

    @pytest.mark.asyncio
    async def test_completed_response_then_user_turn_not_interrupted(self):
        hits: list = []
        t = _tracker(hits)
        await t.process_frame(LLMFullResponseStartFrame(), self.D)
        await t.process_frame(LLMTextFrame(text=FULL_RESPONSE), self.D)
        await t.process_frame(BotStartedSpeakingFrame(), self.D)
        await t.process_frame(BotStoppedSpeakingFrame(), self.D)
        # Normal caller reply → InterruptionFrame while bot is silent.
        await t.process_frame(InterruptionFrame(), self.D)
        assert hits == []

    @pytest.mark.asyncio
    async def test_mid_speech_interruption_fires_with_full_buffer(self):
        hits: list = []
        t = _tracker(hits)
        await t.process_frame(LLMFullResponseStartFrame(), self.D)
        await t.process_frame(LLMTextFrame(text="Part one. "), self.D)
        await t.process_frame(LLMTextFrame(text="Part two."), self.D)
        await t.process_frame(BotStartedSpeakingFrame(), self.D)
        await t.process_frame(InterruptionFrame(), self.D)
        assert hits == ["Part one. Part two."]

    @pytest.mark.asyncio
    async def test_greeting_speak_frame_interruptible(self):
        hits: list = []
        t = _tracker(hits)
        await t.process_frame(TTSSpeakFrame(text=FULL_RESPONSE), self.D)
        await t.process_frame(BotStartedSpeakingFrame(), self.D)
        await t.process_frame(InterruptionFrame(), self.D)
        assert hits == [FULL_RESPONSE]

    @pytest.mark.asyncio
    async def test_new_response_resets_previous_buffer(self):
        hits: list = []
        t = _tracker(hits)
        await t.process_frame(LLMFullResponseStartFrame(), self.D)
        await t.process_frame(LLMTextFrame(text="Old response text that completed."), self.D)
        await t.process_frame(BotStartedSpeakingFrame(), self.D)
        await t.process_frame(BotStoppedSpeakingFrame(), self.D)
        # Next turn's response is interrupted — only ITS text may be reported.
        await t.process_frame(LLMFullResponseStartFrame(), self.D)
        await t.process_frame(LLMTextFrame(text="New response text."), self.D)
        await t.process_frame(BotStartedSpeakingFrame(), self.D)
        await t.process_frame(InterruptionFrame(), self.D)
        assert hits == ["New response text."]
