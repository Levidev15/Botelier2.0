"""Pure, bounded node input validation and configured output rendering.

These functions receive copied flow facts, not sessions, credentials or clients.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import html
import json
import math
import re

import regex

from botelier.validators import SlotValidators
from botelier.voice.flows.native_expression import ExpressionError, evaluate_expression


_TOKEN = re.compile(r"{{\s*([A-Za-z][A-Za-z0-9_]*)\s*}}")
_NAME_FIELDS = ("name", "title", "label", "rate_plan_name", "room_name", "room_type_name", "plan_name", "description")
_NUMBER_WORDS = dict(zip(("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"), range(11)))


class NativeValueError(ValueError):
    """Stable failure category without caller/provider values."""


def _number(value, code="slot_number"):
    if type(value) is bool or not isinstance(value, (str, int, float, Decimal)):
        raise NativeValueError(code)
    try:
        number = Decimal(str(value).strip())
        if not number.is_finite() or abs(number) > Decimal("1e100"):
            raise NativeValueError(code)
        return number
    except (InvalidOperation, ValueError):
        raise NativeValueError(code) from None


def normalize_date_value(raw, today, built_in, future):
    """Parse configured date formats without applying range/cross-field policy."""
    if built_in:
        raw = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", raw, flags=re.I)
        relative = {"today": 0, "tonight": 0, "tomorrow": 1, "next week": 7}
        if raw.casefold() in relative:
            return today + timedelta(days=relative[raw.casefold()])
    formats = ("%Y-%m-%d",)
    if built_in:
        formats += ("%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y")
    for format_string in formats:
        try:
            return datetime.strptime(raw, format_string).date()
        except ValueError:
            continue
    if built_in:
        stripped = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", raw, flags=re.I)
        for format_string in ("%B %d", "%b %d", "%d %B", "%d %b"):
            try:
                parsed = datetime.strptime(f"{stripped} {today.year}", f"{format_string} %Y").date()
                if future and parsed < today:
                    parsed = parsed.replace(year=today.year + 1)
                return parsed
            except ValueError:
                continue
    raise NativeValueError("slot_date")


def validate_value(slot, value, facts, *, today=None):
    """Normalize one caller answer and enforce all configured constraints."""
    today = today or date.today()
    kind = slot.get("type", "text")
    constraints = slot.get("validation") or {}
    built_in = slot.get("useBuiltInValidator", True)
    pattern = constraints.get("pattern")
    if pattern is not None and (not isinstance(pattern, str) or len(pattern) > 512):
        raise NativeValueError("slot_pattern")
    if kind == "number":
        if built_in and isinstance(value, str):
            value = _NUMBER_WORDS.get(value.strip().casefold(), value)
        number = _number(value)
        if not constraints.get("allowDecimal", False) and number != number.to_integral_value():
            raise NativeValueError("slot_number_integer")
        if "min" in constraints and number < _number(constraints["min"]):
            raise NativeValueError("slot_min")
        if "max" in constraints and number > _number(constraints["max"]):
            raise NativeValueError("slot_max")
        result = int(number) if number == number.to_integral_value() else float(number)
    else:
        if not isinstance(value, str) or not value.strip() or len(value) > 8000:
            raise NativeValueError("slot_text")
        result = value.strip()
        if any(ord(character) < 32 and character not in "\t\n" for character in result):
            raise NativeValueError("slot_characters")
        if kind in {"email", "phone"} and any(character in result for character in "\r\n\t"):
            raise NativeValueError("slot_contact")
        if kind == "date":
            future = constraints.get("requireFuture", constraints.get("require_future", True))
            parsed = normalize_date_value(result, today, built_in, future)
            if future and parsed < today:
                raise NativeValueError("slot_date_future")
            if "minDaysAhead" in constraints and parsed < today + timedelta(days=constraints["minDaysAhead"]):
                raise NativeValueError("slot_date_min")
            maximum_days = constraints.get("maxDaysAhead", 365 if built_in else None)
            if maximum_days is not None and parsed > today + timedelta(days=maximum_days):
                raise NativeValueError("slot_date_max")
            result = parsed.isoformat()
        elif kind in {"email", "phone", "time"} and built_in:
            if kind == "phone" and not re.fullmatch(r"\+?[0-9 () .-]{7,32}", result):
                raise NativeValueError("slot_phone")
            if kind == "time":
                hour_match = re.match(r"^(\d{1,2})(?::\d{2})?\s*(am|pm)$", result, re.I)
                if hour_match and not 1 <= int(hour_match[1]) <= 12:
                    raise NativeValueError("slot_time")
            checked = getattr(SlotValidators, f"validate_{kind}")(result)
            if not checked.is_valid:
                raise NativeValueError(f"slot_{kind}")
            result = checked.normalized_value
        elif kind == "choice":
            choices = constraints.get("choices", slot.get("choices", []))
            exact = [choice for choice in choices if choice.casefold() == result.casefold()]
            matches = exact or [choice for choice in choices if result.casefold() in choice.casefold()]
            if len(matches) != 1:
                raise NativeValueError("slot_choice")
            result = matches[0]
        elif kind not in {"text", "phone", "email", "time"}:
            raise NativeValueError("slot_type")
    if isinstance(result, str):
        default_maximum = 500 if kind == "text" and built_in else 8000
        if not constraints.get("minLength", 1) <= len(result) <= constraints.get("maxLength", default_maximum):
            raise NativeValueError("slot_length")
        if pattern:
            try:
                if not regex.fullmatch(pattern, result, timeout=0.02):
                    raise NativeValueError("slot_pattern")
            except (regex.error, TimeoutError):
                raise NativeValueError("slot_pattern") from None
    cross = constraints.get("crossFieldCheck") or constraints.get("cross_field_check") or {}
    compare_with = cross.get("compareWith") or cross.get("compare_with") or constraints.get("afterDateVariable") or constraints.get("after_date_variable")
    if compare_with:
        if compare_with not in facts or facts[compare_with] is None:
            raise NativeValueError("slot_cross_field")
        try:
            actual, expected = result, facts[compare_with]
            if kind == "date":
                actual, expected = date.fromisoformat(result), date.fromisoformat(expected)
            elif kind == "number":
                actual, expected = _number(result), _number(expected)
            direction = cross.get("operator", "after")
            if direction not in {"after", "before", "greater", "less"}:
                raise NativeValueError("slot_cross_field")
            valid = actual > expected if direction in {"after", "greater"} else actual < expected
            if not valid:
                raise NativeValueError("slot_cross_field")
        except (TypeError, ValueError):
            raise NativeValueError("slot_cross_field") from None
    return result


def _plain_text(text):
    return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", text)).split())


def _spoken(value):
    if value is None:
        raise NativeValueError("template_missing")
    if isinstance(value, dict):
        for key in _NAME_FIELDS:
            if isinstance(value.get(key), str) and value[key].strip():
                return _plain_text(value[key])
        raise NativeValueError("template_structured")
    if isinstance(value, list):
        if len(value) > 50:
            raise NativeValueError("template_size")
        items = [_spoken(item) for item in value]
        return " and ".join(items) if len(items) < 3 else ", ".join(items[:-1]) + " and " + items[-1]
    if isinstance(value, str):
        return _plain_text(value)
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int and value.bit_length() <= 1024:
        return str(value)
    if type(value) is float and math.isfinite(value):
        return str(value)
    if isinstance(value, Decimal) and value.is_finite() and abs(value) <= Decimal("1e100"):
        return str(value)
    raise NativeValueError("template_type")


def render_text(template, facts, *, speech=True):
    """Render explicitly named fields; missing values never reach TTS as tokens."""
    if not isinstance(template, str) or len(template) > 8000:
        raise NativeValueError("template_size")
    residual = _TOKEN.sub("", template)
    if "{{" in residual or "}}" in residual:
        raise NativeValueError("template_syntax")

    def replace(match):
        key = match[1]
        if key not in facts or facts[key] is None:
            raise NativeValueError("template_missing")
        value = facts[key]
        if speech:
            return _spoken(value)
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError):
            raise NativeValueError("template_type") from None

    result = _TOKEN.sub(replace, template).strip()
    if len(result) > 8000:
        raise NativeValueError("template_size")
    return result


def evaluate_value(configuration, facts):
    mode, value = configuration.get("valueType", "static"), configuration.get("value", "")
    if mode == "static":
        return deepcopy(value)
    if mode == "template":
        return render_text(value, facts, speech=False)
    if mode == "expression":
        try:
            return evaluate_expression(value, facts)
        except ExpressionError as error:
            raise NativeValueError(str(error)) from None
    raise NativeValueError("expression_mode")


def evaluate_condition(configuration, facts):
    actual = facts.get(configuration.get("variable"))
    expected = configuration.get("value", "")
    if isinstance(expected, str):
        expected = render_text(expected, facts, speech=False)
    operation = configuration.get("operator", "equals")
    empty = actual is None or actual == "" or isinstance(actual, (dict, list)) and not actual or isinstance(actual, str) and actual.strip().casefold() in {"", "[]", "{}", "null", "none"}
    if operation in {"is_empty", "is_not_empty"}:
        return empty if operation == "is_empty" else not empty
    if operation in {"greater_than", "less_than"}:
        try:
            left, right = _number(actual), _number(expected)
        except NativeValueError:
            left, right = str(actual or "").strip(), str(expected or "").strip()
        return left > right if operation == "greater_than" else left < right
    left = str(actual if actual is not None else "").strip().casefold()
    right = str(expected if expected is not None else "").strip().casefold()
    if operation == "equals":
        return left == right
    if operation == "not_equals":
        return left != right
    if operation == "contains":
        return right in left
    raise NativeValueError("condition_operator")


def get_path(value, path):
    for part in path.split(".") if path else ():
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def _array(value, code):
    if isinstance(value, str) and len(value) <= 100_000:
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            raise NativeValueError(code) from None
    if not isinstance(value, list) or len(value) > 50:
        raise NativeValueError(code)
    return value


@dataclass(frozen=True)
class SelectedOption:
    index: int
    label: str
    writes: dict


def resolve_option(configuration, facts, arguments):
    if not isinstance(arguments, dict) or not arguments or set(arguments) - {"ordinal", "label"}:
        raise NativeValueError("selection_arguments")
    items = _array(facts.get(configuration["sourceVariable"]), "selection_source")
    ordinal = arguments.get("ordinal")
    selected_index = None
    if ordinal is not None:
        if type(ordinal) is not int or not 1 <= ordinal <= len(items):
            raise NativeValueError("selection_ordinal")
        selected_index = ordinal - 1
    label = arguments.get("label")
    if label is not None:
        if not isinstance(label, str) or not label.strip() or len(label) > 2048:
            raise NativeValueError("selection_label")
        needle = label.strip().casefold()
        labels = [get_path(item, configuration.get("labelPath", "")) for item in items]
        exact = [index for index, item in enumerate(labels) if isinstance(item, str) and item.strip().casefold() == needle]
        matches = exact or [index for index, item in enumerate(labels) if isinstance(item, str) and needle in item.casefold()]
        if len(matches) != 1 or selected_index is not None and matches[0] != selected_index:
            raise NativeValueError("selection_ambiguous")
        selected_index = matches[0]
    if selected_index is None:
        raise NativeValueError("selection_arguments")
    item = items[selected_index]
    label = get_path(item, configuration.get("labelPath", ""))
    if not isinstance(label, str) or not label.strip():
        raise NativeValueError("selection_label")
    writes = {entry["variableKey"]: deepcopy(get_path(item, entry["path"])) for entry in configuration["writes"]}
    return SelectedOption(selected_index, _plain_text(label), writes)


def present_response(configuration, facts):
    try:
        variable = configuration.get("arrayVariable")
        parts = [render_text(configuration.get("introText", ""), facts)]
        if variable:
            items = _array(facts.get(variable), "presentation_source")
            if not items:
                return render_text(configuration.get("noResultsText", "No results were found."), facts), False
            for index, item in enumerate(items, 1):
                scoped = {**facts, **(item if isinstance(item, dict) else {"item": item}), "index": index}
                template = configuration.get("itemTemplate")
                parts.append(render_text(template, scoped) if template else _spoken(item))
        parts.append(render_text(configuration.get("outroText", ""), facts))
        text = " ".join(part for part in parts if part)
        if len(text) > 8000:
            raise NativeValueError("presentation_size")
        return text, True
    except NativeValueError as error:
        if str(error).startswith("presentation_"):
            raise
        raise NativeValueError("presentation_value") from None
