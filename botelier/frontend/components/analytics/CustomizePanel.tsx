"use client";

import { X, RotateCcw } from "lucide-react";
import { WidgetDef } from "./useWidgetLayout";

interface CustomizePanelProps {
  open: boolean;
  onClose: () => void;
  widgets: WidgetDef[];
  visibility: Record<string, boolean>;
  onToggle: (id: string) => void;
  onReset: () => void;
}

export default function CustomizePanel({
  open,
  onClose,
  widgets,
  visibility,
  onToggle,
  onReset,
}: CustomizePanelProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative w-80 bg-[#1a1a1a] border-l border-gray-800 h-full overflow-y-auto shadow-xl">
        <div className="sticky top-0 bg-[#1a1a1a] border-b border-gray-800 p-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-100">Customize Widgets</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-200">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-4 space-y-2">
          {widgets.map((w) => (
            <label
              key={w.id}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-gray-800/50 cursor-pointer transition-colors"
            >
              <input
                type="checkbox"
                checked={visibility[w.id] ?? w.defaultVisible}
                onChange={() => onToggle(w.id)}
                className="h-4 w-4 rounded border-gray-600 bg-gray-800 text-blue-500 focus:ring-blue-500/30"
              />
              <span className="text-sm text-gray-300">{w.label}</span>
            </label>
          ))}
        </div>

        <div className="p-4 border-t border-gray-800">
          <button
            onClick={onReset}
            className="flex items-center gap-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
          >
            <RotateCcw className="h-4 w-4" />
            Reset to defaults
          </button>
        </div>
      </div>
    </div>
  );
}
