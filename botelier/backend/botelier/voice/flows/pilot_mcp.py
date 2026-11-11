"""Native handler-format bridge for an already authorized host MCP catalogue.

No discovery, credentials or transport lives here. The original coordinator
handler retains its isolated MCP session, UCP metadata and timing behavior.
"""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from pipecat.flows import FlowsFunctionSchema


@dataclass(frozen=True)
class _HostMCPInvocation:
    """Only the fields consumed by the existing coordinator's MCP handler.

    This is not a fabricated FunctionCallParams: native Flows retains the real
    outer call ID/context/callback and commits its result exactly once.
    """

    function_name: str
    arguments: dict
    result_callback: Callable


def _handler(name, host_handler):
    async def invoke(arguments, manager):
        delivered = []

        async def capture(result: Any, *, properties=None):
            if delivered:
                raise RuntimeError("mcp_multiple_results")
            delivered.append(result)

        await host_handler(_HostMCPInvocation(
            function_name=name, arguments=deepcopy(arguments), result_callback=capture,
        ))
        if len(delivered) != 1:
            raise RuntimeError("mcp_missing_result")
        return delivered[0]

    return invoke


def native_mcp_globals(schemas, handlers, *, reserved_names):
    """Reserve ALL native names before exposing the surviving host globals."""
    globals_ = []
    seen = set()
    for schema in schemas:
        name = schema.name
        if name in reserved_names:
            continue
        if name in seen or name not in handlers or not callable(handlers[name]):
            raise ValueError("mcp_catalogue_invalid")
        seen.add(name)
        globals_.append(FlowsFunctionSchema(
            name=name, description=schema.description,
            properties=deepcopy(schema.properties), required=list(schema.required or []),
            handler=_handler(name, handlers[name]), cancel_on_interruption=True,
        ))
    return globals_
