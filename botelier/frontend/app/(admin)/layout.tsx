"use client";

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
  Mail,
  Sun,
  Moon,
} from "lucide-react";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { useTheme } from "@/lib/theme/ThemeContext";

const adminNavItems = [
  { href: "/admin", label: "Dashboard", icon: BarChart3 },
  { href: "/admin/accounts", label: "Accounts", icon: Building2 },
  { href: "/admin/invitations", label: "Invitations", icon: Mail },
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/settings", label: "Settings", icon: Settings },
];

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { token, loading: tokenLoading, authFetch, logout } = useAuthToken();
  const { theme, toggleTheme } = useTheme();
  const router = useRouter();
  const pathname = usePathname();
  const [userInfo, setUserInfo] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  useEffect(() => {
    const checkAuth = async () => {
      const storedToken = localStorage.getItem("botelier_token");
      const storedUser = localStorage.getItem("botelier_user");
      
      if (!storedToken || !storedUser) {
        router.push("/login?callbackUrl=/admin");
        return;
      }
      
      try {
        const user = JSON.parse(storedUser);
        if (user.user_type !== "platform_admin") {
          router.push("/dashboard");
          return;
        }
        
        setUserInfo(user);
        setIsAuthenticated(true);
        setLoading(false);
      } catch (err) {
        console.error("Error parsing user:", err);
        router.push("/login?callbackUrl=/admin");
      }
    };
    
    checkAuth();
  }, [router]);

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  if (tokenLoading || loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
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

  return (
    <div className="min-h-screen bg-background flex text-foreground">
      <aside className="w-64 bg-surface border-r border-border flex flex-col">
        <div className="p-4 border-b border-border">
          <div className="flex items-center gap-2">
            <Shield className="h-6 w-6 text-blue-500" />
            <span className="text-lg font-semibold text-foreground">
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
                    ? "bg-blue-600/20 text-blue-500"
                    : "text-muted-foreground hover:text-foreground hover:bg-hover-bg"
                }`}
              >
                <item.icon className="h-5 w-5" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="p-4 border-t border-border">
          <Link
            href="/dashboard"
            className="flex items-center gap-3 px-3 py-2 text-muted-foreground hover:text-foreground hover:bg-hover-bg rounded-lg transition-colors"
          >
            <ChevronRight className="h-5 w-5" />
            <span>Go to Dashboard</span>
          </Link>

          <div className="mt-4 px-3 py-2">
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-3 flex-1 min-w-0">
                {userInfo?.profile_image_url ? (
                  <img
                    src={userInfo.profile_image_url}
                    alt=""
                    className="h-8 w-8 rounded-full object-cover flex-shrink-0"
                  />
                ) : (
                  <div className="h-8 w-8 rounded-full bg-blue-600 flex items-center justify-center text-white text-sm font-medium flex-shrink-0">
                    {userInfo?.display_name?.[0] || "?"}
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-foreground truncate">
                    {userInfo?.display_name || "Admin"}
                  </p>
                  <p className="text-xs text-muted-foreground truncate">
                    {userInfo?.email || "Platform Admin"}
                  </p>
                </div>
              </div>
              <button
                onClick={toggleTheme}
                title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
                className="flex-shrink-0 p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-hover-bg transition-colors"
              >
                {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </button>
            </div>
          </div>

          <button
            onClick={handleLogout}
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
