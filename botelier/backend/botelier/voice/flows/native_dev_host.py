"""Explicit, fail-closed host policy for the narrow native voice development pilot."""

from dataclasses import dataclass
import hashlib
import os

from botelier.voice.flows.pilot_contract import (
    PilotAdmissionError, PilotIdentity, compile_pilot,
)


class NativeDevAdmissionError(ValueError):
    """Safe category-only refusal for an unsupported native development call."""


@dataclass(frozen=True)
class NativeFlowDevPolicy:
    """The native pilot is available only under both exact development gates."""

    environment: str | None
    enabled_value: str | None

    @property
    def enabled(self) -> bool:
        return self.environment == "development" and self.enabled_value == "1"

    @classmethod
    def from_environment(cls):
        # Keep app defaults dependent only on the two explicitly approved,
        # non-secret opt-in values.
        return cls(
            os.getenv("BOTELIER_ENV"),
            os.getenv("BOTELIER_NATIVE_FLOWS_DEV"),
        )

@dataclass(frozen=True)
class NativeDevSelection:
    """One published, admitted graph and the existing tool's LLM overrides."""

    compiled: object
    tool: object


def prepare_native_dev_selection(
    *, assistant, tools, tool_set, flow_version, call_sid,
    property_id, property_owned,
):
    """Compile the explicitly selected published FLOW, refusing other resources.

    The caller invokes this outside its legacy per-tool exception handling and
    only after resolving the current ToolSet, FlowVersion and property owner.
    """
    settings = getattr(assistant, "call_settings", None) or {}
    if not isinstance(settings, dict):
        raise NativeDevAdmissionError("native_dev_selection")
    selected_id = settings.get("native_flow_tool_id")
    if selected_id is None:
        return None
    if not isinstance(selected_id, str) or not selected_id.strip():
        raise NativeDevAdmissionError("native_dev_selection")
    if len(tools or []) != 1:
        raise NativeDevAdmissionError("native_dev_resources")

    tool = tools[0]
    tool_id = str(getattr(tool, "id", "") or "")
    if tool_id != selected_id:
        raise NativeDevAdmissionError("native_dev_selection")
    tool_type = getattr(getattr(tool, "tool_type", None), "value", None)
    if tool_type != "FLOW":
        raise NativeDevAdmissionError("native_dev_selection")

    account_id = str(getattr(assistant, "account_id", "") or "")
    assistant_property_id = str(getattr(assistant, "property_id", "") or "")
    tool_set_id = str(getattr(assistant, "tool_set_id", "") or "")
    if (
        not account_id or not assistant_property_id
        or not property_id or str(property_id) != assistant_property_id
        or not property_owned
        or not tool_set_id
        or str(getattr(tool, "tool_set_id", "") or "") != tool_set_id
        or tool_set is None
        or str(getattr(tool_set, "id", "") or "") != tool_set_id
        or str(getattr(tool_set, "account_id", "") or "") != account_id
    ):
        raise NativeDevAdmissionError("native_dev_ownership")
    tool_account_id = getattr(tool, "account_id", None)
    if tool_account_id and str(tool_account_id) != account_id:
        raise NativeDevAdmissionError("native_dev_ownership")

    published_version_id = getattr(tool, "published_version_id", None)
    if not published_version_id or flow_version is None:
        raise NativeDevAdmissionError("native_dev_published_version")
    published_version_id = str(published_version_id)
    status = getattr(getattr(flow_version, "status", None), "value", None)
    if (
        str(getattr(flow_version, "id", "") or "") != published_version_id
        or str(getattr(flow_version, "tool_id", "") or "") != tool_id
        or status != "published"
    ):
        raise NativeDevAdmissionError("native_dev_published_version")

    try:
        compiled = compile_pilot(
            getattr(flow_version, "flow_config", None),
            PilotIdentity(
                account_id=account_id,
                property_id=assistant_property_id,
                tool_id=tool_id,
                flow_version_id=published_version_id,
                call_sid=str(call_sid),
            ),
        )
    except PilotAdmissionError as exc:
        # Admission messages are already fixed safe category codes. Never echo
        # the saved graph or parser/provider details into a log or caller path.
        raise NativeDevAdmissionError(str(exc)) from None
    return NativeDevSelection(compiled=compiled, tool=tool)


def redacted_reference(value) -> str:
    """Stable diagnostic correlation without logging raw identifiers."""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
