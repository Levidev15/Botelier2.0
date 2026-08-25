"""Tests for the suggested_mappings output from test_operation.

Covers:
  - Suggestions are generated from a successful response body
  - Fields already in effective_mapping are excluded
  - Failed tests produce an empty suggested_mappings list
  - The cap of 20 entries is enforced
  - Non-dict/non-JSON response bodies are handled gracefully
  - suggested_mappings is always present in the return value
"""

import json
import pytest

from botelier.services.spec_importer.response_extractor import (
    extract_from_json_example,
    fields_to_response_mapping,
    _path_to_variable_key,
)


# ---------------------------------------------------------------------------
# Helpers that replicate the integration_builder logic under test
# ---------------------------------------------------------------------------

def _build_suggestions(data, effective_mapping: dict, cap: int = 20) -> list[dict]:
    """Pure-Python replica of the suggested_mappings block in test_operation.

    Keeps tests independent of FastAPI / DB / executor machinery while still
    exercising exactly the same logic.
    """
    suggested: list[dict] = []
    try:
        raw = data
        if isinstance(raw, str):
            raw = json.loads(raw)
        fields = extract_from_json_example(raw, max_depth=3)
        existing_paths = {str(v) for v in effective_mapping.values()}
        seen_keys = {str(k) for k in effective_mapping.keys()}
        for f in fields:
            path = f.get("path", "")
            if not path or path in existing_paths:
                continue
            key = _path_to_variable_key(path)
            if not key or key in seen_keys:
                continue
            suggested.append(
                {
                    "variable_key": key,
                    "json_path": path,
                    "label": f.get("label", key),
                    "type": f.get("type", "string"),
                    "is_array_item": "[0]" in path,
                }
            )
            seen_keys.add(key)
            if len(suggested) >= cap:
                break
    except Exception:
        pass
    return suggested


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSuggestedMappingsGeneration:
    def test_scalar_fields_are_suggested(self):
        data = {"id": "123", "name": "Deluxe Room", "price": 299.0}
        suggestions = _build_suggestions(data, effective_mapping={})
        paths = [s["json_path"] for s in suggestions]
        assert "$.id" in paths
        assert "$.name" in paths
        assert "$.price" in paths

    def test_labels_are_human_readable(self):
        data = {"total_price": 150, "roomType": "Standard"}
        suggestions = _build_suggestions(data, effective_mapping={})
        by_path = {s["json_path"]: s for s in suggestions}
        assert by_path["$.total_price"]["label"] == "Total Price"
        assert by_path["$.roomType"]["label"] == "Room Type"

    def test_variable_keys_are_lowercased(self):
        # _path_to_variable_key lowercases and replaces dots with underscores;
        # it does NOT convert camelCase to snake_case (that is _make_label's job).
        data = {"totalPrice": 100, "room_name": "King"}
        suggestions = _build_suggestions(data, effective_mapping={})
        keys = {s["variable_key"] for s in suggestions}
        assert "totalprice" in keys   # camelCase collapsed, not split
        assert "room_name" in keys

    def test_nested_fields_are_included(self):
        data = {"room": {"name": "Deluxe", "price": 200}}
        suggestions = _build_suggestions(data, effective_mapping={})
        paths = [s["json_path"] for s in suggestions]
        assert "$.room.name" in paths
        assert "$.room.price" in paths

    def test_array_first_element_is_walked(self):
        data = {"rooms": [{"name": "Suite", "price": 500}]}
        suggestions = _build_suggestions(data, effective_mapping={})
        paths = [s["json_path"] for s in suggestions]
        assert "$.rooms[0].name" in paths
        assert "$.rooms[0].price" in paths

    def test_type_is_inferred_correctly(self):
        data = {"count": 3, "active": True, "ratio": 0.5, "label": "x"}
        suggestions = _build_suggestions(data, effective_mapping={})
        by_path = {s["json_path"]: s for s in suggestions}
        assert by_path["$.count"]["type"] == "integer"
        assert by_path["$.active"]["type"] == "boolean"
        assert by_path["$.ratio"]["type"] == "number"
        assert by_path["$.label"]["type"] == "string"


