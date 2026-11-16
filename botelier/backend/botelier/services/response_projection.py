"""Build explicit JSON and legacy readable projections of mapped API values.

The mapping layer deliberately preserves API-shaped values for flow variables.
The native JSON boundary uses an operator allowlist and explicit cleanup only.
The legacy display formatter joins parallel arrays without changing action facts.
"""

from __future__ import annotations

import html
from html.parser import HTMLParser
import json
import re
from typing import Any, Mapping


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_PROJECTION_VARIABLE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,47}\Z")
_CLEANUP_OPERATIONS = frozenset({"trim", "collapse_whitespace", "clean_text"})


class ResponseProjectionError(ValueError):
    """Safe, payload-free diagnostic for an invalid LLM data projection."""


class _ProjectionTextParser(HTMLParser):
    """Extract display text without executing or loading provider markup."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)


def _projection_text(value: str) -> str:
    parser = _ProjectionTextParser()
    try:
        parser.feed(value)
        parser.close()
    except (AssertionError, ValueError):
        raise ResponseProjectionError("projection_cleanup_value") from None
    return " ".join(" ".join(parser.parts).split())


def validate_mapped_projection(configuration: Any, available_variables) -> None:
    """Validate a non-executable field allowlist against actual mapping names."""
    if configuration is None:
        return
    if not isinstance(configuration, dict) or set(configuration) != {"fields"}:
        raise ResponseProjectionError("projection_configuration")
    fields = configuration["fields"]
    if not isinstance(fields, list) or len(fields) > 64:
        raise ResponseProjectionError("projection_configuration")
    seen = set()
    for field in fields:
        if not isinstance(field, dict) or not set(field) <= {"variable", "cleanup"}:
            raise ResponseProjectionError("projection_configuration")
        variable = field.get("variable")
        if (
            not isinstance(variable, str) or not _PROJECTION_VARIABLE_RE.fullmatch(variable)
            or variable in seen
        ):
            raise ResponseProjectionError("projection_variable")
        if variable not in available_variables:
            raise ResponseProjectionError("projection_missing_variable")
        seen.add(variable)
        cleanup = field.get("cleanup", [])
        if (
            not isinstance(cleanup, list) or len(cleanup) > 3
            or any(not isinstance(op, str) or op not in _CLEANUP_OPERATIONS for op in cleanup)
        ):
            raise ResponseProjectionError("projection_cleanup")


def project_mapped_values(
    values: Mapping[str, Any], configuration: Any = None,
) -> dict[str, Any]:
    """Return the exact configured JSON payload without changing action facts.

    No implicit array joining, financial calculations, string conversion or
    truncation occurs here. The older human-readable formatter below retains
    its existing behavior for legacy consumers. ``clean_text`` is display
    cleanup, not an HTML-output sanitizer or a prompt-injection trust boundary.
    """
    if not isinstance(values, Mapping):
        raise ResponseProjectionError("projection_json")
    validate_mapped_projection(configuration, values.keys())
    if configuration is None:
        return _bounded_projection_copy(dict(values))
    projected = {
        field["variable"]: values[field["variable"]]
        for field in configuration["fields"]
    }
    # Bound selected provider data before any cleanup or parsing. Reject rather
    # than silently truncate; authoritative action facts are never rewritten.
    projected = _bounded_projection_copy(projected)
    for field in configuration["fields"]:
        variable = field["variable"]
        value = projected[variable]
        for operation in field.get("cleanup", []):
            if not isinstance(value, str):
                raise ResponseProjectionError("projection_cleanup_type")
            if operation == "trim":
                value = value.strip()
            elif operation == "collapse_whitespace":
                value = re.sub(r"\s+", " ", value)
            elif operation == "clean_text":
                value = _projection_text(value)
        projected[variable] = value
    return _bounded_projection_copy(projected)


def _bounded_projection_copy(projected: dict[str, Any]) -> dict[str, Any]:
    """Validate size and depth and return an independent, exact JSON value."""
    try:
        encoded = json.dumps(projected, allow_nan=False, ensure_ascii=False)
        size = len(encoded.encode("utf-8"))
    except (TypeError, ValueError, RecursionError):
        raise ResponseProjectionError("projection_json") from None
    if size > 100_000:
        raise ResponseProjectionError("projection_size")
    pending = [(projected, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > 32:
            raise ResponseProjectionError("projection_depth")
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ResponseProjectionError("projection_json")
            pending.extend((nested, depth + 1) for nested in value.values())
        elif isinstance(value, list):
            pending.extend((nested, depth + 1) for nested in value)
    return json.loads(encoded)


def format_mapped_response(values: Mapping[str, Any]) -> str:
    """Return a concise, readable display projection of mapped API values.

    Top-level lists are treated as related parallel arrays.  The longest list
    determines the number of records, so a partially populated test response
    still shows every available item.  Nested values remain attached to the
    matching record and scalar values are rendered as shared data.
    """
    if not values:
        return ""

    arrays = [(key, value) for key, value in values.items() if isinstance(value, list)]
    scalars = [(key, value) for key, value in values.items() if not isinstance(value, list)]
    sections: list[str] = []

    if arrays:
        max_items = max(len(value) for _, value in arrays)
        if len(arrays) == 1:
            key, items = arrays[0]
            lines = [_label(key) + ":"]
            lines.extend(_format_list_items(items, indent=3))
            if len(lines) > 1:
                sections.append("\n".join(lines))
        else:
            records: list[str] = []
            for index in range(max_items):
                fields: list[str] = []
                for key, items in arrays:
                    if index < len(items):
                        fields.extend(
                            _format_field_lines(
                                _label(key),
                                items[index],
                                indent=3,
                            )
                        )
                if fields:
                    records.append("\n".join([f"{index + 1}.", *fields]))
            if records:
                sections.append("Results:\n\n" + "\n\n".join(records))

    if scalars:
        scalar_lines: list[str] = []
        for key, value in scalars:
            scalar_lines.extend(
                _format_field_lines(_label(key), value, indent=3 if arrays else 0)
            )
        if scalar_lines:
            prefix = "Shared data:\n" if arrays else ""
            sections.append(prefix + "\n".join(scalar_lines))

    return "\n\n".join(section for section in sections if section).strip()


def _label(key: Any) -> str:
    """Make an API-style field name readable without changing its identity."""
    return re.sub(r"[_\-\s]+", " ", str(key)).strip().capitalize()


def _format_field_lines(label: str, value: Any, *, indent: int) -> list[str]:
    """Render one field and its nested values as structured display lines."""
    prefix = " " * indent
    if value is None:
        return []

    if isinstance(value, Mapping):
        child_lines: list[str] = []
        for key, item in value.items():
            child_lines.extend(
                _format_field_lines(_label(key), item, indent=indent + 3)
            )
        return [f"{prefix}{label}:", *child_lines] if child_lines else []

    if isinstance(value, list):
        item_lines = _format_list_items(value, indent=indent + 2)
        return [f"{prefix}{label}:", *item_lines] if item_lines else []

    text = _format_scalar(value)
    return [f"{prefix}{label}: {text}"] if text else []


def _format_list_items(items: list[Any], *, indent: int) -> list[str]:
    """Render a list as readable bullets, preserving nested maps and lists."""
    prefix = " " * indent
    lines: list[str] = []

    for item in items:
        if isinstance(item, Mapping):
            fields: list[str] = []
            for key, nested_value in item.items():
                fields.extend(
                    _format_field_lines(_label(key), nested_value, indent=indent + 2)
                )
            if fields:
                lines.append(f"{prefix}- {fields[0].lstrip()}")
                lines.extend(fields[1:])
        elif isinstance(item, list):
            nested_items = _format_list_items(item, indent=indent + 2)
            if nested_items:
                lines.append(f"{prefix}-")
                lines.extend(nested_items)
        else:
            text = _format_scalar(item)
            if text:
                lines.append(f"{prefix}- {text}")

    return lines


def _format_scalar(value: Any) -> str:
    """Convert a non-container API value into display text."""
    if isinstance(value, str):
        return _clean_text(value)
    return str(value)


def _clean_text(value: str) -> str:
    """Decode and remove markup from API-provided display text."""
    return re.sub(r"\s+", " ", html.unescape(_HTML_TAG_RE.sub(" ", value))).strip()