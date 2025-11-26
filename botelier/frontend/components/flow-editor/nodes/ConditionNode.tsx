"use client";

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { GitBranch, Grip, Check, X } from "lucide-react";
import { ConditionNodeData } from "../store";

interface ConditionNodeProps {
  data: ConditionNodeData & { isActive?: boolean };
  selected?: boolean;
}

const operatorLabels: Record<string, string> = {
  equals: "=",
  not_equals: "≠",
  contains: "contains",
  greater_than: ">",
  less_than: "<",
  is_empty: "is empty",
  is_not_empty: "has value",
};

function ConditionNode({ data, selected }: ConditionNodeProps) {
  const isActive = data.isActive;
  const condition = data.condition;
  
  return (
    <div
      className={`
        min-w-[220px] max-w-[280px] rounded-lg border-2 bg-[#141414] shadow-lg transition-all duration-300
        ${isActive 
          ? "border-cyan-400 ring-4 ring-cyan-400/40 scale-105" 
          : selected 
            ? "border-yellow-500 ring-2 ring-yellow-500/20" 
            : "border-yellow-600/50"
        }
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-yellow-500 !border-2 !border-yellow-300"
      />

      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800 bg-yellow-900/20 rounded-t-lg">
        <Grip className="h-3 w-3 text-gray-500 cursor-grab" />
        <GitBranch className="h-4 w-4 text-yellow-400" />
        <span className="text-sm font-medium text-yellow-400">Condition</span>
      </div>
      
      <div className="px-3 py-3 space-y-2">
        <div className="text-sm font-semibold text-white truncate">
          {data.name || "Check Condition"}
        </div>
        
        {condition && (
          <div className="text-xs bg-gray-800/50 rounded px-2 py-1.5">
            <span className="text-purple-400 font-mono">{`{{${condition.variable}}}`}</span>
            <span className="text-gray-400 mx-1">{operatorLabels[condition.operator]}</span>
            {condition.value && (
              <span className="text-green-400">"{condition.value}"</span>
            )}
          </div>
        )}
        
        <div className="flex items-center justify-between text-xs pt-1">
          <div className="flex items-center gap-1 text-green-400">
            <Check className="h-3 w-3" />
            <span>True</span>
          </div>
          <div className="flex items-center gap-1 text-red-400">
            <X className="h-3 w-3" />
            <span>False</span>
          </div>
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        id="true"
        style={{ left: "30%" }}
        className="!w-3 !h-3 !bg-green-500 !border-2 !border-green-300"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="false"
        style={{ left: "70%" }}
        className="!w-3 !h-3 !bg-red-500 !border-2 !border-red-300"
      />
    </div>
  );
}

export default memo(ConditionNode);
