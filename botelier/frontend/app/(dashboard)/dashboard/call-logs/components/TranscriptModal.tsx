"use client";

import { useState } from "react";
import { X, Bot, User, Clock, Phone, PhoneForwarded, Sparkles, Tag, Wrench, BarChart3, ClipboardCheck, Loader2 } from "lucide-react";
import { notify } from "@/lib/notifications";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface TranscriptEntry {
  role: string;
  content?: string;
  text?: string;
  timestamp?: string;
  interrupted?: boolean;
}

interface CallLeg {
  id: string;
  leg_number: number;
  leg_type: string;
  participant: string | null;
  participant_name: string | null;
  status: string;
  duration_seconds: number;
}

interface CallLog {
  id: string;
  hotel_id?: string;
  reference_id?: string | null;
  caller_number: string | null;
  to_number: string | null;
  status: string;
  started_at: string | null;
  duration_seconds: number;
  has_transfer: boolean;
  transcript: TranscriptEntry[] | null;
  legs: CallLeg[];
  assistant_name: string | null;
  phone_number_display: string | null;
  ai_summary: string | null;
  disposition_name: string | null;
  disposition_color: string | null;
  tool_name: string | null;
  flow_name: string | null;
  acw_resolution: string | null;
  acw_quality_score: number | null;
}

interface TranscriptModalProps {
  log: CallLog;
  onClose: () => void;
  onLogUpdated?: (updatedFields: Partial<CallLog>) => void;
}

