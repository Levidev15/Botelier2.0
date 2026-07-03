"use client";

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { ClipboardList, Grip } from "lucide-react";
import { SaveRecordNodeData } from "../store";

interface SaveRecordNodeProps {
  data: SaveRecordNodeData & { isActive?: boolean };
  selected?: boolean;
}

function SaveRecordNode({ data, selected }: SaveRecordNodeProps) {
  const isActive = data.isActive;
  const saveRecord = data.saveRecord || {
    recordTypeId: "",
    recordTypeName: "",
    mapping: {},
    status: "",
  };

  const mappedCount = Object.keys(saveRecord.mapping || {}).length;

  return (
    <div
      className={`
        min-w-[200px] max-w-[280px] rounded-lg border-2 bg-[#141414] shadow-lg transition-all duration-300
        ${
          isActive
            ? "border-cyan-400 ring-4 ring-cyan-400/40 scale-105"
            : selected
            ? "border-rose-500 ring-2 ring-rose-500/20"
            : "border-rose-600/50"
        }
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-rose-500 !border-2 !border-rose-300"
      />

      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800 bg-rose-900/20 rounded-t-lg">
        <Grip className="h-3 w-3 text-gray-500 cursor-grab" />
        <ClipboardList className="h-4 w-4 text-rose-400" />
        <span className="text-sm font-medium text-rose-400">Save Record</span>
      </div>

      <div className="px-3 py-3 space-y-2">
        <div className="text-sm font-semibold text-white truncate">
          {data.name || "Save Record"}
        </div>

        <div className="flex items-center gap-2 text-xs bg-gray-800/50 rounded px-2 py-1.5">
          <span className="text-rose-400 truncate max-w-[160px]">
            {saveRecord.recordTypeName || "Choose record type"}
          </span>
        </div>

        <div className="text-xs text-gray-500">
          {saveRecord.recordTypeId
            ? `${mappedCount} field${mappedCount === 1 ? "" : "s"} mapped`
            : "Voice-only"}
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-3 !h-3 !bg-rose-500 !border-2 !border-rose-300"
      />
    </div>
  );
}

export default memo(SaveRecordNode);
