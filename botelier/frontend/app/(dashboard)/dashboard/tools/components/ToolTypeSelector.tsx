"use client";

import { Phone, Globe, PhoneOff, Mail, MessageSquare, GitBranch, LucideIcon } from "lucide-react";
import { ToolType } from "./ToolDrawer";

interface ToolTypeSelectorProps {
  selectedType: ToolType | null;
  onSelectType: (type: ToolType) => void;
}

interface ToolTypeOption {
  type: ToolType;
  label: string;
  icon: LucideIcon;
  color: string;
  description: string;
}

const toolTypes: ToolTypeOption[] = [
  {
    type: "FLOW",
    label: "Conversation Flow",
    icon: GitBranch,
    color: "bg-cyan-600",
    description: "Guide multi-step conversations"
  },
  {
    type: "TRANSFER_CALL",
    label: "Transfer Call",
    icon: Phone,
    color: "bg-blue-600",
    description: "Transfer call to a phone number"
  },
  {
    type: "API_REQUEST",
    label: "API Request",
    icon: Globe,
    color: "bg-purple-600",
    description: "Call external APIs"
  },
  {
    type: "END_CALL",
    label: "End Call",
    icon: PhoneOff,
    color: "bg-red-600",
    description: "End the conversation"
  },
  {
    type: "SEND_SMS",
    label: "Send SMS",
    icon: MessageSquare,
    color: "bg-green-600",
    description: "Send text message"
  },
  {
    type: "SEND_EMAIL",
    label: "Send Email",
    icon: Mail,
    color: "bg-orange-600",
    description: "Send email notification"
  }
];

export default function ToolTypeSelector({ selectedType, onSelectType }: ToolTypeSelectorProps) {
  return (
    <div className="space-y-2">
      {toolTypes.map(({ type, label, icon: Icon, color }) => (
        <button
          key={type}
          onClick={() => onSelectType(type)}
          className={`w-full flex items-center gap-3 px-3 py-3 rounded-lg transition-all ${
            selectedType === type
              ? "bg-blue-600 text-white"
              : "text-gray-300 hover:bg-gray-800"
          }`}
        >
          <div className={`w-8 h-8 rounded ${selectedType === type ? 'bg-white/20' : color + '/20'} flex items-center justify-center`}>
            <Icon 
              size={16}
              className={selectedType === type ? 'text-white' : color.replace('bg-', 'text-')}
            />
          </div>
          <span className="text-sm font-medium">{label}</span>
        </button>
      ))}
    </div>
  );
}