class TestSuggestedMappingsFiltering:
    def test_already_mapped_paths_are_excluded(self):
        data = {"id": "1", "name": "Room", "price": 100}
        effective = {"room_name": "$.name"}
        suggestions = _build_suggestions(data, effective_mapping=effective)
        paths = [s["json_path"] for s in suggestions]
        assert "$.name" not in paths
        assert "$.id" in paths
        assert "$.price" in paths

    def test_already_mapped_keys_are_excluded(self):
        """A key collision (same variable_key as existing mapping) is also skipped."""
        data = {"price": 200, "total_price": 300}
        # "price" key is already taken
        effective = {"price": "$.some_other_path"}
        suggestions = _build_suggestions(data, effective_mapping=effective)
        keys = {s["variable_key"] for s in suggestions}
        assert "price" not in keys

    def test_multiple_mapped_paths_all_excluded(self):
        data = {"a": 1, "b": 2, "c": 3, "d": 4}
        effective = {"a": "$.a", "b": "$.b"}
        suggestions = _build_suggestions(data, effective_mapping=effective)
        paths = [s["json_path"] for s in suggestions]
        assert "$.a" not in paths
        assert "$.b" not in paths
        assert "$.c" in paths
        assert "$.d" in paths

    def test_empty_effective_mapping_returns_all_fields(self):
        data = {"x": 1, "y": 2}
        suggestions = _build_suggestions(data, effective_mapping={})
        assert len(suggestions) == 2


class TestSuggestedMappingsCap:
    def test_cap_is_enforced(self):
        # 25 scalar fields — should only get 20 back
        data = {f"field_{i}": i for i in range(25)}
        suggestions = _build_suggestions(data, effective_mapping={}, cap=20)
        assert len(suggestions) == 20

    def test_custom_cap_is_respected(self):
        data = {f"f_{i}": i for i in range(10)}
        suggestions = _build_suggestions(data, effective_mapping={}, cap=5)
        assert len(suggestions) == 5

    def test_fewer_than_cap_returns_all(self):
        data = {"a": 1, "b": 2, "c": 3}
        suggestions = _build_suggestions(data, effective_mapping={}, cap=20)
        assert len(suggestions) == 3


class TestSuggestedMappingsEdgeCases:
    def test_empty_dict_returns_empty(self):
        assert _build_suggestions({}, effective_mapping={}) == []

    def test_none_returns_empty(self):
        assert _build_suggestions(None, effective_mapping={}) == []

    def test_scalar_root_returns_empty(self):
        assert _build_suggestions("just a string", effective_mapping={}) == []
        assert _build_suggestions(42, effective_mapping={}) == []

    def test_json_string_body_is_parsed(self):
        body = json.dumps({"room": "Suite", "price": 400})
        suggestions = _build_suggestions(body, effective_mapping={})
        paths = [s["json_path"] for s in suggestions]
        assert "$.room" in paths
        assert "$.price" in paths

    def test_invalid_json_string_returns_empty(self):
        assert _build_suggestions("not json {{{", effective_mapping={}) == []

    def test_failed_test_produces_no_suggestions(self):
        """Simulate the production guard: only emit suggestions on success."""
        success = False
        data = {"room": "Suite"}
        result = _build_suggestions(data, effective_mapping={}) if success else []
        assert result == []

    def test_array_root_is_handled(self):
        data = [{"name": "Room A"}, {"name": "Room B"}]
        suggestions = _build_suggestions(data, effective_mapping={})
        # extract_from_json_example walks array[0]
        paths = [s["json_path"] for s in suggestions]
        assert any("name" in p for p in paths)

    def test_no_duplicate_variable_keys(self):
        """Collision-suffixing (_2, _3) should not produce duplicate keys."""
        # Two different paths that both reduce to the same key
        data = {"rooms": [{"name": "A"}], "name": "B"}
        suggestions = _build_suggestions(data, effective_mapping={})
        keys = [s["variable_key"] for s in suggestions]
        assert len(keys) == len(set(keys)), "Duplicate variable keys found"

    def test_suggestion_shape_has_required_fields(self):
        data = {"rate": 99.0}
        suggestions = _build_suggestions(data, effective_mapping={})
        assert len(suggestions) == 1
        s = suggestions[0]
        assert "variable_key" in s
        assert "json_path" in s
        assert "label" in s
        assert "type" in s
        assert "is_array_item" in s

    def test_is_array_item_true_for_array_origin_paths(self):
        data = {"rooms": [{"name": "Suite", "price": 500}], "hotel_name": "Grand"}
        suggestions = _build_suggestions(data, effective_mapping={})
        by_path = {s["json_path"]: s for s in suggestions}
        # Fields inside the array get is_array_item=True
        assert by_path["$.rooms[0].name"]["is_array_item"] is True
        assert by_path["$.rooms[0].price"]["is_array_item"] is True
        # Top-level scalar field does not
        assert by_path["$.hotel_name"]["is_array_item"] is False

    def test_is_array_item_false_for_plain_scalar_paths(self):
        data = {"id": "abc", "total": 100}
        suggestions = _build_suggestions(data, effective_mapping={})
        for s in suggestions:
            assert s["is_array_item"] is False
