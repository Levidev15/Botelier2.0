"use client";

import { useState } from "react";
import { Shield, Lock, Users, Edit3, Trash2, Plus, Loader2 } from "lucide-react";
import { toast } from "sonner";
import RoleEditorSlideOver from "./RoleEditorSlideOver";

interface Role {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  is_system_role: boolean;
  permissions: Record<string, Record<string, boolean>>;
  member_count: number;
  created_at: string;
}

interface RolesTabProps {
  accountId: string;
  roles: Role[];
  loading: boolean;
  onRefresh: () => void;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
}

function countPermissions(permissions: Record<string, Record<string, boolean>>): {
  enabled: number;
  total: number;
} {
  let enabled = 0;
  let total = 0;
  for (const feature of Object.values(permissions)) {
    for (const val of Object.values(feature)) {
      total++;
      if (val) enabled++;
    }
  }
  return { enabled, total };
}

const ROLE_BADGE_COLORS: Record<string, string> = {
  account_admin: "text-purple-400 bg-purple-600/10 border-purple-600/30",
  staff: "text-blue-400 bg-blue-600/10 border-blue-600/30",
  viewer: "text-gray-400 bg-gray-600/10 border-gray-600/30",
};

function getRoleBadgeColor(slug: string): string {
  return ROLE_BADGE_COLORS[slug] || "text-green-400 bg-green-600/10 border-green-600/30";
}

