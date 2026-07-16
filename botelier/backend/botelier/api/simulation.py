"""Flow Simulation API - Test flows with real LLM conversations.

This module provides endpoints for simulating conversation flows
with actual LLM-powered responses, allowing users to test slot collection,
API calls, and conditions in a chat-like interface without requiring Twilio.
"""

import json
import os
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from openai import OpenAI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.middleware import check_account_permission, get_current_user
from ..database import get_db
from ..flow_executor import FlowExecutor, NodeType, parse_flow_config
from ..models.assistant import Assistant
from ..models.tool import Tool, ToolType
from ..models.user import User
from ..services.ssrf_safe_transport import _BLOCKED_LITERAL_HOSTS, SSRFSafeTransport

router = APIRouter(prefix="/api/simulate", tags=["Simulation"])

# Simulator↔live parity: the preview must run the SAME LLM the assistant is
# configured with, so what a user tests in the simulator matches what callers
# get on a live call. The resolved assistant's `llm_model` is used per session
# (see SimulationState.model). This default applies only when no backing
# assistant can be resolved, and it mirrors the new-assistant default so even
# the fallback matches live. Do not hardcode a stronger model here — a preview
# on a better model than production would hide real production behavior.
DEFAULT_SIM_MODEL = "gpt-4o-mini"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


class SimulationSession:
    """In-memory storage for simulation sessions."""

    sessions: dict[str, "SimulationState"] = {}


class SimulationState:
    """Tracks state for a simulation session."""

    def __init__(
        self,
        tool_id: str,
        executor: FlowExecutor,
        tool_name: str = "",
        account_id: Optional[str] = None,
        kb_prompt_block: str = "",
        escalation_target: Optional[str] = None,
        model: str = DEFAULT_SIM_MODEL,
        capability_schemas: Optional[list] = None,
        dynamic_operation_schemas: Optional[list] = None,
    ):
        self.tool_id = tool_id
        self.tool_name = tool_name
        self.account_id = account_id
        self.executor = executor
        # Standalone universal-capability tools (Task #329) from the backing
        # assistant's tool_set, mirrored so the simulator previews capability
        # calls the LLM can make outside a flow — identical to voice/SMS. Flow
        # capability *nodes* need nothing extra here: the executor handles them.
        self.capability_schemas = capability_schemas or []
        self.capability_names = {
            s["function"]["name"]
            for s in self.capability_schemas
            if s.get("function", {}).get("name")
        }
        # Standalone DYNAMIC_OPERATION tools from the Universal Adapter (Task #356).
        # Mirrored identically to capability_schemas above.
        self.dynamic_operation_schemas = dynamic_operation_schemas or []
        self.dynamic_operation_names = {
            s["function"]["name"]
            for s in self.dynamic_operation_schemas
            if s.get("function", {}).get("name")
        }
        # LLM model for this session — mirrors the backing assistant's llm_model
        # so the simulator runs the exact model a live call would use.
        self.model = model or DEFAULT_SIM_MODEL
        # Assistant-level knowledge base block + escalation number, resolved once
        # at session start so the simulator mirrors live: it can answer mid-flow
        # questions from the KB and offer "talk to a human".
        self.kb_prompt_block = kb_prompt_block or ""
        self.escalation_target = escalation_target
        self.messages: list[dict] = []
        self.llm_messages: list[dict] = []
        self.is_ended = False
        self._init_llm_context()

    def _init_llm_context(self):
        """Initialize LLM conversation context with system prompt."""
        system_prompt = self.executor.get_system_prompt() + self.kb_prompt_block
        initial_messages = self.executor.get_initial_messages()
        combined_greeting = " ".join(initial_messages)

        self.llm_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "assistant", "content": combined_greeting},
        ]

    def add_message(self, role: str, content: str, metadata: Optional[dict] = None):
        self.messages.append({"role": role, "content": content, "metadata": metadata or {}})

    def add_llm_message(self, role: str, content: str):
        self.llm_messages.append({"role": role, "content": content})

    def get_state_snapshot(self) -> dict:
        """Get current state for frontend display."""
        return {
            "collected_slots": self.executor.state.collected_slots.copy(),
            "current_node": self.executor.state.current_node_id,
            "pending_slot": self.executor.state.pending_slot,
            "is_complete": self.executor.state.is_complete,
            "is_ended": self.is_ended,
            "progress": self.executor.get_progress(),
        }


