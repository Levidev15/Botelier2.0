"use client";

import { useState, useEffect } from "react";
import { useAccountContext } from "@/components/AccountContext";
import { notify } from "@/lib/notify";
import { 
  Plug, 
  Check, 
  AlertCircle, 
  ExternalLink,
  RefreshCw,
  Loader2,
  X,
  ChevronRight
} from "lucide-react";

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
  placeholder: string;
  description: string;
  required: boolean;
}

interface AccountIntegration {
  id: string;
  integration_type_id: string;
  integration_slug: string;
  integration_name: string;
  status: string;
  connected_at: string | null;
  last_sync_at: string | null;
  last_error: string | null;
}

export default function IntegrationsPage() {
  const { accountId, loading: contextLoading } = useAccountContext();
  const [integrationTypes, setIntegrationTypes] = useState<IntegrationType[]>([]);
  const [accountIntegrations, setAccountIntegrations] = useState<AccountIntegration[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedType, setSelectedType] = useState<IntegrationType | null>(null);
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [credentials, setCredentials] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!contextLoading && accountId) {
      fetchIntegrations();
    }
  }, [accountId, contextLoading]);

  const fetchIntegrations = async () => {
    try {
      setLoading(true);
      
      const [typesRes, accountRes] = await Promise.all([
        fetch("/api/integrations/types"),
        fetch(`/api/integrations/account/${accountId}`)
      ]);

      if (typesRes.ok) {
        const types = await typesRes.json();
        setIntegrationTypes(types);
      }

      if (accountRes.ok) {
        const integrations = await accountRes.json();
        setAccountIntegrations(integrations);
      }
    } catch (error) {
      console.error("Failed to fetch integrations:", error);
      notify.error("Failed to load integrations");
    } finally {
      setLoading(false);
    }
  };

  const getIntegrationStatus = (typeId: string): AccountIntegration | undefined => {
    return accountIntegrations.find(i => i.integration_type_id === typeId);
  };

  const handleConnect = (type: IntegrationType) => {
    setSelectedType(type);
    setCredentials({});
    setShowConnectModal(true);
  };

  const handleDisconnect = async (integration: AccountIntegration) => {
    if (!confirm("Are you sure you want to disconnect this integration? This will remove your stored credentials.")) {
      return;
    }

    try {
      const response = await fetch(
        `/api/integrations/account/${accountId}/integration/${integration.id}`,
        { method: "DELETE" }
      );

      if (response.ok) {
        notify.success("Integration disconnected");
        fetchIntegrations();
      } else {
        notify.error("Failed to disconnect integration");
      }
    } catch (error) {
      console.error("Failed to disconnect:", error);
      notify.error("Failed to disconnect integration");
    }
  };

  const handleTestConnection = async (integration: AccountIntegration) => {
    setTesting(integration.id);
    
    try {
      const response = await fetch(
        `/api/integrations/account/${accountId}/integration/${integration.id}/test`,
        { method: "POST" }
      );

      const result = await response.json();

      if (result.success) {
        notify.success("Connection test successful!");
      } else {
        notify.error(result.message || "Connection test failed");
      }
    } catch (error) {
      console.error("Test failed:", error);
      notify.error("Failed to test connection");
    } finally {
      setTesting(null);
    }
  };

  const handleSubmitConnect = async () => {
    if (!selectedType) return;

    const missingFields = selectedType.required_fields
      .filter(f => f.required && !credentials[f.key])
      .map(f => f.label);

    if (missingFields.length > 0) {
      notify.error(`Missing required fields: ${missingFields.join(", ")}`);
      return;
    }

    setConnecting(true);

    try {
      const response = await fetch(`/api/integrations/account/${accountId}/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          integration_type_id: selectedType.id,
          credentials: credentials
        })
      });

      const result = await response.json();

      if (result.status === "connected") {
        notify.success("Integration connected successfully!");
        setShowConnectModal(false);
        fetchIntegrations();
      } else if (result.last_error) {
        notify.error(`Connection failed: ${result.last_error}`);
      } else {
        notify.error("Failed to connect integration");
      }
    } catch (error) {
      console.error("Failed to connect:", error);
      notify.error("Failed to connect integration");
    } finally {
      setConnecting(false);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "connected":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-900/50 text-green-400 border border-green-700">
            <Check className="h-3 w-3 mr-1" />
            Connected
          </span>
        );
      case "error":
      case "token_expired":
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
            Not Connected
          </span>
        );
    }
  };

  if (loading || contextLoading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-4xl">
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
          const connection = getIntegrationStatus(type.id);
          const isConnected = connection?.status === "connected";

          return (
            <div
              key={type.id}
              className="bg-[#141414] border border-gray-800 rounded-lg p-6 hover:border-gray-700 transition"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-4">
                  <div className="w-12 h-12 bg-gradient-to-br from-orange-500 to-red-600 rounded-lg flex items-center justify-center text-white font-bold text-lg">
                    OC
                  </div>
                  <div>
                    <div className="flex items-center gap-3">
                      <h3 className="text-lg font-semibold">{type.name}</h3>
                      {connection && getStatusBadge(connection.status)}
                    </div>
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
                    {connection?.last_error && (
                      <p className="text-xs text-red-400 mt-2">
                        Error: {connection.last_error}
                      </p>
                    )}
                    {connection?.connected_at && (
                      <p className="text-xs text-gray-500 mt-1">
                        Connected {new Date(connection.connected_at).toLocaleDateString()}
                      </p>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {isConnected ? (
                    <>
                      <button
                        onClick={() => handleTestConnection(connection)}
                        disabled={testing === connection.id}
                        className="px-3 py-1.5 text-sm font-medium text-gray-300 bg-gray-800 hover:bg-gray-700 rounded-lg transition disabled:opacity-50"
                      >
                        {testing === connection.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <RefreshCw className="h-4 w-4" />
                        )}
                      </button>
                      <button
                        onClick={() => handleDisconnect(connection)}
                        className="px-4 py-1.5 text-sm font-medium text-red-400 hover:text-red-300 border border-red-800 hover:border-red-700 rounded-lg transition"
                      >
                        Disconnect
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => handleConnect(type)}
                      className="inline-flex items-center px-4 py-1.5 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition"
                    >
                      Connect
                      <ChevronRight className="h-4 w-4 ml-1" />
                    </button>
                  )}
                </div>
              </div>
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

              {selectedType.required_fields.map((field) => (
                <div key={field.key}>
                  <label className="block text-sm font-medium text-gray-300 mb-1">
                    {field.label}
                    {field.required && <span className="text-red-400 ml-1">*</span>}
                  </label>
                  <input
                    type={field.type === "password" ? "password" : "text"}
                    placeholder={field.placeholder}
                    value={credentials[field.key] || ""}
                    onChange={(e) => setCredentials(prev => ({ ...prev, [field.key]: e.target.value }))}
                    className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                  />
                  {field.description && (
                    <p className="text-xs text-gray-500 mt-1">{field.description}</p>
                  )}
                </div>
              ))}

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
                onClick={() => setShowConnectModal(false)}
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
