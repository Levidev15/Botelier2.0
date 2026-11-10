"""Save real-worker transcripts from real STT/LLM/TTS events, not hand-built context."""

import asyncio
import json

import pytest

from lifecycle_io import (
    ANSWER, CALL_SID, CORRECTION, GREETING, QUESTION, REVISED_ANSWER,
)
from lifecycle_support import OfflineCall
from transcript_io import TranscriptProviders
from transcript_tools import (
    FLOW_INTRO, FLOW_PROMPT, TOOL_PREFACE, TOOL_RESULT,
    flow_tools, lookup_tools, tool_reply,
)


async def start_conversation(call):
    await call.wait_until(lambda: call.records.call.ai_greeting_completed)
    call.carrier.start_streaming()
    await call.wait_until(
        lambda: any(isinstance(item, bytes) for item in call.providers.stt.sent)
    )


async def wait_for_reply(call, text, count=1):
    await call.wait_until(
        lambda: sum(
            message.get("role") == "assistant" and message.get("content") == text
            for message in call.created[4].messages
        ) == count and not call.created[5]._bot_speaking
    )


def saved_transcript(call):
    call.assert_clean()
    assert len(call.records.saved) == 1
    assert call.records.saved[0]["call_sid"] == CALL_SID
    transcript = call.records.saved[0]["transcript"]
    assert all("_elapsed_s" not in item for item in transcript)
    return transcript


def transcript_diagnostics(call):
    """Synthetic-fixture data only; show boundaries when a new scenario fails."""
    return {
        "context": [
            message for message in call.created[4].messages
            if message.get("role") != "system"
        ],
        "captured": call.handler.pending_responses.get(CALL_SID),
        "actions": call.handler.action_timestamps.get(CALL_SID),
        "tts": call.providers.tts.sent,
    }


@pytest.mark.parametrize("repeated_role", ["assistant", "user"])
def test_repeated_utterances_keep_their_own_chronological_position(repeated_role):
    """Reusing the first text-prefix timestamp would move the second turn backwards."""
    async def scenario():
        replies = [ANSWER, ANSWER if repeated_role == "assistant" else REVISED_ANSWER]
        second_question = CORRECTION if repeated_role == "assistant" else QUESTION
        async with OfflineCall(providers=TranscriptProviders(replies)) as call:
            await start_conversation(call)
            await call.providers.user_turn()
            await wait_for_reply(call, ANSWER)
            await call.providers.user_turn(second_question, turn_index=1)
            await wait_for_reply(
                call, replies[1], count=2 if repeated_role == "assistant" else 1,
            )
            await call.finish("graceful_end")
            transcript = saved_transcript(call)
            assert [(item["role"], item["content"]) for item in transcript] == [
                ("assistant", GREETING),
                ("user", QUESTION),
                ("assistant", ANSWER),
                ("user", second_question),
                ("assistant", replies[1]),
            ]
            assert not any(item["interrupted"] for item in transcript)
    asyncio.run(scenario())


@pytest.mark.parametrize("same_prefix", [False, True])
def test_interrupting_one_reply_does_not_mark_a_later_similar_reply(same_prefix):
    """Text-based interruption matching must not label a completed later utterance."""
    async def scenario():
        first = (
            "This fixture response has a deliberately shared opening sentence "
            "that is longer than eighty characters. The first ending."
            if same_prefix else ANSWER
        )
        second = (
            "This fixture response has a deliberately shared opening sentence "
            "that is longer than eighty characters. The revised ending."
            if same_prefix else ANSWER
        )
        providers = TranscriptProviders([first, second], hold_tts_turn=2)
        async with OfflineCall(providers=providers) as call:
            await start_conversation(call)
            await call.providers.user_turn()
            await call.wait_until(
                lambda: providers.tts.pending_metadata is not None
                and call.created[5]._bot_speaking
            )
            clears = sum(
                item.get("event") == "clear" for item in call.carrier.wire_messages()
            )
            await providers.user_turn(CORRECTION, turn_index=1, final=False)
            await call.wait_until(
                lambda: sum(
                    item.get("event") == "clear"
                    for item in call.carrier.wire_messages()
                ) == clears + 1
            )
            await providers.user_event("EndOfTurn", CORRECTION, turn_index=1)
            await wait_for_reply(call, second, count=1 if same_prefix else 2)
            await call.finish("graceful_end")
            transcript = saved_transcript(call)
            replies = [
                item for item in transcript
                if item["role"] == "assistant" and item["content"] != GREETING
            ]
            assert [(item["content"], item["interrupted"]) for item in replies] == [
                (first, True), (second, False),
            ]
            assert [(item["role"], item["content"]) for item in transcript] == [
                ("assistant", GREETING), ("user", QUESTION),
                ("assistant", first), ("user", CORRECTION),
                ("assistant", second),
            ]
    asyncio.run(scenario())


