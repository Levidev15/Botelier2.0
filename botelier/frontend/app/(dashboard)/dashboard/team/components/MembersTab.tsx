"use client";

import { useState } from "react";
import { Crown, MoreHorizontal, UserMinus, Shield, Loader2 } from "lucide-react";
import { toast } from "sonner";
import ChangeRoleModal from "./ChangeRoleModal";

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
  user_id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  display_name: string;
  profile_image_url: string | null;
  role_id: string;
  role_name: string;
  role_slug: string;
  is_owner: boolean;
  accepted_at: string | null;
  created_at: string;
}

interface MembersTabProps {
  accountId: string;
  members: Member[];
  roles: Role[];
  loading: boolean;
  onRefresh: () => void;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
  currentUserId?: string;
}

const ROLE_COLORS: Record<string, string> = {
  account_admin: "text-purple-400 bg-purple-600/10 border-purple-600/20",
  staff: "text-blue-400 bg-blue-600/10 border-blue-600/20",
  viewer: "text-gray-400 bg-gray-600/10 border-gray-600/20",
};

function getRoleColor(slug: string): string {
  return ROLE_COLORS[slug] || "text-green-400 bg-green-600/10 border-green-600/20";
}

function getInitials(member: Member): string {
  if (member.first_name && member.last_name) {
    return `${member.first_name[0]}${member.last_name[0]}`.toUpperCase();
  }
  if (member.first_name) return member.first_name[0].toUpperCase();
  return member.email[0].toUpperCase();
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export default function MembersTab({
  accountId,
  members,
  roles,
  loading,
  onRefresh,
  authFetch,
  currentUserId,
}: MembersTabProps) {
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [changeRoleMember, setChangeRoleMember] = useState<Member | null>(null);
  const [confirmRemoveMember, setConfirmRemoveMember] = useState<Member | null>(null);
  const [removing, setRemoving] = useState(false);

  const handleRemove = async (member: Member) => {
    setRemoving(true);
    try {
      const res = await authFetch(
        `/api/accounts/${accountId}/team/members/${member.membership_id}`,
        { method: "DELETE" }
      );
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || "Failed to remove member");
        return;
      }
      toast.success(`${member.display_name} has been removed`);
      onRefresh();
      setConfirmRemoveMember(null);
    } catch {
      toast.error("Failed to remove member");
    } finally {
      setRemoving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
      </div>
    );
  }

  if (members.length === 0) {
    return (
      <div className="text-center py-16">
        <div className="w-12 h-12 bg-[#1a1a1a] rounded-full flex items-center justify-center mx-auto mb-3">
          <Shield className="w-5 h-5 text-gray-600" />
        </div>
        <p className="text-gray-400 font-medium">No members yet</p>
        <p className="text-gray-600 text-sm mt-1">Invite team members using the button above</p>
      </div>
    );
  }

  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[#1a1a1a]">
              <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider pb-3 pr-4">Member</th>
              <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider pb-3 pr-4">Role</th>
              <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider pb-3 pr-4">Joined</th>
              <th className="w-10 pb-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#1a1a1a]">
            {members.map((member) => (
              <tr key={member.membership_id} className="group">
                <td className="py-3.5 pr-4">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 bg-blue-600 rounded-full flex items-center justify-center text-xs font-semibold text-white flex-shrink-0">
                      {getInitials(member)}
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium text-white truncate">
                          {member.display_name}
                        </p>
                        {member.is_owner && (
                          <Crown className="w-3 h-3 text-yellow-400 flex-shrink-0" />
                        )}
                        {currentUserId && member.user_id === currentUserId && (
                          <span className="text-xs text-gray-500">(you)</span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500 truncate">{member.email}</p>
                    </div>
                  </div>
                </td>
                <td className="py-3.5 pr-4">
                  <span
                    className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${getRoleColor(member.role_slug)}`}
                  >
                    {member.role_name}
                  </span>
                </td>
                <td className="py-3.5 pr-4">
                  <span className="text-sm text-gray-500">
                    {formatDate(member.accepted_at || member.created_at)}
                  </span>
                </td>
                <td className="py-3.5 relative">
                  {!member.is_owner && !(currentUserId && member.user_id === currentUserId) && (
                    <div className="relative">
                      <button
                        onClick={() =>
                          setOpenMenuId(openMenuId === member.membership_id ? null : member.membership_id)
                        }
                        className="p-1.5 rounded-md hover:bg-[#222222] text-gray-600 hover:text-gray-300 transition-colors opacity-0 group-hover:opacity-100"
                      >
                        <MoreHorizontal className="w-4 h-4" />
                      </button>

                      {openMenuId === member.membership_id && (
                        <>
                          <div
                            className="fixed inset-0 z-10"
                            onClick={() => setOpenMenuId(null)}
                          />
                          <div className="absolute right-0 top-8 z-20 bg-[#1a1a1a] border border-[#333333] rounded-lg shadow-xl overflow-hidden w-40">
                            <button
                              onClick={() => {
                                setChangeRoleMember(member);
                                setOpenMenuId(null);
                              }}
                              className="flex items-center gap-2 w-full px-3 py-2 text-sm text-gray-300 hover:bg-[#222222] hover:text-white transition-colors"
                            >
                              <Shield className="w-3.5 h-3.5" />
                              Change Role
                            </button>
                            <button
                              onClick={() => {
                                setConfirmRemoveMember(member);
                                setOpenMenuId(null);
                              }}
                              className="flex items-center gap-2 w-full px-3 py-2 text-sm text-red-400 hover:bg-red-900/20 hover:text-red-300 transition-colors"
                            >
                              <UserMinus className="w-3.5 h-3.5" />
                              Remove
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {changeRoleMember && (
        <ChangeRoleModal
          accountId={accountId}
          member={changeRoleMember}
          roles={roles}
          onClose={() => setChangeRoleMember(null)}
          onSuccess={onRefresh}
          authFetch={authFetch}
        />
      )}

      {confirmRemoveMember && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-[#111111] border border-[#222222] rounded-xl w-full max-w-sm mx-4 shadow-2xl p-6">
            <div className="w-10 h-10 bg-red-900/20 rounded-full flex items-center justify-center mx-auto mb-4">
              <UserMinus className="w-5 h-5 text-red-400" />
            </div>
            <h3 className="text-white font-semibold text-center mb-2">Remove Member</h3>
            <p className="text-gray-400 text-sm text-center mb-6">
              Are you sure you want to remove{" "}
              <span className="text-white font-medium">{confirmRemoveMember.display_name}</span>{" "}
              from this account? They will lose all access.
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setConfirmRemoveMember(null)}
                className="flex-1 px-4 py-2.5 bg-[#1a1a1a] hover:bg-[#222222] text-gray-300 rounded-lg font-medium text-sm transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleRemove(confirmRemoveMember)}
                disabled={removing}
                className="flex-1 px-4 py-2.5 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded-lg font-medium text-sm transition-colors flex items-center justify-center"
              >
                {removing ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  "Remove"
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
