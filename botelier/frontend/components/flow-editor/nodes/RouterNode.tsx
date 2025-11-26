"use client";

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { Route, Grip } from "lucide-react";
import { RouterNodeData } from "../store";

interface RouterNodeProps {
  data: RouterNodeData & { isActive?: boolean };
  selected?: boolean;
}

const OPTION_COLORS = [
  { bg: "bg-blue-500", border: "border-blue-300" },
  { bg: "bg-green-500", border: "border-green-300" },
  { bg: "bg-purple-500", border: "border-purple-300" },
  { bg: "bg-orange-500", border: "border-orange-300" },
  { bg: "bg-pink-500", border: "border-pink-300" },
  { bg: "bg-cyan-500", border: "border-cyan-300" },
  { bg: "bg-yellow-500", border: "border-yellow-300" },
  { bg: "bg-red-500", border: "border-red-300" },
];

function RouterNode({ data, selected }: RouterNodeProps) {
  const isActive = data.isActive;
  const router = data.router || { variable: "", options: [] };
  const options = router.options || [];
  const optionCount = options.length + 1;
  
  return (
    <div
      className={`
        min-w-[240px] max-w-[320px] rounded-lg border-2 bg-[#141414] shadow-lg transition-all duration-300
        ${isActive 
          ? "border-cyan-400 ring-4 ring-cyan-400/40 scale-105" 
          : selected 
            ? "border-indigo-500 ring-2 ring-indigo-500/20" 
            : "border-indigo-600/50"
        }
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-indigo-500 !border-2 !border-indigo-300"
      />

      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800 bg-indigo-900/20 rounded-t-lg">
        <Grip className="h-3 w-3 text-gray-500 cursor-grab" />
        <Route className="h-4 w-4 text-indigo-400" />
        <span className="text-sm font-medium text-indigo-400">Router</span>
      </div>
      
      <div className="px-3 py-3 space-y-2">
        <div className="text-sm font-semibold text-white truncate">
          {data.name || "Route Decision"}
        </div>
        
        {router.variable && (
          <div className="text-xs bg-gray-800/50 rounded px-2 py-1.5">
            <span className="text-gray-400">Check: </span>
            <span className="text-purple-400 font-mono">{`{{${router.variable}}}`}</span>
          </div>
        )}
        
        <div className="space-y-1 pt-1">
          {options.map((option, index) => {
            const color = OPTION_COLORS[index % OPTION_COLORS.length];
            return (
              <div key={option.id} className="flex items-center gap-2 text-xs">
                <span className={`w-2 h-2 ${color.bg} rounded-full`} />
                <span className="text-gray-300 truncate">{option.label || option.value}</span>
              </div>
            );
          })}
          <div className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 bg-gray-500 rounded-full" />
            <span className="text-gray-500 italic">Default</span>
          </div>
        </div>
      </div>

      {options.map((option, index) => {
        const color = OPTION_COLORS[index % OPTION_COLORS.length];
        const position = ((index + 1) / optionCount) * 100;
        return (
          <Handle
            key={option.id}
            type="source"
            position={Position.Bottom}
            id={option.id}
            style={{ left: `${position}%` }}
            className={`!w-3 !h-3 ${color.bg} !border-2 ${color.border}`}
            title={option.label || option.value}
          />
        );
      })}
      <Handle
        type="source"
        position={Position.Bottom}
        id="default"
        style={{ left: `${((options.length + 1) / optionCount) * 100}%` }}
        className="!w-3 !h-3 !bg-gray-500 !border-2 !border-gray-400"
        title="Default (no match)"
      />
    </div>
  );
}

export default memo(RouterNode);
