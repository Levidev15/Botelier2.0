"use client";

import { AlertTriangle, Save, Trash2, X } from "lucide-react";

interface UnsavedChangesModalProps {
  isOpen: boolean;
  onSave: () => void;
  onDiscard: () => void;
  onCancel: () => void;
  isSaving?: boolean;
}

export function UnsavedChangesModal({
  isOpen,
  onSave,
  onDiscard,
  onCancel,
  isSaving = false,
}: UnsavedChangesModalProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div 
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onCancel}
      />
      
      <div className="relative bg-[#1a1a1a] border border-gray-700 rounded-xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-amber-900/30 rounded-lg">
              <AlertTriangle className="h-5 w-5 text-amber-400" />
            </div>
            <h3 className="text-lg font-semibold text-white">Unsaved Changes</h3>
          </div>
          <button
            onClick={onCancel}
            className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        
        <div className="px-5 py-4">
          <p className="text-gray-300">
            You have unsaved changes to your flow. What would you like to do?
          </p>
        </div>
        
        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-gray-700 bg-[#141414]">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-300 hover:text-white hover:bg-gray-700 rounded-lg transition"
          >
            Cancel
          </button>
          <button
            onClick={onDiscard}
            className="flex items-center gap-2 px-4 py-2 text-sm text-red-400 hover:text-white hover:bg-red-600/20 rounded-lg transition"
          >
            <Trash2 className="h-4 w-4" />
            Discard Changes
          </button>
          <button
            onClick={onSave}
            disabled={isSaving}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Save className="h-4 w-4" />
            {isSaving ? "Saving..." : "Save Draft"}
          </button>
        </div>
      </div>
    </div>
  );
}
