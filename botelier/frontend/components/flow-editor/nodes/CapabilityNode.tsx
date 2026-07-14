"use client";

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { Sparkles, Grip, ArrowRightLeft } from "lucide-react";
import { CapabilityNodeData } from "../store";

interface CapabilityNodeProps {
  data: CapabilityNodeData & { isActive?: boolean };
  selected?: boolean;
}

// Human-readable labels for the vendor-neutral capabilities. Falls back to a
// prettified version of the raw name for any capability not listed here.
const capabilityLabels: Record<string, string> = {
  search_availability: "Search Availability",
  lookup_reservation: "Look Up Reservation",
  book_reservation: "Book Reservation",
  cancel_reservation: "Cancel Reservation",
  collect_payment: "Collect Payment",
};

function prettify(name: string): string {
  return name
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function CapabilityNode({ data, selected }: CapabilityNodeProps) {
  const isActive = data.isActive;
  const api = data.api;
  const capability = api?.capability || "";
  const label = capability
    ? capabilityLabels[capability] || prettify(capability)
    : "No capability selected";

  return (
    <div
      className={`
        min-w-[220px] max-w-[280px] rounded-lg border-2 bg-[#141414] shadow-lg transition-all duration-300
        ${isActive
          ? "border-cyan-400 ring-4 ring-cyan-400/40 scale-105"
          : selected
            ? "border-purple-500 ring-2 ring-purple-500/20"
            : "border-purple-600/50"
        }
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-purple-500 !border-2 !border-purple-300"
      />

      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800 bg-purple-900/20 rounded-t-lg">
        <Grip className="h-3 w-3 text-gray-500 cursor-grab" />
        <Sparkles className="h-4 w-4 text-purple-400" />
        <span className="text-sm font-medium text-purple-400">Capability</span>
      </div>

      <div className="px-3 py-3 space-y-2">
        <div className="text-sm font-semibold text-white truncate">
          {data.name || "Capability"}
        </div>

        <div className="flex items-center gap-2">
          <span
            className={`text-xs font-mono font-bold rounded px-1.5 py-0.5 ${
              capability
                ? "text-purple-300 bg-purple-900/50"
                : "text-gray-400 bg-gray-800"
            }`}
          >
            {label}
          </span>
        </div>

        {api?.responseMapping && Object.keys(api.responseMapping).length > 0 && (
          <div className="flex items-center gap-1 text-xs text-purple-400/70">
            <ArrowRightLeft className="h-3 w-3" />
            <span>Maps {Object.keys(api.responseMapping).length} fields</span>
          </div>
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

export default memo(CapabilityNode);
