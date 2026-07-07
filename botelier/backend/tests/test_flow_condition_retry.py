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


ALL_TESTS = [
    test_evaluate_condition_operators,
    test_condition_true_branch,
    test_condition_false_branch,
    test_bfs_follows_only_true_branch,
    test_bfs_follows_only_false_branch,
    test_bfs_transparent_when_var_unset,
    test_maxretries_reprompts_then_fallback,
    test_maxretries_escalates_when_no_fallback,
    test_maxretries_graceful_end_when_nothing_configured,
]


if __name__ == "__main__":
    for t in ALL_TESTS:
        t()
    print(f"\n{len(ALL_TESTS)} tests passed.")