class StartSimulationRequest(BaseModel):
    tool_id: str
    # Optional: the assistant whose knowledge base + escalation number back this
    # flow. When omitted, the simulator falls back to an assistant sharing the
    # tool's tool_set so KB parity still works without a frontend change.
    assistant_id: Optional[str] = None


class StartSimulationResponse(BaseModel):
    session_id: str
    greeting: str
    variables_to_collect: list[dict]
    state: dict
    messages: list[dict]


class SimulateMessageRequest(BaseModel):
    session_id: str
    message: str
    function_call: Optional[str] = None
    function_args: Optional[dict] = None


class SimulateMessageResponse(BaseModel):
    response: str
    function_called: Optional[str] = None
    function_result: Optional[dict] = None
    state: dict
    messages: list[dict]
    suggested_functions: list[dict]
    # Populated only when LLM processing raised — surfaces the real cause
    # (exception type + one-line message) to the simulator UI instead of
    # hiding flow-config bugs behind a generic apology. Never a traceback.
    error: Optional[str] = None


class TestAPIRequest(BaseModel):
    method: str
    url: str
    headers: Optional[dict] = None
    body: Optional[str] = None
    variables: Optional[dict] = None


class TestAPIResponse(BaseModel):
    status_code: int
    response_body: Any
    response_headers: dict
    resolved_url: str
    resolved_body: Optional[str] = None
    error: Optional[str] = None


def _build_kb_prompt_block(knowledge_base_id: Optional[Any]) -> str:
    """Load the assistant's knowledge base and format the exact block that live
    calls inject (see call_handler `_create_agent_config`), so the simulator can
    answer mid-flow questions from the KB just like production.

    Returns "" when there is no KB or it fails to load — the simulator then
    behaves as a flow-only preview, never a hard error.
    """
    if not knowledge_base_id:
        return ""
    try:
        from ..voice.knowledge_handler import load_knowledge_for_prompt

        kb_content = load_knowledge_for_prompt(str(knowledge_base_id))
    except Exception as e:
        logger.error(f"Simulator failed to load KB {knowledge_base_id}: {e}")
        return ""
    if not kb_content:
        return ""
    return f"""

## RESPONSE GUIDELINES
- Answer questions from the knowledge base naturally and conversationally
- Keep responses concise (under 50 words) since this is a phone call
- Only transfer to a human if: (1) the caller explicitly requests to speak with someone, OR (2) the question requires information NOT in the knowledge base AND the caller needs urgent assistance
- For general questions covered by the knowledge base, answer directly without offering to transfer
- If the caller asks a question in the middle of a task, answer it briefly, then continue where you left off — do not lose your place or restart

## KNOWLEDGE BASE
You have access to the following Q&A knowledge base. Use this information to answer customer questions directly and confidently. Do NOT transfer the call or say you don't have information if the answer is in this knowledge base.

{kb_content}"""


def _build_capability_tool_schemas(db: Session, assistant: Optional[Assistant]) -> list:
    """Mirror the backing assistant's standalone capability tools (Task #329).

    Returns OpenAI tool schemas (deduped by capability) so the simulator can
    preview capability calls the LLM would make outside a flow — identical to the
    voice/SMS channels. The LLM only ever sees the abstract capability name and
    its vendor-neutral parameters; resolution to a concrete vendor happens at
    execution time. Returns [] when there is no backing assistant / tool_set.
    """
    if not assistant or not assistant.tool_set_id:
        return []
    from botelier.services.capabilities import build_capability_schema, get_capability

    cap_tools = (
        db.query(Tool)
        .filter(
            Tool.tool_set_id == assistant.tool_set_id,
            Tool.tool_type == ToolType.CAPABILITY.value,
            Tool.is_active == "true",
        )
        .all()
    )
    schemas: list = []
    seen: set = set()
    for tool in cap_tools:
        capability_name = (tool.config or {}).get("capability")
        if not capability_name or capability_name in seen:
            continue
        spec = get_capability(capability_name)
        schema = build_capability_schema(capability_name) if spec else None
        if not schema:
            continue
        seen.add(capability_name)
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": schema["name"],
                    "description": schema["description"],
                    "parameters": schema["parameters"],
                },
            }
        )
    return schemas


