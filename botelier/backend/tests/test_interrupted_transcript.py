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
    handler.action_timestamps = {}   # added for global-sort action timestamp assignment
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


class TestTranscriptOrdering:
    def test_timestamped_messages_are_ordered_by_capture_time(self):
        """Context commit order must not make the call transcript misleading."""
        handler = _bare_handler()
        handler.user_turn_timestamps[CALL_SID] = [
            {"text": "I need a room.", "elapsed_s": 4.0},
            {"text": "Two adults.", "elapsed_s": 12.0},
        ]
        handler.pending_responses[CALL_SID] = [
            {"text": "How many adults?", "elapsed_s": 8.0},
        ]

        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx(
                [
                    {"role": "user", "content": "I need a room."},
                    {"role": "user", "content": "Two adults."},
                    {"role": "assistant", "content": "How many adults?"},
                ]
            ),
        )

        assert [entry["content"] for entry in transcript] == [
            "I need a room.",
            "How many adults?",
            "Two adults.",
        ]

    def test_global_sort_crosses_action_barrier(self):
        """A tool-action entry must NOT be a fixed barrier for the global sort.

        Scenario: the LLM context was committed in this (wrong) order —
            user(T=10s) · [Action: check_availability] · assistant(T=2s)
        The assistant actually spoke at T=2s (greeting/confirmation before the
        user's turn), then the user replied at T=10s, then the tool fired.
        The slot-bounded sort left this unchanged; the global sort must produce:
            assistant(T=2s) · [Action: check_availability(~6s)] · user(T=10s)
        where the action's virtual time is interpolated between its neighbours.
        """
        handler = _bare_handler()
        handler.user_turn_timestamps[CALL_SID] = [
            {"text": "Yes please.", "elapsed_s": 10.0},
        ]
        handler.pending_responses[CALL_SID] = [
            {"text": "Let me check that for you.", "elapsed_s": 2.0},
        ]
        # Supply the action timestamp so it gets an elapsed time between T=2 and T=10
        handler.action_timestamps[CALL_SID] = [
            {"name": "check_availability", "elapsed_s": 6.0},
        ]

        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx(
                [
                    # Context committed out of real-time order
                    {"role": "user", "content": "Yes please."},
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {"function": {"name": "check_availability"}}
                        ],
                    },
                    {"role": "assistant", "content": "Let me check that for you."},
                ]
            ),
        )

        contents = [e["content"] for e in transcript]
        assert contents == [
            "Let me check that for you.",   # T=2s
            "[Action: check_availability]", # T=6s (supplied)
            "Yes please.",                   # T=10s
        ], f"Unexpected order: {contents}"

        # Internal _elapsed_s must be stripped before returning — callers must never
        # see it in the final transcript dict.
        action_entry = next(e for e in transcript if e["content"].startswith("[Action:"))
        assert "_elapsed_s" not in action_entry, (
            "_elapsed_s is an internal sort key and must be stripped from the final output"
        )

    def test_extra_messages_join_the_global_sort_not_just_appended(self):
        """extra_messages (e.g. the pre-transfer TTSSpeakFrame message, which
        bypasses the LLM context entirely) must take part in the same
        chronological sort as every other entry (Task #534) — a prior version
        appended them AFTER this function's own sort had already run, so they
        could only ever land dead last even when their real elapsed time put
        them earlier than a later-committed context message.
        """
        handler = _bare_handler()
        handler.user_turn_timestamps[CALL_SID] = [
            {"text": "Please transfer me.", "elapsed_s": 5.0},
        ]
        # Context commits the user's turn only — the pre-transfer phrase
        # never enters the LLM context, so it has no capture-buffer entry of
        # its own and arrives purely via extra_messages.
        handler.pending_responses[CALL_SID] = []

        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx([{"role": "user", "content": "Please transfer me."}]),
            extra_messages=[
                {
                    "role": "assistant",
                    "content": "One moment while I connect you.",
                    "interrupted": False,
                    "_elapsed_s": 6.0,
                }
            ],
        )

        contents = [e["content"] for e in transcript]
        assert contents == [
            "Please transfer me.",              # T=5s
            "One moment while I connect you.",  # T=6s — correctly placed last
        ]
        # Anchored entries get a display timestamp too, not just the sort key.
        pre_transfer_entry = transcript[-1]
        assert pre_transfer_entry.get("timestamp")
        assert "_elapsed_s" not in pre_transfer_entry

    def test_extra_message_without_elapsed_anchor_still_lands_after_prior_entries(self):
        """An extra_message with no elapsed anchor (defensive fallback) must
        still interpolate to AFTER the existing timed entries rather than
        being blindly forced to the tail regardless of real chronology —
        merging happens before the sort now, so plain list order plus
        interpolation both push it to the correct place here."""
        handler = _bare_handler()
        handler.user_turn_timestamps[CALL_SID] = [
            {"text": "Please transfer me.", "elapsed_s": 5.0},
        ]
        handler.pending_responses[CALL_SID] = []

        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx([{"role": "user", "content": "Please transfer me."}]),
            extra_messages=[
                {
                    "role": "assistant",
                    "content": "One moment while I connect you.",
                    "interrupted": False,
                }
            ],
        )

        contents = [e["content"] for e in transcript]
        assert contents == [
            "Please transfer me.",
            "One moment while I connect you.",
        ]

    def test_global_sort_without_action_timestamps_uses_interpolation(self):
        """When no action_timestamps are supplied, the action is interpolated correctly.

        Same scenario as above but without an explicit action timestamp: the
        action's virtual time is interpolated between its timed neighbours and
        it must still end up between them in the output.
        """
        handler = _bare_handler()
        handler.user_turn_timestamps[CALL_SID] = [
            {"text": "Yes please.", "elapsed_s": 10.0},
        ]
        handler.pending_responses[CALL_SID] = [
            {"text": "Let me check that for you.", "elapsed_s": 2.0},
        ]
        # No action_timestamps — action gets interpolated virtual time

        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx(
                [
                    {"role": "user", "content": "Yes please."},
                    {
                        "role": "assistant",
                        "tool_calls": [{"function": {"name": "check_availability"}}],
                    },
                    {"role": "assistant", "content": "Let me check that for you."},
                ]
            ),
        )

        contents = [e["content"] for e in transcript]
        assert contents == [
            "Let me check that for you.",   # T=2s
            "[Action: check_availability]", # interpolated ~6s
            "Yes please.",                   # T=10s
        ], f"Unexpected order without explicit action timestamps: {contents}"

    def test_flow_trigger_and_flow_function_each_get_own_timestamp(self):
        """Flow trigger (start_booking) and a flow function (collect_checkin) must
        each receive their own timestamp, keyed by name, not consumed by position.

        Context committed order (wrong):
            [Action: start_booking] (T=?) · user(T=12s) · [Action: collect_checkin]
        Actual elapsed order:
            start_booking fires at T=2s, user speaks at T=12s, collect_checkin at T=18s
        After global sort the transcript must read:
            start_booking · user · collect_checkin
        """
        handler = _bare_handler()
        handler.user_turn_timestamps[CALL_SID] = [
            {"text": "March 15th.", "elapsed_s": 12.0},
        ]
        handler.pending_responses[CALL_SID] = []
        handler.action_timestamps[CALL_SID] = [
            {"name": "start_booking", "elapsed_s": 2.0},
            {"name": "collect_checkin", "elapsed_s": 18.0},
        ]

        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx(
                [
                    # Out-of-order as Pipecat might commit them
                    {
                        "role": "assistant",
                        "tool_calls": [{"function": {"name": "start_booking"}}],
                    },
                    {"role": "user", "content": "March 15th."},
                    {
                        "role": "assistant",
                        "tool_calls": [{"function": {"name": "collect_checkin"}}],
                    },
                ]
            ),
        )

        contents = [e["content"] for e in transcript]
        assert contents == [
            "[Action: start_booking]",   # T=2s — trigger
            "March 15th.",               # T=12s
            "[Action: collect_checkin]", # T=18s — flow function
        ], f"Trigger and function got wrong timestamps/order: {contents}"

    def test_non_flow_action_does_not_consume_flow_action_timestamp(self):
        """A non-flow tool action (no entry in action_timestamps) must NOT
        consume a flow action's queued timestamp, leaving the flow action
        with the wrong elapsed time or no timestamp at all.

        Scenario:
            assistant(T=1s) · [Action: transfer_call] · [Action: check_availability] · user(T=20s)
        action_timestamps only has an entry for check_availability (T=12s).
        transfer_call must fall back to interpolation; check_availability must still
        get its real T=12s.
        """
        handler = _bare_handler()
        handler.user_turn_timestamps[CALL_SID] = [
            {"text": "What is available?", "elapsed_s": 20.0},
        ]
        handler.pending_responses[CALL_SID] = [
            {"text": "Of course!", "elapsed_s": 1.0},
        ]
        # Only the flow action has a recorded timestamp; the non-flow transfer_call
        # has no entry — it must NOT steal check_availability's slot.
        handler.action_timestamps[CALL_SID] = [
            {"name": "check_availability", "elapsed_s": 12.0},
        ]

        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx(
                [
                    {"role": "assistant", "content": "Of course!"},
                    {
                        "role": "assistant",
                        "tool_calls": [{"function": {"name": "transfer_call"}}],
                    },
                    {
                        "role": "assistant",
                        "tool_calls": [{"function": {"name": "check_availability"}}],
                    },
                    {"role": "user", "content": "What is available?"},
                ]
            ),
        )

        contents = [e["content"] for e in transcript]
        # check_availability (T=12s) must appear before user (T=20s).
        # transfer_call has no timestamp so it interpolates; its exact position is
        # flexible, but it must NOT displace check_availability.
        assert "[Action: check_availability]" in contents
        assert "[Action: transfer_call]" in contents
        ca_idx = contents.index("[Action: check_availability]")
        user_idx = contents.index("What is available?")
        assert ca_idx < user_idx, (
            f"check_availability ({ca_idx}) should appear before user ({user_idx}): {contents}"
        )

    def test_mcp_handler_wrapper_records_timestamp_and_sorts(self):
        """MCP tool wrapper captures action timestamp; _extract_transcript sorts correctly.

        Simulates the wrapping pattern applied at the MCP merge call site in
        call_handler so that [Action: mcp_tool] entries get real elapsed times
        rather than relying on positional interpolation.
        """
        import asyncio
        from datetime import datetime
        from types import SimpleNamespace

        handler = _bare_handler()
        handler.call_start_times = {CALL_SID: datetime.utcnow()}  # type: ignore[attr-defined]
        handler.action_timestamps[CALL_SID] = []
        handler.user_turn_timestamps[CALL_SID] = [
            {"text": "Please check me in.", "elapsed_s": 10.0},
        ]
        handler.pending_responses[CALL_SID] = [
            {"text": "Of course, let me check.", "elapsed_s": 2.0},
        ]

        # Reproduce the closure created at the MCP merge call site.
        _mcp_fn = "mcp_check_in"
        _raw_mcp_calls: list = []

        async def _raw_mcp(params):
            _raw_mcp_calls.append(params)

        from datetime import datetime as _dt_mcp  # noqa: PLC0415

        async def _mcp_ts_wrapper(
            params,
            _fn=_mcp_fn,
            _raw=_raw_mcp,
            _ch=handler,
            _cs=CALL_SID,
        ):
            _ts_list = _ch.action_timestamps.get(_cs)
            if _ts_list is not None:
                _s = _ch.call_start_times.get(_cs)
                _ts_list.append(
                    {
                        "name": _fn,
                        "elapsed_s": (_dt_mcp.utcnow() - _s).total_seconds() if _s else 0.0,
                    }
                )
            return await _raw(params)

        # Invoke the wrapper — simulates LLM calling the MCP tool mid-call.
        asyncio.run(_mcp_ts_wrapper(SimpleNamespace()))

        # 1 — Timestamp entry recorded under the correct name.
        assert len(handler.action_timestamps[CALL_SID]) == 1
        ts_entry = handler.action_timestamps[CALL_SID][0]
        assert ts_entry["name"] == "mcp_check_in"
        assert ts_entry["elapsed_s"] >= 0.0, "Elapsed must be non-negative"

        # 2 — _extract_transcript uses the recorded timestamp in the global sort.
        # Context out of order: user(T=10s) · action · assistant(T=2s).
        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx(
                [
                    {"role": "user", "content": "Please check me in."},
                    {
                        "role": "assistant",
                        "tool_calls": [{"function": {"name": "mcp_check_in"}}],
                    },
                    {"role": "assistant", "content": "Of course, let me check."},
                ]
            ),
        )

        contents = [e["content"] for e in transcript]
        # assistant(T=2s) · action(~0s elapsed but < user T=10s) · user(T=10s)
        # The critical assertion: action must appear before user in the final order.
        assert "[Action: mcp_check_in]" in contents, f"Action missing: {contents}"
        action_idx = contents.index("[Action: mcp_check_in]")
        user_idx = contents.index("Please check me in.")
        assert action_idx < user_idx, (
            f"MCP action ({action_idx}) must appear before user ({user_idx}): {contents}"
        )

        # 3 — Internal _elapsed_s key must be stripped from the final output.
        action_entry = next(e for e in transcript if e["content"].startswith("[Action:"))
        assert "_elapsed_s" not in action_entry, (
            "_elapsed_s is internal and must be stripped before returning"
        )

    def test_recovered_response_inserted_at_elapsed_position(self):
        """Recovered (incomplete) assistant response must be inserted by time, not appended.

        Scenario: an action fires at T=5s, then the LLM starts generating a response
        at T=8s but the caller hangs up before it commits.  Context has only the
        user turn and the action.  The recovered response must appear AFTER the
        action (T=5s < T=8s), not at the very end after the user entry.
        """
        handler = _bare_handler()
        handler.user_turn_timestamps[CALL_SID] = [
            {"text": "What rooms do you have?", "elapsed_s": 3.0},
        ]
        handler.pending_responses[CALL_SID] = [
            # This response was generated but never committed to context (hang-up)
            {"text": "We have a Superior Room available.", "elapsed_s": 8.0},
        ]
        handler.action_timestamps[CALL_SID] = [
            {"name": "check_availability", "elapsed_s": 5.0},
        ]

        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx(
                [
                    {"role": "user", "content": "What rooms do you have?"},
                    {
                        "role": "assistant",
                        "tool_calls": [{"function": {"name": "check_availability"}}],
                    },
                    # Note: no committed assistant text — hang-up during generation
                ]
            ),
        )

        contents = [e["content"] for e in transcript]
        assert contents == [
            "What rooms do you have?",          # T=3s
            "[Action: check_availability]",     # T=5s
            "We have a Superior Room available.", # T=8s (recovered, inserted here)
        ], f"Unexpected order for recovered response: {contents}"

        recovered = next(e for e in transcript if e.get("incomplete"))
        assert recovered["incomplete"] is True
        assert recovered["interrupted"] is False


