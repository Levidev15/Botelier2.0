"use client";

import { useState, useEffect } from "react";
import { Loader2, X, AlertCircle, Check, ChevronDown, Plus, Trash2 } from "lucide-react";
import type { IntegrationType } from "../types";

interface AvailableEndpoint {
  id: string;
  method: string;
  path: string;
  name: string;
}

interface AvailableStrategy {
  value: string;
  label: string;
}

interface AuthConfig {
  auth_strategy: string;
  base_url?: string;
  header_name?: string;
  credential_key?: string;
  param_name?: string;
  headers?: { header_name: string; credential_key: string }[];
  login_endpoint_path?: string;
  login_body_mapping?: Record<string, string>;
  token_response_path?: string;
  refresh_token_response_path?: string;
  token_expiry_seconds?: number;
  token_url?: string;
  scope?: string;
}

interface AuthConfigModalProps {
  integrationType: IntegrationType;
  accountId: string;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
  onSuccess: () => void;
  onNotify: (type: "success" | "error", message: string) => void;
  onClose: () => void;
}

const STRATEGY_DESCRIPTIONS: Record<string, string> = {
  none: "No authentication required — the API is publicly accessible.",
  bearer: "Send a static API token in the Authorization header (Bearer token).",
  api_key_header: "Send an API key in a custom request header.",
  api_key_query: "Append an API key as a URL query parameter.",
  custom_headers: "Send multiple API keys in separate request headers.",
  basic: "Authenticate with a username and password (HTTP Basic Auth).",
  login_endpoint: "Obtain a bearer token by calling the API's own login endpoint.",
  oauth2_client_credentials: "Obtain a bearer token via the OAuth2 client credentials grant.",
};

