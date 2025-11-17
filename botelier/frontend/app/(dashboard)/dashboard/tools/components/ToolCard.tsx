"use client";

import { LucideIcon, Trash2, Edit } from "lucide-react";
import { useState } from "react";

interface ToolCardProps {
  tool: {
    id: string;
    name: string;
    description: string;
    tool_type: string;
    config: any;
    is_active: boolean;
  };
  icon: LucideIcon;
  typeLabel: string;
  onDelete: (toolId: string) => void;
}

export default function ToolCard({ tool, icon: Icon, typeLabel, onDelete }: ToolCardProps) {
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    if (!confirm(`Delete tool "${tool.name}"?`)) return;

    setDeleting(true);
    try {
      const response = await fetch(`http://localhost:8000/api/tools/${tool.id}`, {
        method: "DELETE",
      });

      if (response.ok) {
        onDelete(tool.id);
      } else {
        alert("Failed to delete tool");
      }
    } catch (error) {
      console.error("Error deleting tool:", error);
      alert("Failed to delete tool");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="bg-[#141414] border border-gray-800 rounded-lg p-6 hover:border-gray-700 transition-colors">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-blue-600/10 flex items-center justify-center">
            <Icon className="text-blue-500" size={20} />
          </div>
          <div>
            <h3 className="font-semibold text-white">{tool.name}</h3>
            <p className="text-xs text-gray-500">{typeLabel}</p>
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${tool.is_active ? 'bg-green-500' : 'bg-gray-500'}`} />
        </div>
      </div>

      {/* Description */}
      <p className="text-sm text-gray-400 mb-4 line-clamp-2">
        {tool.description}
      </p>

      {/* Config Preview */}
      <div className="text-xs text-gray-500 mb-4">
        {tool.tool_type === "transfer_call" && (
          <div className="bg-[#0a0a0a] rounded p-2">
            📞 {tool.config.phone_number}
          </div>
        )}
        {tool.tool_type === "api_request" && (
          <div className="bg-[#0a0a0a] rounded p-2">
            <span className="font-mono">{tool.config.method || "GET"}</span> {tool.config.url?.substring(0, 40)}...
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 pt-4 border-t border-gray-800">
        <button
          className="flex-1 px-3 py-2 text-sm text-gray-400 hover:text-white hover:bg-gray-800 rounded transition-colors flex items-center justify-center gap-2"
        >
          <Edit size={14} />
          Edit
        </button>
        <button
          onClick={handleDelete}
          disabled={deleting}
          className="flex-1 px-3 py-2 text-sm text-red-400 hover:text-red-300 hover:bg-red-950/20 rounded transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
        >
          <Trash2 size={14} />
          {deleting ? "Deleting..." : "Delete"}
        </button>
      </div>
    </div>
  );
}
