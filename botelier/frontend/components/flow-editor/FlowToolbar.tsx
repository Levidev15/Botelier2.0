"use client";

import { useState } from "react";
import { 
  Save, 
  Undo2, 
  Redo2, 
  Plus, 
  Layout, 
  Download,
  Upload,
  ChevronDown 
} from "lucide-react";
import { useFlowStore } from "./store";

interface FlowToolbarProps {
  onSave: () => void;
  isSaving: boolean;
}

export default function FlowToolbar({ onSave, isSaving }: FlowToolbarProps) {
  const { addNode, isDirty, applyTemplate, isLoading } = useFlowStore();
  const [showAddMenu, setShowAddMenu] = useState(false);
  const [showTemplateMenu, setShowTemplateMenu] = useState(false);

  const templates = [
    { id: "faq_bot", name: "FAQ Bot", description: "Simple Q&A assistant" },
    { id: "booking_flow", name: "Booking Flow", description: "Room reservation workflow" },
    { id: "transfer_flow", name: "Transfer Flow", description: "Call routing system" },
    { id: "concierge_flow", name: "Concierge Flow", description: "Full-service assistant" },
  ];

  const handleAddNode = (type: "initial" | "node" | "end") => {
    addNode(type, { x: 250, y: 250 });
    setShowAddMenu(false);
  };

  const handleApplyTemplate = async (templateId: string) => {
    try {
      await applyTemplate(templateId);
      setShowTemplateMenu(false);
    } catch (error) {
      console.error("Failed to apply template:", error);
    }
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
            <div className="absolute top-full left-0 mt-1 w-48 bg-[#1a1a1a] border border-gray-700 rounded-lg shadow-xl z-50">
              <button
                onClick={() => handleAddNode("initial")}
                className="w-full px-3 py-2 text-left text-sm text-gray-300 hover:bg-gray-800 flex items-center gap-2"
              >
                <div className="w-3 h-3 rounded-full bg-green-500" />
                Start Node
              </button>
              <button
                onClick={() => handleAddNode("node")}
                className="w-full px-3 py-2 text-left text-sm text-gray-300 hover:bg-gray-800 flex items-center gap-2"
              >
                <div className="w-3 h-3 rounded-full bg-blue-500" />
                Conversation Node
              </button>
              <button
                onClick={() => handleAddNode("end")}
                className="w-full px-3 py-2 text-left text-sm text-gray-300 hover:bg-gray-800 flex items-center gap-2"
              >
                <div className="w-3 h-3 rounded-full bg-red-500" />
                End Node
              </button>
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
            <div className="absolute top-full left-0 mt-1 w-64 bg-[#1a1a1a] border border-gray-700 rounded-lg shadow-xl z-50">
              {templates.map((template) => (
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