export default function AuthConfigModal({
  integrationType,
  accountId,
  authFetch,
  onSuccess,
  onNotify,
  onClose,
}: AuthConfigModalProps) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [strategy, setStrategy] = useState("bearer");
  const [authConfig, setAuthConfig] = useState<AuthConfig>({ auth_strategy: "bearer" });
  const [availableStrategies, setAvailableStrategies] = useState<AvailableStrategy[]>([]);
  const [availableEndpoints, setAvailableEndpoints] = useState<AvailableEndpoint[]>([]);
  // Body mapping rows live in their own state so empty rows persist while the user types.
  const [bodyMappingRows, setBodyMappingRows] = useState<{ body_key: string; cred_key: string }[]>([
    { body_key: "username", cred_key: "username" },
    { body_key: "password", cred_key: "password" },
  ]);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await authFetch(
          `/api/integrations/types/${integrationType.id}/auth-config?account_id=${accountId}`
        );
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          setError(d.detail || "Failed to load auth configuration");
          return;
        }
        const data = await res.json();
        setStrategy(data.auth_strategy || "bearer");
        const cfg: AuthConfig = data.auth_config || { auth_strategy: "bearer" };
        setAuthConfig(cfg);
        setAvailableStrategies(data.available_strategies || []);
        setAvailableEndpoints(data.available_endpoints || []);
        // Sync body mapping rows from saved config (or seed defaults)
        const mapping = cfg.login_body_mapping;
        if (mapping && Object.keys(mapping).length > 0) {
          setBodyMappingRows(Object.entries(mapping).map(([body_key, cred_key]) => ({ body_key, cred_key })));
        }
      } catch (e: any) {
        setError(e?.message || "Failed to load auth configuration");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [integrationType.id, accountId]);

  const handleStrategyChange = (newStrategy: string) => {
    setStrategy(newStrategy);
    setAuthConfig((prev) => ({ ...prev, auth_strategy: newStrategy }));
  };

  const handleSave = async () => {
    setError(null);
    setSaving(true);
    try {
      const res = await authFetch(
        `/api/integrations/types/${integrationType.id}/auth-config`,
        {
          method: "PATCH",
          body: JSON.stringify({
            account_id: accountId,
            auth_strategy: strategy,
            auth_config: authConfig,
          }),
        }
      );
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || "Failed to save auth configuration");
        return;
      }
      onSuccess();
      onNotify("success", `Auth method updated to "${strategy}" for ${integrationType.name}`);
      onClose();
    } catch (e: any) {
      setError(e?.message || "Failed to save — please try again");
    } finally {
      setSaving(false);
    }
  };

  const updateConfig = (key: string, value: unknown) => {
    setAuthConfig((prev) => ({ ...prev, [key]: value }));
  };

  const addCustomHeader = () => {
    const headers = authConfig.headers || [];
    updateConfig("headers", [...headers, { header_name: "", credential_key: "" }]);
  };

  const removeCustomHeader = (idx: number) => {
    const headers = authConfig.headers || [];
    updateConfig("headers", headers.filter((_, i) => i !== idx));
  };

  const updateCustomHeader = (idx: number, field: "header_name" | "credential_key", value: string) => {
    const headers = [...(authConfig.headers || [])];
    headers[idx] = { ...headers[idx], [field]: value };
    updateConfig("headers", headers);
  };

  const updateBodyMappingRow = (rows: { body_key: string; cred_key: string }[]) => {
    setBodyMappingRows(rows);
    // Commit only fully-keyed rows to authConfig so the save payload is clean
    const mapping: Record<string, string> = {};
    rows.forEach(({ body_key, cred_key }) => {
      if (body_key.trim()) mapping[body_key.trim()] = cred_key.trim();
    });
    updateConfig("login_body_mapping", mapping);
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-[#1a1a1a] border border-gray-800 rounded-xl w-full max-w-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-gray-800">
          <div>
            <h2 className="text-lg font-semibold">Auth Settings</h2>
            <p className="text-xs text-gray-400 mt-0.5">{integrationType.name}</p>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-gray-800 rounded-lg transition">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-5">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
            </div>
          ) : (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1.5">
                  Authentication Method
                </label>
                <div className="relative">
                  <select
                    value={strategy}
                    onChange={(e) => handleStrategyChange(e.target.value)}
                    className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm appearance-none pr-8 focus:outline-none focus:ring-2 focus:ring-blue-600"
                  >
                    {availableStrategies.map((s) => (
                      <option key={s.value} value={s.value}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="absolute right-2.5 top-2.5 h-4 w-4 text-gray-500 pointer-events-none" />
                </div>
                {STRATEGY_DESCRIPTIONS[strategy] && (
                  <p className="text-xs text-gray-500 mt-1">{STRATEGY_DESCRIPTIONS[strategy]}</p>
                )}
              </div>

              {strategy === "api_key_header" && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-1">Header Name</label>
                    <input
                      type="text"
                      value={authConfig.header_name || ""}
                      onChange={(e) => updateConfig("header_name", e.target.value)}
                      placeholder="X-API-Key"
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    />
                    <p className="text-xs text-gray-500 mt-1">The HTTP header name the API expects</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-1">Credential Field Name</label>
                    <input
                      type="text"
                      value={authConfig.credential_key || ""}
                      onChange={(e) => updateConfig("credential_key", e.target.value)}
                      placeholder="api_key"
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    />
                    <p className="text-xs text-gray-500 mt-1">Field key users will enter when connecting (e.g. "api_key")</p>
                  </div>
                </>
              )}

              {strategy === "api_key_query" && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-1">Query Parameter Name</label>
                    <input
                      type="text"
                      value={authConfig.param_name || ""}
                      onChange={(e) => updateConfig("param_name", e.target.value)}
                      placeholder="api_key"
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    />
                    <p className="text-xs text-gray-500 mt-1">The URL query parameter name (e.g. ?api_key=...)</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-1">Credential Field Name</label>
                    <input
                      type="text"
                      value={authConfig.credential_key || ""}
                      onChange={(e) => updateConfig("credential_key", e.target.value)}
                      placeholder="api_key"
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    />
                  </div>
                </>
              )}

              {strategy === "custom_headers" && (
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="block text-sm font-medium text-gray-300">Header Keys</label>
                    <button
                      onClick={addCustomHeader}
                      className="inline-flex items-center gap-1 px-2 py-1 text-xs text-blue-400 hover:text-blue-300 bg-blue-900/20 hover:bg-blue-900/30 rounded transition"
                    >
                      <Plus className="h-3 w-3" />
                      Add Header
                    </button>
                  </div>
                  <div className="space-y-2">
                    {(authConfig.headers || []).map((hdr, idx) => (
                      <div key={idx} className="flex gap-2 items-center">
                        <input
                          type="text"
                          value={hdr.header_name}
                          onChange={(e) => updateCustomHeader(idx, "header_name", e.target.value)}
                          placeholder="X-Header-Name"
                          className="flex-1 px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-600"
                        />
                        <input
                          type="text"
                          value={hdr.credential_key}
                          onChange={(e) => updateCustomHeader(idx, "credential_key", e.target.value)}
                          placeholder="field_name"
                          className="flex-1 px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-600"
                        />
                        <button
                          onClick={() => removeCustomHeader(idx)}
                          className="p-1 text-red-400 hover:text-red-300 transition"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}
                    {(authConfig.headers || []).length === 0 && (
                      <p className="text-xs text-gray-600">Add at least one header key</p>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 mt-1.5">
                    Left column = HTTP header name · Right column = credential field key users will fill in
                  </p>
                </div>
              )}

              {strategy === "login_endpoint" && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-1">Login Endpoint Path</label>
                    {availableEndpoints.length > 0 ? (
                      <select
                        value={authConfig.login_endpoint_path || ""}
                        onChange={(e) => updateConfig("login_endpoint_path", e.target.value)}
                        className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                      >
                        <option value="">— Select an endpoint —</option>
                        {availableEndpoints
                          .filter((ep) => ep.method === "POST" || ep.method === "PUT")
                          .map((ep) => (
                            <option key={ep.id} value={ep.path}>
                              {ep.method} {ep.path}
                            </option>
                          ))}
                        {availableEndpoints
                          .filter((ep) => ep.method !== "POST" && ep.method !== "PUT")
                          .map((ep) => (
                            <option key={ep.id} value={ep.path}>
                              {ep.method} {ep.path}
                            </option>
                          ))}
                      </select>
                    ) : (
                      <input
                        type="text"
                        value={authConfig.login_endpoint_path || ""}
                        onChange={(e) => updateConfig("login_endpoint_path", e.target.value)}
                        placeholder="/auth/login"
                        className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                      />
                    )}
                    <p className="text-xs text-gray-500 mt-1">The API path to POST credentials to obtain a token</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-2">
                      Request Body Mapping
                    </label>
                    <div className="space-y-1.5">
                      {bodyMappingRows.map((entry, idx) => (
                        <div key={idx} className="flex gap-2 items-center">
                          <input
                            type="text"
                            value={entry.body_key}
                            onChange={(e) => {
                              const updated = [...bodyMappingRows];
                              updated[idx] = { ...updated[idx], body_key: e.target.value };
                              updateBodyMappingRow(updated);
                            }}
                            placeholder="request_body_field"
                            className="flex-1 px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-600"
                          />
                          <span className="text-gray-600 text-xs">→</span>
                          <input
                            type="text"
                            value={entry.cred_key}
                            onChange={(e) => {
                              const updated = [...bodyMappingRows];
                              updated[idx] = { ...updated[idx], cred_key: e.target.value };
                              updateBodyMappingRow(updated);
                            }}
                            placeholder="credential_field"
                            className="flex-1 px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-600"
                          />
                          <button
                            onClick={() => updateBodyMappingRow(bodyMappingRows.filter((_, i) => i !== idx))}
                            className="p-1 text-red-400 hover:text-red-300 transition"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      ))}
                      <button
                        onClick={() => updateBodyMappingRow([...bodyMappingRows, { body_key: "", cred_key: "" }])}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs text-blue-400 hover:text-blue-300 bg-blue-900/20 rounded transition"
                      >
                        <Plus className="h-3 w-3" />
                        Add field
                      </button>
                    </div>
                    <p className="text-xs text-gray-500 mt-1.5">
                      Left = JSON body key sent to login endpoint · Right = credential key the user fills in
                    </p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-1">Token JSON Path</label>
                    <input
                      type="text"
                      value={authConfig.token_response_path || ""}
                      onChange={(e) => updateConfig("token_response_path", e.target.value)}
                      placeholder="token"
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    />
                    <p className="text-xs text-gray-500 mt-1">Dot-path to the bearer token in the login response (e.g. "token" or "data.access_token")</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-1">
                      Token Expiry (seconds) <span className="text-gray-500 font-normal">(optional)</span>
                    </label>
                    <input
                      type="number"
                      value={authConfig.token_expiry_seconds || 3600}
                      onChange={(e) => updateConfig("token_expiry_seconds", parseInt(e.target.value) || 3600)}
                      min={60}
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    />
                    <p className="text-xs text-gray-500 mt-1">Default TTL in seconds if the login response omits expires_in (default: 3600)</p>
                  </div>
                </>
              )}

              {strategy === "oauth2_client_credentials" && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-1">Token URL</label>
                    <input
                      type="url"
                      value={authConfig.token_url || ""}
                      onChange={(e) => updateConfig("token_url", e.target.value)}
                      placeholder="https://api.example.com/oauth/token"
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    />
                    <p className="text-xs text-gray-500 mt-1">Full URL of the OAuth2 token endpoint</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-1">
                      Scope <span className="text-gray-500 font-normal">(optional)</span>
                    </label>
                    <input
                      type="text"
                      value={authConfig.scope || ""}
                      onChange={(e) => updateConfig("scope", e.target.value)}
                      placeholder="read write"
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    />
                    <p className="text-xs text-gray-500 mt-1">Space-separated scopes to request (leave blank for server default)</p>
                  </div>
                </>
              )}

              {error && (
                <div className="flex items-start gap-2 p-3 bg-red-900/30 border border-red-800 rounded-lg">
                  <AlertCircle className="h-4 w-4 text-red-400 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-red-300">{error}</p>
                </div>
              )}

              <div className="p-3 bg-amber-900/20 border border-amber-800/50 rounded-lg">
                <p className="text-xs text-amber-300">
                  Changing the auth method updates the credential fields for this integration type.
                  Existing connections will need to be reconnected with their credentials.
                </p>
              </div>
            </>
          )}
        </div>

        {!loading && (
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
                <>
                  <Check className="h-4 w-4 mr-1.5" />
                  Save Auth Settings
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
