"use client";

import { useState } from "react";
import { X, Plus, Trash2, ChevronDown, ChevronRight } from "lucide-react";
import { useFlowStore, NodeData, FlowFunction } from "./store";

export default function NodeInspector() {
  const { selectedNode, updateNodeData, deleteNode, nodes } = useFlowStore();
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    messages: true,
    functions: true,
  });

  if (!selectedNode) {
    return (
      <div className="w-80 bg-[#141414] border-l border-gray-800 p-4 text-gray-400 text-sm">
        <p>Select a node to edit its properties</p>
      </div>
    );
  }

  const data = selectedNode.data as NodeData;

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => ({ ...prev, [section]: !prev[section] }));
  };

  const handleNameChange = (value: string) => {
    updateNodeData(selectedNode.id, { name: value });
  };

  const handleTaskMessageChange = (index: number, content: string) => {
    const newMessages = [...(data.task_messages || [])];
    newMessages[index] = { role: "system", content };
    updateNodeData(selectedNode.id, { task_messages: newMessages });
  };

  const addTaskMessage = () => {
    const newMessages = [...(data.task_messages || []), { role: "system", content: "" }];
    updateNodeData(selectedNode.id, { task_messages: newMessages });
  };

  const removeTaskMessage = (index: number) => {
    const newMessages = (data.task_messages || []).filter((_, i) => i !== index);
    updateNodeData(selectedNode.id, { task_messages: newMessages });
  };

  const handleFunctionChange = (index: number, field: keyof FlowFunction, value: any) => {
    const newFunctions = [...(data.functions || [])];
    newFunctions[index] = { ...newFunctions[index], [field]: value };
    updateNodeData(selectedNode.id, { functions: newFunctions });
  };

  const addFunction = () => {
    const newFunctions = [
      ...(data.functions || []),
      {
        name: "new_function",
        description: "Description of what this function does",
        parameters: { type: "object", properties: {}, required: [] },
      },
    ];
    updateNodeData(selectedNode.id, { functions: newFunctions });
  };

  const removeFunction = (index: number) => {
    const newFunctions = (data.functions || []).filter((_, i) => i !== index);
    updateNodeData(selectedNode.id, { functions: newFunctions });
  };

  const otherNodes = nodes.filter((n) => n.id !== selectedNode.id);

  return (
    <div className="w-80 bg-[#141414] border-l border-gray-800 overflow-y-auto">
      <div className="p-4 border-b border-gray-800 flex items-center justify-between">
        <h3 className="font-semibold text-white">Node Properties</h3>
        <button
          onClick={() => deleteNode(selectedNode.id)}
          className="p-1 text-gray-400 hover:text-red-400 transition"
          title="Delete node"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      <div className="p-4 space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-400 mb-1">
            Node Name
          </label>
          <input
            type="text"
            value={data.name || ""}
            onChange={(e) => handleNameChange(e.target.value)}
            className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>

        <div>
          <button
            onClick={() => toggleSection("messages")}
            className="flex items-center gap-2 w-full text-left text-sm font-medium text-gray-300 mb-2"
          >
            {expandedSections.messages ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
            Task Messages
          </button>

          {expandedSections.messages && (
            <div className="space-y-2">
              {(data.task_messages || []).map((msg, i) => (
                <div key={i} className="relative">
                  <textarea
                    value={msg.content}
                    onChange={(e) => handleTaskMessageChange(i, e.target.value)}
                    rows={3}
                    className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none resize-none pr-8"
                    placeholder="Instructions for this step..."
                  />
                  <button
                    onClick={() => removeTaskMessage(i)}
                    className="absolute top-2 right-2 text-gray-500 hover:text-red-400"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
              <button
                onClick={addTaskMessage}
                className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
              >
                <Plus className="h-3 w-3" />
                Add Message
              </button>
            </div>
          )}
        </div>

        {selectedNode.type !== "end" && (
          <div>
            <button
              onClick={() => toggleSection("functions")}
              className="flex items-center gap-2 w-full text-left text-sm font-medium text-gray-300 mb-2"
            >
              {expandedSections.functions ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
              Functions ({data.functions?.length || 0})
            </button>

            {expandedSections.functions && (
              <div className="space-y-3">
                {(data.functions || []).map((func, i) => (
                  <div
                    key={i}
                    className="bg-[#1a1a1a] border border-gray-700 rounded-lg p-3 space-y-2"
                  >
                    <div className="flex items-center justify-between">
                      <input
                        type="text"
                        value={func.name}
                        onChange={(e) => handleFunctionChange(i, "name", e.target.value)}
                        className="flex-1 bg-transparent border-none text-white text-sm font-medium focus:outline-none"
                        placeholder="function_name"
                      />
                      <button
                        onClick={() => removeFunction(i)}
                        className="text-gray-500 hover:text-red-400"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </div>

                    <textarea
                      value={func.description}
                      onChange={(e) => handleFunctionChange(i, "description", e.target.value)}
                      rows={2}
                      className="w-full bg-[#0a0a0a] border border-gray-800 rounded px-2 py-1.5 text-gray-300 text-xs focus:border-blue-500 focus:outline-none resize-none"
                      placeholder="When should the AI call this function?"
                    />

                    <div>
                      <label className="block text-xs text-gray-500 mb-1">
                        Transition To
                      </label>
                      <select
                        value={func.transition_to || ""}
                        onChange={(e) => handleFunctionChange(i, "transition_to", e.target.value || undefined)}
                        className="w-full bg-[#0a0a0a] border border-gray-800 rounded px-2 py-1.5 text-gray-300 text-xs focus:border-blue-500 focus:outline-none"
                      >
                        <option value="">Stay on this node</option>
                        {otherNodes.map((node) => (
                          <option key={node.id} value={node.id}>
                            {(node.data as NodeData).name || node.id}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                ))}

                <button
                  onClick={addFunction}
                  className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
                >
                  <Plus className="h-3 w-3" />
                  Add Function
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
