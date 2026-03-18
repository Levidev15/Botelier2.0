"use client";

import { useState } from "react";
import { X, Shield, ChevronDown } from "lucide-react";
import { toast } from "sonner";

interface Role {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  is_system_role: boolean;
  member_count: number;
}

interface Member {
  membership_id: string;
  display_name: string;
  email: string;
  role_id: string;
  role_name: string;
}

interface ChangeRoleModalProps {
  accountId: string;
  member: Member;
  roles: Role[];
  onClose: () => void;
  onSuccess: () => void;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
}

export default function ChangeRoleModal({
  accountId,
  member,
  roles,
  onClose,
  onSuccess,
  authFetch,
}: ChangeRoleModalProps) {
  const [selectedRoleId, setSelectedRoleId] = useState(member.role_id);
  const [loading, setLoading] = useState(false);

  const selectedRole = roles.find((r) => r.id === selectedRoleId);
  const hasChanged = selectedRoleId !== member.role_id;

  const handleSubmit = async () => {
    if (!hasChanged) return;

    setLoading(true);
    try {
      const res = await authFetch(
        `/api/accounts/${accountId}/team/members/${member.membership_id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ role_id: selectedRoleId }),
        }
      );

      const data = await res.json();

      if (!res.ok) {
        toast.error(data.detail || "Failed to update role");
        return;
      }

      toast.success(`Role updated to ${selectedRole?.name}`);
      onSuccess();
      onClose();
    } catch {
      toast.error("Failed to update role");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[#111111] border border-[#222222] rounded-xl w-full max-w-sm mx-4 shadow-2xl">
        <div className="flex items-center justify-between p-5 border-b border-[#222222]">
          <h2 className="text-base font-semibold text-white">Change Role</h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md hover:bg-[#222222] text-gray-400 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <div className="flex items-center gap-3 p-3 bg-[#0a0a0a] rounded-lg border border-[#222222]">
            <div className="w-8 h-8 bg-blue-600 rounded-full flex items-center justify-center text-xs font-semibold text-white flex-shrink-0">
              {member.display_name.charAt(0).toUpperCase()}
            </div>
            <div className="min-w-0">
              <p className="text-sm font-medium text-white truncate">{member.display_name}</p>
              <p className="text-xs text-gray-400 truncate">{member.email}</p>
            </div>
            <span className="ml-auto px-2 py-0.5 text-xs bg-[#1a1a1a] text-gray-400 rounded border border-[#333333] flex-shrink-0">
              {member.role_name}
            </span>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-400 mb-2">
              New Role
            </label>
            <div className="space-y-2">
              {roles.map((role) => (
                <button
                  key={role.id}
                  type="button"
                  onClick={() => setSelectedRoleId(role.id)}
                  className={`w-full text-left p-3 rounded-lg border transition-colors ${
                    selectedRoleId === role.id
                      ? "border-blue-500 bg-blue-600/10"
                      : "border-[#333333] hover:border-[#444444] bg-[#0a0a0a]"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <div
                      className={`w-4 h-4 rounded-full border-2 flex-shrink-0 flex items-center justify-center ${
                        selectedRoleId === role.id
                          ? "border-blue-500"
                          : "border-gray-600"
                      }`}
                    >
                      {selectedRoleId === role.id && (
                        <div className="w-2 h-2 bg-blue-500 rounded-full" />
                      )}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-white">{role.name}</p>
                      {role.description && (
                        <p className="text-xs text-gray-500 mt-0.5">{role.description}</p>
                      )}
                    </div>
                    {role.is_system_role && (
                      <Shield className="w-3 h-3 text-gray-600 ml-auto" />
                    )}
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="flex gap-3 pt-2">
            <button
              onClick={onClose}
              className="flex-1 px-4 py-2.5 bg-[#1a1a1a] hover:bg-[#222222] text-gray-300 rounded-lg font-medium text-sm transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={loading || !hasChanged}
              className="flex-1 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/40 disabled:cursor-not-allowed text-white rounded-lg font-medium text-sm transition-colors flex items-center justify-center"
            >
              {loading ? (
                <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
              ) : (
                "Update Role"
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
