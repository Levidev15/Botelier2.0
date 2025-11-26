"use client";

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { FormInput, Grip, Calendar, Phone, Mail, Hash, List, Type } from "lucide-react";
import { CollectSlotNodeData, SlotType } from "../store";

interface CollectSlotNodeProps {
  data: CollectSlotNodeData & { isActive?: boolean };
  selected?: boolean;
}

const slotTypeIcons: Record<SlotType, React.ReactNode> = {
  text: <Type className="h-3 w-3" />,
  date: <Calendar className="h-3 w-3" />,
  number: <Hash className="h-3 w-3" />,
  phone: <Phone className="h-3 w-3" />,
  email: <Mail className="h-3 w-3" />,
  time: <Calendar className="h-3 w-3" />,
  choice: <List className="h-3 w-3" />,
};

const slotTypeLabels: Record<SlotType, string> = {
  text: "Text",
  date: "Date",
  number: "Number",
  phone: "Phone",
  email: "Email",
  time: "Time",
  choice: "Choice",
};

function CollectSlotNode({ data, selected }: CollectSlotNodeProps) {
  const isActive = data.isActive;
  const slot = data.slot;
  
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
        <FormInput className="h-4 w-4 text-purple-400" />
        <span className="text-sm font-medium text-purple-400">Collect Input</span>
      </div>
      
      <div className="px-3 py-3 space-y-2">
        <div className="text-sm font-semibold text-white truncate">
          {data.name || "Collect Info"}
        </div>
        
        {slot && (
          <>
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1 text-xs bg-purple-900/50 text-purple-300 rounded px-2 py-0.5">
                {slotTypeIcons[slot.type]}
                <span>{slotTypeLabels[slot.type]}</span>
              </div>
              <div className="text-xs text-gray-500 font-mono">
                {`{{${slot.variableKey}}}`}
              </div>
            </div>
            
            <div className="text-xs text-gray-400 line-clamp-2 bg-gray-800/50 rounded px-2 py-1">
              "{slot.prompt}"
            </div>
            
            {slot.validation && (
              <div className="text-xs text-purple-400/70">
                {slot.validation.min !== undefined && `Min: ${slot.validation.min}`}
                {slot.validation.max !== undefined && ` Max: ${slot.validation.max}`}
                {slot.validation.choices && `Options: ${slot.validation.choices.length}`}
              </div>
            )}
          </>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-3 !h-3 !bg-purple-500 !border-2 !border-purple-300"
      />
    </div>
  );
}

export default memo(CollectSlotNode);
