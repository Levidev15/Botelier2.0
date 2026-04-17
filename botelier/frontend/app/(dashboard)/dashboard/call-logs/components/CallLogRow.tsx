"use client";

import { useState, useEffect, useRef } from "react";
import {
  ChevronDown, ChevronRight, Play, Clock, User, Bot, Wrench,
  PhoneForwarded, FileText, MoreHorizontal, Pencil, Loader2,
  MessageSquareText, Trash2, Sparkles, X,
} from "lucide-react";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { notify } from "@/lib/notifications";
import type { CallLog } from "../types";
import {
  formatDuration, formatPhoneNumber, getStatusIcon, getStatusBadge, getLegTypeLabel,
} from "../utils";

interface CallLogRowProps {
  log: CallLog;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onViewTranscript: () => void;
  onViewEventLog: () => void;
  onGenerateSummary: () => void;
  isGeneratingSummary: boolean;
  onEditLog: () => void;
  onDeleteLog: () => void;
  formatDateTime: (date: string | null) => string;
  canViewTranscripts: boolean;
  canEditLogs: boolean;
  canDeleteLogs: boolean;
  canPlayRecordings: boolean;
}

export default function CallLogRow({
  log,
  isExpanded,
  onToggleExpand,
  onViewTranscript,
  onViewEventLog,
  onGenerateSummary,
  isGeneratingSummary,
  onEditLog,
  onDeleteLog,
  formatDateTime,
  canViewTranscripts,
  canEditLogs,
  canDeleteLogs,
  canPlayRecordings,
}: CallLogRowProps) {
  const hasLegs = log.legs && log.legs.length > 1;
  const hasTranscript = log.transcript && log.transcript.length > 0;
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [showPlayer, setShowPlayer] = useState(false);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [loadingAudio, setLoadingAudio] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const { authFetch } = useAuthToken();

  useEffect(() => {
    return () => {
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [blobUrl]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setIsMenuOpen(false);
      }
    }
    if (isMenuOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [isMenuOpen]);

  const hasRecording = !!log.recording_url && canPlayRecordings;

  const togglePlayer = async () => {
    if (showPlayer) {
      setShowPlayer(false);
      return;
    }
    if (!blobUrl && !loadingAudio) {
      setLoadingAudio(true);
      try {
        const res = await authFetch(`/api/calls/${log.id}/recording`);
        if (!res.ok) throw new Error("Failed to load recording");
        const blob = await res.blob();
        setBlobUrl(URL.createObjectURL(blob));
      } catch {
        notify.error("Failed to load recording");
        setLoadingAudio(false);
        return;
      }
      setLoadingAudio(false);
    }
    setShowPlayer(true);
  };

  const hasMenuItems =
    canEditLogs ||
    (canDeleteLogs && hasTranscript && !log.ai_summary) ||
    (canViewTranscripts && !!log.ai_summary) ||
    canDeleteLogs;

  return (
    <>
      <tr className="hover:bg-[#1a1a1a] transition">
        <td className="px-4 py-3">
          {hasLegs ? (
            <button
              onClick={onToggleExpand}
              className="p-1 text-gray-400 hover:text-foreground hover:bg-gray-700 rounded transition"
            >
              {isExpanded ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
            </button>
          ) : (
            <div className="w-6" />
          )}
        </td>
        <td className="px-4 py-3 whitespace-nowrap">
          {log.reference_id ? (
            <button
              onClick={onViewEventLog}
              className="font-mono text-xs bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200 px-1.5 py-0.5 rounded transition cursor-pointer"
              title="View event timeline"
            >
              #{log.reference_id}
            </button>
          ) : (
            <span className="text-gray-700 text-xs">—</span>
          )}
        </td>
        <td className="px-4 py-3 whitespace-nowrap">
          <div className="flex items-center gap-2">
            {getStatusIcon(log.status)}
            <span className="text-sm font-medium text-foreground">
              {formatDateTime(log.started_at)}
            </span>
          </div>
        </td>
        <td className="px-4 py-3 whitespace-nowrap">
          {hasRecording ? (
            <button
              onClick={togglePlayer}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-all ${
                showPlayer
                  ? "bg-blue-500/20 border-blue-500/50 text-blue-300"
                  : "bg-blue-500/10 border-blue-500/30 text-blue-400 hover:bg-blue-500/20 hover:border-blue-500/50 hover:text-blue-300"
              }`}
              title={showPlayer ? "Hide recording" : "Play recording"}
            >
              {loadingAudio ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Play className="h-3 w-3 fill-current" />
              )}
              {formatDuration(log.duration_seconds)}
            </button>
          ) : (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-gray-800 border border-gray-700 text-gray-400">
              <Clock className="h-3 w-3" />
              {formatDuration(log.duration_seconds)}
            </span>
          )}
        </td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            <User className="h-4 w-4 text-gray-500" />
            <span className="text-sm text-gray-300">
              {formatPhoneNumber(log.caller_number)}
            </span>
          </div>
        </td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            <Bot className="h-4 w-4 text-gray-500" />
            <span className="text-sm text-gray-300">
              {log.assistant_name || "-"}
            </span>
          </div>
        </td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            {(log.tool_name || log.flow_name) ? (
              <>
                <Wrench className="h-4 w-4 text-gray-500" />
                <span className="text-sm text-gray-300">
                  {log.tool_name || log.flow_name}
                </span>
              </>
            ) : (
              <span className="text-sm text-gray-500">-</span>
            )}
          </div>
        </td>
        <td className="px-4 py-3">
          {log.acw_skip_reason === "no_caller_audio" || log.caller_spoke === false ? (
            <span
              className="px-2 py-0.5 text-xs rounded-full border bg-yellow-500/10 border-yellow-500/40 text-yellow-300"
              title="The AI greeted the caller but no audio was received from the caller. Counted as Unresolved, not AI Handled."
            >
              No Caller Audio
            </span>
          ) : log.disposition_name ? (
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
          ) : (
            <span className="text-sm text-gray-500">-</span>
          )}
        </td>
        <td className="px-4 py-3">
          {log.acw_resolution ? (
            <span className="px-2 py-0.5 text-xs rounded-full border bg-blue-500/10 border-blue-500/30 text-blue-400">
              {log.acw_resolution}
            </span>
          ) : (
            <span className="text-sm text-gray-500">-</span>
          )}
        </td>
        <td className="px-4 py-3">
          {log.acw_quality_score != null ? (
            <span
              className={`px-2 py-0.5 text-xs rounded-full border font-medium ${
                log.acw_quality_score >= 80
                  ? "bg-green-500/10 border-green-500/30 text-green-400"
                  : log.acw_quality_score >= 50
                  ? "bg-yellow-500/10 border-yellow-500/30 text-yellow-400"
                  : "bg-red-500/10 border-red-500/30 text-red-400"
              }`}
            >
              {log.acw_quality_score}
            </span>
          ) : (
            <span className="px-2 py-0.5 text-xs rounded-full border bg-gray-500/10 border-gray-500/30 text-gray-500">—</span>
          )}
        </td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={`px-2 py-0.5 text-xs rounded-full border ${getStatusBadge(log.status || 'unknown')}`}
            >
              {log.status ? (log.status.charAt(0).toUpperCase() + log.status.slice(1).replace("_", " ")) : "Unknown"}
            </span>
            {log.has_transfer && (
              <span className="flex items-center gap-1 text-xs text-purple-400">
                <PhoneForwarded className="h-3 w-3" />
              </span>
            )}
            {log.ended_early && log.status !== "ended_early" && (
              <span className="px-1.5 py-0.5 text-xs rounded border bg-orange-500/10 border-orange-500/30 text-orange-400 whitespace-nowrap">
                Early End
              </span>
            )}
          </div>
        </td>
        <td className="px-4 py-3 text-right">
          <div className="flex items-center justify-end gap-1">
            {canViewTranscripts && hasTranscript && (
              <button
                onClick={onViewTranscript}
                className="p-2 text-gray-400 hover:text-blue-400 hover:bg-gray-700 rounded-lg transition"
                title="View transcript"
              >
                <FileText className="h-4 w-4" />
              </button>
            )}
            {hasMenuItems && (
              <div ref={menuRef} className="relative">
                <button
                  onClick={() => setIsMenuOpen((o) => !o)}
                  className="p-2 text-gray-400 hover:text-foreground hover:bg-gray-700 rounded-lg transition"
                  title="More actions"
                >
                  <MoreHorizontal className="h-4 w-4" />
                </button>
                {isMenuOpen && (
                  <div className="absolute right-0 mt-1 w-48 bg-[#1c1c1c] border border-gray-700 rounded-lg shadow-xl z-50 overflow-hidden">
                    {canEditLogs && (
                      <button
                        onClick={() => { setIsMenuOpen(false); onEditLog(); }}
                        className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-gray-300 hover:bg-[#252525] hover:text-foreground text-left transition-colors"
                      >
                        <Pencil className="h-4 w-4 text-gray-500" />
                        Edit Call Log
                      </button>
                    )}
                    {canViewTranscripts && log.ai_summary && (
                      <button
                        onClick={() => { setIsMenuOpen(false); onViewTranscript(); }}
                        className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-gray-300 hover:bg-[#252525] hover:text-foreground text-left transition-colors"
                      >
                        <MessageSquareText className="h-4 w-4 text-gray-500" />
                        View Summary
                      </button>
                    )}
                    {canDeleteLogs && hasTranscript && !log.ai_summary && (
                      <button
                        onClick={() => { setIsMenuOpen(false); onGenerateSummary(); }}
                        disabled={isGeneratingSummary}
                        className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-gray-300 hover:bg-[#252525] hover:text-foreground text-left transition-colors disabled:opacity-50"
                      >
                        {isGeneratingSummary ? (
                          <Loader2 className="h-4 w-4 text-gray-500 animate-spin" />
                        ) : (
                          <Sparkles className="h-4 w-4 text-gray-500" />
                        )}
                        Generate Summary
                      </button>
                    )}
                    {canDeleteLogs && (canEditLogs || (hasTranscript && !log.ai_summary) || (canViewTranscripts && !!log.ai_summary)) && (
                      <div className="border-t border-gray-700 my-0.5" />
                    )}
                    {canDeleteLogs && (
                      <button
                        onClick={() => { setIsMenuOpen(false); onDeleteLog(); }}
                        className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-red-400 hover:bg-red-500/10 text-left transition-colors"
                      >
                        <Trash2 className="h-4 w-4" />
                        Delete Call Log
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </td>
      </tr>
      {showPlayer && hasRecording && (
        <tr>
          <td colSpan={12} className="bg-[#0f0f0f] px-8 py-3 border-t border-gray-800">
            <div className="flex items-center gap-3">
              <Play className="h-4 w-4 text-gray-400 flex-shrink-0" />
              {blobUrl ? (
                <audio
                  controls
                  autoPlay
                  className="w-full max-w-lg h-8"
                  src={blobUrl}
                  style={{ colorScheme: "dark" }}
                />
              ) : (
                <div className="flex items-center gap-2 text-sm text-gray-500">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading…
                </div>
              )}
              <button
                onClick={() => setShowPlayer(false)}
                className="p-1 text-gray-500 hover:text-gray-300 transition flex-shrink-0"
                title="Close player"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </td>
        </tr>
      )}
      {isExpanded && hasLegs && (
        <tr>
          <td colSpan={12} className="bg-[#0f0f0f] px-4 py-3">
            <div className="ml-10">
              <div className="text-xs text-gray-500 mb-2 font-medium uppercase tracking-wider">
                Call Segments
              </div>
              <div className="space-y-2">
                {log.legs.map((leg) => (
                  <div
                    key={leg.id}
                    className="flex items-center gap-4 text-sm bg-[#1a1a1a] rounded-lg px-4 py-2 border border-gray-800"
                  >
                    <div className="w-8 text-gray-500 font-mono">
                      #{leg.leg_number}
                    </div>
                    <div className="min-w-[160px]">
                      <span className={`px-2 py-0.5 text-xs rounded ${
                        leg.leg_type === "ai_conversation"
                          ? "bg-blue-500/10 text-blue-400"
                          : leg.leg_type === "transfer_cold"
                          ? "bg-amber-500/10 text-amber-400"
                          : "bg-purple-500/10 text-purple-400"
                      }`}>
                        {getLegTypeLabel(leg.leg_type)}
                      </span>
                    </div>
                    <div className="flex-1 text-gray-400">
                      {leg.participant_name || leg.participant || "-"}
                    </div>
                    <div className="text-gray-500 flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {leg.leg_type === "transfer_cold" && (leg.duration_seconds === null || leg.duration_seconds === 0)
                        ? <span className="text-amber-500/70 italic">Handed off</span>
                        : formatDuration(leg.duration_seconds ?? 0)
                      }
                    </div>
                    <div>
                      <span className={`px-2 py-0.5 text-xs rounded-full border ${getStatusBadge(leg.status)}`}>
                        {leg.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
