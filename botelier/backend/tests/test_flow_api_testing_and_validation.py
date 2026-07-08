import os

import pytest

os.environ.setdefault("NEXTAUTH_SECRET", "test-nextauth-secret")

from botelier.api import api_tester
from botelier.api.api_tester import ApiTestRequest
from botelier.api.flow_versions import validate_flow_config
from botelier.services.integration_client import (
    APIErrorType,
    IntegrationAPIConfig,
    IntegrationClient,
    _MissingRequiredVariables,
)


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


class _FakeIntegrationType:
    auth_type = "basic_or_jwt"

    def get_auth_config(self):
        return {
            "base_url": "https://api.example.com",
            "basic_auth_query_params": [],
        }


class _FakeIntegration:
    def __init__(self, credentials=None):
        self.integration_type = _FakeIntegrationType()
        self._credentials = credentials or {}

    def get_credentials(self):
        return self._credentials


def _endpoint_def(query_params):
    return {"path": "/hotel_rooms", "query_params": query_params}


def _build_url(query_param_overrides, variables, query_params):
    client = IntegrationClient(ACCOUNT_ID, db=None)
    config = IntegrationAPIConfig(
        integration_id="int_1",
        endpoint_id="hotel_rooms",
        method="GET",
        path="/hotel_rooms",
        query_param_overrides=query_param_overrides,
    )
    return client._build_url(
        _FakeIntegration(),
        config,
        variables,
        endpoint_def=_endpoint_def(query_params),
    )


def test_query_param_override_replaces_seed_default():
    url = _build_url(
        query_param_overrides={"checkin": "2026-01-01"},
        variables={},
        query_params=[{"key": "checkin", "value": "{{checkin}}", "required": True}],
    )
    assert "checkin=2026-01-01" in url


def test_query_param_seed_default_used_when_no_override():
    url = _build_url(
        query_param_overrides={},
        variables={"checkin": "2026-02-02"},
        query_params=[{"key": "checkin", "value": "{{checkin}}", "required": True}],
    )
    assert "checkin=2026-02-02" in url


def test_empty_override_on_required_param_fails_fast():
    with pytest.raises(_MissingRequiredVariables) as exc:
        _build_url(
            query_param_overrides={"checkin": ""},
            variables={"checkin": "2026-02-02"},
            query_params=[{"key": "checkin", "value": "{{checkin}}", "required": True}],
        )
    assert "checkin" in str(exc.value)


def test_empty_override_on_optional_param_is_omitted():
    url = _build_url(
        query_param_overrides={"promo": ""},
        variables={"checkin": "2026-02-02"},
        query_params=[
            {"key": "checkin", "value": "{{checkin}}", "required": True},
            {"key": "promo", "value": "{{promo}}", "required": False},
        ],
    )
    assert "checkin=2026-02-02" in url
    assert "promo" not in url


def test_override_for_unknown_param_key_is_ignored():
    url = _build_url(
        query_param_overrides={"nonexistent": "ignored"},
        variables={"checkin": "2026-02-02"},
        query_params=[{"key": "checkin", "value": "{{checkin}}", "required": True}],
    )
    assert "checkin=2026-02-02" in url
    assert "nonexistent" not in url
    assert "ignored" not in url
