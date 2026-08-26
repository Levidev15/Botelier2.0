"""Logic tests for CONDITION evaluation and maxRetries enforcement.

These exercise the pure server-side flow engine (no DB, no LLM), so they behave
identically in live calls and the simulator. Run directly:

    python -m tests.test_flow_condition_retry

or under pytest.
"""

import asyncio

from botelier.flow_executor import (
    FlowExecutor,
    NodeType,
    parse_flow_config,
    _evaluate_condition,
)


def _cfg(nodes, edges, variables=None, initial=None):
    return parse_flow_config(
        {
            "initial_node": initial or nodes[0]["id"],
            "nodes": nodes,
            "edges": edges,
            "variables": variables or [],
        }
    )


# ---------------------------------------------------------------------------
# CONDITION operator whitelist
# ---------------------------------------------------------------------------
def test_evaluate_condition_operators():
    assert _evaluate_condition("equals", "VIP", "vip") is True
    assert _evaluate_condition("not_equals", "gold", "vip") is True
    assert _evaluate_condition("contains", "premium member", "member") is True
    assert _evaluate_condition("greater_than", "21", "18") is True
    assert _evaluate_condition("less_than", "10", "18") is True
    assert _evaluate_condition("is_empty", None, "") is True
    assert _evaluate_condition("is_empty", "x", "") is False
    assert _evaluate_condition("is_not_empty", "x", "") is True
    # Unknown operator fails closed (false branch)
    assert _evaluate_condition("regex_match", "x", "y") is False
    print("PASS: condition operators")


def test_is_empty_handles_empty_collections():
    """is_empty must treat Python empty lists/dicts and their string forms as empty.

    This is the real-world case for the GuestCentric no-rooms branch: the API
    response mapping ($.rooms[*].name) produces [] when no rooms are returned,
    and the condition node must route to the retry path rather than room selection.
    """
    # Empty Python collections
    assert _evaluate_condition("is_empty", [], "") is True,   "empty list should be empty"
    assert _evaluate_condition("is_empty", {}, "") is True,   "empty dict should be empty"
    assert _evaluate_condition("is_empty", set(), "") is True, "empty set should be empty"
    assert _evaluate_condition("is_empty", (), "") is True,   "empty tuple should be empty"
    # Serialized empty collections (stored as strings in some flow-state paths)
    assert _evaluate_condition("is_empty", "[]", "") is True,  '"[]" string should be empty'
    assert _evaluate_condition("is_empty", "{}", "") is True,  '"{}" string should be empty'
    # Non-empty collections are NOT empty
    assert _evaluate_condition("is_empty", ["Superior Room"], "") is False, "non-empty list should not be empty"
    assert _evaluate_condition("is_empty", ["a", "b"], "")    is False, "two-item list should not be empty"
    assert _evaluate_condition("is_not_empty", ["SUP"], "")   is True,  "non-empty list is_not_empty"
    print("PASS: is_empty handles empty collections and their string forms")


# ---------------------------------------------------------------------------
# CONDITION branch resolution on advance
# ---------------------------------------------------------------------------
def _condition_flow():
    nodes = [
        {"id": "init", "type": "initial", "data": {}},
        {"id": "tier", "type": "collect_slot",
         "data": {"slot": {"variableKey": "tier"}}},
        {"id": "cond", "type": "condition",
         "data": {"condition": {"variable": "tier", "operator": "equals", "value": "vip"}}},
        {"id": "vip_msg", "type": "message", "data": {"message": "VIP path"}},
        {"id": "std_msg", "type": "message", "data": {"message": "Standard path"}},
    ]
    edges = [
        {"id": "e1", "source": "init", "target": "tier"},
        {"id": "e2", "source": "tier", "target": "cond"},
        {"id": "e3", "source": "cond", "target": "vip_msg", "sourceHandle": "true"},
        {"id": "e4", "source": "cond", "target": "std_msg", "sourceHandle": "false"},
    ]
    return _cfg(nodes, edges)


def test_condition_true_branch():
    ex = FlowExecutor(_condition_flow())
    ex.state.set_variable("tier", "vip")
    ex.state.advance_to("cond")
    assert ex.state.current_node_id == "vip_msg", ex.state.current_node_id
    print("PASS: condition true branch -> vip_msg")


