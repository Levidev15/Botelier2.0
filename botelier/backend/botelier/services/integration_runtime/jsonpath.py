"""Shared JSONPath-lite extractor.

Used by both ``IntegrationClient`` and ``flow_executor`` so every integration
and flow node resolves response-mapping paths identically. Extracted verbatim
from the former ``integration_client`` monolith.
"""

from typing import Any, Optional


def extract_json_value(data: Any, path: str) -> Any:
    """Extract a value from parsed JSON using a small JSONPath dialect.

    Shared by IntegrationClient and the flow executor so every integration and
    flow node resolves response paths identically.

    Supported syntax:
      - ``$`` / ``$.`` root prefix (optional)
      - dot keys: ``a.b.c``
      - bracket index: ``a[0].b``
      - legacy dot index: ``a.0.b``
      - wildcard: ``a[*].b`` expands across list elements and flattens

    Returns a single value when the path has no wildcard, or a flattened list
    (order-preserving, deduped) when a wildcard is used. ``None`` is returned
    when the path resolves to nothing, so callers can apply default values.
    """
    if not path:
        return data

    if path.startswith("$"):
        path = path[1:]
    # Normalize bracket segments into dot segments so a single split handles
    # ``a[0].b`` and ``a[*].b`` alongside ``a.b`` and legacy ``a.0.b``.
    normalized = path.replace("[", ".[")
    parts = [p for p in normalized.split(".") if p != ""]

    # The "frontier" is the set of live values being resolved. A wildcard
    # expands it; every other token narrows each entry to a single child.
    frontier: list[Any] = [data]
    used_wildcard = False

    for part in parts:
        if part == "[*]":
            used_wildcard = True
            expanded: list[Any] = []
            for item in frontier:
                if isinstance(item, list):
                    expanded.extend(item)
            frontier = expanded
            continue

        index: Optional[int] = None
        if part.startswith("[") and part.endswith("]"):
            inner = part[1:-1]
            index = int(inner) if inner.isdigit() else None
        elif part.isdigit():
            index = int(part)

        next_frontier: list[Any] = []
        for item in frontier:
            if index is not None:
                if isinstance(item, list) and 0 <= index < len(item):
                    next_frontier.append(item[index])
            elif isinstance(item, dict):
                child = item.get(part)
                if child is not None:
                    next_frontier.append(child)
        frontier = next_frontier

    results = [v for v in frontier if v is not None]

    if used_wildcard:
        deduped: list[Any] = []
        for v in results:
            if v not in deduped:
                deduped.append(v)
        return deduped or None

    return results[0] if results else None
