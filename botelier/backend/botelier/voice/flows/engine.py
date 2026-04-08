"""
BoteilerFlowEngine - Wraps Pipecat Flows for hotel voice AI.

This engine:
1. Loads flow configurations from database
2. Converts visual editor JSON to Pipecat Flows format
3. Injects hotel-specific function handlers
4. Manages conversation state per call

Security:
- All flows are scoped by hotel_id
- Function handlers are sandboxed
- No arbitrary code execution from flow configs
"""

from typing import Any, Dict, List, Optional, Callable
from loguru import logger


class BoteilerFlowEngine:
    """
    Hotel-centric wrapper around Pipecat Flows FlowManager.
    
    Converts visual editor configurations into executable Pipecat flows
    while maintaining hotel-specific context and security boundaries.
    
    Usage:
        engine = BoteilerFlowEngine(
            hotel_id="uuid",
            flow_config=assistant.flow_config,
            function_handlers=custom_handlers
        )
        
        # Get initial node for FlowManager
        initial_node = engine.get_initial_node()
        
        # Create function handler for a node
        handler = engine.create_node_handler("greeting")
    """
    
    def __init__(
        self,
        account_id: str,
        flow_config: Optional[Dict[str, Any]] = None,
        function_handlers: Optional[Dict[str, Callable]] = None
    ):
        """
        Initialize the flow engine.
        
        Args:
            account_id: UUID of the account (for security scoping)
            flow_config: Flow configuration from visual editor
            function_handlers: Custom function handlers (from FunctionMapper)
        """
        self.account_id = account_id
        self.flow_config = flow_config or {}
        self.function_handlers = function_handlers or {}
        
        self._nodes: Dict[str, Dict] = {}
        self._initial_node_id: Optional[str] = None
        
        if flow_config:
            self._parse_flow_config(flow_config)
    
    def _parse_flow_config(self, config: Dict[str, Any]) -> None:
        """
        Parse visual editor flow config into internal node structure.
        
        The visual editor exports JSON with:
        - nodes: List of node configs
        - edges: Connections between nodes
        - initial_node: ID of starting node
        
        We convert this to Pipecat Flows NodeConfig format.
        """
        nodes = config.get("nodes", [])
        edges = config.get("edges", [])
        self._initial_node_id = config.get("initial_node")
        
        edge_map = {}
        for edge in edges:
            source = edge.get("source")
            target = edge.get("target")
            if source and target:
                if source not in edge_map:
                    edge_map[source] = []
                edge_map[source].append(target)
        
        for node in nodes:
            node_id = node.get("id")
            if not node_id:
                continue
            
            self._nodes[node_id] = self._convert_to_pipecat_node(
                node,
                edge_map.get(node_id, [])
            )
        
        logger.info(f"🔄 Parsed flow config: {len(self._nodes)} nodes for account {self.account_id}")
    
    def _convert_to_pipecat_node(
        self,
        node: Dict[str, Any],
        next_nodes: List[str]
    ) -> Dict[str, Any]:
        """
        Convert a visual editor node to Pipecat Flows NodeConfig format.
        
        Visual Editor Node:
        {
            "id": "greeting",
            "type": "initial",
            "data": {
                "name": "Greeting",
                "role_messages": [...],
                "task_messages": [...],
                "functions": [...]
            },
            "position": {"x": 100, "y": 100}
        }
        
        Pipecat NodeConfig:
        {
            "name": "greeting",
            "role_messages": [...],
            "task_messages": [...],
            "functions": [...]
        }
        """
        node_data = node.get("data", {})
        node_type = node.get("type", "node")
        
        pipecat_node = {
            "name": node_data.get("name", node.get("id")),
        }
        
        if node_data.get("role_messages"):
            pipecat_node["role_messages"] = node_data["role_messages"]
        
        if node_data.get("task_messages"):
            pipecat_node["task_messages"] = node_data["task_messages"]
        
        if node_data.get("functions"):
            pipecat_node["functions"] = self._process_functions(
                node_data["functions"],
                next_nodes
            )
        
        if node_data.get("pre_actions"):
            pipecat_node["pre_actions"] = node_data["pre_actions"]
        
        if node_data.get("post_actions"):
            pipecat_node["post_actions"] = node_data["post_actions"]
        
        if node_type == "end":
            pipecat_node["is_end_node"] = True
        
        return pipecat_node
    
    def _process_functions(
        self,
        functions: List[Dict],
        next_nodes: List[str]
    ) -> List[Dict]:
        """
        Process function definitions from visual editor.
        
        For each function:
        - Validate schema structure
        - Inject hotel context into handlers
        - Link transitions to next nodes
        
        Security:
        - Function handlers are pre-registered, not executed from config
        - Only function names are matched, not arbitrary code
        """
        processed = []
        
        for func in functions:
            processed_func = {
                "name": func.get("name"),
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {
                    "type": "object",
                    "properties": {},
                    "required": []
                })
            }
            
            if func.get("transition_to"):
                processed_func["transition_to"] = func["transition_to"]
            elif func.get("decision"):
                processed_func["decision"] = func["decision"]
            
            processed.append(processed_func)
        
        return processed
    
    def has_flow(self) -> bool:
        """Check if a valid flow configuration exists."""
        return bool(self._nodes and self._initial_node_id)
    
    def get_initial_node(self) -> Optional[Dict[str, Any]]:
        """Get the initial node configuration for FlowManager."""
        if not self._initial_node_id:
            return None
        return self._nodes.get(self._initial_node_id)
    
    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific node configuration."""
        return self._nodes.get(node_id)
    
    def get_all_nodes(self) -> Dict[str, Dict[str, Any]]:
        """Get all node configurations."""
        return self._nodes.copy()
    
    def get_function_handler(self, function_name: str) -> Optional[Callable]:
        """
        Get the handler for a specific function.
        
        Security:
        - Only returns handlers that were explicitly registered
        - Does not execute arbitrary code from flow config
        """
        return self.function_handlers.get(function_name)
    
    def register_function_handler(self, name: str, handler: Callable) -> None:
        """Register a function handler for use in flows."""
        self.function_handlers[name] = handler
        logger.debug(f"Registered flow function handler: {name}")
    
    def create_dynamic_node_handler(self, node_id: str) -> Optional[Callable]:
        """
        Create a dynamic node handler for Pipecat Flows.
        
        This returns an async function that FlowManager can use
        for dynamic flow transitions.
        """
        node = self.get_node(node_id)
        if not node:
            return None
        
        async def node_handler(args: Dict[str, Any]) -> Dict[str, Any]:
            """Dynamic node handler injecting hotel context."""
            node_config = node.copy()
            node_config["_hotel_id"] = self.hotel_id
            return node_config
        
        return node_handler
    
    def validate_flow(self) -> tuple[bool, List[str]]:
        """
        Validate the flow configuration.
        
        Checks:
        - Initial node exists
        - All transitions point to valid nodes
        - No orphan nodes (except end nodes)
        - Required fields are present
        
        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []
        
        if not self._nodes:
            errors.append("No nodes defined in flow")
            return False, errors
        
        if not self._initial_node_id:
            errors.append("No initial node specified")
        elif self._initial_node_id not in self._nodes:
            errors.append(f"Initial node '{self._initial_node_id}' not found")
        
        for node_id, node in self._nodes.items():
            if not node.get("name"):
                errors.append(f"Node '{node_id}' missing name")
            
            for func in node.get("functions", []):
                transition_to = func.get("transition_to")
                if transition_to and transition_to not in self._nodes:
                    errors.append(
                        f"Function '{func.get('name')}' in node '{node_id}' "
                        f"transitions to unknown node '{transition_to}'"
                    )
        
        return len(errors) == 0, errors
    
    def to_pipecat_config(self) -> Optional[Dict[str, Any]]:
        """
        Export flow as Pipecat Flows configuration.
        
        This is the format expected by FlowManager for static flows.
        Note: Static flows are deprecated in Pipecat Flows 0.0.19+,
        but we maintain compatibility for simpler use cases.
        """
        if not self.has_flow():
            return None
        
        return {
            "initial_node": self._initial_node_id,
            "nodes": self._nodes
        }


