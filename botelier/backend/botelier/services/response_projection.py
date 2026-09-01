"""Build readable, LLM-facing projections from mapped API response values.

The mapping layer deliberately preserves API-shaped values for flow variables.
This module is the display boundary: it turns parallel top-level arrays into
index-aligned records without changing the original mapped data.
"""

from __future__ import annotations

import html
import re
from typing import Any, Mapping


_HTML_TAG_RE = re.compile(r"<[^>]+>")


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