"""End-to-end integration tests: CAPABILITY node in a published flow.

Covers the full round trip that was previously untested:

  1. ``validate_flow_config`` accepts a CAPABILITY node with a known capability
     name and rejects one with a missing / unknown capability.
  2. ``FlowExecutor.handle_function_call`` dispatches ``execute_<id>`` for a
     CAPABILITY node through ``_handle_api_request`` → ``_handle_capability_request``.
  3. Fail-closed (pure): missing ``account_id`` returns a structured failure.
  4. Fail-closed (DB-backed): no connected provider → resolver returns None →
     the node returns ``success=False`` with the "not available right now"
     message without making any outbound HTTP call.
  5. Read capability (``search_availability``, DB-backed): with one connected
     provider the resolver finds it, translates variables, synthesises an
     integration api_config and delegates to ``_handle_integration_api_request``.
     The synthesised config carries the correct integration_id / endpoint_id and
     the canonical→vendor translation is applied.
  6. Mutating capability (``book_reservation``, DB-backed): the ``mutating``
     flag causes the effective method to be ``POST``, so the non-GET idempotency
     guard fires and a second concurrent ``execute_`` returns the cached result
     without re-running the write.
"""

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from botelier.api.flow_versions import validate_flow_config
from botelier.flow_executor import FlowExecutor, NodeType, parse_flow_config


# ── helpers ──────────────────────────────────────────────────────────────────


def _flow_with_capability(capability_name: str, node_id: str = "cap") -> dict:
    """Minimal flow: start → collect_slot → CAPABILITY → end."""
    return {
        "initial_node": "start",
        "variables": [
            {"key": "check_in_date", "type": "text", "description": "Check-in date"},
        ],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {
                "id": "collect_checkin",
                "type": "collect_slot",
                "data": {
                    "slot": {
                        "variableKey": "check_in_date",
                        "prompt": "What date would you like to check in?",
                    }
                },
            },
            {
                "id": node_id,
                "type": "capability",
                "data": {
                    "name": "Search Availability",
                    "api": {
                        "apiSource": "capability",
                        "capability": capability_name,
                    },
                },
            },
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "collect_checkin"},
            {"id": "e2", "source": "collect_checkin", "target": node_id},
            {"id": "e3", "source": node_id, "target": "end"},
        ],
    }


def _executor_at_capability(
    capability_name: str,
    node_id: str = "cap",
    account_id: str = None,
    db_session=None,
    property_id: str = None,
) -> FlowExecutor:
    """Build a FlowExecutor positioned on the capability node (slot already filled)."""
    config = _flow_with_capability(capability_name, node_id=node_id)
    executor = FlowExecutor(
        parse_flow_config(config),
        account_id=account_id,
        db_session=db_session,
        property_id=property_id,
    )
    executor.state.collected_slots["check_in_date"] = "2026-08-01"
    executor.state.current_node_id = node_id
    return executor


# ── 1. Validator (pure, no DB) ────────────────────────────────────────────────


def test_validator_accepts_known_capability():
    config = _flow_with_capability("search_availability")
    valid, errors = validate_flow_config(config)
    assert valid, f"Unexpected validation errors: {errors}"
    assert errors == []


def test_validator_accepts_mutating_capability():
    config = _flow_with_capability("book_reservation")
    valid, errors = validate_flow_config(config)
    assert valid, f"Unexpected validation errors: {errors}"


def test_validator_rejects_capability_node_with_no_capability():
    config = _flow_with_capability("search_availability")
    # Wipe the capability name.
    for node in config["nodes"]:
        if node["type"] == "capability":
            node["data"]["api"].pop("capability")
    valid, errors = validate_flow_config(config)
    assert not valid
    assert any("no capability selected" in e for e in errors)


def test_validator_rejects_unknown_capability_name():
    config = _flow_with_capability("teleport_guest")
    valid, errors = validate_flow_config(config)
    assert not valid
    assert any("unknown capability" in e.lower() for e in errors)