def _build_dynamic_operation_tool_schemas(
    db: Session,
    assistant: Optional[Assistant],
    session_property_id: Optional[str] = None,
) -> list:
    """Mirror the backing assistant's DYNAMIC_OPERATION tools (Universal Adapter).

    Returns OpenAI tool schemas so the simulator can preview dynamic-operation
    calls the LLM would make outside a flow — identical to the voice/SMS channels.
    The LLM sees only LLM-owned parameters from the published action version.
    Returns [] when there is no backing assistant / tool_set.

    Only tools whose backing AccountIntegration is CONNECTED and property-scoped
    to the session's property (or account-global) are included; disconnected or
    out-of-scope connections are filtered so the LLM never sees unavailable tools.
    """
    if not assistant or not assistant.tool_set_id:
        return []
    from botelier.models.integration import (
        AccountIntegration,
        IntegrationAction,
        IntegrationActionVersion,
        IntegrationStatus,
    )

    dyn_tools = (
        db.query(Tool)
        .filter(
            Tool.tool_set_id == assistant.tool_set_id,
            Tool.tool_type == ToolType.DYNAMIC_OPERATION.value,
            Tool.is_active == "true",
        )
        .all()
    )
    schemas: list = []
    seen: set = set()
    for tool in dyn_tools:
        tool_config = tool.config or {}
        action_id = tool_config.get("integration_action_id")
        if not action_id or action_id in seen:
            continue

        # Connection-scoped + property-scope filter: skip if not CONNECTED or if
        # the connection is property-bound to a different property than the session.
        # Account-global connections (property_id NULL) always pass.
        connection_id = tool_config.get("connection_id")
        if connection_id:
            conn = db.query(AccountIntegration).filter(
                AccountIntegration.id == connection_id
            ).first()
            if not conn or conn.status != IntegrationStatus.CONNECTED:
                continue
            if conn.property_id is not None:
                if session_property_id is None or str(conn.property_id) != str(session_property_id):
                    continue

        action = db.query(IntegrationAction).filter(IntegrationAction.id == action_id).first()
        if not action or not action.published_version_id:
            continue
        version = db.query(IntegrationActionVersion).filter(
            IntegrationActionVersion.id == action.published_version_id
        ).first()
        if not version:
            continue
        input_schema = version.input_schema or {"type": "object", "properties": {}, "required": []}
        seen.add(action_id)
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or tool.name,
                    "parameters": input_schema,
                },
            }
        )
    return schemas


