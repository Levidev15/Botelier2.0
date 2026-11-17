"""End-to-end tests for the isolated native editor ASGI checkpoint."""

from datetime import datetime, timedelta
import json

import pyotp
import pytest
from unittest.mock import patch


def test_bounded_bridge_rejects_foreign_routes_and_legacy_simulation():
    from editor_fixture import EditorASGIFixture

    fixture = EditorASGIFixture()
    assert fixture.ready_record()["tool_id"] == fixture.tool_id
    assert fixture.allowed_request(
        "PUT",
        "/api/tools/offline-flow/flow/draft?account_id="
        "00000000-0000-0000-0000-000000000101",
        {"flow_config": {"nodes": [], "edges": []}},
    )
    assert not fixture.allowed_request("GET", "/api/admin/users")
    assert not fixture.allowed_request(
        "POST", "/api/simulate/start",
        {"tool_id": "anything", "assistant_id": "anything", "engine": "legacy",
         "source": "published", "source_version": 1},
    )
    assert not fixture.allowed_request(
        "GET", "/api/tools/offline-flow/flow?account_id="
        "00000000-0000-0000-0000-000000000999",
    )
    publish_path = f"/api/tools/{fixture.tool_id}/flow/publish?account_id={fixture.account_id}"
    assert fixture.allowed_request("POST", publish_path, {})
    assert not fixture.allowed_request("POST", publish_path, {"unexpected": "field"})


