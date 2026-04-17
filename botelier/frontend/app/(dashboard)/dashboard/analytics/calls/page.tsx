"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import { SlidersHorizontal, Loader2, FileDown } from "lucide-react";
import {
  ResponsiveContainer,
  LineChart, Line,
  BarChart, Bar,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip,
} from "recharts";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import StatCard from "@/components/analytics/StatCard";
import DashboardWidget from "@/components/analytics/DashboardWidget";
import DateRangePicker, { DateRange } from "@/components/analytics/DateRangePicker";
import AssistantFilter from "@/components/analytics/AssistantFilter";
import CustomizePanel from "@/components/analytics/CustomizePanel";
import DrilldownPanel, { TranscriptCallLog } from "@/components/analytics/DrilldownPanel";
import { useWidgetLayout, WidgetDef } from "@/components/analytics/useWidgetLayout";
import TranscriptModal from "@/app/(dashboard)/dashboard/call-logs/components/TranscriptModal";
import TimezonePicker, { loadTimezone, saveTimezone } from "@/components/analytics/TimezonePicker";

const WIDGETS: WidgetDef[] = [
  { id: "total_calls", label: "Total Calls", defaultVisible: true },
  { id: "ai_handled", label: "AI Handled", defaultVisible: true },
  { id: "early_ended", label: "Dropped Before AI", defaultVisible: true },
  { id: "unresolved", label: "Unresolved", defaultVisible: true },
  { id: "completion_rate", label: "Completion Rate", defaultVisible: true },
  { id: "transfer_rate", label: "Transfer Rate", defaultVisible: true },
  { id: "avg_duration", label: "Avg AI Duration", defaultVisible: true },
  { id: "outbound_duration", label: "Avg Outbound Duration", defaultVisible: true },
  { id: "avg_quality", label: "Avg Quality Score", defaultVisible: true },
  { id: "volume_chart", label: "Call Volume Over Time", defaultVisible: true },
  { id: "hour_chart", label: "Calls by Hour of Day", defaultVisible: true },
  { id: "status_chart", label: "Status Breakdown", defaultVisible: true },
  { id: "disposition_chart", label: "Disposition Breakdown", defaultVisible: true },
  { id: "assistant_chart", label: "Calls by Assistant", defaultVisible: true },
  { id: "acw_resolution", label: "ACW Resolution Status", defaultVisible: true },
  { id: "acw_score_dist", label: "Quality Score Distribution", defaultVisible: true },
];

