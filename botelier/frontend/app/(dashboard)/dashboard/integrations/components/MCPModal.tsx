"use client";

import { useMemo, useState } from "react";
import { AlertCircle, Loader2, ShieldCheck, X } from "lucide-react";
import type { MCPConnection } from "../types";
import { buildMCPGrantConnectionConfig, displayMCPServerHost, type MCPGrantScope } from "@/components/mcpNativePolicy";

interface MCPModalProps {
  editingMcp: MCPConnection | null;
  accountId: string;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
  canManage: boolean;
  onSuccess: () => void;
  onClose: () => void;
}

const defaultForm = {
  name: "",
  description: "",
  server_url: "",
  transport_type: "sse",
  auth_type: "none",
  api_key: "",
  token: "",
};

export default function MCPModal({
  editingMcp,
  accountId,
  authFetch,
  canManage,
  onSuccess,
  onClose,
}: MCPModalProps) {
  const [form, setForm] = useState(() =>
    editingMcp
      ? { name: editingMcp.name, description: editingMcp.description || "", server_url: "", transport_type: editingMcp.transport_type || "sse", auth_type: editingMcp.auth_type, api_key: "", token: "" }
      : defaultForm
  );
  const [saving, setSaving] = useState(false);
  const existingPolicy = editingMcp?.native_flow_policy;
  const [grantScope, setGrantScope] = useState<MCPGrantScope>(
    existingPolicy?.scope === "property" ? "property" : "account",
  );
  const [propertyId, setPropertyId] = useState(existingPolicy?.property_id ?? "");
  const [enabledTools, setEnabledTools] = useState<string[]>(() =>
    (existingPolicy?.enabled_tools ?? []).filter((name) =>
      editingMcp?.discovered_tools?.some((tool) => tool.name === name),
    ),
  );
  const [readOnlyTools, setReadOnlyTools] = useState<string[]>(() =>
    (existingPolicy?.read_only_tools ?? []).filter((name) => enabledTools.includes(name)),
  );
  const [submitFreshGrant, setSubmitFreshGrant] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const toolNames = useMemo(
    () => Array.from(new Set((editingMcp?.discovered_tools ?? []).map((tool) => tool.name).filter(Boolean))),
    [editingMcp],
  );
  const sensitiveConfigChanged = !!editingMcp && (
    (!!form.server_url.trim() && form.server_url.trim() !== editingMcp.server_url) ||
    form.transport_type !== (editingMcp.transport_type || "sse") ||
    form.auth_type !== editingMcp.auth_type ||
    !!form.api_key ||
    !!form.token
  );

  const handleSave = async () => {
    if (!form.name.trim() || (canManage && !editingMcp && !form.server_url.trim())) {
      setSaveError("Name and Server URL are required.");
      return;
    }
    if (!canManage && !editingMcp) return;
    const grant = submitFreshGrant
      ? buildMCPGrantConnectionConfig({ scope: grantScope, propertyId, enabledTools, readOnlyTools })
      : null;
    if (grant && !grant.ok) {
      setSaveError(grant.error);
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const credentials: Record<string, string> = {};
      if (form.auth_type === "api_key" && form.api_key) {
        credentials.api_key = form.api_key;
      } else if (form.auth_type === "bearer" && form.token) {
        credentials.token = form.token;
      }

      const payload: Record<string, unknown> = {
        account_id: accountId,
        name: form.name.trim(),
        description: form.description.trim() || null,
      };
      if (canManage) {
        if (!editingMcp) {
          Object.assign(payload, {
            server_url: form.server_url.trim(),
            transport_type: form.transport_type,
            auth_type: form.auth_type,
            credentials: Object.keys(credentials).length > 0 ? credentials : null,
          });
        } else if (sensitiveConfigChanged) {
          if (form.server_url.trim() && form.server_url.trim() !== editingMcp.server_url) payload.server_url = form.server_url.trim();
          if (form.transport_type !== (editingMcp.transport_type || "sse")) payload.transport_type = form.transport_type;
          if (form.auth_type !== editingMcp.auth_type) {
            payload.auth_type = form.auth_type;
            payload.credentials = Object.keys(credentials).length > 0 ? credentials : null;
          } else if (Object.keys(credentials).length > 0) {
            payload.credentials = credentials;
          }
        }
        if (grant?.ok) payload.connection_config = grant.connectionConfig;
      }

      const url = editingMcp ? `/api/mcp-connections/${editingMcp.id}` : "/api/mcp-connections";
      const method = editingMcp ? "PUT" : "POST";
      const response = await authFetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (response.ok) {
        onSuccess();
        onClose();
      } else {
        setSaveError(`Could not save the MCP connection (request ${response.status}). Check the fields and your permission.`);
      }
    } catch {
      setSaveError("Could not save the MCP connection. Check your access and try again.");
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
          <button type="button" onClick={onClose} className="p-1 hover:bg-gray-800 rounded-lg transition">
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
              disabled={saving}
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
              disabled={saving}
              className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Server URL <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              placeholder={editingMcp
                ? `Current host: ${displayMCPServerHost(editingMcp.server_url)} · enter a new URL to rebind`
                : form.transport_type === "streamable_http" ? "https://your-mcp-server.com/api/mcp" : "https://your-mcp-server.com/sse"}
              value={form.server_url}
              onChange={(e) => setForm(prev => ({ ...prev, server_url: e.target.value }))}
              disabled={!canManage || saving}
              className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm font-mono"
            />
            {editingMcp && (
              <p className="mt-1 text-[10px] text-gray-500">
                Leave blank to retain the saved endpoint. Its path and query are not shown here.
              </p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Transport</label>
            <div className="flex gap-3">
              {([
                { value: "streamable_http", label: "Streamable HTTP", hint: "Recommended for newer MCP servers" },
                { value: "sse", label: "SSE", hint: "Server-Sent Events endpoint" },
              ] as const).map(({ value, label, hint }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setForm(prev => ({ ...prev, transport_type: value }))}
                  disabled={!canManage || saving}
                  className={`flex-1 px-3 py-2 rounded-lg border text-sm text-left transition ${
                    form.transport_type === value
                      ? "border-blue-500 bg-blue-600/10 text-white"
                      : "border-gray-700 bg-[#0a0a0a] text-gray-400 hover:border-gray-600"
                  }`}
                >
                  <div className="font-medium">{label}</div>
                  <div className="text-xs opacity-60 mt-0.5">{hint}</div>
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Authentication</label>
            <select
              value={form.auth_type}
              onChange={(e) => setForm(prev => ({ ...prev, auth_type: e.target.value }))}
              disabled={!canManage || saving}
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
                disabled={!canManage || saving}
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
                disabled={!canManage || saving}
                className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
              />
            </div>
          )}

          {!canManage && (
            <p className="rounded-lg border border-gray-800 bg-[#111111] px-3 py-2 text-xs text-gray-400">
              Read-only server access. You may update the connection name and description; server, transport, authentication and Flow grants require integrations.manage.
            </p>
          )}

          {canManage && (
            <section className="space-y-3 rounded-lg border border-emerald-900/50 bg-emerald-950/10 p-3">
              <div className="flex items-start gap-2">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
                <div>
                  <h3 className="text-sm font-medium text-emerald-200">Native Flow tool access</h3>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-gray-400">
                    A stored grant is not proof of current runtime authorization. The server checks scope and permission again for each native flow action.
                  </p>
                </div>
              </div>
              {existingPolicy?.configured && (
                <p className="text-[11px] text-emerald-200/80">
                  Stored grant: {existingPolicy.scope === "account" ? "account-wide" : `property-scoped${existingPolicy.property_id ? ` · ${existingPolicy.property_id}` : ""}`} · {existingPolicy.enabled_tools.length} enabled · runtime readiness not implied.
                </p>
              )}
              {editingMcp && sensitiveConfigChanged && (
                <p role="alert" className="text-[11px] text-amber-300">
                  This server/transport/authentication change revokes the previous native grant unless you explicitly submit a fresh one below.
                </p>
              )}
              <label className="flex items-start gap-2 text-xs text-gray-200">
                <input
                  type="checkbox"
                  checked={submitFreshGrant}
                  onChange={(event) => setSubmitFreshGrant(event.target.checked)}
                  disabled={saving}
                  className="mt-0.5 accent-emerald-500"
                />
                <span>Submit a fresh native Flow grant with this save</span>
              </label>
              {submitFreshGrant && (
                <div className="space-y-3 border-t border-emerald-900/40 pt-3">
                  <fieldset className="space-y-2">
                    <legend className="mb-1 text-xs font-medium text-gray-300">Grant scope</legend>
                    <label className="flex items-center gap-2 text-xs text-gray-300">
                      <input type="radio" checked={grantScope === "account"} onChange={() => setGrantScope("account")} className="accent-emerald-500" />
                      Account-global
                    </label>
                    <label className="flex items-center gap-2 text-xs text-gray-300">
                      <input type="radio" checked={grantScope === "property"} onChange={() => setGrantScope("property")} className="accent-emerald-500" />
                      One property
                    </label>
                  </fieldset>
                  {grantScope === "property" && (
                    <label className="block text-xs text-gray-300">
                      Property ID
                      <input
                        value={propertyId}
                        onChange={(event) => setPropertyId(event.target.value)}
                        placeholder="Property UUID"
                        disabled={saving}
                        className="mt-1 w-full rounded border border-gray-700 bg-[#0a0a0a] px-3 py-2 font-mono text-xs text-white"
                      />
                    </label>
                  )}
                  {toolNames.length ? (
                    <div className="space-y-2">
                      <p className="text-xs font-medium text-gray-300">Discovered tools · no discovery request is made here</p>
                      {toolNames.map((toolName) => {
                        const enabled = enabledTools.includes(toolName);
                        const readOnly = readOnlyTools.includes(toolName);
                        return (
                          <div key={toolName} className="flex flex-wrap items-center justify-between gap-3 rounded border border-gray-800 bg-[#111111] px-2.5 py-2">
                            <label className="flex items-center gap-2 text-xs text-gray-200">
                              <input
                                type="checkbox"
                                checked={enabled}
                                disabled={saving}
                                onChange={() => {
                                  setEnabledTools((current) => enabled
                                    ? current.filter((name) => name !== toolName)
                                    : [...current, toolName]);
                                  if (enabled) setReadOnlyTools((current) => current.filter((name) => name !== toolName));
                                }}
                                className="accent-emerald-500"
                              />
                              <span className="font-mono">{toolName}</span>
                            </label>
                            <label className={`flex items-center gap-2 text-[11px] ${enabled ? "text-gray-400" : "text-gray-600"}`}>
                              <input
                                type="checkbox"
                                checked={readOnly}
                                disabled={!enabled || saving}
                                onChange={() => setReadOnlyTools((current) => readOnly
                                  ? current.filter((name) => name !== toolName)
                                  : [...current, toolName])}
                                className="accent-amber-500"
                              />
                              Read-only
                            </label>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-[11px] text-amber-300">
                      No stored discovered-tool catalog is available. Save the connection, then use the explicit manager-only Test action before selecting a tool grant.
                    </p>
                  )}
                </div>
              )}
            </section>
          )}
          {saveError && (
            <p role="alert" className="flex items-start gap-2 rounded border border-red-900/60 bg-red-950/20 px-3 py-2 text-xs text-red-300">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{saveError}
            </p>
          )}
        </div>

        <div className="flex items-center justify-end gap-3 p-4 border-t border-gray-800">
          <button
            onClick={onClose}
            type="button"
            className="px-4 py-2 text-sm font-medium text-gray-300 hover:text-white transition"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            type="button"
            disabled={saving || (canManage && !editingMcp && !form.server_url.trim()) || (!canManage && !editingMcp)}
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
