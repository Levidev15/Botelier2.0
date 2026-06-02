import httpx
import pytest

from botelier.models.integration import IntegrationActionInvocation, IntegrationCallLog
from botelier.services.action_executor import (
    ActionContext,
    ActionExecutionRequest,
    ActionExecutor,
)
from botelier.services.integration_client import APIErrorType


ACCOUNT_ID = "00000000-0000-0000-0000-000000000001"


class FakeDB:
    def __init__(self):
        self.added = []
        self.committed = False
        self.rolled_back = False

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def query(self, *_args, **_kwargs):
        raise AssertionError("unexpected database query")


@pytest.mark.asyncio
async def test_legacy_action_extracts_response_mapping_and_logs(monkeypatch):
    db = FakeDB()

    async def fake_send(self, client, method, url, headers, body):
        assert method == "GET"
        assert url == "https://api.example.com/guests/Ada"
        return httpx.Response(
            200,
            json={"guest": {"name": "Ada", "room": "214"}},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(ActionExecutor, "_send", fake_send)

    result = await ActionExecutor(db).execute_and_log(
        ActionExecutionRequest(
            context=ActionContext(
                account_id=ACCOUNT_ID,
                channel="flow",
                call_sid="CA123",
                node_id="node-1",
            ),
            variables={"guest_name": "Ada"},
            legacy_config={
                "url": "https://api.example.com/guests/{{guest_name}}",
                "method": "GET",
                "responseMapping": [{"path": "guest.room", "variable": "room"}],
            },
        )
    )

    assert result.success is True
    assert result.extracted_variables == {"room": "214"}
    assert db.committed is True
    assert any(isinstance(obj, IntegrationActionInvocation) for obj in db.added)
    assert any(isinstance(obj, IntegrationCallLog) for obj in db.added)


@pytest.mark.asyncio
async def test_safe_method_retries_network_errors(monkeypatch):
    db = FakeDB()
    calls = 0

    async def flaky_send(self, client, method, url, headers, body):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.NetworkError("temporary network failure")
        return httpx.Response(
            200,
            json={"ok": True},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(ActionExecutor, "_send", flaky_send)

    result = await ActionExecutor(db).execute_and_log(
        ActionExecutionRequest(
            context=ActionContext(account_id=ACCOUNT_ID, channel="test"),
            legacy_config={
                "url": "https://api.example.com/ping",
                "method": "GET",
                "retryCount": 1,
            },
        )
    )

    assert calls == 2
    assert result.success is True
    assert result.data == {"ok": True}


@pytest.mark.asyncio
async def test_mutating_method_does_not_retry_network_errors(monkeypatch):
    db = FakeDB()
    calls = 0

    async def always_fail(self, client, method, url, headers, body):
        nonlocal calls
        calls += 1
        raise httpx.NetworkError("network down")

    monkeypatch.setattr(ActionExecutor, "_send", always_fail)

    result = await ActionExecutor(db).execute_and_log(
        ActionExecutionRequest(
            context=ActionContext(account_id=ACCOUNT_ID, channel="voice"),
            legacy_config={
                "url": "https://api.example.com/reservations",
                "method": "POST",
                "retryCount": 3,
                "body": {"guest": "Ada"},
            },
        )
    )

    assert calls == 1
    assert result.success is False
    assert result.error_type == APIErrorType.NETWORK_ERROR
    assert db.committed is True
