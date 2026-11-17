"""Prepared native bodies through actual action/client serializers, no sockets."""

import asyncio
import json

import httpx
import pytest

from node_contract_io import ACCOUNT, CONNECTION, PROPERTY, ActionRecords, synthetic_integration


@pytest.mark.parametrize("source", ["custom", "integration", "integration-request"])
@pytest.mark.parametrize("mode,media_type,value", [
    ("json", "application/json", {"guest": '"}, "admin":true', "literal": "{{private}}", "zero": 0}),
    ("data", "application/x-www-form-urlencoded", {"guest": "A&B", "literal": "{{private}}"}),
    ("content", "application/xml", "<name>&lt;Guest&gt; {{private}}</name>"),
])
def test_prepared_request_uses_declared_transport_without_replacing_literal_values(
    monkeypatch, source, mode, media_type, value,
):
    from botelier.services.action_executor import ActionContext, ActionExecutionRequest, ActionExecutor
    from botelier.services.integration_client import IntegrationAPIConfig
    from botelier.services.request_templates import PreparedRequestBody
    from botelier.services.ssrf_safe_transport import SSRFSafeTransport

    observed = []

    async def transport(self, request):
        observed.append(request)
        return httpx.Response(200, json={"ok": True}, request=request)

    monkeypatch.setattr(SSRFSafeTransport, "handle_async_request", transport)

    async def scenario():
        records = ActionRecords(synthetic_integration())
        db = records.session()
        prepared = PreparedRequestBody(mode, value)
        kwargs = {}
        if source in {"integration", "integration-request"}:
            kwargs["integration_config"] = IntegrationAPIConfig(
                integration_id=CONNECTION, method="POST", path="/search",
                headers={"Content-Type": media_type},
                prepared_body=prepared if source == "integration" else None,
            )
            if source == "integration-request":
                kwargs["prepared_body"] = prepared
        else:
            kwargs.update(
                prepared_body=prepared,
                legacy_config={"url": "https://api.fixture.invalid/search", "method": "POST",
                               "headers": {"Content-Type": media_type}},
            )
        try:
            result = await ActionExecutor(db).execute_and_log(ActionExecutionRequest(
                context=ActionContext(account_id=ACCOUNT, property_id=PROPERTY, channel="flow"),
                variables={"private": "must never replace inserted content"},
                **kwargs,
            ))
            assert result.success, result.error_type
            assert len(observed) == 1
            request = observed[0]
            if mode == "json":
                assert json.loads(request.content) == value
            elif mode == "data":
                from urllib.parse import parse_qs
                assert parse_qs(request.content.decode()) == {key: [item] for key, item in value.items()}
            else:
                assert request.content.decode() == value
            assert records.writes
        finally:
            db.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("case", [
    "test_legacy_action_extracts_response_mapping_and_logs",
    "test_safe_method_retries_network_errors",
    "test_mutating_method_does_not_retry_network_errors",
])
def test_existing_action_executor_contracts_still_execute(case, monkeypatch, request):
    """Run existing async tests explicitly without enabling unrelated plugins."""
    import importlib.util
    from pathlib import Path

    request.config.addinivalue_line("markers", "asyncio: legacy coroutine executed explicitly by this fixture")
    path = Path(__file__).resolve().parents[3] / "botelier/backend/tests/test_action_executor.py"
    spec = importlib.util.spec_from_file_location("legacy_action_contract_cases", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    asyncio.run(getattr(module, case)(monkeypatch))


def test_custom_http_response_is_bounded_before_full_buffering_or_json_parse(monkeypatch):
    from botelier.services.action_executor import ActionContext, ActionExecutionRequest, ActionExecutor
    from botelier.services.ssrf_safe_transport import SSRFSafeTransport

    class Chunks(httpx.AsyncByteStream):
        def __init__(self):
            self.yielded = 0
            self.closed = False

        async def __aiter__(self):
            for _ in range(100):
                self.yielded += 1
                yield b"x" * (1024 * 1024)

        async def aclose(self):
            self.closed = True

    stream = Chunks()
    requests = []

    async def transport(self, request):
        requests.append(request)
        return httpx.Response(200, stream=stream, request=request)

    monkeypatch.setattr(SSRFSafeTransport, "handle_async_request", transport)

    async def scenario():
        records = ActionRecords()
        db = records.session()
        try:
            result = await ActionExecutor(db).execute_and_log(ActionExecutionRequest(
                context=ActionContext(account_id=ACCOUNT, channel="flow"),
                legacy_config={"url": "https://api.fixture.invalid/search", "method": "GET"},
            ))
            assert not result.success
            assert stream.yielded <= 11, "Do not fully buffer an unbounded upstream stream"
            assert stream.closed
            assert len(requests) == 1
        finally:
            db.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["custom", "integration"])
