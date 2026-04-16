"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { X, Loader2, ExternalLink, ChevronLeft, ChevronRight, FileText } from "lucide-react";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
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

export interface TranscriptCallLog {
  id: string;
  account_id?: string;
  reference_id?: string | null;
  caller_number: string | null;
  to_number: string | null;
  status: string;
  started_at: string | null;
  duration_seconds: number;
  has_transfer: boolean;
  transcript: Array<{ role: string; content?: string; text?: string; timestamp?: string; interrupted?: boolean }> | null;
  legs: Array<{ id: string; leg_number: number; leg_type: string; participant: string | null; participant_name: string | null; status: string; duration_seconds: number }>;
  assistant_name: string | null;
  phone_number_display: string | null;
  ai_summary: string | null;
  disposition_name: string | null;
  disposition_color: string | null;
  tool_name: string | null;
  flow_name: string | null;
  acw_resolution: string | null;
  acw_quality_score: number | null;
}

interface DrilldownPanelProps {
  open: boolean;
  metric: string;
  metricLabel: string;
  dateRange: DateRange;
  assistantIds: string[];
  timezone?: string;
  onClose: () => void;
  onViewTranscript: (logId: string) => void;
}


function fmtDuration(s: number) {
  if (!s || s < 0) return "0:00";
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

function fmtDateTime(iso: string | null, tz?: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone: tz,
  });
}

function toDateParam(d: Date): string {
  return d.toISOString().slice(0, 10);
}

const PAGE_LIMIT = 25;

