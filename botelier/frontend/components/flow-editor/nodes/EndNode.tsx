"use client";

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { PhoneOff, Grip } from "lucide-react";
import { EndNodeData } from "../store";

interface EndNodeProps {
  data: EndNodeData & { isActive?: boolean };
  selected?: boolean;
}

function EndNode({ data, selected }: EndNodeProps) {
  const isActive = data.isActive;
  
  return (
    <div
      className={`
        min-w-[220px] max-w-[280px] rounded-lg border-2 bg-[#141414] shadow-lg transition-all duration-300
        ${isActive 
          ? "border-cyan-400 ring-4 ring-cyan-400/40 scale-105" 
          : selected 
            ? "border-red-500 ring-2 ring-red-500/20" 
            : "border-red-600/50"
        }
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-red-500 !border-2 !border-red-300"
      />

      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800 bg-red-900/20 rounded-t-lg">
        <Grip className="h-3 w-3 text-gray-500 cursor-grab" />
        <PhoneOff className="h-4 w-4 text-red-400" />
        <span className="text-sm font-medium text-red-400">End Call</span>
      </div>
      
      <div className="px-3 py-3 space-y-2">
        <div className="text-sm font-semibold text-white truncate">
          {data.name || "End Call"}
        </div>
        
        {data.closingMessage && (
          <div className="text-xs text-gray-400 line-clamp-2 bg-gray-800/50 rounded px-2 py-1">
            "{data.closingMessage.substring(0, 80)}..."
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(EndNode);
