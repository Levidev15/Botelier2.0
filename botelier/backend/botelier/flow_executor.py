"""
Flow Executor - Converts visual flows to Pipecat-compatible function schemas and executes them.

This module handles:
1. Loading flow configurations from the database
2. Converting flow nodes to LLM function schemas
3. Managing conversation state through the flow
4. Executing slot collection, API calls, and conditions
"""

import re
import json
import httpx
from typing import Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum


class NodeType(str, Enum):
    INITIAL = "initial"
    MESSAGE = "message"
    COLLECT_SLOT = "collect_slot"
    API_REQUEST = "api_request"
    CONDITION = "condition"
    TRANSFER = "transfer"
    END = "end"


class SlotType(str, Enum):
    TEXT = "text"
    DATE = "date"
    NUMBER = "number"
    PHONE = "phone"
    EMAIL = "email"
    TIME = "time"
    CHOICE = "choice"


@dataclass
class FlowVariable:
    key: str
    type: SlotType
    description: str
    required: bool = True
    default_value: Optional[str] = None
    choices: Optional[list[str]] = None


@dataclass
class SlotConfig:
    variable_key: str
    prompt: str
    type: SlotType
    retry_prompt: Optional[str] = None
    max_retries: int = 3
    validation: Optional[dict] = None


@dataclass
class APIRequestConfig:
    method: str
    url: str
    headers: Optional[dict[str, str]] = None
    body_template: Optional[str] = None
    response_mapping: Optional[dict[str, str]] = None
    on_success: Optional[str] = None
    on_error: Optional[str] = None


@dataclass
class ConditionConfig:
    variable: str
    operator: str
    value: str
    true_target: Optional[str] = None
    false_target: Optional[str] = None


@dataclass
class TransferConfig:
    phone_number: str
    pre_transfer_message: Optional[str] = None
    warm_transfer: bool = False


@dataclass
class FlowNode:
    id: str
    type: NodeType
    data: dict
    position: dict = field(default_factory=lambda: {"x": 0, "y": 0})


@dataclass
class FlowEdge:
    id: str
    source: str
    target: str
    source_handle: Optional[str] = None
    target_handle: Optional[str] = None


@dataclass
class FlowConfig:
    initial_node: Optional[str]
    nodes: list[FlowNode]
    edges: list[FlowEdge]
    variables: list[FlowVariable]


class FlowState:
    """Tracks the state of a conversation flow execution."""
    
    def __init__(self, flow_config: FlowConfig):
        self.flow_config = flow_config
        self.current_node_id: Optional[str] = flow_config.initial_node
        self.collected_slots: dict[str, Any] = {}
        self.pending_slot: Optional[str] = None
        self.retry_count: int = 0
        self.is_complete: bool = False
        self.transfer_requested: bool = False
        self.transfer_target: Optional[str] = None
        
        for var in flow_config.variables:
            if var.default_value:
                self.collected_slots[var.key] = var.default_value
    
    def get_variable(self, key: str) -> Optional[Any]:
        return self.collected_slots.get(key)
    
    def set_variable(self, key: str, value: Any) -> None:
        self.collected_slots[key] = value
    
    def get_current_node(self) -> Optional[FlowNode]:
        if not self.current_node_id:
            return None
        for node in self.flow_config.nodes:
            if node.id == self.current_node_id:
                return node
        return None
    
    def get_next_node(self, from_node_id: str, handle: Optional[str] = None) -> Optional[FlowNode]:
        """Find the next node connected via edges."""
        for edge in self.flow_config.edges:
            if edge.source == from_node_id:
                if handle and edge.source_handle != handle:
                    continue
                for node in self.flow_config.nodes:
                    if node.id == edge.target:
                        return node
        return None
    
    def advance_to(self, node_id: str) -> None:
        """Move to a specific node."""
        self.current_node_id = node_id
        self.pending_slot = None
        self.retry_count = 0


def substitute_variables(template: str, variables: dict[str, Any]) -> str:
    """Replace {{variable_name}} placeholders with actual values."""
    def replace_var(match):
        var_name = match.group(1)
        value = variables.get(var_name)
        if value is None:
            return match.group(0)
        return str(value)
    
    return re.sub(r'\{\{(\w+)\}\}', replace_var, template)


