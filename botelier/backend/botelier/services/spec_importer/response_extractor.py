"""Response field extraction for the universal spec importer.

Derives response_mapping entries automatically from:
  - OpenAPI 3.x / Swagger 2.x response schemas (extract_from_openapi_schema)
  - Concrete JSON response examples from Postman saved responses (extract_from_json_example)

Both functions return a list of ``{"path": "$.field.sub", "label": "Field Sub",
"type": "string"}`` dicts that ``fields_to_response_mapping`` converts to the
``{"variable_key": "$.field.sub"}`` format the runtime expects.

The runtime contract for ``response_mapping`` (stored in IntegrationActionVersion.config
and consumed by the voice/SMS executors) is ``{variable_key: json_path}``; publishing
converts each entry to ``ResponseVariable(variable_key=key, json_path=value)`` and
extractors must honour that order.

All extraction is best-effort and fail-safe: any malformed schema or example
returns an empty list rather than raising.
"""

import re
from typing import Any


def _make_label(key: str) -> str:
    """Convert a snake_case or camelCase identifier to a human-readable label."""
    # Insert a space before capital letters that follow a lowercase letter or digit
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key)
    # Replace underscores and hyphens with spaces
    s = re.sub(r"[_\-]+", " ", s)
    return s.strip().title()


def _resolve_ref(ref: str, spec_root: dict) -> "dict | None":
    """Resolve a JSON Schema ``$ref`` by walking from the spec root dict.

    Handles both OpenAPI 3.x (``#/components/schemas/Foo``) and
    Swagger 2.x (``#/definitions/Foo``) ``$ref`` formats.

    Returns the resolved schema dict, or ``None`` if the path cannot be walked.
    """
    if not ref or not ref.startswith("#/"):
        return None
    parts = ref[2:].split("/")  # strip leading '#/' then split on '/'
    obj: Any = spec_root
    for part in parts:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj if isinstance(obj, dict) else None


def _walk_schema(
    schema: dict,
    spec_root: dict,
    depth: int,
    prefix: str,
    seen_refs: frozenset,
) -> list[dict]:
    """Recursively walk a JSON Schema and emit field descriptors."""
    if not isinstance(schema, dict) or depth < 0:
        return []

    # --- $ref resolution (circular-ref safe) ---
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref in seen_refs:
            return []  # guard against circular references
        resolved = _resolve_ref(ref, spec_root)
        if not resolved:
            return []
        return _walk_schema(resolved, spec_root, depth, prefix, seen_refs | {ref})

    # --- Schema combiners ---
    # allOf: every branch MUST be satisfied — merge fields across all of them.
    # anyOf/oneOf: branches are alternatives — return the first viable one.
    allOf_subs = schema.get("allOf")
    if isinstance(allOf_subs, list):
        merged: list[dict] = []
        for sub in allOf_subs:
            if isinstance(sub, dict):
                merged.extend(_walk_schema(sub, spec_root, depth, prefix, seen_refs))
        if merged:
            return merged

    for combiner in ("anyOf", "oneOf"):
        subs = schema.get(combiner)
        if isinstance(subs, list):
            for sub in subs:
                if isinstance(sub, dict):
                    result = _walk_schema(sub, spec_root, depth, prefix, seen_refs)
                    if result:
                        return result

    schema_type = schema.get("type", "")

    # --- Array: descend into items ---
    if schema_type == "array" or "items" in schema:
        items = schema.get("items") or {}
        if isinstance(items, dict) and depth > 0:
            return _walk_schema(items, spec_root, depth - 1, f"{prefix}[0]", seen_refs)
        return []

    # --- Object: emit each property ---
    props = schema.get("properties")
    if not props or not isinstance(props, dict):
        return []
    if depth == 0:
        return []

    fields: list[dict] = []
    for key, prop_schema in props.items():
        if not key or not isinstance(prop_schema, dict):
            continue
        path = f"{prefix}.{key}"

        # Peek at the resolved type to decide whether to recurse
        resolved_prop = prop_schema
        if "$ref" in prop_schema:
            ref = prop_schema["$ref"]
            if ref not in seen_refs:
                r = _resolve_ref(ref, spec_root)
                if r:
                    resolved_prop = r

        prop_type = resolved_prop.get("type", "string")
        prop_is_compound = (
            prop_type in ("object", "array")
            or "properties" in resolved_prop
            or "items" in resolved_prop
            or "allOf" in resolved_prop
            or "anyOf" in resolved_prop
            or "oneOf" in resolved_prop
        )

        if prop_is_compound and depth > 1:
            sub_fields = _walk_schema(prop_schema, spec_root, depth - 1, path, seen_refs)
            if sub_fields:
                fields.extend(sub_fields)
            else:
                # Compound but no extractable leaf fields — emit the container itself
                fields.append({"path": path, "label": _make_label(key), "type": prop_type or "object"})
        else:
            fields.append({"path": path, "label": _make_label(key), "type": prop_type or "string"})

    return fields


