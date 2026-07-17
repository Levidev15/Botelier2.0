"use client";

import { useState, useEffect, useRef } from "react";
import { Loader2, Globe, Phone, Settings } from "lucide-react";
import type { CallLog } from "../types";
import { TIMEZONE_OPTIONS } from "@/components/analytics/TimezonePicker";
import CallLogRow from "./CallLogRow";

// Task #397 — key bumped to v2 when the Topic column was added so saved
// preferences from before Topic existed get it enabled once (legacy prefs
// are migrated below; hiding Topic afterwards persists normally).
const LS_KEY = "botelier_call_logs_visible_cols_v2";
const LEGACY_LS_KEY = "botelier_call_logs_visible_cols";

interface ColumnDef {
  key: string;
  label: string;
}

const TOGGLEABLE_COLS: ColumnDef[] = [
  { key: "duration",    label: "Duration" },
  { key: "caller",      label: "Caller" },
  { key: "assistant",   label: "Assistant" },
  { key: "tool",        label: "Tool / Flow" },
  { key: "disposition", label: "Disposition" },
  { key: "topic",       label: "Topic" },
  { key: "resolution",  label: "Resolution" },
  { key: "score",       label: "Score" },
  { key: "transfer",    label: "Transfer" },
];

const ALL_COL_KEYS = new Set(TOGGLEABLE_COLS.map((c) => c.key));
const ALWAYS_VISIBLE_COUNT = 5;

