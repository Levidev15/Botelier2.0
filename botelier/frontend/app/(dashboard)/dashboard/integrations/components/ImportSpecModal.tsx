"use client";

import { useState, useRef } from "react";
import {
  Loader2, X, AlertCircle, Upload, Link, CheckCircle, FileJson,
  ChevronDown, Plus, Trash2,
} from "lucide-react";

const STRATEGY_OPTIONS = [
  { value: "bearer", label: "Bearer Token" },
  { value: "api_key_header", label: "API Key (Header)" },
  { value: "api_key_query", label: "API Key (Query Parameter)" },
  { value: "custom_headers", label: "Custom Headers" },
  { value: "basic", label: "Basic Auth (Username + Password)" },
  { value: "login_endpoint", label: "Login Endpoint (Token from API)" },
  { value: "oauth2_client_credentials", label: "OAuth2 Client Credentials" },
  { value: "none", label: "No Authentication" },
];

const STRATEGY_DESCRIPTIONS: Record<string, string> = {
  none: "No authentication required.",
  bearer: "Send a static API token in the Authorization header.",
  api_key_header: "Send an API key in a custom request header.",
  api_key_query: "Append an API key as a URL query parameter.",
  custom_headers: "Send multiple API keys in separate request headers.",
  basic: "Authenticate with a username and password.",
  login_endpoint: "Obtain a bearer token by calling the API's own login endpoint.",
  oauth2_client_credentials: "Obtain a bearer token via the OAuth2 client credentials grant.",
};

interface AvailableEndpoint {
  id: string;
  method: string;
  path: string;
  name: string;
}

interface ImportResult {
  id: string;
  name: string;
  endpoint_count: number;
  was_truncated: boolean;
  auth_strategy: string;
  auth_config: Record<string, unknown>;
  available_endpoints: AvailableEndpoint[];
}

interface ImportSpecModalProps {
  accountId: string;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
  onSuccess: () => void;
  onNotify: (type: "success" | "error", message: string) => void;
  onClose: () => void;
}

