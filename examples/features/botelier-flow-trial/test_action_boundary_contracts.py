"""Real action/client/flow code with only HTTP and storage I/O replaced."""

import asyncio
from unittest.mock import patch

import httpx
import pytest

from botelier.flow_executor import FlowExecutor, parse_flow_config
from botelier.services.action_executor import ActionContext, ActionExecutionRequest, ActionExecutor
from botelier.services.integration_client import IntegrationAPIConfig, IntegrationClient
from botelier.services.ssrf_safe_transport import SSRFSafeTransport
from node_contract_io import (
    ACCOUNT, API_URL, CONNECTION, PROPERTY, ActionRecords, flow_config, synthetic_integration,
)


@pytest.mark.parametrize("method,count", [
    ("GET", 3), ("HEAD", 3), ("OPTIONS", 3),
    ("POST", 1), ("PUT", 1), ("PATCH", 1), ("DELETE", 1),
])
@pytest.mark.parametrize("failure", ["timeout", "network"])
def test_shared_integration_client_never_retries_an_uncertain_mutation(method, count, failure):
    """All channels share this client; transport failures must obey its method policy."""
    async def scenario():
        records = ActionRecords(synthetic_integration())
        session = records.session()
        requests = []

        async def transport(_transport, request):
            assert str(request.url) == API_URL
            assert request.method == method
            requests.append(request)
            exception = httpx.ReadTimeout if failure == "timeout" else httpx.ReadError
            raise exception("Synthetic transport failure", request=request)

        try:
            client = IntegrationClient(ACCOUNT, db=session, property_id=PROPERTY)
            with patch.object(SSRFSafeTransport, "handle_async_request", transport):
                result = await client.execute_request(IntegrationAPIConfig(
                    integration_id=CONNECTION, method=method, path="/search", retry_count=2,
                ), {})
        finally:
            session.close()
        assert len(requests) == count
        assert result.success is False
        assert result.error_type.value == ("timeout" if failure == "timeout" else "network_error")
        assert len(records.writes) == 1
        assert records.writes[0].success is False
        assert all(session.closed for session in records.sessions)
    asyncio.run(scenario())


@pytest.mark.parametrize("path,expected", [
    ("$.rooms[0].price", {"value": 0}),
    ("rooms.1.name", {"value": "Deluxe"}),
    ("$.rooms[*].name", {"value": ["Standard", "Deluxe"]}),
    ("$.available", {"value": False}),
    ("$.rooms[9].name", {}),
    ("$.missing", {}),
])
def test_custom_action_response_mapping_matches_the_shared_jsonpath_dialect(path, expected):
    """Mapping happens after real HTTP parsing, not via an extracted/mirrored method."""
    async def scenario():
        records = ActionRecords()
        session = records.session()

        async def transport(_transport, request):
            assert request.method == "GET" and str(request.url) == API_URL
            return httpx.Response(200, json={
                "rooms": [{"name": "Standard", "price": 0}, {"name": "Deluxe", "price": 25}],
                "available": False,
            }, request=request)

        try:
            with patch.object(SSRFSafeTransport, "handle_async_request", transport):
                result = await ActionExecutor(session).execute_and_log(ActionExecutionRequest(
                    context=ActionContext(account_id=ACCOUNT, channel="flow"),
                    legacy_config={"url": API_URL, "responseMapping": {"value": path}},
                ))
        finally:
            session.close()
        assert result.success is True
        assert result.extracted_variables == expected
        assert [type(row).__name__ for row in records.writes] == [
            "IntegrationActionInvocation", "IntegrationCallLog",
        ]
    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_competing_same_node_calls_complete_once_without_deadlock_or_rewind(method):
    """Removing the outer entry lock can deadlock; removing dispatch gating replays I/O."""
    async def scenario():
        records = ActionRecords()
        executor = FlowExecutor(
            parse_flow_config(flow_config(method=method)), account_id=ACCOUNT,
            session_factory=records.session,
        )
        executor.state.advance_to("lookup")
        executor.state.set_variable("query", "standard")
        started = asyncio.Event()
        release = asyncio.Event()
        requests = []

        async def transport(_transport, request):
            assert str(request.url) == API_URL + "?query=standard"
            assert request.method == method
            requests.append(request)
            started.set()
            await release.wait()
            return httpx.Response(200, json={
                "rooms": [{"name": "Standard", "price": 0}],
            }, request=request)

        with patch.object(SSRFSafeTransport, "handle_async_request", transport):
            first = asyncio.create_task(executor.handle_function_call("execute_lookup", {}))
            await asyncio.wait_for(started.wait(), timeout=2)
            second = asyncio.create_task(executor.handle_function_call("execute_lookup", {}))
            release.set()
            results = await asyncio.wait_for(asyncio.gather(first, second), timeout=3)
        assert [result["success"] for result in results] == [True, False]
        assert results[1]["out_of_order"] is True
        assert executor.state.current_node_id == "choice"
        assert executor.state.collected_slots["price"] == 0
        assert len(requests) == 1
        assert all(session.closed for session in records.sessions)
    asyncio.run(scenario())