def parse_flow_config(config_dict: dict) -> FlowConfig:
    """Parse a raw flow config dict into typed FlowConfig."""
    nodes = []
    for node_data in config_dict.get("nodes", []):
        nodes.append(FlowNode(
            id=node_data["id"],
            type=NodeType(node_data.get("type", "message")),
            data=node_data.get("data", {}),
            position=node_data.get("position", {"x": 0, "y": 0})
        ))
    
    edges = []
    for edge_data in config_dict.get("edges", []):
        edges.append(FlowEdge(
            id=edge_data["id"],
            source=edge_data["source"],
            target=edge_data["target"],
            source_handle=edge_data.get("sourceHandle"),
            target_handle=edge_data.get("targetHandle")
        ))
    
    variables = []
    for var_data in config_dict.get("variables", []):
        variables.append(FlowVariable(
            key=var_data["key"],
            type=SlotType(var_data.get("type", "text")),
            description=var_data.get("description", ""),
            required=var_data.get("required", True),
            default_value=var_data.get("defaultValue"),
            choices=var_data.get("choices")
        ))
    
    return FlowConfig(
        initial_node=config_dict.get("initial_node"),
        nodes=nodes,
        edges=edges,
        variables=variables
    )


class FlowExecutor:
    """
    Executes a conversation flow during a Pipecat call.
    
    The executor maintains state and provides methods that can be called
    by Pipecat's LLM function calling system.
    """
    
    def __init__(
        self,
        flow_config: FlowConfig,
        speak_callback: Optional[Callable[[str], Awaitable[None]]] = None,
        transfer_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
        end_call_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ):
        self.flow_config = flow_config
        self.state = FlowState(flow_config)
        self.speak_callback = speak_callback
        self.transfer_callback = transfer_callback
        self.end_call_callback = end_call_callback
    
    def get_variables_in_flow_order(self) -> list[FlowVariable]:
        """
        Get variables in the order they appear in the flow traversal.
        
        This traverses the flow graph from the initial node and returns
        variables in the order their collect_slot nodes are encountered.
        """
        ordered_keys = []
        visited = set()
        
        def get_next_nodes(node_id: str) -> list[FlowNode]:
            """Get all nodes connected from a source node."""
            next_nodes = []
            for edge in self.flow_config.edges:
                if edge.source == node_id:
                    for node in self.flow_config.nodes:
                        if node.id == edge.target:
                            next_nodes.append(node)
            return next_nodes
        
        def traverse(node_id: str):
            if node_id in visited:
                return
            visited.add(node_id)
            
            node = None
            for n in self.flow_config.nodes:
                if n.id == node_id:
                    node = n
                    break
            
            if not node:
                return
            
            if node.type == NodeType.COLLECT_SLOT:
                slot = node.data.get("slot", {})
                var_key = slot.get("variableKey")
                if var_key and var_key not in ordered_keys:
                    ordered_keys.append(var_key)
            
            for next_node in get_next_nodes(node_id):
                traverse(next_node.id)
        
        if self.flow_config.initial_node:
            traverse(self.flow_config.initial_node)
        
        var_by_key = {v.key: v for v in self.flow_config.variables}
        ordered_variables = []
        for key in ordered_keys:
            if key in var_by_key:
                ordered_variables.append(var_by_key[key])
        
        for var in self.flow_config.variables:
            if var not in ordered_variables:
                ordered_variables.append(var)
        
        return ordered_variables
    
    def get_system_prompt(self) -> str:
        """Generate the system prompt including flow context."""
        initial_node = None
        for node in self.flow_config.nodes:
            if node.type == NodeType.INITIAL:
                initial_node = node
                break
        
        base_prompt = ""
        if initial_node and initial_node.data.get("systemPrompt"):
            base_prompt = initial_node.data["systemPrompt"]
        
        flow_context = self._generate_flow_context()
        
        return f"""{base_prompt}

You are executing a structured conversation flow. Follow these guidelines:
1. Collect information in the order specified by the flow
2. Use the provided functions to progress through the flow
3. Be natural and conversational while following the flow structure
4. If the guest provides information proactively, acknowledge and record it

{flow_context}"""
    
    def _generate_flow_context(self) -> str:
        """Generate context about what information needs to be collected."""
        ordered_vars = self.get_variables_in_flow_order()
        slots_to_collect = []
        
        for var in ordered_vars:
            if var.key not in self.state.collected_slots:
                node_instructions = self._get_instructions_for_variable(var.key)
                slot_info = f"- {var.key}: {var.description} ({var.type.value})"
                if node_instructions:
                    slot_info += f"\n  Instructions: {node_instructions}"
                slots_to_collect.append(slot_info)
        
        if slots_to_collect:
            return f"""Information to collect (in order):
{chr(10).join(slots_to_collect)}"""
        return "All required information has been collected."
    
    def _get_instructions_for_variable(self, var_key: str) -> Optional[str]:
        """Get the instructions for the node that collects a specific variable."""
        for node in self.flow_config.nodes:
            if node.type == NodeType.COLLECT_SLOT:
                slot = node.data.get("slot", {})
                if slot.get("variableKey") == var_key:
                    return node.data.get("instructions")
        return None
    
    def get_current_node_instructions(self) -> Optional[str]:
        """Get instructions for the current node."""
        current_node = self.state.get_current_node()
        if current_node:
            return current_node.data.get("instructions")
        return None
    
    def get_greeting(self) -> str:
        """Get the initial greeting message."""
        for node in self.flow_config.nodes:
            if node.type == NodeType.INITIAL:
                return node.data.get("greeting", "Hello! How can I assist you?")
        return "Hello! How can I assist you?"
    
    def get_initial_messages(self) -> list[str]:
        """
        Get all initial messages, following auto-advance chain.
        
        If the initial node has awaitResponse=false, it will continue
        to get messages from connected nodes until one requires a response
        or reaches a node that collects input (collect_slot, end, transfer).
        """
        messages = []
        initial_node = None
        
        for node in self.flow_config.nodes:
            if node.type == NodeType.INITIAL:
                initial_node = node
                break
        
        if not initial_node:
            return ["Hello! How can I assist you?"]
        
        messages.append(initial_node.data.get("greeting", "Hello! How can I assist you?"))
        
        await_response = initial_node.data.get("awaitResponse", True)
        if await_response:
            return messages
        
        current_node = self.state.get_next_node(initial_node.id)
        while current_node:
            node_message = self._get_node_message(current_node)
            if node_message:
                messages.append(node_message)
            
            self.state.advance_to(current_node.id)
            
            if current_node.type in [NodeType.COLLECT_SLOT, NodeType.END, NodeType.TRANSFER]:
                break
            
            node_await = current_node.data.get("awaitResponse", current_node.data.get("waitForResponse", True))
            if node_await:
                break
            
            current_node = self.state.get_next_node(current_node.id)
        
        return messages
    
    def _get_node_message(self, node: FlowNode) -> Optional[str]:
        """Extract the spoken message from a node based on its type."""
        if node.type == NodeType.MESSAGE:
            return substitute_variables(
                node.data.get("message", ""),
                self.state.collected_slots
            )
        elif node.type == NodeType.COLLECT_SLOT:
            slot = node.data.get("slot", {})
            return slot.get("prompt", "")
        elif node.type == NodeType.END:
            return substitute_variables(
                node.data.get("closingMessage", "Thank you for calling. Goodbye!"),
                self.state.collected_slots
            )
        elif node.type == NodeType.TRANSFER:
            transfer = node.data.get("transfer", {})
            return transfer.get("preTransferMessage", "Please hold while I transfer you.")
        return None
    
    def get_function_schemas(self) -> list[dict]:
        """
        Generate Pipecat-compatible function schemas from the flow.
        
        This creates functions for:
        1. Collecting each slot variable
        2. API requests
        3. Transfer calls
        4. Ending the call
        """
        functions = []
        
        for var in self.flow_config.variables:
            func_schema = self._create_slot_function(var)
            functions.append(func_schema)
        
        for node in self.flow_config.nodes:
            if node.type == NodeType.API_REQUEST:
                func_schema = self._create_api_function(node)
                functions.append(func_schema)
            elif node.type == NodeType.TRANSFER:
                func_schema = self._create_transfer_function(node)
                functions.append(func_schema)
            elif node.type == NodeType.END:
                func_schema = self._create_end_function(node)
                functions.append(func_schema)
        
        functions.append({
            "type": "function",
            "function": {
                "name": "confirm_booking",
                "description": "Confirm the booking details with the guest after all information is collected",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "confirmed": {
                            "type": "boolean",
                            "description": "Whether the guest confirmed the booking details"
                        }
                    },
                    "required": ["confirmed"]
                }
            }
        })
        
        return functions
    
    def _create_slot_function(self, var: FlowVariable) -> dict:
        """Create a function schema for collecting a slot."""
        param_type = "string"
        if var.type == SlotType.NUMBER:
            param_type = "integer"
        elif var.type == SlotType.CHOICE and var.choices:
            return {
                "type": "function",
                "function": {
                    "name": f"collect_{var.key}",
                    "description": f"Record the {var.description}",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            var.key: {
                                "type": "string",
                                "enum": var.choices,
                                "description": var.description
                            }
                        },
                        "required": [var.key]
                    }
                }
            }
        
        return {
            "type": "function",
            "function": {
                "name": f"collect_{var.key}",
                "description": f"Record the {var.description}",
                "parameters": {
                    "type": "object",
                    "properties": {
                        var.key: {
                            "type": param_type,
                            "description": var.description
                        }
                    },
                    "required": [var.key]
                }
            }
        }
    
    def _create_api_function(self, node: FlowNode) -> dict:
        """Create a function schema for an API request node."""
        return {
            "type": "function",
            "function": {
                "name": f"execute_{node.id}",
                "description": f"Execute API call: {node.data.get('name', node.id)}",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    
    def _create_transfer_function(self, node: FlowNode) -> dict:
        """Create a function schema for a transfer node."""
        transfer_data = node.data.get("transfer", {})
        return {
            "type": "function",
            "function": {
                "name": f"transfer_{node.id}",
                "description": f"Transfer call: {node.data.get('name', 'to agent')}",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "Reason for the transfer"
                        }
                    },
                    "required": []
                }
            }
        }
    
    def _create_end_function(self, node: FlowNode) -> dict:
        """Create a function schema for an end node."""
        return {
            "type": "function",
            "function": {
                "name": f"end_call_{node.id}",
                "description": f"End the call: {node.data.get('name', 'End Call')}",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    
    async def handle_function_call(self, function_name: str, arguments: dict) -> dict:
        """
        Handle a function call from the LLM.
        
        Returns a result dict with:
        - success: bool
        - message: str (to speak to the guest)
        - action: Optional action type (transfer, end, etc.)
        """
        if function_name.startswith("collect_"):
            return await self._handle_slot_collection(function_name, arguments)
        elif function_name.startswith("execute_"):
            return await self._handle_api_request(function_name, arguments)
        elif function_name.startswith("transfer_"):
            return await self._handle_transfer(function_name, arguments)
        elif function_name.startswith("end_call_"):
            return await self._handle_end_call(function_name, arguments)
        elif function_name == "confirm_booking":
            return await self._handle_confirm_booking(arguments)
        else:
            return {"success": False, "message": "Unknown function", "action": None}
    
    async def _handle_slot_collection(self, function_name: str, arguments: dict) -> dict:
        """Handle collecting a slot value."""
        var_key = function_name.replace("collect_", "")
        
        if var_key in arguments:
            value = arguments[var_key]
            self.state.set_variable(var_key, value)
            
            # Find the node that collects this variable and advance to it
            collecting_node_id = None
            for node in self.flow_config.nodes:
                if node.type == NodeType.COLLECT_SLOT:
                    slot = node.data.get("slot", {})
                    if slot.get("variableKey") == var_key:
                        collecting_node_id = node.id
                        self.state.advance_to(node.id)
                        break
            
            var_info = None
            for var in self.flow_config.variables:
                if var.key == var_key:
                    var_info = var
                    break
            
            return {
                "success": True,
                "message": f"Recorded {var_info.description if var_info else var_key}: {value}",
                "action": None,
                "collected": {var_key: value},
                "current_node_id": collecting_node_id
            }
        
        return {
            "success": False,
            "message": f"Missing value for {var_key}",
            "action": None,
            "current_node_id": self.state.current_node_id
        }
    
    async def _handle_api_request(self, function_name: str, arguments: dict) -> dict:
        """Execute an API request."""
        node_id = function_name.replace("execute_", "")
        node = None
        for n in self.flow_config.nodes:
            if n.id == node_id:
                node = n
                break
        
        if not node:
            return {"success": False, "message": "API node not found", "action": None}
        
        api_config = node.data.get("api", {})
        url = substitute_variables(api_config.get("url", ""), self.state.collected_slots)
        
        try:
            async with httpx.AsyncClient() as client:
                method = api_config.get("method", "GET").upper()
                headers = api_config.get("headers", {})
                
                body = None
                if api_config.get("bodyTemplate"):
                    body_str = substitute_variables(api_config["bodyTemplate"], self.state.collected_slots)
                    body = json.loads(body_str)
                
                if method == "GET":
                    response = await client.get(url, headers=headers)
                elif method == "POST":
                    response = await client.post(url, headers=headers, json=body)
                elif method == "PUT":
                    response = await client.put(url, headers=headers, json=body)
                elif method == "DELETE":
                    response = await client.delete(url, headers=headers)
                else:
                    return {"success": False, "message": f"Unsupported method: {method}", "action": None}
                
                if response.status_code >= 200 and response.status_code < 300:
                    response_data = response.json()
                    
                    if api_config.get("responseMapping"):
                        for var_key, json_path in api_config["responseMapping"].items():
                            value = self._extract_json_value(response_data, json_path)
                            if value is not None:
                                self.state.set_variable(var_key, value)
                    
                    self.state.advance_to(node_id)
                    return {
                        "success": True,
                        "message": api_config.get("onSuccess", "API request completed successfully"),
                        "action": None,
                        "response": response_data,
                        "current_node_id": node_id
                    }
                else:
                    return {
                        "success": False,
                        "message": api_config.get("onError", "There was an issue processing your request"),
                        "action": None,
                        "current_node_id": node_id
                    }
        
        except Exception as e:
            return {
                "success": False,
                "message": api_config.get("onError", "There was an issue processing your request"),
                "action": None,
                "error": str(e),
                "current_node_id": node_id
            }
    
    def _extract_json_value(self, data: dict, path: str) -> Any:
        """Extract a value from JSON using dot notation (e.g., 'response.data.id')."""
        parts = path.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit():
                idx = int(part)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None
            else:
                return None
        return current
    
    async def _handle_transfer(self, function_name: str, arguments: dict) -> dict:
        """Handle a call transfer request."""
        node_id = function_name.replace("transfer_", "")
        node = None
        for n in self.flow_config.nodes:
            if n.id == node_id:
                node = n
                break
        
        if not node:
            return {"success": False, "message": "Transfer node not found", "action": None, "current_node_id": None}
        
        transfer_config = node.data.get("transfer", {})
        phone_number = transfer_config.get("phoneNumber", "")
        pre_message = transfer_config.get("preTransferMessage", "Please hold while I transfer you.")
        
        self.state.transfer_requested = True
        self.state.transfer_target = phone_number
        self.state.advance_to(node_id)
        
        if self.transfer_callback:
            await self.transfer_callback(phone_number, arguments.get("reason", ""))
        
        return {
            "success": True,
            "message": pre_message,
            "action": "transfer",
            "target": phone_number,
            "current_node_id": node_id
        }
    
    async def _handle_end_call(self, function_name: str, arguments: dict) -> dict:
        """Handle ending the call."""
        node_id = function_name.replace("end_call_", "")
        node = None
        for n in self.flow_config.nodes:
            if n.id == node_id:
                node = n
                break
        
        closing_message = "Thank you for calling. Goodbye!"
        if node:
            closing_message = node.data.get("closingMessage", closing_message)
        
        closing_message = substitute_variables(closing_message, self.state.collected_slots)
        
        self.state.is_complete = True
        self.state.advance_to(node_id)
        
        if self.end_call_callback:
            await self.end_call_callback(closing_message)
        
        return {
            "success": True,
            "message": closing_message,
            "action": "end",
            "current_node_id": node_id
        }
    
    async def _handle_confirm_booking(self, arguments: dict) -> dict:
        """Handle booking confirmation."""
        confirmed = arguments.get("confirmed", False)
        
        if confirmed:
            return {
                "success": True,
                "message": "Booking confirmed. Processing your reservation.",
                "action": "confirmed",
                "booking_data": self.state.collected_slots.copy(),
                "current_node_id": self.state.current_node_id
            }
        else:
            return {
                "success": True,
                "message": "No problem. Let me know what you'd like to change.",
                "action": None,
                "current_node_id": self.state.current_node_id
            }
    
    def get_collected_data(self) -> dict:
        """Get all collected slot values."""
        return self.state.collected_slots.copy()
    
    def get_progress(self) -> dict:
        """Get flow execution progress."""
        total_required = sum(1 for v in self.flow_config.variables if v.required)
        collected = sum(1 for v in self.flow_config.variables if v.required and v.key in self.state.collected_slots)
        
        return {
            "total_slots": len(self.flow_config.variables),
            "required_slots": total_required,
            "collected_slots": len(self.state.collected_slots),
            "required_collected": collected,
            "is_complete": collected >= total_required,
            "current_node": self.state.current_node_id
        }
