"use client";

import { useState, useRef } from "react";
import { Loader2, X, AlertCircle, Upload, Link, CheckCircle, FileJson, ChevronDown, Settings } from "lucide-react";

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
  const [importResult, setImportResult] = useState<{
    id: string;
    name: string;
    endpoint_count: number;
    was_truncated: boolean;
    auth_strategy: string;
  } | null>(null);
  const [authStrategy, setAuthStrategy] = useState("bearer");
  const fileRef = useRef<HTMLInputElement>(null);

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
      const detectedStrategy = data.auth_config?.auth_strategy || "bearer";
      setAuthStrategy(detectedStrategy);
      setImportResult({
        id: data.id,
        name: data.name,
        endpoint_count: data.endpoint_count,
        was_truncated: data.was_truncated,
        auth_strategy: detectedStrategy,
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
            auth_config: { auth_strategy: authStrategy },
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

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-[#1a1a1a] border border-gray-800 rounded-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-gray-800">
          <h2 className="text-lg font-semibold">
            {importResult ? "Configure Auth Method" : "Import API Spec"}
          </h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-800 rounded-lg transition">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-5">
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
                    onChange={(e) => setAuthStrategy(e.target.value)}
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

              <div className="p-3 bg-[#111] border border-gray-800 rounded-lg">
                <div className="flex items-start gap-2">
                  <Settings className="h-4 w-4 text-gray-500 flex-shrink-0 mt-0.5" />
                  <p className="text-xs text-gray-400">
                    You can update individual auth details (header names, token URL, etc.) after import
                    using the <span className="text-gray-300">Auth</span> button on the integration card.
                  </p>
                </div>
              </div>

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
