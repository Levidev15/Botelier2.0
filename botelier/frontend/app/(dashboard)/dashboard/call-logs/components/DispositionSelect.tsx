"use client";

import { useState, useEffect, useRef } from "react";
import { ChevronDown } from "lucide-react";

interface DispositionSelectProps {
  value: string;
  onChange: (v: string) => void;
  dispositions: Array<{ id: string; name: string; color: string }>;
}

export default function DispositionSelect({ value, onChange, dispositions }: DispositionSelectProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const selected = dispositions.find((d) => d.id === value) || null;

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600 text-left"
      >
        {selected ? (
          <>
            <span
              className="flex-shrink-0 w-2.5 h-2.5 rounded-full"
              style={{ backgroundColor: selected.color }}
            />
            <span className="truncate">{selected.name}</span>
          </>
        ) : (
          <span className="text-gray-400">All dispositions</span>
        )}
        <ChevronDown className="ml-auto h-3 w-3 text-gray-500 flex-shrink-0" />
      </button>
      {open && (
        <div className="absolute z-50 mt-1 w-full bg-[#1a1a1a] border border-gray-700 rounded-lg shadow-lg overflow-y-auto max-h-52">
          <button
            type="button"
            onClick={() => { onChange(""); setOpen(false); }}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-400 hover:bg-[#222222] text-left"
          >
            All dispositions
          </button>
          {dispositions.map((d) => (
            <button
              key={d.id}
              type="button"
              onClick={() => { onChange(d.id); setOpen(false); }}
              className={`w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-[#222222] text-left ${value === d.id ? "bg-[#222222]" : ""}`}
            >
              <span
                className="flex-shrink-0 w-2.5 h-2.5 rounded-full"
                style={{ backgroundColor: d.color }}
              />
              <span className="truncate">{d.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
