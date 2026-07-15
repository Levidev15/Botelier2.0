"""Tests for the permission catalog, schema helpers, and role create/update validation.

Covers:
- Catalog consistency: every DEFAULT_ROLES key exists in PERMISSIONS; every
  system role has an explicit entry for every canonical permission;
  PLATFORM_ADMIN_PERMISSIONS includes every canonical permission.
- build_permission_schema() returns all groups and actions.
- validate_permission_map() rejects unknown features, unknown actions, and
  non-boolean values; accepts valid partial maps.
- normalize_permission_map() fills missing keys with False.
- Static grep: every permission string used literally in backend route files
  is present in the catalog.
"""

import re
from pathlib import Path

import pytest

from botelier.auth.permissions import (
    DEFAULT_ROLES,
    PERMISSIONS,
    PLATFORM_ADMIN_PERMISSIONS,
    build_empty_permission_map,
    build_permission_schema,
    get_flat_permissions,
    normalize_permission_map,
    validate_permission_map,
)

# ---------------------------------------------------------------------------
# Catalog consistency
# ---------------------------------------------------------------------------


def test_flat_permissions_contains_all_catalog_entries():
    flat = get_flat_permissions()
    for feature, actions in PERMISSIONS.items():
        for action in actions:
            assert f"{feature}.{action}" in flat


def test_default_roles_keys_exist_in_permissions():
    """Every feature/action key used in DEFAULT_ROLES is in the canonical catalog."""
    for role_name, role_data in DEFAULT_ROLES.items():
        for feature, actions in role_data["permissions"].items():
            assert feature in PERMISSIONS, (
                f"Role '{role_name}' references unknown feature '{feature}'"
            )
            for action in actions:
                assert action in PERMISSIONS[feature], (
                    f"Role '{role_name}' references unknown action '{feature}.{action}'"
                )


def test_system_roles_have_explicit_entry_for_every_permission():
    """No canonical permission is missing from any system role (least-privilege default)."""
    for role_name, role_data in DEFAULT_ROLES.items():
        for feature, actions in PERMISSIONS.items():
            assert feature in role_data["permissions"], (
                f"System role '{role_name}' is missing feature '{feature}'"
            )
            for action in actions:
                assert action in role_data["permissions"][feature], (
                    f"System role '{role_name}' is missing '{feature}.{action}'"
                )


def test_system_roles_have_no_extra_keys():
    """No system role references a key that is not in the canonical catalog."""
    for role_name, role_data in DEFAULT_ROLES.items():
        for feature, actions in role_data["permissions"].items():
            assert feature in PERMISSIONS, (
                f"Role '{role_name}' has extra feature '{feature}' not in PERMISSIONS"
            )
            for action in actions:
                assert action in PERMISSIONS[feature], (
                    f"Role '{role_name}' has extra action '{feature}.{action}' not in PERMISSIONS"
                )


def test_platform_admin_permissions_includes_every_catalog_permission():
    for feature, actions in PERMISSIONS.items():
        assert feature in PLATFORM_ADMIN_PERMISSIONS, (
            f"PLATFORM_ADMIN_PERMISSIONS missing feature '{feature}'"
        )
        for action in actions:
            assert action in PLATFORM_ADMIN_PERMISSIONS[feature], (
                f"PLATFORM_ADMIN_PERMISSIONS missing action '{feature}.{action}'"
            )


def test_platform_admin_all_true():
    for feature, actions in PERMISSIONS.items():
        for action in actions:
            assert PLATFORM_ADMIN_PERMISSIONS[feature][action] is True, (
                f"PLATFORM_ADMIN_PERMISSIONS[{feature}][{action}] should be True"
            )


# ---------------------------------------------------------------------------
# build_permission_schema
# ---------------------------------------------------------------------------


def test_build_permission_schema_contains_all_features():
    schema = build_permission_schema()
    schema_features = {f["key"] for f in schema}
    for feature in PERMISSIONS:
        assert feature in schema_features, f"Schema missing feature '{feature}'"


def test_build_permission_schema_contains_all_actions():
    schema = build_permission_schema()
    schema_map = {f["key"]: {p["key"] for p in f["permissions"]} for f in schema}
    for feature, actions in PERMISSIONS.items():
        for action in actions:
            assert action in schema_map[feature], (
                f"Schema missing action '{feature}.{action}'"
            )


def test_build_permission_schema_full_key_format():
    schema = build_permission_schema()
    for feature in schema:
        for perm in feature["permissions"]:
            assert perm["full_key"] == f"{feature['key']}.{perm['key']}"


