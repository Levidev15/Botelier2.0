"""Tests for TTS word-substitution fix (Task #415).

The _BotelierDeepgramTTSService class is a local class defined inside
create_tts_service(), making direct instantiation difficult (it's a closure
over _sub_patterns). Instead we test the two separable units:

1. _apply_substitutions semantics — whole-word regex, case-insensitivity.
2. Word-boundary buffering logic — the TOKEN-mode accumulation, split, flush,
   and interruption-clear logic is factored into WordBoundaryBuffer below, using
   the exact same algorithm as the production class.

These tests verify the scenarios listed in "Done looks like":
  - Token fragments reassemble into a substituted word.
  - A word split across 2+ tokens is matched after reassembly.
  - The trailing word of a response is never dropped (flush path).
  - Interruption clears the buffer so stale text doesn't leak.
  - SENTENCE mode bypasses buffering (substitution on the full sentence works).
"""

import re

import pytest

# ---------------------------------------------------------------------------
# Reproduce the default substitution table (identical to engine.py defaults).
# ---------------------------------------------------------------------------

_DEFAULT_SUBSTITUTIONS: dict[str, str] = {
    "washcloths": "wash cloths",
    "washcloth": "wash cloth",
    "spelled": "spelt",
    "spells": "spells",
}


def _make_patterns(substitutions: dict[str, str]):
    return [
        (re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE), replacement)
        for word, replacement in substitutions.items()
    ]


def _apply_substitutions(text: str, patterns) -> str:
    for pattern, replacement in patterns:
        text = pattern.sub(replacement, text)
    return text


_PATTERNS = _make_patterns(_DEFAULT_SUBSTITUTIONS)


def apply_subs(text: str) -> str:
    return _apply_substitutions(text, _PATTERNS)


# ---------------------------------------------------------------------------
# WordBoundaryBuffer — exact reproduction of the TOKEN-mode buffering logic
# used in _BotelierDeepgramTTSService.run_tts / flush_audio /
# on_audio_context_interrupted.
# ---------------------------------------------------------------------------


class WordBoundaryBuffer:
    """Pure-Python mirror of the TOKEN-mode word-boundary buffer."""

    def __init__(self):
        self._word_buffer: dict[str, str] = {}

    def feed(self, text: str, context_id: str = "ctx") -> str:
        """Simulate run_tts(text, context_id) in TOKEN mode.

        Returns the (substituted) text that would be passed to super().run_tts(),
        or an empty string if the fragment is still being buffered.
        """
        pending = self._word_buffer.pop(context_id, "") + text
        ws_pos = max(pending.rfind(" "), pending.rfind("\n"), pending.rfind("\t"))
        if ws_pos >= 0:
            complete = pending[: ws_pos + 1]
            self._word_buffer[context_id] = pending[ws_pos + 1 :]
        else:
            complete = ""
            self._word_buffer[context_id] = pending
        return apply_subs(complete) if complete else ""

    def flush(self, context_id: str = "ctx") -> str:
        """Simulate flush_audio() partial-word drain.

        Returns the (substituted) text that would be sent as a Speak message
        before the Flush command, or empty string if the buffer was empty.
        """
        partial = self._word_buffer.pop(context_id, "")
        return apply_subs(partial) if partial else ""

    def clear(self):
        """Simulate on_audio_context_interrupted() — clears all contexts."""
        self._word_buffer.clear()

    def pending(self, context_id: str = "ctx") -> str:
        return self._word_buffer.get(context_id, "")


# ===========================================================================
# 1. _apply_substitutions unit tests
# ===========================================================================


class TestApplySubstitutions:
    def test_washcloths_replaced(self):
        assert apply_subs("washcloths") == "wash cloths"

    def test_washcloth_singular_replaced(self):
        assert apply_subs("washcloth") == "wash cloth"

    def test_spelled_replaced(self):
        assert apply_subs("spelled") == "spelt"

    def test_case_insensitive_match(self):
        assert apply_subs("Washcloths") == "wash cloths"
        assert apply_subs("WASHCLOTHS") == "wash cloths"
        assert apply_subs("Spelled") == "spelt"

    def test_whole_word_only_washcloth(self):
        # "washcloths" inside a word must NOT match (but our dict keys are exact)
        # More importantly "washclothes" is NOT "washcloths"
        assert apply_subs("washclothes") == "washclothes"

    def test_no_match_leaves_text_unchanged(self):
        assert apply_subs("hello world") == "hello world"
        assert apply_subs("Please bring more towels.") == "Please bring more towels."

    def test_multiple_substitutions_in_one_string(self):
        assert apply_subs("I spelled washcloths wrong") == "I spelt wash cloths wrong"

    def test_washcloths_in_sentence(self):
        result = apply_subs("Please bring more washcloths to my room.")
        assert result == "Please bring more wash cloths to my room."

    def test_trailing_punctuation_does_not_block_match(self):
        assert apply_subs("washcloths.") == "wash cloths."
        assert apply_subs("washcloths,") == "wash cloths,"

    def test_operator_substitutions_merged(self):
        custom = {**_DEFAULT_SUBSTITUTIONS, "shampoo": "sham poo"}
        patterns = _make_patterns(custom)
        result = _apply_substitutions("Please bring shampoo.", patterns)
        assert result == "Please bring sham poo."


