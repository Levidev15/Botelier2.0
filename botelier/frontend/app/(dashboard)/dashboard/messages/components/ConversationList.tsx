"use client";

import { Search, X, MessageSquare, Phone, Eye } from "lucide-react";
import {
  Conversation,
  formatRelativeTime,
  statusColor,
  isPresenceActive,
} from "../hooks/useSMSData";

interface Props {
  conversations: Conversation[];
  loading: boolean;
  search: string;
  setSearch: (v: string) => void;
  statusFilter: string;
  setStatusFilter: (v: string) => void;
  assistantFilter: string;
  setAssistantFilter: (v: string) => void;
  needsAttentionFilter: boolean;
  setNeedsAttentionFilter: (v: boolean) => void;
  assistants: { id: string; name: string }[];
  selectedConvId: string | null;
  onSelectConversation: (id: string) => void;
  onOpenSettings: () => void;
}

export function ConversationList({
  conversations,
  loading,
  search,
  setSearch,
  statusFilter,
  setStatusFilter,
  assistantFilter,
  setAssistantFilter,
  needsAttentionFilter,
  setNeedsAttentionFilter,
  assistants,
  selectedConvId,
  onSelectConversation,
  onOpenSettings,
}: Props) {
  const attentionCount = conversations.filter(c => c.needs_attention && c.status === "active").length;

  return (
    <div className="w-96 border-r border-gray-800 flex flex-col">
      {/* Header */}
      <div className="p-4 border-b border-gray-800">
        <div className="flex items-center justify-between mb-3">
          <h1 className="text-xl font-bold text-white">Messages</h1>
          <button
            onClick={onOpenSettings}
            className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
            title="Settings"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </button>
        </div>

        {/* Needs Attention toggle */}
        <button
          onClick={() => setNeedsAttentionFilter(!needsAttentionFilter)}
          className={`w-full flex items-center justify-between px-3 py-2 mb-2 rounded-lg text-xs font-medium transition-colors ${
            needsAttentionFilter
              ? "bg-amber-500/20 text-amber-300 border border-amber-500/40"
              : "bg-[#1a1a1a] text-gray-400 border border-gray-700 hover:border-amber-500/30 hover:text-amber-400"
          }`}
        >
          <div className="flex items-center gap-2">
            {needsAttentionFilter && (
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
            )}
            <span>Needs Attention</span>
          </div>
          {attentionCount > 0 && (
            <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-bold ${
              needsAttentionFilter ? "bg-amber-500 text-black" : "bg-amber-500/30 text-amber-300"
            }`}>
              {attentionCount}
            </span>
          )}
        </button>

        {/* Search */}
        <div className="relative mb-2">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by phone number..."
            className="w-full pl-9 pr-8 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500"
          />
          {search && (
            <button onClick={() => setSearch("")} className="absolute right-3 top-1/2 -translate-y-1/2">
              <X className="h-4 w-4 text-gray-500 hover:text-white" />
            </button>
          )}
        </div>

        {/* Status filter */}
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="w-full px-3 py-1.5 mb-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-xs text-gray-300 focus:outline-none focus:border-indigo-500"
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="closed">Closed</option>
          <option value="opted_out">Opted Out</option>
        </select>

        {/* Assistant filter */}
        <select
          value={assistantFilter}
          onChange={(e) => setAssistantFilter(e.target.value)}
          className="w-full px-3 py-1.5 bg-[#1a1a1a] border border-gray-700 rounded-lg text-xs text-gray-300 focus:outline-none focus:border-indigo-500"
        >
          <option value="">All assistants</option>
          {assistants.map(a => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
      </div>

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-12 text-gray-400 text-sm">Loading...</div>
        ) : conversations.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 px-4">
            <MessageSquare className="h-10 w-10 text-gray-600 mb-3" />
            <p className="text-gray-400 text-sm text-center">No conversations found</p>
            <p className="text-gray-500 text-xs text-center mt-1">
              {needsAttentionFilter
                ? "No conversations need attention right now"
                : "Conversations appear here when customers text your SMS-enabled numbers"
              }
            </p>
          </div>
        ) : (
          conversations.map((conv) => {
            const needsAgent = !!conv.needs_attention && conv.status === "active";
            return (
              <button
                key={conv.id}
                onClick={() => onSelectConversation(conv.id)}
                className={`w-full text-left p-4 border-b border-gray-800/50 hover:bg-[#1a1a1a] transition-colors border-l-2 ${
                  selectedConvId === conv.id
                    ? needsAgent
                      ? "bg-amber-500/10 border-l-amber-500"
                      : "bg-[#1a1a1a] border-l-indigo-500"
                    : needsAgent
                      ? "bg-amber-500/5 border-l-amber-500/70 hover:bg-amber-500/10"
                      : "border-l-transparent"
                }`}
              >
                {needsAgent && (
                  <div className="flex items-center gap-1.5 mb-2">
                    <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse flex-shrink-0" />
                    <span className="text-[10px] font-semibold text-amber-400 uppercase tracking-wide">
                      Needs Agent
                    </span>
                  </div>
                )}
                <div className="flex items-start justify-between mb-1">
                  <div className="flex items-center gap-2">
                    {conv.has_unread && (
                      <span className="h-2 w-2 rounded-full bg-indigo-500 flex-shrink-0" />
                    )}
                    <Phone className={`h-3.5 w-3.5 flex-shrink-0 ${needsAgent ? "text-amber-400" : "text-gray-400"}`} />
                    <span className={`text-sm ${conv.has_unread ? "font-semibold text-white" : "font-medium text-white"}`}>
                      {conv.customer_number}
                    </span>
                  </div>
                  <span className="text-xs text-gray-500 flex-shrink-0">
                    {formatRelativeTime(conv.last_message_at)}
                  </span>
                </div>
                <p className={`text-xs truncate mb-1.5 ${conv.has_unread ? "text-gray-200 font-medium" : "text-gray-400"}`}>
                  {conv.last_message_preview || "No messages"}
                </p>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${statusColor(conv.status)}`}>
                    {conv.status}
                  </span>
                  {conv.handler_mode === "human" ? (
                    <span className="text-[10px] px-1.5 py-0.5 rounded text-amber-400 bg-amber-400/15 border border-amber-400/30 font-medium">
                      Agent
                    </span>
                  ) : (
                    <span className="text-[10px] px-1.5 py-0.5 rounded text-indigo-400 bg-indigo-400/10">
                      AI
                    </span>
                  )}
                  <span className="text-[10px] text-gray-500">{conv.message_count} msgs</span>
                  {conv.active_agent_name && isPresenceActive(conv.agent_active_at) && (
                    <span className="flex items-center gap-1 text-[10px] text-amber-400">
                      <Eye className="h-2.5 w-2.5" />
                      {conv.active_agent_name}
                    </span>
                  )}
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
