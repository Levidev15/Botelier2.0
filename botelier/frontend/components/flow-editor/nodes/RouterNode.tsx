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
  { bg: "#3b82f6", border: "#93c5fd" },
  { bg: "#22c55e", border: "#86efac" },
  { bg: "#a855f7", border: "#d8b4fe" },
  { bg: "#f97316", border: "#fdba74" },
  { bg: "#ec4899", border: "#f9a8d4" },
  { bg: "#06b6d4", border: "#67e8f9" },
  { bg: "#eab308", border: "#fde047" },
  { bg: "#ef4444", border: "#fca5a5" },
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
                <span 
                  className="w-2 h-2 rounded-full" 
                  style={{ backgroundColor: color.bg }}
                />
                <span className="text-gray-300 truncate">{option.label || option.value}</span>
              </div>
            );
          })}
          <div className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: "#6b7280" }} />
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
            style={{ 
              left: `${position}%`,
              width: "12px",
              height: "12px",
              backgroundColor: color.bg,
              border: `2px solid ${color.border}`
            }}
            title={option.label || option.value}
          />
        );
      })}
      <Handle
        type="source"
        position={Position.Bottom}
        id="default"
        style={{ 
          left: `${((options.length + 1) / optionCount) * 100}%`,
          width: "12px",
          height: "12px",
          backgroundColor: "#6b7280",
          border: "2px solid #9ca3af"
        }}
        title="Default (no match)"
      />
    </div>
  );
}

export default memo(RouterNode);
