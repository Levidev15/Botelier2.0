"""Voice MCP schemas must be present in the initial Pipecat LLM context."""

from unittest.mock import MagicMock

from pipecat.adapters.schemas.function_schema import FunctionSchema

from botelier.voice.call_handler import _merge_voice_mcp_tools


def _schema(name: str) -> FunctionSchema:
    return FunctionSchema(
        name=name,
        description=f"Run {name}",
        properties={},
        required=[],
    )


def test_voice_mcp_merge_filters_enabled_tools_and_preserves_native_collision():
    native_handler = MagicMock(name="native-handler")
    mcp_handler = MagicMock(name="mcp-handler")
    function_schemas = [_schema("lookup_guest")]
    function_handlers = {"lookup_guest": native_handler}

    selected, collisions = _merge_voice_mcp_tools(
        function_schemas=function_schemas,
        function_handlers=function_handlers,
        discovered_tools=[
            _schema("lookup_guest"),
            _schema("check_weather"),
            _schema("disabled_tool"),
        ],
        enabled_names={"lookup_guest", "check_weather"},
        mcp_handler=mcp_handler,
    )

    assert [tool.name for tool in selected] == ["check_weather"]
    assert collisions == ["lookup_guest"]
    assert [schema.name for schema in function_schemas] == [
        "lookup_guest",
        "check_weather",
    ]
    assert function_handlers["lookup_guest"] is native_handler
    assert function_handlers["check_weather"] is mcp_handler
    assert "disabled_tool" not in function_handlers