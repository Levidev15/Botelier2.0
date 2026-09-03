"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  Save, Mail, Plus, Trash2, RefreshCw, CheckCircle, AlertCircle,
  ExternalLink, Loader2, Chrome, Monitor,
} from "lucide-react";
import { usePagePermission, AccessDeniedPage } from "@/components/ui/PermissionGate";
import { usePermissions } from "@/lib/auth/usePermissions";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { notify } from "@/lib/notifications";

// ── Types ────────────────────────────────────────────────────────────────────

interface EmailSender {
  id: string;
  connection_name: string;
  provider: string;
  slug: string;
  email: string;
  status: string;
  connected_at: string | null;
  last_error: string | null;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function ProviderIcon({ provider, size = 18 }: { provider: string; size?: number }) {
  if (provider === "google") return <Chrome size={size} className="text-red-400" />;
  if (provider === "microsoft") return <Monitor size={size} className="text-blue-400" />;
  return <Mail size={size} className="text-gray-400" />;
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { cls: string; label: string }> = {
    connected: { cls: "bg-green-900/40 text-green-400 border border-green-800", label: "Connected" },
    connecting: { cls: "bg-yellow-900/40 text-yellow-400 border border-yellow-800", label: "Connecting…" },
    error: { cls: "bg-red-900/40 text-red-400 border border-red-800", label: "Error" },
    disconnected: { cls: "bg-gray-800 text-gray-400 border border-gray-700", label: "Disconnected" },
  };
  const s = map[status] ?? map.disconnected;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${s.cls}`}>
      {s.label}
    </span>
  );
}

// ── Email Accounts Tab ───────────────────────────────────────────────────────

function EmailAccountsTab({ accountId }: { accountId: string }) {
  const { authFetch } = useAuthToken();
  const [senders, setSenders] = useState<EmailSender[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [connectingProvider, setConnectingProvider] = useState<string | null>(null);
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);
  const freshRef = useRef(false);

  const searchParams = useSearchParams();
  const justConnected = searchParams.get("connected") === "1";

  const fetchSenders = async () => {
    try {
      const resp = await authFetch(`/api/settings/email-senders?account_id=${accountId}`);
      if (resp.ok) {
        const data = await resp.json();
        setSenders(data.connections ?? []);
      }
    } catch {
      // silently fail — list stays empty
    } finally {
      setLoadingList(false);
    }
  };

  useEffect(() => {
    if (!accountId) return;
    fetchSenders();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId]);

  // After a successful OAuth redirect, show a success toast once
  useEffect(() => {
    if (justConnected && !freshRef.current) {
      freshRef.current = true;
      notify.success("Email account connected successfully");
    }
  }, [justConnected]);

  const handleConnect = async (provider: "gmail" | "microsoft") => {
    setConnectingProvider(provider);
    try {
      const resp = await authFetch(
        `/api/settings/email-senders/connect/${provider}?account_id=${accountId}`,
        { method: "POST" },
      );
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        const msg = typeof err.detail === "string" ? err.detail : "Failed to start connection";
        notify.error(msg);
        return;
      }
      const data = await resp.json();
      // Open the provider consent page in a new tab so it is never loaded
      // inside an iframe (Microsoft/Google refuse iframe embedding via
      // X-Frame-Options: DENY). After OAuth completes the callback redirects
      // back to this app in that same tab.
      window.open(data.authorization_url, "_blank", "noopener,noreferrer");
    } catch {
      notify.error("Failed to start email connection");
    } finally {
      setConnectingProvider(null);
    }
  };

  const handleDisconnect = async (id: string, name: string) => {
    if (!confirm(`Remove "${name}" as a connected sender?`)) return;
    setDisconnectingId(id);
    try {
      const resp = await authFetch(
        `/api/settings/email-senders/${id}?account_id=${accountId}`,
        { method: "DELETE" },
      );
      if (resp.ok) {
        setSenders((prev) => prev.filter((s) => s.id !== id));
        notify.success("Sender disconnected");
      } else {
        notify.error("Failed to disconnect sender");
      }
    } catch {
      notify.error("Failed to disconnect sender");
    } finally {
      setDisconnectingId(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Explainer */}
      <div className="bg-[#141414] border border-gray-800 rounded-lg p-6">
        <div className="flex items-start gap-3">
          <Mail className="text-blue-400 mt-0.5 shrink-0" size={20} />
          <div>
            <h2 className="text-base font-semibold mb-1">Connected Email Accounts</h2>
            <p className="text-sm text-gray-400 leading-relaxed">
              Connect a Gmail or Microsoft account so your AI assistant can send emails
              directly from your own mailbox. Emails arrive from your address — not a
              generic platform address. Botelier only has send permission; it cannot
              read your messages.
            </p>
          </div>
        </div>
      </div>

      {/* Connected senders */}
      <div className="bg-[#141414] border border-gray-800 rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-800 flex items-center justify-between">
          <span className="text-sm font-medium text-gray-300">
            Connected accounts ({senders.length})
          </span>
          <button
            onClick={fetchSenders}
            className="text-gray-500 hover:text-gray-300 transition-colors"
            title="Refresh list"
          >
            <RefreshCw size={14} />
          </button>
        </div>

        {loadingList ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-gray-500" />
          </div>
        ) : senders.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center px-6">
            <Mail className="text-gray-600 mb-3" size={32} />
            <p className="text-sm text-gray-400 mb-1">No email accounts connected yet</p>
            <p className="text-xs text-gray-600">
              Connect Gmail or Microsoft below to start sending from your own address.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-gray-800">
            {senders.map((s) => (
              <li key={s.id} className="flex items-center gap-4 px-6 py-4">
                <ProviderIcon provider={s.provider} size={20} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{s.email || s.connection_name}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <StatusBadge status={s.status} />
                    {s.connected_at && (
                      <span className="text-xs text-gray-600">
                        connected {new Date(s.connected_at).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                  {s.last_error && s.status === "error" && (
                    <p className="text-xs text-red-400 mt-1">{s.last_error}</p>
                  )}
                </div>
                <button
                  onClick={() => handleDisconnect(s.id, s.email || s.connection_name)}
                  disabled={disconnectingId === s.id}
                  className="p-2 text-gray-600 hover:text-red-400 transition-colors disabled:opacity-50"
                  title="Disconnect"
                >
                  {disconnectingId === s.id ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Trash2 size={16} />
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Connect buttons */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <button
          onClick={() => handleConnect("gmail")}
          disabled={connectingProvider !== null}
          className="flex items-center gap-3 px-5 py-4 bg-[#141414] border border-gray-800 hover:border-gray-600 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {connectingProvider === "gmail" ? (
            <Loader2 size={20} className="animate-spin text-red-400" />
          ) : (
            <Chrome size={20} className="text-red-400" />
          )}
          <div className="text-left">
            <p className="text-sm font-medium">Connect Gmail</p>
            <p className="text-xs text-gray-500">Gmail or Google Workspace</p>
          </div>
          <ExternalLink size={14} className="ml-auto text-gray-600" />
        </button>

        <button
          onClick={() => handleConnect("microsoft")}
          disabled={connectingProvider !== null}
          className="flex items-center gap-3 px-5 py-4 bg-[#141414] border border-gray-800 hover:border-gray-600 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {connectingProvider === "microsoft" ? (
            <Loader2 size={20} className="animate-spin text-blue-400" />
          ) : (
            <Monitor size={20} className="text-blue-400" />
          )}
          <div className="text-left">
            <p className="text-sm font-medium">Connect Microsoft</p>
            <p className="text-xs text-gray-500">Microsoft 365 or Outlook</p>
          </div>
          <ExternalLink size={14} className="ml-auto text-gray-600" />
        </button>
      </div>

      <p className="text-xs text-gray-600 leading-relaxed">
        Botelier uses your account&apos;s connected mailbox only for emails explicitly sent by your
        AI assistant. It cannot read, delete, or forward your messages.
      </p>
    </div>
  );
}

// ── General Tab ──────────────────────────────────────────────────────────────

function GeneralTab({ canBilling, canEdit }: { canBilling: boolean; canEdit: boolean }) {
  return (
    <div className="space-y-6">
      <div className="bg-[#141414] border border-gray-800 rounded-lg p-6">
        <h2 className="text-lg font-semibold mb-1">Account Information</h2>
        <p className="text-sm text-gray-400">
          Account details are for administration only. Set the caller-facing business or
          location name and timezone in each assistant&apos;s Basic Information.
        </p>
      </div>

      <div className="bg-[#141414] border border-gray-800 rounded-lg p-6">
        <h2 className="text-lg font-semibold mb-4">Billing</h2>
        <p className="text-sm text-gray-400">
          Manage your subscription and billing information.
        </p>
        {canBilling && (
          <button className="mt-4 px-4 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg transition text-sm font-medium">
            Manage Subscription
          </button>
        )}
      </div>

      {canEdit && (
        <div className="flex justify-end">
          <button className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium">
            <Save className="h-4 w-4 mr-2" />
            Save Changes
          </button>
        </div>
      )}
    </div>
  );
}

// ── Tabs ─────────────────────────────────────────────────────────────────────

type Tab = "general" | "email";

// ── Page (inner, must be inside Suspense for useSearchParams) ────────────────

function SettingsPageInner() {
  const { hasAccess, loading: permLoading } = usePagePermission("settings", "view");
  const { can, isPlatformAdmin } = usePermissions();
  const { accountId } = useAccountContext();
  const searchParams = useSearchParams();
  const router = useRouter();

  const tabParam = (searchParams.get("tab") ?? "general") as Tab;
  const [activeTab, setActiveTab] = useState<Tab>(
    ["general", "email"].includes(tabParam) ? tabParam : "general",
  );

  const canEdit = isPlatformAdmin || can("settings", "edit");
  const canBilling = isPlatformAdmin || can("settings", "billing");

  const switchTab = (t: Tab) => {
    setActiveTab(t);
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", t);
    // Remove the "connected" marker when navigating away
    params.delete("connected");
    router.replace(`/dashboard/settings?${params.toString()}`);
  };

  if (permLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
      </div>
    );
  }

  if (!hasAccess) {
    return <AccessDeniedPage message="You don't have permission to view account settings." />;
  }

  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: "general", label: "General", icon: <Save size={15} /> },
    { id: "email", label: "Email", icon: <Mail size={15} /> },
  ];

  return (
    <div className="p-8 max-w-3xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-sm text-gray-400 mt-1">Manage your account configuration</p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 mb-8 border-b border-gray-800 -mx-px">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => switchTab(t.id)}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === t.id
                ? "border-blue-500 text-white"
                : "border-transparent text-gray-400 hover:text-gray-200"
            }`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "general" && (
        <GeneralTab canBilling={canBilling} canEdit={canEdit} />
      )}
      {activeTab === "email" && accountId && (
        <EmailAccountsTab accountId={accountId} />
      )}
    </div>
  );
}

// ── Page export (Suspense boundary for useSearchParams) ───────────────────────

export default function SettingsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-[400px]">
          <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
        </div>
      }
    >
      <SettingsPageInner />
    </Suspense>
  );
}
