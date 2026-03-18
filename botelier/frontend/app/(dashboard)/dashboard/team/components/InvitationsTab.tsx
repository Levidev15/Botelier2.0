"use client";

import { useState } from "react";
import { Copy, CheckCircle, XCircle, Clock, Loader2, Mail, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

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

interface InvitationsTabProps {
  accountId: string;
  invitations: Invitation[];
  loading: boolean;
  onRefresh: () => void;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
}

function getStatusBadge(status: string, expiresAt: string) {
  const isExpiringSoon =
    status === "pending" &&
    new Date(expiresAt).getTime() - Date.now() < 24 * 60 * 60 * 1000;

  switch (status) {
    case "pending":
      return (
        <span
          className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border ${
            isExpiringSoon
              ? "text-orange-400 bg-orange-600/10 border-orange-600/20"
              : "text-blue-400 bg-blue-600/10 border-blue-600/20"
          }`}
        >
          {isExpiringSoon ? (
            <AlertTriangle className="w-2.5 h-2.5" />
          ) : (
            <Clock className="w-2.5 h-2.5" />
          )}
          {isExpiringSoon ? "Expiring soon" : "Pending"}
        </span>
      );
    case "accepted":
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border text-green-400 bg-green-600/10 border-green-600/20">
          <CheckCircle className="w-2.5 h-2.5" />
          Accepted
        </span>
      );
    case "revoked":
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border text-red-400 bg-red-600/10 border-red-600/20">
          <XCircle className="w-2.5 h-2.5" />
          Revoked
        </span>
      );
    case "expired":
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border text-gray-400 bg-gray-600/10 border-gray-600/20">
          <Clock className="w-2.5 h-2.5" />
          Expired
        </span>
      );
    default:
      return null;
  }
}

function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function InvitationsTab({
  accountId,
  invitations,
  loading,
  onRefresh,
  authFetch,
}: InvitationsTabProps) {
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [confirmRevokeId, setConfirmRevokeId] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const pendingInvitations = invitations.filter((inv) => inv.status === "pending");
  const displayedInvitations = showAll ? invitations : pendingInvitations;

  const handleCopyLink = async (invitation: Invitation) => {
    const link = `${window.location.origin}/invite/${invitation.token}`;
    try {
      await navigator.clipboard.writeText(link);
      setCopiedId(invitation.id);
      toast.success("Invite link copied");
      setTimeout(() => setCopiedId(null), 2000);
    } catch {
      toast.error("Failed to copy link");
    }
  };

  const handleRevoke = async (invitationId: string) => {
    setRevokingId(invitationId);
    try {
      const res = await authFetch(
        `/api/accounts/${accountId}/team/invitations/${invitationId}`,
        { method: "DELETE" }
      );
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || "Failed to revoke invitation");
        return;
      }
      toast.success("Invitation revoked");
      onRefresh();
      setConfirmRevokeId(null);
    } catch {
      toast.error("Failed to revoke invitation");
    } finally {
      setRevokingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
      </div>
    );
  }

  if (pendingInvitations.length === 0 && !showAll) {
    return (
      <div className="text-center py-16">
        <div className="w-12 h-12 bg-[#1a1a1a] rounded-full flex items-center justify-center mx-auto mb-3">
          <Mail className="w-5 h-5 text-gray-600" />
        </div>
        <p className="text-gray-400 font-medium">No pending invitations</p>
        <p className="text-gray-600 text-sm mt-1">Invite team members using the button above</p>
        {invitations.length > 0 && (
          <button
            onClick={() => setShowAll(true)}
            className="mt-3 text-xs text-gray-500 hover:text-gray-300 underline transition-colors"
          >
            View all invitation history ({invitations.length})
          </button>
        )}
      </div>
    );
  }

  const confirmingInvitation = invitations.find((inv) => inv.id === confirmRevokeId);

  return (
    <>
      <div className="flex items-center justify-between mb-4">
        <p className="text-xs text-gray-500">
          {showAll
            ? `${invitations.length} total invitation${invitations.length !== 1 ? "s" : ""}`
            : `${pendingInvitations.length} pending invitation${pendingInvitations.length !== 1 ? "s" : ""}`}
        </p>
        {invitations.length !== pendingInvitations.length && (
          <button
            onClick={() => setShowAll((v) => !v)}
            className="text-xs text-gray-500 hover:text-gray-300 underline transition-colors"
          >
            {showAll ? "Show pending only" : `View all history (${invitations.length})`}
          </button>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[#1a1a1a]">
              <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider pb-3 pr-4">
                Invitee
              </th>
              <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider pb-3 pr-4">
                Role
              </th>
              <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider pb-3 pr-4">
                Status
              </th>
              <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider pb-3 pr-4">
                Expires
              </th>
              <th className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider pb-3">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#1a1a1a]">
            {displayedInvitations.map((invitation) => (
              <tr key={invitation.id} className="group">
                <td className="py-3.5 pr-4">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 bg-[#1a1a1a] border border-[#333333] rounded-full flex items-center justify-center">
                      <Mail className="w-3.5 h-3.5 text-gray-500" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm text-white truncate">{invitation.invitee_email}</p>
                      <p className="text-xs text-gray-500">
                        Invited by {invitation.invited_by_name}
                      </p>
                    </div>
                  </div>
                </td>
                <td className="py-3.5 pr-4">
                  <span className="text-sm text-gray-300">{invitation.role_name}</span>
                </td>
                <td className="py-3.5 pr-4">
                  {getStatusBadge(invitation.status, invitation.expires_at)}
                </td>
                <td className="py-3.5 pr-4">
                  <span
                    className={`text-sm ${
                      invitation.status === "pending" &&
                      new Date(invitation.expires_at).getTime() - Date.now() < 24 * 60 * 60 * 1000
                        ? "text-orange-400"
                        : "text-gray-500"
                    }`}
                  >
                    {formatDate(invitation.expires_at)}
                  </span>
                </td>
                <td className="py-3.5">
                  <div className="flex items-center gap-2">
                    {invitation.status === "pending" && (
                      <>
                        <button
                          onClick={() => handleCopyLink(invitation)}
                          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors ${
                            copiedId === invitation.id
                              ? "bg-green-600/10 text-green-400"
                              : "bg-[#1a1a1a] hover:bg-[#222222] text-gray-400 hover:text-white"
                          }`}
                        >
                          {copiedId === invitation.id ? (
                            <CheckCircle className="w-3 h-3" />
                          ) : (
                            <Copy className="w-3 h-3" />
                          )}
                          {copiedId === invitation.id ? "Copied" : "Copy Link"}
                        </button>

                        <button
                          onClick={() => setConfirmRevokeId(invitation.id)}
                          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium bg-[#1a1a1a] hover:bg-red-900/20 text-gray-500 hover:text-red-400 transition-colors"
                        >
                          <XCircle className="w-3 h-3" />
                          Revoke
                        </button>
                      </>
                    )}
                    {invitation.status === "accepted" && invitation.accepted_at && (
                      <span className="text-xs text-gray-500">
                        Accepted {formatDate(invitation.accepted_at)}
                      </span>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {confirmingInvitation && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-[#111111] border border-[#222222] rounded-xl w-full max-w-sm mx-4 shadow-2xl p-6">
            <div className="w-10 h-10 bg-red-900/20 rounded-full flex items-center justify-center mx-auto mb-4">
              <XCircle className="w-5 h-5 text-red-400" />
            </div>
            <h3 className="text-white font-semibold text-center mb-2">Revoke Invitation</h3>
            <p className="text-gray-400 text-sm text-center mb-6">
              Revoke the invitation for{" "}
              <span className="text-white font-medium">
                {confirmingInvitation.invitee_email}
              </span>
              ? The link will no longer work.
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setConfirmRevokeId(null)}
                className="flex-1 px-4 py-2.5 bg-[#1a1a1a] hover:bg-[#222222] text-gray-300 rounded-lg font-medium text-sm transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleRevoke(confirmingInvitation.id)}
                disabled={revokingId === confirmingInvitation.id}
                className="flex-1 px-4 py-2.5 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded-lg font-medium text-sm transition-colors flex items-center justify-center"
              >
                {revokingId === confirmingInvitation.id ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  "Revoke"
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
