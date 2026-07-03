"use client";

import { useEffect, useState } from "react";
import { X, Loader2, Plus, Trash2, GripVertical } from "lucide-react";
import { notify } from "@/lib/notifications";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import type { RecordType, FieldDef, StatusOption, FieldType } from "../types";
import { FIELD_TYPES } from "../types";

interface Assistant {
  id: string;
  name: string;
}

interface Props {
  accountId: string;
  recordType: RecordType | null;
  onClose: () => void;
  onSaved: () => void;
}

const COLORS = [
  "#6366f1",
  "#8b5cf6",
  "#ec4899",
  "#ef4444",
  "#f59e0b",
  "#10b981",
  "#06b6d4",
  "#3b82f6",
];

function slugKey(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

export default function RecordTypeModal({ accountId, recordType, onClose, onSaved }: Props) {
  const { authFetch } = useAuthToken();
  const isEdit = !!recordType;

  const [name, setName] = useState(recordType?.name || "");
  const [description, setDescription] = useState(recordType?.description || "");
  const [color, setColor] = useState(recordType?.color || COLORS[0]);
  const [isActive, setIsActive] = useState(recordType?.is_active ?? true);
  const [fields, setFields] = useState<FieldDef[]>(recordType?.fields || []);
  const [statusOptions, setStatusOptions] = useState<StatusOption[]>(
    recordType?.status_options || []
  );
  const [autoExtract, setAutoExtract] = useState(recordType?.auto_extract ?? false);
  const [extractionInstructions, setExtractionInstructions] = useState(
    recordType?.extraction_instructions || ""
  );
  const [scopeAll, setScopeAll] = useState(
    !recordType?.assistant_ids || recordType.assistant_ids.length === 0
  );
  const [assistantIds, setAssistantIds] = useState<string[]>(recordType?.assistant_ids || []);
  const [assistants, setAssistants] = useState<Assistant[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await authFetch(`/api/assistants?account_id=${accountId}`);
        const data = await res.json();
        setAssistants(data.assistants || []);
      } catch {
        setAssistants([]);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId]);

  const addField = () =>
    setFields((prev) => [...prev, { key: "", label: "", type: "text", required: false }]);

  const updateField = (idx: number, patch: Partial<FieldDef>) =>
    setFields((prev) => prev.map((f, i) => (i === idx ? { ...f, ...patch } : f)));

  const removeField = (idx: number) =>
    setFields((prev) => prev.filter((_, i) => i !== idx));

  const moveField = (idx: number, dir: -1 | 1) =>
    setFields((prev) => {
      const next = [...prev];
      const target = idx + dir;
      if (target < 0 || target >= next.length) return prev;
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });

  const addStatus = () =>
    setStatusOptions((prev) => [...prev, { value: "", label: "", color: "#6b7280" }]);

  const updateStatus = (idx: number, patch: Partial<StatusOption>) =>
    setStatusOptions((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)));

  const removeStatus = (idx: number) =>
    setStatusOptions((prev) => prev.filter((_, i) => i !== idx));

  const toggleAssistant = (id: string) =>
    setAssistantIds((prev) =>
      prev.includes(id) ? prev.filter((a) => a !== id) : [...prev, id]
    );

  const handleSave = async () => {
    if (!name.trim()) {
      notify.error("Name is required");
      return;
    }
    // Normalise + validate fields.
    const cleanFields: FieldDef[] = [];
    const seenKeys = new Set<string>();
    for (const f of fields) {
      const label = (f.label || "").trim();
      const key = (f.key || "").trim() || slugKey(label);
      if (!key) {
        notify.error("Every field needs a name");
        return;
      }
      if (seenKeys.has(key)) {
        notify.error(`Duplicate field key: ${key}`);
        return;
      }
      seenKeys.add(key);
      const cleaned: FieldDef = {
        key,
        label: label || key,
        type: f.type,
        required: !!f.required,
      };
      if (f.type === "select") {
        cleaned.options = (f.options || []).map((o) => o.trim()).filter(Boolean);
      }
      cleanFields.push(cleaned);
    }

    const cleanStatuses: StatusOption[] = [];
    const seenStatus = new Set<string>();
    for (const s of statusOptions) {
      const label = (s.label || "").trim();
      const value = (s.value || "").trim() || slugKey(label);
      if (!value) continue;
      if (seenStatus.has(value)) continue;
      seenStatus.add(value);
      cleanStatuses.push({ value, label: label || value, color: s.color || "#6b7280" });
    }

    const payload: any = {
      name: name.trim(),
      description: description.trim() || null,
      color,
      is_active: isActive,
      fields: cleanFields,
      status_options: cleanStatuses,
      auto_extract: autoExtract,
      extraction_instructions: extractionInstructions.trim() || null,
      assistant_ids: scopeAll ? null : assistantIds,
    };

    setSaving(true);
    try {
      const res = isEdit
        ? await authFetch(`/api/record-types/${recordType!.id}?account_id=${accountId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          })
        : await authFetch(`/api/record-types?account_id=${accountId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
      if (res.ok) {
        notify.success(isEdit ? "Record type updated" : "Record type created");
        onSaved();
      } else {
        const err = await res.json().catch(() => ({}));
        notify.error(typeof err?.detail === "string" ? err.detail : "Failed to save record type");
      }
    } catch {
      notify.error("Failed to save record type");
    } finally {
      setSaving(false);
    }
  };

  const inputCls =
    "w-full bg-[#111] border border-gray-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-[#0d0d0d] border border-gray-800 rounded-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800 sticky top-0 bg-[#0d0d0d] z-10">
          <h2 className="text-lg font-semibold">
            {isEdit ? "Edit record type" : "New record type"}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-6 py-5 space-y-6">
          {/* Basics */}
          <div className="grid grid-cols-1 gap-4">
            <div>
              <label className="block text-sm text-gray-300 mb-1">Name</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Bookings"
                className={inputCls}
              />
            </div>
            <div>
              <label className="block text-sm text-gray-300 mb-1">Description</label>
              <input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What this record captures"
                className={inputCls}
              />
            </div>
            <div>
              <label className="block text-sm text-gray-300 mb-2">Color</label>
              <div className="flex items-center gap-2">
                {COLORS.map((c) => (
                  <button
                    key={c}
                    onClick={() => setColor(c)}
                    className={`h-7 w-7 rounded-full border-2 transition ${
                      color === c ? "border-white" : "border-transparent"
                    }`}
                    style={{ backgroundColor: c }}
                  />
                ))}
              </div>
            </div>
          </div>

          {/* Fields */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-gray-200">Columns</h3>
              <button
                onClick={addField}
                className="flex items-center gap-1 text-xs px-2 py-1 rounded border border-gray-700 hover:bg-gray-800"
              >
                <Plus className="h-3.5 w-3.5" /> Add column
              </button>
            </div>
            {fields.length === 0 && (
              <p className="text-sm text-gray-500 mb-2">
                No columns yet. Add the pieces of information you want to capture.
              </p>
            )}
            <div className="space-y-2">
              {fields.map((f, idx) => (
                <div key={idx} className="rounded-lg border border-gray-800 p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <div className="flex flex-col text-gray-600">
                      <button
                        onClick={() => moveField(idx, -1)}
                        className="hover:text-gray-300 leading-none"
                        title="Move up"
                      >
                        ▲
                      </button>
                      <button
                        onClick={() => moveField(idx, 1)}
                        className="hover:text-gray-300 leading-none"
                        title="Move down"
                      >
                        ▼
                      </button>
                    </div>
                    <input
                      value={f.label}
                      onChange={(e) =>
                        updateField(idx, {
                          label: e.target.value,
                          key: f.key || slugKey(e.target.value),
                        })
                      }
                      placeholder="Column label (e.g. Guest name)"
                      className={inputCls}
                    />
                    <select
                      value={f.type}
                      onChange={(e) => updateField(idx, { type: e.target.value as FieldType })}
                      className="bg-[#111] border border-gray-800 rounded-lg px-2 py-2 text-sm"
                    >
                      {FIELD_TYPES.map((t) => (
                        <option key={t.value} value={t.value}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={() => removeField(idx)}
                      className="p-1.5 text-gray-500 hover:text-red-400"
                      title="Remove"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                  <div className="flex items-center gap-4 pl-8">
                    <label className="flex items-center gap-1.5 text-xs text-gray-400">
                      <input
                        type="checkbox"
                        checked={!!f.required}
                        onChange={(e) => updateField(idx, { required: e.target.checked })}
                        className="h-3.5 w-3.5 accent-indigo-600"
                      />
                      Required
                    </label>
                    <span className="text-xs text-gray-600">key: {f.key || slugKey(f.label)}</span>
                  </div>
                  {f.type === "select" && (
                    <div className="pl-8">
                      <input
                        value={(f.options || []).join(", ")}
                        onChange={(e) =>
                          updateField(idx, {
                            options: e.target.value.split(",").map((o) => o.trim()),
                          })
                        }
                        placeholder="Options, comma separated"
                        className={inputCls}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Status options */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-gray-200">
                Statuses <span className="text-gray-500 font-normal">(optional)</span>
              </h3>
              <button
                onClick={addStatus}
                className="flex items-center gap-1 text-xs px-2 py-1 rounded border border-gray-700 hover:bg-gray-800"
              >
                <Plus className="h-3.5 w-3.5" /> Add status
              </button>
            </div>
            <div className="space-y-2">
              {statusOptions.map((s, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <input
                    type="color"
                    value={s.color || "#6b7280"}
                    onChange={(e) => updateStatus(idx, { color: e.target.value })}
                    className="h-8 w-8 rounded bg-transparent border border-gray-800 cursor-pointer"
                  />
                  <input
                    value={s.label}
                    onChange={(e) =>
                      updateStatus(idx, {
                        label: e.target.value,
                        value: s.value || slugKey(e.target.value),
                      })
                    }
                    placeholder="Status label (e.g. Open)"
                    className={inputCls}
                  />
                  <button
                    onClick={() => removeStatus(idx)}
                    className="p-1.5 text-gray-500 hover:text-red-400"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Auto extraction */}
          <div className="rounded-lg border border-gray-800 p-4 space-y-3">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={autoExtract}
                onChange={(e) => setAutoExtract(e.target.checked)}
                className="h-4 w-4 accent-indigo-600"
              />
              <span className="text-sm font-medium text-gray-200">
                Automatically capture from conversations
              </span>
            </label>
            <p className="text-xs text-gray-500">
              When on, completed voice and SMS conversations are analyzed and matching
              records are created automatically.
            </p>
            {autoExtract && (
              <>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">
                    Extraction guidance (optional)
                  </label>
                  <textarea
                    value={extractionInstructions}
                    onChange={(e) => setExtractionInstructions(e.target.value)}
                    rows={3}
                    placeholder="e.g. Only create a booking when the caller confirms a date."
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-2">Applies to</label>
                  <label className="flex items-center gap-2 text-sm mb-1">
                    <input
                      type="radio"
                      checked={scopeAll}
                      onChange={() => setScopeAll(true)}
                      className="accent-indigo-600"
                    />
                    All assistants
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      checked={!scopeAll}
                      onChange={() => setScopeAll(false)}
                      className="accent-indigo-600"
                    />
                    Specific assistants
                  </label>
                  {!scopeAll && (
                    <div className="mt-2 max-h-40 overflow-y-auto space-y-1 pl-6">
                      {assistants.length === 0 && (
                        <p className="text-xs text-gray-500">No assistants found.</p>
                      )}
                      {assistants.map((a) => (
                        <label key={a.id} className="flex items-center gap-2 text-sm text-gray-300">
                          <input
                            type="checkbox"
                            checked={assistantIds.includes(a.id)}
                            onChange={() => toggleAssistant(a.id)}
                            className="h-3.5 w-3.5 accent-indigo-600"
                          />
                          {a.name}
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>

          {/* Active */}
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              className="h-4 w-4 accent-indigo-600"
            />
            <span className="text-sm text-gray-200">Active</span>
          </label>
        </div>

        <div className="flex justify-end gap-2 px-6 py-4 border-t border-gray-800 sticky bottom-0 bg-[#0d0d0d]">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-lg border border-gray-700 hover:bg-gray-800"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 font-medium flex items-center gap-2 disabled:opacity-60"
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            {isEdit ? "Save changes" : "Create record type"}
          </button>
        </div>
      </div>
    </div>
  );
}
