"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  MessageSquare, Search, X, Send, Sparkles, Phone, Eye,
  Paperclip, Bookmark, Settings, Volume2, VolumeX, Bell, BellOff,
  Plus, Trash2, Edit2, Check, FileText, Image as ImageIcon, ChevronDown,
} from "lucide-react";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
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
  has_unread?: boolean;
  active_agent_id?: string | null;
  active_agent_name?: string | null;
  agent_active_at?: string | null;
}

interface Message {
  id: string;
  direction: string;
  sender: string;
  content: string;
  status: string;
  created_at: string;
  tool_calls: any;
  session_boundary?: boolean;
  media_urls?: string[] | null;
}

interface ConversationDetail extends Conversation {
  messages: Message[];
}

interface SMSTemplate {
  id: string;
  hotel_id: string;
  name: string;
  content: string;
  category: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string | null;
}

interface NotificationSettings {
  sound_enabled: boolean;
  visual_enabled: boolean;
  threshold: number;
  sound_type: string;
}

interface AttachedFile {
  url: string;
  filename: string;
  content_type: string;
}

const PRESENCE_STALE_SECONDS = 30;

function isPresenceActive(agentActiveAt: string | null | undefined): boolean {
  if (!agentActiveAt) return false;
  const activeTime = new Date(agentActiveAt).getTime();
  const now = Date.now();
  return (now - activeTime) < PRESENCE_STALE_SECONDS * 1000;
}

function isImageUrl(url: string): boolean {
  return /\.(jpg|jpeg|png|gif|webp)(\?|$)/i.test(url);
}

