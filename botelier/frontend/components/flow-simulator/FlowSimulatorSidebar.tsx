"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import ChatMessage from "./ChatMessage";
import SlotTracker from "./SlotTracker";
import { Play, RotateCcw, Loader2, X, ChevronDown, ChevronUp } from "lucide-react";

interface FlowSimulatorSidebarProps {
  toolId: string;
  toolName: string;
  onClose: () => void;
  onNodeChange?: (nodeId: string | null) => void;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  metadata?: {
    function_called?: string;
    function_result?: Record<string, unknown>;
  };
}

interface SimulationState {
  collected_slots: Record<string, unknown>;
  current_node: string | null;
  pending_slot: string | null;
  is_complete: boolean;
  is_ended: boolean;
  progress: {
    collected: number;
    total: number;
    percentage: number;
  };
}

interface Variable {
  key: string;
  type: string;
  description: string;
  required: boolean;
  choices?: string[];
}

export default function FlowSimulatorSidebar({
  toolId,
  toolName,
  onClose,
  onNodeChange,
}: FlowSimulatorSidebarProps) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [state, setState] = useState<SimulationState | null>(null);
  const [variables, setVariables] = useState<Variable[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showSlotTracker, setShowSlotTracker] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    if (state?.current_node && onNodeChange) {
      onNodeChange(state.current_node);
    }
  }, [state?.current_node, onNodeChange]);

  const startSimulation = async () => {
    setIsStarting(true);
    setError(null);
    try {
      const response = await fetch("/api/simulate/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool_id: toolId }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || "Failed to start simulation");
      }

      const data = await response.json();
      setSessionId(data.session_id);
      setMessages(data.messages);
      setState(data.state);
      setVariables(data.variables_to_collect);
      
      if (data.state?.current_node && onNodeChange) {
        onNodeChange(data.state.current_node);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start simulation");
    } finally {
      setIsStarting(false);
    }
  };

  const sendMessage = async () => {
    if (!sessionId || !input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput("");
    setIsLoading(true);
    setError(null);

    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);

    try {
      const response = await fetch("/api/simulate/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message: userMessage,
        }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || "Failed to send message");
      }

      const data = await response.json();
      setMessages(data.messages);
      setState(data.state);
      
      if (data.state?.current_node && onNodeChange) {
        onNodeChange(data.state.current_node);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send message");
    } finally {
      setIsLoading(false);
    }
  };

  const resetSimulation = async () => {
    if (sessionId) {
      try {
        await fetch(`/api/simulate/session/${sessionId}`, { method: "DELETE" });
      } catch {
        // Ignore cleanup errors
      }
    }
    setSessionId(null);
    setMessages([]);
    setState(null);
    setVariables([]);
    setError(null);
    if (onNodeChange) {
      onNodeChange(null);
    }
  };

  useEffect(() => {
    return () => {
      if (sessionId) {
        fetch(`/api/simulate/session/${sessionId}`, { method: "DELETE" }).catch(() => {});
      }
      if (onNodeChange) {
        onNodeChange(null);
      }
    };
  }, [sessionId, onNodeChange]);

  return (
    <div className="h-full flex flex-col bg-[#0f0f0f] border-l border-[#2a2a2a]">
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
            >
              <RotateCcw className="w-4 h-4" />
            </button>
          )}
          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-white hover:bg-[#2a2a2a] rounded transition-colors"
            title="Close simulator"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {!sessionId ? (
        <div className="flex-1 flex items-center justify-center p-4">
          <div className="text-center">
            {error && (
              <div className="mb-4 px-3 py-2 bg-red-900/30 border border-red-700 rounded text-red-400 text-xs">
                {error}
              </div>
            )}
            <p className="text-gray-400 text-sm mb-4">
              Test your flow with a simulated conversation
            </p>
            <button
              onClick={startSimulation}
              disabled={isStarting}
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
            <div className="px-3 py-2 bg-red-900/30 border-t border-red-700 text-red-400 text-xs">
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
                  disabled={isLoading}
                  className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-1.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                />
                <button
                  onClick={sendMessage}
                  disabled={isLoading || !input.trim()}
                  className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs rounded transition-colors"
                >
                  Send
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