# ===========================================================================
# 2. WordBoundaryBuffer — TOKEN mode buffering
# ===========================================================================


class TestWordBoundaryBuffer:
    """Tests for the TOKEN-mode word-boundary accumulation logic."""

    # -----------------------------------------------------------------------
    # Basic accumulation
    # -----------------------------------------------------------------------

    def test_no_whitespace_all_buffered(self):
        buf = WordBoundaryBuffer()
        result = buf.feed("wash")
        assert result == "", "No whitespace yet → nothing sent"
        assert buf.pending() == "wash"

    def test_whitespace_releases_complete_word(self):
        buf = WordBoundaryBuffer()
        buf.feed("hello")
        result = buf.feed(" ")
        assert result == "hello ", "Space releases 'hello' + space"
        assert buf.pending() == ""

    def test_token_with_embedded_space_splits_correctly(self):
        buf = WordBoundaryBuffer()
        result = buf.feed("hello world")
        assert result == "hello "
        assert buf.pending() == "world"

    # -----------------------------------------------------------------------
    # washcloths split across tokens (the primary bug scenario)
    # -----------------------------------------------------------------------

    def test_washcloths_split_three_tokens_substituted(self):
        """'wash' + 'cloth' + 's ' should produce 'wash cloths '."""
        buf = WordBoundaryBuffer()
        r1 = buf.feed("wash")
        r2 = buf.feed("cloth")
        r3 = buf.feed("s ")
        assert r1 == ""
        assert r2 == ""
        assert r3 == "wash cloths ", (
            "Reassembled 'washcloths ' must be substituted to 'wash cloths '"
        )
        assert buf.pending() == ""

    def test_washcloths_two_tokens_substituted(self):
        """'washcloths' + ' ' should work even when the whole word arrives first."""
        buf = WordBoundaryBuffer()
        r1 = buf.feed("washcloths")
        r2 = buf.feed(" more")
        assert r1 == "", "No whitespace yet"
        # After ' more': pending was 'washcloths', new = 'washcloths more', last ws at 10
        assert r2 == "wash cloths ", (
            "'washcloths ' released and substituted when trailing ' more' arrives"
        )
        assert buf.pending() == "more"

    def test_washcloth_singular_two_tokens(self):
        buf = WordBoundaryBuffer()
        buf.feed("wash")
        result = buf.feed("cloth ")
        assert result == "wash cloth "

    def test_spelled_two_tokens(self):
        buf = WordBoundaryBuffer()
        buf.feed("spell")
        result = buf.feed("ed ")
        assert result == "spelt "

    # -----------------------------------------------------------------------
    # Trailing word flush (end of response)
    # -----------------------------------------------------------------------

    def test_trailing_word_flushed(self):
        """The last word of a response (no trailing space) must be sent at flush."""
        buf = WordBoundaryBuffer()
        buf.feed("bring ")
        buf.feed("washcloth")
        buf.feed("s")          # no trailing space — full word in buffer
        assert buf.pending() == "washcloths"
        flushed = buf.flush()
        assert flushed == "wash cloths", "flush() must substitute the trailing word"
        assert buf.pending() == ""

    def test_flush_empty_buffer_returns_empty(self):
        buf = WordBoundaryBuffer()
        assert buf.flush() == ""

    def test_flush_no_substitution_needed(self):
        buf = WordBoundaryBuffer()
        buf.feed("towel")
        flushed = buf.flush()
        assert flushed == "towel"

    def test_trailing_word_with_punctuation_flushed(self):
        """Trailing word ending in '.' must be substituted when flushed.

        In TOKEN mode, feed() emits the complete portion ("Please bring more ")
        and flush() emits only the trailing partial ("wash cloths.").  Together
        they form the full substituted utterance.
        """
        buf = WordBoundaryBuffer()
        emitted = buf.feed("Please bring more washcloths.")
        flushed = buf.flush()
        # complete portion emitted during run_tts, trailing word at flush_audio
        assert emitted == "Please bring more "
        assert flushed == "wash cloths."
        assert emitted + flushed == "Please bring more wash cloths."

    # -----------------------------------------------------------------------
    # Interruption
    # -----------------------------------------------------------------------

    def test_interruption_clears_buffer(self):
        buf = WordBoundaryBuffer()
        buf.feed("wash")
        buf.feed("cloth")
        assert buf.pending() != ""
        buf.clear()
        assert buf.pending() == "", "Buffer must be empty after interruption"

    def test_interruption_clears_multiple_contexts(self):
        buf = WordBoundaryBuffer()
        buf.feed("wash", "ctx1")
        buf.feed("hello", "ctx2")
        buf.clear()
        assert buf.pending("ctx1") == ""
        assert buf.pending("ctx2") == ""

    def test_no_stale_text_after_interruption_and_new_turn(self):
        """After interrupt + clear, new tokens for the same context_id start fresh."""
        buf = WordBoundaryBuffer()
        buf.feed("wash")
        buf.clear()
        result = buf.feed("hello ")
        assert result == "hello "
        assert "wash" not in result

    # -----------------------------------------------------------------------
    # Multiple context IDs
    # -----------------------------------------------------------------------

    def test_independent_context_ids(self):
        buf = WordBoundaryBuffer()
        buf.feed("wash", "ctx1")
        buf.feed("hello ", "ctx2")
        # ctx2 has whitespace → releases "hello "
        assert buf.pending("ctx1") == "wash"
        assert buf.pending("ctx2") == ""

    def test_flush_only_affects_specified_context(self):
        buf = WordBoundaryBuffer()
        buf.feed("washcloths", "ctx1")
        buf.feed("hello", "ctx2")
        flushed = buf.flush("ctx1")
        assert flushed == "wash cloths"
        assert buf.pending("ctx2") == "hello"   # ctx2 unaffected

    # -----------------------------------------------------------------------
    # Full-sentence simulation (sentence mode bypass sanity check)
    # -----------------------------------------------------------------------

    def test_sentence_mode_substitution_works_directly(self):
        """In SENTENCE mode we bypass buffering; apply_subs on a full sentence."""
        sentence = "Please bring more washcloths and a new washcloth."
        result = apply_subs(sentence)
        assert "washcloths" not in result
        assert "washcloth." not in result
        assert result == "Please bring more wash cloths and a new wash cloth."

    def test_multiple_substitutions_across_sentence(self):
        sentence = "She spelled washcloths incorrectly."
        assert apply_subs(sentence) == "She spelt wash cloths incorrectly."


