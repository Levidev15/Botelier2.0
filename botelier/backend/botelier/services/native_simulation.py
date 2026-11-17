"""Authoritative, development-only source admission for native simulations.

The app selects and authorizes one immutable published graph here. Pipecat
Flows, not this module, owns every runtime node and transition.
"""

from dataclasses import dataclass
import asyncio
import importlib.util
import json
import math
import os
import re

from loguru import logger

from botelier.models.flow_version import FlowVersion, FlowVersionStatus
from botelier.models.tool import Tool
from botelier.models.tool_set import ToolSet
from botelier.services.native_simulation_session import NativeSimulationError
from botelier.services.property_scope import property_belongs_to_account
from botelier.voice.assistant_config import build_assistant_agent_config
from botelier.voice.flows.native_dev_host import (
    NativeDevAdmissionError,
    NativeFlowDevPolicy,
    apply_native_flow_context,
    ensure_native_dev_resources,
    prepare_native_dev_catalogue,
    prepare_native_dev_selection,
)


_ADMISSION_CODES = frozenset({
    "native_dev_selection", "native_dev_resources", "native_dev_ownership",
    "native_dev_published_version",
})
_MAX_PRIVATE_PROMPT_BYTES = 64 * 1024
_MAX_COMPLETION_TOKENS = 32768


@dataclass(frozen=True)
class NativeSimulationPlan:
    """Server-owned snapshot; never serialize the private agent configuration."""

    compiled: object
    config: object
    runtime: dict
    variables_to_collect: list[dict]
    global_functions: tuple = ()
    available_flows: dict = None
    preview: object = None


def validate_native_simulation_source(request, policy) -> None:
    """Refuse ambiguous sources before touching metadata or provider clients."""
    if not policy.enabled:
        raise NativeSimulationError("native_dev_disabled", 403)
    if request.engine != "native_pilot" or request.source != "published":
        raise NativeSimulationError("native_simulation_published_source_required")
    if (
        type(request.source_version) is not int
        or not 1 <= request.source_version <= 2_147_483_647
    ):
        raise NativeSimulationError("native_simulation_version_required")
    if not isinstance(request.assistant_id, str) or not request.assistant_id:
        raise NativeSimulationError("native_dev_selection")


def _validate_model_configuration(config) -> None:
    # Match the current voice engine's two implemented SDK paths. Never
    # silently substitute OpenAI for a configured Gemini model.
    provider = config.llm_provider.lower()
    if provider not in {"openai", "google_gemini"}:
        raise NativeSimulationError("native_simulation_provider_unsupported")
    if provider == "google_gemini":
        try:
            google_sdk_available = importlib.util.find_spec("google.genai") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            google_sdk_available = False
        if not google_sdk_available:
            raise NativeSimulationError("native_simulation_provider_unsupported")
    if (
        not isinstance(config.llm_model, str)
        or not config.llm_model.strip()
        or len(config.llm_model) > 128
        or isinstance(config.llm_temperature, bool)
        or not isinstance(config.llm_temperature, (int, float))
        or not math.isfinite(config.llm_temperature)
        or not 0 <= config.llm_temperature <= 2
        or type(config.llm_max_tokens) is not int
        or not 1 <= config.llm_max_tokens <= _MAX_COMPLETION_TOKENS
        or len(config.system_prompt.encode("utf-8")) > _MAX_PRIVATE_PROMPT_BYTES
    ):
        # Refuse rather than truncate prompts or silently change token limits.
        raise NativeSimulationError("native_simulation_model_configuration")