# ── 2. Dispatch routing (pure, no DB) ────────────────────────────────────────


def test_capability_node_type_is_resolved_correctly():
    """The capability node parses to NodeType.CAPABILITY (not api_request)."""
    config = _flow_with_capability("search_availability")
    executor = FlowExecutor(parse_flow_config(config))
    executor.state.current_node_id = "cap"
    node = executor.state.get_current_node()
    assert node is not None
    assert node.type == NodeType.CAPABILITY


@pytest.mark.asyncio
async def test_missing_account_id_fails_gracefully():
    """Without account_id the capability node returns a structured failure."""
    executor = _executor_at_capability("search_availability", account_id=None)
    result = await executor.handle_function_call("execute_cap", {})
    assert result["success"] is False
    assert "account context" in result["message"].lower()


@pytest.mark.asyncio
async def test_unknown_capability_name_fails_gracefully():
    """An unknown capability (validator bypassed) returns a structured failure."""
    executor = _executor_at_capability(
        "teleport_guest",
        account_id="00000000-0000-0000-0000-000000000001",
        db_session=None,
    )
    result = await executor.handle_function_call("execute_cap", {})
    assert result["success"] is False
    assert "unknown capability" in result["message"].lower()


# ── DB-backed tests ───────────────────────────────────────────────────────────

if not os.environ.get("DATABASE_URL"):
    raise RuntimeError(
        "test_flow_capability_e2e requires DATABASE_URL to be set. "
        "These tests are DB-backed and must not be silently skipped."
    )

from botelier.database import SessionLocal  # noqa: E402
from botelier.models.account import Account, AccountStatus, SubscriptionTier  # noqa: E402
from botelier.models.integration import (  # noqa: E402
    AccountIntegration,
    IntegrationStatus,
    IntegrationType,
)
from botelier.models.property import Property  # noqa: E402
from botelier.services.capabilities.resolver import CapabilityResolver  # noqa: E402

# Capability-tagged endpoint fixtures used to build IntegrationTypes.
_SEARCH_ENDPOINT = {
    "id": "search",
    "capability": "search_availability",
    "capability_params": {
        "check_in_date": "checkin",  # canonical → vendor translation
        "guest_count": "adults",
    },
    "method": "GET",
    "path": "/availability",
}

_BOOK_ENDPOINT = {
    "id": "book",
    "capability": "book_reservation",
    "capability_params": {
        "check_in_date": "checkin",
        "guest_count": "adults",
    },
    "method": "POST",
    "path": "/reservations",
}


def _make_account(db) -> Account:
    suffix = uuid.uuid4().hex[:12]
    acct = Account(
        name=f"cap-e2e-{suffix}",
        slug=f"cap-e2e-{suffix}",
        email=f"cap-e2e-{suffix}@example.invalid",
        status=AccountStatus.ACTIVE,
        subscription_tier=SubscriptionTier.FREE,
    )
    db.add(acct)
    db.flush()
    return acct


def _make_itype(db, endpoints: list) -> IntegrationType:
    itype = IntegrationType(
        slug=f"cap-e2e-type-{uuid.uuid4().hex[:8]}",
        name="Cap E2E Type",
        provider="test",
        auth_type="none",
    )
    itype.set_endpoints(endpoints)
    db.add(itype)
    db.flush()
    return itype


def _make_integration(
    db,
    account_id,
    itype_id,
    property_id=None,
    status=IntegrationStatus.CONNECTED,
) -> AccountIntegration:
    integ = AccountIntegration(
        account_id=account_id,
        integration_type_id=itype_id,
        property_id=property_id,
        status=status,
    )
    db.add(integ)
    db.flush()
    return integ


@pytest.fixture()
def db_env():
    """Account + property + db session, rolled back after each test."""
    db = SessionLocal()
    try:
        acct = _make_account(db)
        prop = Property(account_id=acct.id, name="Test Hotel")
        db.add(prop)
        db.flush()
        yield db, acct, prop
    finally:
        db.rollback()
        db.close()


