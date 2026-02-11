"use client";

import { useEffect, useState, useCallback } from "react";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import {
  BarChart3,
  RefreshCw,
  Clock,
  PhoneIncoming,
  PhoneOff,
  PhoneForwarded,
  Timer,
  TrendingUp,
  AlertCircle,
  CheckCircle2,
  Plug,
} from "lucide-react";

interface QueueSummary {
  queue_id: string;
  queue_name: string;
  total_calls: number;
  calls_answered: number;
  calls_abandoned: number;
  calls_transferred: number;
  avg_wait_time_seconds: number;
  max_wait_time_seconds: number;
  avg_handle_time_seconds: number;
  avg_service_level_pct: number;
  avg_abandon_rate_pct: number;
  avg_answer_rate_pct: number;
  report_count: number;
}

interface TrendPoint {
  timestamp: string;
  queue_name: string;
  total_calls: number;
  calls_answered: number;
  calls_abandoned: number;
  avg_wait_time: number;
  avg_handle_time: number;
  service_level: number;
  abandon_rate: number;
}

interface ZoomStatus {
  connected: boolean;
  connection_status: string;
  last_sync: string | null;
  last_report_at: string | null;
  total_reports: number;
}

export default function ReportsPage() {
  const { authFetch, isAuthenticated, loading: authLoading } = useAuthToken();
  const { accountId } = useAccountContext();

  const [status, setStatus] = useState<ZoomStatus | null>(null);
  const [summary, setSummary] = useState<QueueSummary[]>([]);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [days, setDays] = useState(7);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!isAuthenticated || authLoading) return;
    setLoading(true);
    setError(null);
    try {
      const [statusRes, summaryRes, trendRes] = await Promise.all([
        authFetch("/api/reports/zoom/status"),
        authFetch(`/api/reports/queue-performance/summary?days=${days}`),
        authFetch(`/api/reports/queue-performance/trend?days=${days}`),
      ]);

      if (statusRes.ok) setStatus(await statusRes.json());
      if (summaryRes.ok) setSummary(await summaryRes.json());
      if (trendRes.ok) setTrend(await trendRes.json());
    } catch (e: any) {
      setError(e.message || "Failed to load report data");
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated, authLoading, authFetch, days]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleRefresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      const res = await authFetch("/api/reports/queue-performance/refresh", {
        method: "POST",
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || "Failed to refresh reports");
      }
      await fetchData();
    } catch (e: any) {
      setError(e.message || "Failed to refresh");
    } finally {
      setRefreshing(false);
    }
  };

  const formatTime = (seconds: number) => {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return `${mins}m ${secs}s`;
  };

  const formatDate = (iso: string | null) => {
    if (!iso) return "Never";
    return new Date(iso).toLocaleString();
  };

  const totals = summary.reduce(
    (acc, q) => ({
      totalCalls: acc.totalCalls + q.total_calls,
      answered: acc.answered + q.calls_answered,
      abandoned: acc.abandoned + q.calls_abandoned,
      transferred: acc.transferred + q.calls_transferred,
    }),
    { totalCalls: 0, answered: 0, abandoned: 0, transferred: 0 }
  );

  const avgServiceLevel =
    summary.length > 0
      ? summary.reduce((s, q) => s + q.avg_service_level_pct, 0) / summary.length
      : 0;
  const avgAbandonRate =
    summary.length > 0
      ? summary.reduce((s, q) => s + q.avg_abandon_rate_pct, 0) / summary.length
      : 0;
  const avgWaitTime =
    summary.length > 0
      ? summary.reduce((s, q) => s + q.avg_wait_time_seconds, 0) / summary.length
      : 0;
  const avgHandleTime =
    summary.length > 0
      ? summary.reduce((s, q) => s + q.avg_handle_time_seconds, 0) / summary.length
      : 0;

  if (loading && !status) {
    return (
      <div className="p-8 flex items-center justify-center min-h-[60vh]">
        <div className="flex items-center gap-3 text-gray-400">
          <RefreshCw className="h-5 w-5 animate-spin" />
          <span>Loading reports...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-[1400px]">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-3">
            <BarChart3 className="h-7 w-7 text-blue-400" />
            Queue Performance Reports
          </h1>
          <p className="text-sm text-gray-400 mt-1">
            Zoom Contact Center queue metrics and analytics
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
          >
            <option value={1}>Last 24 hours</option>
            <option value={3}>Last 3 days</option>
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
          <button
            onClick={handleRefresh}
            disabled={refreshing || !status?.connected}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded-lg text-sm font-medium transition-colors"
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
            {refreshing ? "Fetching..." : "Refresh Now"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-900/20 border border-red-800 rounded-lg flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-red-400 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-red-300 text-sm font-medium">Error</p>
            <p className="text-red-400 text-sm mt-1">{error}</p>
          </div>
        </div>
      )}

      <div className="mb-6 p-4 bg-[#141414] border border-gray-800 rounded-lg flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            {status?.connected ? (
              <>
                <div className="relative">
                  <div className="w-2.5 h-2.5 rounded-full bg-green-500" />
                  <div className="absolute inset-0 w-2.5 h-2.5 rounded-full bg-green-500 animate-ping opacity-50" />
                </div>
                <span className="text-green-400 text-sm font-medium">Connected</span>
              </>
            ) : (
              <>
                <div className="w-2.5 h-2.5 rounded-full bg-gray-500" />
                <span className="text-gray-400 text-sm">Not Connected</span>
              </>
            )}
          </div>
          <span className="text-gray-600">|</span>
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <Clock className="h-4 w-4" />
            <span>Last sync: {formatDate(status?.last_sync ?? null)}</span>
          </div>
          <span className="text-gray-600">|</span>
          <span className="text-sm text-gray-400">{status?.total_reports ?? 0} total reports</span>
        </div>
        {!status?.connected && (
          <a
            href="/dashboard/integrations"
            className="flex items-center gap-2 px-3 py-1.5 bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 rounded-lg text-sm transition-colors"
          >
            <Plug className="h-4 w-4" />
            Connect Zoom
          </a>
        )}
      </div>

      {!status?.connected && summary.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 bg-[#141414] border border-gray-800 rounded-lg">
          <BarChart3 className="h-16 w-16 text-gray-600 mb-4" />
          <h3 className="text-lg font-semibold text-gray-300 mb-2">
            No Report Data Yet
          </h3>
          <p className="text-gray-500 text-sm max-w-md text-center mb-6">
            Connect your Zoom Contact Center account in the Integrations page to
            start receiving hourly queue performance reports automatically.
          </p>
          <a
            href="/dashboard/integrations"
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors"
          >
            <Plug className="h-4 w-4" />
            Go to Integrations
          </a>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <MetricCard
              title="Total Calls"
              value={totals.totalCalls.toLocaleString()}
              icon={<PhoneIncoming className="h-6 w-6 text-blue-400" />}
              subtitle={`${totals.answered} answered`}
            />
            <MetricCard
              title="Avg Wait Time"
              value={formatTime(avgWaitTime)}
              icon={<Timer className="h-6 w-6 text-amber-400" />}
              subtitle={`Handle: ${formatTime(avgHandleTime)}`}
            />
            <MetricCard
              title="Service Level"
              value={`${avgServiceLevel.toFixed(1)}%`}
              icon={<TrendingUp className="h-6 w-6 text-green-400" />}
              color={avgServiceLevel >= 80 ? "green" : avgServiceLevel >= 60 ? "amber" : "red"}
            />
            <MetricCard
              title="Abandon Rate"
              value={`${avgAbandonRate.toFixed(1)}%`}
              icon={<PhoneOff className="h-6 w-6 text-red-400" />}
              color={avgAbandonRate <= 5 ? "green" : avgAbandonRate <= 10 ? "amber" : "red"}
            />
          </div>

          {summary.length > 0 && (
            <div className="bg-[#141414] border border-gray-800 rounded-lg mb-8">
              <div className="p-5 border-b border-gray-800">
                <h2 className="text-lg font-semibold">Queue Summary</h2>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-800 text-gray-400">
                      <th className="text-left py-3 px-5 font-medium">Queue</th>
                      <th className="text-right py-3 px-5 font-medium">Total Calls</th>
                      <th className="text-right py-3 px-5 font-medium">Answered</th>
                      <th className="text-right py-3 px-5 font-medium">Abandoned</th>
                      <th className="text-right py-3 px-5 font-medium">Transferred</th>
                      <th className="text-right py-3 px-5 font-medium">Avg Wait</th>
                      <th className="text-right py-3 px-5 font-medium">Avg Handle</th>
                      <th className="text-right py-3 px-5 font-medium">Service Level</th>
                      <th className="text-right py-3 px-5 font-medium">Abandon Rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.map((q) => (
                      <tr
                        key={q.queue_id}
                        className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors"
                      >
                        <td className="py-3 px-5 font-medium text-gray-200">
                          {q.queue_name}
                        </td>
                        <td className="text-right py-3 px-5 text-gray-300">
                          {q.total_calls.toLocaleString()}
                        </td>
                        <td className="text-right py-3 px-5 text-green-400">
                          {q.calls_answered.toLocaleString()}
                        </td>
                        <td className="text-right py-3 px-5 text-red-400">
                          {q.calls_abandoned.toLocaleString()}
                        </td>
                        <td className="text-right py-3 px-5 text-gray-300">
                          {q.calls_transferred.toLocaleString()}
                        </td>
                        <td className="text-right py-3 px-5 text-gray-300">
                          {formatTime(q.avg_wait_time_seconds)}
                        </td>
                        <td className="text-right py-3 px-5 text-gray-300">
                          {formatTime(q.avg_handle_time_seconds)}
                        </td>
                        <td className="text-right py-3 px-5">
                          <span
                            className={`${
                              q.avg_service_level_pct >= 80
                                ? "text-green-400"
                                : q.avg_service_level_pct >= 60
                                ? "text-amber-400"
                                : "text-red-400"
                            }`}
                          >
                            {q.avg_service_level_pct.toFixed(1)}%
                          </span>
                        </td>
                        <td className="text-right py-3 px-5">
                          <span
                            className={`${
                              q.avg_abandon_rate_pct <= 5
                                ? "text-green-400"
                                : q.avg_abandon_rate_pct <= 10
                                ? "text-amber-400"
                                : "text-red-400"
                            }`}
                          >
                            {q.avg_abandon_rate_pct.toFixed(1)}%
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {summary.length > 0 && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
              <div className="bg-[#141414] border border-gray-800 rounded-lg p-5">
                <h3 className="text-sm font-semibold text-gray-300 mb-4">
                  Calls by Queue
                </h3>
                <div className="space-y-3">
                  {summary.map((q) => {
                    const maxCalls = Math.max(...summary.map((s) => s.total_calls), 1);
                    return (
                      <div key={q.queue_id}>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm text-gray-300 truncate max-w-[200px]">
                            {q.queue_name}
                          </span>
                          <span className="text-sm text-gray-400">
                            {q.total_calls.toLocaleString()}
                          </span>
                        </div>
                        <div className="h-2.5 bg-gray-800 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-blue-500 rounded-full transition-all duration-500"
                            style={{
                              width: `${(q.total_calls / maxCalls) * 100}%`,
                            }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="bg-[#141414] border border-gray-800 rounded-lg p-5">
                <h3 className="text-sm font-semibold text-gray-300 mb-4">
                  Answer vs Abandon Rate
                </h3>
                <div className="space-y-4">
                  {summary.map((q) => (
                    <div key={q.queue_id}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm text-gray-300 truncate max-w-[200px]">
                          {q.queue_name}
                        </span>
                      </div>
                      <div className="h-3 bg-gray-800 rounded-full overflow-hidden flex">
                        <div
                          className="h-full bg-green-500 transition-all duration-500"
                          style={{ width: `${q.avg_answer_rate_pct}%` }}
                          title={`Answered: ${q.avg_answer_rate_pct.toFixed(1)}%`}
                        />
                        <div
                          className="h-full bg-red-500 transition-all duration-500"
                          style={{ width: `${q.avg_abandon_rate_pct}%` }}
                          title={`Abandoned: ${q.avg_abandon_rate_pct.toFixed(1)}%`}
                        />
                      </div>
                      <div className="flex items-center gap-4 mt-1">
                        <span className="text-xs text-green-400">
                          {q.avg_answer_rate_pct.toFixed(1)}% answered
                        </span>
                        <span className="text-xs text-red-400">
                          {q.avg_abandon_rate_pct.toFixed(1)}% abandoned
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {trend.length > 0 && (
            <div className="bg-[#141414] border border-gray-800 rounded-lg mb-8">
              <div className="p-5 border-b border-gray-800">
                <h2 className="text-lg font-semibold">Hourly Trend</h2>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-800 text-gray-400">
                      <th className="text-left py-3 px-5 font-medium">Time</th>
                      <th className="text-left py-3 px-5 font-medium">Queue</th>
                      <th className="text-right py-3 px-5 font-medium">Calls</th>
                      <th className="text-right py-3 px-5 font-medium">Answered</th>
                      <th className="text-right py-3 px-5 font-medium">Abandoned</th>
                      <th className="text-right py-3 px-5 font-medium">Avg Wait</th>
                      <th className="text-right py-3 px-5 font-medium">Service Level</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trend.slice(-50).map((t, i) => (
                      <tr
                        key={i}
                        className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors"
                      >
                        <td className="py-3 px-5 text-gray-300 whitespace-nowrap">
                          {t.timestamp
                            ? new Date(t.timestamp).toLocaleString(undefined, {
                                month: "short",
                                day: "numeric",
                                hour: "2-digit",
                                minute: "2-digit",
                              })
                            : "-"}
                        </td>
                        <td className="py-3 px-5 text-gray-200">{t.queue_name}</td>
                        <td className="text-right py-3 px-5 text-gray-300">
                          {t.total_calls}
                        </td>
                        <td className="text-right py-3 px-5 text-green-400">
                          {t.calls_answered}
                        </td>
                        <td className="text-right py-3 px-5 text-red-400">
                          {t.calls_abandoned}
                        </td>
                        <td className="text-right py-3 px-5 text-gray-300">
                          {formatTime(t.avg_wait_time)}
                        </td>
                        <td className="text-right py-3 px-5">
                          <span
                            className={`${
                              t.service_level >= 80
                                ? "text-green-400"
                                : t.service_level >= 60
                                ? "text-amber-400"
                                : "text-red-400"
                            }`}
                          >
                            {t.service_level.toFixed(1)}%
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {trend.length > 50 && (
                <div className="p-3 text-center text-sm text-gray-500 border-t border-gray-800">
                  Showing latest 50 of {trend.length} entries
                </div>
              )}
            </div>
          )}

          {summary.length === 0 && status?.connected && (
            <div className="flex flex-col items-center justify-center py-16 bg-[#141414] border border-gray-800 rounded-lg">
              <Clock className="h-12 w-12 text-gray-600 mb-4" />
              <h3 className="text-lg font-semibold text-gray-300 mb-2">
                Waiting for Data
              </h3>
              <p className="text-gray-500 text-sm max-w-md text-center mb-4">
                Your Zoom Contact Center is connected. Reports will be fetched
                automatically every hour, or you can click "Refresh Now" to fetch immediately.
              </p>
              <button
                onClick={handleRefresh}
                disabled={refreshing}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors"
              >
                <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
                {refreshing ? "Fetching..." : "Fetch Now"}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function MetricCard({
  title,
  value,
  icon,
  subtitle,
  color,
}: {
  title: string;
  value: string;
  icon: React.ReactNode;
  subtitle?: string;
  color?: "green" | "amber" | "red";
}) {
  const colorClass =
    color === "green"
      ? "text-green-400"
      : color === "amber"
      ? "text-amber-400"
      : color === "red"
      ? "text-red-400"
      : "text-gray-100";

  return (
    <div className="bg-[#141414] border border-gray-800 rounded-lg p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-gray-400">{title}</span>
        {icon}
      </div>
      <div className={`text-2xl font-bold ${colorClass}`}>{value}</div>
      {subtitle && (
        <p className="text-xs text-gray-500 mt-1">{subtitle}</p>
      )}
    </div>
  );
}
