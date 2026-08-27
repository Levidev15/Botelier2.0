"use client";

import { useState } from "react";
import { Plus, X } from "lucide-react";
import { useFlowStore } from "../store";

export default function VariablesPanel() {
  const { variables, addVariable, deleteVariable } = useFlowStore();
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
    <div className="flex flex-col h-full overflow-hidden">
      {/* Scrollable variable list */}
      <div className="flex-1 overflow-y-auto p-4 space-y-1 min-h-0">
        {variables.length === 0 && (
          <p className="text-xs text-gray-500 text-center pt-6">
            No variables declared yet.
          </p>
        )}
        {variables.map((v) => (
          <div
            key={v.key}
            className="flex items-center gap-2 bg-[#1a1a1a] rounded px-2 py-1.5 group"
          >
            <span className="text-xs text-purple-400 font-mono flex-1 truncate">
              {`{{${v.key}}}`}
            </span>
            <span className="text-xs text-gray-500 flex-shrink-0">{v.type}</span>
            <button
              onClick={() => deleteVariable(v.key)}
              className="text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
              title={`Delete ${v.key}`}
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ))}
      </div>

      {/* Pinned add-variable input */}
      <div className="p-4 border-t border-gray-800 flex-shrink-0 bg-[#141414]">
        <div className="flex gap-2">
          <input
            type="text"
            value={newVarKey}
            onChange={(e) => setNewVarKey(e.target.value)}
            placeholder="new_variable_name"
            className="flex-1 bg-[#1a1a1a] border border-gray-700 rounded px-2 py-1.5 text-white text-xs focus:border-purple-500 focus:outline-none font-mono"
            onKeyDown={(e) => e.key === "Enter" && handleAddVariable()}
          />
          <button
            onClick={handleAddVariable}
            disabled={!newVarKey.trim()}
            className="px-2 bg-[#1a1a1a] border border-gray-700 rounded text-purple-400 hover:text-purple-300 hover:border-purple-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            title="Add variable"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>
        <p className="text-xs text-gray-600 mt-1.5">
          Use <span className="font-mono text-gray-500">{"{{variable_name}}"}</span> in any text field
        </p>
      </div>
    </div>
  );
}
