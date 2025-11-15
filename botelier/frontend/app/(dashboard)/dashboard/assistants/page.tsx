"use client";

import { useState } from "react";
import { Plus, Search, MoreVertical, Play, Pause, Copy } from "lucide-react";
import Link from "next/link";

interface Assistant {
  id: string;
  name: string;
  status: "active" | "draft";
  model: string;
  voice: string;
  lastModified: string;
}

export default function AssistantsPage() {
  const [assistants] = useState<Assistant[]>([
    {
      id: "1",
      name: "Hotel Concierge",
      status: "active",
      model: "gpt-4o-mini",
      voice: "British Reading Lady",
      lastModified: "2 hours ago",
    },
    {
      id: "2",
      name: "Room Service",
      status: "draft",
      model: "gpt-4o",
      voice: "Friendly Reading Man",
      lastModified: "1 day ago",
    },
  ]);

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
        <div className="space-y-3">
          {assistants.map((assistant) => (
            <AssistantCard key={assistant.id} assistant={assistant} />
          ))}
        </div>
      </div>
    </div>
  );
}

function AssistantCard({ assistant }: { assistant: Assistant }) {
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
                {assistant.status === "active" ? (
                  <span className="flex items-center space-x-1 text-xs text-green-400">
                    <div className="w-1.5 h-1.5 bg-green-400 rounded-full"></div>
                    <span>Active</span>
                  </span>
                ) : (
                  <span className="text-xs text-gray-500">Draft</span>
                )}
              </div>
              <div className="flex items-center space-x-4 mt-1 text-xs text-gray-500">
                <span>Model: {assistant.model}</span>
                <span>•</span>
                <span>Voice: {assistant.voice}</span>
                <span>•</span>
                <span>Modified {assistant.lastModified}</span>
              </div>
            </div>
          </div>
        </div>

        <div className="flex items-center space-x-2">
          <button className="p-2 hover:bg-gray-800 rounded-lg transition opacity-0 group-hover:opacity-100">
            <Copy className="h-4 w-4 text-gray-400" />
          </button>
          <button className="p-2 hover:bg-gray-800 rounded-lg transition opacity-0 group-hover:opacity-100">
            {assistant.status === "active" ? (
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
