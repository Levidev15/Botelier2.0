"use client";

import { ChevronDown, ChevronRight, Plus, X } from "lucide-react";

interface Secret {
  key: string;
  name: string;
}

interface APIRequestHeadersSectionProps {
  showHeaders: boolean;
  onToggle: () => void;
  headerEntries: [string, string][];
  addHeader: () => void;
  updateHeader: (oldKey: string, newKey: string, value: string, index: number) => void;
  removeHeader: (index: number) => void;
  availableSecrets: Secret[];
  secretPickerIndex: number | null;
  setSecretPickerIndex: (index: number | null) => void;
  smallInputCls: string;
}

export default function APIRequestHeadersSection({
  showHeaders,
  onToggle,
  headerEntries,
  addHeader,
  updateHeader,
  removeHeader,
  availableSecrets,
  secretPickerIndex,
  setSecretPickerIndex,
  smallInputCls,
}: APIRequestHeadersSectionProps) {
  return (
    <div>
      <button
        onClick={onToggle}
        className="flex items-center gap-2 text-sm font-medium text-gray-300"
      >
        {showHeaders ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        Headers
        {headerEntries.length > 0 && <span className="text-xs text-gray-500">({headerEntries.length})</span>}
      </button>

      {showHeaders && (
        <div className="mt-2 space-y-2">
          <p className="text-xs text-gray-500">Add custom HTTP headers for the request</p>
          {headerEntries.map(([key, value], i) => (
            <div key={i} className="flex gap-2 items-center">
              <input
                type="text"
                value={key}
                onChange={(e) => updateHeader(key, e.target.value, value, i)}
                className={smallInputCls}
                placeholder="Header-Name"
              />
              <div className="relative flex-1 min-w-0">
                <input
                  type="text"
                  value={value}
                  onChange={(e) => updateHeader(key, key, e.target.value, i)}
                  className={`${smallInputCls} w-full pr-7`}
                  placeholder="value or {{secrets.key}}"
                />
                {availableSecrets.length > 0 && (
                  <button
                    type="button"
                    title="Insert secret"
                    onClick={() => setSecretPickerIndex(secretPickerIndex === i ? null : i)}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-blue-400 transition"
                  >
                    <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                    </svg>
                  </button>
                )}
                {secretPickerIndex === i && availableSecrets.length > 0 && (
                  <div className="absolute right-0 top-full mt-1 z-20 bg-[#1a1a1a] border border-gray-700 rounded-lg shadow-xl min-w-[180px] overflow-hidden">
                    <div className="px-2 py-1.5 text-xs text-gray-500 border-b border-gray-800">Insert secret</div>
                    {availableSecrets.map((s) => (
                      <button
                        key={s.key}
                        type="button"
                        onClick={() => {
                          updateHeader(key, key, `{{secrets.${s.key}}}`, i);
                          setSecretPickerIndex(null);
                        }}
                        className="w-full text-left px-3 py-2 text-xs hover:bg-gray-800 transition"
                      >
                        <div className="font-medium text-white">{s.name}</div>
                        <div className="text-blue-400 font-mono">{`{{secrets.${s.key}}}`}</div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button
                onClick={() => removeHeader(i)}
                className="text-red-400 hover:text-red-300 p-1 flex-shrink-0"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
          <button
            onClick={addHeader}
            className="text-xs text-orange-400 hover:text-orange-300 flex items-center gap-1"
          >
            <Plus className="h-3 w-3" /> Add Header
          </button>
        </div>
      )}
    </div>
  );
}
