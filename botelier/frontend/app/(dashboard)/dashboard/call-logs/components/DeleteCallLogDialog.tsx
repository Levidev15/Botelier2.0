"use client";

import { Loader2, AlertTriangle } from "lucide-react";
import type { CallLog } from "../types";

interface DeleteCallLogDialogProps {
  log: CallLog;
  deletingId: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}

export default function DeleteCallLogDialog({ log, deletingId, onCancel, onConfirm }: DeleteCallLogDialogProps) {
  return (
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
            onClick={onCancel}
            disabled={deletingId === log.id}
            className="flex-1 px-4 py-2.5 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={deletingId === log.id}
            className="flex-1 px-4 py-2.5 bg-red-600 hover:bg-red-700 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {deletingId === log.id ? (
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
  );
}