@pytest.mark.parametrize("mode,media_type,value", [
    ("data", "application/json", {"value": "literal"}),
    ("json", "text/plain", {"value": "literal"}),
    ("content", "application/json", "literal"),
])
def test_conflicting_prepared_mode_and_content_type_fail_before_transport(
    monkeypatch, source, mode, media_type, value,
):
    from botelier.services.action_executor import ActionContext, ActionExecutionRequest, ActionExecutor
    from botelier.services.integration_client import IntegrationAPIConfig
    from botelier.services.request_templates import PreparedRequestBody
    from botelier.services.ssrf_safe_transport import SSRFSafeTransport

    observed = []

    async def transport(self, request):
        observed.append(request)
        return httpx.Response(200, json={}, request=request)

    monkeypatch.setattr(SSRFSafeTransport, "handle_async_request", transport)

    async def scenario():
        records = ActionRecords(synthetic_integration())
        db = records.session()
        prepared = PreparedRequestBody(mode, value)
        if source == "integration":
            kwargs = {"integration_config": IntegrationAPIConfig(
                integration_id=CONNECTION, method="POST", path="/search",
                headers={"Content-Type": media_type}, prepared_body=prepared,
            )}
        else:
            kwargs = {"legacy_config": {
                "url": "https://api.fixture.invalid/search", "method": "POST",
                "headers": {"Content-Type": media_type},
            }, "prepared_body": prepared}
        try:
            result = await ActionExecutor(db).execute(ActionExecutionRequest(
                context=ActionContext(account_id=ACCOUNT, property_id=PROPERTY, channel="flow"),
                **kwargs,
            ))
            assert not result.success
            assert observed == []
        finally:
            db.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["custom", "integration"])
@pytest.mark.parametrize("mode,headers,value,expected_type", [
    ("data", {}, {"value": "{{literal}}"}, "application/x-www-form-urlencoded"),
    ("content", {}, "literal", "text/plain"),
    ("files", {"CONTENT-TYPE": "multipart/form-data"}, {"value": "{{literal}}"}, "multipart/form-data"),
])
def test_prepared_modes_derive_defaults_and_multipart_always_owns_its_boundary(
    monkeypatch, source, mode, headers, value, expected_type,
):
    from botelier.services.action_executor import ActionContext, ActionExecutionRequest, ActionExecutor
    from botelier.services.integration_client import IntegrationAPIConfig
    from botelier.services.request_templates import PreparedRequestBody
    from botelier.services.ssrf_safe_transport import SSRFSafeTransport

    observed = []

    async def transport(self, request):
        await request.aread()
        observed.append(request)
        return httpx.Response(200, json={}, request=request)

    monkeypatch.setattr(SSRFSafeTransport, "handle_async_request", transport)

    async def scenario():
        records = ActionRecords(synthetic_integration())
        db = records.session()
        prepared = PreparedRequestBody(mode, value)
        if source == "integration":
            kwargs = {"integration_config": IntegrationAPIConfig(
                integration_id=CONNECTION, method="POST", path="/search",
                headers=headers, prepared_body=prepared,
            )}
        else:
            kwargs = {"legacy_config": {
                "url": "https://api.fixture.invalid/search", "method": "POST", "headers": headers,
            }, "prepared_body": prepared}
        try:
            result = await ActionExecutor(db).execute(ActionExecutionRequest(
                context=ActionContext(account_id=ACCOUNT, property_id=PROPERTY, channel="flow"),
                **kwargs,
            ))
            assert result.success
            assert len(observed) == 1
            content_type = observed[0].headers["content-type"]
            assert content_type.startswith(expected_type)
            if mode == "files":
                assert "boundary=" in content_type
                assert b"{{literal}}" in observed[0].content
        finally:
            db.close()

    asyncio.run(scenario())