export default function RolesTab({
  accountId,
  roles,
  loading,
  onRefresh,
  authFetch,
}: RolesTabProps) {
  const [editRole, setEditRole] = useState<Role | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteRole, setConfirmDeleteRole] = useState<Role | null>(null);

  const handleDelete = async (role: Role) => {
    setDeletingId(role.id);
    try {
      const res = await authFetch(
        `/api/accounts/${accountId}/team/roles/${role.id}`,
        { method: "DELETE" }
      );
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || "Failed to delete role");
        return;
      }
      toast.success(`Role "${role.name}" deleted`);
      onRefresh();
      setConfirmDeleteRole(null);
    } catch {
      toast.error("Failed to delete role");
    } finally {
      setDeletingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
      </div>
    );
  }

  const systemRoles = roles.filter((r) => r.is_system_role);
  const customRoles = roles.filter((r) => !r.is_system_role);

  return (
    <>
      <div className="space-y-6">
        <div>
          <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
            System Roles
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {systemRoles.map((role) => {
              const { enabled, total } = countPermissions(role.permissions);
              return (
                <div
                  key={role.id}
                  className="bg-[#0d0d0d] border border-[#222222] rounded-xl p-4"
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-2.5">
                      <div className="w-8 h-8 bg-[#1a1a1a] rounded-lg flex items-center justify-center">
                        <Shield className="w-4 h-4 text-gray-400" />
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-white">{role.name}</p>
                        <span
                          className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-xs rounded border mt-0.5 ${getRoleBadgeColor(role.slug)}`}
                        >
                          <Lock className="w-2.5 h-2.5" />
                          System
                        </span>
                      </div>
                    </div>
                  </div>

                  {role.description && (
                    <p className="text-xs text-gray-400 mb-3 leading-relaxed">
                      {role.description}
                    </p>
                  )}

                  <div className="flex items-center justify-between text-xs text-gray-500">
                    <div className="flex items-center gap-1">
                      <Users className="w-3 h-3" />
                      {role.member_count} member{role.member_count !== 1 ? "s" : ""}
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="w-16 h-1 bg-[#333333] rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gray-500 rounded-full"
                          style={{ width: total > 0 ? `${(enabled / total) * 100}%` : "0%" }}
                        />
                      </div>
                      <span>{enabled}/{total}</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider">
              Custom Roles
            </h3>
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-[#1a1a1a] hover:bg-[#222222] text-gray-300 hover:text-white border border-[#333333] rounded-lg text-xs font-medium transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              Add Custom Role
            </button>
          </div>

          {customRoles.length === 0 ? (
            <div className="border border-dashed border-[#333333] rounded-xl p-8 text-center">
              <div className="w-10 h-10 bg-[#1a1a1a] rounded-full flex items-center justify-center mx-auto mb-3">
                <Shield className="w-4 h-4 text-gray-600" />
              </div>
              <p className="text-gray-500 text-sm">No custom roles yet</p>
              <p className="text-gray-600 text-xs mt-1">
                Create roles tailored to your team's workflow
              </p>
              <button
                onClick={() => setShowCreate(true)}
                className="mt-4 inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-600/10 hover:bg-blue-600/20 text-blue-400 border border-blue-600/20 rounded-lg text-xs font-medium transition-colors"
              >
                <Plus className="w-3.5 h-3.5" />
                Create First Custom Role
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {customRoles.map((role) => {
                const { enabled, total } = countPermissions(role.permissions);
                return (
                  <div
                    key={role.id}
                    className="bg-[#0d0d0d] border border-[#222222] hover:border-[#333333] rounded-xl p-4 transition-colors"
                  >
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 bg-green-600/10 border border-green-600/20 rounded-lg flex items-center justify-center">
                          <Shield className="w-4 h-4 text-green-400" />
                        </div>
                        <div>
                          <p className="text-sm font-semibold text-white">{role.name}</p>
                          <span className="inline-flex items-center px-1.5 py-0.5 text-xs rounded border text-green-400 bg-green-600/10 border-green-600/30 mt-0.5">
                            Custom
                          </span>
                        </div>
                      </div>

                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => setEditRole(role)}
                          className="p-1.5 rounded-md hover:bg-[#222222] text-gray-500 hover:text-gray-300 transition-colors"
                          title="Edit role"
                        >
                          <Edit3 className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => setConfirmDeleteRole(role)}
                          className="p-1.5 rounded-md hover:bg-red-900/20 text-gray-500 hover:text-red-400 transition-colors"
                          title="Delete role"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>

                    {role.description && (
                      <p className="text-xs text-gray-400 mb-3 leading-relaxed">
                        {role.description}
                      </p>
                    )}

                    <div className="flex items-center justify-between text-xs text-gray-500">
                      <div className="flex items-center gap-1">
                        <Users className="w-3 h-3" />
                        {role.member_count} member{role.member_count !== 1 ? "s" : ""}
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1 bg-[#333333] rounded-full overflow-hidden">
                          <div
                            className="h-full bg-blue-500 rounded-full"
                            style={{ width: total > 0 ? `${(enabled / total) * 100}%` : "0%" }}
                          />
                        </div>
                        <span>{enabled}/{total} perms</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {(editRole || showCreate) && (
        <RoleEditorSlideOver
          accountId={accountId}
          role={editRole || undefined}
          onClose={() => {
            setEditRole(null);
            setShowCreate(false);
          }}
          onSuccess={() => {
            onRefresh();
            setEditRole(null);
            setShowCreate(false);
          }}
          authFetch={authFetch}
        />
      )}

      {confirmDeleteRole && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-[#111111] border border-[#222222] rounded-xl w-full max-w-sm mx-4 shadow-2xl p-6">
            <div className="w-10 h-10 bg-red-900/20 rounded-full flex items-center justify-center mx-auto mb-4">
              <Trash2 className="w-5 h-5 text-red-400" />
            </div>
            <h3 className="text-white font-semibold text-center mb-2">Delete Role</h3>
            <p className="text-gray-400 text-sm text-center mb-6">
              Delete the role{" "}
              <span className="text-white font-medium">"{confirmDeleteRole.name}"</span>?
              {confirmDeleteRole.member_count > 0 && (
                <span className="block mt-1 text-orange-400">
                  {confirmDeleteRole.member_count} member(s) use this role — reassign them first.
                </span>
              )}
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setConfirmDeleteRole(null)}
                className="flex-1 px-4 py-2.5 bg-[#1a1a1a] hover:bg-[#222222] text-gray-300 rounded-lg font-medium text-sm transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDelete(confirmDeleteRole)}
                disabled={deletingId === confirmDeleteRole.id || confirmDeleteRole.member_count > 0}
                className="flex-1 px-4 py-2.5 bg-red-600 hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg font-medium text-sm transition-colors flex items-center justify-center"
              >
                {deletingId === confirmDeleteRole.id ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  "Delete"
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
