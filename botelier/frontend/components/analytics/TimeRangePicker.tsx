"use client";

interface TimeRangePickerProps {
  value: number;
  onChange: (days: number) => void;
}

const OPTIONS = [
  { label: "7 days", value: 7 },
  { label: "30 days", value: 30 },
  { label: "90 days", value: 90 },
];

export default function TimeRangePicker({ value, onChange }: TimeRangePickerProps) {
  return (
    <div className="inline-flex rounded-lg border border-gray-700 overflow-hidden">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={`px-4 py-1.5 text-sm font-medium transition-colors ${
            value === opt.value
              ? "bg-blue-600 text-white"
              : "bg-[#1a1a1a] text-gray-400 hover:text-gray-200 hover:bg-gray-800"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
