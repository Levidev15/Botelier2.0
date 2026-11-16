"""Legacy flow node builder used by the public starter templates."""

from typing import Any, Dict, Optional


class FlowNodeBuilder:
    """Builder pattern for creating Pipecat Flow nodes programmatically.

    Used for creating default flow templates.
    """

    def __init__(self, node_id: str, name: str):
        self.node_id = node_id
        self.node = {"name": name, "role_messages": [], "task_messages": [], "functions": []}

    def with_role_message(self, content: str) -> "FlowNodeBuilder":
        """Add a role message (persistent system context)."""
        self.node["role_messages"].append({"role": "system", "content": content})
        return self

    def with_task_message(self, content: str) -> "FlowNodeBuilder":
        """Add a task message (node-specific instructions)."""
        self.node["task_messages"].append({"role": "system", "content": content})
        return self

    def with_function(
        self,
        name: str,
        description: str,
        parameters: Optional[Dict] = None,
        transition_to: Optional[str] = None,
    ) -> "FlowNodeBuilder":
        """Add a function to this node."""
        func = {
            "name": name,
            "description": description,
            "parameters": parameters or {"type": "object", "properties": {}, "required": []},
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
