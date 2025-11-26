"""
Flow Simulation API - Test flows with real LLM conversations.

This module provides endpoints for simulating conversation flows
with actual LLM-powered responses, allowing users to test slot collection,
API calls, and conditions in a chat-like interface without requiring Twilio.
"""

import os
import uuid
import json
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from loguru import logger
from openai import OpenAI

from ..database import get_db
from ..models.tool import Tool
from ..flow_executor import FlowExecutor, parse_flow_config


router = APIRouter(prefix="/api/simulate", tags=["Simulation"])

# the newest OpenAI model is "gpt-5" which was released August 7, 2025.
# do not change this unless explicitly requested by the user
OPENAI_MODEL = "gpt-4o-mini"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


class SimulationSession:
    """In-memory storage for simulation sessions."""
    sessions: dict[str, "SimulationState"] = {}


class SimulationState:
    """Tracks state for a simulation session."""
    
    def __init__(self, tool_id: str, executor: FlowExecutor, tool_name: str = ""):
        self.tool_id = tool_id
        self.tool_name = tool_name
        self.executor = executor
        self.messages: list[dict] = []
        self.llm_messages: list[dict] = []
        self.is_ended = False
        self._init_llm_context()
    
    def _init_llm_context(self):
        """Initialize LLM conversation context with system prompt."""
        system_prompt = self.executor.get_system_prompt()
        initial_messages = self.executor.get_initial_messages()
        combined_greeting = " ".join(initial_messages)
        
        self.llm_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "assistant", "content": combined_greeting}
        ]
    
    def add_message(self, role: str, content: str, metadata: Optional[dict] = None):
        self.messages.append({
            "role": role,
            "content": content,
            "metadata": metadata or {}
        })
    
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
            "progress": self.executor.get_progress()
        }


class StartSimulationRequest(BaseModel):
    tool_id: str


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


@router.post("/start", response_model=StartSimulationResponse)
async def start_simulation(
    request: StartSimulationRequest,
    db: Session = Depends(get_db)
):
    """
    Start a new flow simulation session.
    
    Creates a FlowExecutor instance and returns the initial greeting
    along with variables that need to be collected.
    """
    tool = db.query(Tool).filter(Tool.id == request.tool_id).first()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    
    if tool.tool_type.value != "FLOW":
        raise HTTPException(status_code=400, detail="Tool is not a flow type")
    
    config_data = tool.config if tool.config else {}
    flow_config_dict = dict(config_data) if isinstance(config_data, dict) else {}
    if not flow_config_dict.get("nodes"):
        raise HTTPException(status_code=400, detail="Flow has no configured nodes")
    
    try:
        flow_config = parse_flow_config(flow_config_dict)
        executor = FlowExecutor(flow_config)
    except Exception as e:
        logger.error(f"Failed to parse flow config: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid flow configuration: {str(e)}")
    
    session_id = str(uuid.uuid4())
    state = SimulationState(tool_id=request.tool_id, executor=executor, tool_name=tool.name)
    
    initial_messages = executor.get_initial_messages()
    greeting = " ".join(initial_messages)
    
    for msg in initial_messages:
        state.add_message("assistant", msg)
    
    SimulationSession.sessions[session_id] = state
    
    variables_to_collect = [
        {
            "key": v.key,
            "type": v.type.value,
            "description": v.description,
            "required": v.required,
            "choices": v.choices
        }
        for v in flow_config.variables
    ]
    
    logger.info(f"Started simulation session {session_id} for tool {tool.name}")
    
    return StartSimulationResponse(
        session_id=session_id,
        greeting=greeting,
        variables_to_collect=variables_to_collect,
        state=state.get_state_snapshot(),
        messages=state.messages
    )


