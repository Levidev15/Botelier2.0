"use client";

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { Play, Grip } from "lucide-react";
import { InitialNodeData } from "../store";

interface InitialNodeProps {
  data: InitialNodeData & { isActive?: boolean };
  selected?: boolean;
}

function InitialNode({ data, selected }: InitialNodeProps) {
  const isActive = data.isActive;
  
  return (
    <div
      className={`
        min-w-[220px] max-w-[280px] rounded-lg border-2 bg-[#141414] shadow-lg transition-all duration-300
        ${isActive 
          ? "border-cyan-400 ring-4 ring-cyan-400/40 scale-105" 
          : selected 
            ? "border-green-500 ring-2 ring-green-500/20" 
            : "border-green-600/50"
        }
      `}
    >
      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800 bg-green-900/20 rounded-t-lg">
        <Grip className="h-3 w-3 text-gray-500 cursor-grab" />
        <Play className="h-4 w-4 text-green-400" />
        <span className="text-sm font-medium text-green-400">Start</span>
      </div>
      
      <div className="px-3 py-3 space-y-2">
        <div className="text-sm font-semibold text-white truncate">
          {data.name || "Greeting"}
        </div>
        
        {data.greeting && (
          <div className="text-xs text-gray-400 line-clamp-2 bg-gray-800/50 rounded px-2 py-1">
            "{data.greeting.substring(0, 80)}..."
          </div>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-3 !h-3 !bg-green-500 !border-2 !border-green-300"
      />
    </div>
  );
}

export default memo(InitialNode);
