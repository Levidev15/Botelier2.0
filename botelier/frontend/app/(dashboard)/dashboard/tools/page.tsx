"use client";

import { useState, useEffect } from "react";
import { Plus, Phone, Globe, PhoneOff, Mail, MessageSquare, GitBranch, ChevronDown, FolderPlus, X } from "lucide-react";
import ToolCard from "./components/ToolCard";
import ToolDrawer from "./components/ToolDrawer";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { notify } from "@/lib/notifications";

interface Tool {
  id: string;
  name: string;
  description: string;
  tool_type: string;
  config: any;
  is_active: boolean;
  created_at: string;
  tool_set_id: string | null;
}

interface ToolSet {
  id: string;
  name: string;
  description: string | null;
  tool_count: number;
}

export default function ToolsPage() {
  const { accountId, loading: contextLoading } = useAccountContext();
  const [tools, setTools] = useState<Tool[]>([]);
  const [toolSets, setToolSets] = useState<ToolSet[]>([]);
  const [selectedToolSet, setSelectedToolSet] = useState<ToolSet | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [editingTool, setEditingTool] = useState<Tool | null>(null);
  const [loading, setLoading] = useState(true);
  const [showToolSetDropdown, setShowToolSetDropdown] = useState(false);
  const [showCreateToolSet, setShowCreateToolSet] = useState(false);
  const [newToolSetName, setNewToolSetName] = useState("");
  const [newToolSetDescription, setNewToolSetDescription] = useState("");
  const [creatingToolSet, setCreatingToolSet] = useState(false);

  useEffect(() => {
    if (!contextLoading && accountId) {
      fetchToolSets();
    }
  }, [accountId, contextLoading]);

  useEffect(() => {
    if (selectedToolSet) {
      fetchTools(selectedToolSet.id);
    } else {
      setTools([]);
    }
  }, [selectedToolSet]);

  const fetchToolSets = async () => {
    if (!accountId) return;
    try {
      const res = await fetch(`/api/tool-sets?account_id=${accountId}`);
      const data = await res.json();
      const sets = data.tool_sets || [];
      setToolSets(sets);
      if (sets.length > 0 && !selectedToolSet) {
        setSelectedToolSet(sets[0]);
      }
    } catch (error) {
      console.error("Failed to fetch tool sets:", error);
    } finally {
      setLoading(false);
    }
  };

  const fetchTools = async (toolSetId: string) => {
    try {
      const res = await fetch(`/api/tool-sets/${toolSetId}/tools`);
      const data = await res.json();
      setTools(data.tools || []);
    } catch (error) {
      console.error("Failed to fetch tools:", error);
      setTools([]);
    }
  };

  const handleCreateToolSet = async () => {
    if (!newToolSetName.trim()) {
      notify.error("Tool set name is required");
      return;
    }
    
    try {
      setCreatingToolSet(true);
      const res = await fetch("/api/tool-sets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account_id: accountId,
          name: newToolSetName,
          description: newToolSetDescription || null,
        }),
      });
      
      if (res.ok) {
        const newSet = await res.json();
        setToolSets([...toolSets, newSet]);
        setSelectedToolSet(newSet);
        setNewToolSetName("");
        setNewToolSetDescription("");
        setShowCreateToolSet(false);
        notify.success("Tool set created");
      } else {
        notify.error("Failed to create tool set");
      }
    } catch (error) {
      notify.error("Failed to create tool set");
    } finally {
      setCreatingToolSet(false);
    }
  };

  const handleToolCreated = (newTool: Tool) => {
    setTools([...tools, newTool]);
    setIsDrawerOpen(false);
    setEditingTool(null);
    if (selectedToolSet) {
      setToolSets(toolSets.map(ts => 
        ts.id === selectedToolSet.id ? { ...ts, tool_count: ts.tool_count + 1 } : ts
      ));
    }
  };

  const handleToolUpdated = (updatedTool: Tool) => {
    setTools(tools.map(t => t.id === updatedTool.id ? updatedTool : t));
    setIsDrawerOpen(false);
    setEditingTool(null);
  };

  const handleToolDeleted = (toolId: string) => {
    setTools(tools.filter(t => t.id !== toolId));
    if (selectedToolSet) {
      setToolSets(toolSets.map(ts => 
        ts.id === selectedToolSet.id ? { ...ts, tool_count: Math.max(0, ts.tool_count - 1) } : ts
      ));
    }
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
            disabled={!selectedToolSet}
            className="flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Plus size={20} />
            Create Tool
          </button>
        </div>
      </div>

      {/* Tool Set Selector */}
      <div className="max-w-7xl mx-auto mb-6">
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-400">Tool Set:</span>
          <div className="relative">
            <button
              onClick={() => setShowToolSetDropdown(!showToolSetDropdown)}
              className="flex items-center gap-2 px-4 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg hover:border-gray-600 transition-colors min-w-[200px]"
            >
              <span className="flex-1 text-left">
                {selectedToolSet ? selectedToolSet.name : "Select a tool set..."}
              </span>
              <ChevronDown size={16} className="text-gray-400" />
            </button>
            
            {showToolSetDropdown && (
              <div className="absolute top-full left-0 mt-1 w-72 bg-[#1a1a1a] border border-gray-700 rounded-lg shadow-xl z-50">
                {toolSets.map((ts) => (
                  <button
                    key={ts.id}
                    onClick={() => {
                      setSelectedToolSet(ts);
                      setShowToolSetDropdown(false);
                    }}
                    className={`w-full px-4 py-3 text-left hover:bg-gray-800 transition-colors first:rounded-t-lg ${
                      selectedToolSet?.id === ts.id ? "bg-gray-800" : ""
                    }`}
                  >
                    <div className="font-medium">{ts.name}</div>
                    <div className="text-sm text-gray-400">{ts.tool_count} tools</div>
                  </button>
                ))}
                <button
                  onClick={() => {
                    setShowToolSetDropdown(false);
                    setShowCreateToolSet(true);
                  }}
                  className="w-full px-4 py-3 text-left hover:bg-gray-800 transition-colors border-t border-gray-700 rounded-b-lg flex items-center gap-2 text-blue-400"
                >
                  <FolderPlus size={16} />
                  Create New Tool Set
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto">
        {loading ? (
          <div className="text-center py-12 text-gray-400">
            Loading tools...
          </div>
        ) : !selectedToolSet ? (
          <div className="text-center py-12">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-gray-800 mb-4">
              <FolderPlus className="text-gray-400" size={32} />
            </div>
            <h3 className="text-xl font-semibold mb-2">No tool sets yet</h3>
            <p className="text-gray-400 mb-6">
              Create a tool set to organize your tools
            </p>
            <button
              onClick={() => setShowCreateToolSet(true)}
              className="inline-flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium transition-colors"
            >
              <FolderPlus size={20} />
              Create Tool Set
            </button>
          </div>
        ) : tools.length === 0 ? (
          <div className="text-center py-12">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-gray-800 mb-4">
              <Globe className="text-gray-400" size={32} />
            </div>
            <h3 className="text-xl font-semibold mb-2">No tools in this set</h3>
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
                hotelId={accountId}
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
        accountId={accountId}
        toolSetId={selectedToolSet?.id}
      />

      {/* Create Tool Set Modal */}
      {showCreateToolSet && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowCreateToolSet(false)}>
          <div className="bg-[#1a1a1a] border border-gray-700 rounded-xl w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-semibold">Create Tool Set</h2>
              <button onClick={() => setShowCreateToolSet(false)} className="p-1 hover:bg-gray-800 rounded">
                <X size={20} className="text-gray-400" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-400 mb-2">Name *</label>
                <input
                  type="text"
                  value={newToolSetName}
                  onChange={(e) => setNewToolSetName(e.target.value)}
                  placeholder="e.g., Front Desk Tools"
                  className="w-full px-4 py-3 bg-[#0a0a0a] border border-gray-700 rounded-lg text-white placeholder:text-gray-500 focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-2">Description</label>
                <textarea
                  value={newToolSetDescription}
                  onChange={(e) => setNewToolSetDescription(e.target.value)}
                  placeholder="What actions does this tool set enable?"
                  rows={3}
                  className="w-full px-4 py-3 bg-[#0a0a0a] border border-gray-700 rounded-lg text-white placeholder:text-gray-500 focus:outline-none focus:border-blue-500 resize-none"
                />
              </div>
            </div>

            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setShowCreateToolSet(false)} className="px-4 py-2 text-gray-400 hover:text-white transition-colors">
                Cancel
              </button>
              <button
                onClick={handleCreateToolSet}
                disabled={creatingToolSet}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium transition-colors disabled:opacity-50"
              >
                {creatingToolSet ? "Creating..." : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
