"use client";

import { useState, useEffect } from "react";
import { Plus, Search, MoreVertical, Play, Pause, Copy, Bot } from "lucide-react";
import Link from "next/link";

interface Assistant {
  id: string;
  hotel_id: string;
  name: string;
  description: string | null;
  stt_provider: string;
  llm_provider: string;
  tts_provider: string;
  stt_model: string | null;
  llm_model: string | null;
  tts_voice: string | null;
  system_prompt: string | null;
  first_message: string | null;
  language: string;
  temperature: string;
  max_tokens: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string | null;
}

export default function AssistantsPage() {
  const [assistants, setAssistants] = useState<Assistant[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAssistants();
  }, []);

  const fetchAssistants = async () => {
    try {
      const hotelId = "6b410bcc-f843-40df-b32d-078d3e01ac7f"; // Demo Hotel - will come from auth context later
      const response = await fetch(`/api/assistants?hotel_id=${hotelId}`);
      const data = await response.json();
      setAssistants(data.assistants || []);
    } catch (error) {
      console.error("Failed to fetch assistants:", error);
      setAssistants([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-full">
      <div className="border-b border-gray-800 bg-[#0a0a0a] sticky top-0 z-10">
        <div className="px-8 py-6">
          <div className="flex justify-between items-center">
            <div>
              <h1 className="text-2xl font-bold">Assistants</h1>
              <p className="text-sm text-gray-400 mt-1">
                Manage your voice AI assistants
              </p>
            </div>
            <Link
              href="/dashboard/assistants/new"
              className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium"
            >
              <Plus className="h-4 w-4 mr-2" />
              Create Assistant
            </Link>
          </div>

          <div className="mt-6">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-500" />
              <input
                type="text"
                placeholder="Search assistants..."
                className="w-full pl-10 pr-4 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
              />
            </div>
          </div>
        </div>
      </div>

      <div className="p-8">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="text-gray-400">Loading assistants...</div>
          </div>
        ) : assistants.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-20 h-20 bg-gray-800 rounded-full flex items-center justify-center mb-4">
              <Bot className="h-10 w-10 text-gray-600" />
            </div>
            <h2 className="text-xl font-semibold text-white mb-2">No assistants yet</h2>
            <p className="text-gray-400 text-center mb-6 max-w-md">
              Create your first voice AI assistant to get started
            </p>
            <Link
              href="/dashboard/assistants/new"
              className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg transition-colors"
            >
              <Plus className="h-5 w-5" />
              <span>Create Assistant</span>
            </Link>
          </div>
        ) : (
          <div className="space-y-3">
            {assistants.map((assistant) => (
              <AssistantCard key={assistant.id} assistant={assistant} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function AssistantCard({ assistant }: { assistant: Assistant }) {
  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return "Never";
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffDays = Math.floor(diffHours / 24);

    if (diffHours < 1) return "Just now";
    if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
    if (diffDays < 7) return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;
    return date.toLocaleDateString();
  };

  return (
    <div className="bg-[#141414] border border-gray-800 rounded-lg p-5 hover:border-gray-700 transition group">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-4 flex-1">
          <div className="flex items-center space-x-3 flex-1">
            <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg flex items-center justify-center">
              <span className="text-lg font-bold">{assistant.name[0]}</span>
            </div>
            <div className="flex-1">
              <div className="flex items-center space-x-2">
                <h3 className="font-semibold text-gray-100">{assistant.name}</h3>
                {assistant.is_active ? (
                  <span className="flex items-center space-x-1 text-xs text-green-400">
                    <div className="w-1.5 h-1.5 bg-green-400 rounded-full"></div>
                    <span>Active</span>
                  </span>
                ) : (
                  <span className="text-xs text-gray-500">Draft</span>
                )}
              </div>
              <div className="flex items-center space-x-4 mt-1 text-xs text-gray-500">
                <span>Model: {assistant.llm_model || assistant.llm_provider}</span>
                <span>•</span>
                <span>Voice: {assistant.tts_voice || assistant.tts_provider}</span>
                <span>•</span>
                <span>Modified {formatDate(assistant.updated_at || assistant.created_at)}</span>
              </div>
            </div>
          </div>
        </div>

        <div className="flex items-center space-x-2">
          <button className="p-2 hover:bg-gray-800 rounded-lg transition opacity-0 group-hover:opacity-100">
            <Copy className="h-4 w-4 text-gray-400" />
          </button>
          <button className="p-2 hover:bg-gray-800 rounded-lg transition opacity-0 group-hover:opacity-100">
            {assistant.is_active ? (
              <Pause className="h-4 w-4 text-gray-400" />
            ) : (
              <Play className="h-4 w-4 text-gray-400" />
            )}
          </button>
          <Link
            href={`/dashboard/assistants/${assistant.id}`}
            className="px-4 py-2 bg-blue-600/10 hover:bg-blue-600/20 text-blue-400 rounded-lg transition text-sm font-medium"
          >
            Configure
          </Link>
          <button className="p-2 hover:bg-gray-800 rounded-lg transition">
            <MoreVertical className="h-4 w-4 text-gray-400" />
          </button>
        </div>
      </div>
    </div>
  );
}
