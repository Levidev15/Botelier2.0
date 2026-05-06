"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import {
  Loader2,
  FileDown,
  ChevronDown,
  ChevronRight,
  Info,
  LockKeyhole,
} from "lucide-react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { usePermissions } from "@/lib/auth/usePermissions";
import DateRangePicker, { DateRange } from "@/components/analytics/DateRangePicker";

// ──────────────────────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────────────────────

type PeriodKey = "mtd" | "7d" | "30d" | "custom";

interface UsageSummary {
  period_start: string;
  period_end: string;
  inbound_calls: number;
  inbound_minutes: number;
  inbound_cost_usd: number;
  outbound_transfers: number;
  outbound_minutes: number;
  outbound_cost_usd: number;
  sms_inbound_count: number;
  sms_outbound_count: number;
  sms_cost_usd: number;
  total_cost_usd: number;
}

interface BillingConfig {
  inbound_rate_usd: number;
  outbound_rate_usd: number;
  sms_inbound_rate_usd: number;
  sms_outbound_rate_usd: number;
  is_platform_default: boolean;
}

interface TimeseriesPoint {
  date: string;
  inbound_cost_usd: number;
  outbound_cost_usd: number;
  sms_cost_usd: number;
  total_cost_usd: number;
}

interface BillingItem {
  id: string;
  item_type: "inbound_call" | "outbound_transfer";
  quantity_minutes: number;
  rate_per_unit_usd: number;
  cost_usd: number;
  destination?: string | null;
  destination_name?: string | null;
  leg_type?: string | null;
  leg_duration_seconds?: number;
}

interface CallRow {
  call_log_id: string;
  reference_id: string | null;
  started_at: string | null;
  direction: string;
  caller_number: string | null;
  to_number: string | null;
  assistant_name: string | null;
  duration_seconds: number;
  billable_inbound_minutes: number;
  inbound_cost_usd: number;
  has_transfers: boolean;
  total_cost_usd: number;
  billing_items: BillingItem[];
}

