"use client";

import { useState, useRef, useEffect } from "react";
import ChatMessage from "./ChatMessage";
import SlotTracker from "./SlotTracker";
import FunctionPicker from "./FunctionPicker";
import { X, Play, RotateCcw, Loader2 } from "lucide-react";

interface FlowSimulatorProps {
  toolId: string;
  toolName: string;
  onClose: () => void;
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

interface SuggestedFunction {
  name: string;
  description: string;
  parameters: {
    type?: string;
    properties?: Record<string, { type: string; description: string }>;
    required?: string[];
  };
}

export default function FlowSimulator({
  toolId,
  toolName,
  onClose,
}: FlowSimulatorProps) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [state, setState] = useState<SimulationState | null>(null);
  const [variables, setVariables] = useState<Variable[]>([]);
  const [suggestedFunctions, setSuggestedFunctions] = useState<SuggestedFunction[]>([]);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

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
      setSuggestedFunctions([]);
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
      setSuggestedFunctions(data.suggested_functions);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send message");
    } finally {
      setIsLoading(false);
    }
  };

  const executeFunction = async (functionName: string, args: Record<string, unknown>) => {
    if (!sessionId || isLoading) return;

    setIsLoading(true);
    setError(null);

    setMessages((prev) => [
      ...prev,
      { role: "user", content: `[Executing: ${functionName}(${JSON.stringify(args)})]` },
    ]);

    try {
      const response = await fetch("/api/simulate/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message: `Execute function ${functionName}`,
          function_call: functionName,
          function_args: args,
        }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || "Failed to execute function");
      }

      const data = await response.json();
      setMessages(data.messages);
      setState(data.state);
      setSuggestedFunctions(data.suggested_functions);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to execute function");
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
    setSuggestedFunctions([]);
    setError(null);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-[#0f0f0f] border border-[#2a2a2a] rounded-lg w-full max-w-5xl h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#2a2a2a]">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded bg-blue-600 flex items-center justify-center">
              <Play className="w-4 h-4 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Flow Simulator</h2>
              <p className="text-xs text-gray-500">{toolName}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {sessionId && (
              <button
                onClick={resetSimulation}
                className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-400 hover:text-white bg-[#2a2a2a] hover:bg-[#3a3a3a] rounded transition-colors"
              >
                <RotateCcw className="w-4 h-4" />
                Reset
              </button>
            )}
            <button
              onClick={onClose}
              className="p-1.5 text-gray-400 hover:text-white hover:bg-[#2a2a2a] rounded transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {!sessionId ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              {error && (
                <div className="mb-4 px-4 py-2 bg-red-900/30 border border-red-700 rounded text-red-400 text-sm">
                  {error}
                </div>
              )}
              <p className="text-gray-400 mb-4">
                Start a simulation to test the flow without making a phone call.
              </p>
              <button
                onClick={startSimulation}
                disabled={isStarting}
                className="flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors mx-auto"
              >
                {isStarting ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <Play className="w-5 h-5" />
                )}
                Start Simulation
              </button>
            </div>
          </div>
        ) : (
          <div className="flex-1 flex overflow-hidden">
            <div className="flex-1 flex flex-col">
              <div className="flex-1 overflow-y-auto p-4 space-y-1">
                {messages.map((message, index) => (
                  <ChatMessage
                    key={index}
                    role={message.role}
                    content={message.content}
                    metadata={message.metadata}
                  />
                ))}
                {isLoading && (
                  <div className="flex justify-start mb-3">
                    <div className="bg-[#2a2a2a] rounded-lg px-4 py-2 flex items-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
                      <span className="text-sm text-gray-400">Processing...</span>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>

              {error && (
                <div className="px-4 py-2 bg-red-900/30 border-t border-red-700 text-red-400 text-sm">
                  {error}
                </div>
              )}

              <div className="p-4 border-t border-[#2a2a2a]">
                {state?.is_ended ? (
                  <div className="text-center py-3">
                    <p className="text-gray-400 mb-2">Simulation ended</p>
                    <button
                      onClick={resetSimulation}
                      className="text-blue-400 hover:text-blue-300 text-sm"
                    >
                      Start a new simulation
                    </button>
                  </div>
                ) : (
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && sendMessage()}
                      placeholder="Type a message as a guest..."
                      disabled={isLoading}
                      className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-4 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                    />
                    <button
                      onClick={sendMessage}
                      disabled={isLoading || !input.trim()}
                      className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg transition-colors"
                    >
                      Send
                    </button>
                  </div>
                )}
              </div>
            </div>

            <div className="w-80 border-l border-[#2a2a2a] overflow-y-auto p-4 space-y-4">
              {state && (
                <SlotTracker
                  collectedSlots={state.collected_slots}
                  variablesToCollect={variables}
                  progress={state.progress}
                />
              )}
              
              {suggestedFunctions.length > 0 && (
                <FunctionPicker
                  functions={suggestedFunctions}
                  onExecute={executeFunction}
                  disabled={isLoading || state?.is_ended}
                />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
