"use client";

import { useEffect, useState, useMemo } from "react";
import { SlidersHorizontal, Loader2 } from "lucide-react";
import {
  ResponsiveContainer,
  LineChart, Line,
  BarChart, Bar,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip,
} from "recharts";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import StatCard from "@/components/analytics/StatCard";
import DashboardWidget from "@/components/analytics/DashboardWidget";
import TimeRangePicker from "@/components/analytics/TimeRangePicker";
import CustomizePanel from "@/components/analytics/CustomizePanel";
import { useWidgetLayout, WidgetDef } from "@/components/analytics/useWidgetLayout";

const WIDGETS: WidgetDef[] = [
  { id: "total_convos", label: "Total Conversations", defaultVisible: true },
  { id: "active_convos", label: "Active Conversations", defaultVisible: true },
  { id: "escalation_rate", label: "Escalation Rate", defaultVisible: true },
  { id: "ai_handle_rate", label: "AI Handle Rate", defaultVisible: true },
  { id: "avg_response_time", label: "Avg Response Time", defaultVisible: true },
  { id: "volume_chart", label: "Volume Over Time", defaultVisible: true },
  { id: "handler_chart", label: "Handler Mode Split", defaultVisible: true },
  { id: "assistant_chart", label: "Conversations by Assistant", defaultVisible: true },
  { id: "message_volume", label: "Message Volume", defaultVisible: true },
  { id: "phone_numbers", label: "Top Phone Numbers", defaultVisible: true },
];

const CHART_COLORS = ["#3b82f6", "#8b5cf6", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4", "#ec4899", "#84cc16"];

function fmtSeconds(s: number | null) {
  if (s == null) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return sec > 0 ? `${m}m ${sec}s` : `${m}m`;
}

interface SMSStats {
  period: { from: string | null; to: string | null };
  overview: {
    total_conversations: number;
    active: number;
    closed: number;
    opted_out: number;
    ai_handled: number;
    human_handled: number;
    total_escalated: number;
    escalation_rate_pct: number;
    currently_needs_attention: number;
    total_messages: number;
    inbound_messages: number;
    outbound_messages: number;
    ai_responses: number;
    agent_responses: number;
    avg_messages_per_conversation: number;
    total_tokens_used: number;
  };
  volume_by_day: { date: string; conversations_started: number; messages: number }[];
  response_time: { avg_first_response_seconds: number | null; conversations_with_response: number };
  by_phone_number: { botelier_number: string; conversations: number; messages: number }[];
  by_assistant: { assistant_id: string; assistant_name: string; conversations: number }[];
  dispositions: { disposition_id: string; name: string; color: string | null; count: number }[];
  top_customers: { customer_number: string; conversation_count: number; message_count: number }[];
}

interface TooltipPayloadEntry {
  name?: string;
  value?: string | number;
  color?: string;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
  label?: string | number;
}

const CustomTooltipContent = ({ active, payload, label }: CustomTooltipProps) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#252525] border border-gray-700 rounded-lg px-3 py-2 text-sm shadow-lg">
      <p className="text-gray-400 mb-1">{String(label)}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color }} className="font-medium">
          {p.name}: {p.value}
        </p>
      ))}
    </div>
  );
};

