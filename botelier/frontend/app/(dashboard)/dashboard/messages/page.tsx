"use client";

import { useState, useEffect, useRef } from "react";
import { MessageSquare, Search, X, Send, Sparkles, Phone, Clock, ChevronDown } from "lucide-react";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { notify } from "@/lib/notifications";

interface Conversation {
  id: string;
  customer_number: string;
  botelier_number: string;
  status: string;
  message_count: number;
  last_message_at: string | null;
  created_at: string;
  assistant_id: string | null;
  tools_used: string | null;
  ai_summary: string | null;
  last_message_preview?: string;
}

interface Message {
  id: string;
  direction: string;
  sender: string;
  content: string;
  status: string;
  created_at: string;
  tool_calls: any;
}

interface ConversationDetail extends Conversation {
  messages: Message[];
}

export default function MessagesPage() {
  const { accountId, loading: contextLoading } = useAccountContext();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConv, setSelectedConv] = useState<ConversationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingConv, setLoadingConv] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [generatingSummary, setGeneratingSummary] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const fetchConversations = async () => {
    if (!accountId) return;
    try {
      setLoading(true);
      const params = new URLSearchParams({ hotel_id: accountId });
      if (search) params.set("search", search);
      if (statusFilter) params.set("status", statusFilter);
      const res = await fetch(`/api/sms/conversations?${params}`);
      const data = await res.json();
      setConversations(data.conversations || []);
    } catch (error) {
      console.error("Failed to fetch conversations:", error);
    } finally {
      setLoading(false);
    }
  };

  const fetchConversation = async (id: string) => {
    if (!accountId) return;
    try {
      setLoadingConv(true);
      const res = await fetch(`/api/sms/conversations/${id}?hotel_id=${accountId}`);
      const data = await res.json();
      setSelectedConv(data);
      setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }), 100);
    } catch (error) {
      console.error("Failed to fetch conversation:", error);
    } finally {
      setLoadingConv(false);
    }
  };

  const handleGenerateSummary = async () => {
    if (!selectedConv || !accountId) return;
    setGeneratingSummary(true);
    try {
      const res = await fetch(`/api/sms/conversations/${selectedConv.id}/generate-summary`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hotel_id: accountId }),
      });
      const data = await res.json();
      if (data.success) {
        setSelectedConv(prev => prev ? { ...prev, ai_summary: data.summary } : null);
        notify.success("Summary generated");
      }
    } catch (error) {
      notify.error("Failed to generate summary");
    } finally {
      setGeneratingSummary(false);
    }
  };

  const handleCloseConversation = async () => {
    if (!selectedConv || !accountId) return;
    try {
      const res = await fetch(`/api/sms/conversations/${selectedConv.id}/close`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hotel_id: accountId }),
      });
      if (res.ok) {
        notify.success("Conversation closed");
        setSelectedConv(prev => prev ? { ...prev, status: "closed" } : null);
        fetchConversations();
      }
    } catch (error) {
      notify.error("Failed to close conversation");
    }
  };

  useEffect(() => {
    if (!contextLoading && accountId) {
      fetchConversations();
    }
  }, [accountId, contextLoading]);

  useEffect(() => {
    if (accountId) {
      const debounce = setTimeout(() => fetchConversations(), 300);
      return () => clearTimeout(debounce);
    }
  }, [search, statusFilter]);

  const formatTime = (dateStr: string | null) => {
    if (!dateStr) return "";
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    return date.toLocaleDateString();
  };

  const formatFullTime = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "active": return "text-green-400 bg-green-400/10";
      case "closed": return "text-gray-400 bg-gray-400/10";
      case "opted_out": return "text-red-400 bg-red-400/10";
      default: return "text-gray-400 bg-gray-400/10";
    }
  };

  return (
    <div className="flex h-full bg-[#0a0a0a]">
      {/* Left Panel - Conversation List */}
      <div className="w-96 border-r border-gray-800 flex flex-col">
        <div className="p-4 border-b border-gray-800">
          <h1 className="text-xl font-bold text-white mb-3">Messages</h1>
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
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="w-full px-3 py-1.5 bg-[#1a1a1a] border border-gray-700 rounded-lg text-xs text-gray-300 focus:outline-none focus:border-indigo-500"
          >
            <option value="">All conversations</option>
            <option value="active">Active</option>
            <option value="closed">Closed</option>
            <option value="opted_out">Opted Out</option>
          </select>
        </div>

        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-gray-400 text-sm">Loading...</div>
          ) : conversations.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 px-4">
              <MessageSquare className="h-10 w-10 text-gray-600 mb-3" />
              <p className="text-gray-400 text-sm text-center">No SMS conversations yet</p>
              <p className="text-gray-500 text-xs text-center mt-1">
                Conversations will appear here when customers text your SMS-enabled numbers
              </p>
            </div>
          ) : (
            conversations.map((conv) => (
              <button
                key={conv.id}
                onClick={() => fetchConversation(conv.id)}
                className={`w-full text-left p-4 border-b border-gray-800/50 hover:bg-[#1a1a1a] transition-colors ${
                  selectedConv?.id === conv.id ? "bg-[#1a1a1a] border-l-2 border-l-indigo-500" : ""
                }`}
              >
                <div className="flex items-start justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <Phone className="h-3.5 w-3.5 text-gray-400" />
                    <span className="text-sm font-medium text-white">{conv.customer_number}</span>
                  </div>
                  <span className="text-xs text-gray-500">{formatTime(conv.last_message_at)}</span>
                </div>
                <p className="text-xs text-gray-400 truncate mb-1.5">
                  {conv.last_message_preview || "No messages"}
                </p>
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${getStatusColor(conv.status)}`}>
                    {conv.status}
                  </span>
                  <span className="text-[10px] text-gray-500">{conv.message_count} messages</span>
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Right Panel - Conversation Thread */}
      <div className="flex-1 flex flex-col">
        {!selectedConv ? (
          <div className="flex-1 flex flex-col items-center justify-center text-gray-400">
            <MessageSquare className="h-12 w-12 text-gray-600 mb-4" />
            <p className="text-lg font-medium">Select a conversation</p>
            <p className="text-sm text-gray-500 mt-1">Choose a conversation from the list to view messages</p>
          </div>
        ) : loadingConv ? (
          <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">Loading messages...</div>
        ) : (
          <>
            {/* Thread Header */}
            <div className="p-4 border-b border-gray-800 bg-[#141414]">
              <div className="flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-semibold text-white">{selectedConv.customer_number}</h2>
                    <span className={`text-xs px-2 py-0.5 rounded ${getStatusColor(selectedConv.status)}`}>
                      {selectedConv.status}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {selectedConv.botelier_number} | {selectedConv.message_count} messages
                    {selectedConv.tools_used && ` | Tools: ${selectedConv.tools_used}`}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleGenerateSummary}
                    disabled={generatingSummary}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600/10 hover:bg-indigo-600/20 text-indigo-400 rounded-lg text-xs transition-colors disabled:opacity-50"
                  >
                    <Sparkles className="h-3.5 w-3.5" />
                    {generatingSummary ? "Generating..." : "AI Summary"}
                  </button>
                  {selectedConv.status === "active" && (
                    <button
                      onClick={handleCloseConversation}
                      className="px-3 py-1.5 bg-gray-700/50 hover:bg-gray-700 text-gray-300 rounded-lg text-xs transition-colors"
                    >
                      Close
                    </button>
                  )}
                </div>
              </div>

              {selectedConv.ai_summary && (
                <div className="mt-3 p-3 bg-indigo-600/5 border border-indigo-600/20 rounded-lg">
                  <div className="flex items-center gap-1.5 mb-1">
                    <Sparkles className="h-3 w-3 text-indigo-400" />
                    <span className="text-xs font-medium text-indigo-400">AI Summary</span>
                  </div>
                  <p className="text-xs text-gray-300 whitespace-pre-wrap">{selectedConv.ai_summary}</p>
                </div>
              )}
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {selectedConv.messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex ${msg.sender === "customer" ? "justify-start" : "justify-end"}`}
                >
                  <div
                    className={`max-w-[70%] rounded-2xl px-4 py-2.5 ${
                      msg.sender === "customer"
                        ? "bg-[#1a1a1a] border border-gray-700 text-white rounded-bl-sm"
                        : "bg-indigo-600 text-white rounded-br-sm"
                    }`}
                  >
                    <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                    <div className={`flex items-center gap-1.5 mt-1 ${
                      msg.sender === "customer" ? "text-gray-500" : "text-indigo-200"
                    }`}>
                      <span className="text-[10px]">{formatFullTime(msg.created_at)}</span>
                      {msg.tool_calls && msg.tool_calls.length > 0 && (
                        <span className="text-[10px] px-1 bg-white/10 rounded">
                          {msg.tool_calls.map((tc: any) => tc.name).join(", ")}
                        </span>
                      )}
                      {msg.status === "failed" && (
                        <span className="text-[10px] text-red-400">Failed</span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
