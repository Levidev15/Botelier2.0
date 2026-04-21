"use client";

import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import { SlidersHorizontal, Loader2, FileDown, ChevronDown, AlertTriangle } from "lucide-react";
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
import CallDrilldownModal, { TranscriptCallLog } from "@/components/analytics/CallDrilldownModal";
import { useWidgetLayout, WidgetDef } from "@/components/analytics/useWidgetLayout";
import TranscriptModal from "@/app/(dashboard)/dashboard/call-logs/components/TranscriptModal";
import TimezonePicker, { loadTimezone, saveTimezone } from "@/components/analytics/TimezonePicker";
import PartitionBar, { PartitionBarBucket } from "@/components/analytics/PartitionBar";
import BucketPill, { BucketPillSubSegment } from "@/components/analytics/BucketPill";

// Task #129 — chart-only widgets (the 5 partition pills + Quality &
// Operations stat row are now structural, never togglable, because they
// are the page's spine and the only way to reconcile to total_calls).
const WIDGETS: WidgetDef[] = [
  { id: "volume_chart", label: "Call Volume Over Time", defaultVisible: true },
  { id: "hour_chart", label: "Calls by Hour of Day", defaultVisible: true },
  { id: "disposition_chart", label: "Disposition Breakdown", defaultVisible: true },
  { id: "assistant_chart", label: "Calls by Assistant", defaultVisible: true },
  { id: "acw_resolution", label: "ACW Resolution Status", defaultVisible: true },
  { id: "acw_score_dist", label: "Quality Score Distribution", defaultVisible: true },
  { id: "status_chart", label: "Status Breakdown (technical)", defaultVisible: false },
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

// Task #129 — single source of truth for the 5 MECE bucket presentation.
// Order is intentional (the partition bar reads left→right as positive→negative
// outcome). Colors mirror the spec's emotional mapping so the bar tells the
// at-a-glance story without needing to read labels.
const BUCKET_DISPLAY: { key: string; label: string; color: string }[] = [
  { key: "ai_handled",  label: "AI Handled",        color: "#22c55e" }, // green
  { key: "ended_early", label: "Dropped Before AI", color: "#f97316" }, // orange
  { key: "missed",      label: "Missed",            color: "#f59e0b" }, // amber
  { key: "failed",      label: "Failed",            color: "#ef4444" }, // red
  { key: "unresolved",  label: "Unresolved",        color: "#eab308" }, // yellow
];

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
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const [timezone, setTimezone] = useState<string>("UTC");
  const { visibility, toggle, resetDefaults, isVisible } = useWidgetLayout("call_analytics", WIDGETS);
  const exportMenuRef = useRef<HTMLDivElement | null>(null);

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

  // Close export menu on outside click.
  useEffect(() => {
    if (!exportMenuOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(e.target as Node)) {
        setExportMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [exportMenuOpen]);

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

  // Task #129 — three export modes share filters + timezone so the row set
  // and aggregates always match what's currently on screen. The Detailed
  // CSV row count under "Bucket = X" reconciles to the X pill's count by
  // construction (same `_bucket_predicate` on the backend).
  const buildExportParams = useCallback(() => {
    if (!accountId) return null;
    const p = new URLSearchParams({
      account_id: accountId,
      date_from: dateRange.from.toISOString(),
      date_to: dateRange.to.toISOString(),
      tz: timezone,
    });
    assistantIds.forEach((id) => p.append("assistant_ids", id));
    return p;
  }, [accountId, dateRange, assistantIds, timezone]);

  // Auth in this app is JWT-in-localStorage sent as `Authorization: Bearer
  // <token>`. A `window.open(...)` would issue a top-level GET that cannot
  // attach custom headers, so the backend (HTTPBearer) would reject it as
  // "Not authenticated". Instead we fetch via `authFetch` (which injects
  // the bearer token + admin-session headers), get a Blob, and trigger a
  // download via a temporary anchor + object URL. This is also how a future
  // CORS / cookie-less deployment will keep working unchanged.
  const downloadCsv = useCallback(
    async (url: string, filename: string) => {
      try {
        const r = await authFetch(url);
        if (!r.ok) {
          let msg = `Export failed (${r.status})`;
          try {
            const body = await r.json();
            if (body?.detail) msg = `${msg}: ${body.detail}`;
          } catch {
            /* non-JSON error body — keep generic message */
          }
          alert(msg);
          return;
        }
        const blob = await r.blob();
        const objectUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = objectUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        // Defer revoke so Safari has time to start the download.
        setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      } catch (err) {
        console.error("CSV export error:", err);
        alert("Export failed — please try again.");
      }
    },
    [authFetch],
  );

  const handleExportDetailed = useCallback(() => {
    const p = buildExportParams();
    if (!p) return;
    setExportMenuOpen(false);
    const ts = new Date().toISOString().slice(0, 10);
    // Detailed CSV — one row per call with the new MECE Bucket column.
    void downloadCsv(
      `/api/call-logs/export?${p}`,
      `call-logs-detailed-${ts}.csv`,
    );
  }, [buildExportParams, downloadCsv]);

  const handleExportSummary = useCallback(() => {
    const p = buildExportParams();
    if (!p) return;
    setExportMenuOpen(false);
    const ts = new Date().toISOString().slice(0, 10);
    void downloadCsv(
      `/api/analytics/calls/export-summary?${p}`,
      `call-analytics-summary-${ts}.csv`,
    );
  }, [buildExportParams, downloadCsv]);

  const handleExportReport = useCallback(() => {
    if (!accountId) return;
    setExportMenuOpen(false);
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
  const total = o?.total_calls ?? 0;

  // Task #129 — compose the partition buckets in the canonical display
  // order. Reads exclusively from the `*_count` keys so the bar, the pills,
  // and the drilldown modal share one vocabulary.
  const partitionBuckets: PartitionBarBucket[] = BUCKET_DISPLAY.map((b) => ({
    key: b.key,
    label: b.label,
    color: b.color,
    count:
      b.key === "ai_handled"  ? (o?.ai_handled_count  ?? 0) :
      b.key === "ended_early" ? (o?.ended_early_count ?? 0) :
      b.key === "missed"      ? (o?.missed_count      ?? 0) :
      b.key === "failed"      ? (o?.failed_count      ?? 0) :
      /* unresolved */          (o?.unresolved_count  ?? 0),
  }));

  // Sub-breakdown for the Unresolved pill — promoted out of the tooltip so
  // the most-asked question (silent caller vs sweeper-pending) is visible
  // without hovering. Kept separate from `partitionBuckets` because these
  // are sub-types, NOT a sixth bucket.
  const unresolvedSubs: BucketPillSubSegment[] = (() => {
    const ub = o?.unresolved_breakdown;
    if (!ub) return [];
    return [
      { key: "no_caller_audio",     label: "Silent caller",       color: "#fde047", count: ub.no_caller_audio ?? 0 },
      { key: "dropped_pre_greeting", label: "Pending finalization", color: "#facc15", count: ub.dropped_pre_greeting ?? 0 },
      { key: "other",               label: "Other anomalies",     color: "#a16207", count: ub.other ?? 0 },
    ];
  })();

  return (
    <div className="flex flex-col lg:flex-row gap-6 p-6 max-w-[1500px] mx-auto">
      {/* ── Left rail: filters ────────────────────────────────────────── */}
      <aside className="lg:w-60 lg:flex-shrink-0 lg:sticky lg:top-6 lg:self-start space-y-4">
        <div className="bg-[#1a1a1a] border border-gray-800 rounded-xl p-4 space-y-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Filters</h3>
          <div className="space-y-3">
            <div>
              <label className="block text-[11px] text-gray-500 mb-1.5">Date range</label>
              <DateRangePicker value={dateRange} onChange={setDateRange} />
            </div>
            <div>
              <label className="block text-[11px] text-gray-500 mb-1.5">Timezone</label>
              <TimezonePicker
                value={timezone}
                onChange={(tz) => { setTimezone(tz); saveTimezone(tz); }}
              />
            </div>
            <div>
              <label className="block text-[11px] text-gray-500 mb-1.5">Assistant</label>
              <AssistantFilter selected={assistantIds} onChange={setAssistantIds} />
            </div>
          </div>
        </div>
      </aside>

      {/* ── Main column ───────────────────────────────────────────────── */}
      <main className="flex-1 min-w-0 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold text-gray-100">Call Analytics</h1>
            <p className="text-sm text-gray-400 mt-1">
              {total.toLocaleString()} calls in window
              {o && !o.partition_integrity_ok && (
                <span className="ml-2 inline-flex items-center gap-1 text-amber-400">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  partition mismatch — contact support
                </span>
              )}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setCustomizeOpen(true)}
              className="flex items-center gap-2 px-3 py-1.5 text-sm bg-[#1a1a1a] border border-gray-700 rounded-lg text-gray-300 hover:text-gray-100 hover:border-gray-600 transition-colors"
              title="Show / hide chart widgets"
            >
              <SlidersHorizontal className="h-4 w-4" />
              View
            </button>
            <div ref={exportMenuRef} className="relative">
              <button
                onClick={() => setExportMenuOpen((v) => !v)}
                className="flex items-center gap-2 px-3 py-1.5 text-sm bg-[#1a1a1a] border border-gray-700 rounded-lg text-gray-300 hover:text-gray-100 hover:border-gray-600 transition-colors"
              >
                <FileDown className="h-4 w-4" />
                Export
                <ChevronDown className="h-3.5 w-3.5" />
              </button>
              {exportMenuOpen && (
                <div className="absolute right-0 mt-1 w-64 bg-[#1a1a1a] border border-gray-700 rounded-lg shadow-xl z-30 overflow-hidden">
                  <button
                    onClick={handleExportDetailed}
                    className="w-full text-left px-4 py-2.5 hover:bg-gray-800 transition-colors"
                  >
                    <div className="text-sm text-gray-100">Detailed CSV</div>
                    <div className="text-[11px] text-gray-500">One row per call · MECE Bucket column</div>
                  </button>
                  <button
                    onClick={handleExportSummary}
                    className="w-full text-left px-4 py-2.5 hover:bg-gray-800 transition-colors border-t border-gray-800"
                  >
                    <div className="text-sm text-gray-100">Summary CSV</div>
                    <div className="text-[11px] text-gray-500">Per-day-per-bucket + per-assistant-per-bucket</div>
                  </button>
                  <button
                    onClick={handleExportReport}
                    className="w-full text-left px-4 py-2.5 hover:bg-gray-800 transition-colors border-t border-gray-800"
                  >
                    <div className="text-sm text-gray-100">Visual report</div>
                    <div className="text-[11px] text-gray-500">Print-ready, opens in new tab</div>
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        {loading && (
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <Loader2 className="h-4 w-4 animate-spin" /> Refreshing…
          </div>
        )}

        {/* ── Partition spine ──────────────────────────────────────────── */}
        <PartitionBar
          buckets={partitionBuckets}
          total={total}
          onSegmentClick={(k, label) => openDrilldown(k, label)}
        />

        {/* ── 5 bucket pills (the spine, never togglable) ──────────────── */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {partitionBuckets.map((b) => (
            <BucketPill
              key={b.key}
              bucketKey={b.key}
              label={b.label}
              count={b.count}
              total={total}
              color={b.color}
              onClick={(key, label) => openDrilldown(key, label)}
              subSegments={b.key === "unresolved" ? unresolvedSubs : undefined}
              tooltip={
                b.key === "unresolved"
                  ? "Catch-all bucket. Silent caller = AI greeted but caller never spoke. Pending finalization = sweeper still working. Other = anomalies."
                  : undefined
              }
            />
          ))}
        </div>

        {/* ── Quality & Operations row ─────────────────────────────────── */}
        <section>
          <h2 className="text-sm font-semibold text-gray-300 mb-3 uppercase tracking-wide">
            Quality &amp; Operations
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {(() => {
              // Task #129 — express Transfer Rate as transfers / AI-handled
              // (the meaningful denominator: a transfer can only happen on a
              // call the AI handled). Computed client-side from existing
              // partition keys; the API still returns the legacy
              // transfers / total_calls under `transfer_rate` for any
              // external consumer that depends on it.
              const transferred = o?.transferred ?? 0;
              const aiHandled = o?.ai_handled_count ?? 0;
              const rateOfAi = aiHandled > 0
                ? ((transferred / aiHandled) * 100).toFixed(1)
                : "0.0";
              return (
                <StatCard
                  label="Transfer Rate"
                  value={`${rateOfAi}%`}
                  sub={`${transferred} transferred · of ${aiHandled} AI Handled`}
                  color="text-blue-400"
                  onClick={() => openDrilldown("transferred", "Transferred Calls")}
                  tooltip={
                    "Denominator = AI Handled (a transfer can only happen on a call the AI greeted). " +
                    "Transferred calls are a subset of AI Handled — not a separate partition bucket. " +
                    `Legacy transfers/total_calls = ${o?.transfer_rate ?? 0}% (still emitted by the API).`
                  }
                />
              );
            })()}
            <StatCard
              label="Avg AI Duration"
              value={fmtDuration(o?.avg_ai_duration_seconds ?? 0)}
              sub={`${fmtDuration(o?.total_ai_duration_seconds ?? 0)} total`}
              onClick={() => openDrilldown("ai_handled", "AI Handled Calls")}
            />
            <StatCard
              label="Avg Outbound Duration"
              value={fmtDuration(o?.avg_outbound_duration_seconds ?? 0)}
              sub={`${o?.outbound_calls_count ?? 0} outbound legs`}
              color="text-amber-400"
              onClick={() => openDrilldown("transferred", "Transferred Calls")}
            />
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
          </div>
        </section>

        {/* ── Outcomes & activity ──────────────────────────────────────── */}
        <section>
          <h2 className="text-sm font-semibold text-gray-300 mb-3 uppercase tracking-wide">
            Outcomes &amp; Activity
          </h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Disposition is now the primary "what happened" lens (promoted). */}
            {isVisible("disposition_chart") && (
              <DashboardWidget title="Disposition Breakdown" span={2}>
                {data && data.dispositions.length > 0 ? (
                  <div className="space-y-2">
                    {data.dispositions.map((d) => {
                      const denom = data.dispositions.reduce((a, b) => a + b.count, 0);
                      const pct = denom > 0 ? (d.count / denom) * 100 : 0;
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
                            <span className="text-gray-400">{d.count} ({pct.toFixed(1)}%)</span>
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
                      const denom = data.acw.resolution_distribution.reduce((a, b) => a + b.count, 0);
                      const pct = denom > 0 ? (d.count / denom) * 100 : 0;
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
        </section>

        {/* ── Technical breakdown (collapsed by default) ───────────────── */}
        {/* View toggle gates the entire panel so the menu's "Status
            Breakdown (technical)" entry actually controls something. */}
        {isVisible("status_chart") && (
        <details className="bg-[#1a1a1a] border border-gray-800 rounded-xl group">
          <summary className="cursor-pointer px-5 py-3 text-sm font-medium text-gray-300 flex items-center justify-between select-none">
            <span>Technical breakdown</span>
            <span className="text-[11px] text-gray-500 group-open:hidden">
              raw Twilio status — for ops & debugging
            </span>
            <ChevronDown className="h-4 w-4 text-gray-500 group-open:rotate-180 transition-transform" />
          </summary>
          <div className="px-5 pb-5 pt-1">
            {data && data.status_distribution.length > 0 ? (
              <div className="flex items-center gap-6 flex-wrap">
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
                <div className="flex-1 min-w-[200px] space-y-1.5">
                  <p className="text-[11px] text-gray-500 mb-2">
                    Raw Twilio status enum. The MECE buckets above derive from these plus
                    <code className="text-gray-400 mx-1">ai_greeting_completed</code>and
                    <code className="text-gray-400 mx-1">caller_spoke</code>— use this only when debugging.
                  </p>
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
              <p className="text-gray-500 text-sm py-4 text-center">No status data</p>
            )}
          </div>
        </details>
        )}
      </main>

      <CustomizePanel
        open={customizeOpen}
        onClose={() => setCustomizeOpen(false)}
        widgets={WIDGETS}
        visibility={visibility}
        onToggle={toggle}
        onReset={resetDefaults}
      />

      <CallDrilldownModal
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
