"""Synthetic tool catalogue with real mapper dispatch and legacy flow speech.

Catalogue persistence/authorization and durable flow snapshots are outside this
transcript checkpoint. The flow executor is deliberately ephemeral; no business
API/MCP, phone or database operation can be reached.
"""

from types import SimpleNamespace

from application_support import load_function_mapper
from lifecycle_io import CALL_SID


FLOW_INTRO = "I can help with your fixture request."
FLOW_PROMPT = "Which fixture would you like?"
TOOL_PREFACE = "I will check that fixture now."
TOOL_RESULT = {"status": "ok", "label": "ready", "internal_marker": "private-fixture-data"}


def mapper_for(call):
    mapper = load_function_mapper().FunctionMapper(
        call_sid=CALL_SID, call_handler=call.handler, account_id="offline-account",
    )
    call.handler.call_mappers[CALL_SID] = mapper
    return mapper


def flow_tools(call):
    from botelier.flow_executor import FlowExecutor, parse_flow_config
    from pipecat.adapters.schemas.function_schema import FunctionSchema

    config = {
        "initial_node": "start",
        "variables": [{"key": "label", "type": "string", "description": "Fixture label"}],
        "nodes": [
            {
                "id": "start", "type": "initial",
                "data": {"greeting": FLOW_INTRO, "waitForResponse": False},
            },
            {
                "id": "label", "type": "collect_slot",
                "data": {"slot": {"variableKey": "label", "prompt": FLOW_PROMPT}},
            },
        ],
        "edges": [{"id": "fixture-edge", "source": "start", "target": "label"}],
    }
    mapper = mapper_for(call)
    mapper._flow_executors["fixture"] = FlowExecutor(parse_flow_config(config))
    call.records.call.flow_name = None
    call.records.call.flow_id = None
    schemas, handlers = mapper.get_flow_functions(SimpleNamespace(
        id="offline-flow", name="fixture", description="Choose a fixture", config=config,
    ))
    return [
        FunctionSchema(
            name=item["function"]["name"],
            description=item["function"]["description"],
            properties=item["function"]["parameters"].get("properties", {}),
            required=item["function"]["parameters"].get("required", []),
        )
        for item in schemas
    ], {
        name: mapper.wrap_with_timestamp(name, handler)
        for name, handler in handlers.items()
    }


def lookup_tools(call):
    from pipecat.adapters.schemas.function_schema import FunctionSchema

    mapper = mapper_for(call)

    async def lookup(params):
        # The business result is the fake external boundary. Native function
        # parsing/result frames, context update and model continuation stay real.
        assert params.arguments == {}
        await params.result_callback(dict(TOOL_RESULT))

    return [
        FunctionSchema(
            name="lookup_fixture", description="Look up the synthetic fixture",
            properties={}, required=[],
        )
    ], {"lookup_fixture": mapper.wrap_with_timestamp("lookup_fixture", lookup)}


def tool_reply(name, *, text=None):
    reply = {
        "tool_calls": [{
            "index": 0, "id": "offline-transcript-tool", "type": "function",
            "function": {"name": name, "arguments": "{}"},
        }],
    }
    if text:
        reply["content"] = text
    return reply
