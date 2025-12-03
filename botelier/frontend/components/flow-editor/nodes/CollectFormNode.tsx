"use client";

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { ClipboardList, Grip, Calendar, Phone, Mail, Hash, List, Type, Clock } from "lucide-react";
import { CollectFormNodeData, SlotType } from "../store";

interface CollectFormNodeProps {
  data: CollectFormNodeData & { isActive?: boolean };
  selected?: boolean;
}

const slotTypeIcons: Record<SlotType, React.ReactNode> = {
  text: <Type className="h-2.5 w-2.5" />,
  date: <Calendar className="h-2.5 w-2.5" />,
  number: <Hash className="h-2.5 w-2.5" />,
  phone: <Phone className="h-2.5 w-2.5" />,
  email: <Mail className="h-2.5 w-2.5" />,
  time: <Clock className="h-2.5 w-2.5" />,
  choice: <List className="h-2.5 w-2.5" />,
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

function CollectFormNode({ data, selected }: CollectFormNodeProps) {
  const isActive = data.isActive;
  const slots = data.slots || [];
  const sortedSlots = [...slots].sort((a, b) => a.order - b.order);
  
  return (
    <div
      className={`
        min-w-[240px] max-w-[300px] rounded-lg border-2 bg-[#141414] shadow-lg transition-all duration-300
        ${isActive 
          ? "border-violet-400 ring-4 ring-violet-400/40 scale-105" 
          : selected 
            ? "border-violet-500 ring-2 ring-violet-500/20" 
            : "border-violet-600/50"
        }
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-violet-500 !border-2 !border-violet-300"
      />

      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800 bg-violet-900/30 rounded-t-lg">
        <Grip className="h-3 w-3 text-gray-500 cursor-grab" />
        <ClipboardList className="h-4 w-4 text-violet-400" />
        <span className="text-sm font-medium text-violet-400">Collect Form</span>
        <div className="ml-auto bg-violet-600/50 text-violet-200 text-xs px-1.5 py-0.5 rounded">
          {slots.length} {slots.length === 1 ? 'field' : 'fields'}
        </div>
      </div>
      
      <div className="px-3 py-3 space-y-2">
        <div className="text-sm font-semibold text-white truncate">
          {data.name || "Collect Form"}
        </div>
        
        {data.introMessage && (
          <div className="text-xs text-gray-400 line-clamp-1 bg-gray-800/50 rounded px-2 py-1">
            "{data.introMessage}"
          </div>
        )}
        
        {sortedSlots.length > 0 && (
          <div className="space-y-1 mt-2">
            {sortedSlots.slice(0, 4).map((slot, index) => (
              <div 
                key={slot.id} 
                className="flex items-center gap-2 text-xs bg-violet-900/20 rounded px-2 py-1"
              >
                <div className="flex items-center justify-center w-4 h-4 rounded-full bg-violet-600/40 text-violet-300 text-[10px] font-medium">
                  {index + 1}
                </div>
                <div className="flex items-center gap-1 text-violet-300">
                  {slotTypeIcons[slot.type]}
                </div>
                <span className="text-gray-300 truncate flex-1">
                  {slot.variableKey}
                </span>
                <span className="text-gray-500 text-[10px]">
                  {slotTypeLabels[slot.type]}
                </span>
              </div>
            ))}
            {sortedSlots.length > 4 && (
              <div className="text-xs text-gray-500 text-center py-1">
                +{sortedSlots.length - 4} more fields...
              </div>
            )}
          </div>
        )}
        
        {sortedSlots.length === 0 && (
          <div className="text-xs text-gray-500 italic text-center py-2">
            No fields configured
          </div>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-3 !h-3 !bg-violet-500 !border-2 !border-violet-300"
      />
    </div>
  );
}

export default memo(CollectFormNode);
