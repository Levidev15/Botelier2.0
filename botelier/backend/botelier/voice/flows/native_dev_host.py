"""Explicit, fail-closed host policy for the narrow native voice development pilot."""

from dataclasses import dataclass
from datetime import datetime, timezone
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


def ensure_native_dev_resources(
    assistant, *, mcp_connection_data=None, mcp_enabled_tools=None,
) -> None:
    """Refuse unsupported global resources before any client is constructed."""
    settings = getattr(assistant, "call_settings", None) or {}
    if not isinstance(settings, dict):
        raise NativeDevAdmissionError("native_dev_selection")
    if (
        getattr(assistant, "mcp_connection_id", None)
        or getattr(assistant, "mcp_enabled_tools", None)
        or mcp_connection_data
        or mcp_enabled_tools
        or settings.get("escalation_number")
    ):
        raise NativeDevAdmissionError("native_dev_resources")


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
    ensure_native_dev_resources(assistant)
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


def apply_native_pilot_context(config, *, assistant, tool, now=None) -> None:
    """Apply the same native host policy and selected-tool overrides everywhere.

    ``runtime_has_flow`` specifically opts the clock updater into *legacy*
    FlowExecutor behavioral rules. Native node instructions belong exclusively
    to FlowManager and must not gain a second controller's instructions when the
    clock refreshes. Business identity is part of the stable private prefix so
    that refresh cannot silently discard it.
    """
    from botelier.voice.prompt_context import (
        build_business_context_segment, build_runtime_system_prompt,
    )

    business_context = build_business_context_segment(
        getattr(assistant, "business_name", None),
    )
    private_prefix = "\n\n".join(
        part for part in (config.system_prompt, business_context) if part
    )
    config.runtime_assistant_prompt = private_prefix
    config.runtime_flow_personas = []
    config.runtime_has_flow = False
    config.runtime_has_past_date_slot = False
    config.system_prompt = build_runtime_system_prompt(
        private_prefix, [], config.timezone,
        now=now if now is not None else datetime.now(timezone.utc),
    )
    overrides = {
        key: getattr(tool, key, None)
        for key in (
            "llm_provider", "llm_model", "llm_temperature", "llm_max_tokens",
        )
    }
    for key in ("llm_provider", "llm_model"):
        if overrides[key]:
            setattr(config, key, overrides[key])
    for key in ("llm_temperature", "llm_max_tokens"):
        if overrides[key] is not None:
            setattr(config, key, overrides[key])
    if not any(value is not None for value in overrides.values()):
        if assistant.temperature is None:
            config.llm_temperature = 0.4


def redacted_reference(value) -> str:
    """Stable diagnostic correlation without logging raw identifiers."""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
