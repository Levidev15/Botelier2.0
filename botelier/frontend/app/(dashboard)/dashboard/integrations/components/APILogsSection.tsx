"use client";

import { Fragment, useEffect, useState } from "react";
import { AlertCircle, ChevronDown, ChevronRight, Loader2, RefreshCcw } from "lucide-react";

interface APILogsSectionProps {
  accountId: string;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
}

interface APILogRow {
  id: string;
  source_label: string;
  channel: string;
  method: string | null;
  endpoint_called: string | null;
  status_code: number | null;
  success: boolean;
  latency_ms: number | null;
  error_type: string | null;
  error_message: string | null;
  request_id: string;
  call_sid: string | null;
  flow_tool_id: string | null;
  node_id: string | null;
  action_id: string | null;
  integration_id: string | null;
  response_metadata: Record<string, unknown>;
  called_at: string | null;
}

interface APILogResponse {
  items: APILogRow[];
  page: number;
  per_page: number;
  total: number;
  summary: {
    total: number;
    successful: number;
    failed: number;
    avg_latency_ms: number;
    last_called_at: string | null;
    last_error: string | null;
  };
}

const statusClass = (success: boolean) =>
  success ? "text-green-300 bg-green-950/40 border-green-900" : "text-red-300 bg-red-950/40 border-red-900";

const formatDate = (value: string | null) => {
  if (!value) return "-";
  return new Date(value).toLocaleString();
};

