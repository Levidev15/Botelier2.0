"use client";

import { X } from "lucide-react";
import type { ParsedRow } from "../types";

interface ReviewModalProps {
  rows: ParsedRow[];
  replaceDuplicates: boolean;
  onToggleReplace: () => void;
  onCancel: () => void;
  onImport: () => void;
}

export default function ReviewModal({
  rows,
  replaceDuplicates,
  onToggleReplace,
  onCancel,
  onImport,
}: ReviewModalProps) {
  const duplicateCount = rows.filter(r => r.isDuplicate).length;
  const newCount = rows.length - duplicateCount;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onCancel}>
      <div
        className="bg-[#1A1A1A] border border-white/10 rounded-xl w-full max-w-2xl flex flex-col max-h-[80vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-5 border-b border-white/10">
          <div>
            <h2 className="text-xl font-semibold text-white">Review Import</h2>
            <p className="text-sm text-white/50 mt-0.5">
              {rows.length} rows parsed &mdash; {newCount} new, {duplicateCount} duplicate{duplicateCount !== 1 ? "s" : ""}
            </p>
          </div>
          <button onClick={onCancel} className="p-1 hover:bg-white/5 rounded">
            <X className="w-5 h-5 text-white/60" />
          </button>
        </div>

        {duplicateCount > 0 && (
          <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between gap-4">
            <div>
              <p className="text-sm text-white font-medium">{duplicateCount} duplicate question{duplicateCount !== 1 ? "s" : ""} found</p>
              <p className="text-xs text-white/50 mt-0.5">
                {replaceDuplicates
                  ? "Existing entries will be overwritten with new data"
                  : "Existing entries will be left unchanged"}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <span className={`text-xs ${!replaceDuplicates ? "text-white" : "text-white/40"}`}>Skip</span>
              <button
                onClick={onToggleReplace}
                className={`relative w-10 h-5 rounded-full transition-colors ${replaceDuplicates ? "bg-blue-600" : "bg-white/20"}`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${replaceDuplicates ? "translate-x-5" : "translate-x-0"}`}
                />
              </button>
              <span className={`text-xs ${replaceDuplicates ? "text-white" : "text-white/40"}`}>Replace</span>
            </div>
          </div>
        )}

        <div className="overflow-y-auto flex-1 px-6 py-3 space-y-2">
          {rows.map((row, idx) => (
            <div
              key={idx}
              className={`rounded-lg px-4 py-3 border text-sm ${
                row.isDuplicate
                  ? "bg-yellow-500/5 border-yellow-500/20"
                  : "bg-white/[0.02] border-white/5"
              }`}
            >
              <div className="flex items-start gap-2">
                {row.isDuplicate && (
                  <span className="shrink-0 mt-0.5 text-xs px-1.5 py-0.5 bg-yellow-500/15 text-yellow-400 rounded font-medium">
                    duplicate
                  </span>
                )}
                <div className="min-w-0">
                  <p className="text-white font-medium truncate">{row.question || <span className="text-white/30 italic">no question</span>}</p>
                  <p className="text-white/50 text-xs mt-0.5 line-clamp-2">{row.answer || <span className="italic">no answer</span>}</p>
                  {row.category && (
                    <span className="inline-block mt-1 text-xs px-1.5 py-0.5 bg-blue-500/10 text-blue-400 rounded">
                      {row.category}
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="flex justify-end gap-3 px-6 py-5 border-t border-white/10">
          <button onClick={onCancel} className="px-4 py-2 text-white/60 hover:text-white transition-colors text-sm">
            Cancel
          </button>
          <button
            onClick={onImport}
            className="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors text-sm"
          >
            Import {rows.length} entries
          </button>
        </div>
      </div>
    </div>
  );
}
