"use client";

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { ListChecks, Grip } from "lucide-react";
import { OptionPickerNodeData } from "../store";

interface OptionPickerNodeProps {
  data: OptionPickerNodeData & { isActive?: boolean; isError?: boolean };
  selected?: boolean;
}

function OptionPickerNode({ data, selected }: OptionPickerNodeProps) {
  const isActive = data.isActive;
  const isError = data.isError;
  const picker = data.optionPicker || { sourceVariable: "", labelPath: "", prompt: "", writes: [] };
  const writes = picker.writes || [];

  return (
    <div
      className={`
        min-w-[240px] max-w-[300px] rounded-lg border-2 bg-[#141414] shadow-lg transition-all duration-300
        ${isError
          ? "border-red-500 ring-2 ring-red-500/40 node-error-shake"
          : isActive
            ? "border-cyan-400 ring-4 ring-cyan-400/40 scale-105"
            : selected
              ? "border-teal-500 ring-2 ring-teal-500/20"
              : "border-teal-600/50"
        }
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-teal-500 !border-2 !border-teal-300"
      />

      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800 bg-teal-900/20 rounded-t-lg">
        <Grip className="h-3 w-3 text-gray-500 cursor-grab" />
        <ListChecks className="h-4 w-4 text-teal-400" />
        <span className="text-sm font-medium text-teal-400">Option Picker</span>
      </div>

      <div className="px-3 py-3 space-y-2">
        <div className="text-sm font-semibold text-white truncate">
          {data.name || "Pick Option"}
        </div>

        {picker.sourceVariable && (
          <div className="text-xs bg-gray-800/50 rounded px-2 py-1.5">
            <span className="text-gray-400">From: </span>
            <span className="text-purple-400 font-mono">{`{{${picker.sourceVariable}}}`}</span>
          </div>
        )}

        {writes.length > 0 && (
          <div className="text-xs text-gray-400">
            Binds {writes.length} variable{writes.length === 1 ? "" : "s"} on selection
          </div>
        )}

        {!picker.sourceVariable && (
          <div className="text-xs text-gray-500">Configure source list →</div>
        )}
      </div>

      <div className="flex justify-between px-3 pb-1.5 pt-0.5">
        <span className="text-[9px] text-teal-400/70 font-medium">Selected</span>
        <span className="text-[9px] text-gray-500 font-medium">Fallback</span>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        id="selected"
        style={{ left: "28%" }}
        className="!w-3 !h-3 !bg-teal-500 !border-2 !border-teal-300"
        title="After a valid selection"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="fallback"
        style={{ left: "72%" }}
        className="!w-3 !h-3 !bg-gray-500 !border-2 !border-gray-400"
        title="After repeated failed attempts (optional)"
      />
    </div>
  );
}

export default memo(OptionPickerNode);