class TestDefectFixes:
    """Targeted regression tests for the three transcript-ordering defects."""

    # ------------------------------------------------------------------ Defect A
    def test_speech_emitted_before_action_when_content_and_tool_calls_together(self):
        """When the LLM returns speech text AND a tool call in the same message,
        both must appear in the transcript — speech first, action second.

        Previously the ``continue`` at the tool_calls branch silently discarded
        ``content``, so only the action entry was produced.
        """
        handler = _bare_handler()
        handler.pending_responses[CALL_SID] = [
            {"text": "I'd be happy to help. What is your check-in date?", "elapsed_s": 8.0},
        ]
        handler.action_timestamps[CALL_SID] = [
            {"name": "collect_checkin", "elapsed_s": 8.1},
        ]
        handler.user_turn_timestamps[CALL_SID] = []

        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx(
                [
                    {
                        "role": "assistant",
                        "content": "I'd be happy to help. What is your check-in date?",
                        "tool_calls": [{"function": {"name": "collect_checkin"}}],
                    }
                ]
            ),
        )

        contents = [e["content"] for e in transcript]
        assert len(contents) == 2, f"Expected 2 entries (speech + action), got: {contents}"
        assert contents[0] == "I'd be happy to help. What is your check-in date?", (
            f"Speech must appear first: {contents}"
        )
        assert contents[1] == "[Action: collect_checkin]", (
            f"Action must appear second: {contents}"
        )

    def test_co_generated_speech_gets_timestamp_from_pending_responses(self):
        """Co-generated speech recovered from content+tool_calls message must receive
        its real elapsed timestamp from pending_responses so it sorts correctly."""
        handler = _bare_handler()
        handler.pending_responses[CALL_SID] = [
            {"text": "Let me confirm that for you.", "elapsed_s": 5.0},
        ]
        handler.action_timestamps[CALL_SID] = [
            {"name": "confirm_booking", "elapsed_s": 5.1},
        ]
        handler.user_turn_timestamps[CALL_SID] = [
            {"text": "Yes, that is correct.", "elapsed_s": 15.0},
        ]

        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx(
                [
                    {
                        "role": "assistant",
                        "content": "Let me confirm that for you.",
                        "tool_calls": [{"function": {"name": "confirm_booking"}}],
                    },
                    {"role": "user", "content": "Yes, that is correct."},
                ]
            ),
        )

        contents = [e["content"] for e in transcript]
        # Real-time order: speech(5s) → action(5.1s) → user(15s)
        assert contents == [
            "Let me confirm that for you.",
            "[Action: confirm_booking]",
            "Yes, that is correct.",
        ], f"Wrong order: {contents}"

    def test_content_list_format_in_tool_calls_message_is_recovered(self):
        """Content in list form (OpenAI structured format) inside a tool_calls
        message must also be emitted as a speech entry."""
        handler = _bare_handler()
        handler.pending_responses[CALL_SID] = [
            {"text": "Great, looking that up now.", "elapsed_s": 3.0},
        ]
        handler.action_timestamps[CALL_SID] = [
            {"name": "lookup_guest", "elapsed_s": 3.1},
        ]
        handler.user_turn_timestamps[CALL_SID] = []

        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx(
                [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Great, looking that up now."}],
                        "tool_calls": [{"function": {"name": "lookup_guest"}}],
                    }
                ]
            ),
        )

        contents = [e["content"] for e in transcript]
        assert len(contents) == 2, f"Expected speech + action: {contents}"
        assert contents[0] == "Great, looking that up now.", f"Speech first: {contents}"
        assert contents[1] == "[Action: lookup_guest]", f"Action second: {contents}"

    # ------------------------------------------------------------------ Defect B
    def test_untimed_extra_message_gets_timestamp_from_pending_responses(self):
        """An assistant extra_message without ``_elapsed_s`` (e.g. a TTS-direct
        greeting that bypassed the LLM) must pick up its real capture time from
        ``pending_responses`` before the global sort runs.

        Without the fix it fell to the ``right is None`` tail-interpolation path,
        placing it at ``last_timed_ts + tiny_delta`` — AFTER the user reply even
        though the greeting was spoken first.
        """
        handler = _bare_handler()
        # The TTS-direct greeting was captured by on_llm_response at T=8s.
        handler.pending_responses[CALL_SID] = [
            {"text": "I'd be happy to assist you today.", "elapsed_s": 8.0},
        ]
        # User replies at T=23s — appears at context index 0 (committed early by STT).
        handler.user_turn_timestamps[CALL_SID] = [
            {"text": "September first.", "elapsed_s": 23.0},
        ]
        handler.action_timestamps[CALL_SID] = []

        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx([{"role": "user", "content": "September first."}]),
            extra_messages=[
                {
                    "role": "assistant",
                    "content": "I'd be happy to assist you today.",
                    "interrupted": False,
                    # No _elapsed_s — simulates TTS-direct speech without anchor
                }
            ],
        )

        contents = [e["content"] for e in transcript]
        assert contents == [
            "I'd be happy to assist you today.",  # T=8s from pending_responses
            "September first.",                   # T=23s from STT
        ], f"Greeting must sort before user reply: {contents}"

        greeting_entry = next(e for e in transcript if e["content"] == "I'd be happy to assist you today.")
        assert greeting_entry.get("timestamp") == "0:08", (
            f"Greeting must carry the real captured timestamp: {greeting_entry.get('timestamp')!r}"
        )

    # ------------------------------------------------------------------ Defect C
    def test_duplicate_prefix_user_turns_first_occurrence_wins(self):
        """When two STT captures share the same 80-char prefix (e.g. an early
        partial capture and the full utterance later), the annotation map must
        keep only the FIRST occurrence so the second context message does not
        accidentally inherit the first entry's (wrong) timestamp.

        The old inline scan was functionally first-match which happens to be
        correct, but the map was dead code and offered no dedup guarantee.
        This test locks in the first-occurrence behaviour via the maps.
        """
        handler = _bare_handler()
        # Two STT captures with similar prefixes — first at T=14s, second at T=50s.
        handler.user_turn_timestamps[CALL_SID] = [
            {"text": "September fifth.", "elapsed_s": 14.0},   # partial / early capture
            {"text": "September fifth, please.", "elapsed_s": 50.0},
        ]
        handler.pending_responses[CALL_SID] = []
        handler.action_timestamps[CALL_SID] = []

        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx(
                [
                    # Context has only the full utterance
                    {"role": "user", "content": "September fifth."},
                ]
            ),
        )

        assert len(transcript) == 1
        entry = transcript[0]
        # First-occurrence (T=14s) wins — the entry's content exactly matches
        # the first capture's text.
        assert entry.get("timestamp") == "0:14", (
            f"First-occurrence capture at 0:14 must win: got {entry.get('timestamp')!r}"
        )

    def test_screenshot_scenario_end_to_end_ordering(self):
        """Regression for the exact ordering failure observed in the screenshot.

        The assistant's greeting came via TTS-direct (extra_messages, no _elapsed_s).
        Pipecat also committed the caller's reply "September first." early in the
        LLM context — BEFORE the collect_checkin tool result.

        Without the Defect B fix the greeting's tail-interpolation placed it at
        23.0001 s (just past the user's 23 s anchor), making the transcript read:
            start_new_booking · user "September first." · greeting · collect_checkin
        instead of the correct chronological order.

        After the fix the greeting picks up T=15 s from pending_responses and
        sorts before the user's reply.
        """
        handler = _bare_handler()
        handler.user_turn_timestamps[CALL_SID] = [
            {"text": "I need to book a new room.", "elapsed_s": 14.0},
            {"text": "September first.", "elapsed_s": 23.0},
        ]
        # Speech captured by on_llm_response at T=15s.
        handler.pending_responses[CALL_SID] = [
            {"text": "I'd be happy to assist. What is your check-in date?", "elapsed_s": 15.0},
        ]
        handler.action_timestamps[CALL_SID] = [
            {"name": "start_new_booking", "elapsed_s": 14.1},
            {"name": "collect_checkin", "elapsed_s": 23.5},  # fires after user speaks
        ]

        # LLM context: STT commits "September first." BEFORE the collect_checkin
        # tool result (Pipecat early commit). The greeting comes via TTS-direct
        # and is not in the LLM context — it arrives as extra_messages without
        # _elapsed_s, triggering the Defect B tail-interpolation bug.
        transcript, _ = handler._extract_transcript(
            CALL_SID,
            _ctx(
                [
                    {"role": "user", "content": "I need to book a new room."},
                    {
                        "role": "assistant",
                        "tool_calls": [{"function": {"name": "start_new_booking"}}],
                    },
                    # Committed early by STT — appears before collect_checkin in context
                    {"role": "user", "content": "September first."},
                    {
                        "role": "assistant",
                        "tool_calls": [{"function": {"name": "collect_checkin"}}],
                    },
                ]
            ),
            extra_messages=[
                {
                    "role": "assistant",
                    "content": "I'd be happy to assist. What is your check-in date?",
                    "interrupted": False,
                    # No _elapsed_s — simulates TTS-direct greeting (Defect B target)
                }
            ],
        )

        contents = [e["content"] for e in transcript]
        assert contents == [
            "I need to book a new room.",                           # T=14.0s
            "[Action: start_new_booking]",                          # T=14.1s
            "I'd be happy to assist. What is your check-in date?", # T=15.0s (Defect B fix)
            "September first.",                                      # T=23.0s
            "[Action: collect_checkin]",                            # T=23.5s
        ], f"Wrong ordering in screenshot scenario: {contents}"


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
