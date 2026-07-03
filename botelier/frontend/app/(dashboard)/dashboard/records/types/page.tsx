"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Plus,
  Pencil,
  Trash2,
  Sparkles,
  Loader2,
  Settings2,
} from "lucide-react";
import { notify, confirmAction } from "@/lib/notifications";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { usePermissions } from "@/lib/auth/usePermissions";
import { usePagePermission, AccessDeniedPage } from "@/components/ui/PermissionGate";
import type { RecordType } from "../types";
import RecordTypeModal from "../components/RecordTypeModal";

export default function RecordTypesPage() {
  const { accountId, loading: contextLoading } = useAccountContext();
  const { authFetch } = useAuthToken();
  const { can, isPlatformAdmin } = usePermissions();
  const { hasAccess, loading: permLoading } = usePagePermission("records", "view");

  const canManageTypes = isPlatformAdmin || can("records", "manage_types");

  const [recordTypes, setRecordTypes] = useState<RecordType[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState<RecordType | null>(null);

  useEffect(() => {
    if (!contextLoading && accountId) fetchTypes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, contextLoading]);

  const fetchTypes = async () => {
    if (!accountId) return;
    try {
      setLoading(true);
      const res = await authFetch(`/api/record-types?account_id=${accountId}`);
      const data = await res.json();
      setRecordTypes(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error("Failed to load record types", e);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (rt: RecordType) => {
    const confirmed = await confirmAction(
      `Delete record type "${rt.name}"? This permanently deletes all ${
        rt.record_count ?? 0
      } records captured under it.`
    );
    if (!confirmed) return;
    try {
      const res = await authFetch(`/api/record-types/${rt.id}?account_id=${accountId}`, {
        method: "DELETE",
      });
      if (res.ok) {
        notify.success("Record type deleted");
        setRecordTypes((prev) => prev.filter((t) => t.id !== rt.id));
      } else {
        notify.error("Failed to delete record type");
      }
    } catch {
      notify.error("Failed to delete record type");
    }
  };

  if (!permLoading && !hasAccess) {
    return <AccessDeniedPage message="You don't have permission to view records." />;
  }

  return (
    <div className="h-full">
      <div className="border-b border-gray-800 bg-[#0a0a0a] sticky top-0 z-10">
        <div className="px-8 py-6 flex items-center justify-between gap-4">
          <div>
            <Link
              href="/dashboard/records"
              className="inline-flex items-center gap-1.5 text-sm text-gray-400 hover:text-white mb-2"
            >
              <ArrowLeft className="h-4 w-4" /> Back to records
            </Link>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Settings2 className="h-6 w-6" /> Record Types
            </h1>
            <p className="text-sm text-gray-400 mt-1">
              Define the structured tables your assistants capture
            </p>
          </div>
          {canManageTypes && (
            <button
              onClick={() => {
                setEditing(null);
                setShowModal(true);
              }}
              className="flex items-center gap-2 px-3 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 font-medium"
            >
              <Plus className="h-4 w-4" /> New Type
            </button>
          )}
        </div>
      </div>

      <div className="p-8">
        {loading ? (
          <div className="flex items-center justify-center py-24 text-gray-400">
            <Loader2 className="h-5 w-5 animate-spin mr-2" /> Loading…
          </div>
        ) : recordTypes.length === 0 ? (
          <div className="border border-dashed border-gray-800 rounded-xl py-20 text-center">
            <Settings2 className="h-10 w-10 mx-auto text-gray-600 mb-4" />
            <h2 className="text-lg font-semibold">No record types yet</h2>
            <p className="text-sm text-gray-400 mt-1 max-w-md mx-auto">
              Create your first record type to start capturing structured data.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {recordTypes.map((rt) => (
              <div
                key={rt.id}
                className="rounded-xl border border-gray-800 bg-[#0d0d0d] p-5 flex flex-col"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2.5">
                    <span
                      className="h-3 w-3 rounded-full"
                      style={{ backgroundColor: rt.color || "#6366f1" }}
                    />
                    <h3 className="font-semibold">{rt.name}</h3>
                  </div>
                  {canManageTypes && (
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => {
                          setEditing(rt);
                          setShowModal(true);
                        }}
                        className="p-1.5 rounded hover:bg-gray-800 text-gray-400 hover:text-white"
                        title="Edit"
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                      <button
                        onClick={() => handleDelete(rt)}
                        className="p-1.5 rounded hover:bg-gray-800 text-gray-400 hover:text-red-400"
                        title="Delete"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  )}
                </div>
                {rt.description && (
                  <p className="text-sm text-gray-400 mt-2 line-clamp-2">{rt.description}</p>
                )}
                <div className="mt-4 flex flex-wrap gap-1.5">
                  {(rt.fields || []).slice(0, 5).map((f) => (
                    <span
                      key={f.key}
                      className="text-xs px-2 py-0.5 rounded bg-gray-800 text-gray-300"
                    >
                      {f.label || f.key}
                    </span>
                  ))}
                  {(rt.fields?.length ?? 0) > 5 && (
                    <span className="text-xs px-2 py-0.5 text-gray-500">
                      +{(rt.fields?.length ?? 0) - 5} more
                    </span>
                  )}
                  {(rt.fields?.length ?? 0) === 0 && (
                    <span className="text-xs text-gray-600">No columns yet</span>
                  )}
                </div>
                <div className="mt-auto pt-4 flex items-center gap-3 text-xs text-gray-500">
                  <span>{rt.record_count ?? 0} records</span>
                  {rt.auto_extract && (
                    <span className="inline-flex items-center gap-1 text-indigo-400">
                      <Sparkles className="h-3 w-3" /> Auto-capture
                    </span>
                  )}
                  {!rt.is_active && <span className="text-amber-500">Inactive</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showModal && accountId && (
        <RecordTypeModal
          accountId={accountId}
          recordType={editing}
          onClose={() => {
            setShowModal(false);
            setEditing(null);
          }}
          onSaved={() => {
            setShowModal(false);
            setEditing(null);
            fetchTypes();
          }}
        />
      )}
    </div>
  );
}