def _preview_global_mcp_functions(selection, assistant, db, preview=None):
    """Expose only cached, explicitly read-only MCP schemas in preview mode."""
    connection_id = getattr(assistant, "mcp_connection_id", None)
    if not connection_id:
        if getattr(assistant, "mcp_enabled_tools", None):
            raise NativeSimulationError("native_dev_resources")
        return ()

    from botelier.models.mcp_connection import (
        MCPConnection, MCPConnectionStatus,
    )
    from botelier.voice.flows.native_actions import NativeActionRunner
    from pipecat.flows.types import FlowsFunctionSchema

    connection = db.query(MCPConnection).filter(
        MCPConnection.id == connection_id,
        MCPConnection.account_id == assistant.account_id,
        MCPConnection.is_active.is_(True),
    ).first()
    if (
        connection is None
        or connection.status != MCPConnectionStatus.CONNECTED
        or not getattr(connection, "server_url", None)
    ):
        raise NativeSimulationError("native_dev_resources")
    enabled = getattr(assistant, "mcp_enabled_tools", None) or []
    if (
        not isinstance(enabled, list) or len(enabled) > 128
        or any(not isinstance(name, str) or not name for name in enabled)
        or len(enabled) != len(set(enabled))
    ):
        raise NativeSimulationError("native_dev_resources")
    discover = getattr(connection, "get_discovered_tools", None)
    discovered = (
        discover() if callable(discover)
        else getattr(connection, "discovered_tools", None)
    ) or []
    if not isinstance(discovered, list):
        raise NativeSimulationError("native_dev_resources")

    result = []
    for name in enabled:
        try:
            current, read_only = NativeActionRunner.resolve_mcp_tool_policy(
                db, selection.compiled.identity, connection_id, name,
            )
        except (LookupError, PermissionError, TypeError, ValueError):
            raise NativeSimulationError("native_dev_resources") from None
        if current.id != connection.id:
            raise NativeSimulationError("native_dev_resources")
        if not read_only:
            continue
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name)
            or name in selection.compiled.native_names
            or name.startswith("native_")
        ):
            raise NativeSimulationError("native_dev_resources")
        matching = [
            item for item in discovered
            if isinstance(item, dict) and item.get("name") == name
        ]
        if len(matching) != 1:
            raise NativeSimulationError("native_dev_resources")
        item = matching[0]
        parameters = item.get("parameters", item.get("inputSchema", {}))
        if not isinstance(parameters, dict):
            raise NativeSimulationError("native_dev_resources")
        properties = parameters.get("properties", {})
        required = parameters.get("required", [])
        if (
            parameters.get("type", "object") != "object"
            or set(parameters) - {
                "type", "properties", "required", "description",
                "additionalProperties",
            }
            or parameters.get("additionalProperties", False) is not False
            or not isinstance(properties, dict) or len(properties) > 64
            or not isinstance(required, list)
            or any(not isinstance(key, str) or key not in properties for key in required)
            or len(required) != len(set(required))
        ):
            raise NativeSimulationError("native_dev_resources")

        def safe_schema(schema, depth=0):
            if (
                depth > 16 or not isinstance(schema, dict)
                or schema.get("type") not in {
                    "string", "number", "integer", "boolean", "object", "array",
                }
                or set(schema) - {
                    "type", "title", "description", "default", "enum",
                    "properties", "required", "items", "minimum", "maximum",
                    "minLength", "maxLength", "additionalProperties",
                }
            ):
                raise NativeSimulationError("native_dev_resources")
            result_schema = {"type": schema["type"]}
            enum = schema.get("enum")
            if enum is not None:
                if (
                    not isinstance(enum, list) or not enum or len(enum) > 128
                    or any(
                        not isinstance(value, (str, int, float, bool))
                        or isinstance(value, float) and not math.isfinite(value)
                        for value in enum
                    )
                ):
                    raise NativeSimulationError("native_dev_resources")
                result_schema["enum"] = enum
            for minimum_key, maximum_key in (
                ("minimum", "maximum"),
                ("minLength", "maxLength"),
            ):
                minimum = schema.get(minimum_key)
                maximum = schema.get(maximum_key)
                if minimum is not None:
                    if (
                        isinstance(minimum, bool)
                        or not isinstance(minimum, (int, float))
                        or isinstance(minimum, float) and not math.isfinite(minimum)
                    ):
                        raise NativeSimulationError("native_dev_resources")
                    result_schema[minimum_key] = minimum
                if maximum is not None:
                    if (
                        isinstance(maximum, bool)
                        or not isinstance(maximum, (int, float))
                        or isinstance(maximum, float) and not math.isfinite(maximum)
                    ):
                        raise NativeSimulationError("native_dev_resources")
                    result_schema[maximum_key] = maximum
                if minimum is not None and maximum is not None and minimum > maximum:
                    raise NativeSimulationError("native_dev_resources")
            if schema["type"] == "object":
                child_properties = schema.get("properties", {})
                child_required = schema.get("required", [])
                if (
                    not isinstance(child_properties, dict)
                    or len(child_properties) > 128
                    or not isinstance(child_required, list)
                    or any(
                        not isinstance(key, str) or key not in child_properties
                        for key in child_required
                    )
                    or len(child_required) != len(set(child_required))
                    or schema.get("additionalProperties", False) is not False
                ):
                    raise NativeSimulationError("native_dev_resources")
                safe_children = {}
                for key, child in child_properties.items():
                    if (
                        not isinstance(key, str)
                        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", key)
                    ):
                        raise NativeSimulationError("native_dev_resources")
                    safe_children[key] = safe_schema(child, depth + 1)
                result_schema["properties"] = safe_children
                if child_required:
                    result_schema["required"] = list(child_required)
                result_schema["additionalProperties"] = False
            elif schema["type"] == "array":
                if schema.get("additionalProperties") is not None:
                    raise NativeSimulationError("native_dev_resources")
                if not isinstance(schema.get("items"), dict):
                    raise NativeSimulationError("native_dev_resources")
                result_schema["items"] = safe_schema(schema["items"], depth + 1)
            elif any(
                key in schema for key in (
                    "properties", "required", "items", "additionalProperties",
                )
            ):
                raise NativeSimulationError("native_dev_resources")
            return result_schema

        safe_properties = {}
        for key, schema in properties.items():
            if (
                not isinstance(key, str)
                or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", key)
            ):
                raise NativeSimulationError("native_dev_resources")
            safe_properties[key] = safe_schema(schema)
        try:
            encoded_schema = json.dumps(
                {"type": "object", "properties": safe_properties, "required": required},
                ensure_ascii=False, allow_nan=False, separators=(",", ":"),
            )
        except (TypeError, ValueError, RecursionError):
            raise NativeSimulationError("native_dev_resources") from None
        if len(encoded_schema.encode("utf-8")) > 64_000:
            raise NativeSimulationError("native_dev_resources")

        async def preview_handler(
            _arguments, _manager, _tool_name=name,
            _properties=safe_properties, _required=tuple(required),
        ):
            if preview is None:
                return {"status": "preview_required", "source": "mcp"}
            try:
                NativeActionRunner._validate_mcp_schema(
                    {"type": "object", "properties": _properties,
                     "required": list(_required), "additionalProperties": False},
                    _arguments,
                )
                sample = await preview.request(
                    node_id="global-" + _tool_name,
                    source_kind="mcp_read",
                    scope=(
                        str(selection.compiled.identity.tool_id),
                        str(selection.compiled.identity.flow_version_id),
                        str(selection.compiled.identity.call_sid),
                        _tool_name,
                    ),
                )
                if not sample.success or not isinstance(sample.data, dict):
                    return {"status": "preview_rejected", "source": "mcp"}
                result = NativeActionRunner._json_safe_mcp_value(sample.data)
                if result.get("isError") is True:
                    return {"status": "preview_rejected", "source": "mcp"}
                from botelier.voice.flows.native_quote_graph import assert_quote_payload_safe

                assert_quote_payload_safe(selection.compiled, {}, result)
                preview.record_effect("mcp_read", "global-" + _tool_name)
                return result
            except Exception:
                return {"status": "preview_rejected", "source": "mcp"}

        result.append(FlowsFunctionSchema(
            name=name,
            description="Read-only connected resource; preview only.",
            properties=safe_properties,
            required=required,
            handler=preview_handler,
        ))
    return tuple(result)


