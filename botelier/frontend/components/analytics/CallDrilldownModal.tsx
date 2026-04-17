"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  X, Loader2, ExternalLink, ChevronLeft, ChevronRight, FileText,
  Play, Pencil, Clock,
} from "lucide-react";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { usePermissions } from "@/lib/auth/usePermissions";
import { notify } from "@/lib/notifications";
import { DateRange } from "./DateRangePicker";
import EditCallLogModal from "@/app/(dashboard)/dashboard/call-logs/components/EditCallLogModal";

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
  recording_url: string | null;
  recording_sid: string | null;
}

/**
 * Shape consumed by the page-level TranscriptModal when the user clicks a
 * row in the drilldown. Re-exported here so the analytics page has a single
 * import path for everything drilldown-related.
 */
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

interface DrilldownResponse {
  records: DrilldownRecord[];
  total: number;
  page: number;
  limit: number;
  pages: number;
  metric: string;
}

interface CallDrilldownModalProps {
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

/**
 * Inline lazy recording player — mirrors the CallLogRow pattern. We never
 * embed `recording_url` directly because it points at Twilio media that
 * requires our auth proxy. Audio is fetched only after the user clicks Play
 * (`preload="none"` semantics) and the resulting blob URL is revoked on unmount.
 */
function RecordingCell({
  callId,
  durationSeconds,
  hasRecording,
}: {
  callId: string;
  durationSeconds: number;
  hasRecording: boolean;
}) {
  const { authFetch } = useAuthToken();
  const [showPlayer, setShowPlayer] = useState(false);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [loadingAudio, setLoadingAudio] = useState(false);

  useEffect(() => {
    return () => {
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [blobUrl]);

  const togglePlayer = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (showPlayer) {
      setShowPlayer(false);
      return;
    }
    if (!blobUrl && !loadingAudio) {
      setLoadingAudio(true);
      try {
        const res = await authFetch(`/api/calls/${callId}/recording`);
        if (!res.ok) throw new Error("Failed to load recording");
        const blob = await res.blob();
        setBlobUrl(URL.createObjectURL(blob));
      } catch {
        notify.error("Failed to load recording");
        setLoadingAudio(false);
        return;
      }
      setLoadingAudio(false);
    }
    setShowPlayer(true);
  };

  if (!hasRecording) {
    return (
      <span className="inline-flex items-center gap-1 text-gray-600 text-xs">
        <Clock className="h-3 w-3" />
        {fmtDuration(durationSeconds)}
      </span>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      <button
        onClick={togglePlayer}
        className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border transition-all w-fit ${
          showPlayer
            ? "bg-blue-500/20 border-blue-500/50 text-blue-300"
            : "bg-blue-500/10 border-blue-500/30 text-blue-400 hover:bg-blue-500/20 hover:border-blue-500/50 hover:text-blue-300"
        }`}
        title={showPlayer ? "Hide recording" : "Play recording"}
      >
        {loadingAudio ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <Play className="h-3 w-3 fill-current" />
        )}
        {fmtDuration(durationSeconds)}
      </button>
      {showPlayer && blobUrl && (
        <audio
          controls
          autoPlay
          preload="none"
          src={blobUrl}
          onClick={(e) => e.stopPropagation()}
          className="h-7 w-56"
          style={{ colorScheme: "dark" }}
        />
      )}
    </div>
  );
}

export default function CallDrilldownModal({
  open,
  metric,
  metricLabel,
  dateRange,
  assistantIds,
  timezone,
  onClose,
  onViewTranscript,
}: CallDrilldownModalProps) {
  const { accountId } = useAccountContext();
  const { authFetch } = useAuthToken();
  const { can, isPlatformAdmin } = usePermissions();
  const router = useRouter();
  const [data, setData] = useState<DrilldownResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [silentOnly, setSilentOnly] = useState(false);
  const [editingRecord, setEditingRecord] = useState<DrilldownRecord | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeBtnRef = useRef<HTMLButtonElement>(null);

  const supportsSilentToggle = metric === "unresolved";
  const canEditLogs = isPlatformAdmin || can("call_logs", "edit");
  const canPlayRecordings = isPlatformAdmin || can("call_logs", "play_recordings");

  const effectiveMetric =
    supportsSilentToggle && silentOnly ? "silent_caller" : metric;

  const fetchData = useCallback(
    async (p: number) => {
      if (!accountId || !open || !metric) return;
      setLoading(true);
      try {
        const params = new URLSearchParams({
          account_id: accountId,
          metric: effectiveMetric,
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
    [accountId, open, metric, effectiveMetric, dateRange, assistantIds, timezone, authFetch]
  );

  useEffect(() => {
    setSilentOnly(false);
  }, [metric]);

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

  // ESC + scroll lock + focus trap while open. We:
  //   1. Save the element that was focused before the modal opened so we can
  //      restore focus when it closes (avoids the "lost focus" jump).
  //   2. Move initial focus to the close button so keyboard users land
  //      inside the dialog.
  //   3. Trap Tab / Shift+Tab so focus cycles through the dialog's own
  //      focusable elements only — required for accessible modals.
  //   4. Lock body scroll behind the backdrop.
  // The trap intentionally lets focus pass through to a nested EditCallLogModal
  // because that child modal mounts as a sibling overlay and grabs its own
  // focus when opened.
  useEffect(() => {
    if (!open) return;

    const previouslyFocused = document.activeElement as HTMLElement | null;
    const focusableSelector =
      'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    // Defer initial focus by one tick so dialogRef is mounted.
    const focusTimer = window.setTimeout(() => {
      closeBtnRef.current?.focus();
    }, 0);

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;

      // If a nested modal (EditCallLogModal) is open, defer to it — don't
      // trap inside the parent dialog.
      if (editingRecord) return;

      const root = dialogRef.current;
      if (!root) return;
      const focusables = Array.from(
        root.querySelectorAll<HTMLElement>(focusableSelector)
      ).filter((el) => el.offsetParent !== null);
      if (focusables.length === 0) {
        e.preventDefault();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey) {
        if (active === first || !root.contains(active)) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      // Restore focus to whatever opened the modal.
      previouslyFocused?.focus?.();
    };
  }, [open, onClose, editingRecord]);

  function buildCallLogsTarget(): string {
    const params = new URLSearchParams();
    params.set("date_from", toDateParam(dateRange.from));
    params.set("date_to", toDateParam(dateRange.to));

    const target = effectiveMetric;

    if (target === "silent_caller") {
      // No status filter — Call Logs has no caller_spoke filter today.
    } else if (target === "all") {
      // no extra filter
    } else if (metric === "completed") {
      params.set("status", "completed");
    } else if (metric === "failed") {
      params.set("status", "failed");
    } else if (metric === "missed") {
      params.set("status", "missed");
    } else if (metric === "transferred") {
      params.set("has_transfer", "true");
    } else if (metric === "acw_completed") {
      params.set("acw_completed", "true");
    } else if (metric === "ai_handled") {
      params.set("status", "completed");
    } else if (metric === "ended_early") {
      params.set("status", "ended_early");
    } else if (metric === "unresolved") {
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
      const label = metric.slice(14);
      const parts = label.split("-");
      if (parts.length === 2) {
        params.set("quality_min", parts[0]);
        params.set("quality_max", parts[1]);
      }
    }

    if (assistantIds.length === 1 && !params.has("assistant_id")) {
      params.set("assistant_id", assistantIds[0]);
    }

    return `/dashboard/call-logs?${params}`;
  }

  function handleViewInCallLogs() {
    router.push(buildCallLogsTarget());
    onClose();
  }

  /**
   * Apply an in-place patch to a single row after the EditCallLogModal saves.
   * No refetch — the PATCH endpoint already returned the canonical values.
   */
  function applyRowPatch(
    rowId: string,
    patch: Partial<Pick<DrilldownRecord,
      "disposition_id" | "disposition_name" | "disposition_color" | "acw_resolution"
    >>,
  ) {
    setData((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        records: prev.records.map((r) =>
          r.id === rowId ? { ...r, ...patch } : r
        ),
      };
    });
  }

  if (!open) return null;

  const skeletonRows = Array.from({ length: 8 });
  const colCount = canEditLogs ? 8 : 7;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={metricLabel}
        className="relative w-full max-w-5xl max-h-[88vh] bg-[#141414] border border-gray-800 rounded-2xl shadow-2xl flex flex-col overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800 flex-shrink-0">
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-semibold text-gray-100">
              {metricLabel}
              {silentOnly && (
                <span className="ml-2 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide rounded bg-yellow-500/15 text-yellow-300 border border-yellow-500/30 align-middle">
                  Silent only
                </span>
              )}
            </h2>
            {data && (
              <p className="text-sm text-gray-500 mt-0.5">
                {data.total} call{data.total !== 1 ? "s" : ""}
                {" · "}
                {dateRange.from.toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                {" – "}
                {dateRange.to.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
              </p>
            )}
            {supportsSilentToggle && (
              <label
                className="mt-2 inline-flex items-center gap-2 text-xs text-gray-400 cursor-pointer select-none"
                title="Show only calls where the AI greeted but the caller never spoke (silent line)"
              >
                <input
                  type="checkbox"
                  checked={silentOnly}
                  onChange={(e) => setSilentOnly(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-gray-600 bg-gray-800 text-yellow-400 focus:ring-yellow-500/40 focus:ring-offset-0"
                />
                Silent caller only
              </label>
            )}
          </div>
          <button
            ref={closeBtnRef}
            onClick={onClose}
            className="p-2 rounded-lg text-gray-500 hover:text-gray-200 hover:bg-gray-800 transition-colors"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto">
          <table className="w-full text-sm border-collapse">
            <thead className="sticky top-0 bg-[#1a1a1a] border-b border-gray-800 z-10">
              <tr>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">Ref</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">Date & Time</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">Caller</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">Assistant</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">Recording</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">Disposition</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">QA</th>
                {canEditLogs && (
                  <th className="text-right px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">Edit</th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/60">
              {loading && !data &&
                skeletonRows.map((_, i) => (
                  <tr key={i} className="animate-pulse">
                    <td className="px-4 py-3"><div className="h-4 w-24 bg-gray-800 rounded" /></td>
                    <td className="px-4 py-3"><div className="h-4 w-28 bg-gray-800 rounded" /></td>
                    <td className="px-4 py-3"><div className="h-4 w-24 bg-gray-800 rounded" /></td>
                    <td className="px-4 py-3"><div className="h-4 w-20 bg-gray-800 rounded" /></td>
                    <td className="px-4 py-3"><div className="h-4 w-16 bg-gray-800 rounded" /></td>
                    <td className="px-4 py-3"><div className="h-4 w-16 bg-gray-800 rounded" /></td>
                    <td className="px-4 py-3"><div className="h-4 w-8 bg-gray-800 rounded" /></td>
                    {canEditLogs && (
                      <td className="px-4 py-3"><div className="h-4 w-6 bg-gray-800 rounded ml-auto" /></td>
                    )}
                  </tr>
                ))}

              {!loading && data?.records.length === 0 && (
                <tr>
                  <td colSpan={colCount} className="px-4 py-16 text-center text-sm text-gray-500">
                    No calls match this filter
                  </td>
                </tr>
              )}

              {data?.records.map((rec) => {
                const hasRecording = !!rec.recording_url && canPlayRecordings;
                return (
                  <tr
                    key={rec.id}
                    onClick={() => onViewTranscript(rec.id)}
                    className="hover:bg-[#1a1a1a] transition-colors cursor-pointer group align-top"
                    title="Click to view transcript"
                  >
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className="font-mono text-xs bg-gray-800 text-gray-400 px-1.5 py-0.5 rounded">
                        {rec.reference_id ? `#${rec.reference_id}` : "—"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-400 whitespace-nowrap text-xs">
                      {fmtDateTime(rec.started_at, timezone)}
                    </td>
                    <td className="px-4 py-3 text-gray-300 whitespace-nowrap text-xs font-mono">
                      {rec.caller_number ?? rec.to_number ?? "—"}
                      {rec.has_transfer && (
                        <span className="ml-1 text-blue-400 font-sans font-normal">↗</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-400 text-xs max-w-[120px] truncate">
                      {rec.assistant_name ?? "—"}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                      <RecordingCell
                        callId={rec.id}
                        durationSeconds={rec.duration_seconds}
                        hasRecording={hasRecording}
                      />
                    </td>
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
                      {rec.acw_resolution && (
                        <div className="mt-1">
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] border bg-blue-500/10 border-blue-500/30 text-blue-400">
                            {rec.acw_resolution}
                          </span>
                        </div>
                      )}
                    </td>
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
                    {canEditLogs && (
                      <td className="px-4 py-3 text-right whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setEditingRecord(rec);
                          }}
                          className="p-1.5 text-gray-500 hover:text-blue-400 hover:bg-gray-800 rounded-lg transition-colors"
                          title="Edit disposition / resolution"
                          aria-label="Edit call log"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })}

              {loading && data && (
                <tr>
                  <td colSpan={colCount} className="py-3 text-center">
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
                  aria-label="Previous page"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <button
                  disabled={page >= data.pages}
                  onClick={() => setPage((p) => p + 1)}
                  className="p-1.5 rounded-lg text-gray-400 hover:text-gray-100 hover:bg-gray-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  aria-label="Next page"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Inline edit modal — reuses the Call Logs editor and the existing
          PATCH /api/call-logs/{id} endpoint. No refetch on save: we mutate
          the visible row in place from the response payload. */}
      {editingRecord && accountId && (
        <EditCallLogModal
          log={{
            id: editingRecord.id,
            account_id: accountId,
            assistant_id: editingRecord.assistant_id,
            disposition_id: editingRecord.disposition_id,
            disposition_name: editingRecord.disposition_name,
            disposition_color: editingRecord.disposition_color,
            acw_resolution: editingRecord.acw_resolution,
          }}
          accountId={accountId}
          authFetch={authFetch}
          onClose={() => setEditingRecord(null)}
          onSaved={(updates) => {
            applyRowPatch(editingRecord.id, {
              disposition_id: updates.disposition_id ?? null,
              disposition_name: updates.disposition_name ?? null,
              disposition_color: updates.disposition_color ?? null,
              acw_resolution: updates.acw_resolution ?? null,
            });
          }}
        />
      )}
    </div>
  );
}