def test_condition_false_branch():
    ex = FlowExecutor(_condition_flow())
    ex.state.set_variable("tier", "regular")
    ex.state.advance_to("cond")
    assert ex.state.current_node_id == "std_msg", ex.state.current_node_id
    print("PASS: condition false branch -> std_msg")


# ---------------------------------------------------------------------------
# CONDITION BFS branch-following (action-node gating)
# ---------------------------------------------------------------------------
def _bfs_flow():
    nodes = [
        {"id": "msg", "type": "message", "data": {"message": "hi"}},
        {"id": "cond", "type": "condition",
         "data": {"condition": {"variable": "tier", "operator": "equals", "value": "vip"}}},
        {"id": "api_true", "type": "api_request", "data": {"api": {"method": "GET", "url": "x"}}},
        {"id": "end_false", "type": "end", "data": {}},
    ]
    edges = [
        {"id": "e1", "source": "msg", "target": "cond"},
        {"id": "e2", "source": "cond", "target": "api_true", "sourceHandle": "true"},
        {"id": "e3", "source": "cond", "target": "end_false", "sourceHandle": "false"},
    ]
    return _cfg(nodes, edges)


def test_bfs_follows_only_true_branch():
    ex = FlowExecutor(_bfs_flow())
    ex.state.current_node_id = "msg"
    ex.state.set_variable("tier", "vip")
    reachable = ex._get_reachable_action_node_ids()
    assert reachable == {"api_true"}, reachable
    print("PASS: BFS follows only true branch (api_true), not end_false")


def test_bfs_follows_only_false_branch():
    ex = FlowExecutor(_bfs_flow())
    ex.state.current_node_id = "msg"
    ex.state.set_variable("tier", "regular")
    reachable = ex._get_reachable_action_node_ids()
    assert reachable == {"end_false"}, reachable
    print("PASS: BFS follows only false branch (end_false), not api_true")


def test_bfs_transparent_when_var_unset():
    ex = FlowExecutor(_bfs_flow())
    ex.state.current_node_id = "msg"
    reachable = ex._get_reachable_action_node_ids()
    assert reachable == {"api_true", "end_false"}, reachable
    print("PASS: BFS transparent when variable unset (both branches)")


# ---------------------------------------------------------------------------
# maxRetries enforcement
# ---------------------------------------------------------------------------
def _retry_flow(with_fallback=False):
    nodes = [
        {"id": "age", "type": "collect_slot",
         "data": {"slot": {"variableKey": "age", "validation": {"min": 18}, "maxRetries": 2}}},
        {"id": "fb", "type": "message", "data": {"message": "fallback"}},
    ]
    edges = []
    if with_fallback:
        edges.append({"id": "e_fb", "source": "age", "target": "fb", "sourceHandle": "fallback"})
    variables = [{"key": "age", "type": "number", "description": "age"}]
    return _cfg(nodes, edges, variables=variables, initial="age")


def test_maxretries_reprompts_then_fallback():
    ex = FlowExecutor(_retry_flow(with_fallback=True))
    r1 = asyncio.run(ex.handle_function_call("collect_age", {"age": "10"}))
    assert r1["success"] is False and not r1.get("retry_exhausted"), r1
    assert ex.state.retry_count == 1, ex.state.retry_count
    r2 = asyncio.run(ex.handle_function_call("collect_age", {"age": "12"}))
    assert r2.get("retry_exhausted") is True, r2
    assert ex.state.current_node_id == "fb", ex.state.current_node_id
    print("PASS: maxRetries reprompt then fallback branch")


def test_maxretries_escalates_when_no_fallback():
    ex = FlowExecutor(_retry_flow(with_fallback=False), escalation_target="+15551230000")
    asyncio.run(ex.handle_function_call("collect_age", {"age": "10"}))
    r2 = asyncio.run(ex.handle_function_call("collect_age", {"age": "11"}))
    assert r2.get("retry_exhausted") is True and r2.get("action") == "transfer", r2
    assert r2.get("target") == "+15551230000", r2
    print("PASS: maxRetries escalates to human when no fallback")


