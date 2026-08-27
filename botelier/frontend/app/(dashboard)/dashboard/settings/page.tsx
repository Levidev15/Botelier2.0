"use client";

import { useEffect, useState } from "react";
import { Save, Check, AlertCircle } from "lucide-react";
import { usePagePermission, AccessDeniedPage } from "@/components/ui/PermissionGate";
import { usePermissions } from "@/lib/auth/usePermissions";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { TIMEZONE_OPTIONS } from "@/components/analytics/TimezonePicker";

interface AccountBasicInfo {
  id: string;
  name: string;
  business_type: string | null;
  email: string;
  phone: string | null;
  timezone: string;
}

export default function SettingsPage() {
  const { hasAccess, loading: permLoading } = usePagePermission("settings", "view");
  const { can, isPlatformAdmin } = usePermissions();
  const { accountId } = useAccountContext();
  const { authFetch, token } = useAuthToken();

  const [info, setInfo] = useState<AccountBasicInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const canEdit = isPlatformAdmin || can("settings", "edit");
  const canBilling = isPlatformAdmin || can("settings", "billing");

  useEffect(() => {
    if (!accountId || !token) return;
    let cancelled = false;

    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await authFetch(`/api/account/basic-info?account_id=${accountId}`);
        if (!res.ok) {
          throw new Error(`Failed to load account info (${res.status})`);
        }
        const data: AccountBasicInfo = await res.json();
        if (!cancelled) setInfo(data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load account info");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [accountId, token]);

  function updateField<K extends keyof AccountBasicInfo>(key: K, value: AccountBasicInfo[K]) {
    setInfo((prev) => (prev ? { ...prev, [key]: value } : prev));
    setSaved(false);
  }

  async function handleSave() {
    if (!info || !accountId) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const res = await authFetch(`/api/account/basic-info?account_id=${accountId}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: info.name,
          email: info.email,
          phone: info.phone,
          timezone: info.timezone,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || `Failed to save (${res.status})`);
      }
      const data: AccountBasicInfo = await res.json();
      setInfo(data);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save changes");
    } finally {
      setSaving(false);
    }
  }

  if (permLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="animate-spin h-6 w-6 border-2 border-blue-500 border-t-transparent rounded-full" />
      </div>
    );
  }

  if (!hasAccess) {
    return <AccessDeniedPage message="You don't have permission to view account settings." />;
  }

  return (
    <div className="p-8 max-w-3xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-sm text-gray-400 mt-1">
          Manage your account settings
        </p>
      </div>

      <div className="space-y-6">
        <div className="bg-[#141414] border border-gray-800 rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-1">Basic Information</h2>
          <p className="text-sm text-gray-400 mb-4">
            Your business name and timezone. This isn't limited to hotels — use
            whatever name your callers know you by, e.g. "Mrs Fields".
          </p>

          {loading ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin h-5 w-5 border-2 border-blue-500 border-t-transparent rounded-full" />
            </div>
          ) : !info ? (
            <p className="text-sm text-red-400">
              {error || "Unable to load account information."}
            </p>
          ) : (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Business Name
                </label>
                <input
                  type="text"
                  value={info.name}
                  onChange={(e) => updateField("name", e.target.value)}
                  placeholder="e.g., Mrs Fields"
                  disabled={!canEdit}
                  className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                />
                <p className="text-xs text-gray-500 mt-1">
                  Used in caller-facing messages and SMS templates (e.g. "Thanks for
                  choosing {info.name || "your business"}!").
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Timezone
                </label>
                <select
                  value={info.timezone}
                  onChange={(e) => updateField("timezone", e.target.value)}
                  disabled={!canEdit}
                  className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {TIMEZONE_OPTIONS.map(({ label, value }) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                  {info.timezone && !TIMEZONE_OPTIONS.some(({ value }) => value === info.timezone) && (
                    <option value={info.timezone}>{info.timezone}</option>
                  )}
                </select>
                <p className="text-xs text-gray-500 mt-1">
                  Used as the default timezone for new assistants you create. Each
                  assistant can still override this under its own Call Settings.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Email
                </label>
                <input
                  type="email"
                  value={info.email}
                  onChange={(e) => updateField("email", e.target.value)}
                  disabled={!canEdit}
                  className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Phone
                </label>
                <input
                  type="tel"
                  value={info.phone || ""}
                  onChange={(e) => updateField("phone", e.target.value)}
                  disabled={!canEdit}
                  placeholder="Optional"
                  className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                />
              </div>

              {error && (
                <div className="flex items-center gap-2 text-sm text-red-400">
                  <AlertCircle className="h-4 w-4 flex-shrink-0" />
                  {error}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="bg-[#141414] border border-gray-800 rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-4">Billing</h2>
          <p className="text-sm text-gray-400">
            Manage your subscription and billing information
          </p>
          {canBilling && (
            <button className="mt-4 px-4 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg transition text-sm font-medium">
              Manage Subscription
            </button>
          )}
        </div>

        {canEdit && info && (
          <div className="flex items-center justify-end gap-3">
            {saved && (
              <span className="flex items-center gap-1.5 text-sm text-green-400">
                <Check className="h-4 w-4" />
                Saved
              </span>
            )}
            <button
              onClick={handleSave}
              disabled={saving}
              className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition text-sm font-medium"
            >
              {saving ? (
                <span className="h-4 w-4 mr-2 border-2 border-white/40 border-t-white rounded-full animate-spin" />
              ) : (
                <Save className="h-4 w-4 mr-2" />
              )}
              {saving ? "Saving..." : "Save Changes"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
