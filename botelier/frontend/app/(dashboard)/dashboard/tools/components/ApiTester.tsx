"use client";

import { useState } from "react";
import { Play, Plus, Trash2, ChevronDown, ChevronRight, Copy, Check, Loader2 } from "lucide-react";
import { notify } from "@/lib/notifications";

interface HeaderEntry {
  key: string;
  value: string;
}

interface ResponseData {
  status_code: number;
  headers: Record<string, string>;
  body: any;
  elapsed_ms: number;
  error?: string;
}

function flattenKeys(obj: any, prefix: string = ""): string[] {
  if (obj === null || obj === undefined || typeof obj !== "object") return [];
  const keys: string[] = [];
  if (Array.isArray(obj)) {
    if (obj.length > 0) {
      keys.push(`${prefix}[0]`);
      const nested = flattenKeys(obj[0], `${prefix}[0]`);
      keys.push(...nested);
    }
  } else {
    for (const [key, value] of Object.entries(obj)) {
      const path = prefix ? `${prefix}.${key}` : key;
      keys.push(path);
      if (typeof value === "object" && value !== null) {
        const nested = flattenKeys(value, path);
        keys.push(...nested);
      }
    }
  }
  return keys;
}

function getNestedValue(obj: any, path: string): any {
  const parts = path.split(/\.|\[|\]/).filter(Boolean);
  let current = obj;
  for (const part of parts) {
    if (current === null || current === undefined) return undefined;
    current = current[part];
  }
  return current;
}

