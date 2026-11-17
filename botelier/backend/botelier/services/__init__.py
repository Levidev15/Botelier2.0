"""Botelier Services.

Provides business logic services for the Botelier platform.
"""

from importlib import import_module

__all__ = [
    "CallLogger",
    "MCPClient",
    "MCPClientPool",
    "mcp_client_pool",
    "test_mcp_connection",
]

_PUBLIC_EXPORTS = {
    "CallLogger": (".call_logger", "CallLogger"),
    "MCPClient": (".mcp_client", "MCPClient"),
    "MCPClientPool": (".mcp_client", "MCPClientPool"),
    "mcp_client_pool": (".mcp_client", "mcp_client_pool"),
    "test_mcp_connection": (".mcp_client", "test_mcp_connection"),
}


def __getattr__(name):
    """Keep pure service submodules importable without eager service startup."""
    target = _PUBLIC_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
