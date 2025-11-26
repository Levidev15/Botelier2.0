"use client";

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { Variable, Grip } from "lucide-react";
import { SetVariableNodeData } from "../store";

interface SetVariableNodeProps {
  data: SetVariableNodeData & { isActive?: boolean };
  selected?: boolean;
}

function SetVariableNode({ data, selected }: SetVariableNodeProps) {
  const isActive = data.isActive;
  const setVariable = data.setVariable || { 
    variableKey: "", 
    valueType: "static",
    value: "" 
  };

  const getValueTypeLabel = (type: string) => {
    switch (type) {
      case "static": return "=";
      case "template": return "{{}}";
      case "expression": return "f(x)";
      default: return "=";
    }
  };

  return (
    <div
      className={`
        min-w-[200px] max-w-[280px] rounded-lg border-2 bg-[#141414] shadow-lg transition-all duration-300
        ${isActive 
          ? "border-cyan-400 ring-4 ring-cyan-400/40 scale-105" 
          : selected 
            ? "border-violet-500 ring-2 ring-violet-500/20" 
            : "border-violet-600/50"
        }
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-violet-500 !border-2 !border-violet-300"
      />

      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800 bg-violet-900/20 rounded-t-lg">
        <Grip className="h-3 w-3 text-gray-500 cursor-grab" />
        <Variable className="h-4 w-4 text-violet-400" />
        <span className="text-sm font-medium text-violet-400">Set Variable</span>
      </div>

      <div className="px-3 py-3 space-y-2">
        <div className="text-sm font-semibold text-white truncate">
          {data.name || "Set Variable"}
        </div>
        
        <div className="flex items-center gap-2 text-xs bg-gray-800/50 rounded px-2 py-1.5">
          <span className="text-violet-400 font-mono">{setVariable.variableKey || "variable"}</span>
          <span className="text-gray-500 font-mono">{getValueTypeLabel(setVariable.valueType)}</span>
          <span className="text-gray-300 truncate max-w-[100px]">
            {setVariable.value || "value"}
          </span>
        </div>

        <div className="text-xs text-gray-500">
          {setVariable.valueType === "static" && "Static value"}
          {setVariable.valueType === "template" && "Template with variables"}
          {setVariable.valueType === "expression" && "Computed expression"}
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-3 !h-3 !bg-violet-500 !border-2 !border-violet-300"
      />
    </div>
  );
}

export default memo(SetVariableNode);
