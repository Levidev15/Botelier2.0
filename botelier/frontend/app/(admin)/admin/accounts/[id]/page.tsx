"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import {
  ArrowLeft,
  Building2,
  Phone,
  Users,
  Mail,
  Calendar,
  Edit,
  Save,
  X,
  Loader2,
  Shield,
  Plus,
} from "lucide-react";
import { toast } from "sonner";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface Account {
  id: string;
  name: string;
  slug: string;
  email: string;
  phone: string | null;
  business_type: string | null;
  status: string;
  subscription_tier: string;
  has_twilio: boolean;
  twilio_sub_account_sid: string | null;
  member_count: number;
  created_at: string;
}

interface Member {
  id: string;
  user_id: string;
  user_email: string;
  user_name: string;
  role_name: string;
  is_owner: boolean;
  joined_at: string;
}

export default function AccountDetailPage() {
  const { token, user, loading: authLoading, authFetch } = useAuthToken();
  const router = useRouter();
  const params = useParams();
  const accountId = params.id as string;

  const [account, setAccount] = useState<Account | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editForm, setEditForm] = useState({
    name: "",
    email: "",
    phone: "",
    business_type: "",
    status: "",
    subscription_tier: "",
  });

  useEffect(() => {
    if (authLoading) return;

    if (!token) {
      router.push("/login?callbackUrl=/admin/accounts");
      return;
    }

    if (user?.user_type !== "platform_admin") {
      router.push("/dashboard");
      return;
    }

    if (accountId) {
      fetchAccount();
    }
  }, [token, user, authLoading, accountId]);

  const fetchAccount = async () => {
    try {
      setLoading(true);
      const res = await authFetch(`/api/admin/accounts/${accountId}`);
      if (res.ok) {
        const data = await res.json();
        setAccount(data);
        setEditForm({
          name: data.name,
          email: data.email,
          phone: data.phone || "",
          business_type: data.business_type || "",
          status: data.status,
          subscription_tier: data.subscription_tier,
        });
      } else {
        toast.error("Account not found");
        router.push("/admin/accounts");
      }
    } catch (err) {
      console.error("Error fetching account:", err);
      toast.error("Failed to load account");
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await authFetch(`/api/admin/accounts/${accountId}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: editForm.name,
          email: editForm.email,
          phone: editForm.phone || null,
          business_type: editForm.business_type || null,
          status: editForm.status,
          subscription_tier: editForm.subscription_tier,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setAccount(data);
        setEditing(false);
        toast.success("Account updated successfully");
      } else {
        const error = await res.json();
        toast.error(error.detail || "Failed to update account");
      }
    } catch (err) {
      console.error("Error updating account:", err);
      toast.error("Failed to update account");
    } finally {
      setSaving(false);
    }
  };

  const handleProvisionTwilio = async () => {
    try {
      const res = await authFetch(`/api/admin/accounts/${accountId}/provision-twilio`, {
        method: "POST",
      });

      if (res.ok) {
        toast.success("Twilio sub-account provisioned successfully");
        fetchAccount();
      } else {
        const error = await res.json();
        toast.error(error.detail || "Failed to provision Twilio");
      }
    } catch (err) {
      console.error("Error provisioning Twilio:", err);
      toast.error("Failed to provision Twilio");
    }
  };

  const statusColors: Record<string, string> = {
    trial: "bg-yellow-600/20 text-yellow-400 border-yellow-600/30",
    active: "bg-green-600/20 text-green-400 border-green-600/30",
    suspended: "bg-red-600/20 text-red-400 border-red-600/30",
    cancelled: "bg-gray-600/20 text-gray-400 border-gray-600/30",
  };

  const tierColors: Record<string, string> = {
    free: "bg-gray-600/20 text-gray-400",
    starter: "bg-blue-600/20 text-blue-400",
    professional: "bg-purple-600/20 text-purple-400",
    enterprise: "bg-orange-600/20 text-orange-400",
  };

  if (authLoading || loading) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full"></div>
      </div>
    );
  }

  if (!account) {
    return (
      <div className="p-8">
        <p className="text-gray-400">Account not found</p>
      </div>
    );
  }

  return (
    <div className="p-8">
      <button
        onClick={() => router.push("/admin/accounts")}
        className="flex items-center gap-2 text-gray-400 hover:text-white mb-6 transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Accounts
      </button>

      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-white">{account.name}</h1>
          <p className="text-gray-400 mt-1">Account ID: {account.id}</p>
        </div>
        <div className="flex items-center gap-3">
          {!editing ? (
            <button
              onClick={() => setEditing(true)}
              className="flex items-center gap-2 px-4 py-2 bg-[#1a1a1a] hover:bg-[#222222] text-white rounded-lg transition-colors border border-[#333333]"
            >
              <Edit className="h-4 w-4" />
              Edit
            </button>
          ) : (
            <>
              <button
                onClick={() => {
                  setEditing(false);
                  setEditForm({
                    name: account.name,
                    email: account.email,
                    phone: account.phone || "",
                    business_type: account.business_type || "",
                    status: account.status,
                    subscription_tier: account.subscription_tier,
                  });
                }}
                className="flex items-center gap-2 px-4 py-2 text-gray-400 hover:text-white transition-colors"
              >
                <X className="h-4 w-4" />
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 text-white rounded-lg transition-colors"
              >
                {saving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Save className="h-4 w-4" />
                )}
                Save Changes
              </button>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-[#111111] border border-[#222222] rounded-xl p-6">
            <h2 className="text-lg font-semibold text-white mb-6">Account Details</h2>

            {editing ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">
                    Account Name
                  </label>
                  <input
                    type="text"
                    value={editForm.name}
                    onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                    className="w-full px-4 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-600"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">
                    Email
                  </label>
                  <input
                    type="email"
                    value={editForm.email}
                    onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                    className="w-full px-4 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-600"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">
                    Phone
                  </label>
                  <input
                    type="tel"
                    value={editForm.phone}
                    onChange={(e) => setEditForm({ ...editForm, phone: e.target.value })}
                    className="w-full px-4 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-600"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">
                    Business Type
                  </label>
                  <input
                    type="text"
                    value={editForm.business_type}
                    onChange={(e) => setEditForm({ ...editForm, business_type: e.target.value })}
                    className="w-full px-4 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-600"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">
                    Status
                  </label>
                  <select
                    value={editForm.status}
                    onChange={(e) => setEditForm({ ...editForm, status: e.target.value })}
                    className="w-full px-4 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-600"
                  >
                    <option value="trial">Trial</option>
                    <option value="active">Active</option>
                    <option value="suspended">Suspended</option>
                    <option value="cancelled">Cancelled</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">
                    Subscription Tier
                  </label>
                  <select
                    value={editForm.subscription_tier}
                    onChange={(e) => setEditForm({ ...editForm, subscription_tier: e.target.value })}
                    className="w-full px-4 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-600"
                  >
                    <option value="free">Free</option>
                    <option value="starter">Starter</option>
                    <option value="professional">Professional</option>
                    <option value="enterprise">Enterprise</option>
                  </select>
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="flex items-start gap-3">
                  <Building2 className="h-5 w-5 text-gray-500 mt-0.5" />
                  <div>
                    <p className="text-gray-400 text-sm">Account Name</p>
                    <p className="text-white font-medium">{account.name}</p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <Mail className="h-5 w-5 text-gray-500 mt-0.5" />
                  <div>
                    <p className="text-gray-400 text-sm">Email</p>
                    <p className="text-white font-medium">{account.email}</p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <Phone className="h-5 w-5 text-gray-500 mt-0.5" />
                  <div>
                    <p className="text-gray-400 text-sm">Phone</p>
                    <p className="text-white font-medium">{account.phone || "Not set"}</p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <Building2 className="h-5 w-5 text-gray-500 mt-0.5" />
                  <div>
                    <p className="text-gray-400 text-sm">Business Type</p>
                    <p className="text-white font-medium">{account.business_type || "Not set"}</p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <Calendar className="h-5 w-5 text-gray-500 mt-0.5" />
                  <div>
                    <p className="text-gray-400 text-sm">Created</p>
                    <p className="text-white font-medium">
                      {new Date(account.created_at).toLocaleDateString()}
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <Shield className="h-5 w-5 text-gray-500 mt-0.5" />
                  <div>
                    <p className="text-gray-400 text-sm">URL Slug</p>
                    <p className="text-white font-medium">{account.slug}</p>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="bg-[#111111] border border-[#222222] rounded-xl p-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-semibold text-white">Members</h2>
              <button
                onClick={() => router.push(`/admin/invitations?account_id=${accountId}`)}
                className="flex items-center gap-2 px-3 py-1.5 text-sm bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 rounded-lg transition-colors"
              >
                <Plus className="h-4 w-4" />
                Invite
              </button>
            </div>

            <div className="flex items-center gap-3 p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg">
              <Users className="h-5 w-5 text-gray-500" />
              <div>
                <p className="text-white font-medium">{account.member_count} members</p>
                <p className="text-gray-500 text-sm">
                  View and manage members from the Invitations page
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-[#111111] border border-[#222222] rounded-xl p-6">
            <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-4">
              Status
            </h3>
            <span
              className={`inline-flex px-3 py-1.5 text-sm font-medium rounded-full border ${
                statusColors[account.status] || statusColors.cancelled
              }`}
            >
              {account.status.charAt(0).toUpperCase() + account.status.slice(1)}
            </span>
          </div>

          <div className="bg-[#111111] border border-[#222222] rounded-xl p-6">
            <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-4">
              Subscription
            </h3>
            <span
              className={`inline-flex px-3 py-1.5 text-sm font-medium rounded-lg ${
                tierColors[account.subscription_tier] || tierColors.free
              }`}
            >
              {account.subscription_tier.charAt(0).toUpperCase() +
                account.subscription_tier.slice(1)}
            </span>
          </div>

          <div className="bg-[#111111] border border-[#222222] rounded-xl p-6">
            <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-4">
              Twilio Integration
            </h3>
            {account.has_twilio ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-green-400">
                  <Phone className="h-5 w-5" />
                  <span className="font-medium">Connected</span>
                </div>
                {account.twilio_sub_account_sid && (
                  <p className="text-gray-500 text-xs font-mono break-all">
                    SID: {account.twilio_sub_account_sid}
                  </p>
                )}
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-gray-400 text-sm">
                  No Twilio sub-account configured
                </p>
                <button
                  onClick={handleProvisionTwilio}
                  className="w-full px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors text-sm"
                >
                  Provision Twilio
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
