"use client";

import { Bot, LayoutDashboard, Phone, BarChart, Settings, Key, Users, Wrench, BookOpen, Shield, LogOut, ArrowLeft, Building2 } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { useAccountContext } from "@/lib/auth/useAccountContext";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { data: session, status } = useSession();
  const { token, loading: tokenLoading, authFetch } = useAuthToken();
  const { accountId, accountName, isAdminSession, exitAccount, loading: accountLoading } = useAccountContext();
  const router = useRouter();
  const pathname = usePathname();
  const [userInfo, setUserInfo] = useState<any>(null);

  const handleExitAccount = () => {
    exitAccount();
    router.push("/admin/accounts");
  };

  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/login?callbackUrl=/dashboard");
    }
  }, [status, router]);

  useEffect(() => {
    if (session && token) {
      fetchUserInfo();
    }
  }, [session, token]);

  const fetchUserInfo = async () => {
    if (!token) return;
    try {
      const res = await authFetch("/api/admin/me");
      if (res.ok) {
        setUserInfo(await res.json());
      }
    } catch (err) {
      console.error("Error fetching user info:", err);
    }
  };

  if (status === "loading" || tokenLoading || accountLoading) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full mx-auto"></div>
          <p className="mt-4 text-gray-400">Loading...</p>
        </div>
      </div>
    );
  }

  const isActive = (href: string) => {
    if (href === "/dashboard") {
      return pathname === "/dashboard";
    }
    return pathname.startsWith(href);
  };

  return (
    <div className="flex h-screen bg-[#0a0a0a] text-gray-100">
      <aside className="w-64 bg-[#141414] border-r border-gray-800 flex flex-col">
        {isAdminSession && (
          <div className="p-3 bg-purple-600/20 border-b border-purple-600/30">
            <div className="flex items-center gap-2 text-purple-400 text-sm">
              <Building2 className="h-4 w-4" />
              <span className="font-medium truncate">{accountName}</span>
            </div>
            <button
              onClick={handleExitAccount}
              className="mt-2 w-full flex items-center justify-center gap-1 px-2 py-1.5 text-xs bg-purple-600/30 hover:bg-purple-600/50 text-purple-300 rounded transition-colors"
            >
              <ArrowLeft className="h-3 w-3" />
              Exit Account
            </button>
          </div>
        )}
        <div className="p-6 border-b border-gray-800">
          <Link href="/" className="flex items-center space-x-2">
            <Bot className="h-8 w-8 text-blue-500" />
            <span className="text-xl font-bold">Botelier</span>
          </Link>
        </div>
        
        <nav className="flex-1 p-4 space-y-1">
          <NavItem href="/dashboard" icon={<LayoutDashboard className="h-5 w-5" />} active={isActive("/dashboard") && pathname === "/dashboard"}>
            Dashboard
          </NavItem>
          <NavItem href="/dashboard/assistants" icon={<Bot className="h-5 w-5" />} active={isActive("/dashboard/assistants")}>
            Assistants
          </NavItem>
          <NavItem href="/dashboard/tools" icon={<Wrench className="h-5 w-5" />} active={isActive("/dashboard/tools")}>
            Tools
          </NavItem>
          <NavItem href="/dashboard/knowledge-bases" icon={<BookOpen className="h-5 w-5" />} active={isActive("/dashboard/knowledge-bases")}>
            Knowledge Bases
          </NavItem>
          <NavItem href="/dashboard/phone-numbers" icon={<Phone className="h-5 w-5" />} active={isActive("/dashboard/phone-numbers")}>
            Phone Numbers
          </NavItem>
          <NavItem href="/dashboard/call-logs" icon={<BarChart className="h-5 w-5" />} active={isActive("/dashboard/call-logs")}>
            Call Logs
          </NavItem>
          
          <div className="pt-4 pb-2">
            <div className="px-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Configuration
            </div>
          </div>
          
          <NavItem href="/dashboard/api-keys" icon={<Key className="h-5 w-5" />} active={isActive("/dashboard/api-keys")}>
            API Keys
          </NavItem>
          <NavItem href="/dashboard/team" icon={<Users className="h-5 w-5" />} active={isActive("/dashboard/team")}>
            Team
          </NavItem>
          <NavItem href="/dashboard/settings" icon={<Settings className="h-5 w-5" />} active={isActive("/dashboard/settings")}>
            Settings
          </NavItem>

          {userInfo?.is_platform_admin && (
            <>
              <div className="pt-4 pb-2">
                <div className="px-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Platform
                </div>
              </div>
              <NavItem href="/admin" icon={<Shield className="h-5 w-5" />} active={false}>
                Admin Panel
              </NavItem>
            </>
          )}
        </nav>

        <div className="p-4 border-t border-gray-800">
          <div className="flex items-center space-x-3">
            {userInfo?.profile_image_url ? (
              <img
                src={userInfo.profile_image_url}
                alt=""
                className="w-8 h-8 rounded-full object-cover"
              />
            ) : (
              <div className="w-8 h-8 bg-blue-600 rounded-full flex items-center justify-center text-sm font-semibold">
                {userInfo?.display_name?.[0] || session?.user?.name?.[0] || "?"}
              </div>
            )}
            <div className="flex-1">
              <div className="text-sm font-medium">{userInfo?.display_name || session?.user?.name || "User"}</div>
              <div className="text-xs text-gray-400">{userInfo?.email || session?.user?.email || ""}</div>
            </div>
          </div>
          <button
            onClick={() => signOut({ callbackUrl: "/login" })}
            className="w-full mt-3 flex items-center gap-2 px-3 py-2 text-sm text-red-400 hover:text-red-300 hover:bg-red-900/20 rounded-lg transition-colors"
          >
            <LogOut className="h-4 w-4" />
            Sign Out
          </button>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">
        {children}
      </main>
    </div>
  );
}

function NavItem({
  href,
  icon,
  children,
  active,
}: {
  href: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  active?: boolean;
}) {
  return (
    <Link
      href={href}
      className={`flex items-center space-x-3 px-3 py-2 rounded-lg transition-colors ${
        active
          ? "bg-blue-600/10 text-blue-400"
          : "text-gray-400 hover:bg-gray-800 hover:text-gray-200"
      }`}
    >
      {icon}
      <span className="text-sm font-medium">{children}</span>
    </Link>
  );
}
