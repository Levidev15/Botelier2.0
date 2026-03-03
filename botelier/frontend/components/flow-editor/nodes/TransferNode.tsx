"use client";

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { PhoneForwarded, Grip, User } from "lucide-react";
import { TransferNodeData } from "../store";

interface TransferNodeProps {
  data: TransferNodeData & { isActive?: boolean };
  selected?: boolean;
}

function TransferNode({ data, selected }: TransferNodeProps) {
  const isActive = data.isActive;
  const transfer = data.transfer;
  
  return (
    <div
      className={`
        min-w-[220px] max-w-[280px] rounded-lg border-2 bg-[#141414] shadow-lg transition-all duration-300
        ${isActive 
          ? "border-cyan-400 ring-4 ring-cyan-400/40 scale-105" 
          : selected 
            ? "border-cyan-500 ring-2 ring-cyan-500/20" 
            : "border-cyan-600/50"
        }
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-cyan-500 !border-2 !border-cyan-300"
      />

      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800 bg-cyan-900/20 rounded-t-lg">
        <Grip className="h-3 w-3 text-gray-500 cursor-grab" />
        <PhoneForwarded className="h-4 w-4 text-cyan-400" />
        <span className="text-sm font-medium text-cyan-400">Transfer</span>
      </div>
      
      <div className="px-3 py-3 space-y-2">
        <div className="text-sm font-semibold text-white truncate">
          {data.name || "Transfer Call"}
        </div>
        
        {transfer && (
          <>
            {transfer.phoneNumber && (
              <div className="flex items-center gap-2 text-xs text-gray-400">
                <User className="h-3 w-3" />
                <span className="font-mono">{transfer.phoneNumber || "Not set"}</span>
              </div>
            )}
            
            {transfer.preTransferMessage && (
              <div className="text-xs text-gray-400 line-clamp-2 bg-gray-800/50 rounded px-2 py-1">
                "{transfer.preTransferMessage.substring(0, 60)}..."
              </div>
            )}
            
            {transfer.transferMode === "cold" ? (
              <div className="text-xs text-amber-400/70 flex items-center gap-1">
                <span className="w-1.5 h-1.5 bg-amber-400 rounded-full" />
                Cold transfer (SIP REFER)
              </div>
            ) : (
              <div className="text-xs text-cyan-400/70 flex items-center gap-1">
                <span className="w-1.5 h-1.5 bg-cyan-400 rounded-full" />
                Warm transfer
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default memo(TransferNode);
