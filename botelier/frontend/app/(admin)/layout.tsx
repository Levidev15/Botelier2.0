"use client";

import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Building2,
  Users,
  BarChart3,
  Settings,
  LogOut,
  ChevronRight,
  Shield,
} from "lucide-react";
import { signOut } from "next-auth/react";
import { useAuthToken } from "@/lib/auth/useAuthToken";

const adminNavItems = [
  { href: "/admin", label: "Dashboard", icon: BarChart3 },
  { href: "/admin/accounts", label: "Accounts", icon: Building2 },
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/settings", label: "Settings", icon: Settings },
];

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { data: session, status } = useSession();
  const { token, loading: tokenLoading, authFetch } = useAuthToken();
  const router = useRouter();
  const pathname = usePathname();
  const [userInfo, setUserInfo] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/login?callbackUrl=/admin");
      return;
    }

    if (status === "authenticated" && token) {
      fetchUserInfo();
    }
  }, [status, token, router]);

  const fetchUserInfo = async () => {
    if (!token) return;
    try {
      const res = await authFetch("/api/admin/me");
      if (res.ok) {
        const data = await res.json();
        setUserInfo(data);
        if (!data.is_platform_admin) {
          router.push("/dashboard");
        }
      } else {
        router.push("/dashboard");
      }
    } catch (err) {
      console.error("Error fetching user info:", err);
      router.push("/dashboard");
    } finally {
      setLoading(false);
    }
  };

  if (status === "loading" || tokenLoading || loading) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full mx-auto"></div>
          <p className="mt-4 text-gray-400">Loading...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] flex">
      <aside className="w-64 bg-[#0f0f0f] border-r border-[#1a1a1a] flex flex-col">
        <div className="p-4 border-b border-[#1a1a1a]">
          <div className="flex items-center gap-2">
            <Shield className="h-6 w-6 text-blue-500" />
            <span className="text-lg font-semibold text-white">
              Platform Admin
            </span>
          </div>
        </div>

        <nav className="flex-1 p-4 space-y-1">
          {adminNavItems.map((item) => {
            const isActive =
              pathname === item.href ||
              (item.href !== "/admin" && pathname.startsWith(item.href));
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${
                  isActive
                    ? "bg-blue-600/20 text-blue-400"
                    : "text-gray-400 hover:text-white hover:bg-[#1a1a1a]"
                }`}
              >
                <item.icon className="h-5 w-5" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="p-4 border-t border-[#1a1a1a]">
          <Link
            href="/dashboard"
            className="flex items-center gap-3 px-3 py-2 text-gray-400 hover:text-white hover:bg-[#1a1a1a] rounded-lg transition-colors"
          >
            <ChevronRight className="h-5 w-5" />
            <span>Go to Dashboard</span>
          </Link>

          <div className="mt-4 px-3 py-2">
            <div className="flex items-center gap-3">
              {userInfo?.profile_image_url ? (
                <img
                  src={userInfo.profile_image_url}
                  alt=""
                  className="h-8 w-8 rounded-full object-cover"
                />
              ) : (
                <div className="h-8 w-8 rounded-full bg-blue-600 flex items-center justify-center text-white text-sm font-medium">
                  {userInfo?.display_name?.[0] || "?"}
                </div>
              )}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white truncate">
                  {userInfo?.display_name || "Admin"}
                </p>
                <p className="text-xs text-gray-500 truncate">
                  {userInfo?.email || "Platform Admin"}
                </p>
              </div>
            </div>
          </div>

          <button
            onClick={() => signOut({ callbackUrl: "/login" })}
            className="w-full flex items-center gap-3 px-3 py-2 mt-2 text-red-400 hover:text-red-300 hover:bg-red-900/20 rounded-lg transition-colors"
          >
            <LogOut className="h-5 w-5" />
            <span>Sign Out</span>
          </button>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  );
}
