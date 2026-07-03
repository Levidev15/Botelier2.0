"use client";

import { useState } from "react";
import { X, Loader2 } from "lucide-react";
import { notify } from "@/lib/notifications";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import type { RecordType, RecordRow, FieldDef } from "../types";

interface Props {
  accountId: string;
  recordType: RecordType;
  record: RecordRow | null;
  onClose: () => void;
  onSaved: () => void;
}

export default function RecordFormModal({
  accountId,
  recordType,
  record,
  onClose,
  onSaved,
}: Props) {
  const { authFetch } = useAuthToken();
  const isEdit = !!record;

  const [data, setData] = useState<Record<string, any>>(() => ({ ...(record?.data || {}) }));
  const [statusValue, setStatusValue] = useState<string>(record?.status || "");
  const [saving, setSaving] = useState(false);

  const setField = (key: string, value: any) => {
    setData((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    // Validate required fields.
    const missing = (recordType.fields || [])
      .filter((f) => f.required)
      .filter((f) => {
        const v = data[f.key];
        return v === undefined || v === null || v === "";
      });
    if (missing.length) {
      notify.error(`Please fill in: ${missing.map((f) => f.label || f.key).join(", ")}`);
      return;
    }

    setSaving(true);
    try {
      const payload: any = {
        data,
        status: statusValue || null,
      };
      let res: Response;
      if (isEdit) {
        res = await authFetch(`/api/records/${record!.id}?account_id=${accountId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      } else {
        res = await authFetch(`/api/records?account_id=${accountId}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...payload, record_type_id: recordType.id }),
        });
      }
      if (res.ok) {
        notify.success(isEdit ? "Record updated" : "Record created");
        onSaved();
      } else {
        const err = await res.json().catch(() => ({}));
        notify.error(err?.detail || "Failed to save record");
      }
    } catch {
      notify.error("Failed to save record");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-[#0d0d0d] border border-gray-800 rounded-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800 sticky top-0 bg-[#0d0d0d]">
          <h2 className="text-lg font-semibold">
            {isEdit ? "Edit" : "New"} {recordType.name} record
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">
          {(recordType.fields || []).map((f) => (
            <FieldInput key={f.key} field={f} value={data[f.key]} onChange={(v) => setField(f.key, v)} />
          ))}

          {(recordType.status_options?.length ?? 0) > 0 && (
            <div>
              <label className="block text-sm text-gray-300 mb-1">Status</label>
              <select
                value={statusValue}
                onChange={(e) => setStatusValue(e.target.value)}
                className="w-full bg-[#111111] border border-gray-800 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
              >
                <option value="">—</option>
                {recordType.status_options.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          {(recordType.fields?.length ?? 0) === 0 && (
            <p className="text-sm text-gray-500">
              This record type has no fields defined yet. Add fields in Manage Types.
            </p>
          )}
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
            {isEdit ? "Save changes" : "Create record"}
          </button>
        </div>
      </div>
    </div>
  );
}

function FieldInput({
  field,
  value,
  onChange,
}: {
  field: FieldDef;
  value: any;
  onChange: (v: any) => void;
}) {
  const label = (
    <label className="block text-sm text-gray-300 mb-1">
      {field.label || field.key}
      {field.required && <span className="text-red-400 ml-0.5">*</span>}
    </label>
  );
  const cls =
    "w-full bg-[#111111] border border-gray-800 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500";

  if (field.type === "boolean") {
    return (
      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={value === true || value === "true"}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 accent-indigo-600"
        />
        <span className="text-sm text-gray-300">{field.label || field.key}</span>
      </div>
    );
  }

  if (field.type === "select") {
    return (
      <div>
        {label}
        <select value={value ?? ""} onChange={(e) => onChange(e.target.value)} className={cls}>
          <option value="">—</option>
          {(field.options || []).map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      </div>
    );
  }

  const inputType =
    field.type === "number"
      ? "number"
      : field.type === "date"
      ? "date"
      : field.type === "datetime"
      ? "datetime-local"
      : field.type === "email"
      ? "email"
      : field.type === "phone"
      ? "tel"
      : "text";

  return (
    <div>
      {label}
      <input
        type={inputType}
        value={value ?? ""}
        onChange={(e) =>
          onChange(field.type === "number" ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value)
        }
        className={cls}
      />
    </div>
  );
}
