"use client";

import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import { Building2, Users, Phone, Headphones } from "lucide-react";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface PlatformStats {
  total_accounts: number;
  active_accounts: number;
  total_users: number;
  platform_admins: number;
  accounts_by_tier: Record<string, number>;
}

export default function AdminDashboardPage() {
  const { data: session } = useSession();
  const { token, authFetch } = useAuthToken();
  const [stats, setStats] = useState<PlatformStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (session && token) {
      fetchStats();
    }
  }, [session, token]);

  const fetchStats = async () => {
    if (!token) return;
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
    },
    {
      label: "Active Accounts",
      value: stats?.active_accounts || 0,
      icon: Building2,
      color: "green",
    },
    {
      label: "Total Users",
      value: stats?.total_users || 0,
      icon: Users,
      color: "purple",
    },
    {
      label: "Platform Admins",
      value: stats?.platform_admins || 0,
      icon: Users,
      color: "orange",
    },
  ];

  const tierLabels: Record<string, string> = {
    free: "Free",
    starter: "Starter",
    professional: "Professional",
    enterprise: "Enterprise",
  };

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">Platform Dashboard</h1>
        <p className="text-gray-400 mt-1">
          Overview of your Botelier platform
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full"></div>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
            {statCards.map((card) => (
              <div
                key={card.label}
                className="bg-[#111111] border border-[#222222] rounded-xl p-6"
              >
                <div className="flex items-center justify-between mb-4">
                  <div
                    className={`p-2 rounded-lg ${
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
                <p className="text-3xl font-bold text-white">{card.value}</p>
                <p className="text-gray-400 text-sm mt-1">{card.label}</p>
              </div>
            ))}
          </div>

          <div className="bg-[#111111] border border-[#222222] rounded-xl p-6">
            <h2 className="text-lg font-semibold text-white mb-4">
              Accounts by Tier
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {Object.entries(stats?.accounts_by_tier || {}).map(
                ([tier, count]) => (
                  <div
                    key={tier}
                    className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg p-4"
                  >
                    <p className="text-2xl font-bold text-white">{count}</p>
                    <p className="text-gray-400 text-sm">
                      {tierLabels[tier] || tier}
                    </p>
                  </div>
                )
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
