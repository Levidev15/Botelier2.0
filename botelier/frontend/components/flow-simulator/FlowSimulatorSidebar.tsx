"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import ChatMessage from "./ChatMessage";
import SlotTracker from "./SlotTracker";
import { Play, RotateCcw, Loader2, X, ChevronDown, ChevronUp } from "lucide-react";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import NativePreviewCard from "./NativePreviewCard";
import {
  buildNativePreviewMessage,
  getNativePendingPreview,
  hasNativePendingPreview,
  isNativePreviewCurrent,
  nativePreviewEffectMessages,
} from "./nativePreview";
import type {
  NativePreviewInput,
  NativePreviewOwnership,
  PendingNativePreview,
} from "./nativePreview";
import {
  appendNativeAssistantHistory,
  initializeNativeAssistantHistory,
  mergeNativeAssistantTail,
} from "./nativeConversation";
import type {
  ConversationMessage,
  NativeServerHistoryCursor,
} from "./nativeConversation";
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

type Message = ConversationMessage;

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function normalizeLegacyMessages(value: unknown): Message[] {
  if (!Array.isArray(value)) return [];
  return value.slice(-100).flatMap((entry) => {
    if (!isRecord(entry) ||
        !["user", "assistant", "system"].includes(String(entry.role)) ||
        typeof entry.content !== "string" || entry.content.length > 16_384) return [];
    const message: Message = {
      role: entry.role as Message["role"],
      content: entry.content,
    };
    if (isRecord(entry.metadata)) {
      const metadata: NonNullable<Message["metadata"]> = {};
      if (typeof entry.metadata.function_called === "string" &&
          entry.metadata.function_called.length <= 128) {
        metadata.function_called = entry.metadata.function_called;
      }
      if (isRecord(entry.metadata.function_result)) {
        metadata.function_result = entry.metadata.function_result;
      }
      if (typeof entry.metadata.record_saved === "boolean") {
        metadata.record_saved = entry.metadata.record_saved;
      }
      if (Object.keys(metadata).length) message.metadata = metadata;
    }
    return [message];
  });
}

function normalizeSimulationState(value: unknown): SimulationState | null {
  if (!isRecord(value)) return null;
  const progress = isRecord(value.progress) ? value.progress : {};
  const finite = (input: unknown) =>
    typeof input === "number" && Number.isFinite(input) ? input : 0;
  return {
    collected_slots: isRecord(value.collected_slots) ? value.collected_slots : {},
    current_node: typeof value.current_node === "string" ? value.current_node : null,
    pending_slot: typeof value.pending_slot === "string" ? value.pending_slot : null,
    is_complete: value.is_complete === true,
    is_ended: value.is_ended === true,
    progress: {
      collected: finite(progress.collected),
      total: finite(progress.total),
      percentage: finite(progress.percentage),
    },
    ...(Object.prototype.hasOwnProperty.call(value, "pending_preview")
      ? { pending_preview: value.pending_preview }
      : {}),
    ...(Object.prototype.hasOwnProperty.call(value, "preview_effects")
      ? { preview_effects: value.preview_effects }
      : {}),
  };
}

