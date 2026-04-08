"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import { Bot, ChevronDown, X, Search } from "lucide-react";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface Assistant {
  id: string;
  name: string;
}

interface AssistantFilterProps {
  selected: string[];
  onChange: (ids: string[]) => void;
}

export default function AssistantFilter({ selected, onChange }: AssistantFilterProps) {
  const { accountId } = useAccountContext();
  const { authFetch } = useAuthToken();
  const [open, setOpen] = useState(false);
  const [assistants, setAssistants] = useState<Assistant[]>([]);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!accountId) return;
    authFetch(`/api/assistants?account_id=${accountId}`)
      .then((r) => r.json())
      .then((data) => setAssistants(Array.isArray(data) ? data : (data.assistants ?? [])))
      .catch(() => {});
  }, [accountId, authFetch]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Focus search input when dropdown opens
  useEffect(() => {
    if (open && searchRef.current) {
      searchRef.current.focus();
    }
    if (!open) setSearch("");
  }, [open]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return assistants;
    return assistants.filter((a) => a.name.toLowerCase().includes(q));
  }, [assistants, search]);

  function toggle(id: string) {
    if (selected.includes(id)) {
      onChange(selected.filter((s) => s !== id));
    } else {
      onChange([...selected, id]);
    }
  }

  function clearAll() {
    onChange([]);
  }

  const label =
    selected.length === 0
      ? "All assistants"
      : selected.length === 1
      ? (assistants.find((a) => a.id === selected[0])?.name ?? "1 assistant")
      : `${selected.length} assistants`;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className={`flex items-center gap-2 px-3 py-1.5 text-sm border rounded-lg transition-colors ${
          selected.length > 0
            ? "bg-blue-600/10 border-blue-600/50 text-blue-400 hover:border-blue-500"
            : "bg-[#1a1a1a] border-gray-700 text-gray-300 hover:text-gray-100 hover:border-gray-600"
        }`}
      >
        <Bot className="h-4 w-4" />
        <span>{label}</span>
        {selected.length > 0 ? (
          <span
            role="button"
            onClick={(e) => {
              e.stopPropagation();
              clearAll();
            }}
            className="hover:text-white"
          >
            <X className="h-3.5 w-3.5" />
          </span>
        ) : (
          <ChevronDown
            className={`h-4 w-4 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}
          />
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 bg-[#1a1a1a] border border-gray-700 rounded-xl shadow-xl w-64 flex flex-col">
          {/* Search box */}
          <div className="p-2 border-b border-gray-700">
            <div className="flex items-center gap-2 px-2 py-1.5 bg-[#252525] border border-gray-700 rounded-lg">
              <Search className="h-3.5 w-3.5 text-gray-500 flex-shrink-0" />
              <input
                ref={searchRef}
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search assistants…"
                className="flex-1 bg-transparent text-sm text-gray-200 placeholder-gray-600 focus:outline-none min-w-0"
              />
            </div>
          </div>

          {/* List */}
          <div className="overflow-y-auto max-h-60 py-1">
            {selected.length > 0 && !search && (
              <div className="px-3 py-1 border-b border-gray-800 mb-1">
                <button
                  onClick={clearAll}
                  className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
                >
                  Clear all ({selected.length})
                </button>
              </div>
            )}

            {filtered.length === 0 ? (
              <p className="text-sm text-gray-500 px-3 py-3">
                {search ? "No matches" : "No assistants found"}
              </p>
            ) : (
              filtered.map((a) => {
                const checked = selected.includes(a.id);
                return (
                  <button
                    key={a.id}
                    onClick={() => toggle(a.id)}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 text-sm text-left transition-colors ${
                      checked
                        ? "text-blue-400 bg-blue-600/10"
                        : "text-gray-300 hover:bg-gray-800 hover:text-gray-100"
                    }`}
                  >
                    <span
                      className={`w-4 h-4 rounded border flex-shrink-0 flex items-center justify-center transition-colors ${
                        checked ? "bg-blue-600 border-blue-600" : "border-gray-600"
                      }`}
                    >
                      {checked && (
                        <svg viewBox="0 0 10 8" className="w-2.5 h-2.5 text-white fill-current">
                          <path
                            d="M1 4l2.5 2.5L9 1"
                            stroke="currentColor"
                            strokeWidth="1.5"
                            fill="none"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      )}
                    </span>
                    <span className="truncate">{a.name}</span>
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