# ── 3. Fail-closed: no provider connected ────────────────────────────────────


@pytest.mark.asyncio
async def test_read_capability_no_provider_fails_closed(db_env):
    """No connected integration → resolver returns None → fail-closed message."""
    db, acct, prop = db_env
    executor = _executor_at_capability(
        "search_availability",
        account_id=str(acct.id),
        db_session=db,
        property_id=str(prop.id),
    )
    result = await executor.handle_function_call("execute_cap", {})
    assert result["success"] is False
    assert "not available" in result["message"].lower()


@pytest.mark.asyncio
async def test_mutating_capability_no_provider_fails_closed(db_env):
    """book_reservation with no provider → fail-closed (mutating path)."""
    db, acct, prop = db_env

    config = {
        "initial_node": "start",
        "variables": [{"key": "check_in_date", "type": "text", "description": "ci"}],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {
                "id": "book_cap",
                "type": "capability",
                "data": {
                    "name": "Book Room",
                    "api": {"apiSource": "capability", "capability": "book_reservation"},
                },
            },
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "book_cap"},
            {"id": "e2", "source": "book_cap", "target": "end"},
        ],
    }
    executor = FlowExecutor(
        parse_flow_config(config),
        account_id=str(acct.id),
        db_session=db,
        property_id=str(prop.id),
    )
    executor.state.collected_slots["check_in_date"] = "2026-08-01"
    executor.state.current_node_id = "book_cap"
    result = await executor.handle_function_call("execute_book_cap", {})
    assert result["success"] is False
    assert "not available" in result["message"].lower()


# ── 4. Read capability with a connected provider ──────────────────────────────


@pytest.mark.asyncio
async def test_read_capability_dispatches_to_integration_request(db_env):
    """search_availability with one provider → _handle_integration_api_request
    is called with the resolved integration_id, endpoint_id, and translated
    canonical variables (check_in_date → checkin).
    """
    db, acct, prop = db_env
    itype = _make_itype(db, [_SEARCH_ENDPOINT])
    integration = _make_integration(db, acct.id, itype.id, property_id=prop.id)

    executor = _executor_at_capability(
        "search_availability",
        account_id=str(acct.id),
        db_session=db,
        property_id=str(prop.id),
    )
    executor.state.collected_slots["check_in_date"] = "2026-08-15"
    executor.state.collected_slots["guest_count"] = 2

    captured_calls = []

    async def _fake_integration_request(node_id, node, api_config, variables=None):
        captured_calls.append(
            {"node_id": node_id, "api_config": dict(api_config), "variables": dict(variables or {})}
        )
        return {
            "success": True,
            "message": "Found 3 rooms",
            "voice_result": "3 rooms available",
            "action": None,
            "current_node_id": "end",
        }

    executor._handle_integration_api_request = _fake_integration_request

    result = await executor.handle_function_call("execute_cap", {"check_in_date": "2026-08-15"})

    # The capability dispatch must have reached _handle_integration_api_request.
    assert len(captured_calls) == 1, "Expected exactly one integration request"
    call = captured_calls[0]

    # Synthesised config must point at the resolved integration + endpoint.
    assert call["api_config"]["apiSource"] == "integration"
    assert call["api_config"]["integrationId"] == str(integration.id)
    assert call["api_config"]["endpointId"] == "search"

    # Canonical→vendor variable translation must have been applied.
    # The capability_params map: check_in_date → checkin, guest_count → adults.
    # translate_variables adds vendor-key entries; original keys may also pass
    # through (documented pass-through behaviour for unmapped / extra keys).
    assert call["variables"].get("checkin") == "2026-08-15", (
        f"Expected 'checkin' in translated variables; got: {call['variables']}"
    )
    assert call["variables"].get("adults") == 2, (
        f"Expected 'adults'=2 in translated variables; got: {call['variables']}"
    )

    # The executor surfaces the mocked result verbatim.
    assert result["success"] is True


