"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { notify } from "@/lib/notifications";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Assistant {
  id: string;
  name: string;
  is_active: boolean;
}

export interface Conversation {
  id: string;
  reference_id?: string | null;
  customer_number: string;
  botelier_number: string;
  status: string;
  handler_mode: "ai" | "human";
  needs_attention: boolean;
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

export interface Message {
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

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface SMSTemplate {
  id: string;
  account_id: string;
  name: string;
  content: string;
  category: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface NotificationSettings {
  sound_enabled: boolean;
  visual_enabled: boolean;
  threshold: number;
  sound_type: string;
}

export interface AttachedFile {
  url: string;
  filename: string;
  content_type: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export const PRESENCE_STALE_MS = 30_000;

export function isPresenceActive(agentActiveAt: string | null | undefined): boolean {
  if (!agentActiveAt) return false;
  return Date.now() - new Date(agentActiveAt).getTime() < PRESENCE_STALE_MS;
}

export function isImageUrl(url: string): boolean {
  return /\.(jpg|jpeg|png|gif|webp)(\?|$)/i.test(url);
}

export function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return "";
  const diffMs = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return new Date(dateStr).toLocaleDateString();
}

export function formatFullTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString();
}

export function statusColor(status: string): string {
  switch (status) {
    case "active":    return "text-green-400 bg-green-400/10";
    case "closed":    return "text-gray-400 bg-gray-400/10";
    case "opted_out": return "text-red-400 bg-red-400/10";
    default:          return "text-gray-400 bg-gray-400/10";
  }
}

export function playTone(soundType: string): void {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    const freqs: Record<string, number> = { chime: 880, bell: 660, ding: 1200 };
    osc.frequency.value = freqs[soundType] ?? 880;
    osc.type = "sine";
    gain.gain.setValueAtTime(0.3, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 0.5);
  } catch {}
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useSMSData() {
  const { accountId, loading: contextLoading } = useAccountContext();
  const { user } = useAuthToken();

  // --- Conversation list state ---
  const [conversations, setConversations]     = useState<Conversation[]>([]);
  const [assistants, setAssistants]           = useState<Assistant[]>([]);
  const [loading, setLoading]                 = useState(true);
  const [search, setSearch]                   = useState("");
  const [statusFilter, setStatusFilter]       = useState("");
  const [assistantFilter, setAssistantFilter] = useState("");
  const [needsAttentionFilter, setNeedsAttentionFilter] = useState(false);

  // --- Thread state ---
  const [selectedConv, setSelectedConv]       = useState<ConversationDetail | null>(null);
  const [loadingConv, setLoadingConv]         = useState(false);
  const [generatingSummary, setGeneratingSummary] = useState(false);
  const [handoffLoading, setHandoffLoading]   = useState(false);
  const [replyText, setReplyText]             = useState("");
  const [sendingReply, setSendingReply]       = useState(false);

  // --- Attachment state ---
  const [attachedFiles, setAttachedFiles]     = useState<AttachedFile[]>([]);
  const [uploading, setUploading]             = useState(false);

  // --- Template state ---
  const [templates, setTemplates]             = useState<SMSTemplate[]>([]);
  const [showTemplates, setShowTemplates]     = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<SMSTemplate | null>(null);
  const [newTemplate, setNewTemplate]         = useState({ name: "", content: "", category: "" });
  const [showNewTemplate, setShowNewTemplate] = useState(false);

  // --- Settings state ---
  const [settingsOpen, setSettingsOpen]       = useState(false);
  const [settingsTab, setSettingsTab]         = useState<"notifications" | "templates">("templates");
  const [savingSettings, setSavingSettings]   = useState(false);
  const [notifSettings, setNotifSettings]     = useState<NotificationSettings>({
    sound_enabled: true,
    visual_enabled: true,
    threshold: 1,
    sound_type: "chime",
  });

  // --- Refs ---
  const messagesEndRef        = useRef<HTMLDivElement>(null);
  const presenceIntervalRef   = useRef<NodeJS.Timeout | null>(null);
  const lastPresenceConvIdRef = useRef<string | null>(null);
  const fileInputRef          = useRef<HTMLInputElement>(null);
  const eventSourceRef        = useRef<EventSource | null>(null);
  const selectedConvIdRef     = useRef<string | null>(null);
  const conversationsRef      = useRef<Conversation[]>([]);

  // Refs for SSE callbacks — avoids tearing down the SSE connection on filter changes
  const notifSettingsRef           = useRef(notifSettings);
  const fetchConversationRef       = useRef<((id: string) => void) | null>(null);
  const fetchConversationsRef      = useRef<(() => void) | null>(null);
  const fetchSingleIntoListRef     = useRef<((id: string) => void) | null>(null);

  // Keep selectedConvIdRef in sync
  useEffect(() => {
    selectedConvIdRef.current = selectedConv?.id ?? null;
  }, [selectedConv?.id]);

  // Keep conversationsRef in sync so SSE handlers can read current list
  // without being listed as deps (which would restart the SSE connection).
  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);