def test_maxretries_graceful_end_when_nothing_configured():
    ex = FlowExecutor(_retry_flow(with_fallback=False))
    asyncio.run(ex.handle_function_call("collect_age", {"age": "10"}))
    r2 = asyncio.run(ex.handle_function_call("collect_age", {"age": "11"}))
    assert r2.get("retry_exhausted") is True and r2.get("action") == "end", r2
    assert ex.state.is_complete is True
    print("PASS: maxRetries graceful end when nothing configured")


# ---------------------------------------------------------------------------
# GuestCentric no-rooms retry loop: empty availability routes to retry path
# ---------------------------------------------------------------------------
def _gc_availability_flow():
    """Minimal replica of the GuestCentric availability → condition → no-rooms
    branch. Exercises that empty available_rooms (Python list []) routes to
    no_rooms_message and NOT to collect_room."""
    nodes = [
        {"id": "check_availability",    "type": "api_request",
         "data": {"api": {"method": "GET", "url": "x"}}},
        {"id": "condition_availability", "type": "condition",
         "data": {"condition": {"variable": "available_rooms",
                                "operator": "is_empty", "value": ""}}},
        {"id": "no_rooms_message",      "type": "message", "data": {"message": "No rooms"}},
        {"id": "collect_room",          "type": "collect_slot",
         "data": {"slot": {"variableKey": "room_type_code"}}},
    ]
    edges = [
        {"id": "e1", "source": "check_availability",    "target": "condition_availability"},
        {"id": "e2", "source": "condition_availability", "target": "no_rooms_message",
         "sourceHandle": "true"},
        {"id": "e3", "source": "condition_availability", "target": "collect_room",
         "sourceHandle": "false"},
    ]
    return _cfg(nodes, edges, initial="check_availability")


def test_empty_available_rooms_list_routes_to_retry():
    """Python empty list [] must be treated as empty by is_empty."""
    ex = FlowExecutor(_gc_availability_flow())
    ex.state.set_variable("available_rooms", [])
    ex.state.advance_to("condition_availability")
    assert ex.state.current_node_id == "no_rooms_message", (
        f"Expected no_rooms_message, got {ex.state.current_node_id!r}. "
        "is_empty did not recognise [] as empty."
    )
    print("PASS: empty available_rooms [] routes to no_rooms_message")


def test_empty_available_rooms_string_routes_to_retry():
    """Serialised '[]' string must also be treated as empty."""
    ex = FlowExecutor(_gc_availability_flow())
    ex.state.set_variable("available_rooms", "[]")
    ex.state.advance_to("condition_availability")
    assert ex.state.current_node_id == "no_rooms_message", (
        f"Expected no_rooms_message, got {ex.state.current_node_id!r}. "
        "is_empty did not recognise '[]' string as empty."
    )
    print("PASS: available_rooms='[]' string routes to no_rooms_message")


def test_nonempty_available_rooms_routes_to_collect_room():
    """When rooms are available the success path must be taken."""
    ex = FlowExecutor(_gc_availability_flow())
    ex.state.set_variable("available_rooms", ["Superior Room", "Deluxe Room"])
    ex.state.advance_to("condition_availability")
    assert ex.state.current_node_id == "collect_room", (
        f"Expected collect_room, got {ex.state.current_node_id!r}"
    )
    print("PASS: non-empty available_rooms routes to collect_room")


# ---------------------------------------------------------------------------
# GuestCentric room-rate guard: missing room_rate_code routes to reselection
# ---------------------------------------------------------------------------
def _gc_room_rate_guard_flow():
    """Minimal replica of confirm_room_rate → condition_room_rate → collect_room
    / build_hotels_array branching."""
    nodes = [
        {"id": "confirm_room_rate",  "type": "api_request",
         "data": {"api": {"method": "GET", "url": "x"}}},
        {"id": "condition_room_rate", "type": "condition",
         "data": {"condition": {"variable": "room_rate_code",
                                "operator": "is_empty", "value": ""}}},
        {"id": "collect_room",       "type": "collect_slot",
         "data": {"slot": {"variableKey": "room_type_code"}}},
        {"id": "build_hotels_array", "type": "set_variable",
         "data": {"setVariable": {"variableKey": "hotels", "value": "[]"}}},
    ]
    edges = [
        {"id": "e1", "source": "confirm_room_rate",   "target": "condition_room_rate"},
        {"id": "e2", "source": "condition_room_rate",  "target": "collect_room",
         "sourceHandle": "true"},
        {"id": "e3", "source": "condition_room_rate",  "target": "build_hotels_array",
         "sourceHandle": "false"},
    ]
    return _cfg(nodes, edges, initial="confirm_room_rate")


