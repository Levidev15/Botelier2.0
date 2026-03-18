"use client";

import { useState, useEffect } from "react";
import { X, Mail, Shield, Copy, CheckCircle, Link } from "lucide-react";
import { toast } from "sonner";

interface Role {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  is_system_role: boolean;
  permissions: Record<string, Record<string, boolean>>;
  member_count: number;
}

interface InviteMemberModalProps {
  accountId: string;
  roles: Role[];
  onClose: () => void;
  onSuccess: () => void;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
}

export default function InviteMemberModal({
  accountId,
  roles,
  onClose,
  onSuccess,
  authFetch,
}: InviteMemberModalProps) {
  const [email, setEmail] = useState("");
  const [roleId, setRoleId] = useState("");
  const [loading, setLoading] = useState(false);
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const adminRole = roles.find((r) => r.slug === "account_admin");
    const staffRole = roles.find((r) => r.slug === "staff");
    setRoleId(staffRole?.id || adminRole?.id || roles[0]?.id || "");
  }, [roles]);

  const selectedRole = roles.find((r) => r.id === roleId);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !roleId) return;

    setLoading(true);
    try {
      const res = await authFetch(
        `/api/accounts/${accountId}/team/invitations`,
        {
          method: "POST",
          body: JSON.stringify({ email, role_id: roleId }),
        }
      );

      const data = await res.json();

      if (!res.ok) {
        toast.error(data.detail || "Failed to create invitation");
        return;
      }

      const baseUrl = window.location.origin;
      setInviteLink(`${baseUrl}/invite/${data.token}`);
      onSuccess();
    } catch {
      toast.error("Failed to create invitation");
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = async () => {
    if (!inviteLink) return;
    try {
      await navigator.clipboard.writeText(inviteLink);
      setCopied(true);
      toast.success("Invite link copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Failed to copy link");
    }
  };

  const handleDone = () => {
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[#111111] border border-[#222222] rounded-xl w-full max-w-md mx-4 shadow-2xl">
        <div className="flex items-center justify-between p-6 border-b border-[#222222]">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-blue-600/10 rounded-lg flex items-center justify-center">
              <Mail className="w-4 h-4 text-blue-400" />
            </div>
            <h2 className="text-lg font-semibold text-white">Invite Member</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md hover:bg-[#222222] text-gray-400 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {inviteLink ? (
          <div className="p-6">
            <div className="text-center mb-6">
              <div className="w-14 h-14 bg-green-900/20 rounded-full flex items-center justify-center mx-auto mb-3">
                <CheckCircle className="w-7 h-7 text-green-400" />
              </div>
              <h3 className="text-white font-semibold mb-1">Invitation Created</h3>
              <p className="text-gray-400 text-sm">
                Share this link with <span className="text-white">{email}</span> — it expires in 7 days.
              </p>
            </div>

            <div className="bg-[#0a0a0a] border border-[#333333] rounded-lg p-3 mb-4">
              <div className="flex items-center gap-2 mb-2">
                <Link className="w-3 h-3 text-gray-500 flex-shrink-0" />
                <span className="text-xs text-gray-500">Invite link</span>
              </div>
              <p className="text-sm text-gray-300 break-all font-mono">{inviteLink}</p>
            </div>

            <button
              onClick={handleCopy}
              className={`w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg font-medium text-sm transition-colors mb-3 ${
                copied
                  ? "bg-green-600/20 text-green-400 border border-green-600/30"
                  : "bg-blue-600 hover:bg-blue-700 text-white"
              }`}
            >
              {copied ? (
                <>
                  <CheckCircle className="w-4 h-4" />
                  Copied!
                </>
              ) : (
                <>
                  <Copy className="w-4 h-4" />
                  Copy Link
                </>
              )}
            </button>

            <button
              onClick={handleDone}
              className="w-full px-4 py-2.5 bg-[#1a1a1a] hover:bg-[#222222] text-gray-300 rounded-lg font-medium text-sm transition-colors"
            >
              Done
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="p-6 space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1.5">
                Email address
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  placeholder="colleague@company.com"
                  className="w-full pl-10 pr-4 py-2.5 bg-[#0a0a0a] border border-[#333333] rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 text-sm"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1.5">
                Role
              </label>
              <div className="relative">
                <Shield className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                <select
                  value={roleId}
                  onChange={(e) => setRoleId(e.target.value)}
                  required
                  className="w-full pl-10 pr-4 py-2.5 bg-[#0a0a0a] border border-[#333333] rounded-lg text-white focus:outline-none focus:border-blue-500 text-sm appearance-none"
                >
                  {roles.map((role) => (
                    <option key={role.id} value={role.id}>
                      {role.name}
                    </option>
                  ))}
                </select>
              </div>

              {selectedRole && (
                <div className="mt-2 p-3 bg-[#0a0a0a] border border-[#222222] rounded-lg">
                  <p className="text-xs text-gray-400">
                    {selectedRole.description || "No description"}
                  </p>
                  {selectedRole.is_system_role && (
                    <span className="inline-block mt-1.5 px-2 py-0.5 text-xs bg-[#1a1a1a] text-gray-500 rounded">
                      System role
                    </span>
                  )}
                </div>
              )}
            </div>

            <div className="pt-2 flex gap-3">
              <button
                type="button"
                onClick={onClose}
                className="flex-1 px-4 py-2.5 bg-[#1a1a1a] hover:bg-[#222222] text-gray-300 rounded-lg font-medium text-sm transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={loading || !email || !roleId}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 disabled:cursor-not-allowed text-white rounded-lg font-medium text-sm transition-colors"
              >
                {loading ? (
                  <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
                ) : (
                  "Generate Invite Link"
                )}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
