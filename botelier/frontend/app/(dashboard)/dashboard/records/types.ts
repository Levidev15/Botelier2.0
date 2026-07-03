export type FieldType =
  | "text"
  | "number"
  | "date"
  | "datetime"
  | "boolean"
  | "select"
  | "phone"
  | "email";

export interface FieldDef {
  key: string;
  label: string;
  type: FieldType;
  required?: boolean;
  options?: string[];
}

export interface StatusOption {
  value: string;
  label: string;
  color?: string;
}

export interface RecordType {
  id: string;
  account_id: string;
  name: string;
  slug: string;
  description?: string | null;
  icon?: string | null;
  color?: string | null;
  fields: FieldDef[];
  status_options: StatusOption[];
  auto_extract: boolean;
  extraction_instructions?: string | null;
  assistant_ids?: string[] | null;
  is_active: boolean;
  display_order: number;
  record_count?: number;
  created_at?: string;
  updated_at?: string | null;
}

export interface RecordRow {
  id: string;
  account_id: string;
  record_type_id: string;
  status: string | null;
  data: Record<string, any>;
  source_channel: string;
  capture_method: string;
  source_call_log_id?: string | null;
  source_conversation_id?: string | null;
  assistant_id?: string | null;
  created_at: string;
  updated_at?: string | null;
  record_type_name?: string;
  record_type_slug?: string;
  record_type_color?: string;
}

export const FIELD_TYPES: { value: FieldType; label: string }[] = [
  { value: "text", label: "Text" },
  { value: "number", label: "Number" },
  { value: "date", label: "Date" },
  { value: "datetime", label: "Date & time" },
  { value: "boolean", label: "Yes / No" },
  { value: "select", label: "Select (options)" },
  { value: "phone", label: "Phone" },
  { value: "email", label: "Email" },
];

export function sourceMeta(channel: string): { label: string } {
  switch (channel) {
    case "voice":
      return { label: "Voice" };
    case "sms":
      return { label: "SMS" };
    case "manual":
      return { label: "Manual" };
    default:
      return { label: channel || "—" };
  }
}

export function formatDateTime(iso?: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function formatCell(value: any, field: FieldDef): string {
  if (value === null || value === undefined || value === "") return "";
  if (field.type === "boolean") {
    if (value === true || value === "true") return "Yes";
    if (value === false || value === "false") return "No";
  }
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