async def _execute_sim_dynamic_operation(
    state: "SimulationState",
    function_name: str,
    function_args: dict,
    db: Session,
) -> dict:
    """Execute a DYNAMIC_OPERATION tool through the certified integration runtime.

    Mirrors voice/SMS channels exactly: ActionExecutor → IntegrationClient pipeline
    (property isolation, rate-limiting, circuit-breaker, credential encryption,
    response bounding + redaction).  Same certified path, no shortcuts.
    """
    from botelier.models.integration import IntegrationAction, IntegrationActionVersion
    from botelier.models.tool import Tool, ToolType
    from botelier.services.action_executor import (
        ActionContext,
        ActionExecutionRequest,
        ActionExecutor,
    )
    from botelier.services.integration_client import IntegrationAPIConfig

    tool = (
        db.query(Tool)
        .filter(
            Tool.name == function_name,
            Tool.tool_type == ToolType.DYNAMIC_OPERATION.value,
            Tool.account_id == state.account_id,
            Tool.is_active == "true",
        )
        .first()
    )
    if not tool:
        return {"error": f"Dynamic operation {function_name!r} not found", "status": "failed"}

    tool_config = tool.config or {}
    action_id = tool_config.get("integration_action_id")
    connection_id = tool_config.get("connection_id")
    operation_id = tool_config.get("operation_id")

    action = (
        db.query(IntegrationAction).filter(IntegrationAction.id == action_id).first()
        if action_id else None
    )
    if not action or not action.published_version_id:
        return {"error": "Dynamic operation has no published version", "status": "failed"}

    version = db.query(IntegrationActionVersion).filter(
        IntegrationActionVersion.id == action.published_version_id
    ).first()
    if not version or not version.config:
        return {"error": "Dynamic operation version config missing", "status": "failed"}

    exec_config = version.config
    api_config = IntegrationAPIConfig(
        integration_id=exec_config.get("integration_id") or connection_id or "",
        method=exec_config.get("method", "GET"),
        path=exec_config.get("path", "/"),
        endpoint_id=exec_config.get("endpoint_id") or operation_id or "",
        query_param_overrides={},
    )

    exec_result = await ActionExecutor(db).execute_and_log(
        ActionExecutionRequest(
            context=ActionContext(
                account_id=state.account_id,
                channel="test",
                tool_id=str(tool.id),
                property_id=getattr(state.executor, "property_id", None),
            ),
            variables=function_args,
            integration_config=api_config,
            response_policy=exec_config.get("response_policy"),
        )
    )
    if exec_result.success:
        return exec_result.data or {"status": "ok"}
    return {
        "error": exec_result.error_message or "Dynamic operation failed",
        "status": "failed",
        "error_type": exec_result.error_type.value if exec_result.error_type else "unknown",
    }


def _resolve_flow_assistant(
    db: Session, tool: Tool, assistant_id: Optional[str], user: User
) -> Optional[Assistant]:
    """Resolve the assistant whose config (KB + escalation number) should back
    this flow simulation.

    An explicit ``assistant_id`` wins — it is permission-checked and bound to the
    tool's account to prevent cross-tenant KB/escalation injection. Otherwise we
    fall back to the most recent assistant sharing the tool's ``tool_set`` so KB
    parity works even without a frontend change. Returns ``None`` when nothing
    can be resolved.
    """
    if assistant_id:
        assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
        if not assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")
        if tool.account_id and str(assistant.account_id) != str(tool.account_id):
            raise HTTPException(
                status_code=403, detail="Assistant does not belong to this account"
            )
        check_account_permission(user, str(assistant.account_id), "assistants.view", db)
        return assistant

    if tool.tool_set_id and tool.account_id:
        return (
            db.query(Assistant)
            .filter(
                Assistant.tool_set_id == tool.tool_set_id,
                Assistant.account_id == tool.account_id,
            )
            .order_by(Assistant.created_at.desc())
            .first()
        )
    return None


