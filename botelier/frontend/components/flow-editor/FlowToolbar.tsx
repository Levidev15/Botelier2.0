"use client";

import { useState } from "react";
import { 
  Save, 
  Undo2, 
  Redo2, 
  Plus, 
  Layout, 
  ChevronDown,
  Play,
  MessageSquare,
  FormInput,
  Globe,
  GitBranch,
  PhoneForwarded,
  PhoneOff
} from "lucide-react";
import { useFlowStore, NodeType, AVAILABLE_TEMPLATES } from "./store";

interface FlowToolbarProps {
  onSave: () => void;
  isSaving: boolean;
}

const nodeTypeConfig: { type: NodeType; label: string; icon: React.ReactNode; color: string }[] = [
  { type: "initial", label: "Start", icon: <Play className="h-3 w-3" />, color: "bg-green-500" },
  { type: "message", label: "Message", icon: <MessageSquare className="h-3 w-3" />, color: "bg-blue-500" },
  { type: "collect_slot", label: "Collect Input", icon: <FormInput className="h-3 w-3" />, color: "bg-purple-500" },
  { type: "api_request", label: "API Request", icon: <Globe className="h-3 w-3" />, color: "bg-orange-500" },
  { type: "condition", label: "Condition", icon: <GitBranch className="h-3 w-3" />, color: "bg-yellow-500" },
  { type: "transfer", label: "Transfer Call", icon: <PhoneForwarded className="h-3 w-3" />, color: "bg-cyan-500" },
  { type: "end", label: "End Call", icon: <PhoneOff className="h-3 w-3" />, color: "bg-red-500" },
];

export default function FlowToolbar({ onSave, isSaving }: FlowToolbarProps) {
  const { addNode, isDirty, applyTemplate, isLoading, nodes } = useFlowStore();
  const [showAddMenu, setShowAddMenu] = useState(false);
  const [showTemplateMenu, setShowTemplateMenu] = useState(false);

  const handleAddNode = (type: NodeType) => {
    const lastNode = nodes[nodes.length - 1];
    const position = lastNode 
      ? { x: lastNode.position.x, y: lastNode.position.y + 150 }
      : { x: 250, y: 100 };
    addNode(type, position);
    setShowAddMenu(false);
  };

  const handleApplyTemplate = (templateId: string) => {
    applyTemplate(templateId);
    setShowTemplateMenu(false);
  };

  return (
    <div className="h-12 bg-[#141414] border-b border-gray-800 flex items-center justify-between px-4">
      <div className="flex items-center gap-2">
        <div className="relative">
          <button
            onClick={() => setShowAddMenu(!showAddMenu)}
            className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium transition"
          >
            <Plus className="h-4 w-4" />
            Add Node
            <ChevronDown className="h-3 w-3" />
          </button>
          
          {showAddMenu && (
            <div className="absolute top-full left-0 mt-1 w-56 bg-[#1a1a1a] border border-gray-700 rounded-lg shadow-xl z-50 py-1">
              <div className="px-3 py-1.5 text-xs text-gray-500 uppercase tracking-wider">Node Types</div>
              {nodeTypeConfig.map((config) => (
                <button
                  key={config.type}
                  onClick={() => handleAddNode(config.type)}
                  className="w-full px-3 py-2 text-left text-sm text-gray-300 hover:bg-gray-800 flex items-center gap-3"
                >
                  <div className={`w-4 h-4 rounded flex items-center justify-center ${config.color}`}>
                    {config.icon}
                  </div>
                  {config.label}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="relative">
          <button
            onClick={() => setShowTemplateMenu(!showTemplateMenu)}
            className="flex items-center gap-1 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-medium transition"
          >
            <Layout className="h-4 w-4" />
            Templates
            <ChevronDown className="h-3 w-3" />
          </button>
          
          {showTemplateMenu && (
            <div className="absolute top-full left-0 mt-1 w-72 bg-[#1a1a1a] border border-gray-700 rounded-lg shadow-xl z-50 py-1">
              <div className="px-3 py-1.5 text-xs text-gray-500 uppercase tracking-wider">Hotel Templates</div>
              {AVAILABLE_TEMPLATES.map((template) => (
                <button
                  key={template.id}
                  onClick={() => handleApplyTemplate(template.id)}
                  disabled={isLoading}
                  className="w-full px-3 py-2 text-left hover:bg-gray-800 disabled:opacity-50"
                >
                  <div className="text-sm text-white font-medium">
                    {template.name}
                  </div>
                  <div className="text-xs text-gray-400">
                    {template.description}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="h-6 w-px bg-gray-700 mx-2" />

        <button
          className="p-2 text-gray-400 hover:text-white rounded-lg hover:bg-gray-800 transition"
          title="Undo"
        >
          <Undo2 className="h-4 w-4" />
        </button>

        <button
          className="p-2 text-gray-400 hover:text-white rounded-lg hover:bg-gray-800 transition"
          title="Redo"
        >
          <Redo2 className="h-4 w-4" />
        </button>
      </div>

      <div className="flex items-center gap-2">
        {isDirty && (
          <span className="text-xs text-yellow-500 mr-2">Unsaved changes</span>
        )}

        <button
          onClick={onSave}
          disabled={isSaving || !isDirty}
          className={`
            flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-medium transition
            ${isDirty
              ? "bg-blue-600 hover:bg-blue-700 text-white"
              : "bg-gray-700 text-gray-400 cursor-not-allowed"
            }
          `}
        >
          <Save className="h-4 w-4" />
          {isSaving ? "Saving..." : "Save Flow"}
        </button>
      </div>

      {(showAddMenu || showTemplateMenu) && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => {
            setShowAddMenu(false);
            setShowTemplateMenu(false);
          }}
        />
      )}
    </div>
  );
}
