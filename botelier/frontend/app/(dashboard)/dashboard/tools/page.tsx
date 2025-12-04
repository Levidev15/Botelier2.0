"use client";

import { useState, useEffect } from "react";
import { Plus, Phone, Globe, PhoneOff, Mail, MessageSquare, GitBranch } from "lucide-react";
import ToolCard from "./components/ToolCard";
import ToolDrawer from "./components/ToolDrawer";

const HOTEL_ID = "6b410bcc-f843-40df-b32d-078d3e01ac7f";

interface Tool {
  id: string;
  name: string;
  description: string;
  tool_type: string;
  config: any;
  is_active: boolean;
  created_at: string;
}

export default function ToolsPage() {
  const [tools, setTools] = useState<Tool[]>([]);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [editingTool, setEditingTool] = useState<Tool | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchTools();
  }, []);

  const fetchTools = async () => {
    try {
      const response = await fetch(`/api/tools?hotel_id=${HOTEL_ID}`);
      const data = await response.json();
      setTools(data.tools || []);
    } catch (error) {
      console.error("Failed to fetch tools:", error);
      setTools([]);
    } finally {
      setLoading(false);
    }
  };

  const handleToolCreated = (newTool: Tool) => {
    setTools([...tools, newTool]);
    setIsDrawerOpen(false);
    setEditingTool(null);
  };

  const handleToolUpdated = (updatedTool: Tool) => {
    setTools(tools.map(t => t.id === updatedTool.id ? updatedTool : t));
    setIsDrawerOpen(false);
    setEditingTool(null);
  };

  const handleToolDeleted = (toolId: string) => {
    setTools(tools.filter(t => t.id !== toolId));
  };

  const handleEditTool = (tool: Tool) => {
    setEditingTool(tool);
    setIsDrawerOpen(true);
  };

  const handleCloseDrawer = () => {
    setIsDrawerOpen(false);
    setEditingTool(null);
  };

  const getToolIcon = (toolType: string) => {
    switch (toolType) {
      case "FLOW":
        return GitBranch;
      case "TRANSFER_CALL":
        return Phone;
      case "API_REQUEST":
        return Globe;
      case "END_CALL":
        return PhoneOff;
      case "SEND_SMS":
        return MessageSquare;
      case "SEND_EMAIL":
        return Mail;
      default:
        return Globe;
    }
  };

  const getToolTypeLabel = (toolType: string) => {
    switch (toolType) {
      case "FLOW":
        return "Conversation Flow";
      case "TRANSFER_CALL":
        return "Transfer Call";
      case "API_REQUEST":
        return "API Request";
      case "END_CALL":
        return "End Call";
      case "SEND_SMS":
        return "Send SMS";
      case "SEND_EMAIL":
        return "Send Email";
      default:
        return toolType;
    }
  };

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white p-8">
      <div className="max-w-7xl mx-auto mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">Tools</h1>
            <p className="text-gray-400">
              Configure functions your AI assistant can perform during conversations
            </p>
          </div>
          <button
            onClick={() => setIsDrawerOpen(true)}
            className="flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium transition-colors"
          >
            <Plus size={20} />
            Create Tool
          </button>
        </div>
      </div>

      <div className="max-w-7xl mx-auto">
        {loading ? (
          <div className="text-center py-12 text-gray-400">
            Loading tools...
          </div>
        ) : tools.length === 0 ? (
          <div className="text-center py-12">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-gray-800 mb-4">
              <Globe className="text-gray-400" size={32} />
            </div>
            <h3 className="text-xl font-semibold mb-2">No tools yet</h3>
            <p className="text-gray-400 mb-6">
              Create your first tool to give your AI assistant new capabilities
            </p>
            <button
              onClick={() => setIsDrawerOpen(true)}
              className="inline-flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium transition-colors"
            >
              <Plus size={20} />
              Create Tool
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {tools.map((tool) => (
              <ToolCard
                key={tool.id}
                tool={tool}
                icon={getToolIcon(tool.tool_type)}
                typeLabel={getToolTypeLabel(tool.tool_type)}
                onDelete={handleToolDeleted}
                onEdit={handleEditTool}
              />
            ))}
          </div>
        )}
      </div>

      <ToolDrawer
        isOpen={isDrawerOpen}
        onClose={handleCloseDrawer}
        onToolCreated={handleToolCreated}
        onToolUpdated={handleToolUpdated}
        editTool={editingTool}
      />
    </div>
  );
}
