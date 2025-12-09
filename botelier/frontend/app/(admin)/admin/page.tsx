"use client";

import { useEffect, useState } from "react";
import { Building2, Users, TrendingUp, Shield, Phone, Activity } from "lucide-react";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { useRouter } from "next/navigation";

interface PlatformStats {
  total_accounts: number;
  active_accounts: number;
  total_users: number;
  platform_admins: number;
  accounts_by_tier: Record<string, number>;
}

export default function AdminDashboardPage() {
  const { token, user, loading: authLoading, authFetch } = useAuthToken();
  const router = useRouter();
  const [stats, setStats] = useState<PlatformStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (authLoading) return;
    
    if (!token) {
      router.push("/login?callbackUrl=/admin");
      return;
    }
    
    if (user?.user_type !== "platform_admin") {
      router.push("/dashboard");
      return;
    }
    
    fetchStats();
  }, [token, user, authLoading, router]);

  const fetchStats = async () => {
    try {
      const res = await authFetch("/api/admin/stats");
      if (res.ok) {
        setStats(await res.json());
      }
    } catch (err) {
      console.error("Error fetching stats:", err);
    } finally {
      setLoading(false);
    }
  };

  const statCards = [
    {
      label: "Total Accounts",
      value: stats?.total_accounts || 0,
      icon: Building2,
      color: "blue",
      description: "All registered accounts",
    },
    {
      label: "Active Accounts",
      value: stats?.active_accounts || 0,
      icon: Activity,
      color: "green",
      description: "Currently active",
    },
    {
      label: "Total Users",
      value: stats?.total_users || 0,
      icon: Users,
      color: "purple",
      description: "All platform users",
    },
    {
      label: "Platform Admins",
      value: stats?.platform_admins || 0,
      icon: Shield,
      color: "orange",
      description: "Administrator access",
    },
  ];

  const tierLabels: Record<string, string> = {
    free: "Free",
    starter: "Starter",
    professional: "Professional",
    enterprise: "Enterprise",
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
        <div className="text-center">
          <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full mx-auto"></div>
          <p className="mt-4 text-gray-400">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">Platform Dashboard</h1>
        <p className="text-gray-400 mt-1">
          Overview of your Botelier platform
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        {statCards.map((card) => (
          <div
            key={card.label}
            className="bg-[#111111] border border-[#222222] rounded-xl p-6 hover:border-[#333333] transition-colors"
          >
            <div className="flex items-center justify-between mb-4">
              <div
                className={`p-3 rounded-lg ${
                  card.color === "blue"
                    ? "bg-blue-600/20"
                    : card.color === "green"
                    ? "bg-green-600/20"
                    : card.color === "purple"
                    ? "bg-purple-600/20"
                    : "bg-orange-600/20"
                }`}
              >
                <card.icon
                  className={`h-5 w-5 ${
                    card.color === "blue"
                      ? "text-blue-400"
                      : card.color === "green"
                      ? "text-green-400"
                      : card.color === "purple"
                      ? "text-purple-400"
                      : "text-orange-400"
                  }`}
                />
              </div>
            </div>
            <p className="text-3xl font-bold text-white mb-1">{card.value}</p>
            <p className="text-gray-400 text-sm font-medium">{card.label}</p>
            <p className="text-gray-500 text-xs mt-1">{card.description}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-[#111111] border border-[#222222] rounded-xl p-6">
          <h2 className="text-lg font-semibold text-white mb-4">
            Accounts by Tier
          </h2>
          <div className="space-y-3">
            {Object.entries(stats?.accounts_by_tier || {}).map(
              ([tier, count]) => (
                <div
                  key={tier}
                  className="flex items-center justify-between p-3 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg"
                >
                  <div className="flex items-center gap-3">
                    <span className={`px-2 py-1 rounded text-xs font-medium ${tierColors[tier] || tierColors.free}`}>
                      {tierLabels[tier] || tier}
                    </span>
                  </div>
                  <p className="text-xl font-bold text-white">{count}</p>
                </div>
              )
            )}
          </div>
        </div>

        <div className="bg-[#111111] border border-[#222222] rounded-xl p-6">
          <h2 className="text-lg font-semibold text-white mb-4">
            Quick Actions
          </h2>
          <div className="space-y-3">
            <button
              onClick={() => router.push("/admin/accounts")}
              className="w-full flex items-center gap-3 p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg hover:border-blue-600/50 transition-colors text-left"
            >
              <Building2 className="h-5 w-5 text-blue-400" />
              <div>
                <p className="text-white font-medium">Manage Accounts</p>
                <p className="text-gray-500 text-sm">Create and configure accounts</p>
              </div>
            </button>
            <button
              onClick={() => router.push("/admin/invitations")}
              className="w-full flex items-center gap-3 p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg hover:border-blue-600/50 transition-colors text-left"
            >
              <Users className="h-5 w-5 text-purple-400" />
              <div>
                <p className="text-white font-medium">Invite Users</p>
                <p className="text-gray-500 text-sm">Send invitations to new users</p>
              </div>
            </button>
            <button
              onClick={() => router.push("/admin/users")}
              className="w-full flex items-center gap-3 p-4 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg hover:border-blue-600/50 transition-colors text-left"
            >
              <Shield className="h-5 w-5 text-orange-400" />
              <div>
                <p className="text-white font-medium">View All Users</p>
                <p className="text-gray-500 text-sm">Manage platform users</p>
              </div>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
