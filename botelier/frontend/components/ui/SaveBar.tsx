"use client";

import { Loader2 } from "lucide-react";

interface SaveBarProps {
  onSave: () => void;
  onCancel: () => void;
  saveLabel?: string;
  cancelLabel?: string;
  isSaving?: boolean;
  isDirty?: boolean;
}

export default function SaveBar({
  onSave,
  onCancel,
  saveLabel = "Save Changes",
  cancelLabel = "Cancel",
  isSaving = false,
  isDirty = false,
}: SaveBarProps) {
  if (!isDirty && !isSaving) return null;

  return (
    <div className="fixed bottom-0 left-0 right-0 border-t border-gray-800 bg-[#0a0a0a] z-30">
      <div className="px-8 py-4 flex justify-end space-x-3">
        <button
          onClick={onCancel}
          disabled={isSaving}
          className="px-4 py-2 text-sm font-medium text-gray-300 hover:text-white bg-gray-800 hover:bg-gray-700 rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {cancelLabel}
        </button>
        <button
          onClick={onSave}
          disabled={isSaving}
          className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center space-x-2"
        >
          {isSaving && <Loader2 className="h-4 w-4 animate-spin" />}
          <span>{saveLabel}</span>
        </button>
      </div>
    </div>
  );
}