# ── 5. Mutating capability + idempotency guard ───────────────────────────────


@pytest.mark.asyncio
async def test_mutating_capability_idempotency_guard_prevents_second_write(db_env):
    """book_reservation (mutating) triggers the POST idempotency guard.

    A second concurrent execute_ for the same node must return the cached
    result from the first execution without calling the integration again.
    """
    db, acct, prop = db_env
    itype = _make_itype(db, [_BOOK_ENDPOINT])
    _make_integration(db, acct.id, itype.id, property_id=prop.id)

    config = {
        "initial_node": "start",
        "variables": [
            {"key": "check_in_date", "type": "text", "description": "ci"},
            {"key": "guest_count", "type": "number", "description": "guests"},
        ],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {
                "id": "book_cap",
                "type": "capability",
                "data": {
                    "name": "Book Room",
                    "api": {"apiSource": "capability", "capability": "book_reservation"},
                },
            },
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "book_cap"},
            {"id": "e2", "source": "book_cap", "target": "end"},
        ],
    }
    executor = FlowExecutor(
        parse_flow_config(config),
        account_id=str(acct.id),
        db_session=db,
        property_id=str(prop.id),
    )
    executor.state.collected_slots.update({"check_in_date": "2026-09-01", "guest_count": 2})
    executor.state.current_node_id = "book_cap"

    call_count = 0

    async def _fake_integration_request(node_id, node, api_config, variables=None):
        nonlocal call_count
        call_count += 1
        return {
            "success": True,
            "message": "Booked successfully",
            "voice_result": "Your reservation is confirmed",
            "action": None,
            "current_node_id": "end",
        }

    executor._handle_integration_api_request = _fake_integration_request

    # First call: executes the write.
    result1 = await executor._dispatch_function_call("execute_book_cap", {})
    assert result1["success"] is True
    assert call_count == 1

    # Second call: idempotency guard returns the cached result (no second write).
    result2 = await executor._dispatch_function_call("execute_book_cap", {})
    assert result2["success"] is True
    assert call_count == 1, (
        "Integration was called more than once — idempotency guard did not fire"
    )


@pytest.mark.asyncio
async def test_mutating_capability_concurrent_requests_deduped(db_env):
    """Concurrent execute_ calls for a mutating capability node are serialised
    so the integration fires exactly once even under simultaneous calls.
    """
    db, acct, prop = db_env
    itype = _make_itype(db, [_BOOK_ENDPOINT])
    _make_integration(db, acct.id, itype.id, property_id=prop.id)

    config = {
        "initial_node": "start",
        "variables": [{"key": "check_in_date", "type": "text", "description": "ci"}],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {
                "id": "bk",
                "type": "capability",
                "data": {
                    "name": "Book",
                    "api": {"apiSource": "capability", "capability": "book_reservation"},
                },
            },
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "bk"},
            {"id": "e2", "source": "bk", "target": "end"},
        ],
    }
    executor = FlowExecutor(
        parse_flow_config(config),
        account_id=str(acct.id),
        db_session=db,
        property_id=str(prop.id),
    )
    executor.state.collected_slots["check_in_date"] = "2026-09-15"
    executor.state.current_node_id = "bk"

    call_count = 0
    gate = asyncio.Event()

    async def _slow_integration(node_id, node, api_config, variables=None):
        nonlocal call_count
        call_count += 1
        await gate.wait()  # Simulate in-flight latency so second arrives mid-flight.
        return {
            "success": True,
            "message": "Booked",
            "voice_result": "Confirmed",
            "action": None,
            "current_node_id": "end",
        }

    executor._handle_integration_api_request = _slow_integration

    # Launch two concurrent dispatches; release the gate after both are queued.
    async def _dispatch():
        return await executor._dispatch_function_call("execute_bk", {})

    task1 = asyncio.create_task(_dispatch())
    task2 = asyncio.create_task(_dispatch())

    # Let both tasks start and queue on the lock.
    await asyncio.sleep(0)
    gate.set()

    r1, r2 = await asyncio.gather(task1, task2)

    assert r1["success"] is True
    assert r2["success"] is True
    assert call_count == 1, (
        f"Integration fired {call_count} times under concurrent execution — "
        "idempotency lock did not serialise correctly"
    )


