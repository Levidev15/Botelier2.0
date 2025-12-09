"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Settings,
  Shield,
  Key,
  Bell,
  Globe,
  Database,
  Phone,
  Loader2,
  CheckCircle,
  AlertCircle,
  XCircle,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface IntegrationStatus {
  name: string;
  status: string;
  message: string | null;
  details: Record<string, any> | null;
}

interface IntegrationHealth {
  twilio: IntegrationStatus;
  openai: IntegrationStatus;
  database: IntegrationStatus;
}

export default function SettingsPage() {
  const { token, user, loading: authLoading, authFetch } = useAuthToken();
  const router = useRouter();
  const [activeTab, setActiveTab] = useState("general");

  useEffect(() => {
    if (authLoading) return;

    if (!token) {
      router.push("/login?callbackUrl=/admin/settings");
      return;
    }

    if (user?.user_type !== "platform_admin") {
      router.push("/dashboard");
      return;
    }
  }, [token, user, authLoading]);

  const tabs = [
    { id: "general", label: "General", icon: Settings },
    { id: "security", label: "Security", icon: Shield },
    { id: "integrations", label: "Integrations", icon: Key },
  ];

  if (authLoading) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full"></div>
      </div>
    );
  }

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">Platform Settings</h1>
        <p className="text-gray-400 mt-1">
          Configure global platform settings and integrations
        </p>
      </div>

      <div className="flex flex-col lg:flex-row gap-6">
        <div className="lg:w-64 flex-shrink-0">
          <nav className="bg-[#111111] border border-[#222222] rounded-xl p-2">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors text-left ${
                  activeTab === tab.id
                    ? "bg-blue-600/20 text-blue-400"
                    : "text-gray-400 hover:text-white hover:bg-[#1a1a1a]"
                }`}
              >
                <tab.icon className="h-5 w-5" />
                <span className="font-medium">{tab.label}</span>
              </button>
            ))}
          </nav>
        </div>

        <div className="flex-1">
          {activeTab === "general" && <GeneralSettings />}
          {activeTab === "security" && <SecuritySettings />}
          {activeTab === "integrations" && <IntegrationsSettings />}
        </div>
      </div>
    </div>
  );
}

function GeneralSettings() {
  return (
    <div className="bg-[#111111] border border-[#222222] rounded-xl p-6">
      <h2 className="text-lg font-semibold text-white mb-6">General Settings</h2>

      <div className="space-y-6">
        <div className="p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg">
          <div className="flex items-center gap-3 mb-4">
            <Globe className="h-5 w-5 text-blue-400" />
            <div>
              <h3 className="text-white font-medium">Platform Name</h3>
              <p className="text-gray-500 text-sm">The name displayed to users</p>
            </div>
          </div>
          <input
            type="text"
            defaultValue="Botelier"
            disabled
            className="w-full px-4 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-600 disabled:opacity-50"
          />
          <p className="text-gray-500 text-xs mt-2">
            Platform name is configured at the system level
          </p>
        </div>

        <div className="p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg">
          <div className="flex items-center gap-3 mb-4">
            <Bell className="h-5 w-5 text-purple-400" />
            <div>
              <h3 className="text-white font-medium">Default Trial Period</h3>
              <p className="text-gray-500 text-sm">Days for new account trials</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="number"
              defaultValue="14"
              disabled
              className="w-24 px-4 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-600 disabled:opacity-50"
            />
            <span className="text-gray-400">days</span>
          </div>
        </div>

        <div className="p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg">
          <div className="flex items-center gap-3 mb-4">
            <Shield className="h-5 w-5 text-orange-400" />
            <div>
              <h3 className="text-white font-medium">Invitation Expiry</h3>
              <p className="text-gray-500 text-sm">How long invitations remain valid</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="number"
              defaultValue="7"
              disabled
              className="w-24 px-4 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-600 disabled:opacity-50"
            />
            <span className="text-gray-400">days</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function SecuritySettings() {
  return (
    <div className="bg-[#111111] border border-[#222222] rounded-xl p-6">
      <h2 className="text-lg font-semibold text-white mb-6">Security Settings</h2>

      <div className="space-y-6">
        <div className="p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <Shield className="h-5 w-5 text-blue-400" />
              <div>
                <h3 className="text-white font-medium">JWT Authentication</h3>
                <p className="text-gray-500 text-sm">Email/password authentication enabled</p>
              </div>
            </div>
            <div className="flex items-center gap-2 text-green-400">
              <CheckCircle className="h-4 w-4" />
              <span className="text-sm">Active</span>
            </div>
          </div>
        </div>

        <div className="p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg">
          <div className="flex items-center gap-3 mb-4">
            <Key className="h-5 w-5 text-yellow-400" />
            <div>
              <h3 className="text-white font-medium">Password Requirements</h3>
              <p className="text-gray-500 text-sm">Minimum password strength</p>
            </div>
          </div>
          <ul className="text-gray-400 text-sm space-y-1 ml-8 list-disc">
            <li>Minimum 8 characters</li>
            <li>At least one uppercase letter</li>
            <li>At least one number</li>
          </ul>
        </div>

        <div className="p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <Bell className="h-5 w-5 text-purple-400" />
              <div>
                <h3 className="text-white font-medium">Session Duration</h3>
                <p className="text-gray-500 text-sm">JWT token expiration</p>
              </div>
            </div>
          </div>
          <p className="text-white ml-8">30 days</p>
        </div>

        <div className="p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <Shield className="h-5 w-5 text-green-400" />
              <div>
                <h3 className="text-white font-medium">Support Session Duration</h3>
                <p className="text-gray-500 text-sm">Platform Admin account access timeout</p>
              </div>
            </div>
          </div>
          <p className="text-white ml-8">1 hour (requires reason for audit trail)</p>
        </div>
      </div>
    </div>
  );
}

function IntegrationsSettings() {
  const { authFetch } = useAuthToken();
  const [loading, setLoading] = useState(true);
  const [health, setHealth] = useState<IntegrationHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchHealth = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch("/api/admin/integrations/health");
      if (res.ok) {
        setHealth(await res.json());
      } else {
        setError("Failed to check integration status");
      }
    } catch (err) {
      setError("Failed to connect to server");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHealth();
  }, []);

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "connected":
        return <CheckCircle className="h-5 w-5 text-green-400" />;
      case "error":
        return <XCircle className="h-5 w-5 text-red-400" />;
      case "not_configured":
        return <AlertCircle className="h-5 w-5 text-yellow-400" />;
      default:
        return <AlertCircle className="h-5 w-5 text-gray-400" />;
    }
  };

  const getStatusLabel = (status: string) => {
    switch (status) {
      case "connected":
        return <span className="text-green-400">Connected</span>;
      case "error":
        return <span className="text-red-400">Error</span>;
      case "not_configured":
        return <span className="text-yellow-400">Not Configured</span>;
      default:
        return <span className="text-gray-400">Unknown</span>;
    }
  };

  return (
    <div className="bg-[#111111] border border-[#222222] rounded-xl p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-lg font-semibold text-white">Integrations</h2>
        <button
          onClick={fetchHealth}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-400 hover:text-white hover:bg-[#1a1a1a] rounded-lg transition-colors"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {loading && !health ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin" />
        </div>
      ) : error ? (
        <div className="p-4 bg-red-600/10 border border-red-600/30 rounded-lg text-red-400">
          {error}
        </div>
      ) : health ? (
        <div className="space-y-4">
          <div className="p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Phone className="h-5 w-5 text-red-400" />
                <div>
                  <h3 className="text-white font-medium">Twilio</h3>
                  <p className="text-gray-500 text-sm">Voice calls and phone numbers</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {getStatusIcon(health.twilio.status)}
                {getStatusLabel(health.twilio.status)}
              </div>
            </div>
            {health.twilio.message && (
              <p className="text-gray-400 text-sm mt-3 ml-8">{health.twilio.message}</p>
            )}
            {health.twilio.details && (
              <div className="mt-2 ml-8 text-xs text-gray-500">
                Sub-accounts provisioned: {health.twilio.details.sub_accounts_provisioned || 0}
              </div>
            )}
          </div>

          <div className="p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="h-5 w-5 rounded bg-gradient-to-r from-green-400 to-blue-500 flex items-center justify-center">
                  <span className="text-[10px] font-bold text-white">AI</span>
                </div>
                <div>
                  <h3 className="text-white font-medium">OpenAI</h3>
                  <p className="text-gray-500 text-sm">Language model and AI capabilities</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {getStatusIcon(health.openai.status)}
                {getStatusLabel(health.openai.status)}
              </div>
            </div>
            {health.openai.message && (
              <p className="text-gray-400 text-sm mt-3 ml-8">{health.openai.message}</p>
            )}
            {health.openai.details && (
              <div className="mt-2 ml-8 text-xs text-gray-500">
                Available models: {health.openai.details.available_models || 0}
              </div>
            )}
          </div>

          <div className="p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Database className="h-5 w-5 text-blue-400" />
                <div>
                  <h3 className="text-white font-medium">PostgreSQL Database</h3>
                  <p className="text-gray-500 text-sm">Primary data storage</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {getStatusIcon(health.database.status)}
                {getStatusLabel(health.database.status)}
              </div>
            </div>
            {health.database.message && (
              <p className="text-gray-400 text-sm mt-3 ml-8">{health.database.message}</p>
            )}
            {health.database.details && (
              <div className="mt-2 ml-8 text-xs text-gray-500 space-y-1">
                <div>Total users: {health.database.details.total_users || 0}</div>
                <div>Total accounts: {health.database.details.total_accounts || 0}</div>
              </div>
            )}
          </div>

          <div className="p-4 bg-blue-600/10 border border-blue-600/30 rounded-lg">
            <p className="text-blue-400 text-sm">
              Integration credentials are managed through environment variables. 
              Contact your system administrator to update API keys.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
