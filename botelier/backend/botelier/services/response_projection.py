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
            lines.extend(
                f"{index}. {_format_value(item)}"
                for index, item in enumerate(items, start=1)
                if _format_value(item)
            )
            sections.append("\n".join(lines))
        else:
            lines = ["Results:"]
            for index in range(max_items):
                fields = [
                    f"{_label(key)}: {_format_value(items[index])}"
                    for key, items in arrays
                    if index < len(items) and _format_value(items[index])
                ]
                if fields:
                    lines.append(f"{index + 1}. " + "; ".join(fields))
            sections.append("\n".join(lines))

    if scalars:
        scalar_text = "; ".join(
            f"{_label(key)}: {_format_value(value)}"
            for key, value in scalars
            if _format_value(value)
        )
        if scalar_text:
            sections.append(f"Shared data: {scalar_text}" if arrays else scalar_text)

    return "\n".join(section for section in sections if section).strip()


def _label(key: Any) -> str:
    """Make an API-style field name readable without changing its identity."""
    return re.sub(r"[_\-\s]+", " ", str(key)).strip().capitalize()


def _format_value(value: Any) -> str:
    """Recursively format a mapped value without emitting raw JSON or HTML."""
    if value is None:
        return ""
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, Mapping):
        return "; ".join(
            f"{_label(key)}: {_format_value(item)}"
            for key, item in value.items()
            if _format_value(item)
        )
    if isinstance(value, list):
        items = [_format_value(item) for item in value]
        return "; ".join(item for item in items if item)
    return str(value)


def _clean_text(value: str) -> str:
    """Decode and remove markup from API-provided display text."""
    return re.sub(r"\s+", " ", html.unescape(_HTML_TAG_RE.sub(" ", value))).strip()