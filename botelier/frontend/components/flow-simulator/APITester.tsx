"use client";

import { useState } from "react";
import { Send, Loader2, CheckCircle, XCircle } from "lucide-react";

interface APITesterProps {
  initialUrl?: string;
  initialMethod?: string;
  initialHeaders?: Record<string, string>;
  initialBody?: string;
  variables?: Record<string, unknown>;
}

export default function APITester({
  initialUrl = "",
  initialMethod = "GET",
  initialHeaders = {},
  initialBody = "",
  variables = {},
}: APITesterProps) {
  const [method, setMethod] = useState(initialMethod);
  const [url, setUrl] = useState(initialUrl);
  const [headers, setHeaders] = useState(JSON.stringify(initialHeaders, null, 2));
  const [body, setBody] = useState(initialBody);
  const [testVariables, setTestVariables] = useState<Record<string, string>>(
    Object.fromEntries(
      Object.entries(variables).map(([k, v]) => [k, String(v)])
    )
  );
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<{
    status_code: number;
    response_body: unknown;
    response_headers: Record<string, string>;
    resolved_url: string;
    resolved_body?: string;
    error?: string;
  } | null>(null);

  const extractVariables = (text: string): string[] => {
    const matches = text.match(/\{\{(\w+)\}\}/g) || [];
    return [...new Set(matches.map((m) => m.slice(2, -2)))];
  };

  const allVariables = [
    ...extractVariables(url),
    ...extractVariables(body),
    ...Object.keys(testVariables),
  ].filter((v, i, arr) => arr.indexOf(v) === i);

  const handleTest = async () => {
    setIsLoading(true);
    setResult(null);

    try {
      let parsedHeaders = {};
      try {
        parsedHeaders = headers ? JSON.parse(headers) : {};
      } catch {
        setResult({
          status_code: 0,
          response_body: null,
          response_headers: {},
          resolved_url: url,
          error: "Invalid JSON in headers",
        });
        setIsLoading(false);
        return;
      }

      const response = await fetch("/api/simulate/test-api", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          method,
          url,
          headers: parsedHeaders,
          body: body || undefined,
          variables: testVariables,
        }),
      });

      const data = await response.json();
      setResult(data);
    } catch (err) {
      setResult({
        status_code: 0,
        response_body: null,
        response_headers: {},
        resolved_url: url,
        error: err instanceof Error ? err.message : "Failed to test API",
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="bg-[#0f0f0f] rounded-lg border border-[#2a2a2a] overflow-hidden">
      <div className="p-4 border-b border-[#2a2a2a]">
        <h3 className="text-lg font-medium text-white mb-4">API Endpoint Tester</h3>

        <div className="space-y-4">
          <div className="flex gap-2">
            <select
              value={method}
              onChange={(e) => setMethod(e.target.value)}
              className="bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
            >
              <option value="GET">GET</option>
              <option value="POST">POST</option>
              <option value="PUT">PUT</option>
              <option value="PATCH">PATCH</option>
              <option value="DELETE">DELETE</option>
            </select>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://api.example.com/endpoint/{{variable}}"
              className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-2 text-sm text-gray-200 font-mono focus:outline-none focus:border-blue-500"
            />
          </div>

          {allVariables.length > 0 && (
            <div className="bg-[#1a1a1a] rounded-lg p-3">
              <label className="block text-xs text-gray-500 mb-2">
                Test Variables
              </label>
              <div className="grid grid-cols-2 gap-2">
                {allVariables.map((varName) => (
                  <div key={varName} className="flex items-center gap-2">
                    <span className="text-xs text-gray-400 font-mono bg-[#2a2a2a] px-2 py-1 rounded">
                      {`{{${varName}}}`}
                    </span>
                    <input
                      type="text"
                      value={testVariables[varName] || ""}
                      onChange={(e) =>
                        setTestVariables((prev) => ({
                          ...prev,
                          [varName]: e.target.value,
                        }))
                      }
                      placeholder="value"
                      className="flex-1 bg-[#2a2a2a] border border-[#3a3a3a] rounded px-2 py-1 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Headers (JSON)
            </label>
            <textarea
              value={headers}
              onChange={(e) => setHeaders(e.target.value)}
              rows={3}
              placeholder='{"Content-Type": "application/json"}'
              className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-2 text-sm text-gray-200 font-mono focus:outline-none focus:border-blue-500 resize-none"
            />
          </div>

          {["POST", "PUT", "PATCH"].includes(method) && (
            <div>
              <label className="block text-xs text-gray-500 mb-1">
                Request Body
              </label>
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={4}
                placeholder='{"key": "{{variable}}"}'
                className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-2 text-sm text-gray-200 font-mono focus:outline-none focus:border-blue-500 resize-none"
              />
            </div>
          )}

          <button
            onClick={handleTest}
            disabled={isLoading || !url}
            className="flex items-center justify-center gap-2 w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium py-2 px-4 rounded transition-colors"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Testing...
              </>
            ) : (
              <>
                <Send className="w-4 h-4" />
                Send Request
              </>
            )}
          </button>
        </div>
      </div>

      {result && (
        <div className="p-4 border-t border-[#2a2a2a] bg-[#0a0a0a]">
          <div className="flex items-center gap-2 mb-3">
            {result.error ? (
              <>
                <XCircle className="w-5 h-5 text-red-500" />
                <span className="text-red-400 font-medium">Error</span>
              </>
            ) : result.status_code >= 200 && result.status_code < 300 ? (
              <>
                <CheckCircle className="w-5 h-5 text-green-500" />
                <span className="text-green-400 font-medium">
                  {result.status_code} OK
                </span>
              </>
            ) : (
              <>
                <XCircle className="w-5 h-5 text-yellow-500" />
                <span className="text-yellow-400 font-medium">
                  {result.status_code}
                </span>
              </>
            )}
          </div>

          {result.resolved_url && result.resolved_url !== url && (
            <div className="mb-3">
              <label className="block text-xs text-gray-500 mb-1">
                Resolved URL
              </label>
              <code className="block text-sm text-gray-300 font-mono bg-[#1a1a1a] p-2 rounded break-all">
                {result.resolved_url}
              </code>
            </div>
          )}

          {result.error ? (
            <div className="text-red-400 text-sm">{result.error}</div>
          ) : (
            <div>
              <label className="block text-xs text-gray-500 mb-1">
                Response Body
              </label>
              <pre className="text-sm text-gray-300 font-mono bg-[#1a1a1a] p-3 rounded overflow-x-auto max-h-64">
                {typeof result.response_body === "string"
                  ? result.response_body
                  : JSON.stringify(result.response_body, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