@router.post("/start", response_model=StartSimulationResponse)
async def start_simulation(
    request: StartSimulationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Start a new flow simulation session.

    Creates a FlowExecutor instance and returns the initial greeting
    along with variables that need to be collected.
    """
    tool = db.query(Tool).filter(Tool.id == request.tool_id).first()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    if tool.account_id:
        check_account_permission(user, str(tool.account_id), "tools.view", db)

    if tool.tool_type.value != "FLOW":
        raise HTTPException(status_code=400, detail="Tool is not a flow type")

    config_data = tool.config if tool.config else {}
    flow_config_dict = dict(config_data) if isinstance(config_data, dict) else {}
    if not flow_config_dict.get("nodes"):
        raise HTTPException(status_code=400, detail="Flow has no configured nodes")

    # Resolve the backing assistant so the simulator mirrors live behavior:
    # inject the same knowledge base block and expose the same "talk to a human"
    # escalation. Explicit assistant_id wins; otherwise fall back to an assistant
    # sharing the tool's tool_set.
    assistant = _resolve_flow_assistant(db, tool, request.assistant_id, user)
    kb_prompt_block = _build_kb_prompt_block(
        assistant.knowledge_base_id if assistant else None
    )
    capability_schemas = _build_capability_tool_schemas(db, assistant)
    # Resolve property_id first so _build_dynamic_operation_tool_schemas can apply
    # the same property-scope filter as voice / SMS.
    property_id = str(assistant.property_id) if assistant and assistant.property_id else None
    dynamic_operation_schemas = _build_dynamic_operation_tool_schemas(db, assistant, property_id)
    escalation_target = None
    sim_model = DEFAULT_SIM_MODEL
    if assistant:
        escalation_target = (assistant.call_settings or {}).get("escalation_number") or None
        sim_model = assistant.llm_model or DEFAULT_SIM_MODEL
        # property_id resolved above so _build_dynamic_operation_tool_schemas receives
        # it before this block runs; keep the value consistent for FlowExecutor below.

    try:
        flow_config = parse_flow_config(flow_config_dict)
        executor = FlowExecutor(
            flow_config,
            db_session=db,
            account_id=str(tool.account_id) if tool.account_id else None,
            flow_tool_id=str(tool.id),
            escalation_target=escalation_target,
            property_id=property_id,
        )
    except Exception as e:
        logger.error(f"Failed to parse flow config: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid flow configuration: {str(e)}")

    session_id = str(uuid.uuid4())
    state = SimulationState(
        tool_id=request.tool_id,
        executor=executor,
        tool_name=tool.name,
        account_id=str(tool.account_id) if tool.account_id else None,
        kb_prompt_block=kb_prompt_block,
        escalation_target=escalation_target,
        model=sim_model,
        capability_schemas=capability_schemas,
        dynamic_operation_schemas=dynamic_operation_schemas,
    )

    initial_messages = executor.get_initial_messages()
    greeting = " ".join(initial_messages)

    for msg in initial_messages:
        state.add_message("assistant", msg)

    SimulationSession.sessions[session_id] = state

    ordered_variables = executor.get_variables_in_flow_order()
    variables_to_collect = [
        {
            "key": v.key,
            "type": v.type.value,
            "description": v.description,
            "required": v.required,
            "choices": v.choices,
        }
        for v in ordered_variables
    ]

    logger.info(f"Started simulation session {session_id} for tool {tool.name}")

    return StartSimulationResponse(
        session_id=session_id,
        greeting=greeting,
        variables_to_collect=variables_to_collect,
        state=state.get_state_snapshot(),
        messages=state.messages,
    )


@router.post("/message", response_model=SimulateMessageResponse)
async def simulate_message(
    request: SimulateMessageRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Process a message in the simulation using LLM with function calling.

    If function_call is provided, execute that function directly (manual mode).
    Otherwise, send the message to the LLM and let it decide what to do.
    """
    state = _get_session_and_check_access(request.session_id, user, db)

    if state.is_ended:
        raise HTTPException(status_code=400, detail="Simulation has ended")

    executor = state.executor
    response_text = ""
    function_called = None
    function_result = None
    error_detail = None
    save_record_events: list[dict] = []

    state.add_message("user", request.message)

    if request.function_call:
        try:
            result = await executor.handle_function_call(
                request.function_call, request.function_args or {}
            )
            function_called = request.function_call
            function_result = result

            if request.function_call.startswith("save_record_"):
                save_record_events.append(
                    {
                        "record_saved": result.get("record_saved", False),
                        "message": result.get("message", "Record could not be saved"),
                    }
                )

            if result.get("action") == "end":
                state.is_ended = True
                response_text = str(result.get("message", "Thank you for calling. Goodbye!"))
            elif result.get("action") == "transfer":
                state.is_ended = True
                response_text = (
                    f"[Transferring call to {result.get('target')}] {result.get('message', '')}"
                )
            elif result.get("message"):
                response_text = str(result.get("message", ""))
            elif result.get("next_prompt"):
                response_text = str(result.get("next_prompt", ""))
            else:
                response_text = f"Recorded: {request.function_args}"

        except Exception as e:
            logger.error(f"Function call error: {e}")
            response_text = f"Error executing function: {str(e)}"
    else:
        llm_response = await _process_with_llm(state, request.message)
        response_text = llm_response["response"]
        function_called = llm_response.get("function_called")
        function_result = llm_response.get("function_result")
        error_detail = llm_response.get("error")
        save_record_events = llm_response.get("save_record_events", [])

        if llm_response.get("is_ended"):
            state.is_ended = True

    state.add_message(
        "assistant",
        response_text,
        {"function_called": function_called, "function_result": function_result},
    )

    for event in save_record_events:
        state.add_message(
            "system",
            event.get("message", "Record could not be saved"),
            {"record_saved": event.get("record_saved", False)},
        )

    suggested_functions = _get_suggested_functions(executor)

    return SimulateMessageResponse(
        response=response_text,
        function_called=function_called,
        function_result=function_result,
        state=state.get_state_snapshot(),
        messages=state.messages,
        suggested_functions=suggested_functions,
        error=error_detail,
    )


async def _process_with_llm(state: SimulationState, user_message: str) -> dict:
    """Process user message with OpenAI LLM using function calling.

    The LLM will naturally converse and call functions to collect slots.
    When the current node is an API Request, tool_choice is forced to the
    specific execute_ function so the API fires immediately — not after a
    separate round-trip back to the user.
    """
    if not openai_client:
        return {
            "response": "OpenAI API key not configured. Please use the function picker to test manually.",
            "function_called": None,
            "function_result": None,
            "is_ended": False,
        }

    state.add_llm_message("user", user_message)

    updated_system_prompt = state.executor.get_system_prompt() + state.kb_prompt_block
    if state.llm_messages and state.llm_messages[0]["role"] == "system":
        state.llm_messages[0]["content"] = updated_system_prompt

    all_functions_called = []
    all_function_results = []
    save_record_events: list[dict] = []
    is_ended = False
    max_iterations = 5
    last_text_content = ""

    try:
        for iteration in range(max_iterations):
            # Rebuild the exposed tools at the top of EACH iteration. A previous
            # handle_function_call may have advanced the flow (collect → set_var →
            # api → ...), and get_function_schemas() now gates functions to the
            # reachable node. Building tools once before the loop left a stale list,
            # so a later forced tool_choice could name a function no longer present
            # → OpenAI 400 (previously swallowed into a generic apology). Rebuilding
            # keeps `tools` and `tool_choice` in lockstep with the live flow state.
            function_schemas = state.executor.get_function_schemas()
            tools = [
                {"type": "function", "function": schema.get("function", schema)}
                for schema in function_schemas
            ]
            # Mirror the always-on live "request_human" escalation tool so the
            # simulator can preview a caller asking for a person mid-flow. Handled
            # with a mocked transfer result below (no real Twilio call).
            if state.escalation_target:
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": "request_human",
                            "description": (
                                "Connect the caller to a human agent. Call this ONLY "
                                "when the caller explicitly asks to speak with a person, "
                                "human, agent, representative, or a live staff member."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {},
                                "required": [],
                            },
                        },
                    }
                )
            # Mirror the backing assistant's standalone capability tools so the
            # LLM can preview capability calls outside a flow — identical to
            # voice/SMS. Capability names never collide with flow function names
            # (execute_* / collect_*), so no dedup against `tools` is needed.
            if state.capability_schemas:
                tools.extend(state.capability_schemas)
            if state.dynamic_operation_schemas:
                tools.extend(state.dynamic_operation_schemas)
            exposed_names = {
                t["function"]["name"]
                for t in tools
                if t.get("function", {}).get("name")
            }

            # Force the specific function when the current node requires it.
            # Using "auto" lets the LLM return a plain text reply and stall the
            # conversation waiting for the next user input instead of progressing
            # the flow. Only force a name that is actually present in the freshly
            # built tool list — forcing a gated-out/absent name is exactly what
            # triggered the OpenAI 400.
            #
            # Only API_REQUEST forces a tool call. We used to also force
            # collect_{var_key} for COLLECT_SLOT and require *any* call for
            # COLLECT_FORM, but that prevented the model from answering a
            # mid-flow question — it was compelled to call the collect function
            # instead of replying from the knowledge base. Live calls never force
            # tool_choice, so leaving collect nodes on "auto" here makes the
            # simulator mirror production: the model can answer a question, then
            # resume collection on the next turn. API_REQUEST still forces
            # because "auto" lets the model narrate instead of firing the request
            # (see memory: simulator-api-node-stall).
            current_node = state.executor.state.get_current_node()
            forced_name = None
            if current_node and current_node.type in (
                NodeType.API_REQUEST,
                NodeType.CAPABILITY,
            ):
                candidate = f"execute_{current_node.id}"
                if candidate not in all_functions_called:
                    forced_name = candidate

            if forced_name and forced_name in exposed_names:
                tool_choice = {"type": "function", "function": {"name": forced_name}}
            else:
                tool_choice = "auto" if tools else None

            response = openai_client.chat.completions.create(
                model=state.model,
                messages=state.llm_messages,
                tools=tools if tools else None,
                tool_choice=tool_choice,
            )

            assistant_message = response.choices[0].message

            if assistant_message.tool_calls:
                # Preserve any content the LLM included alongside the tool call
                # (e.g. a thinking message) so it reaches the final response.
                if assistant_message.content:
                    last_text_content = assistant_message.content

                tool_calls_to_process = []
                for tool_call in assistant_message.tool_calls:
                    tool_calls_to_process.append(
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments,
                            },
                        }
                    )

                state.llm_messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_message.content,
                        "tool_calls": tool_calls_to_process,
                    }
                )

                for tool_call in assistant_message.tool_calls:
                    function_name = tool_call.function.name
                    try:
                        function_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        function_args = {}

                    if function_name == "request_human":
                        # Escalation is a non-flow tool; mock the transfer so the
                        # simulator shows the outcome without a real Twilio call.
                        result = {
                            "success": True,
                            "action": "transfer",
                            "target": state.escalation_target,
                            "message": (
                                "[Simulation] Would connect the caller to a human "
                                f"at {state.escalation_target}."
                            ),
                        }
                    elif function_name in state.capability_names:
                        # Standalone capability tool (Task #329): resolve + execute
                        # through the shared resolver, so the simulator hits the
                        # same property-scoped provider a live call would — real
                        # data, real fail-closed behavior, no vendor exposure.
                        from botelier.services.capabilities import CapabilityResolver

                        resolver = CapabilityResolver(
                            state.executor.db_session,
                            state.account_id,
                            state.executor.property_id,
                        )
                        result = await resolver.execute(
                            function_name,
                            channel="test",
                            arguments=function_args,
                            contact_ref=state.session_id,
                        )
                    elif function_name in state.dynamic_operation_names:
                        # Universal Adapter DYNAMIC_OPERATION tool (Task #356):
                        # execute through the same certified ActionExecutor →
                        # IntegrationClient pipeline as voice/SMS — full property
                        # isolation, resilience gates, response redaction.
                        result = await _execute_sim_dynamic_operation(
                            state, function_name, function_args, db
                        )
                    else:
                        result = await state.executor.handle_function_call(
                            function_name, function_args
                        )

                    all_functions_called.append(function_name)
                    all_function_results.append(result)

                    if function_name.startswith("save_record_"):
                        save_record_events.append(
                            {
                                "record_saved": result.get("record_saved", False),
                                "message": result.get("message", "Record could not be saved"),
                            }
                        )

                    if result.get("action") in ["end", "transfer"]:
                        is_ended = True

                    state.llm_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(result),
                        }
                    )

                if is_ended:
                    last_result = all_function_results[-1] if all_function_results else {}
                    return {
                        "response": last_result.get("message", "Thank you for calling. Goodbye!"),
                        "function_called": all_functions_called[-1]
                        if all_functions_called
                        else None,
                        "function_result": last_result,
                        "is_ended": True,
                        "save_record_events": save_record_events,
                    }
            else:
                content = assistant_message.content or ""
                last_text_content = content
                state.add_llm_message("assistant", content)

                return {
                    "response": content,
                    "function_called": all_functions_called[-1] if all_functions_called else None,
                    "function_result": all_function_results[-1] if all_function_results else None,
                    "is_ended": is_ended,
                    "save_record_events": save_record_events,
                }

        return {
            "response": last_text_content
            or "I've processed your information. Is there anything else I can help with?",
            "function_called": all_functions_called[-1] if all_functions_called else None,
            "function_result": all_function_results[-1] if all_function_results else None,
            "is_ended": is_ended,
            "save_record_events": save_record_events,
        }

    except Exception as e:
        # Log the full traceback server-side for debugging.
        logger.exception("LLM processing error during simulation")
        # Surface the real cause to the simulator UI so flow-config bugs are
        # visible instead of hidden behind a generic apology. Expose ONLY the
        # exception type and a single line of its message — never a traceback or
        # request headers, which can carry integration credentials.
        _msg = str(e).splitlines()[0] if str(e) else ""
        error_summary = f"{type(e).__name__}: {_msg}".strip().rstrip(":").strip()
        return {
            "response": "I apologize, I'm having trouble processing that. Could you please repeat?",
            "function_called": all_functions_called[-1] if all_functions_called else None,
            "function_result": all_function_results[-1] if all_function_results else None,
            "is_ended": False,
            "error": error_summary,
            "save_record_events": save_record_events,
        }


