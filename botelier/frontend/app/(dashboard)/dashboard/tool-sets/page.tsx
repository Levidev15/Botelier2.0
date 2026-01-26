"use client";

import { useState, useEffect } from "react";
import { Wrench, Plus, Pencil, Trash2, ChevronRight, ArrowLeft, Search, X, Phone, Globe, MessageSquare, GitBranch, PhoneOff } from "lucide-react";
import { notify, confirmAction } from "@/lib/notifications";
import { useAccountContext } from "@/lib/auth/useAccountContext";

interface ToolSet {
  id: string;
  account_id: string;
  name: string;
  description: string | null;
  tool_count: number;
  created_at: string | null;
  updated_at: string | null;
}

interface Tool {
  id: string;
  tool_set_id: string | null;
  name: string;
  description: string;
  tool_type: string;
  config: Record<string, any>;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

const toolTypeIcons: Record<string, any> = {
  TRANSFER_CALL: Phone,
  API_REQUEST: Globe,
  END_CALL: PhoneOff,
  SEND_SMS: MessageSquare,
  FLOW: GitBranch,
};

const toolTypeLabels: Record<string, string> = {
  TRANSFER_CALL: "Transfer Call",
  API_REQUEST: "API Request",
  END_CALL: "End Call",
  SEND_SMS: "Send SMS",
  SEND_EMAIL: "Send Email",
  FLOW: "Conversation Flow",
};

function formatDate(dateString: string | null): string {
  if (!dateString) return "N/A";
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined });
}

