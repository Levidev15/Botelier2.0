"use client";

import { useRef } from "react";
import { ArrowLeft, Search, AlertCircle, Grid3x3, List, Download, Upload, Plus } from "lucide-react";
import type { KnowledgeBase } from "../types";

interface KBDetailHeaderProps {
  selectedKB: KnowledgeBase;
  importProgress: { done: number; total: number } | null;
  goBack: () => void;
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  categoryFilter: string;
  setCategoryFilter: (c: string) => void;
  uniqueCategories: string[];
  expiredCount: number;
  showExpired: boolean;
  setShowExpired: (v: boolean) => void;
  view: "grid" | "table";
  setView: (v: "grid" | "table") => void;
  handleExportCSV: () => void;
  canImport: boolean;
  importFileRef: React.RefObject<HTMLInputElement>;
  handleFileChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  canCreate: boolean;
  onAddEntry: () => void;
}

export default function KBDetailHeader({
  selectedKB,
  importProgress,
  goBack,
  searchQuery,
  setSearchQuery,
  categoryFilter,
  setCategoryFilter,
  uniqueCategories,
  expiredCount,
  showExpired,
  setShowExpired,
  view,
  setView,
  handleExportCSV,
  canImport,
  importFileRef,
  handleFileChange,
  canCreate,
  onAddEntry,
}: KBDetailHeaderProps) {
  return (
    <>
      {importProgress && (
        <div className="fixed top-0 left-0 right-0 z-50 bg-blue-600 text-white text-sm font-medium px-6 py-3 flex items-center justify-center gap-3 shadow-lg">
          <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
          Syncing {importProgress.done} of {importProgress.total} entries…
        </div>
      )}

      <div className={`border-b border-gray-800 bg-[#0a0a0a] sticky z-10 ${importProgress ? "top-10" : "top-0"}`}>
        <div className="px-8 py-6">
          <div className="flex items-center gap-4">
            <button onClick={goBack} className="p-2 hover:bg-gray-800 rounded-lg transition-colors">
              <ArrowLeft className="w-5 h-5 text-gray-400" />
            </button>
            <div className="flex-1">
              <h1 className="text-2xl font-bold">{selectedKB.name}</h1>
              <p className="text-sm text-gray-400 mt-0.5">{selectedKB.description || "Knowledge base entries"}</p>
            </div>
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                <input
                  type="text"
                  placeholder="Search entries..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-10 pr-4 py-2 bg-[#141414] border border-gray-800 rounded-lg text-white placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-600 w-64 text-sm"
                />
              </div>
              {uniqueCategories.length > 0 && (
                <select
                  value={categoryFilter}
                  onChange={(e) => setCategoryFilter(e.target.value)}
                  className="px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                >
                  <option value="">All Categories</option>
                  {uniqueCategories.map((cat) => (
                    <option key={cat} value={cat}>{cat}</option>
                  ))}
                </select>
              )}
              {expiredCount > 0 && (
                <button
                  onClick={() => setShowExpired(!showExpired)}
                  className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                    showExpired
                      ? "bg-red-500/20 border border-red-500/50 text-red-400"
                      : "bg-[#141414] border border-gray-800 text-gray-400 hover:text-white"
                  }`}
                >
                  <AlertCircle className="w-4 h-4" />
                  {showExpired ? "Hide" : "Show"} Expired ({expiredCount})
                </button>
              )}
              <div className="flex items-center bg-[#141414] border border-gray-800 rounded-lg">
                <button onClick={() => setView("grid")} className={`p-2 ${view === "grid" ? "text-blue-500" : "text-gray-500"}`}>
                  <Grid3x3 className="w-4 h-4" />
                </button>
                <button onClick={() => setView("table")} className={`p-2 ${view === "table" ? "text-blue-500" : "text-gray-500"}`}>
                  <List className="w-4 h-4" />
                </button>
              </div>
              <button onClick={handleExportCSV} className="flex items-center gap-2 px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg text-gray-400 hover:text-white transition-colors text-sm">
                <Download className="w-4 h-4" />
                Export
              </button>
              {canImport && (
                <label className="flex items-center gap-2 px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg text-gray-400 hover:text-white transition-colors cursor-pointer text-sm">
                  <Upload className="w-4 h-4" />
                  Import
                  <input ref={importFileRef} type="file" accept=".csv" onChange={handleFileChange} className="hidden" />
                </label>
              )}
              {canCreate && (
                <button onClick={onAddEntry} className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium">
                  <Plus className="h-4 w-4 mr-2" />
                  Add Entry
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
