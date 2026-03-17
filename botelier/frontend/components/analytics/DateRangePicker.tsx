"use client";

import { useState, useRef, useEffect } from "react";
import { Calendar, ChevronDown, ChevronLeft } from "lucide-react";

export interface DateRange {
  from: Date;
  to: Date;
}

interface DateRangePickerProps {
  value: DateRange;
  onChange: (range: DateRange) => void;
}

type Preset = {
  label: string;
  key: string;
  resolve: () => DateRange;
};

function startOfDay(d: Date): Date {
  const r = new Date(d);
  r.setHours(0, 0, 0, 0);
  return r;
}
function endOfDay(d: Date): Date {
  const r = new Date(d);
  r.setHours(23, 59, 59, 999);
  return r;
}
function daysAgo(n: number): Date {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return startOfDay(d);
}
function monthsAgo(n: number): Date {
  const d = new Date();
  d.setMonth(d.getMonth() - n);
  return startOfDay(d);
}
function yearsAgo(n: number): Date {
  const d = new Date();
  d.setFullYear(d.getFullYear() - n);
  return startOfDay(d);
}

const PRESETS: Preset[] = [
  {
    label: "Today",
    key: "today",
    resolve: () => ({ from: startOfDay(new Date()), to: endOfDay(new Date()) }),
  },
  {
    label: "Yesterday",
    key: "yesterday",
    resolve: () => {
      const yest = new Date(Date.now() - 86_400_000);
      return { from: startOfDay(yest), to: endOfDay(yest) };
    },
  },
  {
    label: "Last 3 days",
    key: "3d",
    resolve: () => ({ from: daysAgo(3), to: endOfDay(new Date()) }),
  },
  {
    label: "Last 7 days",
    key: "7d",
    resolve: () => ({ from: daysAgo(7), to: endOfDay(new Date()) }),
  },
  {
    label: "Last 14 days",
    key: "14d",
    resolve: () => ({ from: daysAgo(14), to: endOfDay(new Date()) }),
  },
  {
    label: "Last 30 days",
    key: "30d",
    resolve: () => ({ from: daysAgo(30), to: endOfDay(new Date()) }),
  },
  {
    label: "Last 90 days",
    key: "90d",
    resolve: () => ({ from: daysAgo(90), to: endOfDay(new Date()) }),
  },
  {
    label: "Last 6 months",
    key: "6m",
    resolve: () => ({ from: monthsAgo(6), to: endOfDay(new Date()) }),
  },
  {
    label: "Last year",
    key: "1y",
    resolve: () => ({ from: yearsAgo(1), to: endOfDay(new Date()) }),
  },
];

function toInputValue(d: Date): string {
  // Use local date to avoid off-by-one for non-UTC users
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function detectPreset(range: DateRange): string | null {
  for (const p of PRESETS) {
    const r = p.resolve();
    if (
      Math.abs(r.from.getTime() - range.from.getTime()) < 60_000 &&
      Math.abs(r.to.getTime() - range.to.getTime()) < 60_000
    ) {
      return p.key;
    }
  }
  return null;
}

export default function DateRangePicker({ value, onChange }: DateRangePickerProps) {
  const [open, setOpen] = useState(false);
  const [showCustom, setShowCustom] = useState(false);
  const [customFrom, setCustomFrom] = useState(toInputValue(value.from));
  const [customTo, setCustomTo] = useState(toInputValue(value.to));
  const ref = useRef<HTMLDivElement>(null);

  const activePreset = detectPreset(value);
  const isCustom = activePreset === null;

  // When dropdown opens, if the current value is custom, go straight to custom view
  function handleToggle() {
    if (!open) {
      setShowCustom(isCustom);
    }
    setOpen((o) => !o);
  }

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setShowCustom(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  function applyPreset(preset: Preset) {
    const r = preset.resolve();
    onChange(r);
    setCustomFrom(toInputValue(r.from));
    setCustomTo(toInputValue(r.to));
    setOpen(false);
    setShowCustom(false);
  }

  function applyCustom() {
    if (!customFrom || !customTo) return;
    const from = new Date(customFrom + "T00:00:00");
    const to = new Date(customTo + "T23:59:59.999");
    if (from > to) return;
    // Clamp to 365-day max
    const maxFrom = new Date(to.getTime() - 365 * 86_400_000);
    onChange({ from: from < maxFrom ? maxFrom : from, to });
    setOpen(false);
    setShowCustom(false);
  }

  function displayLabel(): string {
    if (activePreset) {
      return PRESETS.find((p) => p.key === activePreset)?.label ?? "Custom";
    }
    const from = value.from.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    const to = value.to.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
    return `${from} – ${to}`;
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={handleToggle}
        className="flex items-center gap-2 px-3 py-1.5 text-sm bg-[#1a1a1a] border border-gray-700 rounded-lg text-gray-300 hover:text-gray-100 hover:border-gray-600 transition-colors"
      >
        <Calendar className="h-4 w-4 text-gray-500" />
        <span>{displayLabel()}</span>
        <ChevronDown
          className={`h-4 w-4 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 bg-[#1a1a1a] border border-gray-700 rounded-xl shadow-xl w-60 overflow-hidden">
          {!showCustom ? (
            /* Preset list */
            <div className="p-2">
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-1.5 px-1">
                Date range
              </p>
              <div className="space-y-0.5">
                {PRESETS.map((preset) => (
                  <button
                    key={preset.key}
                    onClick={() => applyPreset(preset)}
                    className={`w-full text-left px-3 py-1.5 text-sm rounded-lg transition-colors ${
                      activePreset === preset.key
                        ? "bg-blue-600/20 text-blue-400"
                        : "text-gray-300 hover:bg-gray-800 hover:text-gray-100"
                    }`}
                  >
                    {preset.label}
                  </button>
                ))}
                {/* Custom option */}
                <button
                  onClick={() => setShowCustom(true)}
                  className={`w-full text-left px-3 py-1.5 text-sm rounded-lg transition-colors flex items-center justify-between ${
                    isCustom
                      ? "bg-blue-600/20 text-blue-400"
                      : "text-gray-300 hover:bg-gray-800 hover:text-gray-100"
                  }`}
                >
                  <span>Custom range…</span>
                  <ChevronDown className="h-3.5 w-3.5 -rotate-90 opacity-50" />
                </button>
              </div>
            </div>
          ) : (
            /* Custom date picker */
            <div className="p-3">
              <button
                onClick={() => setShowCustom(false)}
                className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 transition-colors mb-3"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
                Back to presets
              </button>
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">
                Custom range <span className="normal-case">(max 365 days)</span>
              </p>
              <div className="space-y-2">
                <div>
                  <p className="text-xs text-gray-500 mb-1">From</p>
                  <input
                    type="date"
                    value={customFrom}
                    onChange={(e) => setCustomFrom(e.target.value)}
                    className="w-full px-2 py-1.5 text-sm bg-[#252525] border border-gray-700 rounded-lg text-gray-200 focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <p className="text-xs text-gray-500 mb-1">To</p>
                  <input
                    type="date"
                    value={customTo}
                    onChange={(e) => setCustomTo(e.target.value)}
                    className="w-full px-2 py-1.5 text-sm bg-[#252525] border border-gray-700 rounded-lg text-gray-200 focus:outline-none focus:border-blue-500"
                  />
                </div>
                <button
                  onClick={applyCustom}
                  disabled={!customFrom || !customTo}
                  className="w-full px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg transition-colors"
                >
                  Apply
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
