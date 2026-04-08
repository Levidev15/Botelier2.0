"use client";

import { CheckCircle2 } from "lucide-react";
import type { ImportResult } from "../types";

interface ResultModalProps {
  result: ImportResult;
  onDone: () => void;
}

export default function ResultModal({ result, onDone }: ResultModalProps) {
  const totalImported = result.created + result.replaced;
  const isFullFailure = totalImported === 0 && result.errors > 0;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-[#1A1A1A] border border-white/10 rounded-xl w-full max-w-md p-6">
        <div className="flex items-center gap-3 mb-5">
          <div className={`p-2 rounded-full ${isFullFailure ? "bg-red-500/15" : "bg-green-500/15"}`}>
            <CheckCircle2 className={`w-6 h-6 ${isFullFailure ? "text-red-400" : "text-green-400"}`} />
          </div>
          <div>
            <h2 className="text-xl font-semibold text-white">{isFullFailure ? "Import Failed" : "Import Complete"}</h2>
            {isFullFailure && (
              <p className="text-sm text-red-400 mt-0.5">No entries were imported — see errors below</p>
            )}
          </div>
        </div>

        <div className="space-y-2 mb-5">
          {result.created > 0 && (
            <div className="flex items-center justify-between py-2 border-b border-white/5">
              <span className="text-sm text-white/70">New entries added</span>
              <span className="text-sm font-medium text-green-400">{result.created}</span>
            </div>
          )}
          {result.replaced > 0 && (
            <div className="flex items-center justify-between py-2 border-b border-white/5">
              <span className="text-sm text-white/70">Duplicates replaced</span>
              <span className="text-sm font-medium text-blue-400">{result.replaced}</span>
            </div>
          )}
          {result.skipped > 0 && (
            <div className="flex items-center justify-between py-2 border-b border-white/5">
              <span className="text-sm text-white/70">Duplicates skipped</span>
              <span className="text-sm font-medium text-white/50">{result.skipped}</span>
            </div>
          )}
          {result.errors > 0 && (
            <div className="flex items-center justify-between py-2 border-b border-white/5">
              <span className="text-sm text-white/70">Errors</span>
              <span className="text-sm font-medium text-red-400">{result.errors}</span>
            </div>
          )}
        </div>

        {result.error_details.length > 0 && (
          <div className="bg-red-500/5 border border-red-500/20 rounded-lg p-3 mb-5 max-h-40 overflow-y-auto">
            <p className="text-xs font-medium text-red-400 mb-2">Error details</p>
            {result.error_details.slice(0, 10).map((err, i) => (
              <p key={i} className="text-xs text-white/50 leading-relaxed">{err}</p>
            ))}
          </div>
        )}

        <div className="flex justify-end">
          <button
            onClick={onDone}
            className="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors text-sm"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