def test_missing_room_rate_code_routes_to_reselection():
    """When confirm_room_rate returns no match (room_rate_code is empty/None)
    the flow must route back to collect_room for reselection, not to booking."""
    ex = FlowExecutor(_gc_room_rate_guard_flow())
    # Simulate filtered re-check returning no results (code not set)
    ex.state.set_variable("room_rate_code", None)
    ex.state.advance_to("condition_room_rate")
    assert ex.state.current_node_id == "collect_room", (
        f"Expected collect_room, got {ex.state.current_node_id!r}. "
        "Missing room_rate_code should route back to room selection."
    )
    print("PASS: missing room_rate_code (None) routes to collect_room")


def test_empty_room_rate_code_string_routes_to_reselection():
    """Empty-string room_rate_code must also trigger reselection."""
    ex = FlowExecutor(_gc_room_rate_guard_flow())
    ex.state.set_variable("room_rate_code", "")
    ex.state.advance_to("condition_room_rate")
    assert ex.state.current_node_id == "collect_room", (
        f"Expected collect_room, got {ex.state.current_node_id!r}"
    )
    print("PASS: empty-string room_rate_code routes to collect_room")


def test_valid_room_rate_code_proceeds_to_booking():
    """A valid room_rate_code must proceed to build_hotels_array, not loop back."""
    ex = FlowExecutor(_gc_room_rate_guard_flow())
    ex.state.set_variable("room_rate_code", "RR-SUP-BAR-001")
    ex.state.advance_to("condition_room_rate")
    assert ex.state.current_node_id == "build_hotels_array", (
        f"Expected build_hotels_array, got {ex.state.current_node_id!r}"
    )
    print("PASS: valid room_rate_code proceeds to build_hotels_array")


# ---------------------------------------------------------------------------
# Slug-to-integration-ID resolution (no editor-panel dependency)
# ---------------------------------------------------------------------------

def _api_node_with_slug(slug: str, endpoint_id: str = "hotel_rooms") -> dict:
    """Return a minimal api_request node that carries only integrationSlug (no integrationId)."""
    return {
        "id": "check_availability",
        "type": "api_request",
        "data": {
            "api": {
                "apiSource": "integration",
                "integrationSlug": slug,
                "integrationId": "",        # ← the template state: no concrete ID
                "endpointId": endpoint_id,
                "method": "GET",
                "responseMapping": {"available_rooms": "$.rooms[*].name"},
            },
        },
    }


def _make_fake_session(connections: list):
    """Return a mock SQLAlchemy session that simulates chained query results.

    ``connections`` is the list returned by ``.all()`` for the final filter.
    A single-element list is also treated as a ``.first()`` result for compat.
    """
    from unittest.mock import MagicMock

    fake_query = MagicMock()
    # Each .join() / .filter() returns the same query mock for chaining.
    fake_query.join.return_value = fake_query
    fake_query.filter.return_value = fake_query
    fake_query.all.return_value = connections
    fake_query.first.return_value = connections[0] if connections else None

    fake_session = MagicMock()
    fake_session.query.return_value = fake_query
    return fake_session


def _make_ai(connection_id, property_id=None):
    """Return a stub AccountIntegration-like object."""
    from unittest.mock import MagicMock
    ai = MagicMock()
    ai.id = connection_id
    ai.property_id = property_id
    return ai


def _slug_flow(account_id, db_session, property_id=None):
    """Return a minimal FlowExecutor configured for slug-resolution tests."""
    cfg = _cfg(
        [{"id": "start", "type": "initial", "data": {}}],
        [],
        initial="start",
    )
    ex = FlowExecutor(cfg, db_session=db_session, account_id=account_id)
    if property_id:
        ex.property_id = property_id
    return ex


