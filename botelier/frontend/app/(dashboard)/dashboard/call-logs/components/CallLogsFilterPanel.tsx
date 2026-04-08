"use client";

import { X } from "lucide-react";
import DispositionSelect from "./DispositionSelect";
import type { FilterOptions } from "../types";
import { TIMEZONE_OPTIONS } from "@/components/analytics/TimezonePicker";

interface CallLogsFilterPanelProps {
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
  onTimezoneChange: (v: string) => void;
  hasActiveFilters: boolean;
  onClearFilters: () => void;
}

export default function CallLogsFilterPanel({
  filterOptions,
  statusFilter, setStatusFilter,
  assistantFilter, setAssistantFilter,
  dispositionIdFilter, setDispositionIdFilter,
  acwResolutionFilter, setAcwResolutionFilter,
  hasTransferFilter, setHasTransferFilter,
  dateFrom, setDateFrom,
  dateTo, setDateTo,
  acwCompletedFilter, setAcwCompletedFilter,
  qualityMin, setQualityMin,
  qualityMax, setQualityMax,
  timezone, onTimezoneChange,
  hasActiveFilters, onClearFilters,
}: CallLogsFilterPanelProps) {
  const selectClass = "w-full px-3 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600";
  const inputClass = "w-full px-3 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600";
  const labelClass = "block text-xs text-gray-500 mb-1";

  return (
    <div className="p-4 bg-[#141414] border border-gray-800 rounded-lg space-y-3">
      <div className="grid grid-cols-5 gap-3">
        <div>
          <label className={labelClass}>Status</label>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className={selectClass}>
            <option value="">All statuses</option>
            {filterOptions?.statuses.map((status) => (
              <option key={status} value={status}>
                {status.charAt(0).toUpperCase() + status.slice(1).replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelClass}>Assistant</label>
          <select value={assistantFilter} onChange={(e) => setAssistantFilter(e.target.value)} className={selectClass}>
            <option value="">All assistants</option>
            {filterOptions?.assistants.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelClass}>Disposition</label>
          <DispositionSelect
            value={dispositionIdFilter}
            onChange={setDispositionIdFilter}
            dispositions={filterOptions?.dispositions || []}
          />
        </div>
        <div>
          <label className={labelClass}>Resolution Status</label>
          <select value={acwResolutionFilter} onChange={(e) => setAcwResolutionFilter(e.target.value)} className={selectClass}>
            <option value="">All resolutions</option>
            {filterOptions?.resolution_options.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelClass}>Transferred</label>
          <select
            value={hasTransferFilter === null ? "" : String(hasTransferFilter)}
            onChange={(e) => {
              const v = e.target.value;
              setHasTransferFilter(v === "" ? null : v === "true");
            }}
            className={selectClass}
          >
            <option value="">All calls</option>
            <option value="true">Transferred</option>
            <option value="false">Not transferred</option>
          </select>
        </div>
      </div>

      <div className="grid grid-cols-5 gap-3">
        <div>
          <label className={labelClass}>From Date</label>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>To Date</label>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>Post Call QA</label>
          <select
            value={acwCompletedFilter === null ? "" : "true"}
            onChange={(e) => setAcwCompletedFilter(e.target.value === "" ? null : true)}
            className={selectClass}
          >
            <option value="">All calls</option>
            <option value="true">Has QA completed</option>
          </select>
        </div>
        <div>
          <label className={labelClass}>Quality Score Min</label>
          <input
            type="number"
            min={0}
            max={100}
            placeholder="0"
            value={qualityMin ?? ""}
            onChange={(e) => setQualityMin(e.target.value === "" ? null : Number(e.target.value))}
            className={inputClass}
          />
        </div>
        <div>
          <label className={labelClass}>Quality Score Max</label>
          <input
            type="number"
            min={0}
            max={100}
            placeholder="100"
            value={qualityMax ?? ""}
            onChange={(e) => setQualityMax(e.target.value === "" ? null : Number(e.target.value))}
            className={inputClass}
          />
        </div>
      </div>

      <div className="flex items-end justify-between gap-3">
        <div className="w-48">
          <label className={labelClass}>Timezone</label>
          <select value={timezone} onChange={(e) => onTimezoneChange(e.target.value)} className={selectClass}>
            {TIMEZONE_OPTIONS.map((tz) => (
              <option key={tz.value} value={tz.value}>{tz.label}</option>
            ))}
          </select>
        </div>
        {hasActiveFilters && (
          <button onClick={onClearFilters} className="text-sm text-gray-400 hover:text-foreground flex items-center gap-1 pb-2">
            <X className="h-3 w-3" />
            Clear all filters
          </button>
        )}
      </div>
    </div>
  );
}
