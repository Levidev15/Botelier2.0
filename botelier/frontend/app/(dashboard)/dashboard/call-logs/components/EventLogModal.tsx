"use client";

import { useState, useEffect } from "react";
import { X, Activity, Loader2, Phone } from "lucide-react";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface CallEvent {
  id: string;
  call_log_id: string;
  event_type: string;
  event_source: string;
  severity: string;
  occurred_at: string | null;
  offset_ms: number | null;
  details: Record<string, unknown> | null;
}

interface CallLog {
  id: string;
  reference_id?: string | null;
  caller_number?: string | null;
  started_at?: string | null;
}

interface EventLogModalProps {
  log: CallLog;
  onClose: () => void;
}

function formatOffset(ms: number | null): string {
  if (ms === null || ms === undefined) return "+?";
  const totalSecs = Math.floor(ms / 1000);
  const mins = Math.floor(totalSecs / 60);
  const secs = totalSecs % 60;
  return `+${mins}:${secs.toString().padStart(2, "0")}`;
}

const EVENT_LABELS: Record<string, string> = {
  call_initiated: "Call Initiated",
  websocket_connected: "WebSocket Connected",
  call_answered: "Call Answered",
  greeting_started: "Greeting Started",
  greeting_completed: "Greeting Completed",
  user_first_speech: "User First Speech",
  transfer_initiated: "Transfer Initiated",
  transfer_connected: "Transfer Connected",
  transfer_ended: "Transfer Ended",
  call_ended: "Call Ended",
  idle_timeout: "Idle Timeout",
  pipeline_error: "Pipeline Error",
};

const SEVERITY_DOT: Record<string, string> = {
  info: "bg-blue-400",
  warning: "bg-yellow-400",
  error: "bg-red-500",
};

const SOURCE_BADGE: Record<string, string> = {
  twilio: "text-purple-400",
  pipecat: "text-cyan-400",
  app: "text-gray-400",
};

function formatDetails(details: Record<string, unknown> | null): string | null {
  if (!details || Object.keys(details).length === 0) return null;
  const parts: string[] = [];
  for (const [key, val] of Object.entries(details)) {
    if (val !== null && val !== undefined && val !== "") {
      parts.push(`${key}: ${val}`);
    }
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

export default function EventLogModal({ log, onClose }: EventLogModalProps) {
  const { authFetch } = useAuthToken();
  const [events, setEvents] = useState<CallEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchEvents() {
      setLoading(true);
      setError(null);
      try {
        const response = await authFetch(`/api/calls/${log.id}/events`);
        if (!response.ok) throw new Error("Failed to fetch events");
        const data = await response.json();
        setEvents(data);
      } catch (e) {
        setError("Could not load event timeline.");
      } finally {
        setLoading(false);
      }
    }
    fetchEvents();
  }, [log.id]);

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-[#111111] border border-gray-800 rounded-xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-indigo-900/30 rounded-lg">
              <Activity className="h-5 w-5 text-indigo-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-semibold text-white">Event Timeline</h3>
                {log.reference_id && (
                  <span className="font-mono text-[11px] text-gray-400 bg-gray-800 px-2 py-0.5 rounded border border-gray-700">
                    #{log.reference_id}
                  </span>
                )}
              </div>
              <p className="text-xs text-gray-400">
                {log.caller_number || "Unknown caller"}
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

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-12 gap-2 text-gray-400">
              <Loader2 className="h-5 w-5 animate-spin" />
              <span className="text-sm">Loading events...</span>
            </div>
          ) : error ? (
            <div className="flex items-center justify-center py-12 text-red-400 text-sm">
              {error}
            </div>
          ) : events.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <Phone className="h-10 w-10 text-gray-600" />
              <p className="text-gray-400 text-sm">No events recorded for this call.</p>
            </div>
          ) : (
            <div className="space-y-0">
              {events.map((event, idx) => {
                const isLast = idx === events.length - 1;
                const details = formatDetails(event.details);
                const label = EVENT_LABELS[event.event_type] || event.event_type;
                const dotColor = SEVERITY_DOT[event.severity] || "bg-gray-400";
                const sourceColor = SOURCE_BADGE[event.event_source] || "text-gray-400";

                return (
                  <div key={event.id} className="flex gap-4">
                    <div className="flex flex-col items-center">
                      <div className={`w-2.5 h-2.5 rounded-full mt-1 flex-shrink-0 ${dotColor}`} />
                      {!isLast && (
                        <div className="w-px flex-1 bg-gray-800 my-1" />
                      )}
                    </div>
                    <div className={`pb-4 ${isLast ? "" : ""}`}>
                      <div className="flex items-baseline gap-2 flex-wrap">
                        <span className="font-mono text-xs text-gray-500 w-12 flex-shrink-0">
                          {formatOffset(event.offset_ms)}
                        </span>
                        <span className="text-sm font-medium text-white">{label}</span>
                        <span className={`text-xs ${sourceColor}`}>{event.event_source}</span>
                        {event.severity !== "info" && (
                          <span className={`text-xs ${event.severity === "error" ? "text-red-400" : "text-yellow-400"}`}>
                            {event.severity}
                          </span>
                        )}
                      </div>
                      {details && (
                        <p className="text-xs text-gray-500 mt-0.5 ml-14 leading-relaxed">
                          {details}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-gray-800 bg-[#0d0d0d] rounded-b-xl">
          <p className="text-xs text-gray-600 text-center">
            {events.length} event{events.length !== 1 ? "s" : ""} recorded
          </p>
        </div>
      </div>
    </div>
  );
}