interface CallsResponse {
  calls: CallRow[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

function fmtUsd(v: number): string {
  return "$" + v.toFixed(4);
}

function fmtMinutes(s: number): string {
  if (s <= 0) return "0s";
  const m = Math.floor(s / 60);
  const sec = s % 60;
  if (m === 0) return `${sec}s`;
  if (sec === 0) return `${m}m`;
  return `${m}m ${sec}s`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) +
    " " + d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

function periodToDates(key: PeriodKey, custom: DateRange): { from: Date; to: Date } {
  const now = new Date();
  if (key === "mtd") return { from: new Date(now.getFullYear(), now.getMonth(), 1), to: now };
  if (key === "7d") return { from: new Date(now.getTime() - 7 * 86_400_000), to: now };
  if (key === "30d") return { from: new Date(now.getTime() - 30 * 86_400_000), to: now };
  return { from: custom.from, to: custom.to };
}

function defaultCustomRange(): DateRange {
  const now = new Date();
  const from = new Date(now.getTime() - 30 * 86_400_000);
  from.setHours(0, 0, 0, 0);
  return { from, to: now };
}

// ──────────────────────────────────────────────────────────────────────────────
// Sub-components
// ──────────────────────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  note,
  skeleton,
}: {
  label: string;
  value: string;
  sub?: string;
  note?: string;
  skeleton?: boolean;
}) {
  return (
    <div className="bg-[#1a1a1a] border border-gray-800 rounded-xl p-5">
      <p className="text-sm text-gray-400 mb-1">{label}</p>
      {skeleton ? (
        <div className="h-8 w-24 bg-gray-800 rounded animate-pulse mt-1" />
      ) : (
        <p className="text-2xl font-bold text-gray-100">{value}</p>
      )}
      {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
      {note && <p className="text-xs text-gray-600 mt-0.5 italic">{note}</p>}
    </div>
  );
}

function PeriodTab({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${
        active
          ? "bg-blue-600/20 text-blue-400 border border-blue-600/40"
          : "text-gray-400 hover:text-gray-200 hover:bg-gray-800"
      }`}
    >
      {label}
    </button>
  );
}

interface UsageTooltipPayload {
  name?: string;
  value?: number;
  color?: string;
}
interface UsageTooltipProps {
  active?: boolean;
  payload?: UsageTooltipPayload[];
  label?: string;
}
function UsageTooltip({ active, payload, label }: UsageTooltipProps) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((s, p) => s + (p.value ?? 0), 0);
  return (
    <div className="bg-[#252525] border border-gray-700 rounded-lg px-3 py-2 text-sm shadow-lg min-w-[170px]">
      <p className="text-gray-400 mb-2 text-xs">{label}</p>
      {payload.map((p, i) => (
        <div key={i} className="flex justify-between gap-4">
          <span style={{ color: p.color }} className="text-xs">{p.name}</span>
          <span className="text-gray-200 text-xs font-mono">{fmtUsd(p.value ?? 0)}</span>
        </div>
      ))}
      <div className="border-t border-gray-700 mt-1.5 pt-1.5 flex justify-between gap-4">
        <span className="text-gray-400 text-xs">Total</span>
        <span className="text-gray-100 text-xs font-mono font-semibold">{fmtUsd(total)}</span>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Main page
// ──────────────────────────────────────────────────────────────────────────────

const PER_PAGE = 25;

export default function UsagePage() {
  const { accountId } = useAccountContext();
  const { authFetch } = useAuthToken();
  const { can, loading: permLoading, isPlatformAdmin } = usePermissions();

  // Period state
  const [periodKey, setPeriodKey] = useState<PeriodKey>("mtd");
  const [customRange, setCustomRange] = useState<DateRange>(defaultCustomRange);

  // Data state
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [config, setConfig] = useState<BillingConfig | null>(null);
  const [timeseries, setTimeseries] = useState<TimeseriesPoint[]>([]);
  const [calls, setCalls] = useState<CallsResponse | null>(null);

  // UI state
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [chartLoading, setChartLoading] = useState(true);
  const [callsLoading, setCallsLoading] = useState(true);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [callsError, setCallsError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [exportLoading, setExportLoading] = useState(false);
  const [tooltipVisible, setTooltipVisible] = useState(false);

  const canView = isPlatformAdmin || can("usage", "view");
  const canExport = isPlatformAdmin || can("usage", "export");

  const { from, to } = useMemo(
    () => periodToDates(periodKey, customRange),
    [periodKey, customRange],
  );

  // Build period params for summary/timeseries (uses period shorthand)
  const periodParam = useMemo(() => {
    if (periodKey !== "custom") return `period=${periodKey}`;
    return `period=custom&from=${from.toISOString()}&to=${to.toISOString()}`;
  }, [periodKey, from, to]);

  // ── Summary + config fetch ────────────────────────────────────────────────
  useEffect(() => {
    if (!accountId || !canView) return;
    setSummaryLoading(true);
    setSummaryError(null);

    const summaryUrl = `/api/billing/usage/summary?account_id=${accountId}&${periodParam}`;
    const configUrl = `/api/billing/config?account_id=${accountId}`;

    Promise.all([
      authFetch(summaryUrl).then((r) => r.json()),
      authFetch(configUrl).then((r) => (r.ok ? r.json() : null)),
    ])
      .then(([summaryData, configData]) => {
        setSummary(summaryData);
        setConfig(configData);
      })
      .catch(() => setSummaryError("Failed to load usage summary"))
      .finally(() => setSummaryLoading(false));
  }, [accountId, periodParam, canView]);

  // ── Timeseries fetch ──────────────────────────────────────────────────────
  useEffect(() => {
    if (!accountId || !canView) return;
    setChartLoading(true);

    authFetch(`/api/billing/usage/timeseries?account_id=${accountId}&${periodParam}`)
      .then((r) => r.json())
      .then((data) => setTimeseries(data.timeseries ?? []))
      .catch(() => setTimeseries([]))
      .finally(() => setChartLoading(false));
  }, [accountId, periodParam, canView]);

  // ── Calls fetch ───────────────────────────────────────────────────────────
  useEffect(() => {
    if (!accountId || !canView) return;
    setCallsLoading(true);
    setCallsError(null);
    setExpandedRows(new Set());

    const params = new URLSearchParams({
      account_id: accountId,
      from: from.toISOString(),
      to: to.toISOString(),
      page: String(page),
      per_page: String(PER_PAGE),
    });

    authFetch(`/api/billing/usage/calls?${params}`)
      .then((r) => r.json())
      .then(setCalls)
      .catch(() => setCallsError("Failed to load call activity"))
      .finally(() => setCallsLoading(false));
  }, [accountId, from, to, page, canView]);

  const handlePeriodChange = (key: PeriodKey) => {
    setPeriodKey(key);
    setPage(1);
  };

  const toggleRow = useCallback((id: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleExport = useCallback(async () => {
    if (!accountId || exportLoading) return;
    setExportLoading(true);
    try {
      const params = new URLSearchParams({
        account_id: accountId,
        from: from.toISOString(),
        to: to.toISOString(),
        format: "csv",
      });
      const r = await authFetch(`/api/billing/usage/calls?${params}`);
      if (!r.ok) {
        alert(`Export failed (${r.status})`);
        return;
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `usage-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      alert("Export failed — please try again.");
    } finally {
      setExportLoading(false);
    }
  }, [accountId, from, to, authFetch, exportLoading]);

  // ── Loading / permission states ───────────────────────────────────────────
  if (permLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-gray-500" />
      </div>
    );
  }

  if (!canView) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-4">
        <div className="w-14 h-14 rounded-full bg-gray-800 flex items-center justify-center">
          <LockKeyhole className="h-7 w-7 text-gray-500" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-gray-200">Access Restricted</h2>
          <p className="text-sm text-gray-500 mt-1 max-w-xs">
            You don't have permission to view usage data. Contact your account admin to request access.
          </p>
        </div>
      </div>
    );
  }

  const rates = config ?? {
    inbound_rate_usd: 0.05,
    outbound_rate_usd: 0.08,
    sms_inbound_rate_usd: 0.01,
    sms_outbound_rate_usd: 0.01,
    is_platform_default: true,
  };

  const chartData = timeseries.map((p) => ({
    ...p,
    date: new Date(p.date + "T00:00:00").toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    }),
  }));

  const hasChartData = chartData.length > 0 && chartData.some((d) => d.total_cost_usd > 0);
  const hasCallData = (calls?.calls?.length ?? 0) > 0;

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-6">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Usage</h1>
          <p className="text-sm text-gray-400 mt-1">
            Billable usage and cost breakdown for your account
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Period tabs */}
          <div className="flex items-center gap-1 bg-[#1a1a1a] border border-gray-800 rounded-lg p-1">
            {(["mtd", "7d", "30d"] as PeriodKey[]).map((k) => (
              <PeriodTab
                key={k}
                label={k === "mtd" ? "MTD" : k === "7d" ? "Last 7d" : "Last 30d"}
                active={periodKey === k}
                onClick={() => handlePeriodChange(k)}
              />
            ))}
            <PeriodTab
              label="Custom"
              active={periodKey === "custom"}
              onClick={() => handlePeriodChange("custom")}
            />
          </div>

          {/* Custom date picker */}
          {periodKey === "custom" && (
            <DateRangePicker
              value={customRange}
              onChange={(r) => {
                setCustomRange(r);
                setPage(1);
              }}
            />
          )}

          {/* Export CSV */}
          {canExport && (
            <button
              onClick={handleExport}
              disabled={exportLoading}
              className="flex items-center gap-2 px-3 py-1.5 text-sm bg-[#1a1a1a] border border-gray-700 rounded-lg text-gray-300 hover:text-gray-100 hover:border-gray-600 transition-colors disabled:opacity-50"
            >
              {exportLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FileDown className="h-4 w-4" />
              )}
              Export CSV
            </button>
          )}
        </div>
      </div>

      {/* ── Stat cards ─────────────────────────────────────────────────── */}
      {summaryError ? (
        <div className="p-4 bg-red-900/20 border border-red-800 rounded-xl text-red-400 text-sm">
          {summaryError}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            label="Inbound Minutes"
            value={summaryLoading ? "—" : (summary?.inbound_minutes ?? 0).toLocaleString()}
            sub={`at $${rates.inbound_rate_usd.toFixed(3)}/min · ${summary?.inbound_calls ?? 0} calls`}
            note={!summaryLoading && (summary?.inbound_cost_usd ?? 0) > 0 ? fmtUsd(summary!.inbound_cost_usd) : undefined}
            skeleton={summaryLoading}
          />
          <StatCard
            label="Outbound Minutes"
            value={summaryLoading ? "—" : (summary?.outbound_minutes ?? 0).toLocaleString()}
            sub={`at $${rates.outbound_rate_usd.toFixed(3)}/min · ${summary?.outbound_transfers ?? 0} transfers`}
            note={!summaryLoading && (summary?.outbound_cost_usd ?? 0) > 0 ? fmtUsd(summary!.outbound_cost_usd) : undefined}
            skeleton={summaryLoading}
          />
          <StatCard
            label="SMS Messages"
            value={summaryLoading ? "—" : ((summary?.sms_inbound_count ?? 0) + (summary?.sms_outbound_count ?? 0)).toLocaleString()}
            sub={`${summary?.sms_inbound_count ?? 0} received · ${summary?.sms_outbound_count ?? 0} sent`}
            note={!summaryLoading && (summary?.sms_cost_usd ?? 0) > 0 ? fmtUsd(summary!.sms_cost_usd) : undefined}
            skeleton={summaryLoading}
          />
          <StatCard
            label="Total Cost"
            value={summaryLoading ? "—" : fmtUsd(summary?.total_cost_usd ?? 0)}
            sub="Inbound + outbound + SMS"
            skeleton={summaryLoading}
          />
        </div>
      )}

      {/* ── Cost trend chart ────────────────────────────────────────────── */}
      <div className="bg-[#1a1a1a] border border-gray-800 rounded-xl p-5">
        <h3 className="text-sm font-medium text-gray-400 mb-4">Daily Cost</h3>

        {chartLoading ? (
          <div className="h-56 flex items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-gray-600" />
          </div>
        ) : !hasChartData ? (
          <div className="h-56 flex flex-col items-center justify-center text-gray-600 text-sm gap-2">
            <p>No cost data for this period</p>
            <p className="text-xs text-gray-700">Costs appear once billing items are recorded on calls</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={chartData} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="date"
                tick={{ fill: "#6b7280", fontSize: 11 }}
                axisLine={{ stroke: "#374151" }}
                tickLine={false}
              />
              <YAxis
                tickFormatter={(v) => `$${(v as number).toFixed(2)}`}
                tick={{ fill: "#6b7280", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={52}
              />
              <Tooltip content={<UsageTooltip />} />
              <Legend
                wrapperStyle={{ fontSize: 12, color: "#9ca3af", paddingTop: 8 }}
              />
              <Area
                type="monotone"
                dataKey="inbound_cost_usd"
                stackId="1"
                stroke="#3b82f6"
                fill="#3b82f6"
                fillOpacity={0.55}
                name="Inbound Calls"
              />
              <Area
                type="monotone"
                dataKey="outbound_cost_usd"
                stackId="1"
                stroke="#8b5cf6"
                fill="#8b5cf6"
                fillOpacity={0.55}
                name="Outbound Transfers"
              />
              <Area
                type="monotone"
                dataKey="sms_cost_usd"
                stackId="1"
                stroke="#22c55e"
                fill="#22c55e"
                fillOpacity={0.55}
                name="SMS"
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* ── Call activity table ─────────────────────────────────────────── */}
      <div className="bg-[#1a1a1a] border border-gray-800 rounded-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <h3 className="text-sm font-medium text-gray-400">Call Activity</h3>
          {calls && (
            <span className="text-xs text-gray-600">
              {calls.total.toLocaleString()} calls total
            </span>
          )}
        </div>

        {callsError ? (
          <div className="p-5 text-sm text-red-400">{callsError}</div>
        ) : callsLoading ? (
          <div className="flex items-center justify-center h-32">
            <Loader2 className="h-5 w-5 animate-spin text-gray-600" />
          </div>
        ) : !hasCallData ? (
          <div className="flex flex-col items-center justify-center h-32 text-gray-600 text-sm gap-1">
            <p>No calls in this period</p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-800 text-left">
                    <th className="px-4 py-3 text-xs font-medium text-gray-500 w-8" />
                    <th className="px-4 py-3 text-xs font-medium text-gray-500">Date / Time</th>
                    <th className="px-4 py-3 text-xs font-medium text-gray-500">Direction</th>
                    <th className="px-4 py-3 text-xs font-medium text-gray-500">Caller</th>
                    <th className="px-4 py-3 text-xs font-medium text-gray-500">Assistant</th>
                    <th className="px-4 py-3 text-xs font-medium text-gray-500">Duration</th>
                    <th className="px-4 py-3 text-xs font-medium text-gray-500">Billable Min</th>
                    <th className="px-4 py-3 text-xs font-medium text-gray-500">
                      <span className="flex items-center gap-1">
                        Cost
                        <span
                          className="relative cursor-help inline-block"
                          onMouseEnter={() => setTooltipVisible(true)}
                          onMouseLeave={() => setTooltipVisible(false)}
                        >
                          <Info className="h-3 w-3 text-gray-600 hover:text-gray-400 transition-colors" />
                          {tooltipVisible && (
                            <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 w-52 bg-[#2a2a2a] border border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-300 shadow-xl z-50 leading-relaxed">
                              Billed in whole minutes, rounded up. 1m 30s counts as 2 billable minutes.
                            </span>
                          )}
                        </span>
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {calls?.calls.flatMap((call) => {
                    const isExpanded = expandedRows.has(call.call_log_id);
                    const transferItems = call.billing_items.filter(
                      (i) => i.item_type === "outbound_transfer",
                    );
                    const hasNoCost = call.total_cost_usd === 0 && call.billing_items.length === 0;

                    const mainRow = (
                      <tr
                        key={call.call_log_id}
                        className="border-b border-gray-800/60 hover:bg-gray-800/20 transition-colors"
                      >
                        {/* Expand toggle */}
                        <td className="px-4 py-3">
                          {call.has_transfers ? (
                            <button
                              onClick={() => toggleRow(call.call_log_id)}
                              className="text-gray-500 hover:text-gray-300 transition-colors"
                              title={isExpanded ? "Collapse transfer legs" : "Expand transfer legs"}
                            >
                              {isExpanded ? (
                                <ChevronDown className="h-4 w-4" />
                              ) : (
                                <ChevronRight className="h-4 w-4" />
                              )}
                            </button>
                          ) : null}
                        </td>
                        <td className="px-4 py-3 text-gray-300 whitespace-nowrap">
                          {fmtDate(call.started_at)}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                              call.direction === "inbound"
                                ? "bg-blue-600/20 text-blue-400"
                                : "bg-purple-600/20 text-purple-400"
                            }`}
                          >
                            {call.direction === "inbound" ? "Inbound" : "Outbound"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-400 font-mono text-xs">
                          {call.caller_number ?? "—"}
                        </td>
                        <td className="px-4 py-3 text-gray-400 max-w-[140px] truncate">
                          {call.assistant_name ?? "—"}
                        </td>
                        <td className="px-4 py-3 text-gray-400 whitespace-nowrap">
                          {fmtMinutes(call.duration_seconds)}
                        </td>
                        <td className="px-4 py-3 text-gray-400">
                          {call.billable_inbound_minutes}
                        </td>
                        <td className="px-4 py-3 font-mono">
                          {hasNoCost ? (
                            <span className="text-gray-600">—</span>
                          ) : (
                            <span className="text-gray-200">{fmtUsd(call.total_cost_usd)}</span>
                          )}
                        </td>
                      </tr>
                    );

                    if (!isExpanded || transferItems.length === 0) {
                      return [mainRow];
                    }

                    const headerRow = (
                      <tr
                        key={`${call.call_log_id}-sub-header`}
                        className="bg-[#151515]"
                      >
                        <td />
                        <td
                          colSpan={7}
                          className="px-4 py-2 text-xs font-medium text-gray-500 uppercase tracking-wide"
                        >
                          Transfer Legs
                        </td>
                      </tr>
                    );

                    const legRows = transferItems.map((item, idx) => {
                      const legLabel = item.leg_type
                        ? item.leg_type.replace("transfer_", "").replace("_", " ")
                        : "transfer";
                      const dest = item.destination_name || item.destination || "—";
                      const legDur = item.leg_duration_seconds
                        ? fmtMinutes(item.leg_duration_seconds)
                        : "—";
                      return (
                        <tr
                          key={item.id || `${call.call_log_id}-leg-${idx}`}
                          className="bg-[#151515] border-b border-gray-800/40"
                        >
                          <td />
                          <td className="px-4 py-2.5 whitespace-nowrap">
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs bg-purple-900/30 text-purple-400 capitalize">
                              {legLabel}
                            </span>
                          </td>
                          <td className="px-4 py-2.5 text-gray-500 text-xs" />
                          <td className="px-4 py-2.5 text-gray-400 font-mono text-xs">
                            {dest}
                          </td>
                          <td className="px-4 py-2.5 text-gray-500 text-xs" />
                          <td className="px-4 py-2.5 text-gray-400 text-xs whitespace-nowrap">
                            {legDur}
                          </td>
                          <td className="px-4 py-2.5 text-gray-400 text-xs">
                            {item.quantity_minutes} min
                          </td>
                          <td className="px-4 py-2.5 font-mono text-xs text-gray-300">
                            {fmtUsd(item.cost_usd)}
                            <span className="text-gray-600 ml-1">
                              @ ${item.rate_per_unit_usd.toFixed(3)}/min
                            </span>
                          </td>
                        </tr>
                      );
                    });

                    return [mainRow, headerRow, ...legRows];
                  })}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {calls && calls.pages > 1 && (
              <div className="flex items-center justify-between px-5 py-3 border-t border-gray-800">
                <span className="text-xs text-gray-600">
                  Page {calls.page} of {calls.pages}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="px-3 py-1 text-xs bg-gray-800 text-gray-300 rounded hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    Previous
                  </button>
                  <button
                    onClick={() => setPage((p) => Math.min(calls.pages, p + 1))}
                    disabled={page === calls.pages}
                    className="px-3 py-1 text-xs bg-gray-800 text-gray-300 rounded hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
