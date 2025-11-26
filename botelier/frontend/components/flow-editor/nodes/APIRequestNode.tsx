"use client";

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { Globe, Grip, ArrowRightLeft } from "lucide-react";
import { APIRequestNodeData } from "../store";

interface APIRequestNodeProps {
  data: APIRequestNodeData;
  selected?: boolean;
}

const methodColors: Record<string, string> = {
  GET: "text-green-400 bg-green-900/50",
  POST: "text-blue-400 bg-blue-900/50",
  PUT: "text-yellow-400 bg-yellow-900/50",
  DELETE: "text-red-400 bg-red-900/50",
};

function APIRequestNode({ data, selected }: APIRequestNodeProps) {
  const api = data.api;
  
  const extractDomain = (url: string) => {
    try {
      if (url.includes("{{")) return url.substring(0, 40) + "...";
      const urlObj = new URL(url);
      return urlObj.hostname;
    } catch {
      return url.substring(0, 30) + "...";
    }
  };

  return (
    <div
      className={`
        min-w-[220px] max-w-[280px] rounded-lg border-2 bg-[#141414] shadow-lg
        ${selected ? "border-orange-500 ring-2 ring-orange-500/20" : "border-orange-600/50"}
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-orange-500 !border-2 !border-orange-300"
      />

      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800 bg-orange-900/20 rounded-t-lg">
        <Grip className="h-3 w-3 text-gray-500 cursor-grab" />
        <Globe className="h-4 w-4 text-orange-400" />
        <span className="text-sm font-medium text-orange-400">API Request</span>
      </div>
      
      <div className="px-3 py-3 space-y-2">
        <div className="text-sm font-semibold text-white truncate">
          {data.name || "API Call"}
        </div>
        
        {api && (
          <>
            <div className="flex items-center gap-2">
              <span className={`text-xs font-mono font-bold rounded px-1.5 py-0.5 ${methodColors[api.method] || "text-gray-400 bg-gray-800"}`}>
                {api.method}
              </span>
              <span className="text-xs text-gray-400 truncate">
                {extractDomain(api.url)}
              </span>
            </div>
            
            {api.responseMapping && Object.keys(api.responseMapping).length > 0 && (
              <div className="flex items-center gap-1 text-xs text-orange-400/70">
                <ArrowRightLeft className="h-3 w-3" />
                <span>Maps {Object.keys(api.responseMapping).length} fields</span>
              </div>
            )}
          </>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        id="success"
        style={{ left: "30%" }}
        className="!w-3 !h-3 !bg-green-500 !border-2 !border-green-300"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="error"
        style={{ left: "70%" }}
        className="!w-3 !h-3 !bg-red-500 !border-2 !border-red-300"
      />
    </div>
  );
}

export default memo(APIRequestNode);