const CHART_COLORS = ["#3b82f6", "#8b5cf6", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4", "#ec4899", "#84cc16"];
const STATUS_COLORS: Record<string, string> = {
  completed: "#22c55e",
  ended_early: "#f97316",
  in_progress: "#3b82f6",
  failed: "#ef4444",
  no_answer: "#f59e0b",
  busy: "#f97316",
  canceled: "#6b7280",
  initiated: "#8b5cf6",
  ringing: "#06b6d4",
};

function fmtDuration(s: number) {
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}m ${sec}s`;
}

function defaultDateRange(): DateRange {
  const now = new Date();
  const from = new Date(now.getTime() - 7 * 86_400_000);
  from.setHours(0, 0, 0, 0);
  const to = new Date(now);
  to.setHours(23, 59, 59, 999);
  return { from, to };
}

interface AnalyticsData {
  date_from: string;
  date_to: string;
  overview: {
    total_calls: number;
    completed: number;
    // Task #97 partition (canonical):
    ai_handled_count: number;
    ended_early_count: number;
    missed_count: number;
    failed_count: number;
    unresolved_count: number;
    unresolved_rate: number;
    unresolved_breakdown?: {
      no_caller_audio: number;
      dropped_pre_greeting: number;
      other: number;
    };
    silent_caller_breakdown?: {
      by_assistant: { assistant_id: string; assistant_name: string; count: number }[];
      by_phone: { phone_number_id: string; phone_number: string; count: number }[];
    };
    partition_integrity_ok: boolean;
    partition_counts_by_status: Record<string, number>;
    // Legacy aliases (deprecated — kept this release):
    ai_handled_calls: number;
    ai_handled_rate: number;
    missed: number;
    failed: number;
    transferred: number;
    ended_early_calls: number;
    ended_early_rate: number;
    completion_rate: number;
    transfer_rate: number;
    avg_duration_seconds: number;
    total_duration_seconds: number;
    avg_ai_duration_seconds: number;
    total_ai_duration_seconds: number;
    avg_outbound_duration_seconds: number;
    total_outbound_duration_seconds: number;
    outbound_calls_count: number;
  };
  volume_by_day: { date: string; calls: number }[];
  calls_by_hour: { hour: number; calls: number }[];
  status_distribution: { status: string; count: number }[];
  by_assistant: { assistant_id: string; assistant_name: string; calls: number; silent_caller_count?: number }[];
  dispositions: { disposition_id: string; name: string; color: string | null; count: number }[];
  acw: {
    acw_completed: number;
    acw_completion_rate: number;
    avg_quality_score: number | null;
    min_quality_score: number | null;
    max_quality_score: number | null;
    resolution_distribution: { resolution: string; count: number }[];
    score_distribution: { range: string; count: number }[];
  };
}

interface TooltipPayloadEntry {
  name?: string;
  value?: string | number;
  color?: string;
}
interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
  label?: string | number;
}

const CustomTooltipContent = ({ active, payload, label }: CustomTooltipProps) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#252525] border border-gray-700 rounded-lg px-3 py-2 text-sm shadow-lg">
      <p className="text-gray-400 mb-1">{String(label)}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color }} className="font-medium">
          {p.name}: {p.value}
        </p>
      ))}
    </div>
  );
};

// Task #100 — by-assistant chart tooltip with silent-caller rate so operators
// can spot a single assistant misconfigured for silent-line drops at a glance.
interface AssistantBarTooltipPayload {
  payload?: {
    assistant_name?: string;
    calls?: number;
    silent_caller_count?: number;
  };
}
interface AssistantBarTooltipProps {
  active?: boolean;
  payload?: AssistantBarTooltipPayload[];
}
const AssistantBarTooltip = ({ active, payload }: AssistantBarTooltipProps) => {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  const calls = row.calls ?? 0;
  const silent = row.silent_caller_count ?? 0;
  const rate = calls > 0 ? ((silent / calls) * 100).toFixed(1) : "0.0";
  return (
    <div className="bg-[#252525] border border-gray-700 rounded-lg px-3 py-2 text-sm shadow-lg min-w-[200px]">
      <p className="text-gray-200 font-medium mb-1">{row.assistant_name ?? "—"}</p>
      <p className="text-green-400">Calls: {calls}</p>
      {silent > 0 && (
        <p className="text-yellow-400 mt-0.5" title="Silent-caller drops: AI greeted but caller never spoke">
          Silent caller: {silent} ({rate}%)
        </p>
      )}
    </div>
  );
};


export default function CallAnalyticsPage() {
  const { accountId, accountName } = useAccountContext();
  const { authFetch } = useAuthToken();
  const [dateRange, setDateRange] = useState<DateRange>(defaultDateRange);
  const [assistantIds, setAssistantIds] = useState<string[]>([]);
  const [retryKey, setRetryKey] = useState(0);
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [customizeOpen, setCustomizeOpen] = useState(false);
  const [timezone, setTimezone] = useState<string>("UTC");
  const { visibility, toggle, resetDefaults, isVisible } = useWidgetLayout("call_analytics", WIDGETS);

  useEffect(() => {
    setTimezone(loadTimezone());
  }, []);

  // Drilldown state
  const [drilldown, setDrilldown] = useState<{ metric: string; label: string; timezone?: string } | null>(null);

  // Transcript state (fetched on demand from drilldown panel)
  const [transcriptLog, setTranscriptLog] = useState<TranscriptCallLog | null>(null);
  const [transcriptLoading, setTranscriptLoading] = useState(false);

  useEffect(() => {
    if (!accountId) return;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({
      account_id: accountId,
      date_from: dateRange.from.toISOString(),
      date_to: dateRange.to.toISOString(),
      timezone,
    });
    assistantIds.forEach((id) => params.append("assistant_ids", id));
    authFetch(`/api/analytics/calls?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error(`Failed to load analytics (${r.status})`);
        return r.json();
      })
      .then(setData)
      .catch((err) => {
        console.error(err);
        setError(err.message || "Failed to load analytics");
      })
      .finally(() => setLoading(false));
  }, [accountId, dateRange, assistantIds, timezone, retryKey]);

  const volumeData = useMemo(() => {
    if (!data) return [];
    return data.volume_by_day.map((d) => ({
      ...d,
      // Append T00:00:00 so JS treats this as local midnight (not UTC midnight)
      // which prevents the off-by-one-day issue in non-UTC browsers.
      date: new Date(d.date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    }));
  }, [data]);

  const hourData = useMemo(() => {
    if (!data) return [];
    const full = Array.from({ length: 24 }, (_, i) => ({ hour: i, calls: 0, label: `${i}:00` }));
    data.calls_by_hour.forEach((h) => {
      full[h.hour].calls = h.calls;
    });
    return full;
  }, [data]);

  const openDrilldown = useCallback((metric: string, label: string) => {
    setDrilldown({ metric, label });
  }, []);

  const handleExportReport = useCallback(() => {
    if (!accountId) return;
    const p = new URLSearchParams({
      account_id: accountId,
      date_from: dateRange.from.toISOString(),
      date_to: dateRange.to.toISOString(),
      tz: timezone,
      account_name: accountName || "",
    });
    window.open(`/dashboard/analytics/calls/report?${p}`, "_blank");
  }, [accountId, dateRange, timezone, accountName]);

  const handleViewTranscript = useCallback(
    async (logId: string) => {
      if (!accountId) return;
      setTranscriptLoading(true);
      try {
        const r = await authFetch(`/api/call-logs/${logId}?account_id=${accountId}`);
        if (!r.ok) throw new Error("Failed to load transcript");
        const log = await r.json();
        setTranscriptLog(log);
      } catch {
        // silently fail — transcript unavailable
      } finally {
        setTranscriptLoading(false);
      }
    },
    [accountId]
  );

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-gray-500" />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4">
        <p className="text-red-400">{error}</p>
        <button
          onClick={() => setRetryKey((k) => k + 1)}
          className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 rounded-lg text-white transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  const o = data?.overview;

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Call Analytics</h1>
          <p className="text-sm text-gray-400 mt-1">
            {o?.total_calls ?? 0} calls
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <AssistantFilter selected={assistantIds} onChange={setAssistantIds} />
          <DateRangePicker value={dateRange} onChange={setDateRange} />
          <TimezonePicker
            value={timezone}
            onChange={(tz) => { setTimezone(tz); saveTimezone(tz); }}
          />
          <button
            onClick={handleExportReport}
            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-[#1a1a1a] border border-gray-700 rounded-lg text-gray-300 hover:text-gray-100 hover:border-gray-600 transition-colors"
            title="Open a print-ready visual report in a new tab"
          >
            <FileDown className="h-4 w-4" />
            Export Report
          </button>
          <button
            onClick={() => setCustomizeOpen(true)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-[#1a1a1a] border border-gray-700 rounded-lg text-gray-300 hover:text-gray-100 hover:border-gray-600 transition-colors"
          >
            <SlidersHorizontal className="h-4 w-4" />
            Customize
          </button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-gray-500 mb-4">
          <Loader2 className="h-4 w-4 animate-spin" /> Refreshing…
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4 mb-6">
        {isVisible("total_calls") && (
          <StatCard
            label="Total Calls"
            value={o?.total_calls ?? 0}
            sub={`${o?.completed ?? 0} completed`}
            onClick={() => openDrilldown("all", "All Calls")}
          />
        )}
        {isVisible("ai_handled") && (
          <StatCard
            label="AI Handled"
            value={o?.ai_handled_count ?? 0}
            sub={`${o?.ai_handled_rate ?? 0}% of total`}
            color="text-green-400"
            onClick={() => openDrilldown("ai_handled", "AI Handled Calls")}
          />
        )}
        {isVisible("early_ended") && (
          <StatCard
            label="Dropped Before AI"
            value={o?.ended_early_count ?? 0}
            sub={`${o?.ended_early_rate ?? 0}% of total`}
            color="text-orange-400"
            onClick={() => openDrilldown("ended_early", "Dropped Before AI")}
          />
        )}
        {isVisible("unresolved") && (
          <StatCard
            label="Unresolved"
            value={o?.unresolved_count ?? 0}
            sub={
              o?.unresolved_breakdown && o.unresolved_breakdown.no_caller_audio > 0
                ? `${o.unresolved_breakdown.no_caller_audio} silent · ${
                    (o.unresolved_breakdown.dropped_pre_greeting || 0) +
                    (o.unresolved_breakdown.other || 0)
                  } pending`
                : `${o?.unresolved_rate ?? 0}% pending finalization`
            }
            color="text-yellow-400"
            tooltip={(() => {
              const lines = [
                "Catch-all bucket. Breakdown:",
                `• No caller audio (AI greeted, caller never spoke): ${
                  o?.unresolved_breakdown?.no_caller_audio ?? 0
                }`,
                `• Dropped before greeting (sweeper-pending rows): ${
                  o?.unresolved_breakdown?.dropped_pre_greeting ?? 0
                }`,
                `• Other anomalies: ${o?.unresolved_breakdown?.other ?? 0}`,
              ];
              const topAsst = o?.silent_caller_breakdown?.by_assistant ?? [];
              const topPhone = o?.silent_caller_breakdown?.by_phone ?? [];
              if (topAsst.length > 0) {
                lines.push("", "Silent-caller drops by assistant:");
                topAsst.slice(0, 5).forEach((a) => {
                  lines.push(`  • ${a.assistant_name}: ${a.count}`);
                });
              }
              if (topPhone.length > 0) {
                lines.push("", "Silent-caller drops by phone number:");
                topPhone.slice(0, 5).forEach((p) => {
                  lines.push(`  • ${p.phone_number}: ${p.count}`);
                });
              }
              lines.push(
                "",
                "No-caller-audio rows replace what was previously mis-counted as AI Handled.",
              );
              return lines.join("\n");
            })()}
            onClick={() => openDrilldown("unresolved", "Unresolved Calls")}
          />
        )}
        {isVisible("completion_rate") && (
          <StatCard
            label="Completion Rate"
            value={`${o?.completion_rate ?? 0}%`}
            sub={`${o?.missed ?? 0} missed`}
            color="text-green-400"
            onClick={() => openDrilldown("completed", "Completed Calls")}
          />
        )}
        {isVisible("transfer_rate") && (
          <StatCard
            label="Transfer Rate"
            value={`${o?.transfer_rate ?? 0}%`}
            sub={`${o?.transferred ?? 0} transferred`}
            color="text-blue-400"
            onClick={() => openDrilldown("transferred", "Transferred Calls")}
          />
        )}
        {isVisible("avg_duration") && (
          <StatCard
            label="Avg AI Duration"
            value={fmtDuration(o?.avg_ai_duration_seconds ?? 0)}
            sub={`${fmtDuration(o?.total_ai_duration_seconds ?? 0)} total`}
            onClick={() => openDrilldown("all", "All Calls")}
          />
        )}
        {isVisible("outbound_duration") && (
          <StatCard
            label="Avg Outbound Duration"
            value={fmtDuration(o?.avg_outbound_duration_seconds ?? 0)}
            sub={`${fmtDuration(o?.total_outbound_duration_seconds ?? 0)} total`}
            color="text-amber-400"
            onClick={() => openDrilldown("transferred", "Transferred Calls")}
          />
        )}
        {isVisible("avg_quality") && (
          <StatCard
            label="Avg Quality Score"
            value={data?.acw.avg_quality_score ?? "—"}
            sub={
              data?.acw.avg_quality_score != null
                ? `${data.acw.min_quality_score}–${data.acw.max_quality_score} range`
                : "No ACW data"
            }
            color="text-purple-400"
            onClick={() => openDrilldown("acw_completed", "Calls with Post Call QA")}
          />
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {isVisible("volume_chart") && (
          <DashboardWidget title="Call Volume Over Time" span={2}>
            {volumeData.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={volumeData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                  <XAxis dataKey="date" tick={{ fill: "#9ca3af", fontSize: 12 }} />
                  <YAxis tick={{ fill: "#9ca3af", fontSize: 12 }} allowDecimals={false} />
                  <Tooltip content={<CustomTooltipContent />} />
                  <Line type="monotone" dataKey="calls" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3, fill: "#3b82f6" }} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-gray-500 text-sm py-12 text-center">No data for this period</p>
            )}
          </DashboardWidget>
        )}

        {isVisible("hour_chart") && (
          <DashboardWidget title="Calls by Hour of Day" span={2}>
            {hourData.some((h) => h.calls > 0) ? (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart
                  data={hourData}
                  onClick={(e: any) => {
                    if (e?.activePayload?.[0]?.payload) {
                      const hr = e.activePayload[0].payload.hour;
                      openDrilldown(`hour:${hr}`, `Calls at ${hr}:00`);
                    }
                  }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                  <XAxis dataKey="label" tick={{ fill: "#9ca3af", fontSize: 10 }} interval={2} />
                  <YAxis tick={{ fill: "#9ca3af", fontSize: 12 }} allowDecimals={false} />
                  <Tooltip content={<CustomTooltipContent />} />
                  <Bar dataKey="calls" fill="#8b5cf6" radius={[4, 4, 0, 0]} cursor="pointer" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-gray-500 text-sm py-12 text-center">No data for this period</p>
            )}
          </DashboardWidget>
        )}

        {isVisible("status_chart") && (
          <DashboardWidget title="Status Breakdown">
            {data && data.status_distribution.length > 0 ? (
              <div className="flex items-center gap-6">
                <ResponsiveContainer width={140} height={140}>
                  <PieChart>
                    <Pie
                      data={data.status_distribution}
                      dataKey="count"
                      nameKey="status"
                      cx="50%"
                      cy="50%"
                      innerRadius={35}
                      outerRadius={60}
                      paddingAngle={2}
                      onClick={(entry: any) => openDrilldown(`status:${entry.status}`, `Status: ${entry.status.replace(/_/g, " ")}`)}
                    >
                      {data.status_distribution.map((d, i) => (
                        <Cell key={d.status} fill={STATUS_COLORS[d.status] || CHART_COLORS[i % CHART_COLORS.length]} cursor="pointer" />
                      ))}
                    </Pie>
                    <Tooltip content={<CustomTooltipContent />} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="flex-1 space-y-1.5">
                  {data.status_distribution.map((d, i) => (
                    <button
                      key={d.status}
                      onClick={() => openDrilldown(`status:${d.status}`, `Status: ${d.status.replace(/_/g, " ")}`)}
                      className="w-full flex items-center justify-between text-sm hover:bg-gray-800 rounded px-1 py-0.5 transition-colors"
                    >
                      <div className="flex items-center gap-2">
                        <span
                          className="w-2.5 h-2.5 rounded-full"
                          style={{ backgroundColor: STATUS_COLORS[d.status] || CHART_COLORS[i % CHART_COLORS.length] }}
                        />
                        <span className="text-gray-300 capitalize">{d.status.replace(/_/g, " ")}</span>
                      </div>
                      <span className="text-gray-400 font-medium">{d.count}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-gray-500 text-sm py-8 text-center">No data</p>
            )}
          </DashboardWidget>
        )}

        {isVisible("disposition_chart") && (
          <DashboardWidget title="Disposition Breakdown">
            {data && data.dispositions.length > 0 ? (
              <div className="space-y-2">
                {data.dispositions.map((d) => {
                  const total = data.dispositions.reduce((a, b) => a + b.count, 0);
                  const pct = total > 0 ? (d.count / total) * 100 : 0;
                  return (
                    <button
                      key={d.disposition_id}
                      onClick={() => openDrilldown(`disposition:${d.disposition_id}`, `Disposition: ${d.name}`)}
                      className="w-full text-left hover:bg-gray-800/50 rounded-lg px-1 py-0.5 transition-colors"
                    >
                      <div className="flex items-center justify-between text-sm mb-1">
                        <div className="flex items-center gap-2">
                          <span
                            className="w-2.5 h-2.5 rounded-full"
                            style={{ backgroundColor: d.color || "#6b7280" }}
                          />
                          <span className="text-gray-300">{d.name}</span>
                        </div>
                        <span className="text-gray-400">{d.count}</span>
                      </div>
                      <div className="w-full h-1.5 bg-gray-800 rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{ width: `${pct}%`, backgroundColor: d.color || "#6b7280" }}
                        />
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <p className="text-gray-500 text-sm py-8 text-center">No dispositions recorded</p>
            )}
          </DashboardWidget>
        )}

        {isVisible("assistant_chart") && (
          <DashboardWidget title="Calls by Assistant" span={2}>
            {data && data.by_assistant.length > 0 ? (
              <ResponsiveContainer width="100%" height={Math.max(180, data.by_assistant.length * 40)}>
                <BarChart
                  data={data.by_assistant}
                  layout="vertical"
                  onClick={(e: any) => {
                    if (e?.activePayload?.[0]?.payload) {
                      const row = e.activePayload[0].payload;
                      openDrilldown(`assistant:${row.assistant_id}`, `Assistant: ${row.assistant_name}`);
                    }
                  }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                  <XAxis type="number" tick={{ fill: "#9ca3af", fontSize: 12 }} allowDecimals={false} />
                  <YAxis
                    type="category"
                    dataKey="assistant_name"
                    tick={{ fill: "#9ca3af", fontSize: 12 }}
                    width={120}
                  />
                  <Tooltip content={<AssistantBarTooltip />} />
                  <Bar dataKey="calls" fill="#22c55e" radius={[0, 4, 4, 0]} cursor="pointer" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-gray-500 text-sm py-8 text-center">No data</p>
            )}
          </DashboardWidget>
        )}

        {isVisible("acw_resolution") && (
          <DashboardWidget title="ACW Resolution Status">
            {data && data.acw.resolution_distribution.length > 0 ? (
              <div className="space-y-2">
                {data.acw.resolution_distribution.map((d, i) => {
                  const total = data.acw.resolution_distribution.reduce((a, b) => a + b.count, 0);
                  const pct = total > 0 ? (d.count / total) * 100 : 0;
                  return (
                    <button
                      key={d.resolution}
                      onClick={() => openDrilldown(`resolution:${d.resolution}`, `Resolution: ${d.resolution}`)}
                      className="w-full text-left hover:bg-gray-800/50 rounded-lg px-1 py-0.5 transition-colors"
                    >
                      <div className="flex items-center justify-between text-sm mb-1">
                        <span className="text-gray-300">{d.resolution}</span>
                        <span className="text-gray-400">
                          {d.count} ({Math.round(pct)}%)
                        </span>
                      </div>
                      <div className="w-full h-1.5 bg-gray-800 rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{ width: `${pct}%`, backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }}
                        />
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <p className="text-gray-500 text-sm py-8 text-center">No ACW data</p>
            )}
          </DashboardWidget>
        )}

        {isVisible("acw_score_dist") && (
          <DashboardWidget title="Quality Score Distribution">
            {data && data.acw.score_distribution.length > 0 && data.acw.score_distribution.some((d) => d.count > 0) ? (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart
                  data={data.acw.score_distribution}
                  onClick={(e: any) => {
                    if (e?.activePayload?.[0]?.payload) {
                      const row = e.activePayload[0].payload;
                      openDrilldown(`quality_range:${row.range}`, `Quality Score ${row.range}`);
                    }
                  }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                  <XAxis dataKey="range" tick={{ fill: "#9ca3af", fontSize: 12 }} />
                  <YAxis tick={{ fill: "#9ca3af", fontSize: 12 }} allowDecimals={false} />
                  <Tooltip content={<CustomTooltipContent />} />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]} cursor="pointer">
                    {data.acw.score_distribution.map((_, i) => (
                      <Cell key={i} fill={["#ef4444", "#f59e0b", "#eab308", "#22c55e", "#10b981"][i]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-gray-500 text-sm py-8 text-center">No quality scores recorded</p>
            )}
          </DashboardWidget>
        )}
      </div>

      <CustomizePanel
        open={customizeOpen}
        onClose={() => setCustomizeOpen(false)}
        widgets={WIDGETS}
        visibility={visibility}
        onToggle={toggle}
        onReset={resetDefaults}
      />

      <DrilldownPanel
        open={drilldown !== null}
        metric={drilldown?.metric ?? ""}
        metricLabel={drilldown?.label ?? ""}
        dateRange={dateRange}
        assistantIds={assistantIds}
        timezone={timezone}
        onClose={() => setDrilldown(null)}
        onViewTranscript={handleViewTranscript}
      />

      {transcriptLoading && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60">
          <Loader2 className="h-8 w-8 animate-spin text-gray-300" />
        </div>
      )}

      {transcriptLog && (
        <TranscriptModal
          log={transcriptLog}
          onClose={() => setTranscriptLog(null)}
        />
      )}
    </div>
  );
}