export default function ApiTester() {
  const [method, setMethod] = useState("GET");
  const [url, setUrl] = useState("");
  const [headers, setHeaders] = useState<HeaderEntry[]>([]);
  const [body, setBody] = useState("");
  const [timeout, setTimeout_] = useState(30);
  const [showHeaders, setShowHeaders] = useState(false);
  const [showBody, setShowBody] = useState(false);
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<ResponseData | null>(null);
  const [responseView, setResponseView] = useState<"pretty" | "raw" | "keys">("pretty");
  const [copiedPath, setCopiedPath] = useState<string | null>(null);

  const handleTest = async () => {
    if (!url.trim()) {
      notify.error("URL is required");
      return;
    }

    setLoading(true);
    setResponse(null);

    try {
      const headersObj: Record<string, string> = {};
      headers.forEach((h) => {
        if (h.key.trim()) headersObj[h.key.trim()] = h.value;
      });

      const payload: any = {
        url,
        method,
        timeout,
      };
      if (Object.keys(headersObj).length > 0) payload.headers = headersObj;
      if (body.trim() && (method === "POST" || method === "PUT" || method === "PATCH")) {
        payload.body = body;
      }

      const res = await fetch("/api/api-tester/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      setResponse(data);
    } catch (error) {
      notify.error("Failed to send test request");
    } finally {
      setLoading(false);
    }
  };

  const addHeader = () => setHeaders([...headers, { key: "", value: "" }]);
  const removeHeader = (i: number) => setHeaders(headers.filter((_, idx) => idx !== i));
  const updateHeader = (i: number, field: "key" | "value", val: string) => {
    const updated = [...headers];
    updated[i][field] = val;
    setHeaders(updated);
  };

  const copyToClipboard = (text: string, path?: string) => {
    navigator.clipboard.writeText(text);
    if (path) {
      setCopiedPath(path);
      setTimeout(() => setCopiedPath(null), 2000);
    }
  };

  const statusColor = (code: number) => {
    if (code === 0) return "text-red-400";
    if (code < 300) return "text-green-400";
    if (code < 400) return "text-yellow-400";
    return "text-red-400";
  };

  const responseKeys = response?.body ? flattenKeys(response.body) : [];

  const inputCls = "w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-purple-600 focus:border-transparent font-mono";

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 pb-3 border-b border-gray-800">
        <div className="w-10 h-10 rounded-lg bg-purple-600/20 flex items-center justify-center">
          <Play className="text-purple-500" size={18} />
        </div>
        <div>
          <h3 className="font-semibold text-white">API Tester</h3>
          <p className="text-xs text-gray-400">Test API endpoints and explore response structure</p>
        </div>
      </div>

      <div className="flex gap-2">
        <select
          value={method}
          onChange={(e) => {
            setMethod(e.target.value);
            if (["POST", "PUT", "PATCH"].includes(e.target.value)) setShowBody(true);
          }}
          className="w-28 px-3 py-2.5 bg-[#141414] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-purple-600 font-mono font-bold"
        >
          <option value="GET">GET</option>
          <option value="POST">POST</option>
          <option value="PUT">PUT</option>
          <option value="DELETE">DELETE</option>
          <option value="PATCH">PATCH</option>
        </select>
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://api.example.com/endpoint"
          className={`flex-1 ${inputCls}`}
          onKeyDown={(e) => { if (e.key === "Enter") handleTest(); }}
        />
        <button
          onClick={handleTest}
          disabled={loading || !url.trim()}
          className="px-5 py-2.5 bg-purple-600 hover:bg-purple-700 rounded-lg font-medium text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
          {loading ? "Sending..." : "Send"}
        </button>
      </div>

      <div>
        <button
          onClick={() => setShowHeaders(!showHeaders)}
          className="flex items-center gap-2 text-sm font-medium text-gray-300"
        >
          {showHeaders ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          Headers
          {headers.length > 0 && <span className="text-xs text-gray-500">({headers.length})</span>}
        </button>
        {showHeaders && (
          <div className="mt-2 space-y-2 pl-2">
            {headers.map((h, i) => (
              <div key={i} className="flex gap-2 items-center">
                <input
                  type="text"
                  value={h.key}
                  onChange={(e) => updateHeader(i, "key", e.target.value)}
                  placeholder="Header-Name"
                  className={`flex-1 ${inputCls}`}
                />
                <input
                  type="text"
                  value={h.value}
                  onChange={(e) => updateHeader(i, "value", e.target.value)}
                  placeholder="value"
                  className={`flex-1 ${inputCls}`}
                />
                <button onClick={() => removeHeader(i)} className="p-1.5 text-red-400 hover:text-red-300">
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <button
              onClick={addHeader}
              className="flex items-center gap-1 text-xs text-purple-400 hover:text-purple-300"
            >
              <Plus size={12} /> Add Header
            </button>
          </div>
        )}
      </div>

      {(method === "POST" || method === "PUT" || method === "PATCH") && (
        <div>
          <button
            onClick={() => setShowBody(!showBody)}
            className="flex items-center gap-2 text-sm font-medium text-gray-300"
          >
            {showBody ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            Request Body
          </button>
          {showBody && (
            <div className="mt-2">
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={6}
                className={`${inputCls} resize-none`}
                placeholder='{"key": "value"}'
              />
            </div>
          )}
        </div>
      )}

      {response && (
        <div className="border border-gray-800 rounded-lg overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2.5 bg-[#141414] border-b border-gray-800">
            <div className="flex items-center gap-4">
              <span className={`font-mono font-bold text-sm ${statusColor(response.status_code)}`}>
                {response.status_code === 0 ? "Error" : response.status_code}
              </span>
              <span className="text-xs text-gray-500">{response.elapsed_ms}ms</span>
              {response.error && <span className="text-xs text-red-400">{response.error}</span>}
            </div>
            <div className="flex gap-1">
              {["pretty", "raw", "keys"].map((view) => (
                <button
                  key={view}
                  onClick={() => setResponseView(view as any)}
                  className={`px-2.5 py-1 text-xs rounded transition-colors ${
                    responseView === view
                      ? "bg-purple-600/30 text-purple-300"
                      : "text-gray-400 hover:text-gray-300 hover:bg-gray-800"
                  }`}
                >
                  {view === "pretty" ? "Pretty" : view === "raw" ? "Raw" : "Keys"}
                </button>
              ))}
            </div>
          </div>

          <div className="max-h-96 overflow-auto">
            {responseView === "pretty" && (
              <div className="relative">
                <pre className="p-4 text-xs text-gray-300 font-mono whitespace-pre-wrap">
                  {typeof response.body === "object"
                    ? JSON.stringify(response.body, null, 2)
                    : String(response.body || "")}
                </pre>
                <button
                  onClick={() =>
                    copyToClipboard(
                      typeof response.body === "object"
                        ? JSON.stringify(response.body, null, 2)
                        : String(response.body || "")
                    )
                  }
                  className="absolute top-2 right-2 p-1.5 text-gray-500 hover:text-gray-300 bg-[#141414] rounded"
                >
                  <Copy size={14} />
                </button>
              </div>
            )}

            {responseView === "raw" && (
              <pre className="p-4 text-xs text-gray-300 font-mono whitespace-pre-wrap">
                {typeof response.body === "object"
                  ? JSON.stringify(response.body)
                  : String(response.body || "")}
              </pre>
            )}

            {responseView === "keys" && (
              <div className="p-4 space-y-1">
                <p className="text-xs text-gray-500 mb-3">
                  Click a path to copy it for use in response mapping
                </p>
                {responseKeys.length === 0 ? (
                  <p className="text-xs text-gray-500">No keys found in response</p>
                ) : (
                  responseKeys.map((path) => {
                    const val = getNestedValue(response.body, path);
                    const displayVal = typeof val === "object" ? (Array.isArray(val) ? `[${val.length} items]` : "{...}") : String(val);
                    return (
                      <button
                        key={path}
                        onClick={() => copyToClipboard(path, path)}
                        className="w-full flex items-center gap-3 px-3 py-1.5 rounded hover:bg-gray-800/50 transition-colors text-left group"
                      >
                        <code className="text-xs text-purple-400 font-mono flex-shrink-0">{path}</code>
                        <span className="text-xs text-gray-500 truncate flex-1">{displayVal}</span>
                        {copiedPath === path ? (
                          <Check size={12} className="text-green-400 flex-shrink-0" />
                        ) : (
                          <Copy size={12} className="text-gray-600 group-hover:text-gray-400 flex-shrink-0" />
                        )}
                      </button>
                    );
                  })
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
