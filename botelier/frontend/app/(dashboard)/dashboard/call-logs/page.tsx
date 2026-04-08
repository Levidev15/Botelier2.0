"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  Download,
  Search,
  ChevronDown,
  Filter,
  Globe,
  X,
  Loader2,
  RefreshCw,
  Tag,
  Trash2,
  AlertTriangle,
  Phone,
} from "lucide-react";
import { notify } from "@/lib/notifications";
import TranscriptModal from "./components/TranscriptModal";
import EventLogModal from "./components/EventLogModal";
import EditCallLogModal from "./components/EditCallLogModal";
import DispositionSelect from "./components/DispositionSelect";
import CallLogRow from "./components/CallLogRow";
import type { CallLog, FilterOptions } from "./types";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { usePagePermission, PermissionGate, AccessDeniedPage } from "@/components/ui/PermissionGate";
import { usePermissions } from "@/lib/auth/usePermissions";
import { loadTimezone, saveTimezone, TIMEZONE_OPTIONS } from "@/components/analytics/TimezonePicker";

export default function CallLogsPage() {
  const { accountId, loading: contextLoading } = useAccountContext();
  const { hasAccess, loading: permLoading } = usePagePermission("call_logs", "view");
  const { can, isPlatformAdmin } = usePermissions();
  const canExport = isPlatformAdmin || can("call_logs", "export");
  const canViewTranscripts = isPlatformAdmin || can("call_logs", "view_transcripts");
  const canEditLogs = isPlatformAdmin || can("call_logs", "edit");
  const canDeleteLogs = isPlatformAdmin || can("call_logs", "delete");
  const canPlayRecordings = isPlatformAdmin || can("call_logs", "play_recordings");
  const { authFetch } = useAuthToken();
  const [callLogs, setCallLogs] = useState<CallLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterOptions, setFilterOptions] = useState<FilterOptions | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [selectedLog, setSelectedLog] = useState<CallLog | null>(null);
  const [showTranscript, setShowTranscript] = useState(false);
  const [showEventLog, setShowEventLog] = useState(false);
  const [eventLogLog, setEventLogLog] = useState<CallLog | null>(null);
  const [generatingIds, setGeneratingIds] = useState<Set<string>>(new Set());
  const [editLogTarget, setEditLogTarget] = useState<CallLog | null>(null);
  const [deleteLogTarget, setDeleteLogTarget] = useState<CallLog | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [assistantFilter, setAssistantFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  // Deep-link params from analytics drilldown "View all in Call Logs"
  const [hasTransferFilter, setHasTransferFilter] = useState<boolean | null>(null);
  const [dispositionIdFilter, setDispositionIdFilter] = useState("");
  const [acwResolutionFilter, setAcwResolutionFilter] = useState("");
  const [acwCompletedFilter, setAcwCompletedFilter] = useState<boolean | null>(null);
  const [qualityMin, setQualityMin] = useState<number | null>(null);
  const [qualityMax, setQualityMax] = useState<number | null>(null);
  const [hourFilter, setHourFilter] = useState<number | null>(null);

  // Pre-populate filters from URL params (e.g. from analytics drilldown "View all" link)
  useEffect(() => {
    if (typeof window === "undefined") return;
    const sp = new URLSearchParams(window.location.search);
    const s = sp.get("status"); if (s) setStatusFilter(s);
    const a = sp.get("assistant_id"); if (a) setAssistantFilter(a);
    const df = sp.get("date_from"); if (df) setDateFrom(df);
    const dt = sp.get("date_to"); if (dt) setDateTo(dt);
    const ht = sp.get("has_transfer"); if (ht === "true") setHasTransferFilter(true);
    const did = sp.get("disposition_id"); if (did) setDispositionIdFilter(did);
    const ar = sp.get("acw_resolution"); if (ar) setAcwResolutionFilter(ar);
    const acw = sp.get("acw_completed"); if (acw === "true") setAcwCompletedFilter(true);
    const qmin = sp.get("quality_min"); if (qmin) setQualityMin(Number(qmin));
    const qmax = sp.get("quality_max"); if (qmax) setQualityMax(Number(qmax));
    const hr = sp.get("hour"); if (hr !== null) setHourFilter(Number(hr));
    if (s || a || df || dt || ht || did || ar || acw || qmin || qmax || hr !== null) setShowFilters(true);
  }, []);

  const [timezone, setTimezone] = useState<string>("UTC");
  useEffect(() => { setTimezone(loadTimezone()); }, []);
  const [showFilters, setShowFilters] = useState(false);

  const handleTimezoneChange = (newTimezone: string) => {
    setTimezone(newTimezone);
    saveTimezone(newTimezone);
  };

  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);

  const fetchCallLogs = useCallback(async () => {
    if (!accountId) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ account_id: accountId, page: page.toString() });
      if (search) params.append("search", search);
      if (statusFilter) params.append("status", statusFilter);
      if (assistantFilter) params.append("assistant_id", assistantFilter);
      if (dateFrom) params.append("date_from", new Date(dateFrom).toISOString());
      if (dateTo) params.append("date_to", new Date(dateTo).toISOString());
      if (hasTransferFilter !== null) params.append("has_transfer", String(hasTransferFilter));
      if (dispositionIdFilter) params.append("disposition_id", dispositionIdFilter);
      if (acwResolutionFilter) params.append("acw_resolution", acwResolutionFilter);
      if (acwCompletedFilter !== null) params.append("acw_completed", String(acwCompletedFilter));
      if (qualityMin !== null) params.append("quality_min", String(qualityMin));
      if (qualityMax !== null) params.append("quality_max", String(qualityMax));
      if (hourFilter !== null) params.append("hour", String(hourFilter));

      const response = await authFetch(`/api/call-logs?${params}`);
      if (!response.ok) throw new Error("Failed to fetch call logs");

      const data = await response.json();
      setCallLogs(data.call_logs || []);
      setTotal(data.total || 0);
      setTotalPages(data.pages || 1);
    } catch (error) {
      console.error("Failed to fetch call logs:", error);
      notify.error("Failed to load call logs");
    } finally {
      setLoading(false);
    }
  }, [accountId, page, search, statusFilter, assistantFilter, dateFrom, dateTo,
      hasTransferFilter, dispositionIdFilter, acwResolutionFilter, acwCompletedFilter, qualityMin, qualityMax, hourFilter]);

  const fetchFilterOptions = useCallback(async () => {
    if (!accountId) return;
    try {
      const url = assistantFilter
        ? `/api/call-logs/filters/options?account_id=${accountId}&assistant_id=${assistantFilter}`
        : `/api/call-logs/filters/options?account_id=${accountId}`;
      const response = await authFetch(url);
      if (response.ok) {
        const data = await response.json();
        setFilterOptions(data);
        if (assistantFilter) {
          const validDispositionIds = new Set((data.dispositions as Array<{ id: string }>).map(d => d.id));
          setDispositionIdFilter(prev => (prev && !validDispositionIds.has(prev) ? "" : prev));
          const validResolutions = new Set(data.resolution_options as string[]);
          setAcwResolutionFilter(prev => (prev && !validResolutions.has(prev) ? "" : prev));
        }
      }
    } catch (error) {
      console.error("Failed to fetch filter options:", error);
    }
  }, [accountId, assistantFilter]);

  useEffect(() => {
    if (!contextLoading && accountId) {
      fetchCallLogs();
      fetchFilterOptions();
    }
  }, [contextLoading, accountId, fetchCallLogs, fetchFilterOptions]);

  const handleExport = async () => {
    if (!accountId) return;
    try {
      const params = new URLSearchParams({ account_id: accountId });
      if (statusFilter) params.append("status", statusFilter);
      if (assistantFilter) params.append("assistant_id", assistantFilter);
      if (dateFrom) params.append("date_from", new Date(dateFrom).toISOString());
      if (dateTo) params.append("date_to", new Date(dateTo).toISOString());

      const response = await authFetch(`/api/call-logs/export?${params}`);
      if (!response.ok) throw new Error("Export failed");

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `call_logs_${new Date().toISOString().split("T")[0]}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      notify.success("Call logs exported successfully");
    } catch (error) {
      console.error("Export failed:", error);
      notify.error("Failed to export call logs");
    }
  };

  const toggleRowExpanded = (id: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const openTranscript = async (log: CallLog) => {
    if (log.transcript && log.transcript.length > 0) {
      setSelectedLog(log);
      setShowTranscript(true);
    } else {
      try {
        const response = await authFetch(`/api/call-logs/${log.id}?account_id=${accountId}`);
        if (response.ok) {
          const fullLog = await response.json();
          setSelectedLog(fullLog);
          setShowTranscript(true);
        }
      } catch (error) {
        notify.error("Failed to load transcript");
      }
    }
  };

  const generateSummary = async (log: CallLog) => {
    if (!accountId) return;
    
    setGeneratingIds((prev) => new Set(prev).add(log.id));
    
    try {
      const response = await authFetch(`/api/call-logs/${log.id}/generate-summary`, {
        method: "POST",
        body: JSON.stringify({ account_id: accountId }),
      });

      if (response.ok) {
        const result = await response.json();
        setCallLogs((prev) =>
          prev.map((l) =>
            l.id === log.id
              ? {
                  ...l,
                  ai_summary: result.summary,
                  disposition_id: result.disposition?.id || null,
                  disposition_name: result.disposition?.name || null,
                  disposition_color: result.disposition?.color || null,
                  acw_resolution: result.acw_resolution || null,
                  acw_quality_score: result.acw_quality_score ?? null,
                }
              : l
          )
        );
        notify.success("Post Call QA complete");
      } else {
        const error = await response.json();
        notify.error(error.detail || "Failed to generate summary");
      }
    } catch (error) {
      notify.error("Error generating summary");
    } finally {
      setGeneratingIds((prev) => {
        const next = new Set(prev);
        next.delete(log.id);
        return next;
      });
    }
  };

  const deleteCallLog = async (log: CallLog) => {
    if (!accountId) return;
    setDeletingId(log.id);
    try {
      const res = await authFetch(`/api/call-logs/${log.id}?account_id=${accountId}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to delete");
      }
      setCallLogs((prev) => prev.filter((l) => l.id !== log.id));
      setDeleteLogTarget(null);
      notify.success("Call log deleted");
    } catch (err) {
      notify.error(err instanceof Error ? err.message : "Failed to delete call log");
    } finally {
      setDeletingId(null);
    }
  };

  const formatDateTime = (dateStr: string | null) => {
    if (!dateStr) return "-";
    const date = new Date(dateStr);
    try {
      return date.toLocaleString("en-US", {
        timeZone: timezone,
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
      });
    } catch {
      return date.toLocaleString();
    }
  };

  const clearFilters = () => {
    setSearch("");
    setStatusFilter("");
    setAssistantFilter("");
    setHasTransferFilter(null);
    setDispositionIdFilter("");
    setAcwResolutionFilter("");
    setAcwCompletedFilter(null);
    setQualityMin(null);
    setQualityMax(null);
    setHourFilter(null);
    setDateFrom("");
    setDateTo("");
    setPage(1);
  };

  const hasActiveFilters =
    search || statusFilter || assistantFilter || dateFrom || dateTo ||
    hasTransferFilter !== null || dispositionIdFilter || acwResolutionFilter ||
    acwCompletedFilter !== null || qualityMin !== null || qualityMax !== null || hourFilter !== null;

  if (!permLoading && !hasAccess) {
    return <AccessDeniedPage message="You don't have permission to view call logs." />;
  }

  return (
    <div className="h-full flex flex-col">
      <div className="border-b border-gray-800 bg-[#0a0a0a] sticky top-0 z-10">
        <div className="px-8 py-6">
          <div className="flex justify-between items-center">
            <div>
              <h1 className="text-2xl font-bold">Call Logs</h1>
              <p className="text-sm text-gray-400 mt-1">
                View and analyze call history
              </p>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={fetchCallLogs}
                className="p-2 text-gray-400 hover:text-foreground hover:bg-gray-800 rounded-lg transition"
                title="Refresh"
              >
                <RefreshCw className="h-4 w-4" />
              </button>
              {canExport && (
                <button
                  onClick={handleExport}
                  className="inline-flex items-center px-4 py-2 bg-[#141414] border border-gray-800 hover:bg-gray-800 rounded-lg transition text-sm font-medium"
                >
                  <Download className="h-4 w-4 mr-2" />
                  Export CSV
                </button>
              )}
            </div>
          </div>

          <div className="mt-6 space-y-4">
            <div className="flex gap-3">
              <div className="flex-1 relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-500" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && fetchCallLogs()}
                  placeholder="Search by caller, reference ID..."
                  className="w-full pl-10 pr-4 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                />
              </div>
              <button
                onClick={() => setShowFilters(!showFilters)}
                className={`inline-flex items-center px-4 py-2 border rounded-lg transition text-sm font-medium ${
                  showFilters || hasActiveFilters
                    ? "bg-blue-600/10 border-blue-600/30 text-blue-400"
                    : "bg-[#141414] border-gray-800 hover:bg-gray-800 text-gray-300"
                }`}
              >
                <Filter className="h-4 w-4 mr-2" />
                Filters
                {hasActiveFilters && (
                  <span className="ml-2 w-2 h-2 bg-blue-500 rounded-full" />
                )}
              </button>
            </div>

            {showFilters && (
              <div className="p-4 bg-[#141414] border border-gray-800 rounded-lg space-y-3">
                {/* Row 1 */}
                <div className="grid grid-cols-5 gap-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Status</label>
                    <select
                      value={statusFilter}
                      onChange={(e) => setStatusFilter(e.target.value)}
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    >
                      <option value="">All statuses</option>
                      {filterOptions?.statuses.map((status) => (
                        <option key={status} value={status}>
                          {status.charAt(0).toUpperCase() + status.slice(1).replace(/_/g, " ")}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Assistant</label>
                    <select
                      value={assistantFilter}
                      onChange={(e) => setAssistantFilter(e.target.value)}
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    >
                      <option value="">All assistants</option>
                      {filterOptions?.assistants.map((a) => (
                        <option key={a.id} value={a.id}>{a.name}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Disposition</label>
                    <DispositionSelect
                      value={dispositionIdFilter}
                      onChange={setDispositionIdFilter}
                      dispositions={filterOptions?.dispositions || []}
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Resolution Status</label>
                    <select
                      value={acwResolutionFilter}
                      onChange={(e) => setAcwResolutionFilter(e.target.value)}
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    >
                      <option value="">All resolutions</option>
                      {filterOptions?.resolution_options.map((r) => (
                        <option key={r} value={r}>{r}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Transferred</label>
                    <select
                      value={hasTransferFilter === null ? "" : String(hasTransferFilter)}
                      onChange={(e) => {
                        const v = e.target.value;
                        setHasTransferFilter(v === "" ? null : v === "true");
                      }}
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    >
                      <option value="">All calls</option>
                      <option value="true">Transferred</option>
                      <option value="false">Not transferred</option>
                    </select>
                  </div>
                </div>

                {/* Row 2 */}
                <div className="grid grid-cols-5 gap-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">From Date</label>
                    <input
                      type="date"
                      value={dateFrom}
                      onChange={(e) => setDateFrom(e.target.value)}
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">To Date</label>
                    <input
                      type="date"
                      value={dateTo}
                      onChange={(e) => setDateTo(e.target.value)}
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Post Call QA</label>
                    <select
                      value={acwCompletedFilter === null ? "" : "true"}
                      onChange={(e) => setAcwCompletedFilter(e.target.value === "" ? null : true)}
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    >
                      <option value="">All calls</option>
                      <option value="true">Has QA completed</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Quality Score Min</label>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      placeholder="0"
                      value={qualityMin ?? ""}
                      onChange={(e) => setQualityMin(e.target.value === "" ? null : Number(e.target.value))}
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Quality Score Max</label>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      placeholder="100"
                      value={qualityMax ?? ""}
                      onChange={(e) => setQualityMax(e.target.value === "" ? null : Number(e.target.value))}
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    />
                  </div>
                </div>

                {/* Timezone + Clear row */}
                <div className="flex items-end justify-between gap-3">
                  <div className="w-48">
                    <label className="block text-xs text-gray-500 mb-1">Timezone</label>
                    <select
                      value={timezone}
                      onChange={(e) => handleTimezoneChange(e.target.value)}
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                    >
                      {TIMEZONE_OPTIONS.map((tz) => (
                        <option key={tz.value} value={tz.value}>{tz.label}</option>
                      ))}
                    </select>
                  </div>
                  {hasActiveFilters && (
                    <button
                      onClick={clearFilters}
                      className="text-sm text-gray-400 hover:text-foreground flex items-center gap-1 pb-2"
                    >
                      <X className="h-3 w-3" />
                      Clear all filters
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-8">
        {contextLoading || loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 text-gray-400 animate-spin" />
            <span className="ml-2 text-gray-400">Loading call logs...</span>
          </div>
        ) : callLogs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-20 h-20 bg-gray-800 rounded-full flex items-center justify-center mb-4">
              <Phone className="h-10 w-10 text-gray-600" />
            </div>
            <h2 className="text-xl font-semibold text-foreground mb-2">No calls yet</h2>
            <p className="text-gray-400 text-center mb-2 max-w-md">
              {hasActiveFilters
                ? "No calls match your current filters"
                : "Call logs will appear here once you start receiving calls"}
            </p>
            {hasActiveFilters && (
              <button
                onClick={clearFilters}
                className="mt-4 text-blue-400 hover:text-blue-300 text-sm"
              >
                Clear filters
              </button>
            )}
          </div>
        ) : (
          <>
            <div className="mb-4 flex items-center justify-between text-sm text-gray-400">
              <span>
                Showing {callLogs.length} of {total} calls
              </span>
              <div className="flex items-center gap-2">
                <Globe className="h-4 w-4" />
                <span>{TIMEZONE_OPTIONS.find((t) => t.value === timezone)?.label || timezone}</span>
              </div>
            </div>

            <div className="bg-[#141414] border border-gray-800 rounded-lg overflow-hidden">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-800 bg-[#0f0f0f]">
                    <th className="w-10 px-4 py-3"></th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                      Ref
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                      Date / Duration
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                      Caller
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                      Assistant
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                      Tool / Flow
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                      Disposition
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                      Resolution
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                      Score
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800">
                  {callLogs.map((log) => (
                    <CallLogRow
                      key={log.id}
                      log={log}
                      isExpanded={expandedRows.has(log.id)}
                      onToggleExpand={() => toggleRowExpanded(log.id)}
                      onViewTranscript={() => openTranscript(log)}
                      onViewEventLog={() => {
                        setEventLogLog(log);
                        setShowEventLog(true);
                      }}
                      onGenerateSummary={() => generateSummary(log)}
                      isGeneratingSummary={generatingIds.has(log.id)}
                      onEditLog={() => setEditLogTarget(log)}
                      onDeleteLog={() => setDeleteLogTarget(log)}
                      formatDateTime={formatDateTime}
                      canViewTranscripts={canViewTranscripts}
                      canEditLogs={canEditLogs}
                      canDeleteLogs={canDeleteLogs}
                      canPlayRecordings={canPlayRecordings}
                    />
                  ))}
                </tbody>
              </table>
            </div>

            {totalPages > 1 && (
              <div className="mt-6 flex items-center justify-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="px-3 py-1.5 text-sm bg-[#141414] border border-gray-800 rounded-lg hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Previous
                </button>
                <span className="text-sm text-gray-400">
                  Page {page} of {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="px-3 py-1.5 text-sm bg-[#141414] border border-gray-800 rounded-lg hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {showTranscript && selectedLog && (
        <TranscriptModal
          log={selectedLog as any}
          onClose={() => {
            setShowTranscript(false);
            setSelectedLog(null);
          }}
          onLogUpdated={(updates) => {
            setSelectedLog((prev) => prev ? { ...prev, ...updates } as any : prev);
            setCallLogs((prev) =>
              prev.map((l) =>
                l.id === selectedLog.id ? { ...l, ...updates } as any : l
              )
            );
          }}
          onViewEventLog={(log) => {
            setEventLogLog(log as any);
            setShowEventLog(true);
          }}
        />
      )}

      {showEventLog && eventLogLog && (
        <EventLogModal
          log={eventLogLog as any}
          onClose={() => {
            setShowEventLog(false);
            setEventLogLog(null);
          }}
        />
      )}

      {editLogTarget && accountId && (
        <EditCallLogModal
          log={editLogTarget}
          accountId={accountId}
          authFetch={authFetch}
          onClose={() => setEditLogTarget(null)}
          onSaved={(updates) => {
            setCallLogs((prev) =>
              prev.map((l) => (l.id === editLogTarget.id ? { ...l, ...updates } : l))
            );
          }}
        />
      )}

      {deleteLogTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-sm mx-4 bg-[#141414] border border-gray-800 rounded-xl shadow-2xl">
            <div className="px-6 pt-6 pb-4">
              <div className="flex items-center gap-3 mb-3">
                <div className="w-10 h-10 rounded-lg bg-red-500/10 flex items-center justify-center flex-shrink-0">
                  <AlertTriangle className="h-5 w-5 text-red-400" />
                </div>
                <h2 className="text-base font-semibold">Delete Call Log</h2>
              </div>
              <p className="text-sm text-gray-400">
                Are you sure you want to delete this call log? This action cannot be undone and will
                permanently remove the call record, transcript, and all associated data.
              </p>
            </div>
            <div className="flex gap-3 px-6 pb-5">
              <button
                type="button"
                onClick={() => setDeleteLogTarget(null)}
                disabled={deletingId === deleteLogTarget.id}
                className="flex-1 px-4 py-2.5 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => deleteCallLog(deleteLogTarget)}
                disabled={deletingId === deleteLogTarget.id}
                className="flex-1 px-4 py-2.5 bg-red-600 hover:bg-red-700 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {deletingId === deleteLogTarget.id ? (
                  <span className="flex items-center justify-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Deleting...
                  </span>
                ) : (
                  "Delete"
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
