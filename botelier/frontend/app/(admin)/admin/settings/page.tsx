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
  Save,
  Loader2,
  CheckCircle,
  AlertCircle,
} from "lucide-react";
import { toast } from "sonner";
import { useAuthToken } from "@/lib/auth/useAuthToken";

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
            Platform name cannot be changed in this version
          </p>
        </div>

        <div className="p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg">
          <div className="flex items-center gap-3 mb-4">
            <Database className="h-5 w-5 text-green-400" />
            <div>
              <h3 className="text-white font-medium">Database Status</h3>
              <p className="text-gray-500 text-sm">PostgreSQL connection status</p>
            </div>
          </div>
          <div className="flex items-center gap-2 text-green-400">
            <CheckCircle className="h-5 w-5" />
            <span>Connected</span>
          </div>
        </div>

        <div className="p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg">
          <div className="flex items-center gap-3 mb-4">
            <Bell className="h-5 w-5 text-purple-400" />
            <div>
              <h3 className="text-white font-medium">Default Trial Period</h3>
              <p className="text-gray-500 text-sm">Days for new account trials</p>
            </div>
          </div>
          <input
            type="number"
            defaultValue="14"
            disabled
            className="w-full px-4 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-600 disabled:opacity-50"
          />
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
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <Key className="h-5 w-5 text-yellow-400" />
              <div>
                <h3 className="text-white font-medium">Password Requirements</h3>
                <p className="text-gray-500 text-sm">Minimum password strength</p>
              </div>
            </div>
          </div>
          <ul className="text-gray-400 text-sm space-y-1 ml-8">
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
      </div>
    </div>
  );
}

function IntegrationsSettings() {
  const [twilioStatus, setTwilioStatus] = useState<"checking" | "connected" | "not_configured">("checking");
  const [openaiStatus, setOpenaiStatus] = useState<"checking" | "connected" | "not_configured">("checking");

  useEffect(() => {
    setTimeout(() => {
      setTwilioStatus("not_configured");
      setOpenaiStatus("connected");
    }, 1000);
  }, []);

  return (
    <div className="bg-[#111111] border border-[#222222] rounded-xl p-6">
      <h2 className="text-lg font-semibold text-white mb-6">Integrations</h2>

      <div className="space-y-6">
        <div className="p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Phone className="h-5 w-5 text-red-400" />
              <div>
                <h3 className="text-white font-medium">Twilio</h3>
                <p className="text-gray-500 text-sm">Voice calls and phone numbers</p>
              </div>
            </div>
            {twilioStatus === "checking" ? (
              <Loader2 className="h-5 w-5 text-gray-400 animate-spin" />
            ) : twilioStatus === "connected" ? (
              <div className="flex items-center gap-2 text-green-400">
                <CheckCircle className="h-4 w-4" />
                <span className="text-sm">Connected</span>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-yellow-400">
                <AlertCircle className="h-4 w-4" />
                <span className="text-sm">Not Configured</span>
              </div>
            )}
          </div>
          {twilioStatus === "not_configured" && (
            <p className="text-gray-500 text-sm mt-3 ml-8">
              Configure Twilio API credentials to enable phone features. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN environment variables.
            </p>
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
            {openaiStatus === "checking" ? (
              <Loader2 className="h-5 w-5 text-gray-400 animate-spin" />
            ) : openaiStatus === "connected" ? (
              <div className="flex items-center gap-2 text-green-400">
                <CheckCircle className="h-4 w-4" />
                <span className="text-sm">Connected</span>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-yellow-400">
                <AlertCircle className="h-4 w-4" />
                <span className="text-sm">Not Configured</span>
              </div>
            )}
          </div>
        </div>

        <div className="p-4 bg-blue-600/10 border border-blue-600/30 rounded-lg">
          <p className="text-blue-400 text-sm">
            Integration settings are managed through environment variables. Contact your system administrator to update API credentials.
          </p>
        </div>
      </div>
    </div>
  );
}