def test_slug_resolution_returns_connection_id():
    """_resolve_integration_slug must return the matching AccountIntegration ID
    for the sole CONNECTED account-global connection.  This is the runtime path
    for a template node with integrationSlug but no integrationId.
    """
    import asyncio
    import uuid

    account_id = str(uuid.uuid4())
    connection_id = str(uuid.uuid4())

    conn = _make_ai(connection_id, property_id=None)
    session = _make_fake_session([conn])

    ex = _slug_flow(account_id, session)
    resolved = asyncio.run(ex._resolve_integration_slug("guestcentric-crs"))
    assert resolved == connection_id, (
        f"Expected {connection_id!r}, got {resolved!r}. "
        "Sole connected account-global connection must be resolved."
    )
    print("PASS: _resolve_integration_slug returns AccountIntegration.id")


def test_slug_resolution_returns_none_without_session():
    """Without a db_session the resolver must fail open (return None)."""
    import asyncio

    ex = _slug_flow("some-account", db_session=None)
    resolved = asyncio.run(ex._resolve_integration_slug("guestcentric-crs"))
    assert resolved is None, f"Expected None, got {resolved!r}"
    print("PASS: _resolve_integration_slug returns None without db_session (fail-open)")


def test_slug_resolution_returns_none_for_disconnected():
    """A disconnected connection must not be resolved — the filter covers CONNECTED only."""
    import asyncio
    import uuid

    account_id = str(uuid.uuid4())
    # Session returns empty list (disconnected rows are excluded by the query filter)
    session = _make_fake_session([])

    ex = _slug_flow(account_id, session)
    resolved = asyncio.run(ex._resolve_integration_slug("guestcentric-crs"))
    assert resolved is None, (
        f"Expected None for disconnected connection, got {resolved!r}. "
        "Only CONNECTED connections should be resolved."
    )
    print("PASS: disconnected connection returns None")


def test_slug_resolution_returns_none_when_ambiguous():
    """Multiple account-global CONNECTED connections for the same slug must
    return None — the caller must supply an explicit integrationId.
    """
    import asyncio
    import uuid

    account_id = str(uuid.uuid4())
    conns = [_make_ai(str(uuid.uuid4()), property_id=None) for _ in range(2)]
    session = _make_fake_session(conns)

    ex = _slug_flow(account_id, session)
    resolved = asyncio.run(ex._resolve_integration_slug("guestcentric-crs"))
    assert resolved is None, (
        f"Expected None for ambiguous slug, got {resolved!r}. "
        "Multiple account-global connections should not be auto-selected."
    )
    print("PASS: ambiguous account-global connections return None")


def test_slug_resolution_prefers_property_scoped_connection():
    """When a property_id is set, the resolver must prefer an exact property-scoped
    connection over any account-global one.  This is validated by the query
    filtering path; the mock simulates a single property-scoped result.
    """
    import asyncio
    import uuid

    account_id = str(uuid.uuid4())
    property_id = str(uuid.uuid4())
    property_conn_id = str(uuid.uuid4())

    property_conn = _make_ai(property_conn_id, property_id=property_id)
    # Simulate: exact property-match query returns one result
    session = _make_fake_session([property_conn])

    ex = _slug_flow(account_id, session, property_id=property_id)
    resolved = asyncio.run(ex._resolve_integration_slug("guestcentric-crs"))
    assert resolved == property_conn_id, (
        f"Expected property-scoped connection {property_conn_id!r}, got {resolved!r}. "
        "Property-scoped connection should take precedence over account-global."
    )
    print("PASS: property-scoped connection preferred when property_id is set")


def test_template_api_nodes_have_integration_slug():
    """Every api_request node in the GC booking template must carry
    integrationSlug so the runtime resolver can find the connection without
    requiring the operator to open each editor panel.

    store.ts lives at botelier/frontend/components/flow-editor/store.ts relative
    to the workspace root.  Absence of the file is a hard CI failure — it means
    the test infrastructure is misconfigured, not that the file is optional.
    """
    import pathlib

    # From botelier/backend/tests/ go up 2 levels → botelier/, then to frontend
    store_ts = (
        pathlib.Path(__file__).parent.parent.parent
        / "frontend/components/flow-editor/store.ts"
    )
    assert store_ts.exists(), (
        f"store.ts not found at {store_ts}. "
        "Check that the path botelier/frontend/components/flow-editor/store.ts "
        "is correct relative to this test file."
    )

    source = store_ts.read_text()

    # Locate GUESTCENTRIC_CRS_BOOKING_TEMPLATE block heuristically:
    # extract the section between the const declaration and the next export/const.
    start = source.find("GUESTCENTRIC_CRS_BOOKING_TEMPLATE")
    assert start != -1, "Could not find GUESTCENTRIC_CRS_BOOKING_TEMPLATE in store.ts"
    end = source.find("\nexport ", start + 1)
    if end == -1:
        end = len(source)
    block = source[start:end]

    # Count api_request nodes that have integrationSlug set.
    # Template uses TypeScript object syntax (no quotes on key names).
    api_request_count = block.count('type: "api_request"')
    slug_count = block.count("integrationSlug:")

    assert api_request_count > 0, "No api_request nodes found in template block"
    assert slug_count >= api_request_count, (
        f"Only {slug_count} integrationSlug entries for {api_request_count} api_request nodes. "
        "All integration API nodes need integrationSlug for panel-free runtime resolution."
    )
    print(
        f"PASS: all {api_request_count} api_request nodes carry integrationSlug "
        f"({slug_count} slug entries found)"
    )