def test_build_permission_schema_has_required_fields():
    schema = build_permission_schema()
    for feature in schema:
        assert "key" in feature
        assert "label" in feature
        assert "description" in feature
        assert "permissions" in feature
        for perm in feature["permissions"]:
            assert "key" in perm
            assert "full_key" in perm
            assert "label" in perm
            assert "description" in perm


def test_build_permission_schema_no_extra_features():
    schema = build_permission_schema()
    schema_keys = {f["key"] for f in schema}
    assert schema_keys == set(PERMISSIONS.keys())


# ---------------------------------------------------------------------------
# validate_permission_map
# ---------------------------------------------------------------------------


def test_validate_unknown_feature_raises():
    with pytest.raises(ValueError, match="Unknown permission feature"):
        validate_permission_map({"nonexistent_feature": {"view": True}})


def test_validate_unknown_action_raises():
    with pytest.raises(ValueError, match="Unknown permission action"):
        validate_permission_map({"integrations": {"destroy": True}})


def test_validate_non_boolean_raises():
    with pytest.raises(ValueError, match="must be a boolean"):
        validate_permission_map({"assistants": {"view": "yes"}})


def test_validate_non_boolean_int_raises():
    with pytest.raises(ValueError, match="must be a boolean"):
        validate_permission_map({"assistants": {"view": 1}})


def test_validate_non_dict_feature_value_raises():
    with pytest.raises(ValueError):
        validate_permission_map({"assistants": True})


def test_validate_valid_partial_map_passes():
    validate_permission_map({"assistants": {"view": True, "create": False}})


def test_validate_full_map_passes():
    full = {
        feature: {action: True for action in actions}
        for feature, actions in PERMISSIONS.items()
    }
    validate_permission_map(full)


def test_validate_empty_map_passes():
    validate_permission_map({})


# ---------------------------------------------------------------------------
# normalize_permission_map
# ---------------------------------------------------------------------------


def test_normalize_empty_fills_all_false():
    result = normalize_permission_map({})
    for feature, actions in PERMISSIONS.items():
        assert feature in result
        for action in actions:
            assert result[feature][action] is False


def test_normalize_partial_preserves_submitted_values():
    result = normalize_permission_map({"assistants": {"view": True}})
    assert result["assistants"]["view"] is True
    assert result["assistants"]["create"] is False


def test_normalize_missing_feature_defaults_false():
    result = normalize_permission_map({"assistants": {"view": True}})
    # All other features should default to False
    for feature in PERMISSIONS:
        if feature == "assistants":
            continue
        for action in PERMISSIONS[feature]:
            assert result[feature][action] is False, (
                f"Expected False for {feature}.{action}, got {result[feature][action]}"
            )


def test_normalize_drops_unknown_keys():
    result = normalize_permission_map(
        {"assistants": {"view": True, "nonexistent_action": True}}
    )
    assert "nonexistent_action" not in result["assistants"]


def test_normalize_drops_unknown_features():
    result = normalize_permission_map({"ghost_feature": {"view": True}})
    assert "ghost_feature" not in result


def test_normalize_result_covers_entire_catalog():
    result = normalize_permission_map({"assistants": {"view": True}})
    for feature, actions in PERMISSIONS.items():
        assert feature in result
        for action in actions:
            assert action in result[feature]
            assert isinstance(result[feature][action], bool)


# ---------------------------------------------------------------------------
# build_empty_permission_map
# ---------------------------------------------------------------------------


def test_build_empty_all_false():
    result = build_empty_permission_map()
    for feature, actions in PERMISSIONS.items():
        for action in actions:
            assert result[feature][action] is False


# ---------------------------------------------------------------------------
# Static grep: literal permission strings in backend routes exist in catalog
# ---------------------------------------------------------------------------


def _collect_literal_permission_strings() -> set[str]:
    """Grep the backend API directory for quoted permission strings like
    ``"assistants.create"`` and return the unique set.
    """
    api_root = Path(__file__).parent.parent / "botelier" / "api"
    pattern = re.compile(r'"([a-z_]+\.[a-z_]+)"')
    found = set()
    for path in api_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            candidate = match.group(1)
            parts = candidate.split(".")
            if len(parts) == 2:
                found.add(candidate)
    return found


def test_all_literal_permission_strings_in_catalog():
    """Every quoted 'feature.action' string found in backend route files is
    a valid entry in the canonical PERMISSIONS catalog.
    """
    flat = set(get_flat_permissions())
    literals = _collect_literal_permission_strings()

    # Only test strings whose feature prefix is actually in PERMISSIONS to
    # avoid false positives from unrelated dot-notation strings (e.g. module
    # paths, field names).
    for literal in literals:
        feature, action = literal.split(".", 1)
        if feature in PERMISSIONS:
            assert literal in flat, (
                f"Literal permission string '{literal}' found in backend routes "
                f"but is not in the PERMISSIONS catalog."
            )
