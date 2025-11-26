"use client";

import { LucideIcon, Trash2, Edit, GitBranch } from "lucide-react";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { notify, confirmAction } from "@/lib/notifications";

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
  const router = useRouter();
  const [deleting, setDeleting] = useState(false);

  const isFlowTool = tool.tool_type === "FLOW";

  const handleEditFlow = () => {
    router.push(`/dashboard/tools/${tool.id}/flow`);
  };

  const handleDelete = async () => {
    const confirmed = await confirmAction(`Delete tool "${tool.name}"?`, {
      confirmText: "Delete",
      cancelText: "Cancel",
    });

    if (!confirmed) return;

    setDeleting(true);
    const hotelId = "6b410bcc-f843-40df-b32d-078d3e01ac7f";

    try {
      const response = await fetch(`/api/tools/${tool.id}?hotel_id=${hotelId}`, {
        method: "DELETE",
      });

      if (response.ok) {
        notify.success("Tool deleted successfully");
        onDelete(tool.id);
      } else {
        const error = await response.json();
        notify.error(error.detail || "Failed to delete tool");
      }
    } catch (error) {
      console.error("Error deleting tool:", error);
      notify.error("Failed to delete tool");
    } finally {
      setDeleting(false);
    }
  };

  const getIconColor = () => {
    if (isFlowTool) return "text-cyan-500";
    return "text-blue-500";
  };

  const getIconBgColor = () => {
    if (isFlowTool) return "bg-cyan-600/10";
    return "bg-blue-600/10";
  };

  return (
    <div className="bg-[#141414] border border-gray-800 rounded-lg p-6 hover:border-gray-700 transition-colors">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-lg ${getIconBgColor()} flex items-center justify-center`}>
            <Icon className={getIconColor()} size={20} />
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

      <p className="text-sm text-gray-400 mb-4 line-clamp-2">
        {tool.description}
      </p>

      <div className="text-xs text-gray-500 mb-4">
        {tool.tool_type === "TRANSFER_CALL" && (
          <div className="bg-[#0a0a0a] rounded p-2">
            <span className="mr-1">📞</span> {tool.config.phone_number}
          </div>
        )}
        {tool.tool_type === "API_REQUEST" && (
          <div className="bg-[#0a0a0a] rounded p-2">
            <span className="font-mono">{tool.config.method || "GET"}</span> {tool.config.url?.substring(0, 40)}...
          </div>
        )}
        {tool.tool_type === "FLOW" && (
          <div className="bg-[#0a0a0a] rounded p-2 flex items-center gap-2">
            <GitBranch size={12} className="text-cyan-500" />
            <span>{tool.config.nodes?.length || 0} nodes</span>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 pt-4 border-t border-gray-800">
        {isFlowTool ? (
          <button
            onClick={handleEditFlow}
            className="flex-1 px-3 py-2 text-sm text-cyan-400 hover:text-cyan-300 hover:bg-cyan-950/20 rounded transition-colors flex items-center justify-center gap-2"
          >
            <GitBranch size={14} />
            Edit Flow
          </button>
        ) : (
          <button
            className="flex-1 px-3 py-2 text-sm text-gray-400 hover:text-white hover:bg-gray-800 rounded transition-colors flex items-center justify-center gap-2"
          >
            <Edit size={14} />
            Edit
          </button>
        )}
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