export default function ToolSetsPage() {
  const { accountId, loading: contextLoading } = useAccountContext();
  
  const [toolSets, setToolSets] = useState<ToolSet[]>([]);
  const [selectedTS, setSelectedTS] = useState<ToolSet | null>(null);
  const [tools, setTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(true);
  
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingTS, setEditingTS] = useState<ToolSet | null>(null);
  
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    if (!contextLoading && accountId) {
      fetchToolSets();
    }
  }, [accountId, contextLoading]);

  const fetchToolSets = async () => {
    if (!accountId) return;
    try {
      setLoading(true);
      const res = await fetch(`/api/tool-sets?account_id=${accountId}`);
      const data = await res.json();
      setToolSets(data.tool_sets || []);
    } catch (error) {
      console.error("Failed to fetch tool sets:", error);
    } finally {
      setLoading(false);
    }
  };

  const fetchTools = async (tsId: string) => {
    try {
      setLoading(true);
      const res = await fetch(`/api/tool-sets/${tsId}/tools`);
      const data = await res.json();
      setTools(data.tools || []);
    } catch (error) {
      console.error("Failed to fetch tools:", error);
    } finally {
      setLoading(false);
    }
  };

  const selectToolSet = (ts: ToolSet) => {
    setSelectedTS(ts);
    fetchTools(ts.id);
  };

  const goBack = () => {
    setSelectedTS(null);
    setTools([]);
    setSearchQuery("");
  };

  const handleDeleteTS = async (ts: ToolSet) => {
    const confirmed = await confirmAction(
      "Delete Tool Set",
      `Are you sure you want to delete "${ts.name}"? This will permanently delete all ${ts.tool_count} tools.`
    );
    if (!confirmed) return;

    try {
      const res = await fetch(`/api/tool-sets/${ts.id}`, { method: "DELETE" });
      if (res.ok) {
        notify.success("Tool set deleted");
        fetchToolSets();
      } else {
        notify.error("Failed to delete tool set");
      }
    } catch (error) {
      notify.error("Failed to delete tool set");
    }
  };

  const filteredTools = tools.filter(t => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q) || t.tool_type.toLowerCase().includes(q);
  });

  if (contextLoading || loading) {
    return (
      <div className="p-6">
        <div className="flex items-center justify-center h-64">
          <div className="text-white/60">Loading...</div>
        </div>
      </div>
    );
  }

  if (selectedTS) {
    return (
      <div className="p-6">
        <div className="flex items-center gap-4 mb-6">
          <button onClick={goBack} className="p-2 hover:bg-white/5 rounded-lg transition-colors">
            <ArrowLeft className="w-5 h-5 text-white/60" />
          </button>
          <div className="flex-1">
            <h1 className="text-2xl font-semibold text-white">{selectedTS.name}</h1>
            <p className="text-white/60 text-sm">{selectedTS.description || "Tool set"}</p>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
              <input
                type="text"
                placeholder="Search tools..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10 pr-4 py-2 bg-[#2A2A2A] border border-white/10 rounded-lg text-white placeholder:text-white/40 focus:outline-none focus:border-[#22C55E]/50 w-64"
              />
            </div>
          </div>
        </div>

        {filteredTools.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Wrench className="w-12 h-12 text-white/20 mb-4" />
            <h3 className="text-lg font-medium text-white/80 mb-2">No tools in this set</h3>
            <p className="text-white/40 text-sm mb-4">Tools can be added from the Tools page</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredTools.map((tool) => {
              const Icon = toolTypeIcons[tool.tool_type] || Wrench;
              return (
                <div key={tool.id} className="bg-[#1A1A1A] border border-white/10 rounded-xl p-4 hover:border-white/20 transition-colors">
                  <div className="flex items-start gap-3">
                    <div className="p-2 bg-[#22C55E]/10 rounded-lg shrink-0">
                      <Icon className="w-5 h-5 text-[#22C55E]" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="text-white font-medium truncate">{tool.name}</h3>
                      <p className="text-white/60 text-sm line-clamp-2 mt-1">{tool.description}</p>
                      <div className="flex items-center gap-2 mt-3">
                        <span className="inline-flex items-center px-2 py-1 bg-white/5 text-white/60 text-xs rounded-full">
                          {toolTypeLabels[tool.tool_type] || tool.tool_type}
                        </span>
                        {!tool.is_active && (
                          <span className="inline-flex items-center px-2 py-1 bg-yellow-500/10 text-yellow-400 text-xs rounded-full">
                            Inactive
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-white">Tool Sets</h1>
          <p className="text-white/60 text-sm mt-1">Manage action tools for your AI assistants</p>
        </div>
        <button onClick={() => setShowCreateModal(true)} className="flex items-center gap-2 px-4 py-2 bg-[#22C55E] hover:bg-[#22C55E]/80 text-black font-medium rounded-lg transition-colors">
          <Plus className="w-4 h-4" />
          Create Tool Set
        </button>
      </div>

      {toolSets.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Wrench className="w-12 h-12 text-white/20 mb-4" />
          <h3 className="text-lg font-medium text-white/80 mb-2">No tool sets yet</h3>
          <p className="text-white/40 text-sm mb-4">Create a tool set to organize actions for your assistants</p>
          <button onClick={() => setShowCreateModal(true)} className="flex items-center gap-2 px-4 py-2 bg-[#22C55E] hover:bg-[#22C55E]/80 text-black font-medium rounded-lg transition-colors">
            <Plus className="w-4 h-4" />
            Create First Tool Set
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {toolSets.map((ts) => (
            <div key={ts.id} onClick={() => selectToolSet(ts)} className="bg-[#1A1A1A] border border-white/10 rounded-xl p-5 hover:border-[#22C55E]/50 transition-colors cursor-pointer group">
              <div className="flex items-start justify-between mb-3">
                <div className="p-2 bg-[#22C55E]/10 rounded-lg">
                  <Wrench className="w-5 h-5 text-[#22C55E]" />
                </div>
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
                  <button onClick={(e) => { e.stopPropagation(); setEditingTS(ts); setShowCreateModal(true); }} className="p-1.5 hover:bg-white/5 rounded">
                    <Pencil className="w-4 h-4 text-white/60" />
                  </button>
                  <button onClick={(e) => { e.stopPropagation(); handleDeleteTS(ts); }} className="p-1.5 hover:bg-red-500/20 rounded">
                    <Trash2 className="w-4 h-4 text-red-400" />
                  </button>
                </div>
              </div>
              <h3 className="text-white font-medium text-lg mb-1">{ts.name}</h3>
              <p className="text-white/60 text-sm mb-4 line-clamp-2">{ts.description || "No description"}</p>
              <div className="flex items-center justify-between">
                <span className="text-white/40 text-sm">{ts.tool_count} tools</span>
                <ChevronRight className="w-4 h-4 text-white/40 group-hover:text-[#22C55E] transition-colors" />
              </div>
            </div>
          ))}
        </div>
      )}

      {showCreateModal && (
        <TSModal
          ts={editingTS}
          accountId={accountId!}
          onClose={() => { setShowCreateModal(false); setEditingTS(null); }}
          onSave={() => { setShowCreateModal(false); setEditingTS(null); fetchToolSets(); }}
        />
      )}
    </div>
  );
}

function TSModal({ ts, accountId, onClose, onSave }: { ts: ToolSet | null; accountId: string; onClose: () => void; onSave: () => void }) {
  const [name, setName] = useState(ts?.name || "");
  const [description, setDescription] = useState(ts?.description || "");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!name.trim()) {
      notify.error("Name is required");
      return;
    }

    try {
      setSaving(true);
      const url = ts ? `/api/tool-sets/${ts.id}` : "/api/tool-sets";
      const method = ts ? "PUT" : "POST";
      const body = ts ? { name, description } : { account_id: accountId, name, description };

      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (res.ok) {
        notify.success(ts ? "Tool set updated" : "Tool set created");
        onSave();
      } else {
        notify.error("Failed to save tool set");
      }
    } catch (error) {
      notify.error("Failed to save tool set");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-[#1A1A1A] border border-white/10 rounded-xl w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold text-white">{ts ? "Edit Tool Set" : "Create Tool Set"}</h2>
          <button onClick={onClose} className="p-1 hover:bg-white/5 rounded">
            <X className="w-5 h-5 text-white/60" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm text-white/60 mb-2">Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Front Desk Tools"
              className="w-full px-4 py-3 bg-[#2A2A2A] border border-white/10 rounded-lg text-white placeholder:text-white/40 focus:outline-none focus:border-[#22C55E]/50"
            />
          </div>
          <div>
            <label className="block text-sm text-white/60 mb-2">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What actions does this tool set enable?"
              rows={3}
              className="w-full px-4 py-3 bg-[#2A2A2A] border border-white/10 rounded-lg text-white placeholder:text-white/40 focus:outline-none focus:border-[#22C55E]/50 resize-none"
            />
          </div>
        </div>

        <div className="flex justify-end gap-3 mt-6">
          <button onClick={onClose} className="px-4 py-2 text-white/60 hover:text-white transition-colors">Cancel</button>
          <button onClick={handleSave} disabled={saving} className="px-4 py-2 bg-[#22C55E] hover:bg-[#22C55E]/80 text-black font-medium rounded-lg transition-colors disabled:opacity-50">
            {saving ? "Saving..." : ts ? "Update" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
