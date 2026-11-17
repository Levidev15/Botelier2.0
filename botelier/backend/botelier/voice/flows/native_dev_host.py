"""Explicit, fail-closed host policy for native voice development flows."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os

from botelier.voice.flows.native_graph import CompiledFlow, NativeGraphError, compile_flow
from botelier.voice.flows.pilot_contract import PilotIdentity


class NativeDevAdmissionError(ValueError):
    """Safe category-only refusal for an unsupported native development call."""


@dataclass(frozen=True)
class NativeFlowDevPolicy:
    """Native flows are available only under both exact development gates."""

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

    compiled: CompiledFlow
    tool: object


def ensure_native_dev_resources(
    assistant, *, mcp_connection_data=None, mcp_enabled_tools=None,
) -> None:
    """Validate the shared selection envelope without blanket resource bans.

    MCP authority is checked against the selected graph and the current
    connection policy by NativeActionRunner before a global schema is exposed.
    Assistant escalation remains an explicitly configured FunctionMapper
    capability; it is not a reason to reject native flow admission.
    """
    settings = getattr(assistant, "call_settings", None) or {}
    if not isinstance(settings, dict):
        raise NativeDevAdmissionError("native_dev_selection")


def prepare_native_dev_selection(
    *, assistant, tools, tool_set, flow_version, call_sid,
    property_id, property_owned, requested_tool_id=None,
):
    """Compile the exact owned published FLOW, never a first-tool fallback.

    The caller invokes this outside its legacy per-tool exception handling and
    only after resolving the current ToolSet, FlowVersion and property owner.
    Test Lab may supply its separately authorized source tool without changing
    the assistant's voice-call selection or routing.
    """
    settings = getattr(assistant, "call_settings", None) or {}
    if not isinstance(settings, dict):
        raise NativeDevAdmissionError("native_dev_selection")
    selected_id = (
        requested_tool_id if requested_tool_id is not None
        else settings.get("native_flow_tool_id")
    )
    if selected_id is None:
        return None
    if not isinstance(selected_id, str) or not selected_id.strip():
        raise NativeDevAdmissionError("native_dev_selection")
    ensure_native_dev_resources(assistant)
    if not isinstance(tools, (list, tuple)):
        raise NativeDevAdmissionError("native_dev_selection")
    matches = [
        tool for tool in tools
        if str(getattr(tool, "id", "") or "") == selected_id
    ]
    if len(matches) != 1:
        raise NativeDevAdmissionError("native_dev_selection")
    tool = matches[0]
    tool_id = str(getattr(tool, "id", "") or "")
    if getattr(tool, "is_active", None) != "true":
        raise NativeDevAdmissionError("native_dev_resources")
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
        compiled = compile_flow(
            getattr(flow_version, "flow_config", None),
            PilotIdentity(
                account_id=account_id,
                property_id=assistant_property_id,
                tool_id=tool_id,
                flow_version_id=published_version_id,
                call_sid=str(call_sid),
            ),
        )
    except NativeGraphError as exc:
        # Admission messages are already fixed safe category codes. Never echo
        # the saved graph or parser/provider details into a log or caller path.
        raise NativeDevAdmissionError(str(exc)) from None
    return NativeDevSelection(compiled=compiled, tool=tool)


def prepare_native_dev_catalogue(
    *, assistant, tools, tool_set, db, call_sid, property_id,
    property_owned, selected,
):
    """Compile only the other currently assigned, published native flows."""
    from botelier.models.flow_version import FlowVersion, FlowVersionStatus

    catalogue = {
        str(selected.tool.id): {
            "compiled": selected.compiled,
            "name": str(getattr(selected.tool, "name", "") or ""),
            "description": str(getattr(selected.tool, "description", "") or ""),
        },
    }
    for tool in tools:
        tool_id = str(getattr(tool, "id", "") or "")
        if (
            not tool_id or tool_id in catalogue
            or getattr(tool, "is_active", None) != "true"
            or getattr(getattr(tool, "tool_type", None), "value", None) != "FLOW"
            or str(getattr(tool, "tool_set_id", "") or "")
            != str(getattr(assistant, "tool_set_id", "") or "")
        ):
            continue
        version_id = getattr(tool, "published_version_id", None)
        if not version_id:
            continue
        version = db.query(FlowVersion).filter(
            FlowVersion.id == version_id,
            FlowVersion.tool_id == tool.id,
            FlowVersion.status == FlowVersionStatus.PUBLISHED,
        ).first()
        if version is None:
            continue
        try:
            flow = prepare_native_dev_selection(
                assistant=assistant,
                tools=tools,
                tool_set=tool_set,
                flow_version=version,
                call_sid=call_sid,
                property_id=property_id,
                property_owned=property_owned,
                requested_tool_id=tool_id,
            )
        except NativeDevAdmissionError:
            # A broken/unpublished alternate must not poison a valid selected
            # flow or become a caller-selectable route.
            continue
        catalogue[tool_id] = {
            "compiled": flow.compiled,
            "name": str(getattr(tool, "name", "") or ""),
            "description": str(getattr(tool, "description", "") or ""),
        }
    return catalogue


def apply_native_flow_context(config, *, assistant, tool, now=None) -> None:
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


# Compatibility import for callers migrated in separate, tested checkpoints.
apply_native_pilot_context = apply_native_flow_context


def redacted_reference(value) -> str:
    """Stable diagnostic correlation without logging raw identifiers."""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