export default function MessagesPage() {
  const { accountId, loading: contextLoading } = useAccountContext();
  const { user } = useAuthToken();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConv, setSelectedConv] = useState<ConversationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingConv, setLoadingConv] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [generatingSummary, setGeneratingSummary] = useState(false);
  const [replyText, setReplyText] = useState("");
  const [sendingReply, setSendingReply] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const presenceIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const lastPresenceConvIdRef = useRef<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([]);
  const [uploading, setUploading] = useState(false);

  const [templates, setTemplates] = useState<SMSTemplate[]>([]);
  const [showTemplates, setShowTemplates] = useState(false);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<"notifications" | "templates">("templates");
  const [notifSettings, setNotifSettings] = useState<NotificationSettings>({
    sound_enabled: true,
    visual_enabled: true,
    threshold: 1,
    sound_type: "chime",
  });
  const [savingSettings, setSavingSettings] = useState(false);

  const [editingTemplate, setEditingTemplate] = useState<SMSTemplate | null>(null);
  const [newTemplate, setNewTemplate] = useState({ name: "", content: "", category: "" });
  const [showNewTemplate, setShowNewTemplate] = useState(false);

  const prevUnreadRef = useRef<number>(0);
  const unreadPollRef = useRef<NodeJS.Timeout | null>(null);

  // Presence
  const sendPresenceHeartbeat = useCallback(async (convId: string) => {
    if (!accountId || !user?.id) return;
    try {
      await fetch(`/api/sms/conversations/${convId}/presence`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          hotel_id: accountId,
          agent_id: user.id,
          agent_name: user.email?.split("@")[0] || "Agent",
        }),
      });
    } catch {}
  }, [accountId, user]);

  const clearPresence = useCallback(async (convId: string) => {
    if (!accountId || !user?.id) return;
    try {
      await fetch(`/api/sms/conversations/${convId}/presence`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hotel_id: accountId, agent_id: user.id }),
      });
    } catch {}
  }, [accountId, user]);

  const startPresenceHeartbeat = useCallback((convId: string) => {
    if (presenceIntervalRef.current) clearInterval(presenceIntervalRef.current);
    if (lastPresenceConvIdRef.current && lastPresenceConvIdRef.current !== convId) {
      clearPresence(lastPresenceConvIdRef.current);
    }
    lastPresenceConvIdRef.current = convId;
    sendPresenceHeartbeat(convId);
    presenceIntervalRef.current = setInterval(() => sendPresenceHeartbeat(convId), 15000);
  }, [sendPresenceHeartbeat, clearPresence]);

  const stopPresenceHeartbeat = useCallback(() => {
    if (presenceIntervalRef.current) {
      clearInterval(presenceIntervalRef.current);
      presenceIntervalRef.current = null;
    }
    if (lastPresenceConvIdRef.current) {
      clearPresence(lastPresenceConvIdRef.current);
      lastPresenceConvIdRef.current = null;
    }
  }, [clearPresence]);

  useEffect(() => {
    return () => { stopPresenceHeartbeat(); };
  }, [stopPresenceHeartbeat]);

  // Data fetching
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
      startPresenceHeartbeat(id);
      fetch(`/api/sms/conversations/${id}/read`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hotel_id: accountId }),
      }).then(() => {
        setConversations(prev => prev.map(c => c.id === id ? { ...c, has_unread: false } : c));
      }).catch(() => {});
    } catch (error) {
      console.error("Failed to fetch conversation:", error);
    } finally {
      setLoadingConv(false);
    }
  };

  const fetchTemplates = useCallback(async () => {
    if (!accountId) return;
    try {
      const res = await fetch(`/api/sms/templates?hotel_id=${accountId}`);
      const data = await res.json();
      setTemplates(data);
    } catch {}
  }, [accountId]);

  const fetchNotifSettings = useCallback(async () => {
    if (!accountId) return;
    try {
      const res = await fetch(`/api/sms/settings/notifications?hotel_id=${accountId}`);
      const data = await res.json();
      setNotifSettings(data);
    } catch {}
  }, [accountId]);

  // Actions
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
    } catch {
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
    } catch {
      notify.error("Failed to close conversation");
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || !accountId) return;
    if (attachedFiles.length + files.length > 10) {
      notify.error("Maximum 10 attachments allowed");
      return;
    }
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        if (file.size > 5 * 1024 * 1024) {
          notify.error(`${file.name} exceeds 5MB limit`);
          continue;
        }
        const formData = new FormData();
        formData.append("file", file);
        formData.append("hotel_id", accountId);
        const res = await fetch("/api/sms/upload", { method: "POST", body: formData });
        const data = await res.json();
        if (!res.ok) {
          notify.error(data.detail || `Failed to upload ${file.name}`);
          continue;
        }
        setAttachedFiles(prev => [...prev, {
          url: data.url,
          filename: data.filename,
          content_type: data.content_type,
        }]);
      }
    } catch {
      notify.error("Upload failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleSendReply = async () => {
    if (!selectedConv || !accountId || sendingReply) return;
    if (!replyText.trim() && attachedFiles.length === 0) return;
    setSendingReply(true);
    try {
      const body: any = { hotel_id: accountId, message: replyText.trim() };
      if (attachedFiles.length > 0) {
        body.media_urls = attachedFiles.map(f => f.url);
      }
      const res = await fetch(`/api/sms/conversations/${selectedConv.id}/reply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        notify.error(data.detail || "Failed to send reply");
        return;
      }
      setReplyText("");
      setAttachedFiles([]);
      fetchConversation(selectedConv.id);
      fetchConversations();
    } catch {
      notify.error("Failed to send reply");
    } finally {
      setSendingReply(false);
    }
  };

  const handleInsertTemplate = (template: SMSTemplate) => {
    let content = template.content;
    if (selectedConv) {
      content = content.replace(/\{\{customer_number\}\}/g, selectedConv.customer_number);
      content = content.replace(/\{\{date\}\}/g, new Date().toLocaleDateString());
      content = content.replace(/\{\{time\}\}/g, new Date().toLocaleTimeString());
    }
    setReplyText(prev => prev + content);
    setShowTemplates(false);
  };

  const handleSaveTemplate = async () => {
    if (!accountId || !newTemplate.name.trim() || !newTemplate.content.trim()) return;
    try {
      const res = await fetch("/api/sms/templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          hotel_id: accountId,
          name: newTemplate.name.trim(),
          content: newTemplate.content.trim(),
          category: newTemplate.category.trim() || null,
        }),
      });
      if (res.ok) {
        setNewTemplate({ name: "", content: "", category: "" });
        setShowNewTemplate(false);
        fetchTemplates();
        notify.success("Template created");
      }
    } catch {
      notify.error("Failed to create template");
    }
  };

  const handleUpdateTemplate = async (template: SMSTemplate) => {
    if (!accountId) return;
    try {
      const res = await fetch(`/api/sms/templates/${template.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          hotel_id: accountId,
          name: template.name,
          content: template.content,
          category: template.category || null,
          is_active: template.is_active,
        }),
      });
      if (res.ok) {
        setEditingTemplate(null);
        fetchTemplates();
        notify.success("Template updated");
      }
    } catch {
      notify.error("Failed to update template");
    }
  };

  const handleDeleteTemplate = async (id: string) => {
    if (!accountId) return;
    try {
      await fetch(`/api/sms/templates/${id}?hotel_id=${accountId}`, { method: "DELETE" });
      fetchTemplates();
      notify.success("Template deleted");
    } catch {
      notify.error("Failed to delete template");
    }
  };

  const handleSaveNotifSettings = async () => {
    if (!accountId) return;
    setSavingSettings(true);
    try {
      await fetch("/api/sms/settings/notifications", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hotel_id: accountId, ...notifSettings }),
      });
      notify.success("Notification settings saved");
    } catch {
      notify.error("Failed to save settings");
    } finally {
      setSavingSettings(false);
    }
  };

  const playNotificationSound = useCallback(() => {
    if (!notifSettings.sound_enabled) return;
    try {
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      const freqs: Record<string, number> = { chime: 880, bell: 660, ding: 1200 };
      osc.frequency.value = freqs[notifSettings.sound_type] || 880;
      osc.type = "sine";
      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.5);
    } catch {}
  }, [notifSettings]);

  // Effects
  useEffect(() => {
    if (!contextLoading && accountId) {
      fetchConversations();
      fetchTemplates();
      fetchNotifSettings();
    }
  }, [accountId, contextLoading]);

  useEffect(() => {
    if (accountId) {
      const debounce = setTimeout(() => fetchConversations(), 300);
      return () => clearTimeout(debounce);
    }
  }, [search, statusFilter]);

  useEffect(() => {
    if (!accountId) return;
    const poll = async () => {
      try {
        const res = await fetch(`/api/sms/unread-count?hotel_id=${accountId}`);
        const data = await res.json();
        const count = data.unread_count || 0;
        if (count > prevUnreadRef.current && count >= notifSettings.threshold) {
          if (document.hidden) {
            playNotificationSound();
          }
          if (notifSettings.visual_enabled) {
            notify.info(`${count} unread message${count > 1 ? "s" : ""}`);
          }
        }
        prevUnreadRef.current = count;
      } catch {}
    };
    unreadPollRef.current = setInterval(poll, 30000);
    poll();
    return () => { if (unreadPollRef.current) clearInterval(unreadPollRef.current); };
  }, [accountId, notifSettings, playNotificationSound]);

  // Helpers
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

  const groupedTemplates = templates.reduce<Record<string, SMSTemplate[]>>((acc, t) => {
    const cat = t.category || "General";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(t);
    return acc;
  }, {});

  return (
    <div className="flex h-full bg-[#0a0a0a]">
      {/* Left Panel - Conversation List */}
      <div className="w-96 border-r border-gray-800 flex flex-col">
        <div className="p-4 border-b border-gray-800">
          <div className="flex items-center justify-between mb-3">
            <h1 className="text-xl font-bold text-white">Messages</h1>
            <button
              onClick={() => { setSettingsOpen(true); fetchTemplates(); fetchNotifSettings(); }}
              className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
              title="Settings"
            >
              <Settings className="h-4 w-4" />
            </button>
          </div>
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
                    {conv.has_unread && (
                      <span className="h-2 w-2 rounded-full bg-indigo-500 flex-shrink-0" />
                    )}
                    <Phone className="h-3.5 w-3.5 text-gray-400" />
                    <span className={`text-sm ${conv.has_unread ? "font-semibold text-white" : "font-medium text-white"}`}>{conv.customer_number}</span>
                  </div>
                  <span className="text-xs text-gray-500">{formatTime(conv.last_message_at)}</span>
                </div>
                <p className={`text-xs truncate mb-1.5 ${conv.has_unread ? "text-gray-200 font-medium" : "text-gray-400"}`}>
                  {conv.last_message_preview || "No messages"}
                </p>
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${getStatusColor(conv.status)}`}>
                    {conv.status}
                  </span>
                  <span className="text-[10px] text-gray-500">{conv.message_count} messages</span>
                  {conv.active_agent_name && isPresenceActive(conv.agent_active_at) && (
                    <span className="flex items-center gap-1 text-[10px] text-amber-400">
                      <Eye className="h-2.5 w-2.5" />
                      {conv.active_agent_name}
                    </span>
                  )}
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
                  {selectedConv.active_agent_name &&
                   isPresenceActive(selectedConv.agent_active_at) &&
                   selectedConv.active_agent_id !== user?.id && (
                    <div className="flex items-center gap-1.5 mt-1">
                      <Eye className="h-3 w-3 text-amber-400" />
                      <span className="text-[11px] text-amber-400">{selectedConv.active_agent_name} is viewing</span>
                    </div>
                  )}
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
                <div key={msg.id}>
                  {msg.session_boundary && (
                    <div className="flex items-center gap-3 my-4">
                      <div className="flex-1 border-t border-dashed border-gray-700" />
                      <span className="text-[10px] text-gray-500 whitespace-nowrap px-2">
                        New session — {formatFullTime(msg.created_at)}
                      </span>
                      <div className="flex-1 border-t border-dashed border-gray-700" />
                    </div>
                  )}
                  <div
                    className={`flex ${msg.sender === "customer" ? "justify-start" : "justify-end"}`}
                  >
                    <div
                      className={`max-w-[70%] rounded-2xl px-4 py-2.5 ${
                        msg.sender === "customer"
                          ? "bg-[#1a1a1a] border border-gray-700 text-white rounded-bl-sm"
                          : msg.sender === "agent"
                          ? "bg-emerald-600 text-white rounded-br-sm"
                          : "bg-indigo-600 text-white rounded-br-sm"
                      }`}
                    >
                      {msg.content && <p className="text-sm whitespace-pre-wrap">{msg.content}</p>}
                      {msg.media_urls && msg.media_urls.length > 0 && (
                        <div className="mt-2 space-y-2">
                          {msg.media_urls.map((url, i) =>
                            isImageUrl(url) ? (
                              <a key={i} href={url} target="_blank" rel="noopener noreferrer">
                                <img
                                  src={url}
                                  alt="Attachment"
                                  className="max-w-full max-h-48 rounded-lg border border-white/10"
                                />
                              </a>
                            ) : (
                              <a
                                key={i}
                                href={url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="flex items-center gap-2 px-3 py-2 bg-white/10 rounded-lg hover:bg-white/20 transition-colors"
                              >
                                <FileText className="h-4 w-4" />
                                <span className="text-xs underline">Download attachment</span>
                              </a>
                            )
                          )}
                        </div>
                      )}
                      <div className={`flex items-center gap-1.5 mt-1 ${
                        msg.sender === "customer" ? "text-gray-500" : msg.sender === "agent" ? "text-emerald-200" : "text-indigo-200"
                      }`}>
                        <span className="text-[10px]">{formatFullTime(msg.created_at)}</span>
                        {msg.sender === "agent" && (
                          <span className="text-[10px] px-1 bg-white/10 rounded">Agent</span>
                        )}
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
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>

            {selectedConv.status === "active" && (
              <div className="p-3 border-t border-gray-800 bg-[#141414]">
                {attachedFiles.length > 0 && (
                  <div className="flex flex-wrap gap-2 mb-2 px-1">
                    {attachedFiles.map((f, i) => (
                      <div key={i} className="flex items-center gap-1.5 px-2 py-1 bg-[#1a1a1a] border border-gray-700 rounded-lg text-xs text-gray-300">
                        {f.content_type.startsWith("image/") ? (
                          <ImageIcon className="h-3 w-3 text-indigo-400" />
                        ) : (
                          <FileText className="h-3 w-3 text-indigo-400" />
                        )}
                        <span className="max-w-[120px] truncate">{f.filename}</span>
                        <button onClick={() => setAttachedFiles(prev => prev.filter((_, idx) => idx !== i))} className="text-gray-500 hover:text-red-400">
                          <X className="h-3 w-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/jpeg,image/png,image/gif,image/webp,application/pdf"
                    multiple
                    onChange={handleFileSelect}
                    className="hidden"
                  />
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploading || attachedFiles.length >= 10}
                    className="p-2.5 text-gray-400 hover:text-white hover:bg-[#1a1a1a] rounded-xl transition-colors disabled:opacity-50"
                    title="Attach file"
                  >
                    <Paperclip className="h-4 w-4" />
                  </button>
                  <div className="relative">
                    <button
                      onClick={() => setShowTemplates(!showTemplates)}
                      className="p-2.5 text-gray-400 hover:text-white hover:bg-[#1a1a1a] rounded-xl transition-colors"
                      title="Templates"
                    >
                      <Bookmark className="h-4 w-4" />
                    </button>
                    {showTemplates && (
                      <div className="absolute bottom-12 left-0 w-72 bg-[#1a1a1a] border border-gray-700 rounded-xl shadow-xl z-50 max-h-80 overflow-y-auto">
                        <div className="p-2 border-b border-gray-700">
                          <span className="text-xs font-medium text-gray-400">Templates</span>
                        </div>
                        {templates.length === 0 ? (
                          <div className="p-4 text-center text-xs text-gray-500">
                            No templates yet. Create one in Settings.
                          </div>
                        ) : (
                          Object.entries(groupedTemplates).map(([cat, tmpls]) => (
                            <div key={cat}>
                              <div className="px-3 py-1.5 text-[10px] font-medium text-gray-500 uppercase tracking-wider bg-[#141414]">
                                {cat}
                              </div>
                              {tmpls.filter(t => t.is_active).map(t => (
                                <button
                                  key={t.id}
                                  onClick={() => handleInsertTemplate(t)}
                                  className="w-full text-left px-3 py-2 hover:bg-[#252525] transition-colors"
                                >
                                  <span className="text-xs font-medium text-white">{t.name}</span>
                                  <p className="text-[10px] text-gray-500 truncate mt-0.5">{t.content}</p>
                                </button>
                              ))}
                            </div>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                  <input
                    type="text"
                    value={replyText}
                    onChange={(e) => setReplyText(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSendReply(); } }}
                    placeholder="Type a reply..."
                    disabled={sendingReply}
                    className="flex-1 px-4 py-2.5 bg-[#1a1a1a] border border-gray-700 rounded-xl text-sm text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500 disabled:opacity-50"
                  />
                  <button
                    onClick={handleSendReply}
                    disabled={sendingReply || (!replyText.trim() && attachedFiles.length === 0)}
                    className="p-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded-xl transition-colors"
                  >
                    <Send className="h-4 w-4" />
                  </button>
                </div>
                <p className="text-[10px] text-gray-600 mt-1.5 ml-1">
                  {uploading ? "Uploading..." : "Replies are sent as your team, not the AI"}
                </p>
              </div>
            )}
          </>
        )}
      </div>

      {/* Settings Slide-out Panel */}
      {settingsOpen && (
        <>
          <div
            className="fixed inset-0 bg-black/40 z-40"
            onClick={() => setSettingsOpen(false)}
          />
          <div className="fixed right-0 top-0 bottom-0 w-[420px] bg-[#111111] border-l border-gray-800 z-50 flex flex-col shadow-2xl">
            <div className="flex items-center justify-between p-4 border-b border-gray-800">
              <h2 className="text-lg font-semibold text-white">Messages Settings</h2>
              <button onClick={() => setSettingsOpen(false)} className="p-1 text-gray-400 hover:text-white">
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex border-b border-gray-800">
              <button
                onClick={() => setSettingsTab("templates")}
                className={`flex-1 py-2.5 text-xs font-medium transition-colors ${
                  settingsTab === "templates" ? "text-indigo-400 border-b-2 border-indigo-400" : "text-gray-500 hover:text-gray-300"
                }`}
              >
                Templates
              </button>
              <button
                onClick={() => setSettingsTab("notifications")}
                className={`flex-1 py-2.5 text-xs font-medium transition-colors ${
                  settingsTab === "notifications" ? "text-indigo-400 border-b-2 border-indigo-400" : "text-gray-500 hover:text-gray-300"
                }`}
              >
                Notifications
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4">
              {settingsTab === "templates" && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-white">Canned Responses</span>
                    <button
                      onClick={() => setShowNewTemplate(!showNewTemplate)}
                      className="flex items-center gap-1 px-2.5 py-1 bg-indigo-600/10 hover:bg-indigo-600/20 text-indigo-400 rounded-lg text-xs transition-colors"
                    >
                      <Plus className="h-3 w-3" />
                      New
                    </button>
                  </div>

                  {showNewTemplate && (
                    <div className="p-3 bg-[#1a1a1a] border border-gray-700 rounded-lg space-y-2">
                      <input
                        type="text"
                        value={newTemplate.name}
                        onChange={(e) => setNewTemplate(p => ({ ...p, name: e.target.value }))}
                        placeholder="Template name"
                        className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-700 rounded-lg text-xs text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500"
                      />
                      <input
                        type="text"
                        value={newTemplate.category}
                        onChange={(e) => setNewTemplate(p => ({ ...p, category: e.target.value }))}
                        placeholder="Category (optional)"
                        className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-700 rounded-lg text-xs text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500"
                      />
                      <textarea
                        value={newTemplate.content}
                        onChange={(e) => setNewTemplate(p => ({ ...p, content: e.target.value }))}
                        placeholder="Template content... Use {{customer_number}}, {{date}}, {{time}} for variables"
                        rows={3}
                        className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-700 rounded-lg text-xs text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500 resize-none"
                      />
                      <div className="flex gap-2">
                        <button
                          onClick={handleSaveTemplate}
                          disabled={!newTemplate.name.trim() || !newTemplate.content.trim()}
                          className="px-3 py-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs disabled:opacity-50"
                        >
                          Save
                        </button>
                        <button
                          onClick={() => { setShowNewTemplate(false); setNewTemplate({ name: "", content: "", category: "" }); }}
                          className="px-3 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg text-xs"
                        >
                          Cancel
                        </button>
                      </div>
                      <p className="text-[10px] text-gray-600">
                        Variables: {"{{customer_number}}"}, {"{{date}}"}, {"{{time}}"}, {"{{guest_name}}"}
                      </p>
                    </div>
                  )}

                  {templates.length === 0 ? (
                    <div className="py-8 text-center text-gray-500 text-xs">
                      No templates yet. Click "New" to create one.
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {templates.map((t) => (
                        <div key={t.id} className="p-3 bg-[#1a1a1a] border border-gray-700 rounded-lg">
                          {editingTemplate?.id === t.id ? (
                            <div className="space-y-2">
                              <input
                                type="text"
                                value={editingTemplate.name}
                                onChange={(e) => setEditingTemplate({ ...editingTemplate, name: e.target.value })}
                                className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-700 rounded-lg text-xs text-white focus:outline-none focus:border-indigo-500"
                              />
                              <input
                                type="text"
                                value={editingTemplate.category || ""}
                                onChange={(e) => setEditingTemplate({ ...editingTemplate, category: e.target.value || null })}
                                placeholder="Category"
                                className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-700 rounded-lg text-xs text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500"
                              />
                              <textarea
                                value={editingTemplate.content}
                                onChange={(e) => setEditingTemplate({ ...editingTemplate, content: e.target.value })}
                                rows={3}
                                className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-700 rounded-lg text-xs text-white focus:outline-none focus:border-indigo-500 resize-none"
                              />
                              <div className="flex gap-2">
                                <button
                                  onClick={() => handleUpdateTemplate(editingTemplate)}
                                  className="px-3 py-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs"
                                >
                                  Save
                                </button>
                                <button
                                  onClick={() => setEditingTemplate(null)}
                                  className="px-3 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg text-xs"
                                >
                                  Cancel
                                </button>
                              </div>
                            </div>
                          ) : (
                            <>
                              <div className="flex items-start justify-between">
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-2">
                                    <span className="text-xs font-medium text-white">{t.name}</span>
                                    {t.category && (
                                      <span className="text-[10px] px-1.5 py-0.5 bg-gray-700 text-gray-400 rounded">{t.category}</span>
                                    )}
                                  </div>
                                  <p className="text-[11px] text-gray-400 mt-1 line-clamp-2">{t.content}</p>
                                </div>
                                <div className="flex items-center gap-1 ml-2">
                                  <button
                                    onClick={() => setEditingTemplate({ ...t })}
                                    className="p-1 text-gray-500 hover:text-indigo-400"
                                  >
                                    <Edit2 className="h-3 w-3" />
                                  </button>
                                  <button
                                    onClick={() => handleDeleteTemplate(t.id)}
                                    className="p-1 text-gray-500 hover:text-red-400"
                                  >
                                    <Trash2 className="h-3 w-3" />
                                  </button>
                                </div>
                              </div>
                            </>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {settingsTab === "notifications" && (
                <div className="space-y-5">
                  <div>
                    <span className="text-sm font-medium text-white">Notification Preferences</span>
                    <p className="text-[11px] text-gray-500 mt-0.5">Configure how you're notified about new messages</p>
                  </div>

                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        {notifSettings.sound_enabled ? <Volume2 className="h-4 w-4 text-indigo-400" /> : <VolumeX className="h-4 w-4 text-gray-500" />}
                        <span className="text-xs text-white">Sound notifications</span>
                      </div>
                      <button
                        onClick={() => setNotifSettings(p => ({ ...p, sound_enabled: !p.sound_enabled }))}
                        className={`w-10 h-5 rounded-full transition-colors ${notifSettings.sound_enabled ? "bg-indigo-600" : "bg-gray-700"}`}
                      >
                        <div className={`w-4 h-4 rounded-full bg-white transition-transform mx-0.5 ${notifSettings.sound_enabled ? "translate-x-5" : "translate-x-0"}`} />
                      </button>
                    </div>

                    {notifSettings.sound_enabled && (
                      <div>
                        <label className="text-[11px] text-gray-400 block mb-1">Sound type</label>
                        <select
                          value={notifSettings.sound_type}
                          onChange={(e) => setNotifSettings(p => ({ ...p, sound_type: e.target.value }))}
                          className="w-full px-3 py-1.5 bg-[#1a1a1a] border border-gray-700 rounded-lg text-xs text-white focus:outline-none focus:border-indigo-500"
                        >
                          <option value="chime">Chime</option>
                          <option value="bell">Bell</option>
                          <option value="ding">Ding</option>
                        </select>
                        <button
                          onClick={playNotificationSound}
                          className="mt-1.5 text-[10px] text-indigo-400 hover:text-indigo-300"
                        >
                          Preview sound
                        </button>
                      </div>
                    )}

                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        {notifSettings.visual_enabled ? <Bell className="h-4 w-4 text-indigo-400" /> : <BellOff className="h-4 w-4 text-gray-500" />}
                        <span className="text-xs text-white">Visual notifications</span>
                      </div>
                      <button
                        onClick={() => setNotifSettings(p => ({ ...p, visual_enabled: !p.visual_enabled }))}
                        className={`w-10 h-5 rounded-full transition-colors ${notifSettings.visual_enabled ? "bg-indigo-600" : "bg-gray-700"}`}
                      >
                        <div className={`w-4 h-4 rounded-full bg-white transition-transform mx-0.5 ${notifSettings.visual_enabled ? "translate-x-5" : "translate-x-0"}`} />
                      </button>
                    </div>

                    <div>
                      <label className="text-[11px] text-gray-400 block mb-1">Notification threshold</label>
                      <div className="flex items-center gap-2">
                        <input
                          type="number"
                          min={1}
                          max={50}
                          value={notifSettings.threshold}
                          onChange={(e) => setNotifSettings(p => ({ ...p, threshold: parseInt(e.target.value) || 1 }))}
                          className="w-20 px-3 py-1.5 bg-[#1a1a1a] border border-gray-700 rounded-lg text-xs text-white focus:outline-none focus:border-indigo-500"
                        />
                        <span className="text-[11px] text-gray-500">unread messages before notifying</span>
                      </div>
                    </div>
                  </div>

                  <button
                    onClick={handleSaveNotifSettings}
                    disabled={savingSettings}
                    className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
                  >
                    {savingSettings ? "Saving..." : "Save Settings"}
                  </button>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
