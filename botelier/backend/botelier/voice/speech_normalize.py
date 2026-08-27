"""Text normalization for TTS so numbers/ordinals/currency are spoken naturally.

Task #547 — on live calls the TTS provider read "3000" as "thirty-zero-zero",
"3rd" as "third-R-D" and "5th" as "fifth-tee-H", and spelled out "EUR".
These helpers expand such tokens to words BEFORE the text reaches the
synthesizer.

IMPORTANT: callers must only pass whitespace-complete text (whole words).
In TOKEN aggregation mode the TTS wrapper buffers sub-word fragments to
whitespace boundaries before applying any substitution (see engine.py
`_BotelierDeepgramTTSService`); this module relies on that guarantee — a
regex applied to a sub-word fragment would silently no-op or corrupt words.
"""

import re

_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]
_TENS = [
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety",
]

# Ordinal word forms for the irregular ones; regular ones derive from cardinal.
_ORDINAL_IRREGULAR = {
    "one": "first", "two": "second", "three": "third", "five": "fifth",
    "eight": "eighth", "nine": "ninth", "twelve": "twelfth",
}

_CURRENCY_WORDS = {
    "EUR": "euros",
    "USD": "dollars",
    "GBP": "pounds",
    "CHF": "Swiss francs",
    "JPY": "yen",
    "AUD": "Australian dollars",
    "CAD": "Canadian dollars",
}


def _under_thousand(n: int) -> str:
    parts: list[str] = []
    if n >= 100:
        parts.append(_ONES[n // 100] + " hundred")
        n %= 100
    if n >= 20:
        if n % 10:
            parts.append(_TENS[n // 10] + "-" + _ONES[n % 10])
        else:
            parts.append(_TENS[n // 10])
    elif n > 0:
        parts.append(_ONES[n])
    return " ".join(parts)


def number_to_words(n: int) -> str:
    """Cardinal words for 0 <= n <= 999,999,999."""
    if n == 0:
        return "zero"
    parts: list[str] = []
    millions, rest = divmod(n, 1_000_000)
    thousands, units = divmod(rest, 1000)
    if millions:
        parts.append(_under_thousand(millions) + " million")
    if thousands:
        parts.append(_under_thousand(thousands) + " thousand")
    if units:
        parts.append(_under_thousand(units))
    return " ".join(parts)


def ordinal_to_words(n: int) -> str:
    """Ordinal words for 1 <= n <= 9999 ("3" -> "third", "21" -> "twenty-first")."""
    cardinal = number_to_words(n)
    head, sep, last = cardinal.rpartition("-")
    if not sep:
        head, sep, last = cardinal.rpartition(" ")
    if last in _ORDINAL_IRREGULAR:
        last_ord = _ORDINAL_IRREGULAR[last]
    elif last.endswith("y"):
        last_ord = last[:-1] + "ieth"
    elif last.endswith("t"):  # e.g. "eight" handled above; "hundred"/"thousand" no
        last_ord = last + "h"
    else:
        last_ord = last + "th"
    return head + sep + last_ord if sep else last_ord


# "3rd", "21st", "5th" — whole token only (never inside a larger word).
_ORDINAL_RE = re.compile(r"\b(\d{1,4})(st|nd|rd|th)\b", re.IGNORECASE)
# "3,000" / "1,250,000" — comma-grouped integers.
_COMMA_INT_RE = re.compile(r"\b\d{1,3}(?:,\d{3})+\b(?!\.\d)")
# "320.50" — decimal amounts (spoken as "... point five zero").
_DECIMAL_RE = re.compile(r"\b(\d{1,6})\.(\d{1,2})\b(?!\d)")
# Plain integers of 3-6 digits with no leading zero, not part of a longer
# digit/date/time/code sequence. 1-2 digit numbers are left alone (providers
# read them fine) and 7+ digits are likely phone/confirmation numbers where
# digit-by-digit reading is correct.
_PLAIN_INT_RE = re.compile(r"(?<![\d.,:/\-])([1-9]\d{2,5})(?![\d.,:/\-])")
_CURRENCY_RE = re.compile(r"\b(" + "|".join(_CURRENCY_WORDS) + r")\b")


# Words that mark the preceding context as an identifier ("confirmation
# number is 123456", "booking reference 4821", "code 9315"): such digit
# strings are the identifier itself and must stay digits so the caller can
# write them down exactly as spoken.
_IDENTIFIER_CONTEXT_RE = re.compile(
    r"\b(number|no\.?|#|code|pin|reference|ref|confirmation|booking|"
    r"reservation|id|extension|ext\.?|flight|order|ticket|account|zip|postal)\b"
    r"(?:\s+\w+){0,2}\W*$",
    re.IGNORECASE,
)

_MAX_WORDS_NUMBER = 999_999_999


def _is_identifier_context(text: str, start: int) -> bool:
    return bool(_IDENTIFIER_CONTEXT_RE.search(text[max(0, start - 40) : start]))


def normalize_for_speech(text: str) -> str:
    """Expand ordinals, comma-grouped/plain integers, decimals, and ISO
    currency codes into spoken words. Input must be whitespace-complete text.

    Never raises: any value outside the supported range (or in an
    identifier context such as "confirmation number is 123456") is left
    exactly as written so synthesis is never interrupted.
    """
    if not text or not any(ch.isdigit() or ch.isupper() for ch in text):
        return text

    def _ordinal(m: re.Match) -> str:
        return ordinal_to_words(int(m.group(1)))

    def _comma_int(m: re.Match) -> str:
        n = int(m.group(0).replace(",", ""))
        if n > _MAX_WORDS_NUMBER or _is_identifier_context(text, m.start()):
            return m.group(0)
        return number_to_words(n)

    def _decimal(m: re.Match) -> str:
        n = int(m.group(1))
        if n > _MAX_WORDS_NUMBER:
            return m.group(0)
        whole = number_to_words(n)
        frac = m.group(2)
        if frac.strip("0") == "":
            return whole  # "320.00" -> "three hundred twenty"
        return whole + " point " + " ".join(_ONES[int(d)] for d in frac)

    def _plain_int(m: re.Match) -> str:
        if _is_identifier_context(text, m.start(1)):
            return m.group(1)
        return number_to_words(int(m.group(1)))

    def _currency(m: re.Match) -> str:
        return _CURRENCY_WORDS[m.group(1)]

    text = _ORDINAL_RE.sub(_ordinal, text)
    text = _COMMA_INT_RE.sub(_comma_int, text)
    text = _DECIMAL_RE.sub(_decimal, text)
    text = _PLAIN_INT_RE.sub(_plain_int, text)
    text = _CURRENCY_RE.sub(_currency, text)
    return text
