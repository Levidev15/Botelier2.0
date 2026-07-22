"use client";

import { useState, useRef } from "react";
import { Loader2, X, AlertCircle, Upload, Link, CheckCircle, FileJson } from "lucide-react";

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
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    name: string;
    endpoint_count: number;
    was_truncated: boolean;
  } | null>(null);
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
      setResult({
        name: data.name,
        endpoint_count: data.endpoint_count,
        was_truncated: data.was_truncated,
      });
      onSuccess();
    } catch (err: any) {
      setError(err?.message || "Import failed — please check your network and try again");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-[#1a1a1a] border border-gray-800 rounded-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-gray-800">
          <h2 className="text-lg font-semibold">Import API Spec</h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-800 rounded-lg transition">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-5">
          {result ? (
            <div className="flex flex-col items-center gap-4 py-6">
              <CheckCircle className="h-12 w-12 text-green-400" />
              <div className="text-center">
                <p className="text-lg font-semibold">{result.name}</p>
                <p className="text-sm text-gray-400 mt-1">
                  {result.endpoint_count} endpoint{result.endpoint_count !== 1 ? "s" : ""} imported
                </p>
                {result.was_truncated && (
                  <p className="text-xs text-yellow-400 mt-2">
                    Large spec — only the first endpoints were imported
                  </p>
                )}
              </div>
              <p className="text-sm text-gray-400 text-center max-w-xs">
                Now add a connection for this integration, then configure and publish its operations.
              </p>
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition"
              >
                Done
              </button>
            </div>
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

        {!result && (
          <div className="flex items-center justify-end gap-3 p-4 border-t border-gray-800">
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
          </div>
        )}
      </div>
    </div>
  );
}