# ── SMS path: execute_sync + contact_ref ─────────────────────────────────────
#
# The SMS service does NOT use FlowExecutor. It calls
# ``CapabilityResolver.execute_sync()`` directly, supplying the SMS
# conversation id as ``contact_ref`` (no call_sid). These tests drive that
# code path end-to-end to verify:
#   1. Fail-closed: no provider or unknown capability → structured error dict.
#   2. Connected provider: correct integration + endpoint resolution, canonical
#      → vendor variable translation, and no idempotency key on reads.
#   3. Mutating capability: idempotency key is scoped to contact_ref so two
#      different SMS conversations with identical arguments produce distinct
#      keys, while a retry within the same conversation gets the same key.


def test_sms_execute_sync_fail_closed_no_provider(db_env):
    """No connected provider → execute_sync returns an unavailable error dict."""
    db, acct, prop = db_env
    resolver = CapabilityResolver(db, str(acct.id), str(prop.id))
    result = resolver.execute_sync(
        "search_availability",
        channel="sms",
        arguments={"check_in_date": "2026-08-01"},
        contact_ref="sms-conv-001",
    )
    assert result.get("status") in ("unavailable", "failed"), (
        f"Expected unavailable/failed status, got: {result}"
    )
    error_text = (result.get("error") or "").lower()
    assert "available" in error_text, (
        f"Expected 'available' in error message, got: {result}"
    )


def test_sms_execute_sync_unknown_capability_fail_closed(db_env):
    """Unknown capability → execute_sync returns a failed error dict."""
    db, acct, prop = db_env
    resolver = CapabilityResolver(db, str(acct.id), str(prop.id))
    result = resolver.execute_sync(
        "teleport_guest",
        channel="sms",
        arguments={},
        contact_ref="sms-conv-002",
    )
    assert result.get("status") == "failed"
    assert "unknown" in (result.get("error") or "").lower()


def test_sms_execute_sync_read_capability_translates_variables(db_env):
    """execute_sync with a connected provider dispatches execute_action_sync
    with translated vendor variables and no idempotency key (read = non-mutating).
    """
    from unittest.mock import MagicMock, patch

    from botelier.services.action_executor import ActionExecutionResult

    db, acct, prop = db_env
    itype = _make_itype(db, [_SEARCH_ENDPOINT])
    integration = _make_integration(db, acct.id, itype.id, property_id=prop.id)

    captured: list = []

    def _fake_execute_sync(db_arg, request):
        captured.append(request)
        mock_result = MagicMock(spec=ActionExecutionResult)
        mock_result.success = True
        mock_result.canonical = None
        mock_result.extracted_variables = {"rooms": [{"id": "101"}]}
        mock_result.data = None
        mock_result.error_type = None
        mock_result.error_message = None
        mock_result.status_code = 200
        return mock_result

    resolver = CapabilityResolver(db, str(acct.id), str(prop.id))
    with patch(
        "botelier.services.action_executor.execute_action_sync",
        side_effect=_fake_execute_sync,
    ):
        result = resolver.execute_sync(
            "search_availability",
            channel="sms",
            arguments={"check_in_date": "2026-08-15", "guest_count": 2},
            contact_ref="sms-conv-003",
        )

    assert len(captured) == 1, "Expected exactly one execute_action_sync call"
    req = captured[0]

    # Must resolve to the correct integration and endpoint.
    assert req.integration_config.integration_id == str(integration.id)
    assert req.integration_config.endpoint_id == "search"

    # Canonical → vendor variable translation:
    #   check_in_date → checkin, guest_count → adults (from _SEARCH_ENDPOINT capability_params).
    assert req.variables.get("checkin") == "2026-08-15", (
        f"Expected 'checkin' in translated vars; got: {req.variables}"
    )
    assert req.variables.get("adults") == 2, (
        f"Expected 'adults'=2 in translated vars; got: {req.variables}"
    )

    # Non-mutating capability → no idempotency key.
    assert req.idempotency_key is None, (
        f"Read capability must not carry an idempotency key; got: {req.idempotency_key}"
    )

    # Result is surfaced correctly.
    assert result.get("data") is not None


