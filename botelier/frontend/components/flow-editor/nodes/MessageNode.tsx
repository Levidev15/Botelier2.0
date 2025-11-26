"use client";

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { MessageSquare, Grip } from "lucide-react";
import { MessageNodeData } from "../store";

interface MessageNodeProps {
  data: MessageNodeData;
  selected?: boolean;
}

function MessageNode({ data, selected }: MessageNodeProps) {
  const highlightVariables = (text: string) => {
    const parts = text.split(/(\{\{[^}]+\}\})/g);
    return parts.map((part, i) => {
      if (part.startsWith("{{") && part.endsWith("}}")) {
        return (
          <span key={i} className="text-purple-400 font-mono">
            {part}
          </span>
        );
      }
      return part;
    });
  };

  return (
    <div
      className={`
        min-w-[220px] max-w-[280px] rounded-lg border-2 bg-[#141414] shadow-lg
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
        <span className="text-sm font-medium text-blue-400">Message</span>
      </div>
      
      <div className="px-3 py-3 space-y-2">
        <div className="text-sm font-semibold text-white truncate">
          {data.name || "Message"}
        </div>
        
        {data.message && (
          <div className="text-xs text-gray-400 line-clamp-3 bg-gray-800/50 rounded px-2 py-1">
            {highlightVariables(data.message.substring(0, 100))}
            {data.message.length > 100 && "..."}
          </div>
        )}
        
        {data.waitForResponse && (
          <div className="text-xs text-blue-400/70 flex items-center gap-1">
            <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse" />
            Waits for response
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

export default memo(MessageNode);
