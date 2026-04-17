"use client";

import { useState, useEffect, useCallback } from "react";
import { notify } from "@/lib/notifications";
import CallLogsToolbar from "./components/CallLogsToolbar";
import CallLogsTable from "./components/CallLogsTable";
import CallLogsModals from "./components/CallLogsModals";
import type { CallLog, FilterOptions } from "./types";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { usePagePermission, AccessDeniedPage } from "@/components/ui/PermissionGate";
import { usePermissions } from "@/lib/auth/usePermissions";
import { loadTimezone, saveTimezone } from "@/components/analytics/TimezonePicker";

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

  const [hasTransferFilter, setHasTransferFilter] = useState<boolean | null>(null);
  const [dispositionIdFilter, setDispositionIdFilter] = useState("");
  const [acwResolutionFilter, setAcwResolutionFilter] = useState("");
  const [acwCompletedFilter, setAcwCompletedFilter] = useState<boolean | null>(null);
  const [qualityMin, setQualityMin] = useState<number | null>(null);
  const [qualityMax, setQualityMax] = useState<number | null>(null);
  const [hourFilter, setHourFilter] = useState<number | null>(null);
  // Task #102 — partition bucket forwarded from the analytics drilldown's
  // "View all in Call Logs" link. Maps 1:1 to the analytics partition
  // predicate via `?bucket=` on /api/call-logs, guaranteeing the count
  // matches the drilldown exactly.
  const [bucketFilter, setBucketFilter] = useState<string>("");

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
    const bk = sp.get("bucket"); if (bk) setBucketFilter(bk);
    if (s || a || df || dt || ht || did || ar || acw || qmin || qmax || hr !== null || bk) setShowFilters(true);
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
      if (bucketFilter) params.append("bucket", bucketFilter);

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
      hasTransferFilter, dispositionIdFilter, acwResolutionFilter, acwCompletedFilter, qualityMin, qualityMax, hourFilter, bucketFilter]);

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
    setBucketFilter("");
    setDateFrom("");
    setDateTo("");
    setPage(1);
  };

  const hasActiveFilters =
    search || statusFilter || assistantFilter || dateFrom || dateTo ||
    hasTransferFilter !== null || dispositionIdFilter || acwResolutionFilter ||
    acwCompletedFilter !== null || qualityMin !== null || qualityMax !== null || hourFilter !== null ||
    bucketFilter;

  if (!permLoading && !hasAccess) {
    return <AccessDeniedPage message="You don't have permission to view call logs." />;
  }

  return (
    <div className="h-full flex flex-col">
      <CallLogsToolbar
        canExport={canExport}
        onRefresh={fetchCallLogs}
        onExport={handleExport}
        search={search}
        setSearch={setSearch}
        onSearch={fetchCallLogs}
        showFilters={showFilters}
        setShowFilters={setShowFilters}
        hasActiveFilters={!!hasActiveFilters}
        filterOptions={filterOptions}
        statusFilter={statusFilter}
        setStatusFilter={setStatusFilter}
        assistantFilter={assistantFilter}
        setAssistantFilter={setAssistantFilter}
        dispositionIdFilter={dispositionIdFilter}
        setDispositionIdFilter={setDispositionIdFilter}
        acwResolutionFilter={acwResolutionFilter}
        setAcwResolutionFilter={setAcwResolutionFilter}
        hasTransferFilter={hasTransferFilter}
        setHasTransferFilter={setHasTransferFilter}
        dateFrom={dateFrom}
        setDateFrom={setDateFrom}
        dateTo={dateTo}
        setDateTo={setDateTo}
        acwCompletedFilter={acwCompletedFilter}
        setAcwCompletedFilter={setAcwCompletedFilter}
        qualityMin={qualityMin}
        setQualityMin={setQualityMin}
        qualityMax={qualityMax}
        setQualityMax={setQualityMax}
        timezone={timezone}
        onTimezoneChange={handleTimezoneChange}
        onClearFilters={clearFilters}
        bucketFilter={bucketFilter}
        onClearBucket={() => { setBucketFilter(""); setPage(1); }}
      />

      <div className="flex-1 overflow-auto p-8">
        <CallLogsTable
          loading={loading}
          contextLoading={contextLoading}
          callLogs={callLogs}
          total={total}
          timezone={timezone}
          hasActiveFilters={!!hasActiveFilters}
          onClearFilters={clearFilters}
          expandedRows={expandedRows}
          onToggleExpand={toggleRowExpanded}
          onViewTranscript={openTranscript}
          onViewEventLog={(log) => { setEventLogLog(log); setShowEventLog(true); }}
          onGenerateSummary={generateSummary}
          generatingIds={generatingIds}
          onEditLog={setEditLogTarget}
          onDeleteLog={setDeleteLogTarget}
          formatDateTime={formatDateTime}
          canViewTranscripts={canViewTranscripts}
          canEditLogs={canEditLogs}
          canDeleteLogs={canDeleteLogs}
          canPlayRecordings={canPlayRecordings}
          page={page}
          totalPages={totalPages}
          onPageChange={setPage}
        />
      </div>

      <CallLogsModals
        showTranscript={showTranscript}
        selectedLog={selectedLog}
        showEventLog={showEventLog}
        eventLogLog={eventLogLog}
        editLogTarget={editLogTarget}
        deleteLogTarget={deleteLogTarget}
        deletingId={deletingId}
        accountId={accountId}
        authFetch={authFetch}
        onTranscriptClose={() => { setShowTranscript(false); setSelectedLog(null); }}
        onLogUpdated={(updates) => {
          setSelectedLog((prev) => prev ? { ...prev, ...updates } as any : prev);
          setCallLogs((prev) => prev.map((l) => l.id === selectedLog?.id ? { ...l, ...updates } as any : l));
        }}
        onViewEventLog={(log) => { setEventLogLog(log as any); setShowEventLog(true); }}
        onEventLogClose={() => { setShowEventLog(false); setEventLogLog(null); }}
        onEditClose={() => setEditLogTarget(null)}
        onEditSaved={(updates) => setCallLogs((prev) => prev.map((l) => l.id === editLogTarget?.id ? { ...l, ...updates } : l))}
        onDeleteCancel={() => setDeleteLogTarget(null)}
        onDeleteConfirm={() => deleteLogTarget && deleteCallLog(deleteLogTarget)}
      />
    </div>
  );
}
