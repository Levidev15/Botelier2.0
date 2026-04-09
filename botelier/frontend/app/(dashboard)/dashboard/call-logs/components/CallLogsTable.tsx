"use client";

import { Loader2, Globe, Phone } from "lucide-react";
import type { CallLog } from "../types";
import { TIMEZONE_OPTIONS } from "@/components/analytics/TimezonePicker";
import CallLogRow from "./CallLogRow";

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
              {["Ref", "Date", "Duration", "Caller", "Assistant", "Tool / Flow", "Disposition", "Resolution", "Score", "Status"].map((h) => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">{h}</th>
              ))}
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
