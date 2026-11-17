"""Authoritative, development-only source admission for native simulations.

The app selects and authorizes one immutable published graph here. Pipecat
Flows, not this module, owns every runtime node and transition.
"""

from dataclasses import dataclass
import asyncio
import math
import os

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
    apply_native_pilot_context,
    ensure_native_dev_resources,
    prepare_native_dev_selection,
)


_ADMISSION_CODES = frozenset({
    "native_dev_selection", "native_dev_resources", "native_dev_ownership",
    "native_dev_published_version",
})
_MAX_PRIVATE_PROMPT_BYTES = 64 * 1024
_MAX_COMPLETION_TOKENS = 4096


@dataclass(frozen=True)
class NativeSimulationPlan:
    """Server-owned snapshot; never serialize the private agent configuration."""

    compiled: object
    config: object
    runtime: dict
    variables_to_collect: list[dict]


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
    # Certify one actual provider path first. Never silently use OpenAI when
    # the configured provider is different; Google remains unverified here.
    if config.llm_provider.lower() != "openai":
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
        if len(tools) != 1:
            raise NativeDevAdmissionError("native_dev_resources")
        if str(tools[0].id) != str(tool.id):
            raise NativeDevAdmissionError("native_dev_selection")
        tool_set = db.query(ToolSet).filter(
            ToolSet.id == assistant.tool_set_id,
        ).first()
        version_id = getattr(tools[0], "published_version_id", None)
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
        )
        if selection is None:
            raise NativeDevAdmissionError("native_dev_selection")
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

    try:
        config = await build_assistant_agent_config(assistant)
        apply_native_pilot_context(config, assistant=assistant, tool=selection.tool)
        _validate_model_configuration(config)
    except NativeSimulationError:
        raise
    except Exception:
        raise NativeSimulationError("native_simulation_model_configuration") from None

    identity = selection.compiled.identity
    # Alternative nodes can collect the same variable. Match the host's
    # unique-variable progress and keep the first collection prompt in the UI.
    variables_by_key = {}
    for slot in (
        selection.compiled.query, selection.compiled.choice,
        selection.compiled.failure,
    ):
        variables_by_key.setdefault(slot.variable, {
            "key": slot.variable, "type": "string",
            "description": slot.prompt, "required": True,
            "node_id": slot.node_id,
        })
    return NativeSimulationPlan(
        compiled=selection.compiled,
        config=config,
        runtime={
            "engine": "native_pilot", "source": "published",
            "tool_id": identity.tool_id, "assistant_id": str(assistant.id),
            "account_id": identity.account_id, "property_id": identity.property_id,
            "flow_version_id": identity.flow_version_id,
            "version_number": version.version_number,
            "llm_provider": config.llm_provider, "llm_model": config.llm_model,
        },
        variables_to_collect=list(variables_by_key.values()),
    )


def native_model_api_keys(config) -> dict:
    """Resolve only the configured model credential, after native admission."""
    if config.llm_provider.lower() != "openai":
        raise NativeSimulationError("native_simulation_provider_unsupported")
    key = os.getenv("OPENAI_API_KEY")
    if not isinstance(key, str) or not key.strip():
        raise NativeSimulationError("native_simulation_model_unconfigured", 503)
    return {"openai_api_key": key}


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
