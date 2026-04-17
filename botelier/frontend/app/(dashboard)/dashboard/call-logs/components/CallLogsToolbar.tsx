"use client";

import { Download, Search, Filter, RefreshCw, X } from "lucide-react";
import CallLogsFilterPanel from "./CallLogsFilterPanel";
import type { FilterOptions } from "../types";

interface CallLogsToolbarProps {
  canExport: boolean;
  onRefresh: () => void;
  onExport: () => void;
  search: string;
  setSearch: (s: string) => void;
  onSearch: () => void;
  showFilters: boolean;
  setShowFilters: (v: boolean) => void;
  hasActiveFilters: boolean;
  filterOptions: FilterOptions | null;
  statusFilter: string;
  setStatusFilter: (v: string) => void;
  assistantFilter: string;
  setAssistantFilter: (v: string) => void;
  dispositionIdFilter: string;
  setDispositionIdFilter: (v: string) => void;
  acwResolutionFilter: string;
  setAcwResolutionFilter: (v: string) => void;
  hasTransferFilter: boolean | null;
  setHasTransferFilter: (v: boolean | null) => void;
  dateFrom: string;
  setDateFrom: (v: string) => void;
  dateTo: string;
  setDateTo: (v: string) => void;
  acwCompletedFilter: boolean | null;
  setAcwCompletedFilter: (v: boolean | null) => void;
  qualityMin: number | null;
  setQualityMin: (v: number | null) => void;
  qualityMax: number | null;
  setQualityMax: (v: number | null) => void;
  timezone: string;
  onTimezoneChange: (tz: string) => void;
  onClearFilters: () => void;
  bucketFilter?: string;
  onClearBucket?: () => void;
}

// Task #102 — human labels for the partition-bucket chip shown when the
// user arrives via the analytics drilldown's "View all in Call Logs" link.
// Keeps the otherwise-invisible `?bucket=` filter discoverable. Unknown
// future tokens (added in analytics first) get a sentence-cased fallback
// so the chip still renders, future-proofing the UI without a code change.
const BUCKET_LABELS: Record<string, string> = {
  ai_handled: "AI handled",
  ended_early: "Ended early",
  missed: "Missed",
  failed: "Failed",
  unresolved: "Unresolved",
  silent_caller: "Silent caller",
};

function bucketLabel(token: string): string {
  if (BUCKET_LABELS[token]) return BUCKET_LABELS[token];
  const cleaned = token.replace(/_/g, " ").trim();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

export default function CallLogsToolbar({
  canExport,
  onRefresh,
  onExport,
  search,
  setSearch,
  onSearch,
  showFilters,
  setShowFilters,
  hasActiveFilters,
  filterOptions,
  statusFilter,
  setStatusFilter,
  assistantFilter,
  setAssistantFilter,
  dispositionIdFilter,
  setDispositionIdFilter,
  acwResolutionFilter,
  setAcwResolutionFilter,
  hasTransferFilter,
  setHasTransferFilter,
  dateFrom,
  setDateFrom,
  dateTo,
  setDateTo,
  acwCompletedFilter,
  setAcwCompletedFilter,
  qualityMin,
  setQualityMin,
  qualityMax,
  setQualityMax,
  timezone,
  onTimezoneChange,
  onClearFilters,
  bucketFilter,
  onClearBucket,
}: CallLogsToolbarProps) {
  return (
    <div className="border-b border-gray-800 bg-[#0a0a0a] sticky top-0 z-10">
      <div className="px-8 py-6">
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-2xl font-bold">Call Logs</h1>
            <p className="text-sm text-gray-400 mt-1">View and analyze call history</p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={onRefresh}
              className="p-2 text-gray-400 hover:text-foreground hover:bg-gray-800 rounded-lg transition"
              title="Refresh"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
            {canExport && (
              <button
                onClick={onExport}
                className="inline-flex items-center px-4 py-2 bg-[#141414] border border-gray-800 hover:bg-gray-800 rounded-lg transition text-sm font-medium"
              >
                <Download className="h-4 w-4 mr-2" />
                Export CSV
              </button>
            )}
          </div>
        </div>

        <div className="mt-6 space-y-4">
          {bucketFilter && (
            <div className="flex items-center gap-2">
              <span
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-blue-500/10 border border-blue-500/30 text-blue-300"
                title="Bucket filter — matches the analytics drilldown exactly"
              >
                Bucket: {bucketLabel(bucketFilter)}
                {onClearBucket && (
                  <button
                    onClick={onClearBucket}
                    className="ml-1 -mr-0.5 p-0.5 rounded-full hover:bg-blue-500/20 transition"
                    title="Clear bucket filter"
                    aria-label="Clear bucket filter"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </span>
            </div>
          )}
          <div className="flex gap-3">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-500" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && onSearch()}
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
            <CallLogsFilterPanel
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
              onTimezoneChange={onTimezoneChange}
              hasActiveFilters={hasActiveFilters}
              onClearFilters={onClearFilters}
            />
          )}
        </div>
      </div>
    </div>
  );
}
