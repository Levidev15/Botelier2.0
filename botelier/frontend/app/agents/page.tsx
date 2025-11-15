"use client";

import { useState } from "react";
import { Bot, Plus, Settings, Phone, Activity } from "lucide-react";
import Link from "next/link";

interface VoiceAgent {
  id: string;
  name: string;
  status: "active" | "draft" | "paused";
  sttProvider: string;
  llmProvider: string;
  ttsProvider: string;
  language: string;
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<VoiceAgent[]>([
    {
      id: "1",
      name: "Concierge Agent",
      status: "active",
      sttProvider: "Deepgram",
      llmProvider: "OpenAI GPT-4o",
      ttsProvider: "Cartesia",
      language: "English",
    },
  ]);

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16 items-center">
            <Link href="/" className="flex items-center">
              <Bot className="h-8 w-8 text-blue-600" />
              <span className="ml-2 text-2xl font-bold text-gray-900">Botelier</span>
            </Link>
            <div className="flex space-x-6">
              <NavLink href="/agents" icon={<Bot className="h-5 w-5" />} active>
                Voice Agents
              </NavLink>
              <NavLink href="/analytics" icon={<Activity className="h-5 w-5" />}>
                Analytics
              </NavLink>
              <NavLink href="/settings" icon={<Settings className="h-5 w-5" />}>
                Settings
              </NavLink>
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex justify-between items-center mb-8">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Voice Agents</h1>
            <p className="text-gray-600 mt-1">
              Manage your hotel's conversational AI agents
            </p>
          </div>
          <Link
            href="/agents/new"
            className="inline-flex items-center px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition"
          >
            <Plus className="h-5 w-5 mr-2" />
            Create Agent
          </Link>
        </div>

        <div className="grid gap-6">
          {agents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}
        </div>
      </main>
    </div>
  );
}

function NavLink({
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
      className={`inline-flex items-center space-x-2 px-3 py-2 rounded-md text-sm font-medium transition ${
        active
          ? "text-blue-600 bg-blue-50"
          : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
      }`}
    >
      {icon}
      <span>{children}</span>
    </Link>
  );
}

function AgentCard({ agent }: { agent: VoiceAgent }) {
  const statusColors = {
    active: "bg-green-100 text-green-800",
    draft: "bg-gray-100 text-gray-800",
    paused: "bg-yellow-100 text-yellow-800",
  };

  return (
    <div className="bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition">
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-start space-x-4">
          <div className="bg-blue-100 rounded-lg p-3">
            <Bot className="h-6 w-6 text-blue-600" />
          </div>
          <div>
            <h3 className="text-xl font-semibold text-gray-900">{agent.name}</h3>
            <span
              className={`inline-block mt-1 px-2 py-1 rounded-full text-xs font-medium ${
                statusColors[agent.status]
              }`}
            >
              {agent.status.charAt(0).toUpperCase() + agent.status.slice(1)}
            </span>
          </div>
        </div>
        <Link
          href={`/agents/${agent.id}/edit`}
          className="inline-flex items-center px-3 py-1.5 bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200 transition text-sm"
        >
          <Settings className="h-4 w-4 mr-1" />
          Configure
        </Link>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
        <InfoItem label="Speech Recognition" value={agent.sttProvider} />
        <InfoItem label="Language Model" value={agent.llmProvider} />
        <InfoItem label="Voice Synthesis" value={agent.ttsProvider} />
        <InfoItem label="Language" value={agent.language} />
      </div>

      <div className="mt-4 pt-4 border-t flex justify-between items-center">
        <div className="flex space-x-4 text-sm text-gray-600">
          <span className="flex items-center">
            <Phone className="h-4 w-4 mr-1" />
            No phone number
          </span>
          <span className="flex items-center">
            <Activity className="h-4 w-4 mr-1" />
            0 calls today
          </span>
        </div>
        <Link
          href={`/agents/${agent.id}`}
          className="text-sm text-blue-600 hover:text-blue-700 font-medium"
        >
          View details →
        </Link>
      </div>
    </div>
  );
}

function InfoItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-gray-500">{label}</p>
      <p className="text-sm font-medium text-gray-900 mt-0.5">{value}</p>
    </div>
  );
}