function normalizeVariables(value: unknown): SimulationVariable[] {
  if (!Array.isArray(value)) return [];
  return value.slice(0, 200).flatMap((entry) => {
    if (!isRecord(entry) || typeof entry.key !== "string" || !/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(entry.key) ||
        typeof entry.type !== "string") return [];
    return [{
      key: entry.key,
      type: entry.type.slice(0, 32),
      description: typeof entry.description === "string" ? entry.description.slice(0, 500) : "",
      required: entry.required === true,
      ...(Array.isArray(entry.choices)
        ? { choices: entry.choices.filter((choice): choice is string => typeof choice === "string").slice(0, 100) }
        : {}),
    }];
  });
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
    executionMode?: string;
    effectMode?: string;
    effectsSimulated?: boolean;
  } | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef<SimulationState | null>(state);
  const nativeHistoryCursorRef = useRef<NativeServerHistoryCursor | null>(null);
  const { authFetch } = useAuthToken();
  const authFetchRef = useRef(authFetch);
  authFetchRef.current = authFetch;
  stateRef.current = state;
  const onNodeChangeRef = useRef(onNodeChange);
  onNodeChangeRef.current = onNodeChange;
  const sessionIdRef = useRef<string | null>(null);
  const sessionSourceKeyRef = useRef<string | null>(null);
  const generationRef = useRef(0);
  const startingRef = useRef(false);
  const startingTokenRef = useRef<number | null>(null);
  const inFlightTokenRef = useRef<number | null>(null);
  const actionSequenceRef = useRef(0);
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
    nativeHistoryCursorRef.current = null;
    stateRef.current = null;
    setState(null);
    setVariables([]);
    setRuntimeEvidence(null);
    setError(null);
    onNodeChangeRef.current?.(null);
  }, []);

  const resetSimulation = useCallback(async () => {
    generationRef.current += 1;
    startingRef.current = false;
    startingTokenRef.current = null;
    inFlightTokenRef.current = null;
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
    if (startingRef.current || sessionIdRef.current || inFlightTokenRef.current !== null) return;
    const startToken = ++actionSequenceRef.current;
    startingTokenRef.current = startToken;
    startingRef.current = true;
    setIsStarting(true);
    setError(null);
    const generation = generationRef.current;
    const current = latestRef.current;
    const startedSourceKey = latestSourceKeyRef.current;
    if (current.engine === "native" && current.isFlowLoading) {
      setError("Wait for the selected flow to finish loading before starting a native test.");
      if (startingTokenRef.current === startToken) {
        startingTokenRef.current = null;
        startingRef.current = false;
        setIsStarting(false);
      }
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
      const nextState = normalizeSimulationState(data.state);
      stateRef.current = nextState;
      if (current.engine === "native") {
        const history = initializeNativeAssistantHistory(data.messages, {
          sessionId: data.session_id!,
          sourceKey: startedSourceKey,
          generation,
        });
        nativeHistoryCursorRef.current = history.cursor;
        setMessages(history.messages);
      } else {
        nativeHistoryCursorRef.current = null;
        setMessages(normalizeLegacyMessages(data.messages));
      }
      setState(nextState);
      setVariables(normalizeVariables(data.variables_to_collect));
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
        executionMode: typeof data.runtime?.execution_mode === "string"
          ? data.runtime.execution_mode
          : undefined,
        effectMode: typeof data.runtime?.effect_mode === "string"
          ? data.runtime.effect_mode
          : undefined,
        effectsSimulated: data.runtime?.effects_simulated === true,
      });
      if (nextState?.current_node) {
        onNodeChangeRef.current?.(nextState.current_node);
      }
    } catch (err) {
      if (mountedRef.current && startingTokenRef.current === startToken &&
          generation === generationRef.current &&
          latestSourceKeyRef.current === startedSourceKey) {
        setError(err instanceof Error ? err.message : "The simulation could not start. Try again.");
      }
    } finally {
      if (startingTokenRef.current === startToken) {
        startingTokenRef.current = null;
        startingRef.current = false;
        if (mountedRef.current && generation === generationRef.current) setIsStarting(false);
      }
    }
  }, []);

  const sendMessage = useCallback(async () => {
    const ownedSession = sessionIdRef.current;
    const sessionSourceKey = sessionSourceKeyRef.current;
    const userMessage = inputRef.current.trim();
    if (!ownedSession || !sessionSourceKey || !userMessage || inFlightTokenRef.current !== null) return;
    if (hasNativePendingPreview(stateRef.current)) {
      setError(getNativePendingPreview(stateRef.current)
        ? "Supply a sample response for the waiting action before sending another message."
        : "The server returned invalid waiting-action metadata. Reset the native test.");
      return;
    }
    const actionToken = ++actionSequenceRef.current;
    inFlightTokenRef.current = actionToken;
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
        if (mountedRef.current && inFlightTokenRef.current === actionToken &&
            generation === generationRef.current &&
            latestSourceKeyRef.current === sessionSourceKey) {
          setError(formatNativeError(detail));
        }
        return;
      }
      const data = await response.json();
      if (!mountedRef.current || inFlightTokenRef.current !== actionToken ||
          generation !== generationRef.current ||
          latestSourceKeyRef.current !== sessionSourceKey) return;
      if (isRecord(data) && data.error) {
        setError(formatNativeError(data.error));
        return;
      }
      if (!isRecord(data)) {
        setError("The simulation returned an invalid response. Reset and try again.");
        return;
      }
      const nextState = normalizeSimulationState(data.state);
      stateRef.current = nextState;
      if (latestRef.current.engine === "native") {
        const history = appendNativeAssistantHistory(
          data.messages,
          nativeHistoryCursorRef.current,
          { sessionId: ownedSession, sourceKey: sessionSourceKey, generation },
        );
        nativeHistoryCursorRef.current = history.cursor;
        setMessages((previous) => mergeNativeAssistantTail(previous, history.messages));
      } else {
        setMessages(normalizeLegacyMessages(data.messages));
      }
      setState(nextState);
      if (hasNativePendingPreview(nextState)) setInput("");
      if (nextState?.current_node) onNodeChangeRef.current?.(nextState.current_node);
    } catch {
      if (mountedRef.current && inFlightTokenRef.current === actionToken &&
          generation === generationRef.current &&
          latestSourceKeyRef.current === sessionSourceKey) {
        setError("The message could not be sent. Check the connection and try again.");
      }
    } finally {
      if (inFlightTokenRef.current === actionToken) {
        inFlightTokenRef.current = null;
        if (mountedRef.current && generation === generationRef.current) setIsLoading(false);
      }
    }
  }, []);

  const submitNativePreview = useCallback(async (input: NativePreviewInput) => {
    const ownedSession = sessionIdRef.current;
    const sessionSourceKey = sessionSourceKeyRef.current;
    const pending = getNativePendingPreview(stateRef.current);
    if (!ownedSession || !sessionSourceKey || latestRef.current.engine !== "native" ||
        runtimeEvidence?.engine !== "native_pilot" || !pending ||
        pending.request_id !== input.requestId || pending.expires_in_seconds <= 0) {
      setError("This sample no longer matches the waiting action. Reset the native test.");
      return;
    }
    if (inFlightTokenRef.current !== null) return;
    let requestBody: Record<string, unknown>;
    try {
      requestBody = buildNativePreviewMessage({
        sessionId: ownedSession,
        pending,
        dataJson: input.dataJson,
        statusCode: input.statusCode,
        outcome: input.outcome,
      });
    } catch (err) {
      setError(err instanceof Error
        ? err.message
        : "The sample could not be used. Check it and try again.");
      return;
    }
    const actionToken = ++actionSequenceRef.current;
    inFlightTokenRef.current = actionToken;
    const generation = generationRef.current;
    const requestId = pending.request_id;
    const owner: NativePreviewOwnership = {
      requestId,
      sessionId: ownedSession,
      sourceKey: sessionSourceKey,
      generation,
      inFlightToken: actionToken,
    };
    setIsLoading(true);
    setError(null);
    const requestStillOwned = () =>
      mountedRef.current &&
      sessionSourceKeyRef.current === sessionSourceKey &&
      isNativePreviewCurrent(owner, {
        requestId: getNativePendingPreview(stateRef.current)?.request_id ?? "",
        sessionId: sessionIdRef.current ?? "",
        sourceKey: latestSourceKeyRef.current,
        generation: generationRef.current,
        inFlightToken: inFlightTokenRef.current ?? -1,
      });

    try {
      const response = await authFetchRef.current("/api/simulate/message", {
        method: "POST",
        body: JSON.stringify(requestBody),
      });
      if (!requestStillOwned()) return;
      if (!response.ok) {
        const detail = await response.json()
          .then((body) => isRecord(body) ? body.detail ?? body.error : undefined)
          .catch(() => undefined);
        if (requestStillOwned()) setError(formatNativeError(detail));
        return;
      }
      let data: unknown;
      try {
        data = await response.json();
      } catch {
        data = null;
      }
      if (!requestStillOwned()) return;
      if (!isRecord(data) || !isRecord(data.state)) {
        setError("The sample response was invalid. Reset the native test and try again.");
        return;
      }
      if (data.error) {
        setError(formatNativeError(data.error));
        return;
      }
      const nextState = normalizeSimulationState(data.state);
      if (!nextState) {
        setError("The sample response was invalid. Reset the native test and try again.");
        return;
      }
      stateRef.current = nextState;
      const history = appendNativeAssistantHistory(
        data.messages,
        nativeHistoryCursorRef.current,
        { sessionId: ownedSession, sourceKey: sessionSourceKey, generation },
      );
      nativeHistoryCursorRef.current = history.cursor;
      setMessages((previous) => mergeNativeAssistantTail(previous, history.messages));
      setState(nextState);
      if (Object.prototype.hasOwnProperty.call(data, "variables_to_collect")) {
        setVariables(normalizeVariables(data.variables_to_collect));
      }
      setInput("");
      if (nextState.current_node) onNodeChangeRef.current?.(nextState.current_node);
    } catch {
      if (requestStillOwned()) {
        setError("The sample could not be submitted. Check the connection and retry.");
      }
    } finally {
      if (inFlightTokenRef.current === actionToken) {
        inFlightTokenRef.current = null;
        if (mountedRef.current && generationRef.current === generation) setIsLoading(false);
      }
    }
  }, [runtimeEvidence?.engine]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      startingRef.current = false;
      startingTokenRef.current = null;
      inFlightTokenRef.current = null;
      const ownedSession = sessionIdRef.current;
      sessionIdRef.current = null;
      sessionSourceKeyRef.current = null;
      stateRef.current = null;
      nativeHistoryCursorRef.current = null;
      deleteSimulationSession(authFetchRef.current, ownedSession).catch(() => {});
      onNodeChangeRef.current?.(null);
    };
  }, []);

  useEffect(() => {
    if (sourceKeyRef.current === sourceKey) return;
    sourceKeyRef.current = sourceKey;
    if (sessionIdRef.current || startingRef.current || inFlightTokenRef.current !== null) {
      void resetSimulation();
    }
  }, [resetSimulation, sourceKey]);

  const pendingPreviewPresent = hasNativePendingPreview(state);
  const pendingPreview: PendingNativePreview | null = getNativePendingPreview(state);
  const verifiedNativePreview =
    engine === "native" &&
    runtimeEvidence?.engine === "native_pilot" &&
    runtimeEvidence.executionMode === "preview" &&
    runtimeEvidence.effectMode === "simulation" &&
    runtimeEvidence.effectsSimulated === true;
  const malformedPendingPreview = pendingPreviewPresent && (!pendingPreview || !verifiedNativePreview);
  const previewEffects = nativePreviewEffectMessages(state?.preview_effects);

  return (
    <section aria-label="Flow Simulator" className="h-full w-full min-w-0 flex flex-col bg-[#0f0f0f] border-0 md:border-l md:border-[#2a2a2a]">
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#2a2a2a] bg-[#141414]">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded bg-blue-600 flex items-center justify-center">
            <Play className="w-3 h-3 text-white" />
          </div>
          <div>
            <h3 className="text-sm font-medium text-white">Test Lab</h3>
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
                The server validates the complete published flow, version, assistant, model and attached resources before native development starts. No provider fallback or production routing change is made.
                The configured model may incur provider usage or cost. API and MCP actions pause for operator-supplied samples; SMS/email, Record and transfer effects are simulated—not sent, saved or moved.
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
              className="px-3 py-2 border-b border-[#2a2a2a] text-[11px] text-gray-300 min-w-0"
            >
              <span className="text-gray-500">Runtime evidence</span>
              <span className="ml-2">{runtimeEvidence.engine}</span>
              {runtimeEvidence.version > 0 && <span className="ml-2">published v{runtimeEvidence.version}</span>}
              {runtimeEvidence.engine === "native_pilot" && runtimeEvidence.flowVersionId && (
                <span className="block mt-1 text-gray-500 break-all">Flow version: {runtimeEvidence.flowVersionId}</span>
              )}
              {runtimeEvidence.engine === "native_pilot" && (
                <p className="mt-2 text-amber-200">
                  Preview rehearsal · configured model may incur provider usage. External effects are simulated only.
                </p>
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
            {previewEffects.length > 0 && (
              <section aria-label="Simulated preview effects" className="my-3 rounded-lg border border-amber-800/60 bg-amber-950/20 p-2.5">
                <h4 className="mb-1 text-[11px] font-semibold text-amber-100">Simulated effects</h4>
                <ul className="space-y-1">
                  {previewEffects.map((effect, index) => (
                    <li key={`${effect.node_id}-${index}`} className="text-[11px] text-amber-100/90">
                      <span className="font-mono">{effect.node_id}</span>: {effect.label}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {malformedPendingPreview && (
              <div role="alert" aria-label="Invalid sample request" className="my-3 rounded border border-red-700 bg-red-950/30 p-2.5 text-xs text-red-200">
                The server returned invalid or mismatched waiting-action metadata. Reset the test; no sample was submitted.
              </div>
            )}
            {pendingPreviewPresent && pendingPreview && verifiedNativePreview && (
              <NativePreviewCard
                key={pendingPreview.request_id}
                pending={pendingPreview}
                isLoading={isLoading}
                onSubmit={submitNativePreview}
              />
            )}
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
                  placeholder={pendingPreviewPresent ? "Waiting for a sample response..." : "Type as guest..."}
                  aria-label="Message as guest"
                  disabled={isLoading || isFlowLoading || pendingPreviewPresent}
                  className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-1.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                />
                <button
                  onClick={sendMessage}
                  disabled={isLoading || isFlowLoading || pendingPreviewPresent || !input.trim()}
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
