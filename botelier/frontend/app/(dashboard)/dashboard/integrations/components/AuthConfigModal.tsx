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
  basic_auth_query_params?: string[];
  login_endpoint_path?: string;
  login_body_mapping?: Record<string, string>;
  login_body_static_fields?: Record<string, string>;
  login_body_encoding?: string;
  login_request_headers?: { header_name: string; credential_key: string }[];
  auth_request_query_params?: string[];
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

type MappingRow = { body_key: string; cred_key: string };
type HeaderRow = { header_name: string; credential_key: string };

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

  const [bodyMappingRows, setBodyMappingRows] = useState<MappingRow[]>([
    { body_key: "username", cred_key: "username" },
    { body_key: "password", cred_key: "password" },
  ]);
  const [queryParamRows, setQueryParamRows] = useState<string[]>([]);
  const [basicQueryParamRows, setBasicQueryParamRows] = useState<string[]>([]);
  const [loginHeaderRows, setLoginHeaderRows] = useState<HeaderRow[]>([]);
  const [staticFieldRows, setStaticFieldRows] = useState<MappingRow[]>([]);

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

        const mapping = cfg.login_body_mapping;
        if (mapping && Object.keys(mapping).length > 0) {
          setBodyMappingRows(Object.entries(mapping).map(([body_key, cred_key]) => ({ body_key, cred_key })));
        }
        setQueryParamRows(cfg.auth_request_query_params || []);
        setBasicQueryParamRows(cfg.basic_auth_query_params || []);
        setLoginHeaderRows(cfg.login_request_headers || []);
        const sf = cfg.login_body_static_fields;
        if (sf && Object.keys(sf).length > 0) {
          setStaticFieldRows(Object.entries(sf).map(([body_key, cred_key]) => ({ body_key, cred_key })));
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

  const updateBodyMappingRow = (rows: MappingRow[]) => {
    setBodyMappingRows(rows);
    const mapping: Record<string, string> = {};
    rows.forEach(({ body_key, cred_key }) => {
      if (body_key.trim()) mapping[body_key.trim()] = cred_key.trim();
    });
    updateConfig("login_body_mapping", mapping);
  };

  const updateQueryParamRows = (rows: string[]) => {
    setQueryParamRows(rows);
    updateConfig("auth_request_query_params", rows.filter((r) => r.trim()));
  };

  const updateBasicQueryParamRows = (rows: string[]) => {
    setBasicQueryParamRows(rows);
    updateConfig("basic_auth_query_params", rows.filter((r) => r.trim()));
  };

  const updateLoginHeaderRows = (rows: HeaderRow[]) => {
    setLoginHeaderRows(rows);
    updateConfig("login_request_headers", rows.filter((r) => r.header_name.trim() && r.credential_key.trim()));
  };

  const updateStaticFieldRows = (rows: MappingRow[]) => {
    setStaticFieldRows(rows);
    const sf: Record<string, string> = {};
    rows.forEach(({ body_key, cred_key }) => {
      if (body_key.trim()) sf[body_key.trim()] = cred_key;
    });
    updateConfig("login_body_static_fields", Object.keys(sf).length ? sf : undefined);
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

              {strategy === "basic" && (
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <div>
                      <label className="block text-sm font-medium text-gray-300">Query Params on Every Request</label>
                      <p className="text-xs text-gray-500 mt-0.5">
                        Credential keys appended as URL query params on every API call (e.g. <code className="text-gray-400">apikey</code>, <code className="text-gray-400">hotelId</code>)
                      </p>
                    </div>
                    <button
                      onClick={() => updateBasicQueryParamRows([...basicQueryParamRows, ""])}
                      className="inline-flex items-center gap-1 px-2 py-1 text-xs text-blue-400 hover:text-blue-300 bg-blue-900/20 hover:bg-blue-900/30 rounded transition shrink-0"
                    >
                      <Plus className="h-3 w-3" />
                      Add Param
                    </button>
                  </div>
                  <div className="space-y-2">
                    {basicQueryParamRows.map((row, idx) => (
                      <div key={idx} className="flex gap-2 items-center">
                        <input
                          type="text"
                          value={row}
                          onChange={(e) => {
                            const updated = [...basicQueryParamRows];
                            updated[idx] = e.target.value;
                            updateBasicQueryParamRows(updated);
                          }}
                          placeholder="e.g. apikey or hotelId"
                          className="flex-1 px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-600"
                        />
                        <button
                          onClick={() => updateBasicQueryParamRows(basicQueryParamRows.filter((_, i) => i !== idx))}
                          className="p-1 text-red-400 hover:text-red-300 transition"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}
                    {basicQueryParamRows.length === 0 && (
                      <p className="text-xs text-gray-600">No extra query params — only the Basic Auth header will be sent</p>
                    )}
                  </div>
                </div>
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
                  {/* Base URL */}
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-1">Base URL</label>
                    {authConfig.base_url ? (
                      <div className="flex items-center gap-2">
                        <input
                          type="text"
                          value={authConfig.base_url}
                          readOnly
                          className="flex-1 px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm text-gray-500 cursor-not-allowed"
                        />
                        <span className="text-xs text-gray-600 whitespace-nowrap">locked at import</span>
                      </div>
                    ) : (
                      <input
                        type="url"
                        value={authConfig.base_url || ""}
                        onChange={(e) => updateConfig("base_url", e.target.value)}
                        placeholder="https://api.example.com"
                        className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                      />
                    )}
                    <p className="text-xs text-gray-500 mt-1">
                      {authConfig.base_url
                        ? "Set from the imported spec — cannot be changed here"
                        : "Root URL of the API (e.g. https://api.example.com) — required when not in the imported spec"}
                    </p>
                  </div>

                  {/* Login endpoint path */}
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

                  {/* Request body encoding */}
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-1">Request Encoding</label>
                    <div className="relative">
                      <select
                        value={authConfig.login_body_encoding || "json"}
                        onChange={(e) => updateConfig("login_body_encoding", e.target.value)}
                        className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm appearance-none pr-8 focus:outline-none focus:ring-2 focus:ring-blue-600"
                      >
                        <option value="json">JSON (application/json)</option>
                        <option value="form">Form (application/x-www-form-urlencoded)</option>
                      </select>
                      <ChevronDown className="absolute right-2.5 top-2.5 h-4 w-4 text-gray-500 pointer-events-none" />
                    </div>
                    <p className="text-xs text-gray-500 mt-1">JSON is standard; use Form for OAuth-style token endpoints</p>
                  </div>

                  {/* Request body mapping */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <label className="block text-sm font-medium text-gray-300">Request Body Mapping</label>
                      <button
                        onClick={() => updateBodyMappingRow([...bodyMappingRows, { body_key: "", cred_key: "" }])}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs text-blue-400 hover:text-blue-300 bg-blue-900/20 rounded transition"
                      >
                        <Plus className="h-3 w-3" />
                        Add field
                      </button>
                    </div>
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
                    </div>
                    <p className="text-xs text-gray-500 mt-1.5">
                      Left = body field sent to API · Right = credential key the user fills in
                    </p>
                  </div>

                  {/* URL query params on the login call */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <div>
                        <label className="block text-sm font-medium text-gray-300">Auth Query Params</label>
                        <p className="text-xs text-gray-500 mt-0.5">Credential fields appended as URL query params on the login call (e.g. <code className="text-gray-400">apikey</code>)</p>
                      </div>
                      <button
                        onClick={() => updateQueryParamRows([...queryParamRows, ""])}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs text-blue-400 hover:text-blue-300 bg-blue-900/20 rounded transition flex-shrink-0"
                      >
                        <Plus className="h-3 w-3" />
                        Add
                      </button>
                    </div>
                    {queryParamRows.length > 0 && (
                      <div className="space-y-1.5">
                        {queryParamRows.map((row, idx) => (
                          <div key={idx} className="flex gap-2 items-center">
                            <input
                              type="text"
                              value={row}
                              onChange={(e) => {
                                const updated = [...queryParamRows];
                                updated[idx] = e.target.value;
                                updateQueryParamRows(updated);
                              }}
                              placeholder="credential_field_name"
                              className="flex-1 px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-600"
                            />
                            <button
                              onClick={() => updateQueryParamRows(queryParamRows.filter((_, i) => i !== idx))}
                              className="p-1 text-red-400 hover:text-red-300 transition"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Extra headers on the login call */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <div>
                        <label className="block text-sm font-medium text-gray-300">Login Request Headers</label>
                        <p className="text-xs text-gray-500 mt-0.5">Extra headers to send on the login call (e.g. <code className="text-gray-400">X-API-Key</code>)</p>
                      </div>
                      <button
                        onClick={() => updateLoginHeaderRows([...loginHeaderRows, { header_name: "", credential_key: "" }])}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs text-blue-400 hover:text-blue-300 bg-blue-900/20 rounded transition flex-shrink-0"
                      >
                        <Plus className="h-3 w-3" />
                        Add
                      </button>
                    </div>
                    {loginHeaderRows.length > 0 && (
                      <div className="space-y-1.5">
                        {loginHeaderRows.map((row, idx) => (
                          <div key={idx} className="flex gap-2 items-center">
                            <input
                              type="text"
                              value={row.header_name}
                              onChange={(e) => {
                                const updated = [...loginHeaderRows];
                                updated[idx] = { ...updated[idx], header_name: e.target.value };
                                updateLoginHeaderRows(updated);
                              }}
                              placeholder="X-Header-Name"
                              className="flex-1 px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-600"
                            />
                            <span className="text-gray-600 text-xs">→</span>
                            <input
                              type="text"
                              value={row.credential_key}
                              onChange={(e) => {
                                const updated = [...loginHeaderRows];
                                updated[idx] = { ...updated[idx], credential_key: e.target.value };
                                updateLoginHeaderRows(updated);
                              }}
                              placeholder="credential_field"
                              className="flex-1 px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-600"
                            />
                            <button
                              onClick={() => updateLoginHeaderRows(loginHeaderRows.filter((_, i) => i !== idx))}
                              className="p-1 text-red-400 hover:text-red-300 transition"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ))}
                        <p className="text-xs text-gray-500 mt-1">Left = header name · Right = credential field key</p>
                      </div>
                    )}
                  </div>

                  {/* Static body fields */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <div>
                        <label className="block text-sm font-medium text-gray-300">
                          Static Body Fields <span className="text-gray-500 font-normal">(optional)</span>
                        </label>
                        <p className="text-xs text-gray-500 mt-0.5">Fixed values always added to the body — not from credentials (e.g. <code className="text-gray-400">grant_type=client_credentials</code>)</p>
                      </div>
                      <button
                        onClick={() => updateStaticFieldRows([...staticFieldRows, { body_key: "", cred_key: "" }])}
                        className="inline-flex items-center gap-1 px-2 py-1 text-xs text-blue-400 hover:text-blue-300 bg-blue-900/20 rounded transition flex-shrink-0"
                      >
                        <Plus className="h-3 w-3" />
                        Add
                      </button>
                    </div>
                    {staticFieldRows.length > 0 && (
                      <div className="space-y-1.5">
                        {staticFieldRows.map((entry, idx) => (
                          <div key={idx} className="flex gap-2 items-center">
                            <input
                              type="text"
                              value={entry.body_key}
                              onChange={(e) => {
                                const updated = [...staticFieldRows];
                                updated[idx] = { ...updated[idx], body_key: e.target.value };
                                updateStaticFieldRows(updated);
                              }}
                              placeholder="field_name"
                              className="flex-1 px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-600"
                            />
                            <span className="text-gray-600 text-xs">=</span>
                            <input
                              type="text"
                              value={entry.cred_key}
                              onChange={(e) => {
                                const updated = [...staticFieldRows];
                                updated[idx] = { ...updated[idx], cred_key: e.target.value };
                                updateStaticFieldRows(updated);
                              }}
                              placeholder="static value"
                              className="flex-1 px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-600"
                            />
                            <button
                              onClick={() => updateStaticFieldRows(staticFieldRows.filter((_, i) => i !== idx))}
                              className="p-1 text-red-400 hover:text-red-300 transition"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Token JSON path */}
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

                  {/* Token expiry */}
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
                    <p className="text-xs text-gray-500 mt-1">Fallback TTL in seconds if the login response omits expires_in (default: 3600)</p>
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
