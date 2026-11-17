"""Actual authenticated, disposable API routes; no vendor/model dispatch."""

from unittest.mock import patch

import pyotp
import pytest


def route(fixture, *, account=None, tool=None):
    return (
        f"/api/tools/{tool or fixture.tool_id}/flow/preview-response"
        f"?account_id={account or fixture.account_id}"
    )


async def login(fixture):
    headers = {"Origin": "http://127.0.0.1:5011", "X-MFA-CSRF": "1"}
    primary = await fixture.client.post(
        "/api/auth/login",
        json={"email": fixture.email, "password": fixture.password},
        headers=headers,
    )
    assert primary.status_code == 200, primary.text
    assert primary.json()["mfa_required"] is True
    pending = await fixture.client.post(
        route(fixture), json=payload(), headers=headers,
    )
    assert pending.status_code in (401, 403)
    verified = await fixture.client.post(
        "/api/auth/mfa/verify",
        json={"code": pyotp.TOTP(fixture.totp_secret).now()},
        headers=headers,
    )
    assert verified.status_code == 200, verified.text
    return headers


def payload():
    return {
        "sample": {"name": "  <b>Harbor</b> ", "price": "230.00", "empty": 0},
        "configuration": {
            "responseMapping": {"hotel": "$.name", "total": "$.price", "zero": "$.empty"},
            "responseProjection": {"fields": [
                {"variable": "hotel", "cleanup": ["clean_text"]},
                {"variable": "total"}, {"variable": "zero"},
            ]},
        },
        "variableDeclarations": [
            {"key": "total", "type": "text", "required": True},
        ],
    }


@pytest.mark.asyncio
async def test_preview_requires_real_auth_mfa_and_account_permission_without_any_dispatch():
    from editor_fixture import EditorASGIFixture

    async with EditorASGIFixture() as fixture:
        from botelier.services.action_executor import ActionExecutor

        assert fixture.app.dependency_overrides == {}
        with patch.object(
            ActionExecutor, "__init__",
            side_effect=AssertionError("Preview must not construct an executor"),
        ):
            anonymous = await fixture.client.post(route(fixture), json=payload())
            assert anonymous.status_code == 401
            headers = await login(fixture)
            foreign = await fixture.client.post(
                route(fixture, account="00000000-0000-0000-0000-000000009999"),
                json=payload(),
                headers=headers,
            )
            assert foreign.status_code == 403, foreign.text
            wrong_tool = await fixture.client.post(
                route(fixture, tool="00000000-0000-0000-0000-000000009999"),
                json=payload(), headers=headers,
            )
            assert wrong_tool.status_code == 404
            result = await fixture.client.post(
                route(fixture), json=payload(), headers=headers,
            )
            assert result.status_code == 200, result.text
            assert result.headers["cache-control"] == "no-store"
            assert result.json() == {
                "mapped_variables": {
                    "hotel": "  <b>Harbor</b> ", "total": "230.00", "zero": 0,
                },
                "llm_data": {"hotel": "Harbor", "total": "230.00", "zero": 0},
            }


@pytest.mark.asyncio
async def test_preview_rejects_oversized_and_effect_bearing_input_without_echoing_data():
    from editor_fixture import EditorASGIFixture

    async with EditorASGIFixture() as fixture:
        from botelier.services.action_executor import ActionExecutor

        headers = await login(fixture)
        with patch.object(
            ActionExecutor, "__init__",
            side_effect=AssertionError("Preview must not construct an executor"),
        ):
            oversized = await fixture.client.post(
                route(fixture), content=b" " * 1_048_577,
                headers={**headers, "Content-Type": "application/json"},
            )
            assert oversized.status_code == 413, oversized.text
            request = payload()
            request["configuration"]["url"] = "https://never-call.example.invalid"
            request["configuration"]["headers"] = {"Authorization": "synthetic-sensitive-only"}
            rejected = await fixture.client.post(route(fixture), json=request, headers=headers)
            assert rejected.status_code == 422
            assert "synthetic-sensitive-only" not in rejected.text
            assert "never-call" not in rejected.text
            request = payload()
            request["execute"] = True
            rejected = await fixture.client.post(route(fixture), json=request, headers=headers)
            assert rejected.status_code == 422


@pytest.mark.asyncio
async def test_preview_requires_flow_edit_permission_and_does_not_change_versions():
    from editor_fixture import EditorASGIFixture

    async with EditorASGIFixture() as fixture:
        with fixture.factory() as db:
            membership = db.query(fixture.models["AccountMembership"]).first()
            membership.is_owner = False
            role = db.query(fixture.models["Role"]).first()
            role.permissions = {"flows": {"view": True}}
            before = db.query(fixture.models["FlowVersion"]).count()
            db.commit()
        headers = await login(fixture)
        denied = await fixture.client.post(
            route(fixture), json=payload(), headers=headers,
        )
        assert denied.status_code == 403, denied.text
        with fixture.factory() as db:
            assert db.query(fixture.models["FlowVersion"]).count() == before


def test_preview_budget_is_bounded_and_expired_entries_do_not_reset_live_quotas():
    from botelier.services.flow_response_preview import FlowPreviewBudget

    now = [10.0]
    budget = FlowPreviewBudget(limit=2, capacity=1, clock=lambda: now[0])
    assert budget.admit("account-a")
    assert budget.admit("account-a")
    assert not budget.admit("account-a")
    assert not budget.admit("account-b")
    now[0] += 60
    assert budget.admit("account-b")
    assert not budget.admit("account-a")


def test_repeated_fixture_namespaces_keep_the_real_dependency_on_fresh_in_memory_data():
    import editor_guard
    from simulation_guard import install_test_namespaces

    first = install_test_namespaces(editor_guard.BACKEND_ROOT)
    original = first._session_factory
    dependency = first.get_db
    closed = []

    class Session:
        def close(self):
            closed.append(True)

    session = Session()
    try:
        second = install_test_namespaces(editor_guard.BACKEND_ROOT)
        assert second is first
        assert second.get_db is dependency
        assert second.SessionLocal.__name__ == "forbidden_database_factory"
        second.bind_session_factory(lambda: session)
        generator = dependency()
        assert next(generator) is session
        generator.close()
        assert closed == [True]
    finally:
        first.bind_session_factory(original)
