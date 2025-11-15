import { Bot, Phone, BarChart, TrendingUp } from "lucide-react";

export default function DashboardPage() {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-6">Dashboard</h1>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <StatCard
          title="Total Assistants"
          value="2"
          icon={<Bot className="h-8 w-8 text-blue-400" />}
        />
        <StatCard
          title="Active Calls"
          value="0"
          icon={<Phone className="h-8 w-8 text-green-400" />}
        />
        <StatCard
          title="Calls Today"
          value="0"
          icon={<BarChart className="h-8 w-8 text-purple-400" />}
        />
        <StatCard
          title="Success Rate"
          value="100%"
          icon={<TrendingUp className="h-8 w-8 text-emerald-400" />}
        />
      </div>

      <div className="bg-[#141414] border border-gray-800 rounded-lg p-6">
        <h2 className="text-lg font-semibold mb-4">Recent Activity</h2>
        <p className="text-gray-400 text-sm">No recent activity</p>
      </div>
    </div>
  );
}

function StatCard({
  title,
  value,
  icon,
}: {
  title: string;
  value: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="bg-[#141414] border border-gray-800 rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="text-sm text-gray-400">{title}</div>
        {icon}
      </div>
      <div className="text-3xl font-bold">{value}</div>
    </div>
  );
}