def _get_session_and_check_access(session_id: str, user: User, db: Session) -> "SimulationState":
    """Retrieve a simulation session and verify the caller has view access to its account."""
    state = SimulationSession.sessions.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    if state.account_id:
        check_account_permission(user, state.account_id, "tools.view", db)
    return state


@router.delete("/session/{session_id}")
async def end_simulation(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """End and cleanup a simulation session."""
    _get_session_and_check_access(session_id, user, db)
    del SimulationSession.sessions[session_id]
    return {"status": "ended"}


@router.get("/session/{session_id}/state")
async def get_simulation_state(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get current state of a simulation session."""
    state = _get_session_and_check_access(session_id, user, db)

    return {
        "state": state.get_state_snapshot(),
        "messages": state.messages,
        "suggested_functions": _get_suggested_functions(state.executor),
    }


@router.post("/test-api", response_model=TestAPIResponse)
async def test_api_endpoint(request: TestAPIRequest, user: User = Depends(get_current_user)):
    """Test an API endpoint with variable substitution.

    This allows testing API calls configured in flows before
    they're used in production calls.
    """
    import re
    from urllib.parse import urlparse

    import httpx

    def substitute_variables(text: str, variables: dict) -> str:
        def replacer(match):
            var_name = match.group(1)
            return str(variables.get(var_name, match.group(0)))

        return re.sub(r"\{\{(\w+)\}\}", replacer, text)

    variables = request.variables or {}
    resolved_url = substitute_variables(request.url, variables)
    resolved_body = None
    if request.body:
        resolved_body = substitute_variables(request.body, variables)

    parsed = urlparse(resolved_url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only HTTP/HTTPS URLs are allowed")
    hostname = parsed.hostname or ""
    if not hostname:
        raise HTTPException(status_code=400, detail="Missing hostname in URL")
    if hostname in _BLOCKED_LITERAL_HOSTS:
        raise HTTPException(
            status_code=400, detail="Requests to internal addresses are not allowed"
        )

    try:
        async with httpx.AsyncClient(transport=SSRFSafeTransport(), timeout=30.0) as client:
            response = await client.request(
                method=request.method.upper(),
                url=resolved_url,
                headers=request.headers or {},
                content=resolved_body if resolved_body else None,
            )

            try:
                response_body = response.json()
            except:
                response_body = response.text

            return TestAPIResponse(
                status_code=response.status_code,
                response_body=response_body,
                response_headers=dict(response.headers),
                resolved_url=resolved_url,
                resolved_body=resolved_body,
            )
    except httpx.TimeoutException:
        return TestAPIResponse(
            status_code=0,
            response_body=None,
            response_headers={},
            resolved_url=resolved_url,
            resolved_body=resolved_body,
            error="Request timed out after 30 seconds",
        )
    except Exception as e:
        return TestAPIResponse(
            status_code=0,
            response_body=None,
            response_headers={},
            resolved_url=resolved_url,
            resolved_body=resolved_body,
            error=str(e),
        )


def _get_suggested_functions(executor: FlowExecutor) -> list[dict]:
    """Get list of functions that can be called in current state."""
    schemas = executor.get_function_schemas()

    suggested = []
    for schema in schemas:
        func = schema.get("function", {})
        suggested.append(
            {
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {}),
            }
        )

    return suggested
