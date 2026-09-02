"""Tests for spelled-out letter sequence normalisation in speech_normalize.py.

Deepgram Flux (and other neural TTS providers) mispronounce hyphen-separated
single-letter sequences: "C-O-R-E-Y" is spoken as "C-O-R-E-E-Y" (the E is
doubled). The fix converts such sequences to period-separated form before
the text reaches the synthesiser, e.g. "C-O-R-E-Y" → "C. O. R. E. Y."

These tests verify:
  - Single spelled-letter sequences are expanded correctly.
  - Email-style spelled sequences are handled (c-n-o-m-m-a-e-a).
  - Compound words that look similar are NOT altered (twenty-one, e-mail, a-ok).
  - Mixed sentences expand only the spelled portion.
  - The expansion is applied before numeric normalisation so hyphens in
    number-words ("twenty-one") are never affected.
  - All-lowercase and mixed-case sequences are handled.
"""

import pytest

from botelier.voice.speech_normalize import normalize_for_speech


@pytest.mark.parametrize(
    "raw, expected",
    [
        # ---- basic spelled-name cases ----
        ("C-O-R-E-Y", "C. O. R. E. Y."),
        ("M-A-N-A", "M. A. N. A."),
        ("c-o-r-e-y", "c. o. r. e. y."),
        # ---- two-letter sequence ----
        ("A-B", "A. B."),
        # ---- email spelled out ----
        ("c-n-o-m-m-a-e-a", "c. n. o. m. m. a. e. a."),
        # ---- inside a sentence ----
        (
            "Your name is spelled C-O-R-E-Y, correct?",
            "Your name is spelled C. O. R. E. Y., correct?",
        ),
        (
            "First name T-O-R-E-Y, last name M-A-N-A.",
            "First name T. O. R. E. Y., last name M. A. N. A..",
        ),
        # ---- NOT altered: compound words with multi-char segments ----
        ("twenty-one", "twenty-one"),
        ("e-mail", "e-mail"),
        ("a-ok", "a-ok"),
        ("t-shirt", "t-shirt"),
        ("x-ray", "x-ray"),
        ("check-in", "check-in"),
        ("check-out", "check-out"),
        # ---- NOT altered: standalone single letter (no hyphen) ----
        ("A", "A"),
        # ---- empty / no change ----
        ("", ""),
        ("Hello world", "Hello world"),
    ],
)
def test_spelled_letters_normalised(raw: str, expected: str):
    assert normalize_for_speech(raw) == expected


def test_spelled_letters_coexist_with_other_normalisation():
    """Spelled-letter expansion does not break other normalisation passes.

    The two things this test proves:
    1.  A spelled-letter sequence in the same string is expanded.
    2.  Compound words with multi-char segments (twenty-one, e-mail, t-shirt)
        are never touched by the spelled-letter pass.
    """
    # Compound words must survive unchanged alongside a spelled-letter sequence.
    result = normalize_for_speech("twenty-one C-O-R-E-Y")
    assert "twenty-one" in result
    assert "C. O. R. E. Y." in result

    # Currency token (space-separated) is still expanded normally.
    result_currency = normalize_for_speech("Charge 200 EUR please.")
    assert "euros" in result_currency

    # The spelled-letter expansion must not corrupt numeric tokens that
    # happen to be adjacent in the same string.
    result_num = normalize_for_speech("Guest A-L-I stays 3 nights.")
    assert "A. L. I." in result_num
    # "3" is a small standalone digit; verify it is not corrupted.
    assert "3" in result_num or "three" in result_num