def test_sms_execute_sync_mutating_idempotency_scoped_to_contact_ref(db_env):
    """book_reservation via execute_sync (SMS path):

    Captures the ActionExecutionRequest that execute_sync passes to
    execute_action_sync and asserts directly on its idempotency_key:

    - Two different SMS conversations with identical arguments produce distinct
      idempotency keys (no cross-conversation collision).
    - A retry from the same conversation produces the same key (dedup).
    - Mutating capability always carries an idempotency key (never None).
    - Channel is "sms" and call_sid is None on every request.
    """
    from unittest.mock import MagicMock, patch

    from botelier.services.action_executor import ActionExecutionResult

    db, acct, prop = db_env
    itype = _make_itype(db, [_BOOK_ENDPOINT])
    _make_integration(db, acct.id, itype.id, property_id=prop.id)

    args = {"check_in_date": "2026-09-01", "guest_count": 2}
    captured_requests: list = []

    def _fake_execute(db_arg, request):
        captured_requests.append(request)
        mock_result = MagicMock(spec=ActionExecutionResult)
        mock_result.success = True
        mock_result.canonical = None
        mock_result.extracted_variables = None
        mock_result.data = {"reservation_id": "res-xyz"}
        mock_result.error_type = None
        mock_result.error_message = None
        mock_result.status_code = 200
        return mock_result

    with patch(
        "botelier.services.action_executor.execute_action_sync",
        side_effect=_fake_execute,
    ):
        # Conversation A — first call.
        CapabilityResolver(db, str(acct.id), str(prop.id)).execute_sync(
            "book_reservation",
            channel="sms",
            arguments=args,
            contact_ref="sms-conv-A",
        )

        # Conversation B — different contact, identical args.
        CapabilityResolver(db, str(acct.id), str(prop.id)).execute_sync(
            "book_reservation",
            channel="sms",
            arguments=args,
            contact_ref="sms-conv-B",
        )

        # Retry from conversation A — same contact, same args.
        CapabilityResolver(db, str(acct.id), str(prop.id)).execute_sync(
            "book_reservation",
            channel="sms",
            arguments=args,
            contact_ref="sms-conv-A",
        )

    assert len(captured_requests) == 3, (
        f"Expected 3 execute_action_sync calls, got {len(captured_requests)}"
    )
    req_a, req_b, req_retry = captured_requests

    # Mutating → every request must carry a non-None idempotency key.
    assert req_a.idempotency_key is not None, (
        "Conversation A: mutating capability must carry an idempotency key"
    )
    assert req_b.idempotency_key is not None, (
        "Conversation B: mutating capability must carry an idempotency key"
    )
    assert req_retry.idempotency_key is not None, (
        "Conversation A retry: mutating capability must carry an idempotency key"
    )

    # Different conversations with identical args → distinct keys (no collision).
    assert req_a.idempotency_key != req_b.idempotency_key, (
        "Cross-conversation collision: identical args in different SMS conversations "
        "produced the same idempotency key"
    )

    # Same conversation, same args → same key (retry/reconnect dedups to one write).
    assert req_retry.idempotency_key == req_a.idempotency_key, (
        "Retry from the same conversation must reproduce the original idempotency key"
    )

    # SMS semantics: no call_sid, channel is "sms" on all requests.
    for req in captured_requests:
        assert req.context.call_sid is None, (
            f"SMS capability must not set call_sid; got: {req.context.call_sid}"
        )
        assert req.context.channel == "sms", (
            f"SMS capability must use channel='sms'; got: {req.context.channel}"
        )