async def prepare_native_simulation(
    *, request, assistant, tool, db, account_id, session_id, policy,
) -> NativeSimulationPlan:
    """Resolve the exact owned version shown by the caller's source selector."""
    validate_native_simulation_source(request, policy)
    if (
        assistant is None
        or request.assistant_id != str(assistant.id)
        or request.tool_id != str(tool.id)
        or str(getattr(assistant, "tool_set_id", "") or "")
        != str(getattr(tool, "tool_set_id", "") or "")
    ):
        raise NativeSimulationError("native_dev_selection")
    if not account_id or str(assistant.account_id) != str(account_id):
        raise NativeSimulationError("native_dev_ownership", 403)
    if getattr(tool, "is_active", None) != "true":
        raise NativeSimulationError("native_dev_resources")

    try:
        ensure_native_dev_resources(assistant)
        tools = db.query(Tool).filter(
            Tool.tool_set_id == assistant.tool_set_id,
            Tool.is_active == "true",
        ).all()
        tool_set = db.query(ToolSet).filter(
            ToolSet.id == assistant.tool_set_id,
        ).first()
        version_id = getattr(tool, "published_version_id", None)
        version = (
            db.query(FlowVersion).filter(
                FlowVersion.id == version_id,
                FlowVersion.tool_id == tool.id,
                FlowVersion.status == FlowVersionStatus.PUBLISHED,
            ).first()
            if version_id else None
        )
        owned = bool(
            assistant.property_id
            and property_belongs_to_account(
                db, assistant.account_id, assistant.property_id,
            )
        )
        selection = prepare_native_dev_selection(
            assistant=assistant, tools=tools, tool_set=tool_set,
            flow_version=version, call_sid=session_id,
            property_id=assistant.property_id, property_owned=owned,
            requested_tool_id=str(tool.id),
        )
        if selection is None:
            raise NativeDevAdmissionError("native_dev_selection")
        flow_catalogue = prepare_native_dev_catalogue(
            assistant=assistant,
            tools=tools,
            tool_set=tool_set,
            db=db,
            call_sid=session_id,
            property_id=assistant.property_id,
            property_owned=owned,
            selected=selection,
        )
    except NativeDevAdmissionError as error:
        code = (
            str(error) if str(error) in _ADMISSION_CODES
            else "native_simulation_flow_unsupported"
        )
        raise NativeSimulationError(code, diagnostic=str(error)) from None

    if (
        type(getattr(version, "version_number", None)) is not int
        or version.version_number != request.source_version
    ):
        raise NativeSimulationError("native_simulation_version_changed", 409)

    from botelier.voice.flows.native_action_preview import NativeActionPreview

    preview = NativeActionPreview(timeout=120.0)
    global_functions = _preview_global_mcp_functions(
        selection, assistant, db, preview,
    )
    try:
        config = await build_assistant_agent_config(assistant)
        apply_native_flow_context(config, assistant=assistant, tool=selection.tool)
        _validate_model_configuration(config)
    except NativeSimulationError:
        raise
    except Exception:
        raise NativeSimulationError("native_simulation_model_configuration") from None

    identity = selection.compiled.identity
    # Alternative nodes can collect the same variable. Match the host's
    # unique-variable progress and keep the first collection prompt in the UI.
    variables_by_key = {}
    for slot in selection.compiled.caller_slots:
        variables_by_key.setdefault(slot.variable, {
            "key": slot.variable, "type": "string" if slot.type == "text" else slot.type,
            "description": slot.prompt, "required": True,
            "node_id": slot.node_id,
        })
    return NativeSimulationPlan(
        compiled=selection.compiled,
        config=config,
        runtime={
            "engine": "native_pilot", "source": "published",
            "implementation": "NativeFlowAdapter",
            "tool_id": identity.tool_id, "assistant_id": str(assistant.id),
            "account_id": identity.account_id, "property_id": identity.property_id,
            "flow_version_id": identity.flow_version_id,
            "version_number": version.version_number,
            "llm_provider": config.llm_provider, "llm_model": config.llm_model,
            "read_only_global_tools": [item.name for item in global_functions],
            "execution_mode": "preview", "effect_mode": "simulation",
            "effects_simulated": True,
        },
        variables_to_collect=list(variables_by_key.values()),
        global_functions=global_functions,
        available_flows=flow_catalogue,
        preview=preview,
    )