@router.post("/message", response_model=SimulateMessageResponse)
async def simulate_message(request: SimulateMessageRequest):
    """
    Process a message in the simulation using LLM with function calling.
    
    If function_call is provided, execute that function directly (manual mode).
    Otherwise, send the message to the LLM and let it decide what to do.
    """
    state = SimulationSession.sessions.get(request.session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if state.is_ended:
        raise HTTPException(status_code=400, detail="Simulation has ended")
    
    executor = state.executor
    response_text = ""
    function_called = None
    function_result = None
    
    state.add_message("user", request.message)
    
    if request.function_call:
        try:
            result = await executor.handle_function_call(
                request.function_call,
                request.function_args or {}
            )
            function_called = request.function_call
            function_result = result
            
            if result.get("action") == "end":
                state.is_ended = True
                response_text = str(result.get("message", "Thank you for calling. Goodbye!"))
            elif result.get("action") == "transfer":
                state.is_ended = True
                response_text = f"[Transferring call to {result.get('target')}] {result.get('message', '')}"
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
        
        if llm_response.get("is_ended"):
            state.is_ended = True
    
    state.add_message("assistant", response_text, {
        "function_called": function_called,
        "function_result": function_result
    })
    
    suggested_functions = _get_suggested_functions(executor)
    
    return SimulateMessageResponse(
        response=response_text,
        function_called=function_called,
        function_result=function_result,
        state=state.get_state_snapshot(),
        messages=state.messages,
        suggested_functions=suggested_functions
    )


async def _process_with_llm(state: SimulationState, user_message: str) -> dict:
    """
    Process user message with OpenAI LLM using function calling.
    
    The LLM will naturally converse and call functions to collect slots.
    Handles multiple function calls in sequence until a text response is generated.
    """
    if not openai_client:
        return {
            "response": "OpenAI API key not configured. Please use the function picker to test manually.",
            "function_called": None,
            "function_result": None,
            "is_ended": False
        }
    
    state.add_llm_message("user", user_message)
    
    function_schemas = state.executor.get_function_schemas()
    tools = [
        {
            "type": "function",
            "function": schema.get("function", schema)
        }
        for schema in function_schemas
    ]
    
    all_functions_called = []
    all_function_results = []
    is_ended = False
    max_iterations = 5
    
    try:
        for iteration in range(max_iterations):
            response = openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=state.llm_messages,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None,
            )
            
            assistant_message = response.choices[0].message
            
            if assistant_message.tool_calls:
                tool_calls_to_process = []
                for tool_call in assistant_message.tool_calls:
                    tool_calls_to_process.append({
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    })
                
                state.llm_messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls_to_process
                })
                
                for tool_call in assistant_message.tool_calls:
                    function_name = tool_call.function.name
                    try:
                        function_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        function_args = {}
                    
                    result = await state.executor.handle_function_call(function_name, function_args)
                    
                    all_functions_called.append(function_name)
                    all_function_results.append(result)
                    
                    if result.get("action") in ["end", "transfer"]:
                        is_ended = True
                    
                    state.llm_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result)
                    })
                
                if is_ended:
                    last_result = all_function_results[-1] if all_function_results else {}
                    return {
                        "response": last_result.get("message", "Thank you for calling. Goodbye!"),
                        "function_called": all_functions_called[-1] if all_functions_called else None,
                        "function_result": last_result,
                        "is_ended": True
                    }
            else:
                content = assistant_message.content or ""
                state.add_llm_message("assistant", content)
                
                return {
                    "response": content,
                    "function_called": all_functions_called[-1] if all_functions_called else None,
                    "function_result": all_function_results[-1] if all_function_results else None,
                    "is_ended": is_ended
                }
        
        return {
            "response": "I've processed your information. Is there anything else I can help with?",
            "function_called": all_functions_called[-1] if all_functions_called else None,
            "function_result": all_function_results[-1] if all_function_results else None,
            "is_ended": is_ended
        }
    
    except Exception as e:
        logger.error(f"LLM processing error: {e}")
        return {
            "response": f"I apologize, I'm having trouble processing that. Could you please repeat?",
            "function_called": None,
            "function_result": None,
            "is_ended": False
        }


@router.delete("/session/{session_id}")
async def end_simulation(session_id: str):
    """End and cleanup a simulation session."""
    if session_id in SimulationSession.sessions:
        del SimulationSession.sessions[session_id]
        return {"status": "ended"}
    raise HTTPException(status_code=404, detail="Session not found")


@router.get("/session/{session_id}/state")
async def get_simulation_state(session_id: str):
    """Get current state of a simulation session."""
    state = SimulationSession.sessions.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "state": state.get_state_snapshot(),
        "messages": state.messages,
        "suggested_functions": _get_suggested_functions(state.executor)
    }


@router.post("/test-api", response_model=TestAPIResponse)
async def test_api_endpoint(request: TestAPIRequest):
    """
    Test an API endpoint with variable substitution.
    
    This allows testing API calls configured in flows before
    they're used in production calls.
    """
    import httpx
    import re
    
    def substitute_variables(text: str, variables: dict) -> str:
        def replacer(match):
            var_name = match.group(1)
            return str(variables.get(var_name, match.group(0)))
        return re.sub(r'\{\{(\w+)\}\}', replacer, text)
    
    variables = request.variables or {}
    resolved_url = substitute_variables(request.url, variables)
    resolved_body = None
    if request.body:
        resolved_body = substitute_variables(request.body, variables)
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=request.method.upper(),
                url=resolved_url,
                headers=request.headers or {},
                content=resolved_body if resolved_body else None
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
                resolved_body=resolved_body
            )
    except httpx.TimeoutException:
        return TestAPIResponse(
            status_code=0,
            response_body=None,
            response_headers={},
            resolved_url=resolved_url,
            resolved_body=resolved_body,
            error="Request timed out after 30 seconds"
        )
    except Exception as e:
        return TestAPIResponse(
            status_code=0,
            response_body=None,
            response_headers={},
            resolved_url=resolved_url,
            resolved_body=resolved_body,
            error=str(e)
        )


def _get_suggested_functions(executor: FlowExecutor) -> list[dict]:
    """Get list of functions that can be called in current state."""
    schemas = executor.get_function_schemas()
    
    suggested = []
    for schema in schemas:
        func = schema.get("function", {})
        suggested.append({
            "name": func.get("name", ""),
            "description": func.get("description", ""),
            "parameters": func.get("parameters", {})
        })
    
    return suggested
