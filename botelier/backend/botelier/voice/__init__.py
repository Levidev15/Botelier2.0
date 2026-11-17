"""Botelier Voice Engine

This module provides the core voice AI engine for Botelier.
It wraps the underlying voice AI framework as an implementation detail.
"""

from importlib import import_module

__all__ = ["VoiceAgent", "CallHandler"]

_PUBLIC_MODULES = {
    "VoiceAgent": ".agent",
    "CallHandler": ".call_handler",
}


def __getattr__(name):
    """Load heavyweight voice components only when their public names are used."""
    module_name = _PUBLIC_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