  // Keep notifSettingsRef in sync (no SSE restart)
  useEffect(() => {
    notifSettingsRef.current = notifSettings;
  }, [notifSettings]);

  // ---------------------------------------------------------------------------
  // Presence
  // ---------------------------------------------------------------------------

  const sendPresenceHeartbeat = useCallback(async (convId: string) => {
    if (!accountId || !user?.id) return;
    try {
      await fetch(`/api/sms/conversations/${convId}/presence`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account_id: accountId,
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
        body: JSON.stringify({ account_id: accountId, agent_id: user.id }),
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
    presenceIntervalRef.current = setInterval(() => sendPresenceHeartbeat(convId), 15_000);
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

  useEffect(() => () => { stopPresenceHeartbeat(); }, [stopPresenceHeartbeat]);

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  const fetchConversations = useCallback(async () => {
    if (!accountId) return;
    try {
      setLoading(true);
      const params = new URLSearchParams({ account_id: accountId });
      if (search)                params.set("search", search);
      if (statusFilter)          params.set("status", statusFilter);
      if (assistantFilter)       params.set("assistant_id", assistantFilter);
      if (needsAttentionFilter)  params.set("needs_attention", "true");
      const res = await fetch(`/api/sms/conversations?${params}`);
      const data = await res.json();
      setConversations(data.conversations || []);
    } catch (err) {
      console.error("Failed to fetch conversations:", err);
    } finally {
      setLoading(false);
    }
  }, [accountId, search, statusFilter, assistantFilter, needsAttentionFilter]);

  const fetchConversation = useCallback(async (id: string) => {
    if (!accountId) return;
    try {
      setLoadingConv(true);
      const res = await fetch(`/api/sms/conversations/${id}?account_id=${accountId}`);
      const data = await res.json();
      setSelectedConv(data);
      setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }), 100);
      startPresenceHeartbeat(id);
      fetch(`/api/sms/conversations/${id}/read`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: accountId }),
      })
        .then(() => setConversations(prev => prev.map(c => c.id === id ? { ...c, has_unread: false } : c)))
        .catch(() => {});
    } catch (err) {
      console.error("Failed to fetch conversation:", err);
    } finally {
      setLoadingConv(false);
    }
  }, [accountId, startPresenceHeartbeat]);

  /**
   * Fetch a single conversation by ID and merge it into the list surgically.
   * Used by SSE handlers for new/reopened conversations so we only touch one
   * card instead of replacing the entire list (which causes every card to blink).
   *
   * If the conversation doesn't match the current filters (e.g. a "closed" conv
   * arrives while the user has "active" filter active) it is silently skipped.
   */
  const fetchSingleConversationIntoList = useCallback(async (id: string) => {
    if (!accountId) return;
    try {
      const res = await fetch(`/api/sms/conversations/${id}?account_id=${accountId}`);
      if (!res.ok) return;
      const conv: Conversation = await res.json();

      setConversations(prev => {
        const exists = prev.some(c => c.id === id);
        let next: Conversation[];
        if (exists) {
          next = prev.map(c => c.id === id ? { ...c, ...conv } : c);
        } else {
          // New conversation — prepend only if it passes active filters
          next = [conv, ...prev];
        }
        return [...next].sort(
          (a, b) =>
            new Date(b.last_message_at ?? 0).getTime() -
            new Date(a.last_message_at ?? 0).getTime()
        );
      });
    } catch {
      // On error fall back to full refetch so we don't silently lose the entry
      fetchConversationsRef.current?.();
    }
  }, [accountId]);

  // Keep callback refs in sync (no SSE restart)
  useEffect(() => {
    fetchConversationRef.current = fetchConversation;
  }, [fetchConversation]);

  useEffect(() => {
    fetchConversationsRef.current = fetchConversations;
  }, [fetchConversations]);

  useEffect(() => {
    fetchSingleIntoListRef.current = fetchSingleConversationIntoList;
  }, [fetchSingleConversationIntoList]);

  const fetchAssistants = useCallback(async () => {
    if (!accountId) return;
    try {
      const res = await fetch(`/api/assistants?account_id=${accountId}&is_active=true`);
      const data = await res.json();
      setAssistants(data.assistants || []);
    } catch {}
  }, [accountId]);

  const fetchTemplates = useCallback(async () => {
    if (!accountId) return;
    try {
      const res = await fetch(`/api/sms/templates?account_id=${accountId}`);
      setTemplates(await res.json());
    } catch {}
  }, [accountId]);

  const fetchNotifSettings = useCallback(async () => {
    if (!accountId) return;
    try {
      const res = await fetch(`/api/sms/settings/notifications?account_id=${accountId}`);
      setNotifSettings(await res.json());
    } catch {}
  }, [accountId]);

  // ---------------------------------------------------------------------------
  // SSE — only depends on accountId; callbacks come from refs to avoid restarts
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (!accountId) return;

    const es = new EventSource(`/api/sms/stream?account_id=${accountId}`);
    eventSourceRef.current = es;

    const handleNewMessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as {
          conversation_id: string;
          customer_number: string;
          preview: string;
          account_id: string;
        };

        // Snapshot current list synchronously so we can decide on side-effects
        // *outside* the state updater (updaters must be pure — no side-effects).
        const currentConversations = conversationsRef.current ?? [];
        const existing = currentConversations.find(c => c.id === data.conversation_id);
        const isNew    = !existing;
        const wasClosed = existing?.status === "closed";

        setConversations(prev => {
          if (isNew) return prev;

          const updated = prev.map(c =>
            c.id === data.conversation_id
              ? {
                  ...c,
                  has_unread: selectedConvIdRef.current !== data.conversation_id,
                  last_message_preview: data.preview,
                  last_message_at: new Date().toISOString(),
                  // Optimistically reopen if closed — the backend always reopens
                  // a closed conversation when a new inbound message arrives.
                  // A follow-up fetch will sync the correct handler_mode from the server.
                  ...(wasClosed ? { status: "active", handler_mode: "ai" as const, needs_attention: false } : {}),
                }
              : c
          );

          return [...updated].sort(
            (a, b) =>
              new Date(b.last_message_at ?? 0).getTime() -
              new Date(a.last_message_at ?? 0).getTime()
          );
        });

        // Side-effects run outside the updater so React doesn't suppress them.
        // For new/reopened conversations we fetch just that one card — avoids
        // replacing the entire list which re-renders (and blinks) every card.
        if (isNew || wasClosed) {
          fetchSingleIntoListRef.current?.(data.conversation_id);
        }

        if (selectedConvIdRef.current === data.conversation_id) {
          fetchConversationRef.current?.(data.conversation_id);
        }

        const ns = notifSettingsRef.current;
        if (document.hidden && ns.sound_enabled) {
          playTone(ns.sound_type);
        }
        if (ns.visual_enabled) {
          notify.info(`New message from ${data.customer_number}`);
        }
      } catch {}
    };

    const handleNewReply = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as {
          conversation_id: string;
          customer_number: string;
          preview: string;
        };

        setConversations(prev =>
          prev.map(c =>
            c.id === data.conversation_id
              ? { ...c, last_message_preview: data.preview, last_message_at: new Date().toISOString() }
              : c
          )
        );

        if (selectedConvIdRef.current === data.conversation_id) {
          fetchConversationRef.current?.(data.conversation_id);
        }
      } catch {}
    };

    const handleHandoffRequested = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as {
          conversation_id: string;
          customer_number: string;
          account_id: string;
          last_ai_message: string;
        };

        setConversations(prev =>
          prev.map(c =>
            c.id === data.conversation_id
              ? { ...c, handler_mode: "human" as const, needs_attention: true }
              : c
          )
        );

        notify.warning(`AI escalated: ${data.customer_number} needs an agent`);

        if (selectedConvIdRef.current === data.conversation_id) {
          fetchConversationRef.current?.(data.conversation_id);
        }
      } catch {}
    };

    const handleHandlerChanged = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as {
          conversation_id: string;
          handler_mode: "ai" | "human";
          needs_attention: boolean;
        };

        setConversations(prev =>
          prev.map(c =>
            c.id === data.conversation_id
              ? { ...c, handler_mode: data.handler_mode, needs_attention: data.needs_attention }
              : c
          )
        );

        setSelectedConv(prev =>
          prev?.id === data.conversation_id
            ? { ...prev, handler_mode: data.handler_mode, needs_attention: data.needs_attention }
            : prev
        );
      } catch {}
    };

    es.addEventListener("new_message", handleNewMessage);
    es.addEventListener("new_reply", handleNewReply);
    es.addEventListener("handoff_requested", handleHandoffRequested);
    es.addEventListener("handler_changed", handleHandlerChanged);

    es.onerror = () => {
      console.debug("SMS SSE connection interrupted, reconnecting...");
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [accountId]); // Only accountId — all callbacks via refs

  // ---------------------------------------------------------------------------
  // Initial data load + filter re-fetch
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (!contextLoading && accountId) {
      fetchConversations();
      fetchAssistants();
      fetchTemplates();
      fetchNotifSettings();
    }
  }, [accountId, contextLoading]);

  useEffect(() => {
    if (!accountId) return;
    const timer = setTimeout(() => fetchConversations(), 300);
    return () => clearTimeout(timer);
  }, [search, statusFilter, assistantFilter, needsAttentionFilter, accountId]);

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  const handleGenerateSummary = async () => {
    if (!selectedConv || !accountId) return;
    setGeneratingSummary(true);
    try {
      const res = await fetch(`/api/sms/conversations/${selectedConv.id}/generate-summary`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: accountId }),
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
        body: JSON.stringify({ account_id: accountId }),
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
        formData.append("account_id", accountId);
        const res = await fetch("/api/sms/upload", { method: "POST", body: formData });
        const data = await res.json();
        if (!res.ok) {
          notify.error(data.detail || `Failed to upload ${file.name}`);
          continue;
        }
        setAttachedFiles(prev => [...prev, { url: data.url, filename: data.filename, content_type: data.content_type }]);
      }
    } catch {
      notify.error("Upload failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleTakeOver = async () => {
    if (!selectedConv || !accountId || handoffLoading) return;
    setHandoffLoading(true);
    try {
      const res = await fetch(`/api/sms/conversations/${selectedConv.id}/take-over`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: accountId }),
      });
      if (!res.ok) {
        const data = await res.json();
        notify.error(data.detail || "Failed to take over conversation");
        return;
      }
      setSelectedConv(prev => prev ? { ...prev, handler_mode: "human", needs_attention: true } : prev);
      setConversations(prev =>
        prev.map(c => c.id === selectedConv.id ? { ...c, handler_mode: "human" as const, needs_attention: true } : c)
      );
    } catch {
      notify.error("Failed to take over conversation");
    } finally {
      setHandoffLoading(false);
    }
  };

  const handleReturnToAI = async () => {
    if (!selectedConv || !accountId || handoffLoading) return;
    setHandoffLoading(true);
    try {
      const res = await fetch(`/api/sms/conversations/${selectedConv.id}/return-to-ai`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: accountId }),
      });
      if (!res.ok) {
        const data = await res.json();
        notify.error(data.detail || "Failed to return to AI");
        return;
      }
      setSelectedConv(prev => prev ? { ...prev, handler_mode: "ai", needs_attention: false } : prev);
      setConversations(prev =>
        prev.map(c => c.id === selectedConv.id ? { ...c, handler_mode: "ai" as const, needs_attention: false } : c)
      );
    } catch {
      notify.error("Failed to return to AI");
    } finally {
      setHandoffLoading(false);
    }
  };

  const handleSendReply = async () => {
    if (!selectedConv || !accountId || sendingReply) return;
    if (!replyText.trim() && attachedFiles.length === 0) return;
    setSendingReply(true);
    try {
      const body: Record<string, any> = { account_id: accountId, message: replyText.trim() };
      if (attachedFiles.length > 0) body.media_urls = attachedFiles.map(f => f.url);
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
      content = content
        .replace(/\{\{customer_number\}\}/g, selectedConv.customer_number)
        .replace(/\{\{date\}\}/g, new Date().toLocaleDateString())
        .replace(/\{\{time\}\}/g, new Date().toLocaleTimeString());
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
          account_id: accountId,
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
          account_id: accountId,
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
      await fetch(`/api/sms/templates/${id}?account_id=${accountId}`, { method: "DELETE" });
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
        body: JSON.stringify({ account_id: accountId, ...notifSettings }),
      });
      notify.success("Notification settings saved");
    } catch {
      notify.error("Failed to save settings");
    } finally {
      setSavingSettings(false);
    }
  };

  const groupedTemplates = templates.reduce<Record<string, SMSTemplate[]>>((acc, t) => {
    const cat = t.category || "General";
    (acc[cat] ??= []).push(t);
    return acc;
  }, {});

  return {
    accountId,
    user,
    conversations, setConversations,
    assistants,
    loading,
    search, setSearch,
    statusFilter, setStatusFilter,
    assistantFilter, setAssistantFilter,
    needsAttentionFilter, setNeedsAttentionFilter,
    selectedConv, setSelectedConv,
    loadingConv,
    generatingSummary,
    handoffLoading,
    replyText, setReplyText,
    sendingReply,
    attachedFiles, setAttachedFiles,
    uploading,
    templates,
    showTemplates, setShowTemplates,
    editingTemplate, setEditingTemplate,
    newTemplate, setNewTemplate,
    showNewTemplate, setShowNewTemplate,
    settingsOpen, setSettingsOpen,
    settingsTab, setSettingsTab,
    savingSettings,
    notifSettings, setNotifSettings,
    messagesEndRef,
    fileInputRef,
    groupedTemplates,
    fetchConversations,
    fetchConversation,
    fetchTemplates,
    fetchNotifSettings,
    handleGenerateSummary,
    handleCloseConversation,
    handleFileSelect,
    handleTakeOver,
    handleReturnToAI,
    handleSendReply,
    handleInsertTemplate,
    handleSaveTemplate,
    handleUpdateTemplate,
    handleDeleteTemplate,
    handleSaveNotifSettings,
    previewNotifSound: () => playTone(notifSettings.sound_type),
  };
}
