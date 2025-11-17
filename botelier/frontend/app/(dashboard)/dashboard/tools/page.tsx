"use client";

import { useState, useEffect } from "react";
import { Plus, Phone, Globe, PhoneOff, Mail, MessageSquare } from "lucide-react";
import ToolCard from "./components/ToolCard";
import ToolDrawer from "./components/ToolDrawer";

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
  const [loading, setLoading] = useState(true);

  // Fetch tools from backend
  useEffect(() => {
    fetchTools();
  }, []);

  const fetchTools = async () => {
    try {
      const response = await fetch("http://localhost:8000/api/tools");
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
  };

  const handleToolDeleted = (toolId: string) => {
    setTools(tools.filter(t => t.id !== toolId));
  };

  const getToolIcon = (toolType: string) => {
    switch (toolType) {
      case "transfer_call":
        return Phone;
      case "api_request":
        return Globe;
      case "end_call":
        return PhoneOff;
      case "send_sms":
        return MessageSquare;
      case "send_email":
        return Mail;
      default:
        return Globe;
    }
  };

  const getToolTypeLabel = (toolType: string) => {
    switch (toolType) {
      case "transfer_call":
        return "Transfer Call";
      case "api_request":
        return "API Request";
      case "end_call":
        return "End Call";
      case "send_sms":
        return "Send SMS";
      case "send_email":
        return "Send Email";
      default:
        return toolType;
    }
  };

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white p-8">
      {/* Header */}
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

      {/* Tools Grid */}
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
              />
            ))}
          </div>
        )}
      </div>

      {/* Tool Creation Drawer */}
      <ToolDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        onToolCreated={handleToolCreated}
      />
    </div>
  );
}
