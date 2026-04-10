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
  LogIn,
  AlertTriangle,
  Clock,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  Zap,
} from "lucide-react";
import { toast } from "sonner";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { setAccountContext } from "@/lib/auth/accountContext";

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

interface SupportSession {
  session_token: string;
  account_id: string;
  account_name: string;
  admin_id: string;
  admin_email: string;
  reason: string;
  created_at: string;
  expires_at: string;
}

interface FeatureMeta {
  name: string;
  description: string;
  tier_defaults: Record<string, boolean>;
}

interface AccountFeaturesData {
  resolved: Record<string, boolean>;
  overrides: Record<string, boolean | null>;
  catalog: Record<string, FeatureMeta>;
}

export default function AccountDetailPage() {
  const { token, user, loading: authLoading, authFetch } = useAuthToken();
  const router = useRouter();
  const params = useParams();
  const accountId = params.id as string;

  const [account, setAccount] = useState<Account | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showSupportModal, setShowSupportModal] = useState(false);
  const [supportReason, setSupportReason] = useState("");
  const [creatingSupportSession, setCreatingSupportSession] = useState(false);
  const [activeSession, setActiveSession] = useState<SupportSession | null>(null);
  const [featuresData, setFeaturesData] = useState<AccountFeaturesData | null>(null);
  const [featuresLoading, setFeaturesLoading] = useState(false);
  const [featuresSaving, setFeaturesSaving] = useState<string | null>(null);
  const [featuresExpanded, setFeaturesExpanded] = useState(false);
  const [showTwilioUpdateForm, setShowTwilioUpdateForm] = useState(false);
  const [twilioUpdateForm, setTwilioUpdateForm] = useState({ sid: "", token: "" });
  const [savingTwilio, setSavingTwilio] = useState(false);
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

  const fetchFeatures = async () => {
    try {
      setFeaturesLoading(true);
      const res = await authFetch(`/api/admin/accounts/${accountId}/features`);
      if (res.ok) {
        const data = await res.json();
        setFeaturesData(data);
      }
    } catch (err) {
      console.error("Error fetching features:", err);
    } finally {
      setFeaturesLoading(false);
    }
  };

  const handleFeaturesExpand = () => {
    const next = !featuresExpanded;
    setFeaturesExpanded(next);
    if (next && !featuresData) {
      fetchFeatures();
    }
  };

  const handleFeatureToggle = async (slug: string, currentResolved: boolean) => {
    if (!featuresData) return;
    const newValue = !currentResolved;
    const tierDefault = featuresData.catalog[slug]?.tier_defaults[account?.subscription_tier ?? "free"] ?? false;
    const overrideValue = newValue === tierDefault ? null : newValue;

    setFeaturesSaving(slug);
    try {
      const res = await authFetch(`/api/admin/accounts/${accountId}/features`, {
        method: "PATCH",
        body: JSON.stringify({ overrides: { [slug]: overrideValue } }),
      });
      if (res.ok) {
        const data = await res.json();
        setFeaturesData(data);
        toast.success(`${featuresData.catalog[slug]?.name ?? slug} ${newValue ? "enabled" : "disabled"}`);
      } else {
        const err = await res.json();
        toast.error(err.detail || "Failed to update feature");
      }
    } catch (err) {
      console.error("Error updating feature:", err);
      toast.error("Failed to update feature");
    } finally {
      setFeaturesSaving(null);
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

  const handleUpdateTwilioCredentials = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!twilioUpdateForm.sid.trim().startsWith("AC") || !twilioUpdateForm.token.trim()) {
      toast.error("Sub-account SID must start with 'AC' and auth token is required");
      return;
    }
    setSavingTwilio(true);
    try {
      const res = await authFetch(`/api/admin/accounts/${accountId}/twilio`, {
        method: "PATCH",
        body: JSON.stringify({
          twilio_sub_account_sid: twilioUpdateForm.sid.trim(),
          twilio_sub_auth_token: twilioUpdateForm.token.trim(),
        }),
      });
      if (res.ok) {
        toast.success("Twilio credentials updated successfully");
        setShowTwilioUpdateForm(false);
        setTwilioUpdateForm({ sid: "", token: "" });
        fetchAccount();
      } else {
        const error = await res.json();
        toast.error(error.detail || "Failed to update Twilio credentials");
      }
    } catch (err) {
      console.error("Error updating Twilio credentials:", err);
      toast.error("Failed to update Twilio credentials");
    } finally {
      setSavingTwilio(false);
    }
  };

  const handleCreateSupportSession = async () => {
    if (!supportReason.trim() || supportReason.length < 5) {
      toast.error("Please provide a reason (at least 5 characters)");
      return;
    }

    setCreatingSupportSession(true);
    try {
      const res = await authFetch(`/api/admin/accounts/${accountId}/support-session`, {
        method: "POST",
        body: JSON.stringify({ reason: supportReason }),
      });

      if (res.ok) {
        const session: SupportSession = await res.json();
        setActiveSession(session);
        setShowSupportModal(false);
        setSupportReason("");
        
        setAccountContext({
          accountId: session.account_id,
          accountName: session.account_name,
          accountSlug: account?.slug || "",
          sessionToken: session.session_token,
          sessionExpires: session.expires_at,
          isAdminSession: true,
        });
        
        toast.success(`Entering ${session.account_name}...`);
        router.push("/dashboard");
      } else {
        const error = await res.json();
        toast.error(error.detail || "Failed to create support session");
      }
    } catch (err) {
      console.error("Error creating support session:", err);
      toast.error("Failed to create support session");
    } finally {
      setCreatingSupportSession(false);
    }
  };

  const handleEnterAccount = () => {
    if (activeSession) {
      toast.info(
        `Support session active. Session token: ${activeSession.session_token.slice(0, 8)}...`,
        { duration: 5000 }
      );
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
          <button
            onClick={() => setShowSupportModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-purple-600/20 hover:bg-purple-600/30 text-purple-400 rounded-lg transition-colors border border-purple-600/30"
          >
            <LogIn className="h-4 w-4" />
            Enter Account
          </button>
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

      {activeSession && (
        <div className="mb-6 p-4 bg-purple-600/10 border border-purple-600/30 rounded-xl">
          <div className="flex items-start gap-3">
            <Shield className="h-5 w-5 text-purple-400 mt-0.5" />
            <div className="flex-1">
              <h3 className="text-white font-medium">Active Support Session</h3>
              <p className="text-gray-400 text-sm mt-1">
                Reason: {activeSession.reason}
              </p>
              <div className="flex flex-wrap items-center gap-4 mt-2 text-xs text-gray-500">
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  Expires: {new Date(activeSession.expires_at).toLocaleTimeString()}
                </span>
                <span className="text-purple-400 font-mono">
                  Token: {activeSession.session_token.slice(0, 16)}...
                </span>
              </div>
              <p className="text-xs text-gray-500 mt-2">
                This session is logged for audit compliance. You have delegated access to configure this account.
              </p>
            </div>
          </div>
        </div>
      )}

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

          <div className="bg-[#111111] border border-[#222222] rounded-xl overflow-hidden">
            <button
              onClick={handleFeaturesExpand}
              className="w-full flex items-center justify-between px-6 py-5 hover:bg-[#161616] transition-colors"
            >
              <div className="flex items-center gap-3">
                <Zap className="h-5 w-5 text-yellow-500" />
                <h2 className="text-lg font-semibold text-white">Features &amp; Entitlements</h2>
              </div>
              {featuresExpanded ? (
                <ChevronUp className="h-5 w-5 text-gray-400" />
              ) : (
                <ChevronDown className="h-5 w-5 text-gray-400" />
              )}
            </button>

            {featuresExpanded && (
              <div className="border-t border-[#222222] px-6 pb-6 pt-4">
                {featuresLoading && !featuresData ? (
                  <div className="flex items-center gap-2 text-gray-400 py-4">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span className="text-sm">Loading features...</span>
                  </div>
                ) : featuresData ? (
                  <div className="space-y-4">
                    {Object.entries(featuresData.catalog).map(([slug, meta]) => {
                      const resolved = featuresData.resolved[slug] ?? false;
                      const tierDefault = meta.tier_defaults[account.subscription_tier] ?? false;
                      const hasOverride = slug in featuresData.overrides;
                      const isSaving = featuresSaving === slug;

                      return (
                        <div
                          key={slug}
                          className="flex items-start justify-between gap-4 p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg"
                        >
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <p className="text-white font-medium text-sm">{meta.name}</p>
                              {hasOverride ? (
                                <span className="inline-flex px-1.5 py-0.5 text-[10px] font-semibold rounded bg-orange-600/20 text-orange-400 border border-orange-600/30">
                                  Overridden
                                </span>
                              ) : (
                                <span className="inline-flex px-1.5 py-0.5 text-[10px] font-medium rounded bg-[#1a1a1a] text-gray-500 border border-[#2a2a2a]">
                                  {tierDefault
                                    ? `Included in ${account.subscription_tier.charAt(0).toUpperCase() + account.subscription_tier.slice(1)}`
                                    : `Not in ${account.subscription_tier.charAt(0).toUpperCase() + account.subscription_tier.slice(1)}`}
                                </span>
                              )}
                            </div>
                            <p className="text-gray-500 text-xs mt-1">{meta.description}</p>
                          </div>

                          <button
                            onClick={() => handleFeatureToggle(slug, resolved)}
                            disabled={isSaving}
                            className={`relative flex-shrink-0 w-11 h-6 rounded-full transition-colors focus:outline-none ${
                              resolved ? "bg-blue-600" : "bg-[#333333]"
                            } ${isSaving ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                            title={resolved ? "Disable" : "Enable"}
                          >
                            {isSaving ? (
                              <span className="absolute inset-0 flex items-center justify-center">
                                <Loader2 className="h-3 w-3 text-white animate-spin" />
                              </span>
                            ) : (
                              <span
                                className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${
                                  resolved ? "translate-x-5" : "translate-x-0"
                                }`}
                              />
                            )}
                          </button>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-gray-500 text-sm py-2">Failed to load features.</p>
                )}
              </div>
            )}
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
                <button
                  onClick={() => setShowTwilioUpdateForm(!showTwilioUpdateForm)}
                  className="w-full px-3 py-2 bg-[#1a1a1a] hover:bg-[#222222] text-gray-400 hover:text-gray-300 rounded-lg transition-colors text-xs"
                >
                  {showTwilioUpdateForm ? "Cancel" : "Update Sub-Account SID"}
                </button>
                {showTwilioUpdateForm && (
                  <form onSubmit={handleUpdateTwilioCredentials} className="space-y-2 pt-1">
                    <input
                      type="text"
                      value={twilioUpdateForm.sid}
                      onChange={(e) => setTwilioUpdateForm({ ...twilioUpdateForm, sid: e.target.value })}
                      placeholder="Sub-account SID (ACxxx...)"
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white text-xs font-mono focus:outline-none focus:border-blue-600"
                      required
                    />
                    <input
                      type="password"
                      value={twilioUpdateForm.token}
                      onChange={(e) => setTwilioUpdateForm({ ...twilioUpdateForm, token: e.target.value })}
                      placeholder="Auth token"
                      className="w-full px-3 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white text-xs font-mono focus:outline-none focus:border-blue-600"
                      required
                    />
                    <button
                      type="submit"
                      disabled={savingTwilio}
                      className="w-full px-3 py-2 bg-orange-600 hover:bg-orange-700 disabled:bg-orange-600/50 text-white rounded-lg transition-colors text-xs"
                    >
                      {savingTwilio ? "Saving..." : "Save Credentials"}
                    </button>
                  </form>
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
                  Retry Twilio Provisioning
                </button>
              </div>
            )}
          </div>

          <div className="bg-[#111111] border border-[#222222] rounded-xl p-6">
            <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-4">
              Quick Actions
            </h3>
            <div className="space-y-2">
              <button
                onClick={() => setShowSupportModal(true)}
                className="w-full flex items-center gap-2 px-4 py-2 bg-purple-600/20 hover:bg-purple-600/30 text-purple-400 rounded-lg transition-colors text-sm"
              >
                <LogIn className="h-4 w-4" />
                Enter Account
              </button>
              <button
                onClick={() => router.push(`/admin/invitations?account_id=${accountId}`)}
                className="w-full flex items-center gap-2 px-4 py-2 bg-[#1a1a1a] hover:bg-[#222222] text-gray-300 rounded-lg transition-colors text-sm"
              >
                <Users className="h-4 w-4" />
                Manage Invitations
              </button>
            </div>
          </div>
        </div>
      </div>

      {showSupportModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-[#111111] border border-[#222222] rounded-xl p-6 max-w-md w-full mx-4">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-semibold text-white">Create Support Session</h2>
              <button
                onClick={() => {
                  setShowSupportModal(false);
                  setSupportReason("");
                }}
                className="text-gray-400 hover:text-white p-1"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="mb-6 p-4 bg-yellow-600/10 border border-yellow-600/30 rounded-lg">
              <div className="flex items-start gap-3">
                <AlertTriangle className="h-5 w-5 text-yellow-400 mt-0.5 flex-shrink-0" />
                <div className="text-sm">
                  <p className="text-yellow-400 font-medium">SaaS Compliance Notice</p>
                  <p className="text-gray-400 mt-1">
                    This action will be logged for audit purposes. Support sessions expire after 1 hour and require a documented reason.
                  </p>
                </div>
              </div>
            </div>

            <div className="mb-6">
              <label className="block text-sm font-medium text-gray-400 mb-2">
                Reason for Access <span className="text-red-400">*</span>
              </label>
              <textarea
                value={supportReason}
                onChange={(e) => setSupportReason(e.target.value)}
                placeholder="Describe why you need to access this account (e.g., 'Assisting with flow configuration per support ticket #1234')"
                rows={3}
                className="w-full px-4 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-600 resize-none"
              />
              <p className="text-gray-500 text-xs mt-1">
                Minimum 5 characters required
              </p>
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => {
                  setShowSupportModal(false);
                  setSupportReason("");
                }}
                className="flex-1 px-4 py-2 bg-[#1a1a1a] text-gray-300 rounded-lg hover:bg-[#222222] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateSupportSession}
                disabled={creatingSupportSession || supportReason.length < 5}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-600/50 text-white rounded-lg transition-colors"
              >
                {creatingSupportSession ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <LogIn className="h-4 w-4" />
                )}
                Create Session
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
