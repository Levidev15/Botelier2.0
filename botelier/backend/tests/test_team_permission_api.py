"""API-level tests for team permission-schema endpoint and role create/update validation.

These tests verify:
  - GET /team/permission-schema: requires team.manage_roles (403 if absent),
    returns all feature groups from the canonical catalog (payload contract).
  - POST /team/roles: unknown feature key → 400, unknown action key → 400,
    non-boolean value → 400, valid partial map → normalized full map persisted.
  - PATCH /team/roles/{id}: same validation rules as create.

Tests call the endpoint handler functions directly with mock AccountContext
objects (consistent with the existing service-test style in this codebase).
"""

import asyncio
import os
import uuid
from unittest.mock import MagicMock, AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("NEXTAUTH_SECRET", "test-secret-for-testing-only")

import pytest
from fastapi import HTTPException

from botelier.auth.permissions import PERMISSIONS, get_flat_permissions
from botelier.api.team import (
    CreateRoleRequest,
    UpdateRoleRequest,
    create_role,
    get_permission_schema,
    update_role,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx_with_permission(has_perm: bool = True) -> MagicMock:
    """Build a mock AccountContext that allows or denies any require_permission call."""
    ctx = MagicMock()
    ctx.account.id = uuid.uuid4()
    if has_perm:
        ctx.require_permission.return_value = None
    else:
        ctx.require_permission.side_effect = HTTPException(
            status_code=403, detail="Permission denied: team.manage_roles"
        )
    return ctx


def _mock_db_no_roles() -> MagicMock:
    """Return a DB mock where no Role with the same slug exists (no collision).

    The ``refresh`` side effect populates required fields so _build_role_response
    can construct a valid RoleResponse (Pydantic requires non-None created_at, etc.).
    """
    from datetime import datetime

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter.return_value.count.return_value = 0
    db.add.return_value = None
    db.commit.return_value = None

    def _refresh(role_obj):
        if not hasattr(role_obj, "created_at") or role_obj.created_at is None:
            object.__setattr__(role_obj, "created_at", datetime.utcnow())
        if not hasattr(role_obj, "id") or role_obj.id is None:
            object.__setattr__(role_obj, "id", uuid.uuid4())

    db.refresh.side_effect = _refresh
    return db


def _make_role(permissions: dict) -> MagicMock:
    """Create a role-like mock with all attributes that RoleResponse needs."""
    from datetime import datetime

    role = MagicMock()
    role.id = uuid.uuid4()
    role.account_id = uuid.uuid4()
    role.is_system_role = False
    role.name = "Test Role"
    role.slug = "test-role"
    role.description = None
    role.permissions = permissions
    role.created_at = datetime.utcnow()
    return role


def _mock_db_with_role(permissions: dict):
    """Return (db_mock, role_mock) where the role has the given permissions map."""
    role = _make_role(permissions)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = role
    db.query.return_value.filter.return_value.count.return_value = 0
    db.commit.return_value = None
    db.refresh.return_value = None
    return db, role


# ---------------------------------------------------------------------------
# GET /permission-schema — authz
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_permission_schema_forbidden_when_missing_permission():
    """Returns 403 when the caller lacks team.manage_roles."""
    ctx = _ctx_with_permission(has_perm=False)
    with pytest.raises(HTTPException) as exc_info:
        await get_permission_schema(ctx=ctx)
    assert exc_info.value.status_code == 403
    ctx.require_permission.assert_called_once_with("team.manage_roles")


@pytest.mark.asyncio
async def test_permission_schema_calls_require_permission():
    """Endpoint always calls require_permission('team.manage_roles')."""
    ctx = _ctx_with_permission(has_perm=True)
    await get_permission_schema(ctx=ctx)
    ctx.require_permission.assert_called_once_with("team.manage_roles")


# ---------------------------------------------------------------------------
# GET /permission-schema — payload contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_permission_schema_returns_features_key():
    """Response has a top-level 'features' key."""
    ctx = _ctx_with_permission(has_perm=True)
    result = await get_permission_schema(ctx=ctx)
    assert "features" in result
    assert isinstance(result["features"], list)


@pytest.mark.asyncio
async def test_permission_schema_contains_all_catalog_features():
    """Every canonical feature appears in the response."""
    ctx = _ctx_with_permission(has_perm=True)
    result = await get_permission_schema(ctx=ctx)
    feature_keys = {f["key"] for f in result["features"]}
    for feature in PERMISSIONS:
        assert feature in feature_keys, f"Missing feature '{feature}' in schema response"


@pytest.mark.asyncio
async def test_permission_schema_contains_all_catalog_actions():
    """Every canonical action appears under its feature in the response."""
    ctx = _ctx_with_permission(has_perm=True)
    result = await get_permission_schema(ctx=ctx)
    schema_map = {f["key"]: {p["key"] for p in f["permissions"]} for f in result["features"]}
    for feature, actions in PERMISSIONS.items():
        for action in actions:
            assert action in schema_map.get(feature, set()), (
                f"Missing action '{feature}.{action}' in schema response"
            )


@pytest.mark.asyncio
async def test_permission_schema_permission_items_have_required_fields():
    """Every permission item has key, full_key, label, description."""
    ctx = _ctx_with_permission(has_perm=True)
    result = await get_permission_schema(ctx=ctx)
    for feature in result["features"]:
        for perm in feature["permissions"]:
            assert "key" in perm
            assert "full_key" in perm
            assert "label" in perm
            assert "description" in perm
            assert perm["full_key"] == f"{feature['key']}.{perm['key']}"


@pytest.mark.asyncio
async def test_permission_schema_includes_new_feature_areas():
    """The six areas missing from the old hardcoded schema are all present."""
    ctx = _ctx_with_permission(has_perm=True)
    result = await get_permission_schema(ctx=ctx)
    feature_keys = {f["key"] for f in result["features"]}
    for required in ("integrations", "messages", "usage", "billing_rates", "properties", "records"):
        assert required in feature_keys, f"Feature '{required}' missing from permission schema"


# ---------------------------------------------------------------------------
# POST /roles — unknown key → 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_role_unknown_feature_returns_400():
    """Submitting a permission map with an unknown feature key returns 400."""
    ctx = _ctx_with_permission(has_perm=True)
    db = _mock_db_no_roles()
    data = CreateRoleRequest(
        name="Test Role",
        permissions={"ghost_feature": {"view": True}},
    )
    with pytest.raises(HTTPException) as exc_info:
        await create_role(data=data, ctx=ctx, db=db)
    assert exc_info.value.status_code == 400
    assert "ghost_feature" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_role_unknown_action_returns_400():
    """Submitting a permission map with an unknown action key returns 400."""
    ctx = _ctx_with_permission(has_perm=True)
    db = _mock_db_no_roles()
    data = CreateRoleRequest(
        name="Test Role",
        permissions={"integrations": {"destroy": True}},
    )
    with pytest.raises(HTTPException) as exc_info:
        await create_role(data=data, ctx=ctx, db=db)
    assert exc_info.value.status_code == 400
    assert "integrations.destroy" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_role_non_boolean_value_returns_400():
    """Submitting a non-boolean value for a permission returns 400."""
    ctx = _ctx_with_permission(has_perm=True)
    db = _mock_db_no_roles()
    data = CreateRoleRequest(
        name="Test Role",
        permissions={"assistants": {"view": "yes"}},
    )
    with pytest.raises(HTTPException) as exc_info:
        await create_role(data=data, ctx=ctx, db=db)
    assert exc_info.value.status_code == 400
    assert "boolean" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# POST /roles — normalization persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_role_partial_map_normalized_to_full():
    """A partial permission map is normalized so all canonical keys are stored."""
    from datetime import datetime

    ctx = _ctx_with_permission(has_perm=True)
    db = _mock_db_no_roles()

    captured_permissions: dict = {}

    def capture_add(role_obj):
        # db.add is called immediately after permissions are set on the role
        captured_permissions.update(role_obj.permissions)
        # Populate required fields so _build_role_response succeeds
        role_obj.id = uuid.uuid4()
        role_obj.created_at = datetime.utcnow()

    db.add.side_effect = capture_add

    data = CreateRoleRequest(
        name="Partial Role",
        permissions={"assistants": {"view": True}},
    )
    await create_role(data=data, ctx=ctx, db=db)

    # All canonical keys must be present in the normalized map
    for feature, actions in PERMISSIONS.items():
        assert feature in captured_permissions, f"Missing feature '{feature}' in stored permissions"
        for action in actions:
            assert action in captured_permissions[feature], (
                f"Missing action '{feature}.{action}' in stored permissions"
            )
    # The submitted value should be honoured
    assert captured_permissions["assistants"]["view"] is True
    # Omitted keys default to False
    assert captured_permissions["assistants"]["create"] is False
    assert captured_permissions["integrations"]["view"] is False


@pytest.mark.asyncio
async def test_create_role_empty_map_normalized_all_false():
    """An empty permission map normalizes to all-False for every canonical key."""
    from datetime import datetime

    ctx = _ctx_with_permission(has_perm=True)
    db = _mock_db_no_roles()

    captured_permissions: dict = {}

    def capture_add(role_obj):
        captured_permissions.update(role_obj.permissions)
        role_obj.id = uuid.uuid4()
        role_obj.created_at = datetime.utcnow()

    db.add.side_effect = capture_add

    data = CreateRoleRequest(name="Empty Role", permissions={})
    await create_role(data=data, ctx=ctx, db=db)

    for feature, actions in PERMISSIONS.items():
        for action in actions:
            assert captured_permissions[feature][action] is False, (
                f"Expected False for {feature}.{action}, got {captured_permissions[feature][action]}"
            )


# ---------------------------------------------------------------------------
# PATCH /roles/{id} — same validation rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_role_unknown_feature_returns_400():
    """PATCH with an unknown feature key returns 400."""
    ctx = _ctx_with_permission(has_perm=True)
    db, role = _mock_db_with_role(permissions={})
    data = UpdateRoleRequest(permissions={"ghost_feature": {"view": True}})
    with pytest.raises(HTTPException) as exc_info:
        await update_role(role_id=str(role.id), data=data, ctx=ctx, db=db)
    assert exc_info.value.status_code == 400
    assert "ghost_feature" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_role_unknown_action_returns_400():
    """PATCH with an unknown action key returns 400."""
    ctx = _ctx_with_permission(has_perm=True)
    db, role = _mock_db_with_role(permissions={})
    data = UpdateRoleRequest(permissions={"integrations": {"destroy": True}})
    with pytest.raises(HTTPException) as exc_info:
        await update_role(role_id=str(role.id), data=data, ctx=ctx, db=db)
    assert exc_info.value.status_code == 400
    assert "integrations.destroy" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_role_non_boolean_returns_400():
    """PATCH with a non-boolean permission value returns 400."""
    ctx = _ctx_with_permission(has_perm=True)
    db, role = _mock_db_with_role(permissions={})
    data = UpdateRoleRequest(permissions={"assistants": {"view": 1}})
    with pytest.raises(HTTPException) as exc_info:
        await update_role(role_id=str(role.id), data=data, ctx=ctx, db=db)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_update_role_partial_map_normalized():
    """PATCH with partial map normalizes to full canonical map before saving."""
    ctx = _ctx_with_permission(has_perm=True)
    db, role = _mock_db_with_role(permissions={})
    data = UpdateRoleRequest(permissions={"assistants": {"view": True}})

    await update_role(role_id=str(role.id), data=data, ctx=ctx, db=db)

    stored = role.permissions
    # All features and actions must be present
    for feature, actions in PERMISSIONS.items():
        assert feature in stored
        for action in actions:
            assert action in stored[feature]
    assert stored["assistants"]["view"] is True
    assert stored["assistants"]["create"] is False


@pytest.mark.asyncio
async def test_update_role_none_permissions_skips_validation():
    """PATCH with permissions=None (only updating name) skips validation."""
    ctx = _ctx_with_permission(has_perm=True)
    original_perms = {"assistants": {"view": True}}
    db, role = _mock_db_with_role(permissions=original_perms)
    data = UpdateRoleRequest(name="New Name", permissions=None)

    # Should not raise
    await update_role(role_id=str(role.id), data=data, ctx=ctx, db=db)
    # Permissions should be unchanged
    assert role.permissions == original_perms


@pytest.mark.asyncio
async def test_update_role_system_role_returns_400():
    """PATCH on a system role returns 400."""
    ctx = _ctx_with_permission(has_perm=True)
    db, role = _mock_db_with_role(permissions={})
    role.is_system_role = True
    data = UpdateRoleRequest(name="New Name")
    with pytest.raises(HTTPException) as exc_info:
        await update_role(role_id=str(role.id), data=data, ctx=ctx, db=db)
    assert exc_info.value.status_code == 400
