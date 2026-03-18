"use client";

import { useState, useRef, useEffect } from "react";
import { Globe, ChevronDown } from "lucide-react";

const STORAGE_KEY = "botelier_analytics_tz";
const LEGACY_KEY = "botelier_call_logs_timezone";

export const TIMEZONE_OPTIONS = [
  { label: "UTC", value: "UTC" },
  { label: "Eastern (ET)", value: "America/New_York" },
  { label: "Central (CT)", value: "America/Chicago" },
  { label: "Mountain (MT)", value: "America/Denver" },
  { label: "Mountain no DST (AZ)", value: "America/Phoenix" },
  { label: "Pacific (PT)", value: "America/Los_Angeles" },
  { label: "Alaska (AK)", value: "America/Anchorage" },
  { label: "Hawaii (HT)", value: "Pacific/Honolulu" },
  { label: "London (GMT/BST)", value: "Europe/London" },
  { label: "Paris (CET/CEST)", value: "Europe/Paris" },
  { label: "Dubai (GST)", value: "Asia/Dubai" },
  { label: "India (IST)", value: "Asia/Kolkata" },
  { label: "Singapore (SGT)", value: "Asia/Singapore" },
  { label: "Tokyo (JST)", value: "Asia/Tokyo" },
  { label: "Sydney (AEST)", value: "Australia/Sydney" },
];

function getBrowserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return "UTC";
  }
}

export function loadTimezone(): string {
  if (typeof window === "undefined") return "UTC";
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) return saved;
  const legacy = localStorage.getItem(LEGACY_KEY);
  if (legacy) {
    localStorage.setItem(STORAGE_KEY, legacy);
    localStorage.removeItem(LEGACY_KEY);
    return legacy;
  }
  return getBrowserTimezone();
}

export function saveTimezone(tz: string) {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, tz);
}

interface TimezonePickerProps {
  value: string;
  onChange: (tz: string) => void;
}

export default function TimezonePicker({ value, onChange }: TimezonePickerProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const currentLabel =
    TIMEZONE_OPTIONS.find((o) => o.value === value)?.label ?? value;

  function handleSelect(tz: string) {
    saveTimezone(tz);
    onChange(tz);
    setOpen(false);
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 px-3 py-1.5 text-sm bg-[#1a1a1a] border border-gray-700 rounded-lg text-gray-300 hover:text-gray-100 hover:border-gray-600 transition-colors"
      >
        <Globe className="h-4 w-4 text-gray-500 flex-shrink-0" />
        <span>{currentLabel}</span>
        <ChevronDown
          className={`h-4 w-4 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 bg-[#1a1a1a] border border-gray-700 rounded-xl shadow-xl w-56 overflow-hidden">
          <div className="p-2">
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-1.5 px-1">
              Timezone
            </p>
            <div className="space-y-0.5 max-h-72 overflow-y-auto">
              {TIMEZONE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => handleSelect(opt.value)}
                  className={`w-full text-left px-3 py-1.5 text-sm rounded-lg transition-colors ${
                    value === opt.value
                      ? "bg-blue-600/20 text-blue-400"
                      : "text-gray-300 hover:bg-gray-800 hover:text-gray-100"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