@pytest.mark.parametrize("with_preface", [False, True])
def test_real_flow_trigger_speech_precedes_the_callers_answer(with_preface):
    """Direct flow prompts must not disappear, duplicate or move after their answer."""
    async def scenario():
        providers = TranscriptProviders([
            tool_reply("start_fixture", text=TOOL_PREFACE if with_preface else None),
            ANSWER,
        ])
        async with OfflineCall(providers=providers, tool_setup=flow_tools) as call:
            await start_conversation(call)
            await providers.user_turn()
            try:
                await call.wait_until(
                    lambda: any(
                        item.get("type") == "Speak" and item.get("text") == FLOW_PROMPT
                        for item in providers.tts.sent
                    ) and not call.created[16].get_audio_contexts()
                    and not call.created[5]._bot_speaking
                )
            except TimeoutError as exc:
                raise AssertionError(transcript_diagnostics(call)) from exc
            requests = [body for body in providers.requests if body.get("stream")]
            assert len(requests) == 1, "Direct flow speech must not trigger a duplicate completion"
            await providers.user_turn(CORRECTION, turn_index=1)
            await wait_for_reply(call, ANSWER)
            await call.finish("graceful_end")
            transcript = saved_transcript(call)
            expected = [
                GREETING, QUESTION,
                *([TOOL_PREFACE] if with_preface else []),
                "[Action: start_fixture]", FLOW_INTRO, FLOW_PROMPT, CORRECTION, ANSWER,
            ]
            # Adjacent direct utterances may share one native context aggregate.
            # Their words must still occur exactly once, before the caller answer.
            assert " ".join(item["content"] for item in transcript).split() == (
                " ".join(expected).split()
            )
            assert call.records.saved[0]["tools_used"] == ["start_fixture"]
            assert all(item["role"] in ("assistant", "user") for item in transcript)
            spoken = "".join(
                item["text"] for item in providers.tts.sent if item.get("type") == "Speak"
            )
            for text in [GREETING, FLOW_INTRO, FLOW_PROMPT, ANSWER]:
                assert spoken.count(text) == 1
            assert "variables_to_collect" not in spoken
    asyncio.run(scenario())


@pytest.mark.parametrize("stream_layout", ["mixed", "separate", "mixed_with_usage"])
def test_text_plus_tool_call_keeps_speech_action_and_result_narration_in_order(stream_layout):
    """Tool JSON must reach the model, not leak as speech or replace its narration."""
    async def scenario():
        providers = TranscriptProviders([
            tool_reply("lookup_fixture", text=TOOL_PREFACE), ANSWER,
        ], separate_tool_chunks=stream_layout == "separate",
           usage_on_content=stream_layout == "mixed_with_usage")
        async with OfflineCall(providers=providers, tool_setup=lookup_tools) as call:
            await start_conversation(call)
            await providers.user_turn()
            await wait_for_reply(call, ANSWER)
            requests = [body for body in providers.requests if body.get("stream")]
            assert len(requests) == 2
            results = [
                message for message in requests[-1]["messages"]
                if message.get("role") == "tool"
            ]
            assert len(results) == 1
            assert results[0]["tool_call_id"] == "offline-transcript-tool"
            assert json.loads(results[0]["content"]) == TOOL_RESULT
            diagnostics = transcript_diagnostics(call)
            await call.finish("graceful_end")
            transcript = saved_transcript(call)
            assert [(item["role"], item["content"]) for item in transcript] == [
                ("assistant", GREETING), ("user", QUESTION),
                ("assistant", TOOL_PREFACE), ("assistant", "[Action: lookup_fixture]"),
                ("assistant", ANSWER),
            ], json.dumps(diagnostics)
            assert call.records.saved[0]["tools_used"] == ["lookup_fixture"]
            assert call.records.saved[0]["llm_prompt_tokens"] == 22
            assert call.records.saved[0]["llm_completion_tokens"] == 14
            spoken = "".join(
                item["text"] for item in providers.tts.sent if item.get("type") == "Speak"
            )
            for text in [GREETING, TOOL_PREFACE, ANSWER]:
                assert spoken.count(text) == 1
            assert "private-fixture-data" not in spoken
            assert "private-fixture-data" not in json.dumps(transcript)
    asyncio.run(scenario())


def test_hangup_closes_a_mixed_model_stream_without_running_its_unfinished_tool():
    """The stream adapter must propagate cancel/close, not retain the HTTP reader."""
    async def scenario():
        providers = TranscriptProviders([
            tool_reply("lookup_fixture", text=TOOL_PREFACE + " "),
        ], stall_after_first=True)
        async with OfflineCall(providers=providers, tool_setup=lookup_tools) as call:
            await start_conversation(call)
            await providers.user_turn()
            await call.wait_until(
                lambda: providers.stream is not None
                and providers.stream.blocked.is_set()
                and any(
                    item.get("type") == "Speak"
                    for item in providers.tts.sent[2:]
                )
            )
            await call.finish("caller_hangup")
            transcript = saved_transcript(call)
            assert providers.stream.cancelled and providers.stream.closed
            assert not providers.stream.gate.is_set()
            assert call.records.saved[0]["tools_used"] == []
            assert len([body for body in providers.requests if body.get("stream")]) == 1
            assert not any(item["content"] == ANSWER for item in transcript)
            assert not any(
                "private-fixture-data" in item["content"] for item in transcript
            )
    asyncio.run(scenario())


def test_intentionally_repeated_greeting_does_not_move_the_initial_greeting():
    """An uncaptured opening greeting must not consume a later matching LLM turn."""
    async def scenario():
        async with OfflineCall(providers=TranscriptProviders([GREETING])) as call:
            await start_conversation(call)
            await call.providers.user_turn()
            await wait_for_reply(call, GREETING, count=2)
            await call.finish("graceful_end")
            transcript = saved_transcript(call)
            assert [(item["role"], item["content"]) for item in transcript] == [
                ("assistant", GREETING), ("user", QUESTION), ("assistant", GREETING),
            ]
    asyncio.run(scenario())