export default function SMSAnalyticsPage() {
  const { accountId } = useAccountContext();
  const [days, setDays] = useState(7);
  const [retryKey, setRetryKey] = useState(0);
  const [data, setData] = useState<SMSStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [customizeOpen, setCustomizeOpen] = useState(false);
  const { visibility, toggle, resetDefaults, isVisible } = useWidgetLayout("sms_analytics", WIDGETS);

  useEffect(() => {
    if (!accountId) return;
    setLoading(true);
    setError(null);
    const now = new Date();
    const from = new Date(now.getTime() - days * 86_400_000);
    const params = new URLSearchParams({
      hotel_id: accountId,
      date_from: from.toISOString(),
      date_to: now.toISOString(),
    });
    fetch(`/api/sms/stats?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error(`Failed to load analytics (${r.status})`);
        return r.json();
      })
      .then(setData)
      .catch((err) => {
        console.error(err);
        setError(err.message || "Failed to load analytics");
      })
      .finally(() => setLoading(false));
  }, [accountId, days, retryKey]);

  const volumeData = useMemo(() => {
    if (!data) return [];
    return data.volume_by_day.map((d) => ({
      ...d,
      date: new Date(d.date).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    }));
  }, [data]);

  const handlerData = useMemo(() => {
    if (!data) return [];
    return [
      { name: "AI Handled", value: data.overview.ai_handled, color: "#3b82f6" },
      { name: "Human Handled", value: data.overview.human_handled, color: "#f59e0b" },
    ].filter((d) => d.value > 0);
  }, [data]);

  const messageData = useMemo(() => {
    if (!data) return [];
    return [
      { name: "Inbound", count: data.overview.inbound_messages },
      { name: "Outbound", count: data.overview.outbound_messages },
      { name: "AI Replies", count: data.overview.ai_responses },
      { name: "Agent Replies", count: data.overview.agent_responses },
    ];
  }, [data]);

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-gray-500" />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4">
        <p className="text-red-400">{error}</p>
        <button
          onClick={() => setRetryKey((k) => k + 1)}
          className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 rounded-lg text-white transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  const o = data?.overview;
  const aiHandleRate =
    o && o.total_conversations > 0
      ? Math.round((o.ai_handled / o.total_conversations) * 100)
      : 0;

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">SMS Analytics</h1>
          <p className="text-sm text-gray-400 mt-1">
            {o?.total_conversations ?? 0} conversations in the last {days} days
          </p>
        </div>
        <div className="flex items-center gap-3">
          <TimeRangePicker value={days} onChange={setDays} />
          <button
            onClick={() => setCustomizeOpen(true)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-[#1a1a1a] border border-gray-700 rounded-lg text-gray-300 hover:text-gray-100 hover:border-gray-600 transition-colors"
          >
            <SlidersHorizontal className="h-4 w-4" />
            Customize
          </button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-gray-500 mb-4">
          <Loader2 className="h-4 w-4 animate-spin" /> Refreshing…
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 mb-6">
        {isVisible("total_convos") && (
          <StatCard
            label="Total Conversations"
            value={o?.total_conversations ?? 0}
            sub={`${o?.total_messages ?? 0} messages`}
          />
        )}
        {isVisible("active_convos") && (
          <StatCard
            label="Active"
            value={o?.active ?? 0}
            sub={`${o?.currently_needs_attention ?? 0} need attention`}
            color="text-green-400"
          />
        )}
        {isVisible("escalation_rate") && (
          <StatCard
            label="Escalation Rate"
            value={`${o?.escalation_rate_pct ?? 0}%`}
            sub={`${o?.total_escalated ?? 0} escalated`}
            color="text-yellow-400"
          />
        )}
        {isVisible("ai_handle_rate") && (
          <StatCard
            label="AI Handle Rate"
            value={`${aiHandleRate}%`}
            sub={`${o?.ai_handled ?? 0} AI handled`}
            color="text-blue-400"
          />
        )}
        {isVisible("avg_response_time") && (
          <StatCard
            label="Avg Response Time"
            value={fmtSeconds(data?.response_time.avg_first_response_seconds ?? null)}
            sub={`${data?.response_time.conversations_with_response ?? 0} measured`}
          />
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {isVisible("volume_chart") && (
          <DashboardWidget title="Conversation Volume Over Time" span={2}>
            {volumeData.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={volumeData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                  <XAxis dataKey="date" tick={{ fill: "#9ca3af", fontSize: 12 }} />
                  <YAxis tick={{ fill: "#9ca3af", fontSize: 12 }} allowDecimals={false} />
                  <Tooltip content={<CustomTooltipContent />} />
                  <Line type="monotone" dataKey="conversations_started" name="Conversations" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3, fill: "#3b82f6" }} />
                  <Line type="monotone" dataKey="messages" name="Messages" stroke="#8b5cf6" strokeWidth={2} dot={{ r: 3, fill: "#8b5cf6" }} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-gray-500 text-sm py-12 text-center">No data for this period</p>
            )}
          </DashboardWidget>
        )}

        {isVisible("handler_chart") && (
          <DashboardWidget title="Handler Mode Split">
            {handlerData.length > 0 ? (
              <div className="flex items-center gap-6">
                <ResponsiveContainer width={140} height={140}>
                  <PieChart>
                    <Pie
                      data={handlerData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      innerRadius={35}
                      outerRadius={60}
                      paddingAngle={2}
                    >
                      {handlerData.map((d) => (
                        <Cell key={d.name} fill={d.color} />
                      ))}
                    </Pie>
                    <Tooltip content={<CustomTooltipContent />} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="flex-1 space-y-2">
                  {handlerData.map((d) => (
                    <div key={d.name} className="flex items-center justify-between text-sm">
                      <div className="flex items-center gap-2">
                        <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: d.color }} />
                        <span className="text-gray-300">{d.name}</span>
                      </div>
                      <span className="text-gray-400 font-medium">{d.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-gray-500 text-sm py-8 text-center">No data</p>
            )}
          </DashboardWidget>
        )}

        {isVisible("message_volume") && (
          <DashboardWidget title="Message Volume">
            {messageData.some((d) => d.count > 0) ? (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={messageData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                  <XAxis dataKey="name" tick={{ fill: "#9ca3af", fontSize: 12 }} />
                  <YAxis tick={{ fill: "#9ca3af", fontSize: 12 }} allowDecimals={false} />
                  <Tooltip content={<CustomTooltipContent />} />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                    {messageData.map((_, i) => (
                      <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-gray-500 text-sm py-8 text-center">No messages</p>
            )}
          </DashboardWidget>
        )}

        {isVisible("assistant_chart") && (
          <DashboardWidget title="Conversations by Assistant" span={2}>
            {data && data.by_assistant.length > 0 ? (
              <ResponsiveContainer width="100%" height={Math.max(180, data.by_assistant.length * 40)}>
                <BarChart data={data.by_assistant} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                  <XAxis type="number" tick={{ fill: "#9ca3af", fontSize: 12 }} allowDecimals={false} />
                  <YAxis
                    type="category"
                    dataKey="assistant_name"
                    tick={{ fill: "#9ca3af", fontSize: 12 }}
                    width={120}
                  />
                  <Tooltip content={<CustomTooltipContent />} />
                  <Bar dataKey="conversations" fill="#22c55e" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-gray-500 text-sm py-8 text-center">No data</p>
            )}
          </DashboardWidget>
        )}

        {isVisible("phone_numbers") && (
          <DashboardWidget title="Top Phone Numbers" span={2}>
            {data && data.by_phone_number.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-800">
                      <th className="text-left py-2 px-3 text-gray-400 font-medium">Phone Number</th>
                      <th className="text-right py-2 px-3 text-gray-400 font-medium">Conversations</th>
                      <th className="text-right py-2 px-3 text-gray-400 font-medium">Messages</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_phone_number.map((r) => (
                      <tr key={r.botelier_number} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                        <td className="py-2 px-3 text-gray-300 font-mono text-xs">{r.botelier_number}</td>
                        <td className="py-2 px-3 text-right text-gray-300">{r.conversations}</td>
                        <td className="py-2 px-3 text-right text-gray-400">{r.messages}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-gray-500 text-sm py-8 text-center">No data</p>
            )}
          </DashboardWidget>
        )}
      </div>

      <CustomizePanel
        open={customizeOpen}
        onClose={() => setCustomizeOpen(false)}
        widgets={WIDGETS}
        visibility={visibility}
        onToggle={toggle}
        onReset={resetDefaults}
      />
    </div>
  );
}
