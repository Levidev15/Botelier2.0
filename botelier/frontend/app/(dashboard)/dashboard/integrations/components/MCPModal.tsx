"use client";

import { useState } from "react";
import { Loader2, X } from "lucide-react";
import type { MCPConnection } from "../types";

interface MCPModalProps {
  editingMcp: MCPConnection | null;
  accountId: string;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
  onSuccess: () => void;
  onClose: () => void;
}

const defaultForm = {
  name: "",
  description: "",
  server_url: "",
  auth_type: "none",
  api_key: "",
  token: "",
};

export default function MCPModal({
  editingMcp,
  accountId,
  authFetch,
  onSuccess,
  onClose,
}: MCPModalProps) {
  const [form, setForm] = useState(() =>
    editingMcp
      ? { name: editingMcp.name, description: editingMcp.description || "", server_url: editingMcp.server_url, auth_type: editingMcp.auth_type, api_key: "", token: "" }
      : defaultForm
  );
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!form.name || !form.server_url) {
      alert("Name and Server URL are required");
      return;
    }
    setSaving(true);
    try {
      const credentials: Record<string, string> = {};
      if (form.auth_type === "api_key" && form.api_key) {
        credentials.api_key = form.api_key;
      } else if (form.auth_type === "bearer" && form.token) {
        credentials.token = form.token;
      }

      const payload = {
        account_id: accountId,
        name: form.name,
        description: form.description || null,
        server_url: form.server_url,
        auth_type: form.auth_type,
        credentials: Object.keys(credentials).length > 0 ? credentials : null,
      };

      const url = editingMcp ? `/api/mcp-connections/${editingMcp.id}` : "/api/mcp-connections";
      const method = editingMcp ? "PUT" : "POST";
      const response = await authFetch(url, { method, body: JSON.stringify(payload) });

      if (response.ok) {
        onSuccess();
        onClose();
      } else {
        const error = await response.json();
        alert(`Failed to save: ${error.detail || "Unknown error"}`);
      }
    } catch (error) {
      console.error("Failed to save MCP connection:", error);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-[#1a1a1a] border border-gray-800 rounded-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-gray-800">
          <h2 className="text-lg font-semibold">
            {editingMcp ? "Edit MCP Connection" : "Add MCP Connection"}
          </h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-800 rounded-lg transition">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Name <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              placeholder="My MCP Server"
              value={form.name}
              onChange={(e) => setForm(prev => ({ ...prev, name: e.target.value }))}
              className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Description</label>
            <input
              type="text"
              placeholder="Optional description"
              value={form.description}
              onChange={(e) => setForm(prev => ({ ...prev, description: e.target.value }))}
              className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Server URL <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              placeholder="https://your-mcp-server.com/sse"
              value={form.server_url}
              onChange={(e) => setForm(prev => ({ ...prev, server_url: e.target.value }))}
              className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm font-mono"
            />
            <p className="text-xs text-gray-500 mt-1">The SSE endpoint of your MCP server</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Authentication</label>
            <select
              value={form.auth_type}
              onChange={(e) => setForm(prev => ({ ...prev, auth_type: e.target.value }))}
              className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
            >
              <option value="none">No Authentication</option>
              <option value="api_key">API Key</option>
              <option value="bearer">Bearer Token</option>
            </select>
          </div>

          {form.auth_type === "api_key" && (
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">API Key</label>
              <input
                type="password"
                placeholder={editingMcp ? "Leave empty to keep existing" : "Enter API key"}
                value={form.api_key}
                onChange={(e) => setForm(prev => ({ ...prev, api_key: e.target.value }))}
                className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
              />
            </div>
          )}

          {form.auth_type === "bearer" && (
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Bearer Token</label>
              <input
                type="password"
                placeholder={editingMcp ? "Leave empty to keep existing" : "Enter token"}
                value={form.token}
                onChange={(e) => setForm(prev => ({ ...prev, token: e.target.value }))}
                className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
              />
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-3 p-4 border-t border-gray-800">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-300 hover:text-white transition"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition disabled:opacity-50"
          >
            {saving ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Saving...
              </>
            ) : (
              editingMcp ? "Update" : "Create"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
