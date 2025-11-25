"use client";

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { MessageSquare, Grip } from "lucide-react";
import { NodeData, FlowFunction } from "../store";

interface ConversationNodeProps {
  data: NodeData;
  selected?: boolean;
}

function ConversationNode({ data, selected }: ConversationNodeProps) {
  const nodeData = data as NodeData;
  
  return (
    <div
      className={`
        min-w-[200px] rounded-lg border-2 bg-[#141414] shadow-lg
        ${selected ? "border-blue-500 ring-2 ring-blue-500/20" : "border-blue-600/50"}
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-blue-500 !border-2 !border-blue-300"
      />

      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800 bg-blue-900/20 rounded-t-lg">
        <Grip className="h-3 w-3 text-gray-500 cursor-grab" />
        <MessageSquare className="h-4 w-4 text-blue-400" />
        <span className="text-sm font-medium text-blue-400">Node</span>
      </div>
      
      <div className="px-3 py-3">
        <div className="text-sm font-semibold text-white truncate">
          {nodeData.name || "Conversation"}
        </div>
        
        {nodeData.task_messages && nodeData.task_messages.length > 0 && (
          <div className="mt-1 text-xs text-gray-400 line-clamp-2">
            {nodeData.task_messages[0].content.substring(0, 60)}...
          </div>
        )}
        
        {nodeData.functions && nodeData.functions.length > 0 && (
          <div className="mt-2 space-y-1">
            {nodeData.functions.slice(0, 3).map((func: FlowFunction, i: number) => (
              <div
                key={i}
                className="text-xs text-gray-400 bg-gray-800/50 rounded px-2 py-1 truncate"
              >
                {func.name}
              </div>
            ))}
            {nodeData.functions.length > 3 && (
              <div className="text-xs text-gray-500">
                +{nodeData.functions.length - 3} more
              </div>
            )}
          </div>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-3 !h-3 !bg-blue-500 !border-2 !border-blue-300"
      />
    </div>
  );
}

export default memo(ConversationNode);
