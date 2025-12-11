"use client";

import { X, Bot, User, Clock, Phone, PhoneForwarded, Sparkles, Tag, Wrench } from "lucide-react";

interface TranscriptEntry {
  role: string;
  content?: string;
  text?: string;
  timestamp?: string;
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
}

interface TranscriptModalProps {
  log: CallLog;
  onClose: () => void;
}

function formatDuration(seconds: number): string {
  if (!seconds) return "0:00";
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

export default function TranscriptModal({ log, onClose }: TranscriptModalProps) {
  const transcript = log.transcript || [];

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
              <h3 className="text-lg font-semibold text-white">Call Transcript</h3>
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
          {log.ai_summary && (
            <div className="mb-6 p-4 bg-gradient-to-r from-purple-900/20 to-blue-900/20 border border-purple-800/30 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <Sparkles className="h-4 w-4 text-purple-400" />
                <span className="text-sm font-medium text-purple-300">AI Summary</span>
                {log.disposition_name && (
                  <span
                    className="ml-auto px-2 py-0.5 text-xs rounded-full border"
                    style={{
                      backgroundColor: `${log.disposition_color || '#6366f1'}15`,
                      borderColor: `${log.disposition_color || '#6366f1'}40`,
                      color: log.disposition_color || '#6366f1',
                    }}
                  >
                    {log.disposition_name}
                  </span>
                )}
              </div>
              <p className="text-sm text-gray-300 whitespace-pre-wrap">{log.ai_summary}</p>
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
                          <Bot className="h-3 w-3 text-blue-400" />
                          <span className="text-xs text-blue-400 font-medium">Assistant</span>
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
                    <p className="text-sm leading-relaxed">{entry.content || entry.text}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-gray-700 bg-[#141414]">
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
