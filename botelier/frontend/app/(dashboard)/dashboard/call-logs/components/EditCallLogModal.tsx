"use client";

import { useState, useEffect, useRef } from "react";
import { X, ChevronDown, Loader2, Check } from "lucide-react";
import { notify } from "@/lib/notifications";

interface Disposition {
  id: string;
  name: string;
  color: string;
}

interface CallLog {
  id: string;
  hotel_id: string;
  assistant_id: string | null;
  disposition_id: string | null;
  disposition_name: string | null;
  disposition_color: string | null;
  acw_resolution: string | null;
}

interface EditCallLogModalProps {
  log: CallLog;
  hotelId: string;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
  onClose: () => void;
  onSaved: (updates: Partial<CallLog>) => void;
}

function DropdownSelect({
  label,
  value,
  onChange,
  options,
  placeholder,
  loading,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string; color?: string }>;
  placeholder: string;
  loading?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const selected = options.find((o) => o.value === value) || null;

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div>
      <label className="block text-sm font-medium text-gray-300 mb-2">{label}</label>
      <div ref={ref} className="relative">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          disabled={loading}
          className="w-full flex items-center gap-2 px-3 py-2.5 bg-[#0a0a0a] border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600 text-left hover:border-gray-600 transition-colors disabled:opacity-50"
        >
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin text-gray-500" />
          ) : selected ? (
            <>
              {selected.color && (
                <span
                  className="flex-shrink-0 w-2.5 h-2.5 rounded-full"
                  style={{ backgroundColor: selected.color }}
                />
              )}
              <span className="truncate text-foreground">{selected.label}</span>
            </>
          ) : (
            <span className="text-gray-500">{placeholder}</span>
          )}
          <ChevronDown className="ml-auto h-3 w-3 text-gray-500 flex-shrink-0" />
        </button>
        {open && !loading && (
          <div className="absolute z-50 mt-1 w-full bg-[#1c1c1c] border border-gray-700 rounded-lg shadow-xl overflow-y-auto max-h-52">
            <button
              type="button"
              onClick={() => { onChange(""); setOpen(false); }}
              className="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-gray-400 hover:bg-[#252525] text-left"
            >
              <span className="italic">None / Clear</span>
            </button>
            {options.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => { onChange(opt.value); setOpen(false); }}
                className={`w-full flex items-center gap-2 px-3 py-2.5 text-sm hover:bg-[#252525] text-left ${value === opt.value ? "bg-[#252525]" : ""}`}
              >
                {opt.color && (
                  <span
                    className="flex-shrink-0 w-2.5 h-2.5 rounded-full"
                    style={{ backgroundColor: opt.color }}
                  />
                )}
                <span className="truncate">{opt.label}</span>
                {value === opt.value && (
                  <Check className="ml-auto h-3 w-3 text-blue-400 flex-shrink-0" />
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function EditCallLogModal({
  log,
  hotelId,
  authFetch,
  onClose,
  onSaved,
}: EditCallLogModalProps) {
  const [dispositions, setDispositions] = useState<Disposition[]>([]);
  const [resolutionOptions, setResolutionOptions] = useState<string[]>([]);
  const [loadingOptions, setLoadingOptions] = useState(true);

  const [selectedDispositionId, setSelectedDispositionId] = useState(log.disposition_id || "");
  const [selectedResolution, setSelectedResolution] = useState(log.acw_resolution || "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    async function fetchOptions() {
      try {
        const params = new URLSearchParams({ hotel_id: hotelId });
        if (log.assistant_id) params.set("assistant_id", log.assistant_id);
        const res = await authFetch(`/api/call-logs/filters/options?${params}`);
        if (res.ok) {
          const data = await res.json();
          setDispositions(data.dispositions || []);
          const configured: string[] = data.configured_resolution_options || [];
          const historical: string[] = data.resolution_options || [];
          const merged = Array.from(new Set([...configured, ...historical])).sort();
          setResolutionOptions(merged);
        }
      } catch {
        notify.error("Failed to load options");
      } finally {
        setLoadingOptions(false);
      }
    }
    fetchOptions();
  }, [log.assistant_id, hotelId]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const body: Record<string, string | null> = {
        disposition_id: selectedDispositionId || "",
        acw_resolution: selectedResolution || "",
      };
      const res = await authFetch(`/api/call-logs/${log.id}?hotel_id=${hotelId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to save");
      }
      const updated = await res.json();
      onSaved({
        disposition_id: updated.disposition_id || null,
        disposition_name: updated.disposition_name || null,
        disposition_color: updated.disposition_color || null,
        acw_resolution: updated.acw_resolution || null,
      });
      notify.success("Call log updated");
      onClose();
    } catch (err) {
      notify.error(err instanceof Error ? err.message : "Failed to save changes");
    } finally {
      setSaving(false);
    }
  };

  const dispositionOptions = dispositions.map((d) => ({
    value: d.id,
    label: d.name,
    color: d.color,
  }));

  const resolutionSelectOptions = resolutionOptions.map((r) => ({
    value: r,
    label: r.charAt(0).toUpperCase() + r.slice(1),
  }));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-md mx-4 bg-[#141414] border border-gray-800 rounded-xl shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
          <div>
            <h2 className="text-base font-semibold text-foreground">Edit Call Log</h2>
            {log.hotel_id && (
              <p className="text-xs text-gray-500 mt-0.5">
                Correct AI-determined fields for this call
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-foreground hover:bg-gray-800 rounded-lg transition"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-6 py-5 space-y-5">
          <DropdownSelect
            label="Disposition"
            value={selectedDispositionId}
            onChange={setSelectedDispositionId}
            options={dispositionOptions}
            placeholder={loadingOptions ? "Loading..." : dispositionOptions.length === 0 ? "No dispositions configured" : "None / Clear"}
            loading={loadingOptions}
          />

          <DropdownSelect
            label="Resolution Status"
            value={selectedResolution}
            onChange={setSelectedResolution}
            options={resolutionSelectOptions}
            placeholder={loadingOptions ? "Loading..." : resolutionSelectOptions.length === 0 ? "No resolution options configured" : "None / Clear"}
            loading={loadingOptions}
          />
        </div>

        <div className="flex gap-3 px-6 pb-5">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 px-4 py-2.5 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm font-medium transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || loadingOptions}
            className="flex-1 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? (
              <span className="flex items-center justify-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                Saving...
              </span>
            ) : (
              "Save Changes"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
