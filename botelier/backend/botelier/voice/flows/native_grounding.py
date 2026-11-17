"""Bounded caller evidence for the native validator's supported scalar formats."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from itertools import islice

from num2words import num2words

from botelier.voice.flows.native_values import NativeValueError, normalize_date_value, validate_value


_MONTH = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
_DATE = re.compile(
    rf"\b(?:[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}|"
    rf"[0-9]{{1,2}}[/-][0-9]{{1,2}}[/-][0-9]{{4}}|"
    rf"(?:{_MONTH})\s+[0-9]{{1,2}}(?:st|nd|rd|th)?"
    rf"(?:(?:,\s*|\s+)[0-9]{{4}})?(?![\s,]+[0-9])|"
    rf"[0-9]{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH})"
    rf"(?:\s+[0-9]{{4}})?(?![\s,]+[0-9])|"
    r"today|tonight|tomorrow|next\s+week)\b", re.I,
)
_DIGITS = re.compile(
    r"(?<![\w.,+-])(?:(?:minus|negative|plus|positive)\s+)?[+-]?"
    r"(?:[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
    r"(?:e[+-]?[0-9]+)?(?!\w|[.,][0-9])", re.I,
)
_NUMBER_VOCABULARY = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy "
    "eighty ninety hundred thousand million billion trillion quadrillion quintillion "
    "point minus negative plus positive"
).split()
_NUMBER_ATOM = "|".join(sorted(_NUMBER_VOCABULARY, key=len, reverse=True))
_SPOKEN_NUMBER = re.compile(
    rf"\b(?:{_NUMBER_ATOM})(?:[\s-]+(?:{_NUMBER_ATOM}|and))*\b", re.I,
)
_EMPTY_COUNT = re.compile(
    r"^(?:none|no(?:\s+(?:children|kids|infants|adults|guests|rooms|people|persons))?)[.!?]?$", re.I,
)
_PHONE = re.compile(r"(?<![\w+])\+?[0-9(][0-9 () .-]{5,30}[0-9](?!\w)")
_TIME = re.compile(r"(?<!\w)(?:[0-9]{1,2}:[0-9]{2}\s*(?:am|pm)?|[0-9]{1,2}\s*(?:am|pm))(?!\w)", re.I)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}\b", re.I)
_NEGATED_CHOICE = re.compile(
    r"\b(?:not|no|never|cannot|except|without|\w+n['’]t|anything\s+but|rather\s+than)\b", re.I,
)
_ALTERNATIVE = re.compile(r"\bor\b", re.I)
_TRAILING_REJECTION = re.compile(
    r"^\s*(?:(?:adults?|children|kids?|infants?|guests?|rooms?|people|persons?|date|time|number|option)\s+)?"
    r"(?:\w+n['’]t\b|cannot\b|(?:is|are|was|were)\s+(?:not|wrong|incorrect|unacceptable)\b)",
    re.I,
)


def _negated_at(caller, start, end):
    clause = re.split(r"[.!?;,]|\bbut\b", caller[:start], flags=re.I)[-1]
    return bool(
        _NEGATED_CHOICE.search(clause)
        or _TRAILING_REJECTION.search(caller[end:end + 128])
    )


def _literal(caller, response, *, affirmative=False):
    left, right = " ".join(caller.casefold().split()), " ".join(str(response).casefold().split())
    if left == right:
        return True
    return bool(right) and any(
        not affirmative or not _negated_at(left, match.start(), match.end())
        for match in islice(re.finditer(rf"(?<!\w){re.escape(right)}(?!\w)", left), 8)
    )


def _number(value):
    if type(value) is bool:
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and abs(number) <= Decimal("1e100") else None
    except (InvalidOperation, ValueError):
        return None


def _number_words(text):
    words = re.sub(r"[-\s]+", " ", text.casefold()).split()
    words = ["minus" if word == "negative" else word for word in words if word != "and"]
    if words and words[0] in {"plus", "positive"}:
        words.pop(0)
    return " ".join(words)


def _numeric_evidence(caller):
    """Do not turn dates, times or clearly formatted contacts into counts."""
    masked = list(caller)
    for pattern in (_DATE, _TIME, _EMAIL, _PHONE):
        matches = list(islice(pattern.finditer(caller), 9))
        if len(matches) > 8:
            return None
        for match in matches:
            if pattern is _PHONE:
                try:
                    validate_value({"type": "phone"}, match.group(), {})
                except NativeValueError:
                    continue
            if pattern is _PHONE and not (
                re.search(r"[+().-]", match.group())
                or re.search(r"\b(?:phone|mobile|cell|sms|text)\b", caller[max(0, match.start() - 24):match.start()], re.I)
            ):
                continue
            masked[match.start():match.end()] = " " * (match.end() - match.start())
    return "".join(masked)


def _grounded_number(caller, proposed, *, built_in):
    target = _number(proposed)
    if target is None:
        return False
    source = _numeric_evidence(caller)
    if source is None:
        return False
    digits = list(islice(_DIGITS.finditer(source), 9))
    words = list(islice(_SPOKEN_NUMBER.finditer(source), 9))
    if len(digits) > 8 or len(words) > 8 or (
        _ALTERNATIVE.search(source) and len(digits) + len(words) > 1
    ):
        return False
    for match in digits:
        token = re.sub(r"^(?:minus|negative)\s+", "-", match.group(), flags=re.I)
        token = re.sub(r"^(?:plus|positive)\s+", "+", token, flags=re.I).replace(",", "")
        if _number(token) == target and not _negated_at(source, match.start(), match.end()):
            return True
    if not built_in:
        return False
    if target == 0 and _EMPTY_COUNT.fullmatch(caller.strip()):
        return True
    if not words:
        return False
    try:
        expected = _number_words(num2words(target, lang="en"))
    except (ValueError, OverflowError, TypeError):
        return False
    return any(
        len(match.group()) <= 192 and _number_words(match.group()) == expected
        and not _negated_at(source, match.start(), match.end())
        for match in words
    )


def _choice_evidence(caller, target, probe):
    choices = probe["choices"]
    exact = [value for value in choices if caller.strip().casefold() == value.casefold()]
    if exact:
        return len(exact) == 1 and exact[0] == target
    if _NEGATED_CHOICE.search(caller):
        return False
    evidence = {value for value in choices if _literal(caller, value)}
    try:
        evidence.add(validate_value(probe, caller, {}))
    except NativeValueError:
        pass
    return len(evidence) == 1 and target in evidence


def caller_value_is_grounded(slot, caller, proposed, *, today=None):
    """Compare evidence only; actual configured constraints still run afterward.

    No language model, I/O, fact writes, financial calculation or permissive
    value coercion occurs here. Long and unrecognized formats fail closed.
    """
    if not isinstance(caller, str) or not caller.strip() or len(caller) > 8000:
        return False
    kind = slot.get("type", "text")
    if kind == "number":
        return _grounded_number(
            caller, proposed, built_in=slot.get("useBuiltInValidator", True),
        )
    if kind == "choice" and not slot.get("useBuiltInValidator", True):
        return caller.strip().casefold() == str(proposed).casefold()
    date_matches = list(islice(_DATE.finditer(caller), 9)) if kind == "date" else []
    if len(date_matches) > 8 or (
        len(date_matches) > 1 and _ALTERNATIVE.search(caller)
    ):
        return False
    if kind != "choice" and _literal(
        caller, proposed, affirmative=kind in {"date", "phone", "email", "time"},
    ):
        return True
    if not slot.get("useBuiltInValidator", True) or kind not in {"date", "phone", "time", "email", "choice"}:
        return False
    probe = {
        "type": kind, "useBuiltInValidator": True,
        "validation": {"requireFuture": False, "maxDaysAhead": None},
        "choices": slot.get("choices", (slot.get("validation") or {}).get("choices", [])),
    }
    try:
        target = validate_value(probe, proposed, {}, today=today)
    except NativeValueError:
        return False
    if kind == "choice":
        return _choice_evidence(caller, target, probe)
    if kind == "date":
        constraints = slot.get("validation") or {}
        future = constraints.get("requireFuture", constraints.get("require_future", True))
        try:
            target = normalize_date_value(proposed, today or date.today(), True, future).isoformat()
        except NativeValueError:
            return False
    candidates = [(caller.strip(), 0, len(caller))]
    pattern = {"date": _DATE, "phone": _PHONE, "time": _TIME}.get(kind)
    if pattern is not None:
        matches = date_matches if kind == "date" else islice(pattern.finditer(caller), 8)
        candidates.extend((match.group().strip(), match.start(), match.end()) for match in matches)
    for candidate, start, end in candidates:
        if _negated_at(caller, start, end):
            continue
        try:
            normalized = (
                normalize_date_value(candidate, today or date.today(), True, future).isoformat()
                if kind == "date" else validate_value(probe, candidate, {}, today=today)
            )
            if normalized == target:
                return True
        except NativeValueError:
            continue
    return False
