"""Nested API JSON is structure, not an unmatched template delimiter."""

from copy import deepcopy

import pytest


TEMPLATE = '{"search":{"filters":{"children":{{children}}},"payload":{{payload}}}}'


def nested_api_definition(source):
    config = {
        "custom": {"apiSource": "custom", "method": "POST", "url": "https://api.example.invalid/search"},
        "mcp": {"apiSource": "mcp", "mcpConnectionId": "synthetic-mcp", "mcpToolName": "search"},
        "tool": {"apiSource": "tool", "toolId": "synthetic-api"},
        "capability": {"apiSource": "capability", "capability": "search_availability"},
    }[source]
    config["bodyTemplate" if source == "custom" else "argumentsTemplate"] = TEMPLATE
    return {
        "initial_node": "start",
        "variables": [{"key": "children", "type": "number"}, {"key": "payload", "type": "text"}],
        "nodes": [
            {"id": "start", "type": "initial", "data": {"greeting": "", "waitForResponse": False}},
            {"id": "confirm", "type": "confirmation", "data": {"confirmation": {
                "summaryTemplate": "Proceed with this search?", "confirmPrompt": "Proceed?",
                "variablesToConfirm": ["children", "payload"], "allowEdit": False,
                "deliveryMode": "static",
            }}},
            {"id": "invoke", "type": "api_request", "data": {"api": config}},
            {"id": "done", "type": "end", "data": {"closingMessage": ""}},
        ],
        "edges": [
            {"id": "start-confirm", "source": "start", "target": "confirm"},
            {"id": "confirm-invoke", "source": "confirm", "target": "invoke", "sourceHandle": "confirmed"},
            {"id": "invoke-done", "source": "invoke", "target": "done", "sourceHandle": "success"},
        ],
    }


@pytest.mark.parametrize("source", ["custom", "mcp", "tool", "capability"])
def test_nested_json_configuration_compiles_and_keeps_typed_values(source):
    from botelier.services.request_templates import render_json_template
    from botelier.voice.flows.native_graph import compile_flow
    from test_native_graph import identity

    config = nested_api_definition(source)
    compiled = compile_flow(config, identity())
    key = "bodyTemplate" if source == "custom" else "argumentsTemplate"
    actual = compiled.node("invoke").data()["api"][key]
    payload = {"code": 'A"B', "enabled": False, "items": []}
    assert actual == TEMPLATE
    assert render_json_template(actual, {"children": 0, "payload": payload}) == {
        "search": {"filters": {"children": 0}, "payload": payload},
    }


@pytest.mark.parametrize("source", ["custom", "mcp", "tool", "capability"])
@pytest.mark.parametrize("invalid", [
    '{"search":{"filters":{"children":{{missing}}}}}',
    '{"search":{"value":"{{payload"}}}',
    '{"search":{{payload}}',
])
def test_nested_json_still_rejects_unknown_refs_bad_tokens_and_invalid_json(source, invalid):
    from botelier.voice.flows.native_graph import NativeGraphError, compile_flow
    from test_native_graph import identity

    config = deepcopy(nested_api_definition(source))
    key = "bodyTemplate" if source == "custom" else "argumentsTemplate"
    config["nodes"][2]["data"]["api"][key] = invalid
    with pytest.raises(NativeGraphError, match="api_template"):
        compile_flow(config, identity())