export default function APILogsSection({ accountId, authFetch }: APILogsSectionProps) {
  const [data, setData] = useState<APILogResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [success, setSuccess] = useState("all");
  const [channel, setChannel] = useState("all");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);

  const fetchLogs = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        page: String(page),
        per_page: "50",
      });
      if (success !== "all") params.set("success", success);
      if (channel !== "all") params.set("channel", channel);
      if (query.trim()) {
        const trimmed = query.trim();
        if (trimmed.startsWith("CA")) params.set("call_sid", trimmed);
        else params.set("request_id", trimmed);
      }
      const response = await authFetch(`/api/integrations/account/${accountId}/api-logs?${params}`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Failed to load API logs");
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load API logs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, success, channel, page]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.per_page)) : 1;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-3">
        <div className="rounded-lg border border-gray-800 bg-[#141414] p-3">
          <p className="text-xs text-gray-500">Total</p>
          <p className="text-xl font-semibold text-white">{data?.summary.total ?? 0}</p>
        </div>
        <div className="rounded-lg border border-gray-800 bg-[#141414] p-3">
          <p className="text-xs text-gray-500">Failures</p>
          <p className="text-xl font-semibold text-red-300">{data?.summary.failed ?? 0}</p>
        </div>
        <div className="rounded-lg border border-gray-800 bg-[#141414] p-3">
          <p className="text-xs text-gray-500">Avg latency</p>
          <p className="text-xl font-semibold text-white">{data?.summary.avg_latency_ms ?? 0}ms</p>
        </div>
        <div className="rounded-lg border border-gray-800 bg-[#141414] p-3">
          <p className="text-xs text-gray-500">Last call</p>
          <p className="text-sm font-medium text-white truncate">{formatDate(data?.summary.last_called_at ?? null)}</p>
        </div>
      </div>

      <div className="rounded-lg border border-gray-800 bg-[#141414]">
        <div className="flex flex-wrap items-center gap-2 p-3 border-b border-gray-800">
          <select
            value={success}
            onChange={(e) => {
              setSuccess(e.target.value);
              setPage(1);
            }}
            className="bg-[#1a1a1a] border border-gray-700 rounded px-3 py-2 text-sm text-white"
          >
            <option value="all">All statuses</option>
            <option value="true">Success</option>
            <option value="false">Failures</option>
          </select>
          <select
            value={channel}
            onChange={(e) => {
              setChannel(e.target.value);
              setPage(1);
            }}
            className="bg-[#1a1a1a] border border-gray-700 rounded px-3 py-2 text-sm text-white"
          >
            <option value="all">All channels</option>
            <option value="flow">Flow</option>
            <option value="voice">Voice</option>
            <option value="sms">SMS</option>
            <option value="test">Test</option>
            <option value="api">API</option>
          </select>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                setPage(1);
                fetchLogs();
              }
            }}
            placeholder="Call SID or request ID"
            className="min-w-56 flex-1 bg-[#1a1a1a] border border-gray-700 rounded px-3 py-2 text-sm text-white font-mono"
          />
          <button
            onClick={fetchLogs}
            disabled={loading}
            className="inline-flex items-center gap-2 px-3 py-2 rounded bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-sm"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
            Refresh
          </button>
        </div>

        {error && (
          <div className="m-3 flex items-start gap-2 rounded border border-red-900/70 bg-red-950/30 px-3 py-2 text-sm text-red-300">
            <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-gray-500 border-b border-gray-800">
              <tr>
                <th className="w-8 px-3 py-2"></th>
                <th className="px-3 py-2 text-left">Time</th>
                <th className="px-3 py-2 text-left">Source</th>
                <th className="px-3 py-2 text-left">Channel</th>
                <th className="px-3 py-2 text-left">Method</th>
                <th className="px-3 py-2 text-left">Endpoint</th>
                <th className="px-3 py-2 text-left">Status</th>
                <th className="px-3 py-2 text-left">Latency</th>
                <th className="px-3 py-2 text-left">Request ID</th>
              </tr>
            </thead>
            <tbody>
              {loading && !data && (
                <tr>
                  <td colSpan={9} className="px-3 py-8 text-center text-gray-500">
                    Loading API logs...
                  </td>
                </tr>
              )}
              {data?.items.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-3 py-8 text-center text-gray-500">
                    No API requests match these filters.
                  </td>
                </tr>
              )}
              {data?.items.map((row) => (
                <Fragment key={row.id}>
                  <tr className="border-b border-gray-900 hover:bg-[#181818]">
                    <td className="px-3 py-2">
                      <button
                        onClick={() => setExpandedId(expandedId === row.id ? null : row.id)}
                        className="text-gray-500 hover:text-gray-300"
                      >
                        {expandedId === row.id ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      </button>
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-gray-300">{formatDate(row.called_at)}</td>
                    <td className="px-3 py-2 text-white">{row.source_label}</td>
                    <td className="px-3 py-2 text-gray-400">{row.channel}</td>
                    <td className="px-3 py-2 font-mono text-gray-300">{row.method || "-"}</td>
                    <td className="px-3 py-2 font-mono text-xs text-gray-400 max-w-xs truncate">{row.endpoint_called || "-"}</td>
                    <td className="px-3 py-2">
                      <span className={`inline-flex px-2 py-0.5 rounded border text-xs ${statusClass(row.success)}`}>
                        {row.status_code || (row.success ? "OK" : "ERR")}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-gray-300">{row.latency_ms ?? "-"}ms</td>
                    <td className="px-3 py-2 font-mono text-xs text-gray-500">{row.request_id.slice(0, 12)}</td>
                  </tr>
                  {expandedId === row.id && (
                    <tr className="border-b border-gray-900 bg-[#101010]">
                      <td></td>
                      <td colSpan={8} className="px-3 py-3">
                        <div className="grid grid-cols-2 gap-3 text-xs">
                          <div>
                            <p className="text-gray-500 mb-1">Context</p>
                            <pre className="rounded bg-[#0a0a0a] border border-gray-900 p-2 text-gray-300 whitespace-pre-wrap">
{JSON.stringify({
  request_id: row.request_id,
  call_sid: row.call_sid,
  flow_tool_id: row.flow_tool_id,
  node_id: row.node_id,
  action_id: row.action_id,
  integration_id: row.integration_id,
}, null, 2)}
                            </pre>
                          </div>
                          <div>
                            <p className="text-gray-500 mb-1">Response metadata</p>
                            <pre className="rounded bg-[#0a0a0a] border border-gray-900 p-2 text-gray-300 whitespace-pre-wrap">
{JSON.stringify(row.response_metadata || {}, null, 2)}
                            </pre>
                          </div>
                          {row.error_message && (
                            <div className="col-span-2 rounded border border-red-900/60 bg-red-950/20 p-2 text-red-200">
                              {row.error_type ? `${row.error_type}: ` : ""}{row.error_message}
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between px-3 py-2 border-t border-gray-800 text-xs text-gray-500">
          <span>Page {page} of {totalPages} - {data?.total ?? 0} requests</span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page <= 1 || loading}
              className="px-2 py-1 rounded border border-gray-800 disabled:opacity-40 hover:bg-gray-800"
            >
              Previous
            </button>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || loading}
              className="px-2 py-1 rounded border border-gray-800 disabled:opacity-40 hover:bg-gray-800"
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