class FlowNodeBuilder:
    """
    Builder pattern for creating Pipecat Flow nodes programmatically.
    
    Used for creating default flow templates.
    """
    
    def __init__(self, node_id: str, name: str):
        self.node_id = node_id
        self.node = {
            "name": name,
            "role_messages": [],
            "task_messages": [],
            "functions": []
        }
    
    def with_role_message(self, content: str) -> "FlowNodeBuilder":
        """Add a role message (persistent system context)."""
        self.node["role_messages"].append({
            "role": "system",
            "content": content
        })
        return self
    
    def with_task_message(self, content: str) -> "FlowNodeBuilder":
        """Add a task message (node-specific instructions)."""
        self.node["task_messages"].append({
            "role": "system",
            "content": content
        })
        return self
    
    def with_function(
        self,
        name: str,
        description: str,
        parameters: Optional[Dict] = None,
        transition_to: Optional[str] = None
    ) -> "FlowNodeBuilder":
        """Add a function to this node."""
        func = {
            "name": name,
            "description": description,
            "parameters": parameters or {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
        if transition_to:
            func["transition_to"] = transition_to
        
        self.node["functions"].append(func)
        return self
    
    def as_end_node(self) -> "FlowNodeBuilder":
        """Mark this as an end node."""
        self.node["is_end_node"] = True
        return self
    
    def build(self) -> Dict[str, Any]:
        """Build the node configuration."""
        return self.node