function formatDuration(seconds: number): string {
  if (!seconds || seconds < 0) return "0:00";
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function formatDateTime(dateStr: string | null): string {
  if (!dateStr) return "-";
  const date = new Date(dateStr);
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

export default function TranscriptModal({ log, onClose, onLogUpdated }: TranscriptModalProps) {
  const transcript = log.transcript || [];
  const [running, setRunning] = useState(false);
  const { authHeaders } = useAuthToken();
  const hasTranscript = transcript.length > 0;

  const runPostCallQA = async () => {
    setRunning(true);
    try {
      const response = await fetch(`/api/call-logs/${log.id}/generate-summary`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ hotel_id: log.hotel_id }),
      });
      if (response.ok) {
        const result = await response.json();
        const updates: Partial<CallLog> = {
          ai_summary: result.summary,
          disposition_name: result.disposition?.name || null,
          disposition_color: result.disposition?.color || null,
          acw_resolution: result.acw_resolution || null,
          acw_quality_score: result.acw_quality_score ?? null,
        };
        if (onLogUpdated) onLogUpdated(updates);
        notify.success("Post Call QA complete");
      } else {
        const error = await response.json();
        notify.error(error.detail || "Failed to run Post Call QA");
      }
    } catch (error) {
      notify.error("Error running Post Call QA");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      <div className="relative bg-[#1a1a1a] border border-gray-700 rounded-xl shadow-2xl w-full max-w-2xl mx-4 max-h-[85vh] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-900/30 rounded-lg">
              <Phone className="h-5 w-5 text-blue-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-semibold text-white">Call Transcript</h3>
                {log.reference_id && (
                  <span className="font-mono text-[11px] text-gray-400 bg-gray-800 px-2 py-0.5 rounded border border-gray-700">
                    #{log.reference_id}
                  </span>
                )}
              </div>
              <p className="text-xs text-gray-400">
                {formatDateTime(log.started_at)} • {formatDuration(log.duration_seconds)}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-5 py-3 border-b border-gray-800 bg-[#141414]">
          <div className="flex flex-wrap gap-4 text-sm">
            <div className="flex items-center gap-2">
              <User className="h-4 w-4 text-gray-500" />
              <span className="text-gray-400">Caller:</span>
              <span className="text-white">{log.caller_number || "Unknown"}</span>
            </div>
            <div className="flex items-center gap-2">
              <Phone className="h-4 w-4 text-gray-500" />
              <span className="text-gray-400">Line:</span>
              <span className="text-white">{log.phone_number_display || log.to_number || "-"}</span>
            </div>
            <div className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-gray-500" />
              <span className="text-gray-400">Assistant:</span>
              <span className="text-white">{log.assistant_name || "-"}</span>
            </div>
            {log.has_transfer && (
              <div className="flex items-center gap-1 text-purple-400">
                <PhoneForwarded className="h-4 w-4" />
                <span>Call was transferred</span>
              </div>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {(log.ai_summary || log.disposition_name || log.acw_resolution || (log.acw_quality_score != null)) && (
            <div className="mb-6 p-4 bg-gradient-to-r from-purple-900/20 to-blue-900/20 border border-purple-800/30 rounded-lg">
              <div className="flex items-center gap-2 mb-3">
                <Sparkles className="h-4 w-4 text-purple-400" />
                <span className="text-sm font-medium text-purple-300">Post Call QA</span>
              </div>

              {(log.disposition_name || log.acw_resolution || (log.acw_quality_score != null)) && (
                <div className="flex flex-wrap gap-2 mb-3">
                  {log.disposition_name && (
                    <span
                      className="px-2 py-0.5 text-xs rounded-full border"
                      style={{
                        backgroundColor: `${log.disposition_color || '#6366f1'}15`,
                        borderColor: `${log.disposition_color || '#6366f1'}40`,
                        color: log.disposition_color || '#6366f1',
                      }}
                    >
                      {log.disposition_name}
                    </span>
                  )}
                  {log.acw_resolution && (
                    <span className="flex items-center gap-1 px-2 py-0.5 text-xs rounded-full border bg-blue-500/10 border-blue-500/30 text-blue-400">
                      <ClipboardCheck className="h-3 w-3" />
                      {log.acw_resolution}
                    </span>
                  )}
                  {log.acw_quality_score != null && (
                    <span
                      className={`flex items-center gap-1 px-2 py-0.5 text-xs rounded-full border font-medium ${
                        log.acw_quality_score >= 80
                          ? "bg-green-500/10 border-green-500/30 text-green-400"
                          : log.acw_quality_score >= 50
                          ? "bg-yellow-500/10 border-yellow-500/30 text-yellow-400"
                          : "bg-red-500/10 border-red-500/30 text-red-400"
                      }`}
                    >
                      <BarChart3 className="h-3 w-3" />
                      Score: {log.acw_quality_score}
                    </span>
                  )}
                </div>
              )}

              {log.ai_summary && (
                <p className="text-sm text-gray-300 whitespace-pre-wrap">{log.ai_summary}</p>
              )}
              {(log.tool_name || log.flow_name) && (
                <div className="mt-2 flex items-center gap-2 text-xs text-gray-500">
                  <Wrench className="h-3 w-3" />
                  <span>{log.tool_name || log.flow_name}</span>
                </div>
              )}
            </div>
          )}

          {transcript.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-gray-500">
              <Clock className="h-8 w-8 mb-2" />
              <p>No transcript available for this call</p>
            </div>
          ) : (
            <div className="space-y-4">
              {transcript.map((entry, index) => (
                <div
                  key={index}
                  className={`flex ${
                    entry.role === "assistant" ? "justify-start" : "justify-end"
                  }`}
                >
                  <div
                    className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                      entry.role === "assistant"
                        ? "bg-[#252525] text-white rounded-tl-sm"
                        : "bg-blue-600 text-white rounded-tr-sm"
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      {entry.role === "assistant" ? (
                        <>
                          <Bot className={`h-3 w-3 ${entry.interrupted ? 'text-red-400' : 'text-blue-400'}`} />
                          <span className={`text-xs font-medium ${entry.interrupted ? 'text-red-400' : 'text-blue-400'}`}>
                            {entry.interrupted ? '[Interrupted] Assistant' : 'Assistant'}
                          </span>
                        </>
                      ) : (
                        <>
                          <User className="h-3 w-3 text-blue-200" />
                          <span className="text-xs text-blue-200 font-medium">Caller</span>
                        </>
                      )}
                      {entry.timestamp && (
                        <span className="text-xs text-gray-500 ml-auto">
                          {entry.timestamp}
                        </span>
                      )}
                    </div>
                    <p className={`text-sm leading-relaxed ${entry.interrupted ? 'italic' : ''}`}>
                      {entry.content || entry.text}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between px-5 py-4 border-t border-gray-700 bg-[#141414]">
          <div>
            {hasTranscript && (
              <button
                onClick={runPostCallQA}
                disabled={running}
                className="flex items-center gap-2 px-4 py-2 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition disabled:opacity-50"
              >
                {running ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                Run Post Call QA
              </button>
            )}
          </div>
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-300 hover:text-white hover:bg-gray-700 rounded-lg transition"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
