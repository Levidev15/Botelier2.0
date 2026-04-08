"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Plus, X, Variable } from "lucide-react";
import { useFlowStore } from "../store";

export default function VariablesPanel() {
  const { variables, addVariable, deleteVariable } = useFlowStore();
  const [isExpanded, setIsExpanded] = useState(true);
  const [newVarKey, setNewVarKey] = useState("");

  const handleAddVariable = () => {
    if (newVarKey.trim()) {
      addVariable({
        key: newVarKey.trim().toLowerCase().replace(/\s+/g, "_"),
        type: "text",
        description: "",
        required: false,
      });
      setNewVarKey("");
    }
  };

  return (
    <div className="border-b border-gray-800 pb-4">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-2 w-full text-left text-sm font-medium text-gray-300 mb-2"
      >
        {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        <Variable className="h-4 w-4 text-purple-400" />
        Flow Variables ({variables.length})
      </button>

      {isExpanded && (
        <div className="space-y-2">
          {variables.map((v) => (
            <div key={v.key} className="flex items-center gap-2 bg-[#1a1a1a] rounded px-2 py-1.5">
              <span className="text-xs text-purple-400 font-mono flex-1">{`{{${v.key}}}`}</span>
              <span className="text-xs text-gray-500">{v.type}</span>
              <button
                onClick={() => deleteVariable(v.key)}
                className="text-gray-500 hover:text-red-400"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}

          <div className="flex gap-2">
            <input
              type="text"
              value={newVarKey}
              onChange={(e) => setNewVarKey(e.target.value)}
              placeholder="variable_name"
              className="flex-1 bg-[#1a1a1a] border border-gray-700 rounded px-2 py-1 text-white text-xs focus:border-purple-500 focus:outline-none font-mono"
              onKeyDown={(e) => e.key === "Enter" && handleAddVariable()}
            />
            <button
              onClick={handleAddVariable}
              className="text-xs text-purple-400 hover:text-purple-300 px-2"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