export default function DrilldownPanel({
  open,
  metric,
  metricLabel,
  dateRange,
  assistantIds,
  timezone,
  onClose,
  onViewTranscript,
}: DrilldownPanelProps) {
  const { accountId } = useAccountContext();
  const { authFetch } = useAuthToken();
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
          account_id: accountId,
          metric,
          date_from: dateRange.from.toISOString(),
          date_to: dateRange.to.toISOString(),
          timezone: timezone ?? "UTC",
          page: String(p),
          limit: String(PAGE_LIMIT),
        });
        assistantIds.forEach((id) => params.append("assistant_ids", id));
        const r = await authFetch(`/api/analytics/calls/drilldown?${params}`);
        if (!r.ok) throw new Error("Failed");
        setData(await r.json());
      } catch {
        setData(null);
      } finally {
        setLoading(false);
      }
    },
    [accountId, open, metric, dateRange, assistantIds, timezone, authFetch]
  );

  // Track previous fetchData identity to distinguish query changes from page changes.
  // When fetchData changes (metric/dateRange/assistantIds changed), reset to page 1.
  // When only page changes, fetch that page without resetting.
  const prevFetchDataRef = useRef(fetchData);

  useEffect(() => {
    const isNewQuery = prevFetchDataRef.current !== fetchData;
    prevFetchDataRef.current = fetchData;
    if (isNewQuery) {
      setPage(1);
      fetchData(1);
    } else {
      fetchData(page);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchData, page]);

  /**
   * Map the current metric token to exact Call Logs URL params so that
   * "View all in Call Logs" always opens a pre-filtered view matching this drilldown.
   */
  function buildCallLogsTarget(): string {
    const params = new URLSearchParams();
    params.set("date_from", toDateParam(dateRange.from));
    params.set("date_to", toDateParam(dateRange.to));

    if (metric === "all") {
      // no extra filter — all calls in date range
    } else if (metric === "completed") {
      params.set("status", "completed");
    } else if (metric === "failed") {
      params.set("status", "failed");
    } else if (metric === "missed") {
      params.set("status", "missed"); // backend expands to no_answer|busy|canceled
    } else if (metric === "transferred") {
      params.set("has_transfer", "true");
    } else if (metric === "acw_completed") {
      params.set("acw_completed", "true");
    } else if (metric === "ai_handled") {
      // Task #97 partition: greeted=true on completed/ringing/in_progress/ended_early.
      // Call Logs page doesn't support this compound predicate as a single filter
      // today, so we approximate with the closest legacy slice — status=completed.
      // Users see a superset-free slice and can refine from there.
      params.set("status", "completed");
    } else if (metric === "ended_early_dropped") {
      // Task #97 partition: status=ended_early AND greeted=false. Call Logs
      // doesn't filter by greeted yet; approximate with status=ended_early.
      params.set("status", "ended_early");
    } else if (metric === "unresolved") {
      // Task #97 partition: status=initiated OR (ringing/in_progress AND
      // greeted=false). Call Logs supports status=initiated as the closest
      // single-status approximation; covers the dominant case in practice.
      params.set("status", "initiated");
    } else if (metric.startsWith("status:")) {
      params.set("status", metric.slice(7));
    } else if (metric.startsWith("assistant:")) {
      params.set("assistant_id", metric.slice(10));
    } else if (metric.startsWith("disposition:")) {
      params.set("disposition_id", metric.slice(12));
    } else if (metric.startsWith("hour:")) {
      params.set("hour", metric.slice(5));
    } else if (metric.startsWith("quality_range:")) {
      const label = metric.slice(14); // e.g. "0-20", "81-100"
      const parts = label.split("-");
      if (parts.length === 2) {
        params.set("quality_min", parts[0]);
        params.set("quality_max", parts[1]);
      }
    }

    // Apply assistant filter — Call Logs supports a single assistant_id param.
    // When exactly one assistant is active, it is preserved; when multiple are selected
    // the date range alone is used (multi-assistant cannot be expressed as a single
    // Call Logs filter without backend changes to support assistant_ids[]).
    if (assistantIds.length === 1 && !params.has("assistant_id")) {
      params.set("assistant_id", assistantIds[0]);
    }

    return `/dashboard/call-logs?${params}`;
  }

  const callLogsUrl = buildCallLogsTarget();

  function handleViewInCallLogs() {
    router.push(callLogsUrl);
    onClose();
  }

  if (!open) return null;

  const skeletonRows = Array.from({ length: 8 });

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="absolute right-0 top-0 h-full w-full max-w-5xl bg-[#141414] border-l border-gray-800 flex flex-col shadow-2xl">
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

        {/* Body — scrollable table */}
        <div className="flex-1 overflow-auto">
          <table className="w-full text-sm border-collapse">
            <thead className="sticky top-0 bg-[#1a1a1a] border-b border-gray-800 z-10">
              <tr>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">Ref</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">Date & Time</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">Caller</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">Assistant</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">Duration</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">Disposition</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">QA</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/60">
              {/* Skeleton rows */}
              {loading && !data &&
                skeletonRows.map((_, i) => (
                  <tr key={i} className="animate-pulse">
                    <td className="px-4 py-3">
                      <div className="h-4 w-24 bg-gray-800 rounded" />
                    </td>
                    <td className="px-4 py-3">
                      <div className="h-4 w-28 bg-gray-800 rounded" />
                    </td>
                    <td className="px-4 py-3">
                      <div className="h-4 w-24 bg-gray-800 rounded" />
                    </td>
                    <td className="px-4 py-3">
                      <div className="h-4 w-20 bg-gray-800 rounded" />
                    </td>
                    <td className="px-4 py-3">
                      <div className="h-4 w-12 bg-gray-800 rounded" />
                    </td>
                    <td className="px-4 py-3">
                      <div className="h-4 w-16 bg-gray-800 rounded" />
                    </td>
                    <td className="px-4 py-3">
                      <div className="h-4 w-8 bg-gray-800 rounded" />
                    </td>
                  </tr>
                ))}

              {/* Empty state */}
              {!loading && data?.records.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-16 text-center text-sm text-gray-500">
                    No calls match this filter
                  </td>
                </tr>
              )}

              {/* Data rows — entire row is clickable to open transcript */}
              {data?.records.map((rec) => (
                <tr
                  key={rec.id}
                  onClick={() => onViewTranscript(rec.id)}
                  className="hover:bg-[#1a1a1a] transition-colors cursor-pointer group"
                  title="Click to view transcript"
                >
                  {/* Ref */}
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span className="font-mono text-xs bg-gray-800 text-gray-400 px-1.5 py-0.5 rounded">
                      {rec.reference_id ? `#${rec.reference_id}` : "—"}
                    </span>
                  </td>

                  {/* Date & Time */}
                  <td className="px-4 py-3 text-gray-400 whitespace-nowrap text-xs">
                    {fmtDateTime(rec.started_at, timezone)}
                  </td>

                  {/* Caller */}
                  <td className="px-4 py-3 text-gray-300 whitespace-nowrap text-xs font-mono">
                    {rec.caller_number ?? rec.to_number ?? "—"}
                    {rec.has_transfer && (
                      <span className="ml-1 text-blue-400 font-sans font-normal">↗</span>
                    )}
                  </td>

                  {/* Assistant */}
                  <td className="px-4 py-3 text-gray-400 text-xs max-w-[120px] truncate">
                    {rec.assistant_name ?? "—"}
                  </td>

                  {/* Duration */}
                  <td className="px-4 py-3 text-gray-400 whitespace-nowrap text-xs">
                    {fmtDuration(rec.duration_seconds)}
                  </td>

                  {/* Disposition */}
                  <td className="px-4 py-3 whitespace-nowrap">
                    {rec.disposition_name ? (
                      <span
                        className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                        style={{
                          backgroundColor: rec.disposition_color ? `${rec.disposition_color}22` : "#374151",
                          color: rec.disposition_color ?? "#9ca3af",
                        }}
                      >
                        {rec.disposition_name}
                      </span>
                    ) : (
                      <span className="text-gray-600 text-xs">—</span>
                    )}
                  </td>

                  {/* QA Score + transcript icon on hover */}
                  <td className="px-4 py-3 whitespace-nowrap min-w-[80px]">
                    <div className="flex items-center gap-3">
                      {rec.acw_quality_score != null ? (
                        <span className="text-xs text-purple-400 font-medium">{rec.acw_quality_score}</span>
                      ) : (
                        <span className="text-gray-600 text-xs">—</span>
                      )}
                      <FileText className="h-3.5 w-3.5 text-gray-700 group-hover:text-gray-400 transition-colors flex-shrink-0" />
                    </div>
                  </td>
                </tr>
              ))}

              {/* Inline refresh indicator */}
              {loading && data && (
                <tr>
                  <td colSpan={7} className="py-3 text-center">
                    <Loader2 className="h-4 w-4 animate-spin text-gray-500 inline-block" />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 border-t border-gray-800 px-6 py-3">
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
                <span className="text-xs text-gray-500">
                  {(page - 1) * PAGE_LIMIT + 1}–{Math.min(page * PAGE_LIMIT, data.total)} of {data.total}
                </span>
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                  className="p-1.5 rounded-lg text-gray-400 hover:text-gray-100 hover:bg-gray-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
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
