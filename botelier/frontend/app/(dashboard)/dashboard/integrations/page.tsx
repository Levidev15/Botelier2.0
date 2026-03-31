"use client";

import { useState, useEffect } from "react";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { confirmAction } from "@/lib/notifications";
import { 
  Plug, 
  Check, 
  AlertCircle, 
  ExternalLink,
  RefreshCw,
  Loader2,
  X,
  ChevronRight,
  Plus,
  Server,
  Trash2,
  Pencil,
  Wrench,
  KeyRound,
  Eye,
  EyeOff
} from "lucide-react";

interface AccountSecret {
  id: string;
  key: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

interface IntegrationType {
  id: string;
  slug: string;
  name: string;
  description: string;
  logo_url: string | null;
  provider: string;
  auth_type: string;
  documentation_url: string | null;
  is_enabled: boolean;
  required_fields: RequiredField[];
}

interface RequiredField {
  key: string;
  label: string;
  type: string;
  placeholder?: string;
  description?: string;
  required: boolean;
  options?: string[];
  option_labels?: Record<string, string>;
  show_when?: Record<string, string>;
}

interface AccountIntegration {
  id: string;
  integration_type_id: string;
  integration_slug: string;
  integration_name: string;
  connection_name: string | null;
  status: string;
  connected_at: string | null;
  last_sync_at: string | null;
  last_error: string | null;
}

interface MCPConnection {
  id: string;
  account_id: string;
  name: string;
  description: string | null;
  transport_type: string;
  server_url: string;
  auth_type: string;
  status: string;
  last_connected_at: string | null;
  last_error: string | null;
  is_active: boolean;
  discovered_tools: MCPTool[];
  created_at: string;
  updated_at: string | null;
}

interface MCPTool {
  name: string;
  description: string;
  parameters: {
    type: string;
    properties: Record<string, unknown>;
    required: string[];
  };
  source: string;
}

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

