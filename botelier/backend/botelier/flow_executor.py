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
from datetime import datetime, timezone
from typing import Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum


class NodeType(str, Enum):
    INITIAL = "initial"
    MESSAGE = "message"
    COLLECT_SLOT = "collect_slot"
    COLLECT_FORM = "collect_form"
    API_REQUEST = "api_request"
    CONDITION = "condition"
    ROUTER = "router"
    CONFIRMATION = "confirmation"
    SET_VARIABLE = "set_variable"
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
class RouterOption:
    id: str
    value: str
    label: str


@dataclass
class RouterConfig:
    variable: str
    options: list[RouterOption]


@dataclass
class ConfirmationConfig:
    summary_template: str
    confirm_prompt: str
    edit_prompt: Optional[str] = None
    variables_to_confirm: list[str] = field(default_factory=list)
    allow_edit: bool = True


@dataclass
class SetVariableConfig:
    variable_key: str
    value_type: str
    value: str


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
    global_prompt: Optional[str] = None


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
        variables=variables,
        global_prompt=config_dict.get("global_prompt") or config_dict.get("globalPrompt")
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
            elif node.type == NodeType.COLLECT_FORM:
                slots = node.data.get("slots", [])
                sorted_slots = sorted(slots, key=lambda s: s.get("order", 0))
                for slot in sorted_slots:
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
        
        global_prompt = self.flow_config.global_prompt or ""
        
        flow_context = self._generate_flow_context()
        
        now = datetime.now(timezone.utc)
        current_date = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M")
        current_date_human = now.strftime("%B %d, %Y")
        
        global_section = ""
        if global_prompt.strip():
            global_section = f"""
FLOW-LEVEL INSTRUCTIONS (apply to entire conversation):
{global_prompt.strip()}
"""
        
        return f"""{base_prompt}

Current date/time: {current_date} {current_time} UTC ({current_date_human})
{global_section}
You are executing a structured conversation flow. Follow these guidelines:
1. Collect information in the order specified by the flow
2. Use the provided functions to progress through the flow
3. Follow the CURRENT NODE instructions - they tell you what to say or ask
4. When instructions say "Say exactly", speak that text verbatim. When they say "Guidance" or "naturally", you may phrase it in your own words while keeping the meaning.
5. If the guest provides information proactively, acknowledge and record it
6. When a guest provides a date without a year (e.g., "Dec 12th"), interpret it as the next occurrence after today ({current_date}). Never assume a past year.
7. For number fields, respect the minimum and maximum limits specified.
8. IMPORTANT: Never use markdown formatting (no asterisks, bold, bullets, etc). This is a voice conversation - speak naturally without any special formatting.
9. When a function returns a "speak_exactly" field, speak that text verbatim without paraphrasing.

{flow_context}"""
    
    def _generate_flow_context(self) -> str:
        """Generate context about what information needs to be collected and current node instructions."""
        context_parts = []
        
        current_node_context = self._get_current_node_context()
        if current_node_context:
            context_parts.append(current_node_context)
        
        ordered_vars = self.get_variables_in_flow_order()
        slots_to_collect = []
        
        for var in ordered_vars:
            if var.key not in self.state.collected_slots:
                node_instructions = self._get_instructions_for_variable(var.key)
                validation = self._get_validation_for_variable(var.key)
                
                slot_info = f"- {var.key}: {var.description} ({var.type.value})"
                constraints = []
                
                if validation:
                    if "min" in validation:
                        constraints.append(f"minimum: {validation['min']}")
                    if "max" in validation:
                        constraints.append(f"maximum: {validation['max']}")
                    
                    after_date_var = validation.get("afterDateVariable") or validation.get("after_date_variable")
                    if after_date_var:
                        after_date_str = self.state.get_variable(after_date_var)
                        if after_date_str:
                            constraints.append(f"must be after {after_date_str}")
                
                if var.type == SlotType.DATE and not any("after" in c for c in constraints):
                    constraints.append("must be today or later")
                
                if constraints:
                    slot_info += f" [{', '.join(constraints)}]"
                
                if node_instructions:
                    node_instructions_resolved = substitute_variables(node_instructions, self.state.collected_slots)
                    slot_info += f"\n  Instructions: {node_instructions_resolved}"
                slots_to_collect.append(slot_info)
        
        if slots_to_collect:
            context_parts.append(f"""Information to collect (in order):
{chr(10).join(slots_to_collect)}""")
        else:
            context_parts.append("All required information has been collected.")
        
        return "\n\n".join(context_parts)
    
    def _get_node_delivery_mode(self, node: FlowNode) -> str:
        """Get the delivery mode for a node (guided or static). Default is guided."""
        if node.type == NodeType.MESSAGE:
            return node.data.get("deliveryMode", "guided")
        elif node.type == NodeType.CONFIRMATION:
            confirmation_data = node.data.get("confirmation", {})
            return confirmation_data.get("deliveryMode", "guided")
        return "guided"
    
    def _get_current_node_context(self) -> Optional[str]:
        """Get context about the current node including any configured messages.
        
        In 'guided' mode: Provides guidance that AI can follow naturally
        In 'static' mode: Provides exact text that must be spoken verbatim
        """
        current_node = self.state.get_current_node()
        if not current_node:
            return None
        
        context_lines = []
        delivery_mode = self._get_node_delivery_mode(current_node)
        is_static = delivery_mode == "static"
        
        if current_node.type == NodeType.MESSAGE:
            message = current_node.data.get("message", "")
            if message:
                resolved = substitute_variables(message, self.state.collected_slots)
                if is_static:
                    context_lines.append(f"CURRENT NODE: Say exactly: \"{resolved}\"")
                else:
                    context_lines.append(f"CURRENT NODE: Guidance - Convey this message naturally: \"{resolved}\"")
        
        elif current_node.type == NodeType.COLLECT_SLOT:
            slot = current_node.data.get("slot", {})
            prompt = slot.get("prompt", "")
            if prompt:
                resolved = substitute_variables(prompt, self.state.collected_slots)
                context_lines.append(f"CURRENT NODE: Ask the guest (you may phrase naturally): \"{resolved}\"")
        
        elif current_node.type == NodeType.COLLECT_FORM:
            intro = current_node.data.get("introMessage", "")
            if intro:
                resolved = substitute_variables(intro, self.state.collected_slots)
                context_lines.append(f"CURRENT NODE: Say introduction: \"{resolved}\"")
            slots = current_node.data.get("slots", [])
            sorted_slots = sorted(slots, key=lambda s: s.get("order", 0))
            uncollected = [s for s in sorted_slots if s.get("variableKey") not in self.state.collected_slots]
            if uncollected:
                first_slot = uncollected[0]
                prompt = first_slot.get("prompt", "")
                if prompt:
                    resolved = substitute_variables(prompt, self.state.collected_slots)
                    context_lines.append(f"Then ask for {first_slot.get('variableKey')}: \"{resolved}\"")
        
        elif current_node.type == NodeType.CONFIRMATION:
            confirmation_data = current_node.data.get("confirmation", {})
            summary_template = confirmation_data.get("summaryTemplate", confirmation_data.get("summary_template", ""))
            confirm_prompt = confirmation_data.get("confirmPrompt", confirmation_data.get("confirm_prompt", ""))
            
            if summary_template:
                resolved_summary = substitute_variables(summary_template, self.state.collected_slots)
                if is_static:
                    context_lines.append(f"CURRENT NODE: Say exactly the summary: \"{resolved_summary}\"")
                else:
                    context_lines.append(f"CURRENT NODE: Summarize these details naturally: \"{resolved_summary}\"")
            if confirm_prompt:
                resolved_confirm = substitute_variables(confirm_prompt, self.state.collected_slots)
                if is_static:
                    context_lines.append(f"Then ask for confirmation: \"{resolved_confirm}\"")
                else:
                    context_lines.append(f"Then ask if this is correct (naturally): \"{resolved_confirm}\"")
        
        elif current_node.type == NodeType.END:
            closing = current_node.data.get("closingMessage", "")
            if closing:
                resolved = substitute_variables(closing, self.state.collected_slots)
                context_lines.append(f"CURRENT NODE: Say goodbye: \"{resolved}\"")
        
        elif current_node.type == NodeType.TRANSFER:
            transfer = current_node.data.get("transfer", {})
            pre_message = transfer.get("preTransferMessage", "")
            if pre_message:
                resolved = substitute_variables(pre_message, self.state.collected_slots)
                context_lines.append(f"CURRENT NODE: Before transfer, say: \"{resolved}\"")
        
        return "\n".join(context_lines) if context_lines else None
    
    def _get_validation_for_variable(self, var_key: str) -> Optional[dict]:
        """Get the validation config for the node that collects a specific variable."""
        for node in self.flow_config.nodes:
            if node.type == NodeType.COLLECT_SLOT:
                slot = node.data.get("slot", {})
                if slot.get("variableKey") == var_key:
                    return slot.get("validation")
            elif node.type == NodeType.COLLECT_FORM:
                slots = node.data.get("slots", [])
                for slot in slots:
                    if slot.get("variableKey") == var_key:
                        return slot.get("validation")
        return None
    
    def _get_instructions_for_variable(self, var_key: str) -> Optional[str]:
        """Get the instructions for the node that collects a specific variable."""
        for node in self.flow_config.nodes:
            if node.type == NodeType.COLLECT_SLOT:
                slot = node.data.get("slot", {})
                if slot.get("variableKey") == var_key:
                    return node.data.get("instructions")
            elif node.type == NodeType.COLLECT_FORM:
                slots = node.data.get("slots", [])
                for slot in slots:
                    if slot.get("variableKey") == var_key:
                        return node.data.get("instructions")
        return None
    
    def _find_next_reachable_collect_slot(self) -> tuple:
        """
        Find the next COLLECT_SLOT or COLLECT_FORM node reachable from the current position.
        Traverses edges from current node without skipping collect nodes.
        
        Returns: (node, variable_key) or (None, None) if no collect node reachable
        """
        current_node = self.state.get_current_node()
        if not current_node:
            return (None, None)
        
        if current_node.type == NodeType.COLLECT_SLOT:
            slot = current_node.data.get("slot", {})
            return (current_node, slot.get("variableKey"))
        
        if current_node.type == NodeType.COLLECT_FORM:
            slots = current_node.data.get("slots", [])
            sorted_slots = sorted(slots, key=lambda s: s.get("order", 0))
            for slot in sorted_slots:
                var_key = slot.get("variableKey")
                if var_key and var_key not in self.state.collected_slots:
                    return (current_node, var_key)
        
        visited = set()
        queue = [current_node.id]
        
        while queue:
            node_id = queue.pop(0)
            if node_id in visited:
                continue
            visited.add(node_id)
            
            node = None
            for n in self.flow_config.nodes:
                if n.id == node_id:
                    node = n
                    break
            
            if not node:
                continue
            
            if node.type == NodeType.COLLECT_SLOT:
                slot = node.data.get("slot", {})
                var_key = slot.get("variableKey")
                if var_key and var_key not in self.state.collected_slots:
                    return (node, var_key)
            
            if node.type == NodeType.COLLECT_FORM:
                slots = node.data.get("slots", [])
                sorted_slots = sorted(slots, key=lambda s: s.get("order", 0))
                for slot in sorted_slots:
                    var_key = slot.get("variableKey")
                    if var_key and var_key not in self.state.collected_slots:
                        return (node, var_key)
            
            for edge in self.flow_config.edges:
                if edge.source == node_id and edge.target not in visited:
                    queue.append(edge.target)
        
        return (None, None)
    
    def _get_next_slot_instructions(self) -> Optional[dict]:
        """Get instructions for the next slot to collect, with dynamic constraints based on collected values."""
        current_node = self.state.get_current_node()
        if not current_node:
            return None
        
        slot = None
        var_key = None
        
        if current_node.type == NodeType.COLLECT_SLOT:
            slot = current_node.data.get("slot", {})
            var_key = slot.get("variableKey")
        elif current_node.type == NodeType.COLLECT_FORM:
            slots = current_node.data.get("slots", [])
            sorted_slots = sorted(slots, key=lambda s: s.get("order", 0))
            for s in sorted_slots:
                v_key = s.get("variableKey")
                if v_key and v_key not in self.state.collected_slots:
                    slot = s
                    var_key = v_key
                    break
        
        if not slot or not var_key:
            return None
        
        if var_key in self.state.collected_slots:
            return None
        
        var_info = None
        for var in self.flow_config.variables:
            if var.key == var_key:
                var_info = var
                break
        
        if not var_info:
            return None
        
        validation = slot.get("validation") or {}
        constraints = []
        
        now = datetime.now(timezone.utc)
        current_date = now.strftime("%Y-%m-%d")
        
        if var_info.type == SlotType.NUMBER:
            if "min" in validation:
                constraints.append(f"minimum: {validation['min']}")
            if "max" in validation:
                constraints.append(f"maximum: {validation['max']}")
        
        elif var_info.type == SlotType.DATE:
            after_date_var = None
            if validation:
                after_date_var = validation.get("afterDateVariable") or validation.get("after_date_variable")
            if after_date_var:
                after_date_str = self.state.get_variable(after_date_var)
                if after_date_str:
                    constraints.append(f"must be after {after_date_str}")
                else:
                    constraints.append("must be today or later")
            else:
                constraints.append("must be today or later")
        
        instructions = current_node.data.get("instructions")
        if instructions:
            instructions = substitute_variables(instructions, self.state.collected_slots)
        
        return {
            "variable": var_key,
            "type": var_info.type.value,
            "description": var_info.description,
            "constraints": constraints if constraints else None,
            "instructions": instructions
        }
    
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
            
            if current_node.type in [NodeType.COLLECT_SLOT, NodeType.COLLECT_FORM, NodeType.END, NodeType.TRANSFER]:
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
        elif node.type == NodeType.COLLECT_FORM:
            intro = node.data.get("introMessage", "")
            if intro:
                return substitute_variables(intro, self.state.collected_slots)
            slots = node.data.get("slots", [])
            sorted_slots = sorted(slots, key=lambda s: s.get("order", 0))
            if sorted_slots:
                return sorted_slots[0].get("prompt", "")
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
        1. Collecting slot variables - ONLY for the current/next collect node (enforces flow order)
        2. API requests
        3. Transfer calls
        4. Ending the call
        
        For collect_slot nodes: Only exposes the single slot function for that node
        For collect_form nodes: Exposes all slots in the form for flexible collection
        """
        functions = []
        
        # Only expose slot functions for the current collect node (strict flow order)
        current_node = self.state.get_current_node()
        
        # Determine which slot functions to expose based on current node type
        slots_to_expose = set()
        
        if current_node and current_node.type == NodeType.COLLECT_SLOT:
            # For collect_slot: only expose this single slot
            slot = current_node.data.get("slot", {})
            var_key = slot.get("variableKey")
            if var_key and var_key not in self.state.collected_slots:
                slots_to_expose.add(var_key)
        elif current_node and current_node.type == NodeType.COLLECT_FORM:
            # For collect_form: expose all uncollected slots in the form (flexible within form)
            form_slots = current_node.data.get("slots", [])
            for slot in form_slots:
                var_key = slot.get("variableKey")
                if var_key and var_key not in self.state.collected_slots:
                    slots_to_expose.add(var_key)
        else:
            # Not on a collect node - find next reachable collect node
            next_collect_node, next_var_key = self._find_next_reachable_collect_slot()
            if next_collect_node:
                if next_collect_node.type == NodeType.COLLECT_SLOT:
                    if next_var_key and next_var_key not in self.state.collected_slots:
                        slots_to_expose.add(next_var_key)
                elif next_collect_node.type == NodeType.COLLECT_FORM:
                    # Expose all form slots
                    form_slots = next_collect_node.data.get("slots", [])
                    for slot in form_slots:
                        var_key = slot.get("variableKey")
                        if var_key and var_key not in self.state.collected_slots:
                            slots_to_expose.add(var_key)
        
        # Create function schemas only for slots we should expose
        for var in self.flow_config.variables:
            if var.key in slots_to_expose:
                func_schema = self._create_slot_function(var)
                functions.append(func_schema)
        
        for node in self.flow_config.nodes:
            if node.type == NodeType.API_REQUEST:
                func_schema = self._create_api_function(node)
                functions.append(func_schema)
            elif node.type == NodeType.ROUTER:
                func_schema = self._create_router_function(node)
                functions.append(func_schema)
            elif node.type == NodeType.CONFIRMATION:
                func_schema = self._create_confirmation_function(node)
                functions.append(func_schema)
            elif node.type == NodeType.SET_VARIABLE:
                func_schema = self._create_set_variable_function(node)
                functions.append(func_schema)
            elif node.type == NodeType.TRANSFER:
                func_schema = self._create_transfer_function(node)
                functions.append(func_schema)
            elif node.type == NodeType.END:
                func_schema = self._create_end_function(node)
                functions.append(func_schema)
        
        has_confirmation_node = any(node.type == NodeType.CONFIRMATION for node in self.flow_config.nodes)
        if not has_confirmation_node:
            functions.append({
                "type": "function",
                "function": {
                    "name": "confirm_booking",
                    "description": "Confirm the booking details with the guest after all information is collected. Summarize all collected information in plain text (no markdown or special formatting) and ask the guest to confirm.",
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
        validation = self._get_validation_for_variable(var.key) or {}
        
        if var.type == SlotType.CHOICE and var.choices:
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
        
        if var.type == SlotType.NUMBER:
            param_schema = {
                "type": "integer",
                "description": var.description
            }
            if validation:
                if "min" in validation:
                    param_schema["minimum"] = validation["min"]
                if "max" in validation:
                    param_schema["maximum"] = validation["max"]
            return {
                "type": "function",
                "function": {
                    "name": f"collect_{var.key}",
                    "description": f"Record the {var.description}",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            var.key: param_schema
                        },
                        "required": [var.key]
                    }
                }
            }
        
        if var.type == SlotType.DATE:
            now = datetime.now(timezone.utc)
            current_date = now.strftime("%Y-%m-%d")
            
            after_date_var = None
            if validation:
                after_date_var = validation.get("afterDateVariable") or validation.get("after_date_variable")
            after_date_str = None
            if after_date_var and hasattr(self, 'state'):
                after_date_str = self.state.get_variable(after_date_var)
            
            if after_date_str:
                date_constraint = f"must be after {after_date_str}"
            else:
                date_constraint = f"must be today ({current_date}) or later"
            
            return {
                "type": "function",
                "function": {
                    "name": f"collect_{var.key}",
                    "description": f"Record the {var.description}. Constraint: {date_constraint}. Accept any reasonable date format the caller provides and convert to YYYY-MM-DD internally.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            var.key: {
                                "type": "string",
                                "description": f"{var.description} ({date_constraint})"
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
                            "type": "string",
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
    
    def _create_router_function(self, node: FlowNode) -> dict:
        """Create a function schema for a router node."""
        router_data = node.data.get("router", {})
        variable = router_data.get("variable", "choice")
        options = router_data.get("options", [])
        
        option_values = [opt.get("value", "") for opt in options if opt.get("value")]
        option_labels = [opt.get("label", opt.get("value", "")) for opt in options]
        
        description = f"Route the conversation based on {variable}. "
        if option_labels:
            description += f"Options: {', '.join(option_labels)}"
        
        return {
            "type": "function",
            "function": {
                "name": f"route_{node.id}",
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "choice": {
                            "type": "string",
                            "enum": option_values if option_values else ["default"],
                            "description": f"The selected option for {variable}"
                        }
                    },
                    "required": ["choice"]
                }
            }
        }
    
    def _create_confirmation_function(self, node: FlowNode) -> dict:
        """Create a function schema for a confirmation node."""
        confirmation_data = node.data.get("confirmation", {})
        summary_template = confirmation_data.get("summaryTemplate", confirmation_data.get("summary_template", ""))
        confirm_prompt = confirmation_data.get("confirmPrompt", confirmation_data.get("confirm_prompt", ""))
        variables_to_confirm = confirmation_data.get("variablesToConfirm", confirmation_data.get("variables_to_confirm", []))
        
        var_list = ", ".join(variables_to_confirm) if variables_to_confirm else "collected details"
        
        resolved_summary = substitute_variables(summary_template, self.state.collected_slots) if summary_template else ""
        resolved_confirm = substitute_variables(confirm_prompt, self.state.collected_slots) if confirm_prompt else ""
        
        description = f"Confirm or edit {var_list}. "
        if resolved_summary:
            description += f"First say exactly: \"{resolved_summary}\" "
        if resolved_confirm:
            description += f"Then ask: \"{resolved_confirm}\""
        else:
            description += "Then ask if this is correct."
        
        return {
            "type": "function",
            "function": {
                "name": f"confirm_{node.id}",
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "confirmed": {
                            "type": "boolean",
                            "description": "True if the guest confirms the details are correct, False if they want to make changes"
                        }
                    },
                    "required": ["confirmed"]
                }
            }
        }
    
    def _create_set_variable_function(self, node: FlowNode) -> dict:
        """Create a function schema for a set variable node."""
        set_var_data = node.data.get("setVariable", node.data.get("set_variable", {}))
        var_key = set_var_data.get("variableKey", set_var_data.get("variable_key", "variable"))
        
        return {
            "type": "function",
            "function": {
                "name": f"set_var_{node.id}",
                "description": f"Set the value of {var_key}",
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
        elif function_name.startswith("route_"):
            return await self._handle_router(function_name, arguments)
        elif function_name == "confirm_booking":
            return await self._handle_confirm_booking(arguments)
        elif function_name.startswith("confirm_"):
            return await self._handle_confirmation(function_name, arguments)
        elif function_name.startswith("set_var_"):
            return await self._handle_set_variable(function_name, arguments)
        elif function_name.startswith("transfer_"):
            return await self._handle_transfer(function_name, arguments)
        elif function_name.startswith("end_call_"):
            return await self._handle_end_call(function_name, arguments)
        else:
            return {"success": False, "message": "Unknown function", "action": None}
    
    async def _handle_slot_collection(self, function_name: str, arguments: dict) -> dict:
        """Handle collecting a slot value."""
        var_key = function_name.replace("collect_", "")
        
        if var_key in arguments:
            value = arguments[var_key]
            
            var_info = None
            for var in self.flow_config.variables:
                if var.key == var_key:
                    var_info = var
                    break
            
            collecting_node_id = None
            slot_config = None
            
            current_node = self.state.get_current_node()
            if current_node and current_node.type == NodeType.COLLECT_SLOT:
                slot = current_node.data.get("slot", {})
                if slot.get("variableKey") == var_key:
                    collecting_node_id = current_node.id
                    slot_config = slot
            elif current_node and current_node.type == NodeType.COLLECT_FORM:
                slots = current_node.data.get("slots", [])
                for slot in slots:
                    if slot.get("variableKey") == var_key:
                        collecting_node_id = current_node.id
                        slot_config = slot
                        break
            
            if not collecting_node_id:
                next_collect_node, next_collect_var = self._find_next_reachable_collect_slot()
                
                if next_collect_node and next_collect_var != var_key:
                    expected_info = None
                    for v in self.flow_config.variables:
                        if v.key == next_collect_var:
                            expected_info = v
                            break
                    expected_desc = expected_info.description if expected_info else next_collect_var
                    return {
                        "success": False,
                        "message": f"Please collect {expected_desc} first before moving to {var_info.description if var_info else var_key}.",
                        "action": None,
                        "out_of_order": True,
                        "expected_variable": next_collect_var,
                        "current_node_id": self.state.current_node_id
                    }
                
                if next_collect_node and next_collect_var == var_key:
                    if next_collect_node.type == NodeType.COLLECT_SLOT:
                        slot = next_collect_node.data.get("slot", {})
                        slot_config = slot
                    elif next_collect_node.type == NodeType.COLLECT_FORM:
                        slots = next_collect_node.data.get("slots", [])
                        for slot in slots:
                            if slot.get("variableKey") == var_key:
                                slot_config = slot
                                break
                    collecting_node_id = next_collect_node.id
                    self.state.advance_to(next_collect_node.id)
            
            validation_error = self._validate_slot_value(var_info, slot_config, value)
            if validation_error:
                retry_prompt_template = slot_config.get("retryPrompt", "") if slot_config else ""
                if retry_prompt_template:
                    retry_prompt = substitute_variables(retry_prompt_template, self.state.collected_slots)
                else:
                    retry_prompt = "Please try again."
                return {
                    "success": False,
                    "message": f"{validation_error} {retry_prompt}",
                    "action": None,
                    "validation_error": validation_error,
                    "current_node_id": collecting_node_id or self.state.current_node_id
                }
            
            self.state.set_variable(var_key, value)
            
            next_node = None
            next_node_id = None
            form_next_slot_prompt = None
            if collecting_node_id:
                collecting_node = None
                for n in self.flow_config.nodes:
                    if n.id == collecting_node_id:
                        collecting_node = n
                        break
                
                if collecting_node and collecting_node.type == NodeType.COLLECT_FORM:
                    slots = collecting_node.data.get("slots", [])
                    sorted_slots = sorted(slots, key=lambda s: s.get("order", 0))
                    remaining = [s for s in sorted_slots if s.get("variableKey") not in self.state.collected_slots]
                    if remaining:
                        next_node_id = collecting_node_id
                        prompt = remaining[0].get("prompt", "")
                        if prompt:
                            form_next_slot_prompt = substitute_variables(prompt, self.state.collected_slots)
                    else:
                        next_node = self.state.get_next_node(collecting_node_id)
                        if next_node:
                            next_node_id = next_node.id
                            self.state.advance_to(next_node.id)
                else:
                    next_node = self.state.get_next_node(collecting_node_id)
                    if next_node:
                        next_node_id = next_node.id
                        self.state.advance_to(next_node.id)
            
            next_slot_instructions = self._get_next_slot_instructions()
            
            next_node_message, is_static = self._get_next_node_configured_message(next_node) if next_node else (None, False)
            
            result = {
                "success": True,
                "action": None,
                "collected": {var_key: value},
                "current_node_id": next_node_id or collecting_node_id or self.state.current_node_id,
                "next_slot": next_slot_instructions
            }
            
            if next_node_message:
                result["message"] = next_node_message
                if is_static:
                    result["speak_exactly"] = next_node_message
            elif form_next_slot_prompt:
                result["message"] = f"Got it. {form_next_slot_prompt}"
            else:
                result["message"] = "Got it."
            
            return result
        
        return {
            "success": False,
            "message": f"Missing value for {var_key}",
            "action": None,
            "current_node_id": self.state.current_node_id
        }
    
    def _validate_slot_value(self, var_info: Optional[FlowVariable], slot_config: Optional[dict], value: Any) -> Optional[str]:
        """Validate a slot value. Returns error message or None if valid."""
        if not var_info:
            return None
        
        validation = (slot_config.get("validation") or {}) if slot_config else {}
        
        if var_info.type == SlotType.NUMBER:
            try:
                num_value = int(value) if isinstance(value, str) else value
                if "min" in validation and num_value < validation["min"]:
                    return f"Value must be at least {validation['min']}."
                if "max" in validation and num_value > validation["max"]:
                    return f"Value cannot exceed {validation['max']}."
            except (ValueError, TypeError):
                return "Please provide a valid number."
        
        elif var_info.type == SlotType.DATE:
            if isinstance(value, str):
                try:
                    date_value = datetime.strptime(value, "%Y-%m-%d").date()
                    today = datetime.now(timezone.utc).date()
                    if date_value < today:
                        return f"Date must be today or in the future (on or after {today})."
                    
                    after_date_var = validation.get("afterDateVariable") or validation.get("after_date_variable")
                    if after_date_var:
                        after_date_str = self.state.get_variable(after_date_var)
                        if after_date_str:
                            try:
                                after_date = datetime.strptime(after_date_str, "%Y-%m-%d").date()
                                if date_value <= after_date:
                                    return f"Date must be after {after_date_str}."
                            except ValueError:
                                pass
                except ValueError:
                    return "I didn't quite catch that date. Could you please tell me the date again?"
        
        return None
    
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
                    
                    next_node = self.state.get_next_node(node_id)
                    if next_node:
                        self.state.advance_to(next_node.id)
                        next_node_id = next_node.id
                    else:
                        self.state.advance_to(node_id)
                        next_node_id = node_id
                    
                    return {
                        "success": True,
                        "message": api_config.get("onSuccess", "API request completed successfully"),
                        "action": None,
                        "response": response_data,
                        "current_node_id": next_node_id
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
    
    async def _handle_router(self, function_name: str, arguments: dict) -> dict:
        """Handle routing based on a choice value."""
        node_id = function_name.replace("route_", "")
        node = None
        for n in self.flow_config.nodes:
            if n.id == node_id:
                node = n
                break
        
        if not node:
            return {"success": False, "message": "Router node not found", "action": None, "current_node_id": None}
        
        router_data = node.data.get("router", {})
        variable = router_data.get("variable", "")
        options = router_data.get("options", [])
        choice = arguments.get("choice", "")
        
        if variable:
            self.state.set_variable(variable, choice)
        
        matched_option_id = None
        matched_label = choice
        for opt in options:
            if opt.get("value", "").lower() == choice.lower():
                matched_option_id = opt.get("id")
                matched_label = opt.get("label", choice)
                break
        
        next_node_id = None
        if matched_option_id:
            next_node = self.state.get_next_node(node_id, handle=matched_option_id)
            if next_node:
                next_node_id = next_node.id
                self.state.advance_to(next_node.id)
        
        if not next_node_id:
            next_node = self.state.get_next_node(node_id, handle="default")
            if next_node:
                next_node_id = next_node.id
                self.state.advance_to(next_node.id)
        
        if not next_node_id:
            next_node = self.state.get_next_node(node_id)
            if next_node:
                next_node_id = next_node.id
                self.state.advance_to(next_node.id)
            else:
                self.state.advance_to(node_id)
                next_node_id = node_id
        
        return {
            "success": True,
            "message": f"Routing to: {matched_label}",
            "action": None,
            "routed_to": matched_label,
            "current_node_id": next_node_id
        }
    
    async def _handle_confirmation(self, function_name: str, arguments: dict) -> dict:
        """Handle a confirmation node - guest confirms or requests edit."""
        node_id = function_name.replace("confirm_", "")
        node = None
        for n in self.flow_config.nodes:
            if n.id == node_id:
                node = n
                break
        
        if not node:
            return {"success": False, "message": "Confirmation node not found", "action": None, "current_node_id": None}
        
        confirmed = arguments.get("confirmed", True)
        confirmation_data = node.data.get("confirmation", {})
        
        summary_template = confirmation_data.get("summaryTemplate", confirmation_data.get("summary_template", ""))
        confirm_prompt = confirmation_data.get("confirmPrompt", confirmation_data.get("confirm_prompt", ""))
        edit_prompt = confirmation_data.get("editPrompt", confirmation_data.get("edit_prompt", ""))
        
        summary_message = substitute_variables(summary_template, self.state.collected_slots) if summary_template else ""
        confirm_message = substitute_variables(confirm_prompt, self.state.collected_slots) if confirm_prompt else ""
        edit_message = substitute_variables(edit_prompt, self.state.collected_slots) if edit_prompt else "What would you like to change?"
        
        delivery_mode = confirmation_data.get("deliveryMode", "guided")
        is_static = delivery_mode == "static"
        
        if confirmed:
            next_node = self.state.get_next_node(node_id, handle="confirmed")
            next_node_id = next_node.id if next_node else node_id
            if next_node:
                self.state.advance_to(next_node.id)
            
            next_node_message, next_is_static = self._get_next_node_configured_message(next_node) if next_node else (None, False)
            
            result = {
                "success": True,
                "action": None,
                "confirmed": True,
                "current_node_id": next_node_id
            }
            
            if next_node_message:
                result["message"] = next_node_message
                if next_is_static:
                    result["speak_exactly"] = next_node_message
            elif summary_message:
                confirmed_text = f"Thank you for confirming. {summary_message}"
                result["message"] = confirmed_text
                if is_static:
                    result["speak_exactly"] = confirmed_text
            else:
                result["message"] = "Thank you for confirming."
            
            return result
        else:
            next_node = self.state.get_next_node(node_id, handle="edit")
            next_node_id = next_node.id if next_node else node_id
            if next_node:
                self.state.advance_to(next_node.id)
            
            result = {
                "success": True,
                "action": None,
                "confirmed": False,
                "current_node_id": next_node_id,
                "message": edit_message
            }
            
            return result
    
    def _get_next_node_configured_message(self, node: Optional[FlowNode]) -> tuple[Optional[str], bool]:
        """Get the configured message from a node and whether to speak it exactly.
        
        Returns: (message, is_static) tuple
        - message: The resolved message text, or None if no message
        - is_static: True if the node is in static delivery mode (speak exactly)
        """
        if not node:
            return (None, False)
        
        delivery_mode = self._get_node_delivery_mode(node)
        is_static = delivery_mode == "static"
        
        if node.type == NodeType.MESSAGE:
            message = node.data.get("message", "")
            resolved = substitute_variables(message, self.state.collected_slots) if message else None
            return (resolved, is_static)
        elif node.type == NodeType.COLLECT_SLOT:
            slot = node.data.get("slot", {})
            prompt = slot.get("prompt", "")
            resolved = substitute_variables(prompt, self.state.collected_slots) if prompt else None
            return (resolved, False)
        elif node.type == NodeType.COLLECT_FORM:
            intro = node.data.get("introMessage", "")
            if intro:
                resolved = substitute_variables(intro, self.state.collected_slots)
                return (resolved, False)
            slots = node.data.get("slots", [])
            sorted_slots = sorted(slots, key=lambda s: s.get("order", 0))
            uncollected = [s for s in sorted_slots if s.get("variableKey") not in self.state.collected_slots]
            if uncollected:
                prompt = uncollected[0].get("prompt", "")
                resolved = substitute_variables(prompt, self.state.collected_slots) if prompt else None
                return (resolved, False)
            return (None, False)
        elif node.type == NodeType.CONFIRMATION:
            confirmation_data = node.data.get("confirmation", {})
            summary_template = confirmation_data.get("summaryTemplate", confirmation_data.get("summary_template", ""))
            confirm_prompt = confirmation_data.get("confirmPrompt", confirmation_data.get("confirm_prompt", ""))
            parts = []
            if summary_template:
                parts.append(substitute_variables(summary_template, self.state.collected_slots))
            if confirm_prompt:
                parts.append(substitute_variables(confirm_prompt, self.state.collected_slots))
            resolved = " ".join(parts) if parts else None
            return (resolved, is_static)
        elif node.type == NodeType.END:
            message = node.data.get("closingMessage", "")
            resolved = substitute_variables(message, self.state.collected_slots) if message else None
            return (resolved, False)
        elif node.type == NodeType.TRANSFER:
            transfer = node.data.get("transfer", {})
            message = transfer.get("preTransferMessage", "")
            resolved = substitute_variables(message, self.state.collected_slots) if message else None
            return (resolved, False)
        elif node.type == NodeType.API_REQUEST:
            api_config = node.data.get("api", {})
            return (api_config.get("onSuccess", None), False)
        
        return (None, False)
    
    async def _handle_set_variable(self, function_name: str, arguments: dict) -> dict:
        """Handle setting a variable value."""
        node_id = function_name.replace("set_var_", "")
        node = None
        for n in self.flow_config.nodes:
            if n.id == node_id:
                node = n
                break
        
        if not node:
            return {"success": False, "message": "Set variable node not found", "action": None, "current_node_id": None}
        
        set_var_data = node.data.get("setVariable", node.data.get("set_variable", {}))
        var_key = set_var_data.get("variableKey", set_var_data.get("variable_key", ""))
        value_type = set_var_data.get("valueType", set_var_data.get("value_type", "static"))
        value = set_var_data.get("value", "")
        
        if value_type == "template":
            final_value = substitute_variables(value, self.state.collected_slots)
        elif value_type == "expression":
            try:
                final_value = eval(value, {"__builtins__": {}}, self.state.collected_slots)
            except:
                final_value = value
        else:
            final_value = value
        
        if var_key:
            self.state.set_variable(var_key, final_value)
        
        next_node = self.state.get_next_node(node_id)
        next_node_id = next_node.id if next_node else node_id
        if next_node:
            self.state.advance_to(next_node.id)
        
        return {
            "success": True,
            "message": f"Set {var_key} to {final_value}",
            "action": None,
            "set_variable": {var_key: final_value},
            "current_node_id": next_node_id
        }
    
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
        """Handle booking confirmation - tries to find a CONFIRMATION node in the flow."""
        confirmed = arguments.get("confirmed", False)
        
        confirmation_node = None
        for node in self.flow_config.nodes:
            if node.type == NodeType.CONFIRMATION:
                confirmation_node = node
                break
        
        if confirmation_node:
            confirmation_data = confirmation_node.data.get("confirmation", {})
            edit_prompt = confirmation_data.get("editPrompt", confirmation_data.get("edit_prompt", ""))
            edit_message = substitute_variables(edit_prompt, self.state.collected_slots) if edit_prompt else "What would you like to change?"
            
            delivery_mode = confirmation_data.get("deliveryMode", "guided")
            is_static = delivery_mode == "static"
            
            if confirmed:
                next_node = self.state.get_next_node(confirmation_node.id, handle="confirmed")
                next_node_id = next_node.id if next_node else confirmation_node.id
                if next_node:
                    self.state.advance_to(next_node.id)
                
                next_node_message, next_is_static = self._get_next_node_configured_message(next_node) if next_node else (None, False)
                
                summary_template = confirmation_data.get("summaryTemplate", confirmation_data.get("summary_template", ""))
                summary_message = substitute_variables(summary_template, self.state.collected_slots) if summary_template else ""
                
                result = {
                    "success": True,
                    "action": "confirmed",
                    "booking_data": self.state.collected_slots.copy(),
                    "current_node_id": next_node_id
                }
                
                if next_node_message:
                    result["message"] = next_node_message
                    if next_is_static:
                        result["speak_exactly"] = next_node_message
                elif summary_message:
                    confirmed_text = f"Thank you for confirming. {summary_message}"
                    result["message"] = confirmed_text
                    if is_static:
                        result["speak_exactly"] = confirmed_text
                else:
                    result["message"] = "Thank you for confirming."
                
                return result
            else:
                next_node = self.state.get_next_node(confirmation_node.id, handle="edit")
                next_node_id = next_node.id if next_node else confirmation_node.id
                if next_node:
                    self.state.advance_to(next_node.id)
                
                result = {
                    "success": True,
                    "action": None,
                    "confirmed": False,
                    "current_node_id": next_node_id,
                    "message": edit_message
                }
                
                return result
        
        if confirmed:
            return {
                "success": True,
                "message": "Great, confirmed.",
                "action": "confirmed",
                "booking_data": self.state.collected_slots.copy(),
                "current_node_id": self.state.current_node_id
            }
        else:
            return {
                "success": True,
                "message": "What would you like to change?",
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
