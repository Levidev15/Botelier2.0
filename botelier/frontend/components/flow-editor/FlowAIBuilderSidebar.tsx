"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import {
  Sparkles,
  X,
  Send,
  Loader2,
  Check,
  RotateCcw,
  ChevronRight,
} from "lucide-react";
import { useFlowStore, AIPatch, FlowVariable } from "./store";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface Props {
  toolId: string;
  accountId: string;
  onClose: () => void;
}

interface AIMessage {
  role: "user" | "assistant";
  content: string;
  patch?: AIPatch | null;
  /** undefined = pending, true = applied, false = discarded */
  applied?: boolean;
}

const STARTERS = [
  "Generate a room-booking flow from scratch",
  "Add a step to collect check-in and check-out dates",
  "Add a condition that branches on whether a room is available",
  "Explain what the Router node does",
  "Why won't my flow publish?",
];

export default function FlowAIBuilderSidebar({ toolId, accountId, onClose }: Props) {
  const { applyAIPatch, getFlowConfig } = useFlowStore();
  const [messages, setMessages] = useState<AIMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Index into messages[] of the latest un-acted-on patch
  const [pendingIdx, setPendingIdx] = useState<number | null>(null);
  const { authFetch } = useAuthToken();
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const scrollToBottom = useCallback(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading, scrollToBottom]);

  const hasPatch = (m: AIMessage): m is AIMessage & { patch: AIPatch } =>
    !!m.patch && (m.patch.nodes.length > 0 || m.patch.variables.length > 0);

  const sendMessage = async (overrideText?: string) => {
    const text = (overrideText ?? input).trim();
    if (!text || loading) return;
    setInput("");
    setError(null);
    setLoading(true);

    const userMsg: AIMessage = { role: "user", content: text };
    const withUser = [...messages, userMsg];
    setMessages(withUser);

    try {
      const cfg = getFlowConfig();
      const currentFlow = {
        nodes: (cfg.nodes as any[]).map((n) => ({
          id: n.id,
          type: n.type,
          position: n.position ?? { x: 0, y: 0 },
          data: n.data,
        })),
        edges: cfg.edges,
        variables: cfg.variables,
      };

      const history = withUser.slice(-9, -1).map((m) => ({
        role: m.role,
        content: m.content,
      }));

      const res = await authFetch(`/api/tools/${toolId}/flow/ai-assist?account_id=${accountId}`, {
        method: "POST",
        body: JSON.stringify({ message: text, history, current_flow: currentFlow }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error((data as any).detail ?? `Request failed (${res.status})`);
      }

      const data = await res.json();
      const hasCandidatePatch =
        data.type === "patch" &&
        data.patch &&
        ((data.patch.nodes?.length ?? 0) > 0 ||
          (data.patch.variables?.length ?? 0) > 0);

      const assistantMsg: AIMessage = {
        role: "assistant",
        content: data.text ?? "",
        patch: hasCandidatePatch ? data.patch : null,
      };

      const withAssistant = [...withUser, assistantMsg];
      setMessages(withAssistant);

      if (hasCandidatePatch) {
        setPendingIdx(withAssistant.length - 1);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
      setTimeout(() => inputRef.current?.focus(), 80);
    }
  };

  const applyPatch = (idx: number, patch: AIPatch) => {
    applyAIPatch(patch);
    setMessages((prev) =>
      prev.map((m, i) => (i === idx ? { ...m, applied: true } : m))
    );
    setPendingIdx(null);
  };

  const discardPatch = (idx: number) => {
    setMessages((prev) =>
      prev.map((m, i) => (i === idx ? { ...m, applied: false } : m))
    );
    setPendingIdx(null);
  };

  const reset = () => {
    setMessages([]);
    setPendingIdx(null);
    setError(null);
    setInput("");
  };

  return (
    <div className="h-full flex flex-col bg-[#0f0f0f] border-l border-[#2a2a2a]">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#2a2a2a] bg-[#141414] flex-shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded bg-purple-600 flex items-center justify-center">
            <Sparkles className="w-3 h-3 text-white" />
          </div>
          <span className="text-sm font-medium text-white">AI Builder</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-900/40 text-purple-400 font-medium leading-none">
            Beta
          </span>
        </div>
        <div className="flex items-center gap-1">
          {messages.length > 0 && (
            <button
              onClick={reset}
              className="p-1.5 text-gray-400 hover:text-white hover:bg-[#2a2a2a] rounded transition-colors"
              title="New conversation"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          )}
          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-white hover:bg-[#2a2a2a] rounded transition-colors"
            title="Close AI Builder"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* ── Messages / Empty state ──────────────────────────────────────── */}
      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 ? (
          /* Empty state */
          <div className="flex flex-col items-center justify-center h-full gap-5 py-4">
            <div className="text-center">
              <div className="w-12 h-12 rounded-full bg-purple-600/15 border border-purple-500/20 flex items-center justify-center mx-auto mb-3">
                <Sparkles className="w-5 h-5 text-purple-400" />
              </div>
              <p className="text-gray-200 text-sm font-medium mb-1">AI Flow Builder</p>
              <p className="text-gray-500 text-xs leading-relaxed">
                Describe what you want to build.
                <br />
                The AI adds nodes directly to your canvas.
              </p>
            </div>
            <div className="w-full space-y-1.5">
              {STARTERS.map((s) => (
                <button
                  key={s}
                  onClick={() => sendMessage(s)}
                  disabled={loading}
                  className="w-full text-left px-3 py-2 rounded-lg border border-[#2a2a2a] bg-[#1a1a1a] hover:border-purple-500/40 hover:bg-purple-900/10 text-xs text-gray-400 hover:text-gray-200 transition-all flex items-center justify-between group disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <span>{s}</span>
                  <ChevronRight className="w-3 h-3 opacity-0 group-hover:opacity-100 text-purple-400 transition-opacity flex-shrink-0" />
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* Chat thread */
          <>
            {messages.map((msg, idx) => (
              <div key={idx} className="space-y-2">
                {/* Chat bubble */}
                <div
                  className={`text-xs rounded-lg px-3 py-2 leading-relaxed whitespace-pre-wrap ${
                    msg.role === "user"
                      ? "bg-[#222] text-gray-200 ml-6"
                      : "bg-purple-950/30 border border-purple-500/20 text-gray-300"
                  }`}
                >
                  {msg.content || <span className="italic text-gray-500">No text</span>}
                </div>

                {/* Patch proposal card */}
                {hasPatch(msg) && (
                  <div
                    className={`rounded-lg border p-3 text-xs space-y-2 transition-all ${
                      msg.applied === true
                        ? "border-green-500/30 bg-green-950/20"
                        : msg.applied === false
                        ? "border-gray-700 bg-[#1a1a1a] opacity-50"
                        : "border-purple-500/30 bg-purple-950/15"
                    }`}
                  >
                    {/* Status dot + label */}
                    <div className="flex items-center gap-1.5">
                      <div
                        className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                          msg.applied === true
                            ? "bg-green-400"
                            : msg.applied === false
                            ? "bg-gray-500"
                            : "bg-purple-400 animate-pulse"
                        }`}
                      />
                      <span
                        className={`font-medium ${
                          msg.applied === true
                            ? "text-green-400"
                            : msg.applied === false
                            ? "text-gray-500"
                            : "text-purple-300"
                        }`}
                      >
                        {msg.applied === true
                          ? "Applied to canvas"
                          : msg.applied === false
                          ? "Discarded"
                          : "Proposed changes"}
                      </span>
                    </div>

                    {/* Summary of what will be added */}
                    <ul className="text-gray-400 space-y-0.5 pl-3 list-none">
                      {msg.patch.nodes.length > 0 && (
                        <li>
                          +{msg.patch.nodes.length} node
                          {msg.patch.nodes.length > 1 ? "s" : ""}:{" "}
                          <span className="text-gray-300">
                            {msg.patch.nodes
                              .map((n) => (n.data as any)?.name ?? n.type)
                              .join(", ")}
                          </span>
                        </li>
                      )}
                      {msg.patch.edges.length > 0 && (
                        <li>
                          +{msg.patch.edges.length} connection
                          {msg.patch.edges.length > 1 ? "s" : ""}
                        </li>
                      )}
                      {msg.patch.variables.length > 0 && (
                        <li>
                          +{msg.patch.variables.length} variable
                          {msg.patch.variables.length > 1 ? "s" : ""}:{" "}
                          <span className="font-mono text-purple-300 text-[10px]">
                            {msg.patch.variables.map((v) => v.key).join(", ")}
                          </span>
                        </li>
                      )}
                    </ul>

                    {/* Apply / Discard buttons (only for the pending patch) */}
                    {msg.applied === undefined && pendingIdx === idx && (
                      <div className="flex gap-2 pt-1">
                        <button
                          onClick={() => applyPatch(idx, msg.patch)}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-600 hover:bg-purple-700 text-white rounded-md text-xs font-medium transition-colors"
                        >
                          <Check className="w-3 h-3" />
                          Apply to canvas
                        </button>
                        <button
                          onClick={() => discardPatch(idx)}
                          className="px-3 py-1.5 bg-[#2a2a2a] hover:bg-[#333] text-gray-400 hover:text-gray-200 rounded-md text-xs transition-colors"
                        >
                          Discard
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}

            {/* Typing indicator */}
            {loading && (
              <div className="flex items-center gap-2 pl-1">
                <div className="bg-purple-950/30 border border-purple-500/20 rounded-lg px-3 py-2 flex items-center gap-2">
                  <Loader2 className="w-3 h-3 animate-spin text-purple-400" />
                  <span className="text-xs text-gray-400">Thinking…</span>
                </div>
              </div>
            )}
          </>
        )}
        <div ref={endRef} />
      </div>

      {/* ── Error bar ──────────────────────────────────────────────────── */}
      {error && (
        <div className="px-3 py-2 bg-red-900/30 border-t border-red-800 text-red-400 text-xs flex-shrink-0">
          {error}
        </div>
      )}

      {/* ── Input ──────────────────────────────────────────────────────── */}
      <div className="p-3 border-t border-[#2a2a2a] flex-shrink-0 bg-[#141414]">
        <div className="flex gap-2">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
              }
            }}
            placeholder="Describe what to build…"
            disabled={loading}
            className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-purple-500 disabled:opacity-50 transition-colors"
          />
          <button
            onClick={() => sendMessage()}
            disabled={loading || !input.trim()}
            className="px-3 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg transition-colors flex-shrink-0"
            title="Send"
          >
            {loading ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Send className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
        <p className="text-[10px] text-gray-600 mt-1.5">
          Add-only · nodes appear after you click Apply
        </p>
      </div>
    </div>
  );
}