  const getMcpStatusBadge = (status: string) => {
    switch (status) {
      case "connected":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-900/50 text-green-400 border border-green-700">
            <Check className="h-3 w-3 mr-1" />
            Connected
          </span>
        );
      case "error":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-900/50 text-red-400 border border-red-700">
            <AlertCircle className="h-3 w-3 mr-1" />
            Error
          </span>
        );
      case "connecting":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-900/50 text-yellow-400 border border-yellow-700">
            <Loader2 className="h-3 w-3 mr-1 animate-spin" />
            Connecting
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-800 text-gray-400 border border-gray-700">
            Not Tested
          </span>
        );
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

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "connected":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-900/50 text-green-400 border border-green-700">
            <span className="w-2 h-2 rounded-full bg-green-400 mr-1.5 animate-pulse" />
            Connected
          </span>
        );
      case "error":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-900/50 text-red-400 border border-red-700">
            <span className="w-2 h-2 rounded-full bg-red-400 mr-1.5" />
            Error
          </span>
        );
      case "token_expired":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-900/50 text-amber-400 border border-amber-700">
            <AlertCircle className="h-3 w-3 mr-1" />
            Token Expired
          </span>
        );
      case "connecting":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-900/50 text-yellow-400 border border-yellow-700">
            <Loader2 className="h-3 w-3 mr-1 animate-spin" />
            Connecting
          </span>
        );
      case "disconnected":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-800 text-gray-400 border border-gray-700">
            <span className="w-2 h-2 rounded-full bg-gray-500 mr-1.5" />
            Disconnected
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-800 text-gray-400 border border-gray-700">
            {status.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
          </span>
        );
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
        {integrationTypes.map((type) => {
          const connections = getIntegrationConnections(type.id);
          const slugInitials = type.slug === "opera-cloud" ? "OC" : type.slug === "guestcentric-crs" ? "GC" : type.name.slice(0, 2).toUpperCase();
          const gradientClass = type.slug === "opera-cloud" ? "from-orange-500 to-red-600" : "from-emerald-500 to-teal-600";

          return (
            <div
              key={type.id}
              className="bg-[#141414] border border-gray-800 rounded-lg p-6 hover:border-gray-700 transition"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-4">
                  <div className={`w-12 h-12 bg-gradient-to-br ${gradientClass} rounded-lg flex items-center justify-center text-white font-bold text-lg`}>
                    {slugInitials}
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold">{type.name}</h3>
                    <p className="text-sm text-gray-400 mt-1 max-w-lg">
                      {type.description}
                    </p>
                    {type.documentation_url && (
                      <a
                        href={type.documentation_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center text-xs text-blue-400 hover:text-blue-300 mt-2"
                      >
                        View Documentation
                        <ExternalLink className="h-3 w-3 ml-1" />
                      </a>
                    )}
                  </div>
                </div>

                <button
                  onClick={() => handleConnect(type)}
                  className="inline-flex items-center px-4 py-1.5 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition"
                >
                  <Plus className="h-4 w-4 mr-1" />
                  Add Connection
                </button>
              </div>

              {connections.length > 0 && (
                <div className="mt-4 space-y-2 border-t border-gray-800 pt-4">
                  {connections.map((conn) => (
                    <div
                      key={conn.id}
                      className="flex items-center justify-between bg-[#0a0a0a] border border-gray-800 rounded-lg px-4 py-3"
                    >
                      <div className="flex items-center gap-3">
                        <Plug className="h-4 w-4 text-gray-500" />
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">{conn.connection_name || conn.integration_name}</span>
                            {getStatusBadge(conn.status)}
                          </div>
                          {conn.last_error && (
                            <p className="text-xs text-red-400 mt-0.5">{conn.last_error}</p>
                          )}
                          {integrationStats[conn.id] && (() => {
                            const s = integrationStats[conn.id];
                            return (
                              <div className="flex items-center gap-3 mt-1.5">
                                <span className="text-xs text-gray-500">
                                  <span className="text-green-400 font-medium">{s.successful_calls}</span>/{s.total_calls} calls OK
                                </span>
                                {s.failed_calls > 0 && (
                                  <span className="text-xs text-red-400">{s.failed_calls} failed</span>
                                )}
                                {s.last_called_at && (
                                  <span className="text-xs text-gray-600">
                                    Last: {new Date(s.last_called_at).toLocaleDateString()}
                                  </span>
                                )}
                                {s.last_error && (
                                  <span className="text-xs text-red-400 truncate max-w-[200px]" title={s.last_error}>
                                    {s.last_error}
                                  </span>
                                )}
                              </div>
                            );
                          })()}
                          {conn.connected_at && (
                            <p className="text-xs text-gray-500 mt-0.5">
                              Connected {new Date(conn.connected_at).toLocaleDateString()}
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleTestConnection(conn)}
                          disabled={testing === conn.id}
                          className="px-2.5 py-1 text-sm text-gray-300 bg-gray-800 hover:bg-gray-700 rounded-lg transition disabled:opacity-50"
                          title="Test connection"
                        >
                          {testing === conn.id ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <RefreshCw className="h-3.5 w-3.5" />
                          )}
                        </button>
                        <button
                          onClick={() => handleDisconnect(conn)}
                          className="px-2.5 py-1 text-sm text-red-400 hover:text-red-300 bg-gray-800 hover:bg-gray-700 rounded-lg transition"
                          title="Remove connection"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}

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
            <div
              key={mcp.id}
              className="bg-[#141414] border border-gray-800 rounded-lg p-6 hover:border-gray-700 transition"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-4">
                  <div className="w-12 h-12 bg-gradient-to-br from-purple-500 to-blue-600 rounded-lg flex items-center justify-center text-white">
                    <Server className="h-6 w-6" />
                  </div>
                  <div>
                    <div className="flex items-center gap-3">
                      <h3 className="text-lg font-semibold">{mcp.name}</h3>
                      {getMcpStatusBadge(mcp.status)}
                      {!mcp.is_active && (
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-800 text-gray-500">
                          Inactive
                        </span>
                      )}
                    </div>
                    {mcp.description && (
                      <p className="text-sm text-gray-400 mt-1">{mcp.description}</p>
                    )}
                    <p className="text-xs text-gray-500 mt-2 font-mono">{mcp.server_url}</p>
                    {mcp.last_error && (
                      <p className="text-xs text-red-400 mt-1">Error: {mcp.last_error}</p>
                    )}
                    {mcp.discovered_tools && mcp.discovered_tools.length > 0 && (
                      <div className="mt-3">
                        <p className="text-xs text-gray-500 mb-1 flex items-center gap-1">
                          <Wrench className="h-3 w-3" />
                          {mcp.discovered_tools.length} tool{mcp.discovered_tools.length !== 1 ? "s" : ""} available
                        </p>
                        <div className="flex flex-wrap gap-1">
                          {mcp.discovered_tools.slice(0, 5).map((tool) => (
                            <span
                              key={tool.name}
                              className="px-2 py-0.5 text-xs bg-gray-800 text-gray-300 rounded"
                              title={tool.description}
                            >
                              {tool.name}
                            </span>
                          ))}
                          {mcp.discovered_tools.length > 5 && (
                            <span className="px-2 py-0.5 text-xs text-gray-500">
                              +{mcp.discovered_tools.length - 5} more
                            </span>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleTestMcp(mcp)}
                    disabled={testingMcp === mcp.id}
                    className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition disabled:opacity-50"
                    title="Test Connection"
                  >
                    {testingMcp === mcp.id ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <RefreshCw className="h-4 w-4" />
                    )}
                  </button>
                  <button
                    onClick={() => handleEditMcp(mcp)}
                    className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition"
                    title="Edit"
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => handleDeleteMcp(mcp)}
                    className="p-2 text-gray-400 hover:text-red-400 hover:bg-gray-800 rounded-lg transition"
                    title="Delete"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </div>
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
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-[#1a1a1a] border border-gray-800 rounded-xl w-full max-w-md">
            <div className="flex items-center justify-between p-4 border-b border-gray-800">
              <h2 className="text-lg font-semibold">
                {editingSecret ? "Edit Secret" : "Add Secret"}
              </h2>
              <button onClick={() => setShowSecretModal(false)} className="p-1 hover:bg-gray-800 rounded-lg transition">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-5 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  Name <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  placeholder="My API Key"
                  value={secretForm.name}
                  onChange={(e) => setSecretForm(prev => ({ ...prev, name: e.target.value }))}
                  className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  Key <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  placeholder="my_api_key"
                  value={secretForm.key}
                  disabled={!!editingSecret}
                  onChange={(e) => setSecretForm(prev => ({ ...prev, key: e.target.value.replace(/[^a-zA-Z0-9_]/g, "_") }))}
                  className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm font-mono disabled:opacity-50"
                />
                <p className="text-xs text-gray-500 mt-1">
                  Used as <code className="text-blue-400">{`{{secrets.${secretForm.key || "key_name"}}}`}</code> in flows
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">Description</label>
                <input
                  type="text"
                  placeholder="Optional description"
                  value={secretForm.description}
                  onChange={(e) => setSecretForm(prev => ({ ...prev, description: e.target.value }))}
                  className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  Value {!editingSecret && <span className="text-red-400">*</span>}
                  {editingSecret && <span className="text-gray-500 font-normal"> (leave blank to keep current)</span>}
                </label>
                <div className="relative">
                  <input
                    type={showSecretValue ? "text" : "password"}
                    placeholder="••••••••"
                    value={secretForm.value}
                    onChange={(e) => setSecretForm(prev => ({ ...prev, value: e.target.value }))}
                    className="w-full px-3 py-2 pr-10 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowSecretValue(v => !v)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                  >
                    {showSecretValue ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>
            </div>
            <div className="flex items-center justify-end gap-3 p-4 border-t border-gray-800">
              <button
                onClick={() => setShowSecretModal(false)}
                className="px-4 py-2 text-sm font-medium text-gray-300 hover:text-white transition"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveSecret}
                disabled={savingSecret}
                className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition disabled:opacity-50"
              >
                {savingSecret ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
                {editingSecret ? "Update Secret" : "Save Secret"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MCP Connection Modal */}
      {showMcpModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-[#1a1a1a] border border-gray-800 rounded-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between p-4 border-b border-gray-800">
              <h2 className="text-lg font-semibold">
                {editingMcp ? "Edit MCP Connection" : "Add MCP Connection"}
              </h2>
              <button
                onClick={() => setShowMcpModal(false)}
                className="p-1 hover:bg-gray-800 rounded-lg transition"
              >
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
                  value={mcpForm.name}
                  onChange={(e) => setMcpForm(prev => ({ ...prev, name: e.target.value }))}
                  className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  Description
                </label>
                <input
                  type="text"
                  placeholder="Optional description"
                  value={mcpForm.description}
                  onChange={(e) => setMcpForm(prev => ({ ...prev, description: e.target.value }))}
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
                  value={mcpForm.server_url}
                  onChange={(e) => setMcpForm(prev => ({ ...prev, server_url: e.target.value }))}
                  className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm font-mono"
                />
                <p className="text-xs text-gray-500 mt-1">
                  The SSE endpoint of your MCP server
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  Authentication
                </label>
                <select
                  value={mcpForm.auth_type}
                  onChange={(e) => setMcpForm(prev => ({ ...prev, auth_type: e.target.value }))}
                  className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                >
                  <option value="none">No Authentication</option>
                  <option value="api_key">API Key</option>
                  <option value="bearer">Bearer Token</option>
                </select>
              </div>

              {mcpForm.auth_type === "api_key" && (
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-1">
                    API Key
                  </label>
                  <input
                    type="password"
                    placeholder={editingMcp ? "Leave empty to keep existing" : "Enter API key"}
                    value={mcpForm.api_key}
                    onChange={(e) => setMcpForm(prev => ({ ...prev, api_key: e.target.value }))}
                    className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                  />
                </div>
              )}

              {mcpForm.auth_type === "bearer" && (
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-1">
                    Bearer Token
                  </label>
                  <input
                    type="password"
                    placeholder={editingMcp ? "Leave empty to keep existing" : "Enter token"}
                    value={mcpForm.token}
                    onChange={(e) => setMcpForm(prev => ({ ...prev, token: e.target.value }))}
                    className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                  />
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-3 p-4 border-t border-gray-800">
              <button
                onClick={() => setShowMcpModal(false)}
                className="px-4 py-2 text-sm font-medium text-gray-300 hover:text-white transition"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveMcp}
                disabled={connecting}
                className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition disabled:opacity-50"
              >
                {connecting ? (
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
      )}

      {showConnectModal && selectedType && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-[#1a1a1a] border border-gray-800 rounded-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between p-4 border-b border-gray-800">
              <h2 className="text-lg font-semibold">Connect {selectedType.name}</h2>
              <button
                onClick={() => setShowConnectModal(false)}
                className="p-1 hover:bg-gray-800 rounded-lg transition"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <p className="text-sm text-gray-400">
                Enter your credentials to connect to {selectedType.name}. 
                Your credentials are encrypted and stored securely.
              </p>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  Connection Name <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  placeholder={`e.g., ${selectedType.name} - Hotel Name`}
                  value={credentials["_connection_name"] || ""}
                  onChange={(e) => setCredentials(prev => ({ ...prev, _connection_name: e.target.value }))}
                  className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                />
                <p className="text-xs text-gray-500 mt-1">A label to identify this connection (e.g., hotel or property name)</p>
              </div>

              {selectedType.required_fields.map((field) => {
                if (field.show_when) {
                  const shouldShow = Object.entries(field.show_when).every(
                    ([key, value]) => (credentials[key] || selectedType.required_fields.find(f => f.key === key)?.options?.[0]) === value
                  );
                  if (!shouldShow) return null;
                }

                return (
                  <div key={field.key}>
                    <label className="block text-sm font-medium text-gray-300 mb-1">
                      {field.label}
                      {field.required && <span className="text-red-400 ml-1">*</span>}
                    </label>
                    {field.type === "select" && field.options ? (
                      <select
                        value={credentials[field.key] || field.options[0] || ""}
                        onChange={(e) => setCredentials(prev => ({ ...prev, [field.key]: e.target.value }))}
                        className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                      >
                        {field.options.map((opt) => (
                          <option key={opt} value={opt}>
                            {field.option_labels?.[opt] || opt.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type={field.type === "password" ? "password" : "text"}
                        placeholder={field.placeholder}
                        value={credentials[field.key] || ""}
                        onChange={(e) => setCredentials(prev => ({ ...prev, [field.key]: e.target.value }))}
                        className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                      />
                    )}
                    {field.description && (
                      <p className="text-xs text-gray-500 mt-1">{field.description}</p>
                    )}
                  </div>
                );
              })}

              {connectError && (
                <div className="flex items-start gap-2 p-3 bg-red-900/30 border border-red-800 rounded-lg">
                  <AlertCircle className="h-4 w-4 text-red-400 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-red-300">{connectError}</p>
                </div>
              )}

              {selectedType.documentation_url && (
                <a
                  href={selectedType.documentation_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center text-sm text-blue-400 hover:text-blue-300"
                >
                  Need help finding your credentials?
                  <ExternalLink className="h-3 w-3 ml-1" />
                </a>
              )}
            </div>

            <div className="flex items-center justify-end gap-3 p-4 border-t border-gray-800">
              <button
                onClick={() => { setShowConnectModal(false); setConnectError(null); }}
                className="px-4 py-2 text-sm font-medium text-gray-300 hover:text-white transition"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmitConnect}
                disabled={connecting}
                className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition disabled:opacity-50"
              >
                {connecting ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Connecting...
                  </>
                ) : (
                  "Connect Integration"
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
