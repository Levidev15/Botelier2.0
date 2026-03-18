"use client";

import { useState, useEffect, useCallback } from "react";
import { Users, Mail, Shield, Plus, RefreshCw } from "lucide-react";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { usePagePermission, AccessDeniedPage } from "@/components/ui/PermissionGate";
import { usePermissions } from "@/lib/auth/usePermissions";
import MembersTab from "./components/MembersTab";
import InvitationsTab from "./components/InvitationsTab";
import RolesTab from "./components/RolesTab";
import InviteMemberModal from "./components/InviteMemberModal";

type Tab = "members" | "invitations" | "roles";

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

interface Invitation {
  id: string;
  invitee_email: string;
  role_id: string;
  role_name: string;
  invited_by_name: string;
  status: string;
  token: string;
  expires_at: string;
  accepted_at: string | null;
  created_at: string;
}

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

const TABS: { key: Tab; label: string; icon: typeof Users }[] = [
  { key: "members", label: "Members", icon: Users },
  { key: "invitations", label: "Pending Invitations", icon: Mail },
  { key: "roles", label: "Roles", icon: Shield },
];

export default function TeamPage() {
  const { accountId, loading: contextLoading } = useAccountContext();
  const { authFetch, user } = useAuthToken();
  const { hasAccess, loading: permLoading } = usePagePermission("team", "view");
  const { can, isPlatformAdmin } = usePermissions();

  const [activeTab, setActiveTab] = useState<Tab>("members");
  const [members, setMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);

  const [loadingMembers, setLoadingMembers] = useState(false);
  const [loadingInvitations, setLoadingInvitations] = useState(false);
  const [loadingRoles, setLoadingRoles] = useState(false);

  const [showInviteModal, setShowInviteModal] = useState(false);

  const fetchMembers = useCallback(async () => {
    if (!accountId) return;
    setLoadingMembers(true);
    try {
      const res = await authFetch(`/api/accounts/${accountId}/team/members`);
      if (res.ok) {
        const data = await res.json();
        setMembers(data);
      }
    } catch {
    } finally {
      setLoadingMembers(false);
    }
  }, [accountId, authFetch]);

  const fetchInvitations = useCallback(async () => {
    if (!accountId) return;
    setLoadingInvitations(true);
    try {
      const res = await authFetch(`/api/accounts/${accountId}/team/invitations`);
      if (res.ok) {
        const data = await res.json();
        setInvitations(data);
      }
    } catch {
    } finally {
      setLoadingInvitations(false);
    }
  }, [accountId, authFetch]);

  const fetchRoles = useCallback(async () => {
    if (!accountId) return;
    setLoadingRoles(true);
    try {
      const res = await authFetch(`/api/accounts/${accountId}/team/roles`);
      if (res.ok) {
        const data = await res.json();
        setRoles(data);
      }
    } catch {
    } finally {
      setLoadingRoles(false);
    }
  }, [accountId, authFetch]);

  const fetchAll = useCallback(() => {
    fetchMembers();
    fetchInvitations();
    fetchRoles();
  }, [fetchMembers, fetchInvitations, fetchRoles]);

  useEffect(() => {
    if (accountId) {
      fetchAll();
    }
  }, [accountId, fetchAll]);

  const pendingCount = invitations.filter((inv) => inv.status === "pending").length;

  const canInvite = isPlatformAdmin || can("team", "invite");
  const canManageRoles = isPlatformAdmin || can("team", "manage_roles");

  if (contextLoading || permLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="animate-spin h-6 w-6 border-2 border-blue-500 border-t-transparent rounded-full" />
      </div>
    );
  }

  if (!hasAccess) {
    return <AccessDeniedPage message="You don't have permission to view team members." />;
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Team</h1>
          <p className="text-sm text-gray-400 mt-1">
            Manage members, invitations, and roles for your account
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={fetchAll}
            className="p-2 rounded-lg hover:bg-[#1a1a1a] text-gray-500 hover:text-gray-300 transition-colors"
            title="Refresh"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
          {canInvite && (
            <button
              onClick={() => setShowInviteModal(true)}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors"
            >
              <Plus className="w-4 h-4" />
              Invite Member
            </button>
          )}
        </div>
      </div>

      <div className="flex items-center gap-1 mb-6 border-b border-[#1a1a1a]">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors relative -mb-px ${
              activeTab === key
                ? "text-white border-blue-500"
                : "text-gray-500 hover:text-gray-300 border-transparent"
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
            {key === "members" && members.length > 0 && (
              <span className="ml-1 px-1.5 py-0.5 text-xs bg-[#1a1a1a] text-gray-400 rounded-full">
                {members.length}
              </span>
            )}
            {key === "invitations" && pendingCount > 0 && (
              <span className="ml-1 px-1.5 py-0.5 text-xs bg-blue-600/20 text-blue-400 rounded-full">
                {pendingCount}
              </span>
            )}
            {key === "roles" && roles.length > 0 && (
              <span className="ml-1 px-1.5 py-0.5 text-xs bg-[#1a1a1a] text-gray-400 rounded-full">
                {roles.length}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="bg-[#111111] border border-[#1a1a1a] rounded-xl p-6">
        {activeTab === "members" && (
          <MembersTab
            accountId={accountId}
            members={members}
            roles={roles}
            loading={loadingMembers}
            onRefresh={fetchMembers}
            authFetch={authFetch}
            currentUserId={user?.id}
          />
        )}

        {activeTab === "invitations" && (
          <InvitationsTab
            accountId={accountId}
            invitations={invitations}
            loading={loadingInvitations}
            onRefresh={fetchInvitations}
            authFetch={authFetch}
          />
        )}

        {activeTab === "roles" && (
          <RolesTab
            accountId={accountId}
            roles={roles}
            loading={loadingRoles}
            onRefresh={fetchRoles}
            authFetch={authFetch}
          />
        )}
      </div>

      {showInviteModal && (
        <InviteMemberModal
          accountId={accountId}
          roles={roles}
          onClose={() => setShowInviteModal(false)}
          onSuccess={() => {
            fetchInvitations();
          }}
          authFetch={authFetch}
        />
      )}
    </div>
  );
}
