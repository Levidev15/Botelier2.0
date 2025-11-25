"use client";

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { PhoneOff, Grip } from "lucide-react";
import { NodeData } from "../store";

interface EndNodeProps {
  data: NodeData;
  selected?: boolean;
}

function EndNode({ data, selected }: EndNodeProps) {
  const nodeData = data as NodeData;
  
  return (
    <div
      className={`
        min-w-[200px] rounded-lg border-2 bg-[#141414] shadow-lg
        ${selected ? "border-red-500 ring-2 ring-red-500/20" : "border-red-600/50"}
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
        <span className="text-sm font-medium text-red-400">End</span>
      </div>
      
      <div className="px-3 py-3">
        <div className="text-sm font-semibold text-white truncate">
          {nodeData.name || "End Call"}
        </div>
        
        {nodeData.task_messages && nodeData.task_messages.length > 0 && (
          <div className="mt-1 text-xs text-gray-400 line-clamp-2">
            {nodeData.task_messages[0].content.substring(0, 60)}...
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(EndNode);
