import { Bot, LayoutDashboard, Phone, BarChart, Settings, Key, Users, Wrench, BookOpen } from "lucide-react";
import Link from "next/link";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-screen bg-[#0a0a0a] text-gray-100">
      <aside className="w-64 bg-[#141414] border-r border-gray-800 flex flex-col">
        <div className="p-6 border-b border-gray-800">
          <Link href="/" className="flex items-center space-x-2">
            <Bot className="h-8 w-8 text-blue-500" />
            <span className="text-xl font-bold">Botelier</span>
          </Link>
        </div>
        
        <nav className="flex-1 p-4 space-y-1">
          <NavItem href="/dashboard" icon={<LayoutDashboard className="h-5 w-5" />}>
            Dashboard
          </NavItem>
          <NavItem href="/dashboard/assistants" icon={<Bot className="h-5 w-5" />} active>
            Assistants
          </NavItem>
          <NavItem href="/dashboard/tools" icon={<Wrench className="h-5 w-5" />}>
            Tools
          </NavItem>
          <NavItem href="/dashboard/knowledge-bases" icon={<BookOpen className="h-5 w-5" />}>
            Knowledge Bases
          </NavItem>
          <NavItem href="/dashboard/phone-numbers" icon={<Phone className="h-5 w-5" />}>
            Phone Numbers
          </NavItem>
          <NavItem href="/dashboard/call-logs" icon={<BarChart className="h-5 w-5" />}>
            Call Logs
          </NavItem>
          
          <div className="pt-4 pb-2">
            <div className="px-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Configuration
            </div>
          </div>
          
          <NavItem href="/dashboard/api-keys" icon={<Key className="h-5 w-5" />}>
            API Keys
          </NavItem>
          <NavItem href="/dashboard/team" icon={<Users className="h-5 w-5" />}>
            Team
          </NavItem>
          <NavItem href="/dashboard/settings" icon={<Settings className="h-5 w-5" />}>
            Settings
          </NavItem>
        </nav>

        <div className="p-4 border-t border-gray-800">
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 bg-blue-600 rounded-full flex items-center justify-center text-sm font-semibold">
              H
            </div>
            <div className="flex-1">
              <div className="text-sm font-medium">Hotel Demo</div>
              <div className="text-xs text-gray-400">hotel@example.com</div>
            </div>
          </div>
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