export default function ImportSpecModal({
  accountId,
  authFetch,
  onSuccess,
  onNotify,
  onClose,
}: ImportSpecModalProps) {
  const [specType, setSpecType] = useState<"openapi" | "swagger" | "postman">("openapi");
  const [inputMode, setInputMode] = useState<"file" | "url">("file");
  const [specUrl, setSpecUrl] = useState("");
  const [baseUrlOverride, setBaseUrlOverride] = useState("");
  const [fileData, setFileData] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [savingAuth, setSavingAuth] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);

  // Auth config state
  const [authStrategy, setAuthStrategy] = useState("bearer");
  const [authConfig, setAuthConfig] = useState<Record<string, unknown>>({});

  const fileRef = useRef<HTMLInputElement>(null);

  const updateConfig = (key: string, value: unknown) =>
    setAuthConfig((prev) => ({ ...prev, [key]: value }));

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result as string;
      try {
        setFileData(btoa(unescape(encodeURIComponent(text))));
      } catch {
        setFileData(btoa(text));
      }
    };
    reader.readAsText(file);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (!file) return;
    const fakeEvent = { target: { files: [file] } } as unknown as React.ChangeEvent<HTMLInputElement>;
    handleFile(fakeEvent);
  };

  const handleImport = async () => {
    setError(null);
    if (inputMode === "file" && !fileData) {
      setError("Please select a spec file to upload");
      return;
    }
    if (inputMode === "url" && !specUrl.trim()) {
      setError("Please enter the spec URL");
      return;
    }

    setImporting(true);
    try {
      const body: Record<string, string> = {
        account_id: accountId,
        spec_type: specType,
      };
      if (inputMode === "file") body.spec_file_b64 = fileData!;
      else body.spec_url = specUrl.trim();
      if (baseUrlOverride.trim()) body.base_url_override = baseUrlOverride.trim();

      const res = await authFetch("/api/integrations/import", {
        method: "POST",
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || "Import failed");
        return;
      }
      onSuccess();
      const detectedStrategy = data.auth_strategy || "bearer";
      const detectedConfig = data.auth_config || { auth_strategy: detectedStrategy };
      setAuthStrategy(detectedStrategy);
      setAuthConfig(detectedConfig);
      setImportResult({
        id: data.id,
        name: data.name,
        endpoint_count: data.endpoint_count,
        was_truncated: data.was_truncated,
        auth_strategy: detectedStrategy,
        auth_config: detectedConfig,
        available_endpoints: data.available_endpoints || [],
      });
    } catch (err: any) {
      setError(err?.message || "Import failed — please check your network and try again");
    } finally {
      setImporting(false);
    }
  };

  const handleSaveAuth = async () => {
    if (!importResult) return;
    setError(null);
    setSavingAuth(true);
    try {
      const res = await authFetch(
        `/api/integrations/types/${importResult.id}/auth-config`,
        {
          method: "PATCH",
          body: JSON.stringify({
            account_id: accountId,
            auth_strategy: authStrategy,
            auth_config: { ...authConfig, auth_strategy: authStrategy },
          }),
        }
      );
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || "Failed to save auth method");
        return;
      }
      onNotify("success", `${importResult.name} imported — auth set to "${authStrategy}"`);
      onClose();
    } catch (err: any) {
      setError(err?.message || "Failed to save — please try again");
    } finally {
      setSavingAuth(false);
    }
  };

  const availableEndpoints = importResult?.available_endpoints || [];
  const bodyMappingEntries = Object.entries(
    (authConfig.login_body_mapping as Record<string, string>) ||
      { username: "username", password: "password" }
  ).map(([body_key, cred_key]) => ({ body_key, cred_key }));

  const updateBodyMapping = (entries: { body_key: string; cred_key: string }[]) => {
    const mapping: Record<string, string> = {};
    entries.forEach(({ body_key, cred_key }) => {
      if (body_key.trim()) mapping[body_key.trim()] = cred_key.trim();
    });
    updateConfig("login_body_mapping", mapping);
  };

  const customHeaders = (authConfig.headers as { header_name: string; credential_key: string }[]) || [];

  const renderStrategyFields = () => {
    switch (authStrategy) {
      case "api_key_header":
        return (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1">Header Name</label>
              <input
                type="text"
                value={(authConfig.header_name as string) || ""}
                onChange={(e) => updateConfig("header_name", e.target.value)}
                placeholder="X-API-Key"
                className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1">Credential Field Name</label>
              <input
                type="text"
                value={(authConfig.credential_key as string) || ""}
                onChange={(e) => updateConfig("credential_key", e.target.value)}
                placeholder="api_key"
                className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
              />
            </div>
          </>
        );

      case "api_key_query":
        return (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1">Query Parameter Name</label>
              <input
                type="text"
                value={(authConfig.param_name as string) || ""}
                onChange={(e) => updateConfig("param_name", e.target.value)}
                placeholder="api_key"
                className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1">Credential Field Name</label>
              <input
                type="text"
                value={(authConfig.credential_key as string) || ""}
                onChange={(e) => updateConfig("credential_key", e.target.value)}
                placeholder="api_key"
                className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
              />
            </div>
          </>
        );

      case "custom_headers":
        return (
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-xs font-medium text-gray-400">Header Keys</label>
              <button
                onClick={() =>
                  updateConfig("headers", [...customHeaders, { header_name: "", credential_key: "" }])
                }
                className="inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
              >
                <Plus className="h-3 w-3" /> Add
              </button>
            </div>
            <div className="space-y-1.5">
              {customHeaders.map((hdr, idx) => (
                <div key={idx} className="flex gap-2 items-center">
                  <input
                    type="text"
                    value={hdr.header_name}
                    onChange={(e) => {
                      const updated = [...customHeaders];
                      updated[idx] = { ...updated[idx], header_name: e.target.value };
                      updateConfig("headers", updated);
                    }}
                    placeholder="X-Header-Name"
                    className="flex-1 px-2 py-1 bg-[#0a0a0a] border border-gray-800 rounded text-xs focus:outline-none focus:ring-1 focus:ring-blue-600"
                  />
                  <input
                    type="text"
                    value={hdr.credential_key}
                    onChange={(e) => {
                      const updated = [...customHeaders];
                      updated[idx] = { ...updated[idx], credential_key: e.target.value };
                      updateConfig("headers", updated);
                    }}
                    placeholder="field_name"
                    className="flex-1 px-2 py-1 bg-[#0a0a0a] border border-gray-800 rounded text-xs focus:outline-none focus:ring-1 focus:ring-blue-600"
                  />
                  <button
                    onClick={() => updateConfig("headers", customHeaders.filter((_, i) => i !== idx))}
                    className="text-red-400 hover:text-red-300"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))}
              {customHeaders.length === 0 && (
                <p className="text-xs text-gray-600">Add at least one header</p>
              )}
            </div>
          </div>
        );

      case "login_endpoint":
        return (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1">Login Endpoint Path</label>
              {availableEndpoints.length > 0 ? (
                <select
                  value={(authConfig.login_endpoint_path as string) || ""}
                  onChange={(e) => updateConfig("login_endpoint_path", e.target.value)}
                  className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                >
                  <option value="">— Select endpoint —</option>
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
                  value={(authConfig.login_endpoint_path as string) || ""}
                  onChange={(e) => updateConfig("login_endpoint_path", e.target.value)}
                  placeholder="/auth/login"
                  className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                />
              )}
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1">Token JSON Path</label>
              <input
                type="text"
                value={(authConfig.token_response_path as string) || ""}
                onChange={(e) => updateConfig("token_response_path", e.target.value)}
                placeholder="token"
                className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
              />
              <p className="text-xs text-gray-600 mt-0.5">Dot-path to the bearer token in the login response</p>
            </div>
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-xs font-medium text-gray-400">Request Body Mapping</label>
                <button
                  onClick={() => updateBodyMapping([...bodyMappingEntries, { body_key: "", cred_key: "" }])}
                  className="inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
                >
                  <Plus className="h-3 w-3" /> Add
                </button>
              </div>
              <div className="space-y-1.5">
                {bodyMappingEntries.map((entry, idx) => (
                  <div key={idx} className="flex gap-2 items-center">
                    <input
                      type="text"
                      value={entry.body_key}
                      onChange={(e) => {
                        const updated = [...bodyMappingEntries];
                        updated[idx] = { ...updated[idx], body_key: e.target.value };
                        updateBodyMapping(updated);
                      }}
                      placeholder="body_field"
                      className="flex-1 px-2 py-1 bg-[#0a0a0a] border border-gray-800 rounded text-xs focus:outline-none focus:ring-1 focus:ring-blue-600"
                    />
                    <span className="text-gray-600 text-xs">→</span>
                    <input
                      type="text"
                      value={entry.cred_key}
                      onChange={(e) => {
                        const updated = [...bodyMappingEntries];
                        updated[idx] = { ...updated[idx], cred_key: e.target.value };
                        updateBodyMapping(updated);
                      }}
                      placeholder="cred_key"
                      className="flex-1 px-2 py-1 bg-[#0a0a0a] border border-gray-800 rounded text-xs focus:outline-none focus:ring-1 focus:ring-blue-600"
                    />
                    <button
                      onClick={() => updateBodyMapping(bodyMappingEntries.filter((_, i) => i !== idx))}
                      className="text-red-400 hover:text-red-300"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </>
        );

      case "oauth2_client_credentials":
        return (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1">Token URL</label>
              <input
                type="url"
                value={(authConfig.token_url as string) || ""}
                onChange={(e) => updateConfig("token_url", e.target.value)}
                placeholder="https://api.example.com/oauth/token"
                className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1">
                Scope <span className="text-gray-600">(optional)</span>
              </label>
              <input
                type="text"
                value={(authConfig.scope as string) || ""}
                onChange={(e) => updateConfig("scope", e.target.value)}
                placeholder="read write"
                className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
              />
            </div>
          </>
        );

      default:
        return null;
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-[#1a1a1a] border border-gray-800 rounded-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-gray-800">
          <h2 className="text-lg font-semibold">
            {importResult ? "Set Auth Method" : "Import API Spec"}
          </h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-800 rounded-lg transition">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          {importResult ? (
            <>
              <div className="flex items-center gap-3 p-3 bg-green-900/20 border border-green-800/50 rounded-lg">
                <CheckCircle className="h-5 w-5 text-green-400 flex-shrink-0" />
                <div>
                  <p className="text-sm font-medium text-green-300">{importResult.name} imported</p>
                  <p className="text-xs text-green-500 mt-0.5">
                    {importResult.endpoint_count} endpoint{importResult.endpoint_count !== 1 ? "s" : ""}
                    {importResult.was_truncated && " (large spec — first batch imported)"}
                  </p>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1.5">
                  Authentication Method
                </label>
                <div className="relative">
                  <select
                    value={authStrategy}
                    onChange={(e) => {
                      setAuthStrategy(e.target.value);
                      setAuthConfig((prev) => ({ ...prev, auth_strategy: e.target.value }));
                    }}
                    className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm appearance-none pr-8 focus:outline-none focus:ring-2 focus:ring-blue-600"
                  >
                    {STRATEGY_OPTIONS.map((s) => (
                      <option key={s.value} value={s.value}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="absolute right-2.5 top-2.5 h-4 w-4 text-gray-500 pointer-events-none" />
                </div>
                {STRATEGY_DESCRIPTIONS[authStrategy] && (
                  <p className="text-xs text-gray-500 mt-1">{STRATEGY_DESCRIPTIONS[authStrategy]}</p>
                )}
              </div>

              {renderStrategyFields()}

              {error && (
                <div className="flex items-start gap-2 p-3 bg-red-900/30 border border-red-800 rounded-lg">
                  <AlertCircle className="h-4 w-4 text-red-400 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-red-300">{error}</p>
                </div>
              )}
            </>
          ) : (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">Spec Format</label>
                <div className="flex gap-2">
                  {(["openapi", "swagger", "postman"] as const).map((t) => (
                    <button
                      key={t}
                      onClick={() => setSpecType(t)}
                      className={`px-3 py-1.5 rounded text-sm transition-colors border ${
                        specType === t
                          ? "bg-blue-600 border-blue-500 text-white"
                          : "bg-[#0a0a0a] border-gray-700 text-gray-400 hover:text-white"
                      }`}
                    >
                      {t === "openapi" ? "OpenAPI" : t === "swagger" ? "Swagger" : "Postman"}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">Source</label>
                <div className="flex gap-2 mb-3">
                  <button
                    onClick={() => setInputMode("file")}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-colors border ${
                      inputMode === "file"
                        ? "bg-blue-600 border-blue-500 text-white"
                        : "bg-[#0a0a0a] border-gray-700 text-gray-400 hover:text-white"
                    }`}
                  >
                    <Upload className="h-3.5 w-3.5" />
                    Upload File
                  </button>
                  <button
                    onClick={() => setInputMode("url")}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-colors border ${
                      inputMode === "url"
                        ? "bg-blue-600 border-blue-500 text-white"
                        : "bg-[#0a0a0a] border-gray-700 text-gray-400 hover:text-white"
                    }`}
                  >
                    <Link className="h-3.5 w-3.5" />
                    URL
                  </button>
                </div>

                {inputMode === "file" ? (
                  <div
                    onClick={() => fileRef.current?.click()}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={handleDrop}
                    className="border-2 border-dashed border-gray-700 rounded-lg p-6 text-center cursor-pointer hover:border-gray-500 transition-colors"
                  >
                    {fileName ? (
                      <div className="flex flex-col items-center gap-2">
                        <FileJson className="h-8 w-8 text-blue-400" />
                        <p className="text-sm text-white font-medium">{fileName}</p>
                        <p className="text-xs text-gray-500">Click to replace</p>
                      </div>
                    ) : (
                      <>
                        <Upload className="h-6 w-6 text-gray-500 mx-auto mb-2" />
                        <p className="text-sm text-gray-400">
                          Click to upload or drag and drop
                        </p>
                        <p className="text-xs text-gray-600 mt-1">JSON or YAML</p>
                      </>
                    )}
                    <input
                      ref={fileRef}
                      type="file"
                      accept=".json,.yaml,.yml"
                      className="hidden"
                      onChange={handleFile}
                    />
                  </div>
                ) : (
                  <input
                    type="url"
                    value={specUrl}
                    onChange={(e) => setSpecUrl(e.target.value)}
                    placeholder="https://api.example.com/openapi.json"
                    className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                  />
                )}
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  Base URL Override{" "}
                  <span className="text-gray-500 font-normal">(optional)</span>
                </label>
                <input
                  type="url"
                  value={baseUrlOverride}
                  onChange={(e) => setBaseUrlOverride(e.target.value)}
                  placeholder="https://api.example.com/v1"
                  className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                />
                <p className="text-xs text-gray-500 mt-1">
                  Override the server URL from the spec (e.g. for sandbox vs production)
                </p>
              </div>

              {error && (
                <div className="flex items-start gap-2 p-3 bg-red-900/30 border border-red-800 rounded-lg">
                  <AlertCircle className="h-4 w-4 text-red-400 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-red-300">{error}</p>
                </div>
              )}
            </>
          )}
        </div>

        <div className="flex items-center justify-end gap-3 p-4 border-t border-gray-800">
          {importResult ? (
            <>
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-gray-300 hover:text-white transition"
              >
                Skip
              </button>
              <button
                onClick={handleSaveAuth}
                disabled={savingAuth}
                className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition disabled:opacity-50"
              >
                {savingAuth ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Saving...
                  </>
                ) : (
                  "Save & Done"
                )}
              </button>
            </>
          ) : (
            <>
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-gray-300 hover:text-white transition"
              >
                Cancel
              </button>
              <button
                onClick={handleImport}
                disabled={importing}
                className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition disabled:opacity-50"
              >
                {importing ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Importing...
                  </>
                ) : (
                  "Import Spec"
                )}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
