"use client";

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { CheckCircle2, Grip, XCircle } from "lucide-react";
import { ConfirmationNodeData } from "../store";

interface ConfirmationNodeProps {
  data: ConfirmationNodeData & { isActive?: boolean };
  selected?: boolean;
}

function ConfirmationNode({ data, selected }: ConfirmationNodeProps) {
  const isActive = data.isActive;
  const confirmation = data.confirmation || { 
    summaryTemplate: "", 
    confirmPrompt: "Is this correct?",
    variablesToConfirm: [] 
  };

  return (
    <div
      className={`
        min-w-[260px] max-w-[320px] rounded-lg border-2 bg-[#141414] shadow-lg transition-all duration-300
        ${isActive 
          ? "border-cyan-400 ring-4 ring-cyan-400/40 scale-105" 
          : selected 
            ? "border-emerald-500 ring-2 ring-emerald-500/20" 
            : "border-emerald-600/50"
        }
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-emerald-500 !border-2 !border-emerald-300"
      />

      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800 bg-emerald-900/20 rounded-t-lg">
        <Grip className="h-3 w-3 text-gray-500 cursor-grab" />
        <CheckCircle2 className="h-4 w-4 text-emerald-400" />
        <span className="text-sm font-medium text-emerald-400">Confirmation</span>
      </div>

      <div className="px-3 py-3 space-y-2">
        <div className="text-sm font-semibold text-white truncate">
          {data.name || "Confirm Details"}
        </div>
        
        {confirmation.variablesToConfirm.length > 0 && (
          <div className="text-xs bg-gray-800/50 rounded px-2 py-1.5">
            <span className="text-gray-400">Confirming: </span>
            <span className="text-emerald-400">
              {confirmation.variablesToConfirm.slice(0, 3).map(v => `{{${v}}}`).join(", ")}
              {confirmation.variablesToConfirm.length > 3 && ` +${confirmation.variablesToConfirm.length - 3} more`}
            </span>
          </div>
        )}

        {confirmation.confirmPrompt && (
          <div className="text-xs text-gray-400 truncate">
            "{confirmation.confirmPrompt}"
          </div>
        )}

        <div className="flex gap-2 mt-2">
          <div className="flex items-center gap-1 text-xs">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: "#22c55e" }} />
            <span className="text-gray-400">Confirmed</span>
          </div>
          <div className="flex items-center gap-1 text-xs">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: "#ef4444" }} />
            <span className="text-gray-400">Edit</span>
          </div>
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        id="confirmed"
        style={{ 
          left: "30%",
          width: "12px",
          height: "12px",
          backgroundColor: "#22c55e",
          border: "2px solid #86efac"
        }}
        title="Confirmed - proceed"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="edit"
        style={{ 
          left: "70%",
          width: "12px",
          height: "12px",
          backgroundColor: "#ef4444",
          border: "2px solid #fca5a5"
        }}
        title="Edit - go back"
      />
    </div>
  );
}

export default memo(ConfirmationNode);
