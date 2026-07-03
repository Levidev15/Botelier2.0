"use client";

import { useEffect, useState } from "react";
import { ClipboardList } from "lucide-react";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import type { RecordType, RecordRow, FieldDef } from "../types";
import { formatCell } from "../types";

interface Props {
  accountId?: string;
  sourceCallLogId?: string;
  sourceConversationId?: string;
  /** Visual density: "modal" (default) or "compact" for narrow panels. */
  variant?: "modal" | "compact";
}

/**
 * Shows structured records that were captured from a specific call or SMS
 * conversation. Renders nothing when there are no records.
 */
export default function SourceRecords({
  accountId: accountIdProp,
  sourceCallLogId,
  sourceConversationId,
  variant = "modal",
}: Props) {
  const { authFetch } = useAuthToken();
  const { accountId: contextAccountId } = useAccountContext();
  const accountId = accountIdProp || contextAccountId;
  const [records, setRecords] = useState<RecordRow[]>([]);
  const [typeMap, setTypeMap] = useState<Record<string, RecordType>>({});
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!accountId || (!sourceCallLogId && !sourceConversationId)) return;
    let cancelled = false;
    (async () => {
      try {
        const params = new URLSearchParams({ account_id: accountId, limit: "50" });
        if (sourceCallLogId) params.set("source_call_log_id", sourceCallLogId);
        if (sourceConversationId) params.set("source_conversation_id", sourceConversationId);

        const [recRes, typeRes] = await Promise.all([
          authFetch(`/api/records?${params.toString()}`),
          authFetch(`/api/record-types?account_id=${accountId}`),
        ]);
        const recJson = await recRes.json();
        const typeJson = await typeRes.json();
        if (cancelled) return;
        setRecords(recJson.records || []);
        const map: Record<string, RecordType> = {};
        (Array.isArray(typeJson) ? typeJson : []).forEach((t: RecordType) => {
          map[t.id] = t;
        });
        setTypeMap(map);
      } catch {
        if (!cancelled) setRecords([]);
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, sourceCallLogId, sourceConversationId]);

  if (!loaded || records.length === 0) return null;

  const statusFor = (rt: RecordType | undefined, value: string | null) => {
    if (!value) return null;
    const opt = (rt?.status_options || []).find((s) => s.value === value);
    return opt || { value, label: value, color: "#6b7280" };
  };

  return (
    <div className={variant === "modal" ? "mb-6" : "mb-4"}>
      <div className="flex items-center gap-2 mb-2">
        <ClipboardList className="h-4 w-4 text-rose-400" />
        <span className="text-sm font-medium text-rose-300">
          Records captured{records.length > 1 ? ` (${records.length})` : ""}
        </span>
      </div>
      <div className="space-y-2">
        {records.map((r) => {
          const rt = typeMap[r.record_type_id];
          const fields: FieldDef[] = rt?.fields || [];
          const st = statusFor(rt, r.status);
          const entries = fields.length
            ? fields.map((f) => ({
                label: f.label || f.key,
                value: formatCell(r.data?.[f.key], f),
              }))
            : Object.entries(r.data || {}).map(([k, v]) => ({
                label: k,
                value: v == null ? "" : String(v),
              }));
          return (
            <div
              key={r.id}
              className="rounded-lg border border-gray-800 bg-[#141414] px-3 py-2.5"
            >
              <div className="flex items-center gap-2 mb-2">
                <span
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: rt?.color || r.record_type_color || "#f43f5e" }}
                />
                <span className="text-sm font-medium text-white">
                  {rt?.name || r.record_type_name || "Record"}
                </span>
                <span className="text-[11px] uppercase tracking-wide text-gray-500">
                  {r.capture_method === "flow_node" ? "Flow" : "Auto"}
                </span>
                {st && (
                  <span
                    className="ml-auto inline-flex items-center px-2 py-0.5 rounded-full text-[11px]"
                    style={{ backgroundColor: `${st.color}22`, color: st.color || "#9ca3af" }}
                  >
                    {st.label}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                {entries
                  .filter((e) => e.value !== "" && e.value != null)
                  .map((e, i) => (
                    <div key={i} className="text-xs min-w-0">
                      <span className="text-gray-500">{e.label}: </span>
                      <span className="text-gray-200 break-words">{e.value}</span>
                    </div>
                  ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