def extract_from_openapi_schema(
    schema: dict,
    spec_root: dict,
    max_depth: int = 3,
) -> list[dict]:
    """Extract response field descriptors from an OpenAPI/Swagger JSON Schema.

    Args:
        schema:    The response schema dict (may contain ``$ref``).
        spec_root: The full parsed spec dict — used to resolve ``$ref`` values
                   (both ``#/components/schemas/...`` and ``#/definitions/...``).
        max_depth: Maximum nesting depth to walk before stopping (default 3).

    Returns:
        List of ``{"path": "$.field", "label": "Field", "type": "string"}``
        dicts, ordered by depth then insertion order.
        Returns ``[]`` (never raises) on any malformed or empty input.
    """
    try:
        if not isinstance(schema, dict) or not isinstance(spec_root, dict):
            return []
        return _walk_schema(schema, spec_root, max_depth, "$", frozenset())
    except Exception:
        return []


def _walk_example(value: Any, depth: int, prefix: str) -> list[dict]:
    """Recursively walk a concrete JSON value and emit field descriptors."""
    if depth < 0:
        return []

    if isinstance(value, list):
        if not value or depth == 0:
            return []
        return _walk_example(value[0], depth - 1, f"{prefix}[0]")

    if not isinstance(value, dict):
        return []

    fields: list[dict] = []
    for key, val in value.items():
        if not key:
            continue
        path = f"{prefix}.{key}"

        # Infer type from the concrete value
        if isinstance(val, bool):
            vtype = "boolean"
        elif isinstance(val, int):
            vtype = "integer"
        elif isinstance(val, float):
            vtype = "number"
        elif isinstance(val, list):
            vtype = "array"
        elif isinstance(val, dict):
            vtype = "object"
        else:
            vtype = "string"

        if vtype in ("object", "array") and depth > 1:
            sub_fields = _walk_example(val, depth - 1, path)
            if sub_fields:
                fields.extend(sub_fields)
            else:
                fields.append({"path": path, "label": _make_label(key), "type": vtype})
        else:
            fields.append({"path": path, "label": _make_label(key), "type": vtype})

    return fields


def extract_from_json_example(
    example: Any,
    max_depth: int = 3,
) -> list[dict]:
    """Extract response field descriptors from a concrete JSON value.

    Intended for Postman saved response examples. Walks the value
    recursively up to ``max_depth`` levels.

    Args:
        example:   A parsed JSON value (dict, list, scalar, or ``None``).
        max_depth: Maximum nesting depth (default 3).

    Returns:
        List of ``{"path": "$.field", "label": "Field", "type": "string"}``
        dicts.  Returns ``[]`` for non-dict/non-list roots or any error.
    """
    try:
        if not isinstance(example, (dict, list)):
            return []
        return _walk_example(example, max_depth, "$")
    except Exception:
        return []


def _path_to_variable_key(json_path: str) -> str:
    """Derive a safe snake_case variable key from a JSONPath expression.

    Examples::

        "$.id"              → "id"
        "$.guest.email"     → "guest_email"
        "$[0].id"           → "id"
        "$[0].guest.email"  → "guest_email"
        "$.rooms[0].name"   → "rooms_name"
    """
    # Strip leading $
    key = json_path.lstrip("$")
    # Remove array index brackets like [0], [1]
    key = re.sub(r"\[\d+\]", "", key)
    # Replace dots with underscores
    key = key.replace(".", "_")
    # Remove any remaining bracket characters
    key = re.sub(r"[\[\]]", "", key)
    # Strip leading/trailing underscores and collapse runs
    key = re.sub(r"_+", "_", key).strip("_")
    return key.lower()


def fields_to_response_mapping(fields: list[dict]) -> dict:
    """Convert extracted field descriptors to the runtime ``response_mapping`` format.

    The runtime contract is ``{variable_key: json_path}``; publishing converts each
    entry to ``ResponseVariable(variable_key=key, json_path=value)`` and the voice/SMS
    executors resolve ``value`` as the JSON path against the API response.

    Args:
        fields: List of ``{"path": "$.x", "label": "X", ...}`` dicts.

    Returns:
        ``{"x": "$.x", ...}`` dict — the format stored in
        ``endpoint["response_mapping"]`` and ``IntegrationActionVersion.config``.
        Keys with an empty path are silently skipped.  Colliding keys (e.g. two
        paths that both reduce to the same variable name) receive a numeric suffix
        (``_2``, ``_3``, …) to preserve all fields.
    """
    mapping: dict = {}
    seen_keys: set = set()
    for f in fields:
        path = f.get("path") or ""
        if not path:
            continue
        key = _path_to_variable_key(path)
        if not key:
            continue
        # Disambiguate colliding variable keys
        original_key = key
        counter = 2
        while key in seen_keys:
            key = f"{original_key}_{counter}"
            counter += 1
        seen_keys.add(key)
        mapping[key] = path
    return mapping
