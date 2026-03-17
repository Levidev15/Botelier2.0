"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { X, Loader2, ExternalLink, ChevronLeft, ChevronRight, FileText } from "lucide-react";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { DateRange } from "./DateRangePicker";

interface DrilldownRecord {
  id: string;
  reference_id: string | null;
  started_at: string | null;
  caller_number: string | null;
  to_number: string | null;
  status: string;
  duration_seconds: number;
  has_transfer: boolean;
  assistant_id: string | null;
  assistant_name: string | null;
  phone_number_display: string | null;
  disposition_id: string | null;
  disposition_name: string | null;
  disposition_color: string | null;
  acw_quality_score: number | null;
  acw_resolution: string | null;
}

interface DrilldownResponse {
  records: DrilldownRecord[];
  total: number;
  page: number;
  limit: number;
  pages: number;
  metric: string;
}

interface DrilldownPanelProps {
  open: boolean;
  metric: string;
  metricLabel: string;
  dateRange: DateRange;
  assistantIds: string[];
  onClose: () => void;
  onViewTranscript: (logId: string) => void;
}

const STATUS_COLORS: Record<string, string> = {
  completed: "bg-green-500/15 text-green-400",
  in_progress: "bg-blue-500/15 text-blue-400",
  failed: "bg-red-500/15 text-red-400",
  no_answer: "bg-yellow-500/15 text-yellow-400",
  busy: "bg-orange-500/15 text-orange-400",
  canceled: "bg-gray-500/15 text-gray-400",
  initiated: "bg-purple-500/15 text-purple-400",
  ringing: "bg-cyan-500/15 text-cyan-400",
};

function fmtDuration(s: number) {
  if (!s || s < 0) return "0:00";
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

const PAGE_LIMIT = 25;

export default function DrilldownPanel({
  open,
  metric,
  metricLabel,
  dateRange,
  assistantIds,
  onClose,
  onViewTranscript,
}: DrilldownPanelProps) {
  const { accountId } = useAccountContext();
  const router = useRouter();
  const [data, setData] = useState<DrilldownResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);

  const fetchData = useCallback(
    async (p: number) => {
      if (!accountId || !open || !metric) return;
      setLoading(true);
      try {
        const params = new URLSearchParams({
          hotel_id: accountId,
          metric,
          date_from: dateRange.from.toISOString(),
          date_to: dateRange.to.toISOString(),
          page: String(p),
          limit: String(PAGE_LIMIT),
        });
        assistantIds.forEach((id) => params.append("assistant_ids", id));
        const r = await fetch(`/api/analytics/calls/drilldown?${params}`);
        if (!r.ok) throw new Error("Failed");
        setData(await r.json());
      } catch {
        setData(null);
      } finally {
        setLoading(false);
      }
    },
    [accountId, open, metric, dateRange, assistantIds]
  );

  useEffect(() => {
    setPage(1);
    fetchData(1);
  }, [fetchData]);

  useEffect(() => {
    if (page > 1) fetchData(page);
  }, [page, fetchData]);

  function handleViewInCallLogs() {
    const params = new URLSearchParams();
    if (metric.startsWith("status:")) params.set("status", metric.slice(7));
    router.push(`/dashboard/call-logs?${params}`);
    onClose();
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="absolute right-0 top-0 h-full w-full max-w-2xl bg-[#141414] border-l border-gray-800 flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800 flex-shrink-0">
          <div>
            <h2 className="text-base font-semibold text-gray-100">{metricLabel}</h2>
            {data && (
              <p className="text-sm text-gray-500 mt-0.5">
                {data.total} call{data.total !== 1 ? "s" : ""}
                {" · "}
                {dateRange.from.toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                {" – "}
                {dateRange.to.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg text-gray-500 hover:text-gray-200 hover:bg-gray-800 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {loading && !data && (
            <div className="flex items-center justify-center h-40">
              <Loader2 className="h-6 w-6 animate-spin text-gray-500" />
            </div>
          )}

          {!loading && data?.records.length === 0 && (
            <div className="flex items-center justify-center h-40">
              <p className="text-gray-500 text-sm">No calls match this filter</p>
            </div>
          )}

          {data && data.records.length > 0 && (
            <div className="divide-y divide-gray-800">
              {data.records.map((rec) => (
                <div key={rec.id} className="px-6 py-4 hover:bg-[#1a1a1a] transition-colors">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0 space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        {rec.reference_id && (
                          <span className="font-mono text-xs bg-gray-800 text-gray-400 px-1.5 py-0.5 rounded">
                            #{rec.reference_id}
                          </span>
                        )}
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                            STATUS_COLORS[rec.status] ?? "bg-gray-700 text-gray-400"
                          }`}
                        >
                          {rec.status.replace(/_/g, " ")}
                        </span>
                        {rec.disposition_name && (
                          <span
                            className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                            style={{
                              backgroundColor: rec.disposition_color ? `${rec.disposition_color}22` : "#374151",
                              color: rec.disposition_color ?? "#9ca3af",
                            }}
                          >
                            {rec.disposition_name}
                          </span>
                        )}
                        {rec.acw_quality_score != null && (
                          <span className="text-xs text-purple-400 font-medium">
                            QA {rec.acw_quality_score}
                          </span>
                        )}
                      </div>
                      <div className="text-sm text-gray-300">
                        {rec.caller_number ?? rec.to_number ?? "Unknown"}
                        {rec.assistant_name && (
                          <span className="text-gray-500"> · {rec.assistant_name}</span>
                        )}
                      </div>
                      <div className="text-xs text-gray-500 flex items-center gap-2">
                        <span>{fmtDateTime(rec.started_at)}</span>
                        <span>·</span>
                        <span>{fmtDuration(rec.duration_seconds)}</span>
                        {rec.has_transfer && <span className="text-blue-400">· Transferred</span>}
                      </div>
                    </div>
                    <button
                      onClick={() => onViewTranscript(rec.id)}
                      className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 text-xs bg-[#252525] border border-gray-700 rounded-lg text-gray-400 hover:text-gray-100 hover:border-gray-500 transition-colors"
                    >
                      <FileText className="h-3.5 w-3.5" />
                      Transcript
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {loading && data && (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 border-t border-gray-800 px-6 py-4">
          <div className="flex items-center justify-between">
            <button
              onClick={handleViewInCallLogs}
              className="flex items-center gap-2 text-sm text-blue-400 hover:text-blue-300 transition-colors"
            >
              <ExternalLink className="h-4 w-4" />
              View all in Call Logs
            </button>

            {data && data.pages > 1 && (
              <div className="flex items-center gap-2">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                  className="p-1.5 rounded-lg text-gray-400 hover:text-gray-100 hover:bg-gray-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="text-sm text-gray-400">
                  {page} / {data.pages}
                </span>
                <button
                  disabled={page >= data.pages}
                  onClick={() => setPage((p) => p + 1)}
                  className="p-1.5 rounded-lg text-gray-400 hover:text-gray-100 hover:bg-gray-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