# ===========================================================================
# 3. End-to-end token stream simulation
# ===========================================================================


class TestTokenStreamSimulation:
    """Simulate how pipecat feeds a stream of tokens to run_tts in TOKEN mode."""

    def _stream(self, tokens, ctx="ctx"):
        """Feed tokens through the buffer, collect all text emitted."""
        buf = WordBoundaryBuffer()
        emitted = []
        for tok in tokens:
            out = buf.feed(tok, ctx)
            if out:
                emitted.append(out)
        # flush at end of response
        tail = buf.flush(ctx)
        if tail:
            emitted.append(tail)
        return "".join(emitted)

    def test_washcloths_full_stream(self):
        tokens = ["Please ", "bring ", "more ", "wash", "cloth", "s", "."]
        result = self._stream(tokens)
        assert result == "Please bring more wash cloths."

    def test_washcloths_with_trailing_space_in_last_token(self):
        tokens = ["Please ", "bring ", "more ", "wash", "cloth", "s "]
        result = self._stream(tokens)
        assert result == "Please bring more wash cloths "

    def test_spelled_full_stream(self):
        tokens = ["She ", "spell", "ed", " it", " wrong", "."]
        result = self._stream(tokens)
        assert result == "She spelt it wrong."

    def test_no_substitution_needed_full_stream(self):
        tokens = ["Please ", "call ", "me ", "back."]
        result = self._stream(tokens)
        assert result == "Please call me back."

    def test_multiple_substitution_words_in_one_stream(self):
        tokens = ["I ", "spell", "ed ", "wash", "cloth", "s ", "wrong."]
        result = self._stream(tokens)
        assert result == "I spelt wash cloths wrong."
