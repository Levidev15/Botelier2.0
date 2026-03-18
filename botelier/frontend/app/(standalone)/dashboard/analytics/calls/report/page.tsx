"use client";

export const dynamic = "force-dynamic";

import { useEffect, useState, useMemo, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import {
  LineChart, Line,
  BarChart, Bar,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from "recharts";

const CHART_COLORS = ["#3b82f6", "#8b5cf6", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4", "#ec4899", "#84cc16"];
const STATUS_COLORS: Record<string, string> = {
  completed: "#22c55e",
  in_progress: "#3b82f6",
  failed: "#ef4444",
  no_answer: "#f59e0b",
  busy: "#f97316",
  canceled: "#6b7280",
  initiated: "#8b5cf6",
  ringing: "#06b6d4",
};
const QA_SCORE_COLORS = ["#ef4444", "#f59e0b", "#eab308", "#22c55e", "#10b981"];

function fmtDuration(s: number) {
  if (!s || s <= 0) return "0s";
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}m ${sec}s`;
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

function daysToRange(days: number): { from: Date; to: Date } {
  const to = new Date();
  to.setHours(23, 59, 59, 999);
  const from = new Date(to.getTime() - (days - 1) * 86_400_000);
  from.setHours(0, 0, 0, 0);
  return { from, to };
}

interface AnalyticsData {
  date_from: string;
  date_to: string;
  overview: {
    total_calls: number;
    completed: number;
    missed: number;
    failed: number;
    transferred: number;
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
  by_assistant: { assistant_id: string; assistant_name: string; calls: number }[];
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

function ReportContent() {
  const params = useSearchParams();
  const { authFetch, loading: authLoading } = useAuthToken();

  const hotelId = params.get("hotel_id") || "";
  const tz = params.get("tz") || "UTC";
  const accountName = params.get("account_name") || "Account";
  const daysParam = params.get("days");

  const { dateFrom, dateTo } = useMemo(() => {
    const rawFrom = params.get("date_from");
    const rawTo = params.get("date_to");
    if (rawFrom && rawTo) return { dateFrom: rawFrom, dateTo: rawTo };
    const days = daysParam ? parseInt(daysParam, 10) : 7;
    const { from, to } = daysToRange(isNaN(days) ? 7 : days);
    return { dateFrom: from.toISOString(), dateTo: to.toISOString() };
  }, [params, daysParam]);

  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const generatedAt = useMemo(() => new Date().toLocaleString("en-US", { dateStyle: "long", timeStyle: "short" }), []);

  useEffect(() => {
    if (authLoading || !hotelId) return;
    setLoading(true);
    const urlParams = new URLSearchParams({ hotel_id: hotelId, timezone: tz });
    if (dateFrom) urlParams.set("date_from", dateFrom);
    if (dateTo) urlParams.set("date_to", dateTo);
    authFetch(`/api/analytics/calls?${urlParams}`)
      .then((r) => {
        if (!r.ok) throw new Error(`Failed to load analytics (${r.status})`);
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [authLoading, hotelId, dateFrom, dateTo, tz]);

  const volumeData = useMemo(() => {
    if (!data) return [];
    return data.volume_by_day.map((d) => ({
      ...d,
      date: new Date(d.date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    }));
  }, [data]);

  const hourData = useMemo(() => {
    if (!data) return [];
    const full = Array.from({ length: 24 }, (_, i) => ({ hour: i, calls: 0, label: `${i}:00` }));
    data.calls_by_hour.forEach((h) => { full[h.hour].calls = h.calls; });
    return full;
  }, [data]);

  if (!hotelId) {
    return (
      <div className="min-h-screen bg-white flex items-center justify-center">
        <div className="text-center max-w-sm">
          <p className="text-red-500 font-medium mb-2">Missing required parameter</p>
          <p className="text-gray-400 text-sm">The <code className="bg-gray-100 px-1 rounded">hotel_id</code> query parameter is required to generate this report.</p>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-white flex items-center justify-center">
        <div className="text-center">
          <div className="w-10 h-10 border-4 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-gray-500 text-sm">Loading analytics report…</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="min-h-screen bg-white flex items-center justify-center">
        <p className="text-red-500">{error || "No data available"}</p>
      </div>
    );
  }

  const o = data.overview;
  const tzLabel = tz === "UTC" ? "UTC" : tz.replace(/_/g, " ");
  const dateLabel = dateFrom && dateTo ? `${fmtDate(dateFrom)} – ${fmtDate(dateTo)}` : "All time";
  const totalDispositions = data.dispositions.reduce((a, b) => a + b.count, 0);

  return (
    <div className="report-root bg-white min-h-screen">
      <style>{`
        @media print {
          .no-print { display: none !important; }
          .report-root { padding: 0; }
          @page { margin: 15mm 12mm; }
        }
        .report-root { font-family: system-ui, -apple-system, sans-serif; }
      `}</style>

      <div className="max-w-[960px] mx-auto px-8 py-8">

        {/* Print button */}
        <div className="no-print flex justify-end mb-6">
          <button
            onClick={() => window.print()}
            className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors shadow-sm"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" />
            </svg>
            Print / Save as PDF
          </button>
        </div>

        {/* Header */}
        <div className="flex items-start justify-between mb-8 pb-6 border-b-2 border-gray-100">
          <div>
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
                <span className="text-lg font-bold text-white">B</span>
              </div>
              <span className="text-2xl font-bold text-gray-900">Botelier</span>
            </div>
            <h1 className="text-3xl font-bold text-gray-900 mb-1">Call Analytics Report</h1>
            <p className="text-gray-500 text-sm">{accountName}</p>
          </div>
          <div className="text-right text-sm text-gray-500 mt-1">
            <p className="font-medium text-gray-700">{dateLabel}</p>
            <p className="mt-0.5">{tzLabel} timezone</p>
            <p className="mt-2 text-xs">Generated {generatedAt}</p>
          </div>
        </div>

        {/* Stat cards */}
        <div className="grid grid-cols-3 gap-4 mb-8">
          <StatCard label="Total Calls" value={o.total_calls} sub={`${o.completed} completed`} />
          <StatCard label="Completion Rate" value={`${o.completion_rate}%`} sub={`${o.missed} missed`} color="text-green-600" />
          <StatCard label="Transfer Rate" value={`${o.transfer_rate}%`} sub={`${o.transferred} transferred`} color="text-blue-600" />
          <StatCard label="Avg AI Duration" value={fmtDuration(o.avg_ai_duration_seconds)} sub={`${fmtDuration(o.total_ai_duration_seconds)} total`} />
          <StatCard label="Avg Outbound Duration" value={fmtDuration(o.avg_outbound_duration_seconds)} sub={`${fmtDuration(o.total_outbound_duration_seconds)} total`} color="text-amber-600" />
          <StatCard
            label="Avg Quality Score"
            value={data.acw.avg_quality_score ?? "—"}
            sub={data.acw.avg_quality_score != null ? `${data.acw.min_quality_score}–${data.acw.max_quality_score} range` : "No ACW data"}
            color="text-purple-600"
          />
        </div>

        {/* Call Volume Over Time */}
        {volumeData.length > 0 && (
          <Section title="Call Volume Over Time">
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={volumeData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="date" tick={{ fill: "#6b7280", fontSize: 11 }} />
                <YAxis tick={{ fill: "#6b7280", fontSize: 11 }} allowDecimals={false} />
                <Tooltip />
                <Line type="monotone" dataKey="calls" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3, fill: "#3b82f6" }} name="Calls" />
              </LineChart>
            </ResponsiveContainer>
          </Section>
        )}

        {/* Calls by Hour */}
        {hourData.some((h) => h.calls > 0) && (
          <Section title="Calls by Hour of Day">
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={hourData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="label" tick={{ fill: "#6b7280", fontSize: 10 }} interval={2} />
                <YAxis tick={{ fill: "#6b7280", fontSize: 11 }} allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="calls" fill="#8b5cf6" radius={[3, 3, 0, 0]} name="Calls" />
              </BarChart>
            </ResponsiveContainer>
          </Section>
        )}

        {/* Status Breakdown (donut) + Outcome/Disposition Breakdown (donut) — side by side */}
        <div className="grid grid-cols-2 gap-6 mb-6">
          {data.status_distribution.length > 0 && (
            <Section title="Status Breakdown" noMargin>
              <div className="flex items-center gap-4">
                <PieChart width={130} height={130}>
                  <Pie
                    data={data.status_distribution}
                    dataKey="count"
                    nameKey="status"
                    cx="50%"
                    cy="50%"
                    innerRadius={30}
                    outerRadius={55}
                    paddingAngle={2}
                  >
                    {data.status_distribution.map((d, i) => (
                      <Cell key={d.status} fill={STATUS_COLORS[d.status] || CHART_COLORS[i % CHART_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
                <div className="flex-1 space-y-1.5">
                  {data.status_distribution.map((d, i) => (
                    <div key={d.status} className="flex items-center justify-between text-sm">
                      <div className="flex items-center gap-2">
                        <span
                          className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                          style={{ backgroundColor: STATUS_COLORS[d.status] || CHART_COLORS[i % CHART_COLORS.length] }}
                        />
                        <span className="text-gray-700 capitalize">{d.status.replace(/_/g, " ")}</span>
                      </div>
                      <span className="text-gray-500 font-medium">{d.count}</span>
                    </div>
                  ))}
                </div>
              </div>
            </Section>
          )}

          {data.dispositions.length > 0 && (
            <Section title="Outcome Breakdown" noMargin>
              <div className="flex items-center gap-4">
                <PieChart width={130} height={130}>
                  <Pie
                    data={data.dispositions}
                    dataKey="count"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius={30}
                    outerRadius={55}
                    paddingAngle={2}
                  >
                    {data.dispositions.map((d, i) => (
                      <Cell key={d.disposition_id} fill={d.color || CHART_COLORS[i % CHART_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
                <div className="flex-1 space-y-1.5">
                  {data.dispositions.map((d, i) => {
                    const pct = totalDispositions > 0 ? Math.round((d.count / totalDispositions) * 100) : 0;
                    return (
                      <div key={d.disposition_id} className="flex items-center justify-between text-sm">
                        <div className="flex items-center gap-2">
                          <span
                            className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                            style={{ backgroundColor: d.color || CHART_COLORS[i % CHART_COLORS.length] }}
                          />
                          <span className="text-gray-700 truncate max-w-[100px]">{d.name}</span>
                        </div>
                        <span className="text-gray-500 font-medium">{d.count} ({pct}%)</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </Section>
          )}
        </div>

        {/* Calls by Assistant */}
        {data.by_assistant.length > 0 && (
          <Section title="Calls by Assistant">
            <ResponsiveContainer width="100%" height={Math.max(120, data.by_assistant.length * 36)}>
              <BarChart data={data.by_assistant} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis type="number" tick={{ fill: "#6b7280", fontSize: 11 }} allowDecimals={false} />
                <YAxis type="category" dataKey="assistant_name" tick={{ fill: "#6b7280", fontSize: 11 }} width={130} />
                <Tooltip />
                <Bar dataKey="calls" fill="#22c55e" radius={[0, 3, 3, 0]} name="Calls" />
              </BarChart>
            </ResponsiveContainer>
          </Section>
        )}

        {/* Post-Call QA */}
        {(data.acw.score_distribution.some((d) => d.count > 0) || data.acw.resolution_distribution.length > 0) && (
          <>
            <div className="mt-8 mb-4 pt-6 border-t border-gray-100">
              <h2 className="text-lg font-bold text-gray-800">Post-Call QA Metrics</h2>
              <p className="text-sm text-gray-500 mt-0.5">
                {data.acw.acw_completed} calls with QA completed ({data.acw.acw_completion_rate}%)
              </p>
            </div>

            <div className="grid grid-cols-2 gap-6 mb-8">
              {data.acw.score_distribution.some((d) => d.count > 0) && (
                <Section title="Quality Score Distribution" noMargin>
                  <ResponsiveContainer width="100%" height={160}>
                    <BarChart data={data.acw.score_distribution}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                      <XAxis dataKey="range" tick={{ fill: "#6b7280", fontSize: 11 }} />
                      <YAxis tick={{ fill: "#6b7280", fontSize: 11 }} allowDecimals={false} />
                      <Tooltip />
                      <Bar dataKey="count" radius={[3, 3, 0, 0]} name="Calls">
                        {data.acw.score_distribution.map((_, i) => (
                          <Cell key={i} fill={QA_SCORE_COLORS[i]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </Section>
              )}

              {data.acw.resolution_distribution.length > 0 && (
                <Section title="Resolution Status" noMargin>
                  <div className="space-y-2.5">
                    {data.acw.resolution_distribution.map((d, i) => {
                      const total = data.acw.resolution_distribution.reduce((a, b) => a + b.count, 0);
                      const pct = total > 0 ? (d.count / total) * 100 : 0;
                      return (
                        <div key={d.resolution}>
                          <div className="flex items-center justify-between text-sm mb-1">
                            <span className="text-gray-700">{d.resolution}</span>
                            <span className="text-gray-500">{d.count} ({Math.round(pct)}%)</span>
                          </div>
                          <div className="w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
                            <div
                              className="h-full rounded-full"
                              style={{ width: `${pct}%`, backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </Section>
              )}
            </div>
          </>
        )}

        {/* Footer */}
        <div className="border-t border-gray-100 pt-4 mt-8 flex items-center justify-between text-xs text-gray-400">
          <span>Generated by Botelier Voice AI Platform</span>
          <span>{generatedAt}</span>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, sub, color = "text-gray-900" }: {
  label: string;
  value: string | number;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="bg-gray-50 border border-gray-200 rounded-xl p-4">
      <p className="text-xs text-gray-500 mb-1 font-medium uppercase tracking-wide">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

function Section({ title, children, noMargin = false }: {
  title: string;
  children: React.ReactNode;
  noMargin?: boolean;
}) {
  return (
    <div className={`bg-white border border-gray-200 rounded-xl p-5 ${noMargin ? "" : "mb-6"}`}>
      <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">{title}</h3>
      {children}
    </div>
  );
}

export default function CallAnalyticsReportPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-white flex items-center justify-center">
        <div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin" />
      </div>
    }>
      <ReportContent />
    </Suspense>
  );
}
