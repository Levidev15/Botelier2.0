import os

import pytest

os.environ.setdefault("NEXTAUTH_SECRET", "test-nextauth-secret")

from botelier.api import api_tester
from botelier.api.api_tester import ApiTestRequest
from botelier.api.flow_versions import validate_flow_config
from botelier.services.integration_client import APIErrorType


ACCOUNT_ID = "00000000-0000-0000-0000-000000000001"


class FakeResult:
    success = True
    status_code = 200
    data = {"guest": {"room": "214"}}
    latency_ms = 17
    error_message = None
    error_type = APIErrorType.SUCCESS
    extracted_variables = {"room": "214"}
    request_id = "req123"


@pytest.mark.asyncio
async def test_account_api_tester_uses_action_executor(monkeypatch):
    captured = {}

    def allow_access(*_args, **_kwargs):
        return None

    async def fake_execute_and_log(self, request):
        captured["request"] = request
        return FakeResult()

    monkeypatch.setattr(api_tester, "check_account_permission", allow_access)
    monkeypatch.setattr(api_tester.ActionExecutor, "execute_and_log", fake_execute_and_log)

    response = await api_tester.test_api_request(
        ApiTestRequest(
            account_id=ACCOUNT_ID,
            method="PATCH",
            url="https://api.example.com/guest",
            bodyTemplate='{"name": "{{guest_name}}"}',
            variables={"guest_name": "Ada"},
            responseMapping={"room": "guest.room"},
            sourceLabel="Guest lookup",
            nodeId="node_api",
            flowToolId="11111111-1111-1111-1111-111111111111",
        ),
        current_user=object(),
        db=object(),
    )

    request = captured["request"]
    assert request.context.account_id == ACCOUNT_ID
    assert request.context.channel == "test"
    assert request.context.node_id == "node_api"
    assert request.context.source_label == "Guest lookup"
    assert request.legacy_config["method"] == "PATCH"
    assert request.legacy_config["responseMapping"] == {"room": "guest.room"}
    assert response.success is True
    assert response.extracted_variables == {"room": "214"}


def test_flow_validation_accepts_patch_without_requiring_successful_api_test():
    valid_flow = {
        "initial_node": "start",
        "nodes": [
            {"id": "start", "type": "initial", "data": {"name": "Start"}},
            {
                "id": "api",
                "type": "api_request",
                "data": {
                    "name": "Patch guest",
                    "api": {
                        "method": "PATCH",
                        "url": "https://api.example.com/guest",
                        "bodyTemplate": '{"name": "{{guest_name}}"}',
                        "timeout": 8,
                        "retryCount": 0,
                        "responseMapping": {"room": "guest.room"},
                    },
                },
            },
        ],
        "edges": [{"source": "start", "target": "api"}],
    }

    is_valid, errors = validate_flow_config(valid_flow)

    assert is_valid is True
    assert errors == []


def test_flow_validation_rejects_invalid_api_node_config():
    invalid_flow = {
        "initial_node": "start",
        "nodes": [
            {"id": "start", "type": "initial", "data": {"name": "Start"}},
            {
                "id": "api",
                "type": "api_request",
                "data": {
                    "name": "Broken call",
                    "api": {
                        "method": "PATCH",
                        "url": "not-a-url",
                        "bodyTemplate": '{"bad":',
                        "timeout": 0,
                        "retryCount": 4,
                        "responseMapping": {"": ""},
                    },
                },
            },
        ],
        "edges": [{"source": "start", "target": "api"}],
    }

    is_valid, errors = validate_flow_config(invalid_flow)

    assert is_valid is False
    assert any("invalid HTTP/HTTPS URL" in error for error in errors)
    assert any("request body must be valid JSON" in error for error in errors)
    assert any("timeout must be 1-60 seconds" in error for error in errors)
    assert any("retry count must be 0-3" in error for error in errors)
    assert any("incomplete response mapping" in error for error in errors)