def test_checkout_date_enforced_against_checkin():
    """collect_checkout uses afterDateVariable: 'checkin' which is the runtime-enforced
    field (flow_executor._validate_slot_value reads afterDateVariable / after_date_variable).

    Verify that checkout on the same day as — or before — checkin is rejected,
    and checkout strictly after checkin is accepted.  This covers both the initial
    collect_checkout node and the retry_checkout node in the GC booking template.
    """
    from botelier.flow_executor import FlowVariable, SlotType

    checkin = "2025-08-20"
    slot_config = {
        "variableKey": "checkout",
        "type": "date",
        "validation": {
            "requireFuture": False,     # disable future check so any past date works for the test
            "afterDateVariable": "checkin",
        },
    }

    # Build a minimal executor with checkin in state
    cfg = _cfg(
        [{"id": "start", "type": "initial", "data": {}}],
        [],
        initial="start",
    )
    ex = FlowExecutor(cfg)
    ex.state.set_variable("checkin", checkin)

    var_info = FlowVariable(key="checkout", type=SlotType.DATE, description="Check-out date")

    # Same day as checkin → must be rejected (checkout must be STRICTLY after checkin)
    err = ex._validate_slot_value(var_info, slot_config, checkin)
    assert err is not None, (
        "Same-day checkout must be rejected (date must be after, not equal to, checkin)."
    )

    # Day before checkin → must be rejected
    err = ex._validate_slot_value(var_info, slot_config, "2025-08-19")
    assert err is not None, "Checkout before checkin must be rejected."

    # Day after checkin → must be accepted
    err = ex._validate_slot_value(var_info, slot_config, "2025-08-21")
    assert err is None, (
        f"Checkout strictly after checkin must be accepted, got error: {err!r}"
    )
    print("PASS: collect_checkout afterDateVariable constraint enforced at runtime")


ALL_TESTS = [
    test_evaluate_condition_operators,
    test_is_empty_handles_empty_collections,
    test_condition_true_branch,
    test_condition_false_branch,
    test_bfs_follows_only_true_branch,
    test_bfs_follows_only_false_branch,
    test_bfs_transparent_when_var_unset,
    test_maxretries_reprompts_then_fallback,
    test_maxretries_escalates_when_no_fallback,
    test_maxretries_graceful_end_when_nothing_configured,
    # GuestCentric-specific condition tests
    test_empty_available_rooms_list_routes_to_retry,
    test_empty_available_rooms_string_routes_to_retry,
    test_nonempty_available_rooms_routes_to_collect_room,
    test_missing_room_rate_code_routes_to_reselection,
    test_empty_room_rate_code_string_routes_to_reselection,
    test_valid_room_rate_code_proceeds_to_booking,
    # Slug resolution tests (panel-free executability)
    test_slug_resolution_returns_connection_id,
    test_slug_resolution_returns_none_without_session,
    test_slug_resolution_returns_none_for_disconnected,
    test_slug_resolution_returns_none_when_ambiguous,
    test_slug_resolution_prefers_property_scoped_connection,
    test_template_api_nodes_have_integration_slug,
    # Date constraint enforcement
    test_checkout_date_enforced_against_checkin,
]


if __name__ == "__main__":
    for t in ALL_TESTS:
        t()
    print(f"\n{len(ALL_TESTS)} tests passed.")
