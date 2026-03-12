"use client";

import { Bot, LayoutDashboard, Phone, BarChart, Settings, Key, Users, Wrench, BookOpen, Shield, LogOut, ArrowLeft, Building2, Plug, MessageSquare, TrendingUp, MessageCircle } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { useAccountContext } from "@/lib/auth/useAccountContext";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { token, loading: tokenLoading, authFetch } = useAuthToken();
  const { accountId, accountName, isAdminSession, exitAccount, loading: accountLoading } = useAccountContext();
  const router = useRouter();
  const pathname = usePathname();
  const [userInfo, setUserInfo] = useState<any>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [pendingHandoffs, setPendingHandoffs] = useState(0);
  const handoffPollRef = useRef<NodeJS.Timeout | null>(null);

  const handleExitAccount = () => {
    exitAccount();
    router.push("/admin/accounts");
  };

  const handleLogout = () => {
    localStorage.removeItem("botelier_token");
    localStorage.removeItem("botelier_user");
    router.push("/login");
  };

  useEffect(() => {
    if (tokenLoading || accountLoading) {
      return;
    }
    
    const hasAdminSupportSession = !!token && isAdminSession;
    const hasRegularSession = !!token && !isAdminSession;
    
    if (!hasAdminSupportSession && !hasRegularSession) {
      router.push("/login?callbackUrl=/dashboard");
    } else {
      setAuthChecked(true);
    }
  }, [token, tokenLoading, accountLoading, isAdminSession, router]);

  useEffect(() => {
    if (token && authChecked) {
      fetchUserInfo();
    }
  }, [token, authChecked]);

  const fetchUserInfo = async () => {
    if (!token) return;
    try {
      const res = await authFetch("/api/admin/me");
      if (res.ok) {
        const data = await res.json();
        setUserInfo(data);
        
        if (!isAdminSession && data.memberships?.length > 0) {
          const firstMembership = data.memberships[0];
          if (!accountId) {
            const { setAccountContext } = await import("@/lib/auth/accountContext");
            setAccountContext({
              accountId: firstMembership.account_id,
              accountName: firstMembership.account_name,
              accountSlug: firstMembership.account_slug,
              isAdminSession: false,
            });
            window.location.reload();
          }
        }
      }
    } catch (err) {
      console.error("Error fetching user info:", err);
    }
  };

  // Poll for pending handoffs count every 30s so the sidebar badge stays current
  // across all pages, not just when the Messages page is open.
  const fetchPendingHandoffs = async (hotelId: string) => {
    try {
      const res = await fetch(`/api/sms/pending-handoffs?hotel_id=${hotelId}`);
      if (res.ok) {
        const data = await res.json();
        setPendingHandoffs(data.count ?? 0);
      }
    } catch {}
  };

  useEffect(() => {
    if (!accountId || !authChecked) return;

    fetchPendingHandoffs(accountId);

    handoffPollRef.current = setInterval(() => {
      fetchPendingHandoffs(accountId);
    }, 30_000);

    return () => {
      if (handoffPollRef.current) clearInterval(handoffPollRef.current);
    };
  }, [accountId, authChecked]);

  if (tokenLoading || accountLoading || !authChecked) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="flex flex-col items-center gap-6">
          <div className="relative">
            <div className="w-14 h-14 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
              <span className="text-xl font-bold text-white">B</span>
            </div>
            <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-blue-500/30 to-purple-600/30 blur-lg animate-pulse" />
          </div>
          <div className="flex items-center gap-1">
            <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-bounce" style={{ animationDelay: "0ms" }} />
            <div className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: "150ms" }} />
            <div className="w-1.5 h-1.5 rounded-full bg-purple-500 animate-bounce" style={{ animationDelay: "300ms" }} />
          </div>
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

  const storedUser = typeof window !== "undefined" ? localStorage.getItem("botelier_user") : null;
  const parsedUser = storedUser ? JSON.parse(storedUser) : null;

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
          <NavItem href="/dashboard/messages" icon={<MessageSquare className="h-5 w-5" />} active={isActive("/dashboard/messages")} badge={pendingHandoffs}>
            Messages
          </NavItem>
          
          <div className="pt-4 pb-2">
            <div className="px-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Analytics
            </div>
          </div>

          <NavItem href="/dashboard/analytics/calls" icon={<TrendingUp className="h-5 w-5" />} active={isActive("/dashboard/analytics/calls")}>
            Call Analytics
          </NavItem>
          <NavItem href="/dashboard/analytics/sms" icon={<MessageCircle className="h-5 w-5" />} active={isActive("/dashboard/analytics/sms")}>
            SMS Analytics
          </NavItem>
          
          <div className="pt-4 pb-2">
            <div className="px-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Configuration
            </div>
          </div>
          
          <NavItem href="/dashboard/sms-compliance" icon={<Shield className="h-5 w-5" />} active={isActive("/dashboard/sms-compliance")}>
            SMS Compliance
          </NavItem>
          <NavItem href="/dashboard/integrations" icon={<Plug className="h-5 w-5" />} active={isActive("/dashboard/integrations")}>
            Integrations
          </NavItem>
          <NavItem href="/dashboard/api-keys" icon={<Key className="h-5 w-5" />} active={isActive("/dashboard/api-keys")}>
            API Keys
          </NavItem>
          <NavItem href="/dashboard/team" icon={<Users className="h-5 w-5" />} active={isActive("/dashboard/team")}>
            Team
          </NavItem>
          <NavItem href="/dashboard/settings" icon={<Settings className="h-5 w-5" />} active={isActive("/dashboard/settings")}>
            Settings
          </NavItem>

          {(userInfo?.is_platform_admin || parsedUser?.user_type === "platform_admin") && (
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
                {userInfo?.display_name?.[0] || parsedUser?.first_name?.[0] || "?"}
              </div>
            )}
            <div className="flex-1">
              <div className="text-sm font-medium">{userInfo?.display_name || parsedUser?.first_name || "User"}</div>
              <div className="text-xs text-gray-400">{userInfo?.email || parsedUser?.email || ""}</div>
            </div>
          </div>
          <button
            onClick={handleLogout}
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
  badge,
}: {
  href: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  active?: boolean;
  badge?: number;
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
      <span className="text-sm font-medium flex-1">{children}</span>
      {badge != null && badge > 0 && (
        <span className="ml-auto flex items-center justify-center min-w-[18px] h-[18px] px-1 bg-red-600 rounded-full text-[10px] font-bold text-white leading-none">
          {badge > 99 ? "99+" : badge}
        </span>
      )}
    </Link>
  );
}