@pytest.mark.asyncio
async def test_real_auth_save_reload_publish_and_native_simulation_checkpoint():
    from editor_fixture import EditorASGIFixture

    fixture = EditorASGIFixture()
    async with fixture:
        client = fixture.client
        assert fixture.app.dependency_overrides == {}
        origin = "http://127.0.0.1:5011"
        csrf = {"X-MFA-CSRF": "1", "Origin": origin}
        rpc_login = await fixture.forward({
            "action": "request", "id": "cookie-set",
            "method": "POST", "path": "/api/auth/login",
            "headers": {
                "Content-Type": "application/json", "Origin": origin, "X-MFA-CSRF": "1",
            },
            "body": {"email": fixture.email, "password": fixture.password},
        })
        assert rpc_login["status"] == 200
        cookie_header = next(
            value for key, value in rpc_login["headers"] if key.lower() == "set-cookie"
        )
        primary_rpc_cookie = cookie_header.split(";", 1)[0]
        without_forwarded_cookie = await fixture.forward({
            "action": "request", "id": "no-ambient-cookie",
            "method": "GET", "path": "/api/auth/mfa/status",
        })
        assert without_forwarded_cookie["status"] == 401
        missing_security_headers = await fixture.forward({
            "action": "request", "id": "missing-origin-csrf",
            "method": "POST", "path": "/api/auth/mfa/verify",
            "headers": {"Cookie": primary_rpc_cookie, "Content-Type": "application/json"},
            "body": {"code": pyotp.TOTP(fixture.totp_secret).now()},
        })
        assert missing_security_headers["status"] == 403

        unauthenticated = await client.get(
            f"/api/tools/{fixture.tool_id}/flow",
            params={"account_id": fixture.account_id},
            headers={"Origin": origin},
        )
        assert unauthenticated.status_code == 401
        login = await client.post(
            "/api/auth/login",
            json={"email": fixture.email, "password": fixture.password},
            headers=csrf,
        )
        assert login.status_code == 200, login.text
        assert login.json()["mfa_required"] is True
        assert login.json()["access_token"] is None
        primary_cookie = client.cookies.get("botelier_mfa_session")
        assert primary_cookie
        missing_csrf = await client.post(
            "/api/auth/mfa/verify",
            json={"code": pyotp.TOTP(fixture.totp_secret).now()},
            headers={"Cookie": f"botelier_mfa_session={primary_cookie}"},
        )
        assert missing_csrf.status_code == 403
        challenge = await client.get("/api/auth/mfa/status", headers=csrf)
        assert challenge.status_code == 200
        assert challenge.json()["mfa_required"] is True
        factor = await client.post(
            "/api/auth/mfa/verify",
            json={"code": pyotp.TOTP(fixture.totp_secret).now()},
            headers=csrf,
        )
        assert factor.status_code == 200, factor.text
        assert factor.json()["mfa_required"] is False
        current = await client.get("/api/auth/mfa/status", headers=csrf)
        assert current.status_code == 200
        assert current.json()["mfa_required"] is False
        stale = await client.get(
            "/api/auth/mfa/status",
            headers={**csrf, "Cookie": f"botelier_mfa_session={primary_cookie}"},
        )
        assert stale.status_code == 401

        account_query = {"account_id": fixture.account_id}
        baseline = await client.get(
            f"/api/tools/{fixture.tool_id}/flow",
            params={**account_query, "source": "published"},
            headers=csrf,
        )
        assert baseline.status_code == 200, baseline.text
        assert baseline.json()["version_number"] == 1
        edited = baseline.json()["flow_config"]
        query_node = next(node for node in edited["nodes"] if node["id"] == "query")
        query_node["data"]["slot"]["prompt"] = "Which synthetic stay?"
        private_guidance = "Private edited guidance: collect the caller's room preference exactly."
        query_node["data"]["instructions"] = private_guidance
        saved = await client.put(
            f"/api/tools/{fixture.tool_id}/flow/draft",
            params=account_query,
            json={"flow_config": edited, "description": "Synthetic editor draft"},
            headers=csrf,
        )
        assert saved.status_code == 200, saved.text
        draft_id = saved.json()["version_id"]
        draft = await client.get(
            f"/api/tools/{fixture.tool_id}/flow",
            params={**account_query, "source": "draft"},
            headers=csrf,
        )
        assert draft.status_code == 200
        assert draft.json()["version_id"] == draft_id
        assert draft.json()["flow_config"]["nodes"][1]["data"]["slot"]["prompt"] == (
            "Which synthetic stay?"
        )
        assert draft.json()["flow_config"]["nodes"][1]["data"]["instructions"] == private_guidance
        published = await client.post(
            f"/api/tools/{fixture.tool_id}/flow/publish",
            params=account_query,
            json={},
            headers=csrf,
        )
        assert published.status_code == 200, published.text
        assert published.json()["version_id"] == draft_id
        assert published.json()["version_number"] == 2
        stale_version = await client.post(
            "/api/simulate/start",
            json={
                "tool_id": fixture.tool_id, "assistant_id": fixture.assistant_id,
                "engine": "native_pilot", "source": "published", "source_version": 1,
            },
            headers=csrf,
        )
        assert stale_version.status_code == 409, stale_version.text
        from botelier.api import simulation

        with patch.object(
            simulation.FlowExecutor, "__init__",
            side_effect=AssertionError("native editor run fell through to FlowExecutor"),
        ):
            started = await client.post(
                "/api/simulate/start",
                json={
                    "tool_id": fixture.tool_id, "assistant_id": fixture.assistant_id,
                    "engine": "native_pilot", "source": "published", "source_version": 2,
                },
                headers=csrf,
            )
        assert started.status_code == 200, started.text
        started_body = started.json()
        runtime = started_body["runtime"]
        assert runtime["engine"] == "native_pilot"
        assert runtime["tool_id"] == fixture.tool_id
        assert runtime["assistant_id"] == fixture.assistant_id
        assert runtime["flow_version_id"] == draft_id
        assert {entry["key"] for entry in started_body["variables_to_collect"]} >= {
            "query", "choice",
        }
        message = await client.post(
            "/api/simulate/message",
            json={"session_id": started_body["session_id"], "message": "standard"},
            headers=csrf,
        )
        assert message.status_code == 200, message.text
        message_body = message.json()
        assert message_body["state"]["collected_slots"]["query"] == "standard"
        assert message_body["function_called"].startswith("pilot_collect_query_")
        assert message_body["function_result"]["data"] == {
            "rooms": [{"name": "Standard", "price": 0}],
            "price": 0,
        }
        assert any(
            message.get("role") in {"system", "developer"}
            and private_guidance in message.get("content", "")
            for request in fixture._native_fixture.providers.requests
            for message in request.get("messages", [])
        )
        assert private_guidance not in json.dumps(started_body["messages"])
        assert private_guidance not in json.dumps(message_body["messages"])

        expired_login = await client.post(
            "/api/auth/login",
            json={"email": fixture.email, "password": fixture.password},
            headers=csrf,
        )
        assert expired_login.status_code == 200
        expired_cookie = client.cookies.get("botelier_mfa_session")
        from botelier.models.mfa import MFASession
        from botelier.services import mfa_service

        expired_db = fixture.factory()
        expired_session = expired_db.get(
            MFASession, mfa_service.digest(expired_cookie),
        )
        expired_session.expires_at = datetime.utcnow() - timedelta(seconds=1)
        expired_db.commit()
        expired_db.close()
        expired_challenge = await client.post(
            "/api/auth/mfa/verify",
            json={"code": pyotp.TOTP(fixture.totp_secret).now()},
            headers={**csrf, "Cookie": f"botelier_mfa_session={expired_cookie}"},
        )
        assert expired_challenge.status_code == 401