interface CallLogsTableProps {
  loading: boolean;
  contextLoading: boolean;
  callLogs: CallLog[];
  total: number;
  timezone: string;
  hasActiveFilters: boolean;
  onClearFilters: () => void;
  expandedRows: Set<string>;
  onToggleExpand: (id: string) => void;
  onViewTranscript: (log: CallLog) => void;
  onViewEventLog: (log: CallLog) => void;
  onGenerateSummary: (log: CallLog) => void;
  generatingIds: Set<string>;
  onEditLog: (log: CallLog) => void;
  onDeleteLog: (log: CallLog) => void;
  formatDateTime: (date: string | null) => string;
  canViewTranscripts: boolean;
  canEditLogs: boolean;
  canDeleteLogs: boolean;
  canPlayRecordings: boolean;
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export default function CallLogsTable({
  loading,
  contextLoading,
  callLogs,
  total,
  timezone,
  hasActiveFilters,
  onClearFilters,
  expandedRows,
  onToggleExpand,
  onViewTranscript,
  onViewEventLog,
  onGenerateSummary,
  generatingIds,
  onEditLog,
  onDeleteLog,
  formatDateTime,
  canViewTranscripts,
  canEditLogs,
  canDeleteLogs,
  canPlayRecordings,
  page,
  totalPages,
  onPageChange,
}: CallLogsTableProps) {
  const [visibleColumns, setVisibleColumns] = useState<Set<string>>(ALL_COL_KEYS);
  const [showColPicker, setShowColPicker] = useState(false);
  const cogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      let raw = localStorage.getItem(LS_KEY);
      if (!raw) {
        // Migrate pre-Topic preferences: keep the user's choices, add the
        // new "topic" column once, and persist under the v2 key.
        const legacy = localStorage.getItem(LEGACY_LS_KEY);
        if (legacy) {
          const legacySaved: string[] = JSON.parse(legacy);
          const migrated = [...new Set([...legacySaved, "topic"])];
          localStorage.setItem(LS_KEY, JSON.stringify(migrated));
          raw = JSON.stringify(migrated);
        }
      }
      if (raw) {
        const saved: string[] = JSON.parse(raw);
        const valid = saved.filter((k) => ALL_COL_KEYS.has(k));
        if (valid.length > 0) setVisibleColumns(new Set(valid));
      }
    } catch {}
  }, []);

  const toggleColumn = (key: string) => {
    setVisibleColumns((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      try { localStorage.setItem(LS_KEY, JSON.stringify([...next])); } catch {}
      return next;
    });
  };

  useEffect(() => {
    function handleOutside(e: MouseEvent) {
      if (cogRef.current && !cogRef.current.contains(e.target as Node)) {
        setShowColPicker(false);
      }
    }
    if (showColPicker) {
      document.addEventListener("mousedown", handleOutside);
      return () => document.removeEventListener("mousedown", handleOutside);
    }
  }, [showColPicker]);

  const totalCols = ALWAYS_VISIBLE_COUNT + visibleColumns.size;

  if (contextLoading || loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 text-gray-400 animate-spin" />
        <span className="ml-2 text-gray-400">Loading call logs...</span>
      </div>
    );
  }

  if (callLogs.length === 0) {
    return (
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
            onClick={onClearFilters}
            className="mt-4 text-blue-400 hover:text-blue-300 text-sm"
          >
            Clear filters
          </button>
        )}
      </div>
    );
  }

  return (
    <>
      <div className="mb-4 flex items-center justify-between text-sm text-gray-400">
        <span>Showing {callLogs.length} of {total} calls</span>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Globe className="h-4 w-4" />
            <span>{TIMEZONE_OPTIONS.find((t) => t.value === timezone)?.label || timezone}</span>
          </div>
          <div ref={cogRef} className="relative">
            <button
              onClick={() => setShowColPicker((v) => !v)}
              className={`p-1.5 rounded-lg transition ${
                showColPicker
                  ? "bg-gray-700 text-gray-200"
                  : "hover:bg-gray-800 text-gray-500 hover:text-gray-300"
              }`}
              title="Column visibility"
            >
              <Settings className="h-4 w-4" />
            </button>
            {showColPicker && (
              <div className="absolute right-0 mt-1 w-48 bg-[#1c1c1c] border border-gray-700 rounded-lg shadow-xl z-50 overflow-hidden py-1">
                <div className="px-3 py-1.5 text-xs font-semibold text-gray-500 uppercase tracking-wider border-b border-gray-800 mb-1">
                  Columns
                </div>
                {TOGGLEABLE_COLS.map((col) => (
                  <label
                    key={col.key}
                    className="flex items-center gap-2.5 px-3 py-2 cursor-pointer hover:bg-[#252525] transition-colors"
                  >
                    <input
                      type="checkbox"
                      checked={visibleColumns.has(col.key)}
                      onChange={() => toggleColumn(col.key)}
                      className="rounded border-gray-600 bg-gray-800 text-blue-500 focus:ring-blue-500 focus:ring-offset-0"
                    />
                    <span className="text-sm text-gray-300">{col.label}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="bg-[#141414] border border-gray-800 rounded-lg overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-800 bg-[#0f0f0f]">
              <th className="w-10 px-4 py-3"></th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Ref</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Date</th>
              {TOGGLEABLE_COLS.filter((c) => visibleColumns.has(c.key)).map((col) => (
                <th key={col.key} className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  {col.label}
                </th>
              ))}
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Status</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {callLogs.map((log) => (
              <CallLogRow
                key={log.id}
                log={log}
                isExpanded={expandedRows.has(log.id)}
                onToggleExpand={() => onToggleExpand(log.id)}
                onViewTranscript={() => onViewTranscript(log)}
                onViewEventLog={() => onViewEventLog(log)}
                onGenerateSummary={() => onGenerateSummary(log)}
                isGeneratingSummary={generatingIds.has(log.id)}
                onEditLog={() => onEditLog(log)}
                onDeleteLog={() => onDeleteLog(log)}
                formatDateTime={formatDateTime}
                canViewTranscripts={canViewTranscripts}
                canEditLogs={canEditLogs}
                canDeleteLogs={canDeleteLogs}
                canPlayRecordings={canPlayRecordings}
                visibleColumns={visibleColumns}
                totalCols={totalCols}
              />
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="mt-6 flex items-center justify-center gap-2">
          <button
            onClick={() => onPageChange(Math.max(1, page - 1))}
            disabled={page === 1}
            className="px-3 py-1.5 text-sm bg-[#141414] border border-gray-800 rounded-lg hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          <span className="text-sm text-gray-400">Page {page} of {totalPages}</span>
          <button
            onClick={() => onPageChange(Math.min(totalPages, page + 1))}
            disabled={page === totalPages}
            className="px-3 py-1.5 text-sm bg-[#141414] border border-gray-800 rounded-lg hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      )}
    </>
  );
}
