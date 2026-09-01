"use client";

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { Mic, Grip, List } from "lucide-react";
import { APIResponseNodeData } from "../store";

interface APIResponseNodeProps {
  data: APIResponseNodeData & { isActive?: boolean; isError?: boolean };
  selected?: boolean;
}

function APIResponseNode({ data, selected }: APIResponseNodeProps) {
  const isActive = data.isActive;
  const isError = data.isError;
  const cfg = data.responsePresentation || {};

  return (
    <div
      className={`
        min-w-[220px] max-w-[280px] rounded-lg border-2 bg-[#141414] shadow-lg transition-all duration-300
        ${isError
          ? "border-red-500 ring-2 ring-red-500/40 node-error-shake"
          : isActive
            ? "border-cyan-400 ring-4 ring-cyan-400/40 scale-105"
            : selected
              ? "border-amber-500 ring-2 ring-amber-500/20"
              : "border-amber-600/50"
        }
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-amber-500 !border-2 !border-amber-300"
      />

      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800 bg-amber-900/20 rounded-t-lg">
        <Grip className="h-3 w-3 text-gray-500 cursor-grab" />
        <Mic className="h-4 w-4 text-amber-400" />
        <span className="text-sm font-medium text-amber-400">API Response</span>
      </div>

      <div className="px-3 py-3 space-y-2">
        <div className="text-sm font-semibold text-white truncate">
          {data.name || "Present Results"}
        </div>

        {cfg.arrayVariable && (
          <div className="flex items-center gap-1.5 text-xs text-amber-400/70">
            <List className="h-3 w-3 shrink-0" />
            <span className="truncate">
              Iterates <span className="font-mono">{`{{${cfg.arrayVariable}}}`}</span>
            </span>
          </div>
        )}

        {cfg.introText && (
          <div className="text-xs text-gray-400 truncate italic">
            &ldquo;{cfg.introText.substring(0, 50)}{cfg.introText.length > 50 ? "…" : ""}&rdquo;
          </div>
        )}

        {!cfg.arrayVariable && !cfg.introText && (
          <div className="text-xs text-gray-500">Configure narration →</div>
        )}
      </div>

      {/* Two output handles — only shown when an array variable is wired */}
      {cfg.arrayVariable ? (
        <>
          <div className="flex justify-between px-3 pb-1.5 pt-0.5">
            <span className="text-[9px] text-green-400/70 font-medium">Has results</span>
            <span className="text-[9px] text-red-400/60 font-medium">No results</span>
          </div>
          <Handle
            type="source"
            position={Position.Bottom}
            id="has_results"
            style={{ left: "28%" }}
            className="!w-3 !h-3 !bg-green-500 !border-2 !border-green-300"
          />
          <Handle
            type="source"
            position={Position.Bottom}
            id="no_results"
            style={{ left: "72%" }}
            className="!w-3 !h-3 !bg-red-500 !border-2 !border-red-300"
          />
        </>
      ) : (
        <Handle
          type="source"
          position={Position.Bottom}
          id="has_results"
          className="!w-3 !h-3 !bg-amber-500 !border-2 !border-amber-300"
        />
      )}
    </div>
  );
}

export default memo(APIResponseNode);
