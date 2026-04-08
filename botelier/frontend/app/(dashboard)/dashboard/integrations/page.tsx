"use client";

import { useState, useEffect } from "react";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { confirmAction } from "@/lib/notifications";
import { Check, AlertCircle, X, Loader2, Plug, Pencil, Trash2, Plus, Server, KeyRound } from "lucide-react";
import type { AccountSecret, IntegrationType, AccountIntegration, MCPConnection, IntegrationStats } from "./types";
import IntegrationCard from "./components/IntegrationCard";
import MCPConnectionCard from "./components/MCPConnectionCard";
import SecretModal from "./components/SecretModal";
import MCPModal from "./components/MCPModal";
import ConnectModal from "./components/ConnectModal";

export default function IntegrationsPage() {
  const { accountId, loading: contextLoading } = useAccountContext();
  const { authFetch, loading: authLoading, isAuthenticated } = useAuthToken();
  const [integrationTypes, setIntegrationTypes] = useState<IntegrationType[]>([]);
  const [accountIntegrations, setAccountIntegrations] = useState<AccountIntegration[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedType, setSelectedType] = useState<IntegrationType | null>(null);
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [connectError, setConnectError] = useState<string | null>(null);
  const [notification, setNotification] = useState<{ type: "success" | "error"; message: string } | null>(null);
  
  const [mcpConnections, setMcpConnections] = useState<MCPConnection[]>([]);
  const [showMcpModal, setShowMcpModal] = useState(false);
  const [editingMcp, setEditingMcp] = useState<MCPConnection | null>(null);
  const [testingMcp, setTestingMcp] = useState<string | null>(null);
  const [mcpForm, setMcpForm] = useState({
    name: "",
    description: "",
    server_url: "",
    auth_type: "none",
    api_key: "",
    token: "",
  });

  const [secrets, setSecrets] = useState<AccountSecret[]>([]);
  const [showSecretModal, setShowSecretModal] = useState(false);
  const [editingSecret, setEditingSecret] = useState<AccountSecret | null>(null);
  const [savingSecret, setSavingSecret] = useState(false);
  const [showSecretValue, setShowSecretValue] = useState(false);
  const [secretForm, setSecretForm] = useState({
    name: "",
    key: "",
    description: "",
    value: "",
  });

  const [integrationStats, setIntegrationStats] = useState<Record<string, {
    total_calls: number;
    successful_calls: number;
    failed_calls: number;
    last_called_at: string | null;
    last_error: string | null;
  }>>({});

  const showNotification = (type: "success" | "error", message: string) => {
    setNotification({ type, message });
    setTimeout(() => setNotification(null), 5000);
  };

  useEffect(() => {
    if (!contextLoading && !authLoading && isAuthenticated && accountId) {
      fetchIntegrations();
      fetchMCPConnections();
      fetchSecrets();
    }
  }, [accountId, contextLoading, authLoading, isAuthenticated]);

  const fetchIntegrationStats = async (integrations: AccountIntegration[]) => {
    const connected = integrations.filter(i => i.status === "connected");
    if (!connected.length) return;
    const results: typeof integrationStats = {};
    await Promise.allSettled(
      connected.map(async (conn) => {
        try {
          const res = await authFetch(
            `/api/integrations/account/${accountId}/integration/${conn.id}/call-stats`
          );
          if (res.ok) {
            results[conn.id] = await res.json();
          }
        } catch {
          // non-fatal
        }
      })
    );
    setIntegrationStats(prev => ({ ...prev, ...results }));
  };

  const fetchIntegrations = async () => {
    try {
      setLoading(true);
      
      const [typesRes, accountRes] = await Promise.all([
        authFetch("/api/integrations/types"),
        authFetch(`/api/integrations/account/${accountId}`)
      ]);

      if (typesRes.ok) {
        const types = await typesRes.json();
        setIntegrationTypes(types);
      }

      if (accountRes.ok) {
        const integrations = await accountRes.json();
        setAccountIntegrations(integrations);
        fetchIntegrationStats(integrations);
      } else if (accountRes.status === 401) {
        console.error("Authentication failed - please log in again");
      }
    } catch (error: any) {
      if (error?.message !== "Not authenticated") {
        console.error("Failed to fetch integrations:", error);
      }
    } finally {
      setLoading(false);
    }
  };

  const fetchMCPConnections = async () => {
    try {
      const response = await authFetch(`/api/mcp-connections?account_id=${accountId}&include_tools=true`);
      if (response.ok) {
        const connections = await response.json();
        setMcpConnections(connections);
      }
    } catch (error) {
      console.error("Failed to fetch MCP connections:", error);
    }
  };

  const fetchSecrets = async () => {
    if (!accountId) return;
    try {
      const response = await authFetch(`/api/secrets/account/${accountId}`);
      if (response.ok) {
        const data = await response.json();
        setSecrets(data);
      }
    } catch (error) {
      console.error("Failed to fetch secrets:", error);
    }
  };

  const handleCreateSecret = () => {
    setEditingSecret(null);
    setShowSecretValue(false);
    setSecretForm({ name: "", key: "", description: "", value: "" });
    setShowSecretModal(true);
  };

  const handleEditSecret = (secret: AccountSecret) => {
    setEditingSecret(secret);
    setShowSecretValue(false);
    setSecretForm({ name: secret.name, key: secret.key, description: secret.description || "", value: "" });
    setShowSecretModal(true);
  };

  const handleDeleteSecret = async (secret: AccountSecret) => {
    const confirmed = await confirmAction(`Delete secret "${secret.name}"? This will break any flows that reference {{secrets.${secret.key}}}.`);
    if (!confirmed) return;
    try {
      const res = await authFetch(`/api/secrets/account/${accountId}/${secret.id}`, { method: "DELETE" });
      if (res.ok) {
        setSecrets(prev => prev.filter(s => s.id !== secret.id));
        showNotification("success", "Secret deleted");
      } else {
        showNotification("error", "Failed to delete secret");
      }
    } catch {
      showNotification("error", "Failed to delete secret");
    }
  };

  const handleSaveSecret = async () => {
    if (!secretForm.name.trim() || !secretForm.key.trim()) {
      showNotification("error", "Name and key are required");
      return;
    }
    if (!editingSecret && !secretForm.value.trim()) {
      showNotification("error", "Value is required for a new secret");
      return;
    }
    setSavingSecret(true);
    try {
      const payload: Record<string, string> = {
        name: secretForm.name.trim(),
        key: secretForm.key.trim().replace(/\s+/g, "_"),
        description: secretForm.description.trim(),
      };
      if (secretForm.value.trim()) payload.value = secretForm.value;

      const url = editingSecret
        ? `/api/secrets/account/${accountId}/${editingSecret.id}`
        : `/api/secrets/account/${accountId}`;
      const method = editingSecret ? "PATCH" : "POST";
      const res = await authFetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        showNotification("success", editingSecret ? "Secret updated" : "Secret created");
        setShowSecretModal(false);
        fetchSecrets();
      } else {
        const err = await res.json().catch(() => ({}));
        showNotification("error", err.detail || "Failed to save secret");
      }
    } finally {
      setSavingSecret(false);
    }
  };

  const handleCreateMcp = () => {
    setEditingMcp(null);
    setMcpForm({
      name: "",
      description: "",
      server_url: "",
      auth_type: "none",
      api_key: "",
      token: "",
    });
    setShowMcpModal(true);
  };

  const handleEditMcp = (mcp: MCPConnection) => {
    setEditingMcp(mcp);
    setMcpForm({
      name: mcp.name,
      description: mcp.description || "",
      server_url: mcp.server_url,
      auth_type: mcp.auth_type,
      api_key: "",
      token: "",
    });
    setShowMcpModal(true);
  };

  const handleSaveMcp = async () => {
    if (!mcpForm.name || !mcpForm.server_url) {
      alert("Name and Server URL are required");
      return;
    }

    setConnecting(true);

    try {
      const credentials: Record<string, string> = {};
      if (mcpForm.auth_type === "api_key" && mcpForm.api_key) {
        credentials.api_key = mcpForm.api_key;
      } else if (mcpForm.auth_type === "bearer" && mcpForm.token) {
        credentials.token = mcpForm.token;
      }

      const payload = {
        account_id: accountId,
        name: mcpForm.name,
        description: mcpForm.description || null,
        server_url: mcpForm.server_url,
        auth_type: mcpForm.auth_type,
        credentials: Object.keys(credentials).length > 0 ? credentials : null,
      };

      const url = editingMcp
        ? `/api/mcp-connections/${editingMcp.id}`
        : "/api/mcp-connections";
      const method = editingMcp ? "PUT" : "POST";

      const response = await authFetch(url, {
        method,
        body: JSON.stringify(payload),
      });

      if (response.ok) {
        setShowMcpModal(false);
        fetchMCPConnections();
      } else {
        const error = await response.json();
        alert(`Failed to save: ${error.detail || "Unknown error"}`);
      }
    } catch (error) {
      console.error("Failed to save MCP connection:", error);
    } finally {
      setConnecting(false);
    }
  };

  const handleDeleteMcp = async (mcp: MCPConnection) => {
    const confirmed = await confirmAction(`Are you sure you want to delete "${mcp.name}"?`, {
      confirmText: "Delete",
    });
    if (!confirmed) return;

    try {
      const response = await authFetch(`/api/mcp-connections/${mcp.id}`, {
        method: "DELETE",
      });

      if (response.ok) {
        fetchMCPConnections();
      }
    } catch (error) {
      console.error("Failed to delete MCP connection:", error);
    }
  };

  const handleTestMcp = async (mcp: MCPConnection) => {
    setTestingMcp(mcp.id);

    try {
      const response = await authFetch(`/api/mcp-connections/${mcp.id}/test`, {
        method: "POST",
      });

      const result = await response.json();

      if (result.success) {
        fetchMCPConnections();
      } else {
        alert(`Connection failed: ${result.error}`);
        fetchMCPConnections();
      }
    } catch (error) {
      console.error("Failed to test MCP connection:", error);
    } finally {
      setTestingMcp(null);
    }
  };

  const getIntegrationConnections = (typeId: string): AccountIntegration[] => {
    return accountIntegrations.filter(i => i.integration_type_id === typeId);
  };

  const handleConnect = (type: IntegrationType) => {
    setSelectedType(type);
    setConnectError(null);
    const defaults: Record<string, string> = {};
    type.required_fields.forEach(field => {
      if (field.type === "select" && field.options && field.options.length > 0) {
        defaults[field.key] = field.options[0];
      }
    });
    setCredentials(defaults);
    setShowConnectModal(true);
  };

  const handleDisconnect = async (integration: AccountIntegration) => {
    const confirmed = await confirmAction("Are you sure you want to disconnect this integration? This will remove your stored credentials.", {
      confirmText: "Disconnect",
    });
    if (!confirmed) return;

    try {
      const response = await authFetch(
        `/api/integrations/account/${accountId}/integration/${integration.id}`,
        { method: "DELETE" }
      );

      if (response.ok) {
        showNotification("success", `${integration.connection_name || integration.integration_name} disconnected`);
        fetchIntegrations();
      } else {
        const data = await response.json().catch(() => ({}));
        showNotification("error", data.detail || "Failed to disconnect integration");
      }
    } catch (error) {
      showNotification("error", "Failed to disconnect — please try again");
    }
  };

  const handleTestConnection = async (integration: AccountIntegration) => {
    setTesting(integration.id);
    
    try {
      const response = await authFetch(
        `/api/integrations/account/${accountId}/integration/${integration.id}/test`,
        { method: "POST" }
      );

      const result = await response.json();

      if (result.success) {
        showNotification("success", `${integration.connection_name || integration.integration_name} — connection test passed`);
      } else {
        showNotification("error", result.message || result.error || "Connection test failed");
      }
      fetchIntegrations();
    } catch (error) {
      showNotification("error", "Connection test failed — please try again");
    } finally {
      setTesting(null);
    }
  };

  const handleSubmitConnect = async () => {
    if (!selectedType) return;
    setConnectError(null);

    if (!credentials["_connection_name"]?.trim()) {
      setConnectError("Please enter a connection name");
      return;
    }

    const visibleFields = selectedType.required_fields.filter(field => {
      if (!field.show_when) return true;
      return Object.entries(field.show_when).every(
        ([key, value]) => (credentials[key] || selectedType.required_fields.find(f => f.key === key)?.options?.[0]) === value
      );
    });

    const missingFields = visibleFields
      .filter(f => f.required && !credentials[f.key])
      .map(f => f.label);

    if (missingFields.length > 0) {
      setConnectError(`Missing required fields: ${missingFields.join(", ")}`);
      return;
    }

    setConnecting(true);

    const { _connection_name, ...apiCredentials } = credentials;

    try {
      const response = await authFetch(`/api/integrations/account/${accountId}/connect`, {
        method: "POST",
        body: JSON.stringify({
          integration_type_id: selectedType.id,
          credentials: apiCredentials,
          connection_name: _connection_name
        })
      });

      const result = await response.json();

      if (result.status === "connected") {
        setShowConnectModal(false);
        showNotification("success", `${_connection_name} connected successfully`);
        fetchIntegrations();
      } else if (result.status === "error" || result.last_error) {
        setConnectError(result.last_error || "Connection failed — check your credentials and try again");
        fetchIntegrations();
      } else if (result.detail) {
        setConnectError(result.detail);
      } else {
        setConnectError("Connection failed — an unexpected error occurred");
      }
    } catch (error: any) {
      setConnectError(error?.message || "Connection failed — please check your network and try again");
    } finally {
      setConnecting(false);
    }
  };

  if (loading || contextLoading || authLoading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-4xl">
      {notification && (
        <div className={`fixed top-4 right-4 z-[60] flex items-center gap-3 px-4 py-3 rounded-lg border shadow-lg transition-all ${
          notification.type === "success" 
            ? "bg-green-900/90 border-green-700 text-green-200" 
            : "bg-red-900/90 border-red-700 text-red-200"
        }`}>
          {notification.type === "success" ? (
            <Check className="h-4 w-4 flex-shrink-0" />
          ) : (
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
          )}
          <span className="text-sm">{notification.message}</span>
          <button onClick={() => setNotification(null)} className="ml-2 hover:opacity-70">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      <div className="mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Plug className="h-6 w-6" />
          Integrations
        </h1>
        <p className="text-sm text-gray-400 mt-1">
          Connect your account to third-party services to unlock additional features in your flows
        </p>
      </div>

      <div className="space-y-4">
        {integrationTypes.map((type) => (
          <IntegrationCard
            key={type.id}
            type={type}
            connections={getIntegrationConnections(type.id)}
            integrationStats={integrationStats}
            testing={testing}
            handleConnect={handleConnect}
            handleTestConnection={handleTestConnection}
            handleDisconnect={handleDisconnect}
          />
        ))}

        {integrationTypes.length === 0 && (
          <div className="bg-[#141414] border border-gray-800 rounded-lg p-12 text-center">
            <Plug className="h-12 w-12 text-gray-600 mx-auto mb-4" />
            <p className="text-gray-400">No integrations available</p>
          </div>
        )}
      </div>

      {/* MCP Connections Section */}
      <div className="mt-10">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-xl font-bold flex items-center gap-2">
              <Server className="h-5 w-5" />
              MCP Connections
            </h2>
            <p className="text-sm text-gray-400 mt-1">
              Connect to external MCP servers to enable dynamic tools for your assistants
            </p>
          </div>
          <button
            onClick={handleCreateMcp}
            className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition"
          >
            <Plus className="h-4 w-4 mr-2" />
            Add Connection
          </button>
        </div>

        <div className="space-y-4">
          {mcpConnections.map((mcp) => (
            <MCPConnectionCard
              key={mcp.id}
              mcp={mcp}
              testingMcp={testingMcp}
              handleTestMcp={handleTestMcp}
              handleEditMcp={handleEditMcp}
              handleDeleteMcp={handleDeleteMcp}
            />
          ))}

          {mcpConnections.length === 0 && (
            <div className="bg-[#141414] border border-gray-800 rounded-lg p-12 text-center">
              <Server className="h-12 w-12 text-gray-600 mx-auto mb-4" />
              <p className="text-gray-400 mb-2">No MCP connections yet</p>
              <p className="text-sm text-gray-500">
                Connect to an MCP server to provide external tools for your voice assistants
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Account Secrets Section */}
      <div className="mt-10">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-xl font-bold flex items-center gap-2">
              <KeyRound className="h-5 w-5" />
              Secrets
            </h2>
            <p className="text-sm text-gray-400 mt-1">
              Encrypted API keys and credentials — reference them in flows as{" "}
              <code className="text-xs bg-gray-800 px-1.5 py-0.5 rounded font-mono">{"{{secrets.key_name}}"}</code>
            </p>
          </div>
          <button
            onClick={handleCreateSecret}
            className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition"
          >
            <Plus className="h-4 w-4 mr-2" />
            Add Secret
          </button>
        </div>

        {secrets.length === 0 ? (
          <div className="bg-[#141414] border border-gray-800 rounded-lg p-12 text-center">
            <KeyRound className="h-12 w-12 text-gray-600 mx-auto mb-4" />
            <p className="text-gray-400 mb-2">No secrets stored yet</p>
            <p className="text-sm text-gray-500">
              Store API keys here and reference them in flows with{" "}
              <span className="font-mono text-xs">{"{{secrets.key_name}}"}</span>
            </p>
          </div>
        ) : (
          <div className="bg-[#141414] border border-gray-800 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left text-xs text-gray-500 uppercase tracking-wider">
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Key</th>
                  <th className="px-4 py-3">Description</th>
                  <th className="px-4 py-3">Created</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {secrets.map((secret) => (
                  <tr key={secret.id} className="hover:bg-gray-800/30 transition">
                    <td className="px-4 py-3 font-medium">{secret.name}</td>
                    <td className="px-4 py-3">
                      <code className="text-xs bg-gray-800 px-1.5 py-0.5 rounded font-mono text-blue-300">
                        {`{{secrets.${secret.key}}}`}
                      </code>
                    </td>
                    <td className="px-4 py-3 text-gray-400">{secret.description || "—"}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {new Date(secret.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => handleEditSecret(secret)}
                          className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition"
                          title="Edit secret"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => handleDeleteSecret(secret)}
                          className="p-1.5 text-gray-400 hover:text-red-400 hover:bg-gray-700 rounded-lg transition"
                          title="Delete secret"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Secret Modal */}
      {showSecretModal && (
        <SecretModal
          editingSecret={editingSecret}
          secretForm={secretForm}
          setSecretForm={setSecretForm}
          showSecretValue={showSecretValue}
          setShowSecretValue={setShowSecretValue}
          handleSaveSecret={handleSaveSecret}
          savingSecret={savingSecret}
          onClose={() => setShowSecretModal(false)}
        />
      )}

      {/* MCP Connection Modal */}
      {showMcpModal && (
        <MCPModal
          editingMcp={editingMcp}
          mcpForm={mcpForm}
          setMcpForm={setMcpForm}
          handleSaveMcp={handleSaveMcp}
          connecting={connecting}
          onClose={() => setShowMcpModal(false)}
        />
      )}

      {showConnectModal && selectedType && (
        <ConnectModal
          selectedType={selectedType}
          credentials={credentials}
          setCredentials={setCredentials}
          connectError={connectError}
          handleSubmitConnect={handleSubmitConnect}
          connecting={connecting}
          onClose={() => { setShowConnectModal(false); setConnectError(null); }}
        />
      )}
    </div>
  );
}
