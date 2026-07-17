"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ClipboardList,
  Plus,
  FileDown,
  Settings2,
  Trash2,
  Pencil,
  Phone,
  MessageSquare,
  Hand,
  X,
  Loader2,
} from "lucide-react";
import { notify, confirmAction } from "@/lib/notifications";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { usePermissions } from "@/lib/auth/usePermissions";
import { usePagePermission, AccessDeniedPage } from "@/components/ui/PermissionGate";
import TimezonePicker from "@/components/analytics/TimezonePicker";
import { useTimezonePreference } from "@/lib/hooks/useTimezonePreference";
import type { RecordType, RecordRow, FieldDef } from "./types";
import { formatCell, formatDateTime, sourceMeta } from "./types";
import RecordFormModal from "./components/RecordFormModal";

export default function RecordsPage() {
  const { accountId, loading: contextLoading } = useAccountContext();
  const { authFetch } = useAuthToken();
  const { can, isPlatformAdmin } = usePermissions();
  const { hasAccess, loading: permLoading } = usePagePermission("records", "view");

  const canCreate = isPlatformAdmin || can("records", "create");
  const canEdit = isPlatformAdmin || can("records", "edit");
  const canDelete = isPlatformAdmin || can("records", "delete");
  const canExport = isPlatformAdmin || can("records", "export");
  const canManageTypes = isPlatformAdmin || can("records", "manage_types");

  const [recordTypes, setRecordTypes] = useState<RecordType[]>([]);
  const [selectedTypeId, setSelectedTypeId] = useState<string | null>(null);
  const [records, setRecords] = useState<RecordRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loadingTypes, setLoadingTypes] = useState(true);
  const [loadingRecords, setLoadingRecords] = useState(false);

  const [statusFilter, setStatusFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [assistantFilter, setAssistantFilter] = useState("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [assistants, setAssistants] = useState<{ id: string; name: string }[]>([]);
  const [offset, setOffset] = useState(0);
  const limit = 50;

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<RecordRow | null>(null);
  const { timezone, setTimezone } = useTimezonePreference();

  const selectedType = useMemo(
    () => recordTypes.find((t) => t.id === selectedTypeId) || null,
    [recordTypes, selectedTypeId]
  );

  useEffect(() => {
    if (!contextLoading && accountId) {
      fetchTypes();
      fetchAssistants();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, contextLoading]);

  // Debounce the free-text search so we don't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    if (accountId && selectedTypeId) fetchRecords();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, selectedTypeId, statusFilter, sourceFilter, assistantFilter, debouncedSearch, dateFrom, dateTo, offset]);

  const fetchTypes = async () => {
    if (!accountId) return;
    try {
      setLoadingTypes(true);
      const res = await authFetch(`/api/record-types?account_id=${accountId}`);
      const data = await res.json();
      const types: RecordType[] = Array.isArray(data) ? data : [];
      setRecordTypes(types);
      if (types.length && !selectedTypeId) setSelectedTypeId(types[0].id);
    } catch (e) {
      console.error("Failed to load record types", e);
    } finally {
      setLoadingTypes(false);
    }
  };

  const fetchAssistants = async () => {
    if (!accountId) return;
    try {
      const res = await authFetch(
        `/api/assistants?account_id=${accountId}&is_active=true`
      );
      const data = await res.json();
      setAssistants(
        Array.isArray(data?.assistants)
          ? data.assistants.map((a: any) => ({ id: a.id, name: a.name }))
          : []
      );
    } catch (e) {
      console.error("Failed to load assistants", e);
    }
  };

  const fetchRecords = async () => {
    if (!accountId || !selectedTypeId) return;
    try {
      setLoadingRecords(true);
      const params = new URLSearchParams({
        account_id: accountId,
        record_type_id: selectedTypeId,
        limit: String(limit),
        offset: String(offset),
      });
      if (statusFilter) params.set("status", statusFilter);
      if (sourceFilter) params.set("source_channel", sourceFilter);
      if (assistantFilter) params.set("assistant_id", assistantFilter);
      if (debouncedSearch.trim()) params.set("search", debouncedSearch.trim());
      if (dateFrom) params.set("date_from", new Date(dateFrom).toISOString());
      if (dateTo) params.set("date_to", new Date(`${dateTo}T23:59:59.999Z`).toISOString());
      const res = await authFetch(`/api/records?${params.toString()}`);
      const data = await res.json();
      setRecords(data.records || []);
      setTotal(data.total || 0);
    } catch (e) {
      console.error("Failed to load records", e);
    } finally {
      setLoadingRecords(false);
    }
  };

  const selectType = (id: string) => {
    setSelectedTypeId(id);
    setOffset(0);
    setStatusFilter("");
    setSourceFilter("");
    setAssistantFilter("");
    setSearch("");
    setDebouncedSearch("");
    setDateFrom("");
    setDateTo("");
  };

  const handleDelete = async (row: RecordRow) => {
    const confirmed = await confirmAction("Delete this record? This cannot be undone.");
    if (!confirmed) return;
    try {
      const res = await authFetch(`/api/records/${row.id}?account_id=${accountId}`, {
        method: "DELETE",
      });
      if (res.ok) {
        notify.success("Record deleted");
        setRecords((prev) => prev.filter((r) => r.id !== row.id));
        setTotal((t) => Math.max(0, t - 1));
        fetchTypes();
      } else {
        notify.error("Failed to delete record");
      }
    } catch {
      notify.error("Failed to delete record");
    }
  };

  const handleExport = () => {
    if (!accountId || !selectedTypeId) return;
    const params = new URLSearchParams({
      account_id: accountId,
      record_type_id: selectedTypeId,
    });
    if (statusFilter) params.set("status", statusFilter);
    if (sourceFilter) params.set("source_channel", sourceFilter);
    if (assistantFilter) params.set("assistant_id", assistantFilter);
    if (debouncedSearch.trim()) params.set("search", debouncedSearch.trim());
    if (dateFrom) params.set("date_from", new Date(dateFrom).toISOString());
    if (dateTo) params.set("date_to", new Date(`${dateTo}T23:59:59.999Z`).toISOString());
    // Stream via authFetch to include the bearer token, then trigger a download.
    (async () => {
      try {
        const res = await authFetch(`/api/records/export?${params.toString()}`);
        if (!res.ok) {
          notify.error("Export failed");
          return;
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${selectedType?.slug || "records"}.csv`;
        link.click();
        URL.revokeObjectURL(url);
      } catch {
        notify.error("Export failed");
      }
    })();
  };

  const statusMeta = (value: string | null) => {
    if (!value) return null;
    const opt = (selectedType?.status_options || []).find((s) => s.value === value);
    return opt || { value, label: value, color: "#6b7280" };
  };

  if (!permLoading && !hasAccess) {
    return <AccessDeniedPage message="You don't have permission to view records." />;
  }

  const fields = selectedType?.fields || [];

  return (
    <div className="h-full">
      <div className="border-b border-gray-800 bg-[#0a0a0a] sticky top-0 z-10">
        <div className="px-8 py-6 flex items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <ClipboardList className="h-6 w-6" /> Records
            </h1>
            <p className="text-sm text-gray-400 mt-1">
              Structured data captured from calls and messages
            </p>
          </div>
          <div className="flex items-center gap-2">
            <TimezonePicker value={timezone} onChange={setTimezone} />
            {canExport && selectedType && (
              <button
                onClick={handleExport}
                className="flex items-center gap-2 px-3 py-2 text-sm rounded-lg border border-gray-700 hover:bg-gray-800 transition"
              >
                <FileDown className="h-4 w-4" /> Export CSV
              </button>
            )}
            {canManageTypes && (
              <Link
                href="/dashboard/records/types"
                className="flex items-center gap-2 px-3 py-2 text-sm rounded-lg border border-gray-700 hover:bg-gray-800 transition"
              >
                <Settings2 className="h-4 w-4" /> Manage Types
              </Link>
            )}
            {canCreate && selectedType && (
              <button
                onClick={() => {
                  setEditing(null);
                  setShowForm(true);
                }}
                className="flex items-center gap-2 px-3 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 transition font-medium"
              >
                <Plus className="h-4 w-4" /> New Record
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="p-8">
        {loadingTypes ? (
          <div className="flex items-center justify-center py-24 text-gray-400">
            <Loader2 className="h-5 w-5 animate-spin mr-2" /> Loading…
          </div>
        ) : recordTypes.length === 0 ? (
          <EmptyTypes canManageTypes={canManageTypes} />
        ) : (
          <>
            {/* Record type tabs */}
            <div className="flex flex-wrap gap-2 mb-6">
              {recordTypes.map((t) => {
                const active = t.id === selectedTypeId;
                return (
                  <button
                    key={t.id}
                    onClick={() => selectType(t.id)}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm border transition ${
                      active
                        ? "bg-gray-800 border-gray-600 text-white"
                        : "border-gray-800 text-gray-400 hover:border-gray-700 hover:text-gray-200"
                    }`}
                  >
                    <span
                      className="h-2.5 w-2.5 rounded-full"
                      style={{ backgroundColor: t.color || "#6366f1" }}
                    />
                    {t.name}
                    <span className="text-xs text-gray-500">{t.record_count ?? 0}</span>
                    {!t.is_active && (
                      <span className="text-[10px] uppercase text-amber-500">off</span>
                    )}
                  </button>
                );
              })}
            </div>

            {/* Filters */}
            <div className="flex flex-wrap items-center gap-3 mb-4">
              {(selectedType?.status_options?.length ?? 0) > 0 && (
                <select
                  value={statusFilter}
                  onChange={(e) => {
                    setStatusFilter(e.target.value);
                    setOffset(0);
                  }}
                  className="bg-[#111111] border border-gray-800 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                >
                  <option value="">All statuses</option>
                  {selectedType!.status_options.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </select>
              )}
              <select
                value={sourceFilter}
                onChange={(e) => {
                  setSourceFilter(e.target.value);
                  setOffset(0);
                }}
                className="bg-[#111111] border border-gray-800 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
              >
                <option value="">All sources</option>
                <option value="voice">Voice</option>
                <option value="sms">SMS</option>
                <option value="manual">Manual</option>
              </select>
              <select
                value={assistantFilter}
                onChange={(e) => {
                  setAssistantFilter(e.target.value);
                  setOffset(0);
                }}
                className="bg-[#111111] border border-gray-800 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
              >
                <option value="">All assistants</option>
                {assistants.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => {
                  setDateFrom(e.target.value);
                  setOffset(0);
                }}
                title="From date"
                className="bg-[#111111] border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-300"
              />
              <input
                type="date"
                value={dateTo}
                onChange={(e) => {
                  setDateTo(e.target.value);
                  setOffset(0);
                }}
                title="To date"
                className="bg-[#111111] border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-300"
              />
              <input
                type="text"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setOffset(0);
                }}
                placeholder="Search records…"
                className="bg-[#111111] border border-gray-800 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 min-w-[200px] focus:outline-none focus:border-indigo-500"
              />
              <div className="text-sm text-gray-500 ml-auto">{total} records</div>
            </div>

            {/* Records table */}
            <div className="border border-gray-800 rounded-xl overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-[#111111] text-gray-400">
                    <tr>
                      <th className="text-left font-medium px-4 py-3 whitespace-nowrap">Captured</th>
                      <th className="text-left font-medium px-4 py-3 whitespace-nowrap">Source</th>
                      {(selectedType?.status_options?.length ?? 0) > 0 && (
                        <th className="text-left font-medium px-4 py-3 whitespace-nowrap">Status</th>
                      )}
                      {fields.map((f) => (
                        <th
                          key={f.key}
                          className="text-left font-medium px-4 py-3 whitespace-nowrap"
                        >
                          {f.label || f.key}
                        </th>
                      ))}
                      <th className="px-4 py-3" />
                    </tr>
                  </thead>
                  <tbody>
                    {loadingRecords ? (
                      <tr>
                        <td
                          colSpan={fields.length + 4}
                          className="px-4 py-12 text-center text-gray-500"
                        >
                          <Loader2 className="h-5 w-5 animate-spin inline mr-2" /> Loading…
                        </td>
                      </tr>
                    ) : records.length === 0 ? (
                      <tr>
                        <td
                          colSpan={fields.length + 4}
                          className="px-4 py-12 text-center text-gray-500"
                        >
                          No records yet for {selectedType?.name}.
                        </td>
                      </tr>
                    ) : (
                      records.map((r) => {
                        const sm = sourceMeta(r.source_channel);
                        const st = statusMeta(r.status);
                        const sourceHref =
                          r.source_channel === "voice" && r.source_call_log_id
                            ? `/dashboard/call-logs?call=${r.source_call_log_id}`
                            : r.source_channel === "sms" && r.source_conversation_id
                            ? `/dashboard/messages?conversation=${r.source_conversation_id}`
                            : null;
                        return (
                          <tr
                            key={r.id}
                            className="border-t border-gray-800 hover:bg-[#0e0e0e]"
                          >
                            <td className="px-4 py-3 whitespace-nowrap text-gray-300">
                              {formatDateTime(r.created_at, timezone)}
                            </td>
                            <td className="px-4 py-3 whitespace-nowrap">
                              {sourceHref ? (
                                <Link
                                  href={sourceHref}
                                  className="inline-flex items-center gap-1.5 text-xs text-indigo-400 hover:text-indigo-300 hover:underline"
                                  title={`View ${sm.label} source`}
                                >
                                  <SourceIcon channel={r.source_channel} />
                                  {sm.label}
                                </Link>
                              ) : (
                                <span
                                  className="inline-flex items-center gap-1.5 text-xs text-gray-300"
                                  title={r.capture_method}
                                >
                                  <SourceIcon channel={r.source_channel} />
                                  {sm.label}
                                </span>
                              )}
                            </td>
                            {(selectedType?.status_options?.length ?? 0) > 0 && (
                              <td className="px-4 py-3 whitespace-nowrap">
                                {st ? (
                                  <span
                                    className="inline-flex items-center px-2 py-0.5 rounded-full text-xs"
                                    style={{
                                      backgroundColor: `${st.color}22`,
                                      color: st.color || "#9ca3af",
                                    }}
                                  >
                                    {st.label}
                                  </span>
                                ) : (
                                  <span className="text-gray-600">—</span>
                                )}
                              </td>
                            )}
                            {fields.map((f) => (
                              <td
                                key={f.key}
                                className="px-4 py-3 max-w-[240px] truncate text-gray-200"
                                title={formatCell(r.data?.[f.key], f)}
                              >
                                {formatCell(r.data?.[f.key], f) || (
                                  <span className="text-gray-600">—</span>
                                )}
                              </td>
                            ))}
                            <td className="px-4 py-3 whitespace-nowrap text-right">
                              <div className="flex items-center justify-end gap-1">
                                {canEdit && (
                                  <button
                                    onClick={() => {
                                      setEditing(r);
                                      setShowForm(true);
                                    }}
                                    className="p-1.5 rounded hover:bg-gray-800 text-gray-400 hover:text-white"
                                    title="Edit"
                                  >
                                    <Pencil className="h-4 w-4" />
                                  </button>
                                )}
                                {canDelete && (
                                  <button
                                    onClick={() => handleDelete(r)}
                                    className="p-1.5 rounded hover:bg-gray-800 text-gray-400 hover:text-red-400"
                                    title="Delete"
                                  >
                                    <Trash2 className="h-4 w-4" />
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Pagination */}
            {total > limit && (
              <div className="flex items-center justify-between mt-4 text-sm text-gray-400">
                <button
                  disabled={offset === 0}
                  onClick={() => setOffset((o) => Math.max(0, o - limit))}
                  className="px-3 py-1.5 rounded-lg border border-gray-800 disabled:opacity-40 hover:bg-gray-800"
                >
                  Previous
                </button>
                <span>
                  {offset + 1}–{Math.min(offset + limit, total)} of {total}
                </span>
                <button
                  disabled={offset + limit >= total}
                  onClick={() => setOffset((o) => o + limit)}
                  className="px-3 py-1.5 rounded-lg border border-gray-800 disabled:opacity-40 hover:bg-gray-800"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {showForm && selectedType && accountId && (
        <RecordFormModal
          accountId={accountId}
          recordType={selectedType}
          record={editing}
          timezone={timezone}
          onClose={() => {
            setShowForm(false);
            setEditing(null);
          }}
          onSaved={() => {
            setShowForm(false);
            setEditing(null);
            fetchRecords();
            fetchTypes();
          }}
        />
      )}
    </div>
  );
}

function SourceIcon({ channel }: { channel: string }) {
  if (channel === "voice") return <Phone className="h-3.5 w-3.5 text-emerald-400" />;
  if (channel === "sms") return <MessageSquare className="h-3.5 w-3.5 text-sky-400" />;
  return <Hand className="h-3.5 w-3.5 text-gray-400" />;
}

function EmptyTypes({ canManageTypes }: { canManageTypes: boolean }) {
  return (
    <div className="border border-dashed border-gray-800 rounded-xl py-20 text-center">
      <ClipboardList className="h-10 w-10 mx-auto text-gray-600 mb-4" />
      <h2 className="text-lg font-semibold">No record types yet</h2>
      <p className="text-sm text-gray-400 mt-1 max-w-md mx-auto">
        Define a record type (like Bookings or Housekeeping requests) to start capturing
        structured data from your calls and messages.
      </p>
      {canManageTypes && (
        <Link
          href="/dashboard/records/types"
          className="inline-flex items-center gap-2 mt-6 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-medium"
        >
          <Plus className="h-4 w-4" /> Create a record type
        </Link>
      )}
    </div>
  );
}
