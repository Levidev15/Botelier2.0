"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import ChatMessage from "./ChatMessage";
import SlotTracker from "./SlotTracker";
import { Play, RotateCcw, Loader2, X, ChevronDown, ChevronUp } from "lucide-react";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import {
  deleteSimulationSession,
  formatNativeError,
  requestSimulationStart,
  SimulationEngine,
  SimulationState,
  SimulationVariable,
} from "./nativePilot";

interface FlowSimulatorSidebarProps {
  toolId: string;
  toolName: string;
  assistantId?: string;
  isDirty: boolean;
  currentSource: string;
  currentVersionNumber: number;
  currentVersionId: string | null;
  publishedVersionNumber: number;
  isFlowLoading: boolean;
  onClose: () => void;
  onNodeChange?: (nodeId: string | null) => void;
}

interface Message {
  role: "user" | "assistant" | "system";
  content: string;
  metadata?: {
    function_called?: string;
    function_result?: Record<string, unknown>;
    record_saved?: boolean;
  };
}

export default function FlowSimulatorSidebar({
  toolId,
  toolName,
  assistantId,
  isDirty,
  currentSource,
  currentVersionNumber,
  currentVersionId,
  publishedVersionNumber,
  isFlowLoading,
  onClose,
  onNodeChange,
}: FlowSimulatorSidebarProps) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [state, setState] = useState<SimulationState | null>(null);
  const [variables, setVariables] = useState<SimulationVariable[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showSlotTracker, setShowSlotTracker] = useState(true);
  const [engine, setEngine] = useState<SimulationEngine>("legacy");
  const [runtimeEvidence, setRuntimeEvidence] = useState<{
    engine: string;
    version: number;
    flowVersionId?: string;
  } | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { authFetch } = useAuthToken();
  const authFetchRef = useRef(authFetch);
  authFetchRef.current = authFetch;
  const onNodeChangeRef = useRef(onNodeChange);
  onNodeChangeRef.current = onNodeChange;
  const sessionIdRef = useRef<string | null>(null);
  const sessionSourceKeyRef = useRef<string | null>(null);
  const generationRef = useRef(0);
  const startingRef = useRef(false);
  const sendingRef = useRef(false);
  const inputRef = useRef(input);
  inputRef.current = input;
  const mountedRef = useRef(false);
  const latestRef = useRef({
    toolId, assistantId, isDirty, currentSource, currentVersionNumber, currentVersionId,
    publishedVersionNumber, isFlowLoading, engine,
  });
  latestRef.current = {
    toolId, assistantId, isDirty, currentSource, currentVersionNumber, currentVersionId,
    publishedVersionNumber, isFlowLoading, engine,
  };
  const sourceKey = [
    toolId, assistantId || "", currentSource, currentVersionNumber, currentVersionId || "",
    publishedVersionNumber, String(isDirty), engine,
  ].join(":");
  const latestSourceKeyRef = useRef(sourceKey);
  latestSourceKeyRef.current = sourceKey;
  const sourceKeyRef = useRef(sourceKey);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    if (state?.current_node) {
      onNodeChangeRef.current?.(state.current_node);
    }
  }, [state?.current_node]);

  const clearLocalSession = useCallback(() => {
    sessionIdRef.current = null;
    sessionSourceKeyRef.current = null;
    setSessionId(null);
    setMessages([]);
    setState(null);
    setVariables([]);
    setRuntimeEvidence(null);
    setError(null);
    onNodeChangeRef.current?.(null);
  }, []);

  const resetSimulation = useCallback(async () => {
    generationRef.current += 1;
    startingRef.current = false;
    sendingRef.current = false;
    setIsStarting(false);
    setIsLoading(false);
    const ownedSession = sessionIdRef.current;
    clearLocalSession();
    try {
      await deleteSimulationSession(authFetchRef.current, ownedSession);
    } catch {
      // A reset remains usable if best-effort server cleanup fails.
    }
  }, [clearLocalSession]);

  const startSimulation = useCallback(async () => {
    if (startingRef.current || sessionIdRef.current) return;
    startingRef.current = true;
    setIsStarting(true);
    setError(null);
    const generation = generationRef.current;
    const current = latestRef.current;
    const startedSourceKey = latestSourceKeyRef.current;
    if (current.engine === "native" && current.isFlowLoading) {
      setError("Wait for the selected flow to finish loading before starting a native test.");
      startingRef.current = false;
      setIsStarting(false);
      return;
    }
    try {
      const result = await requestSimulationStart({
        authFetch: (url, options) => authFetchRef.current(url, options),
        toolId: current.toolId,
        engine: current.engine,
        snapshot: {
          assistantId: current.assistantId,
          isDirty: current.isDirty,
          currentSource: current.currentSource,
          currentVersionNumber: current.currentVersionNumber,
          publishedVersionNumber: current.publishedVersionNumber,
          currentVersionId: current.currentVersionId,
        },
      });
      const sourceWasReplaced = latestSourceKeyRef.current !== startedSourceKey;
      if (sourceWasReplaced) {
        if (result.ok) {
          try {
            await deleteSimulationSession(authFetchRef.current, result.data.session_id || null);
          } catch {
            // A response for a replaced flow must never be attached to this sidebar.
          }
        }
        return;
      }
      if (!mountedRef.current || generation !== generationRef.current) {
        if (result.ok) {
          try {
            await deleteSimulationSession(authFetchRef.current, result.data.session_id || null);
          } catch {
            // The result belongs to a replaced editor; never attach it locally.
          }
        }
        return;
      }
      if (!result.ok) {
        setError(result.error);
        return;
      }
      const data = result.data;
      sessionIdRef.current = data.session_id!;
      sessionSourceKeyRef.current = startedSourceKey;
      setSessionId(data.session_id!);
      setMessages(data.messages || []);
      setState(data.state || null);
      setVariables(data.variables_to_collect || []);
      setRuntimeEvidence({
        engine: typeof data.runtime?.engine === "string"
          ? data.runtime.engine
          : current.engine === "native" ? "native_pilot" : "Legacy",
        version: typeof data.runtime?.version_number === "number"
          ? data.runtime.version_number
          : current.engine === "native" ? current.currentVersionNumber : 0,
        flowVersionId: typeof data.runtime?.flow_version_id === "string"
          ? data.runtime.flow_version_id
          : undefined,
      });
      if (data.state?.current_node) {
        onNodeChangeRef.current?.(data.state.current_node);
      }
    } catch (err) {
      if (mountedRef.current && generation === generationRef.current &&
          latestSourceKeyRef.current === startedSourceKey) {
        setError(err instanceof Error ? err.message : "The simulation could not start. Try again.");
      }
    } finally {
      startingRef.current = false;
      if (mountedRef.current && generation === generationRef.current) setIsStarting(false);
    }
  }, []);

  const sendMessage = useCallback(async () => {
    const ownedSession = sessionIdRef.current;
    const sessionSourceKey = sessionSourceKeyRef.current;
    const userMessage = inputRef.current.trim();
    if (!ownedSession || !sessionSourceKey || !userMessage || sendingRef.current) return;
    sendingRef.current = true;
    const generation = generationRef.current;
    setInput("");
    setIsLoading(true);
    setError(null);
    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);

    try {
      const response = await authFetchRef.current("/api/simulate/message", {
        method: "POST",
        body: JSON.stringify({ session_id: ownedSession, message: userMessage }),
      });
      if (!mountedRef.current || generation !== generationRef.current ||
          latestSourceKeyRef.current !== sessionSourceKey) return;
      if (!response.ok) {
        const detail = await response.json().then((body) => body?.detail ?? body?.error).catch(() => undefined);
        if (mountedRef.current && generation === generationRef.current &&
            latestSourceKeyRef.current === sessionSourceKey) {
          setError(formatNativeError(detail));
        }
        return;
      }
      const data = await response.json();
      if (!mountedRef.current || generation !== generationRef.current ||
          latestSourceKeyRef.current !== sessionSourceKey) return;
      if (data.error) {
        setError(formatNativeError(data.error));
        return;
      }
      setMessages(data.messages || []);
      setState(data.state || null);
      if (data.state?.current_node) onNodeChangeRef.current?.(data.state.current_node);
    } catch {
      if (mountedRef.current && generation === generationRef.current &&
          latestSourceKeyRef.current === sessionSourceKey) {
        setError("The message could not be sent. Check the connection and try again.");
      }
    } finally {
      sendingRef.current = false;
      if (mountedRef.current && generation === generationRef.current) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      const ownedSession = sessionIdRef.current;
      sessionIdRef.current = null;
      sessionSourceKeyRef.current = null;
      deleteSimulationSession(authFetchRef.current, ownedSession).catch(() => {});
      onNodeChangeRef.current?.(null);
    };
  }, []);

  useEffect(() => {
    if (sourceKeyRef.current === sourceKey) return;
    sourceKeyRef.current = sourceKey;
    if (sessionIdRef.current || startingRef.current || sendingRef.current) {
      void resetSimulation();
    }
  }, [resetSimulation, sourceKey]);

  return (
    <section aria-label="Flow Simulator" className="h-full flex flex-col bg-[#0f0f0f] border-l border-[#2a2a2a]">
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#2a2a2a] bg-[#141414]">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded bg-blue-600 flex items-center justify-center">
            <Play className="w-3 h-3 text-white" />
          </div>
          <div>
            <h3 className="text-sm font-medium text-white">Flow Simulator</h3>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {sessionId && (
            <button
              onClick={resetSimulation}
              className="p-1.5 text-gray-400 hover:text-white hover:bg-[#2a2a2a] rounded transition-colors"
              title="Reset simulation"
              aria-label="Reset simulation"
            >
              <RotateCcw className="w-4 h-4" />
            </button>
          )}
          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-white hover:bg-[#2a2a2a] rounded transition-colors"
            title="Close simulator"
            aria-label="Close simulator"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {!sessionId ? (
        <div className="flex-1 flex items-center justify-center p-4">
          <div className="w-full max-w-xs text-center">
            {error && (
              <div role="alert" aria-label="Simulation error" aria-live="assertive" className="mb-4 px-3 py-2 bg-red-900/30 border border-red-700 rounded text-red-400 text-xs">
                {error}
              </div>
            )}
            <label htmlFor="simulation-engine" className="block text-left text-xs text-gray-400 mb-1">
              Test engine
            </label>
            <select
              id="simulation-engine"
              aria-label="Test engine"
              value={engine}
              onChange={(event) => setEngine(event.target.value as SimulationEngine)}
              disabled={isStarting}
              className="w-full mb-3 bg-[#1a1a1a] border border-[#333] rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
            >
              <option value="legacy">Legacy</option>
              <option value="native">Native development</option>
            </select>
            {engine === "native" && (
              <p className="mb-4 text-left text-[11px] leading-relaxed text-amber-200/80">
                Bounded, read-only six-node pilot. It does not support every node type, booking, or messaging, and does not switch production publishing.
                Requires a clean, current published version and an assistant.
              </p>
            )}
            {engine === "native" && !assistantId && (
              <p className="mb-3 text-left text-[11px] leading-relaxed text-amber-200/80">
                No linked primary assistant was found. Link one in Tool settings and reload to enable native testing.
              </p>
            )}
            <p className="text-gray-400 text-sm mb-4">
              Test your flow with a simulated conversation
            </p>
            <button
              onClick={startSimulation}
              disabled={isStarting || isFlowLoading}
              aria-label={`Start ${engine === "native" ? "native development" : "legacy"} test`}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors mx-auto"
            >
              {isStarting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Play className="w-4 h-4" />
              )}
              Start Test
            </button>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex flex-col min-h-0">
          {state && (
            <div className="border-b border-[#2a2a2a]">
              <button
                onClick={() => setShowSlotTracker(!showSlotTracker)}
                className="w-full px-3 py-2 flex items-center justify-between text-xs text-gray-400 hover:bg-[#1a1a1a] transition-colors"
              >
                <span>Collected Data ({Object.keys(state.collected_slots).length}/{variables.length})</span>
                {showSlotTracker ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              </button>
              {showSlotTracker && (
                <div className="px-3 pb-3">
                  <SlotTracker
                    collectedSlots={state.collected_slots}
                    variablesToCollect={variables}
                    progress={state.progress}
                    compact
                  />
                </div>
              )}
            </div>
          )}

          {runtimeEvidence && (
            <div
              aria-label="Simulation runtime evidence"
              className="px-3 py-2 border-b border-[#2a2a2a] text-[11px] text-gray-300"
            >
              <span className="text-gray-500">Runtime evidence</span>
              <span className="ml-2">{runtimeEvidence.engine}</span>
              {runtimeEvidence.version > 0 && <span className="ml-2">published v{runtimeEvidence.version}</span>}
              {runtimeEvidence.engine === "native_pilot" && runtimeEvidence.flowVersionId && (
                <span className="block mt-1 text-gray-500 break-all">Flow version: {runtimeEvidence.flowVersionId}</span>
              )}
            </div>
          )}

          <div className="flex-1 overflow-y-auto p-3 space-y-1 min-h-0">
            {messages.map((message, index) => (
              <ChatMessage
                key={index}
                role={message.role}
                content={message.content}
                metadata={message.metadata}
                compact
              />
            ))}
            {isLoading && (
              <div className="flex justify-start">
                <div className="bg-[#2a2a2a] rounded-lg px-3 py-1.5 flex items-center gap-2">
                  <Loader2 className="w-3 h-3 animate-spin text-gray-400" />
                  <span className="text-xs text-gray-400">Thinking...</span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {error && (
            <div role="alert" aria-label="Simulation error" aria-live="assertive" className="px-3 py-2 bg-red-900/30 border-t border-red-700 text-red-400 text-xs">
              {error}
            </div>
          )}

          <div className="p-3 border-t border-[#2a2a2a]">
            {state?.is_ended ? (
              <div className="text-center py-2">
                <p className="text-gray-400 text-xs mb-2">Simulation ended</p>
                <button
                  onClick={resetSimulation}
                  className="text-blue-400 hover:text-blue-300 text-xs"
                >
                  Start new test
                </button>
              </div>
            ) : (
              <div className="flex gap-2">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && sendMessage()}
                  placeholder="Type as guest..."
                  aria-label="Message as guest"
                  disabled={isLoading || isFlowLoading}
                  className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-1.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                />
                <button
                  onClick={sendMessage}
                  disabled={isLoading || isFlowLoading || !input.trim()}
                  className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs rounded transition-colors"
                >
                  Send
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
