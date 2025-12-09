"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Mail,
  Plus,
  Search,
  Send,
  X,
  Clock,
  CheckCircle,
  XCircle,
  Copy,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface Invitation {
  id: string;
  account_id: string;
  account_name: string;
  invitee_email: string;
  role_id: string;
  role_name: string;
  invited_by_id: string;
  invited_by_name: string;
  status: string;
  token: string;
  expires_at: string;
  accepted_at: string | null;
  created_at: string;
}

interface Account {
  id: string;
  name: string;
}

interface Role {
  id: string;
  name: string;
  slug: string;
}

interface InvitationListResponse {
  invitations: Invitation[];
  total: number;
  page: number;
  page_size: number;
}

export default function InvitationsPage() {
  const { token, user, loading: authLoading, authFetch } = useAuthToken();
  const router = useRouter();
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [creating, setCreating] = useState(false);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [newInvitation, setNewInvitation] = useState({
    account_id: "",
    email: "",
    role_id: "",
  });

  useEffect(() => {
    if (authLoading) return;
    
    if (!token) {
      router.push("/login?callbackUrl=/admin/invitations");
      return;
    }
    
    if (user?.user_type !== "platform_admin") {
      router.push("/dashboard");
      return;
    }
    
    fetchInvitations();
    fetchAccounts();
  }, [token, user, authLoading, page, statusFilter]);

  const fetchInvitations = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams({
        page: page.toString(),
        page_size: "20",
      });
      if (statusFilter) params.set("status", statusFilter);
      if (search) params.set("search", search);

      const res = await authFetch(`/api/admin/invitations?${params}`);
      if (res.ok) {
        const data: InvitationListResponse = await res.json();
        setInvitations(data.invitations);
        setTotal(data.total);
      }
    } catch (err) {
      console.error("Error fetching invitations:", err);
      toast.error("Failed to load invitations");
    } finally {
      setLoading(false);
    }
  };

  const fetchAccounts = async () => {
    try {
      const res = await authFetch("/api/admin/accounts?page_size=100");
      if (res.ok) {
        const data = await res.json();
        setAccounts(data.accounts || []);
      }
    } catch (err) {
      console.error("Error fetching accounts:", err);
    }
  };

  const fetchAccountRoles = async (accountId: string) => {
    if (!accountId) return;
    try {
      const res = await authFetch(`/api/admin/accounts/${accountId}/roles`);
      if (res.ok) {
        const data = await res.json();
        setRoles(data || []);
      }
    } catch (err) {
      console.error("Error fetching roles:", err);
    }
  };

  const handleAccountChange = (accountId: string) => {
    setNewInvitation({ ...newInvitation, account_id: accountId, role_id: "" });
    if (accountId) {
      fetchAccountRoles(accountId);
    } else {
      setRoles([]);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchInvitations();
  };

  const handleCreateInvitation = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newInvitation.account_id || !newInvitation.email || !newInvitation.role_id) {
      toast.error("Please fill in all fields");
      return;
    }

    setCreating(true);
    try {
      const res = await authFetch("/api/admin/invitations", {
        method: "POST",
        body: JSON.stringify(newInvitation),
      });

      if (res.ok) {
        const data = await res.json();
        toast.success(`Invitation created for ${data.invitee_email}`);
        setShowCreateModal(false);
        setNewInvitation({ account_id: "", email: "", role_id: "" });
        setRoles([]);
        fetchInvitations();
      } else {
        const error = await res.json();
        toast.error(error.detail || "Failed to create invitation");
      }
    } catch (err) {
      console.error("Error creating invitation:", err);
      toast.error("Failed to create invitation");
    } finally {
      setCreating(false);
    }
  };

  const handleResend = async (invitationId: string) => {
    try {
      const res = await authFetch(`/api/admin/invitations/${invitationId}/resend`, {
        method: "POST",
      });

      if (res.ok) {
        toast.success("Invitation resent successfully");
        fetchInvitations();
      } else {
        const error = await res.json();
        toast.error(error.detail || "Failed to resend invitation");
      }
    } catch (err) {
      console.error("Error resending invitation:", err);
      toast.error("Failed to resend invitation");
    }
  };

  const handleRevoke = async (invitationId: string) => {
    try {
      const res = await authFetch(`/api/admin/invitations/${invitationId}/revoke`, {
        method: "POST",
      });

      if (res.ok) {
        toast.success("Invitation revoked");
        fetchInvitations();
      } else {
        const error = await res.json();
        toast.error(error.detail || "Failed to revoke invitation");
      }
    } catch (err) {
      console.error("Error revoking invitation:", err);
      toast.error("Failed to revoke invitation");
    }
  };

  const copyInviteLink = (inviteToken: string) => {
    const link = `${window.location.origin}/invite/${inviteToken}`;
    navigator.clipboard.writeText(link);
    toast.success("Invite link copied to clipboard");
  };

  const getStatusBadge = (status: string, expiresAt: string) => {
    const isExpired = new Date(expiresAt) < new Date() && status === "pending";
    
    if (isExpired) {
      return (
        <span className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-gray-400 bg-gray-400/10 rounded-full border border-gray-600/30">
          <Clock className="w-3 h-3" />
          Expired
        </span>
      );
    }
    
    switch (status) {
      case "pending":
        return (
          <span className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-yellow-400 bg-yellow-400/10 rounded-full border border-yellow-600/30">
            <Clock className="w-3 h-3" />
            Pending
          </span>
        );
      case "accepted":
        return (
          <span className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-green-400 bg-green-400/10 rounded-full border border-green-600/30">
            <CheckCircle className="w-3 h-3" />
            Accepted
          </span>
        );
      case "revoked":
        return (
          <span className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-red-400 bg-red-400/10 rounded-full border border-red-600/30">
            <XCircle className="w-3 h-3" />
            Revoked
          </span>
        );
      default:
        return (
          <span className="px-2.5 py-1 text-xs font-medium text-gray-400 bg-gray-400/10 rounded-full">
            {status}
          </span>
        );
    }
  };

  if (authLoading) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full"></div>
      </div>
    );
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-white">Invitations</h1>
          <p className="text-gray-400 mt-1">
            Manage user invitations to accounts ({total} total)
          </p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" />
          Invite User
        </button>
      </div>

      <div className="flex flex-wrap gap-4 mb-6">
        <form onSubmit={handleSearch} className="flex-1 min-w-[300px]">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by email..."
              className="w-full pl-10 pr-4 py-2 bg-[#111111] border border-[#222222] rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
            />
          </div>
        </form>
        <select
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value);
            setPage(1);
          }}
          className="px-4 py-2 bg-[#111111] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-500"
        >
          <option value="">All Statuses</option>
          <option value="pending">Pending</option>
          <option value="accepted">Accepted</option>
          <option value="revoked">Revoked</option>
        </select>
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full"></div>
        </div>
      ) : invitations.length === 0 ? (
        <div className="bg-[#111111] border border-[#222222] rounded-xl p-12 text-center">
          <Mail className="w-12 h-12 text-gray-600 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-white mb-2">No invitations found</h3>
          <p className="text-gray-400 mb-6">
            {search || statusFilter
              ? "Try adjusting your filters"
              : "Get started by inviting users to accounts"}
          </p>
          {!search && !statusFilter && (
            <button
              onClick={() => setShowCreateModal(true)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
            >
              <Plus className="w-4 h-4" />
              Invite User
            </button>
          )}
        </div>
      ) : (
        <div className="bg-[#111111] border border-[#222222] rounded-xl overflow-hidden">
          <table className="w-full">
            <thead className="bg-[#0a0a0a] border-b border-[#222222]">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  Email
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  Account
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  Role
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  Created
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#222222]">
              {invitations.map((invitation) => (
                <tr key={invitation.id} className="hover:bg-[#1a1a1a] transition-colors">
                  <td className="px-6 py-4">
                    <span className="text-white font-medium">{invitation.invitee_email}</span>
                  </td>
                  <td className="px-6 py-4">
                    <span className="text-gray-300">{invitation.account_name}</span>
                  </td>
                  <td className="px-6 py-4">
                    <span className="text-gray-400">{invitation.role_name}</span>
                  </td>
                  <td className="px-6 py-4">
                    {getStatusBadge(invitation.status, invitation.expires_at)}
                  </td>
                  <td className="px-6 py-4">
                    <span className="text-gray-400 text-sm">
                      {new Date(invitation.created_at).toLocaleDateString()}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center justify-end gap-1">
                      {invitation.status === "pending" && (
                        <>
                          <button
                            onClick={() => copyInviteLink(invitation.token)}
                            className="p-2 text-gray-400 hover:text-white hover:bg-[#222222] rounded-lg transition-colors"
                            title="Copy invite link"
                          >
                            <Copy className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => handleResend(invitation.id)}
                            className="p-2 text-gray-400 hover:text-blue-400 hover:bg-blue-900/20 rounded-lg transition-colors"
                            title="Resend invitation"
                          >
                            <RefreshCw className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => handleRevoke(invitation.id)}
                            className="p-2 text-gray-400 hover:text-red-400 hover:bg-red-900/20 rounded-lg transition-colors"
                            title="Revoke invitation"
                          >
                            <XCircle className="w-4 h-4" />
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > 20 && (
        <div className="mt-4 flex items-center justify-between">
          <p className="text-gray-400 text-sm">
            Showing {(page - 1) * 20 + 1} to {Math.min(page * 20, total)} of {total}
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={page === 1}
              className="px-3 py-1 bg-[#111111] border border-[#222222] rounded text-gray-400 disabled:opacity-50 hover:border-[#333333] transition-colors"
            >
              Previous
            </button>
            <button
              onClick={() => setPage(page + 1)}
              disabled={page >= Math.ceil(total / 20)}
              className="px-3 py-1 bg-[#111111] border border-[#222222] rounded text-gray-400 disabled:opacity-50 hover:border-[#333333] transition-colors"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {showCreateModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-[#111111] border border-[#222222] rounded-xl p-6 w-full max-w-md mx-4">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-white">Invite User</h2>
              <button
                onClick={() => {
                  setShowCreateModal(false);
                  setNewInvitation({ account_id: "", email: "", role_id: "" });
                  setRoles([]);
                }}
                className="text-gray-400 hover:text-white p-1"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateInvitation} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1">
                  Account <span className="text-red-400">*</span>
                </label>
                <select
                  value={newInvitation.account_id}
                  onChange={(e) => handleAccountChange(e.target.value)}
                  required
                  className="w-full px-3 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="">Select an account</option>
                  {accounts.map((account) => (
                    <option key={account.id} value={account.id}>
                      {account.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1">
                  Email Address <span className="text-red-400">*</span>
                </label>
                <input
                  type="email"
                  value={newInvitation.email}
                  onChange={(e) =>
                    setNewInvitation({ ...newInvitation, email: e.target.value })
                  }
                  required
                  placeholder="user@example.com"
                  className="w-full px-3 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1">
                  Role <span className="text-red-400">*</span>
                </label>
                <select
                  value={newInvitation.role_id}
                  onChange={(e) =>
                    setNewInvitation({ ...newInvitation, role_id: e.target.value })
                  }
                  required
                  disabled={!newInvitation.account_id || roles.length === 0}
                  className="w-full px-3 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
                >
                  <option value="">
                    {!newInvitation.account_id
                      ? "Select an account first"
                      : roles.length === 0
                      ? "Loading roles..."
                      : "Select a role"}
                  </option>
                  {roles.map((role) => (
                    <option key={role.id} value={role.id}>
                      {role.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex gap-3 pt-4">
                <button
                  type="button"
                  onClick={() => {
                    setShowCreateModal(false);
                    setNewInvitation({ account_id: "", email: "", role_id: "" });
                    setRoles([]);
                  }}
                  className="flex-1 px-4 py-2 bg-[#1a1a1a] text-gray-300 rounded-lg hover:bg-[#222222] transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 text-white rounded-lg transition-colors"
                >
                  {creating ? "Creating..." : "Send Invitation"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