def native_model_api_keys(config) -> dict:
    """Resolve only the configured model credential, after native admission."""
    provider = config.llm_provider.lower()
    if provider == "openai":
        env_name, key_name = "OPENAI_API_KEY", "openai_api_key"
    elif provider == "google_gemini":
        env_name, key_name = "GOOGLE_API_KEY", "google_api_key"
    else:
        raise NativeSimulationError("native_simulation_provider_unsupported")
    key = os.getenv(env_name)
    if not isinstance(key, str) or not key.strip():
        raise NativeSimulationError("native_simulation_model_unconfigured", 503)
    return {key_name: key}


def native_action_session_factory():
    """Actions own a fresh session; they never retain the API request session."""
    from botelier.database import SessionLocal

    return SessionLocal


async def start_native_simulation(
    *, request, assistant, tool, db, account_id, owner_user_id,
    registry, session_map, policy_provider=None,
) -> dict:
    """Construct the real native host only after source and ownership checks."""
    from botelier.services.native_simulation_session import NativeSimulationSession

    policy_provider = policy_provider or NativeFlowDevPolicy.from_environment
    validate_native_simulation_source(request, policy_provider())
    owner_user_id = str(owner_user_id)
    session_id = registry.reserve(owner_user_id)
    host = None
    session = None
    try:
        async with asyncio.timeout(30.0):
            plan = await prepare_native_simulation(
                request=request, assistant=assistant, tool=tool, db=db,
                account_id=account_id, session_id=session_id,
                policy=policy_provider(),
            )
            # No paid model/remote action runs while the read-only request
            # transaction holds a database connection. Everything below uses
            # copied identity/configuration and independently owned sessions.
            db.close()
            keys = native_model_api_keys(plan.config)
            action_sessions = native_action_session_factory()
            from botelier.voice.flows.native_text_host import NativeTextHost

            host = NativeTextHost(
                plan.compiled, config=plan.config, api_keys=keys,
                session_factory=action_sessions, turn_timeout=120.0,
                global_functions=plan.global_functions,
                available_flows=plan.available_flows,
                preview=plan.preview,
            )
            session = NativeSimulationSession(
                session_id=session_id, owner_user_id=owner_user_id,
                account_id=str(account_id), runtime=plan.runtime,
                variables_to_collect=plan.variables_to_collect,
                host=host, registry=registry, session_map=session_map,
                policy_provider=policy_provider,
            )
            return await session.start()
    except BaseException as error:
        # In particular, caller cancellation must not leave an unpublished
        # worker or pending quota reservation alive.
        target = session if session is not None else host
        try:
            if target is not None:
                await target.close()
        except Exception as cleanup_error:
            logger.error(
                "native_simulation_start_cleanup_failed category={}",
                type(cleanup_error).__name__,
            )
        finally:
            registry.abandon(session_id, owner_user_id)
        if isinstance(error, NativeSimulationError):
            raise
        if isinstance(error, TimeoutError):
            raise NativeSimulationError("native_simulation_timeout", 503) from None
        if not isinstance(error, Exception):
            raise
        logger.error(
            "native_simulation_start_failed category={}", type(error).__name__,
        )
        raise NativeSimulationError("native_simulation_start_failed", 502) from None
