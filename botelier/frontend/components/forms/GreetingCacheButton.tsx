"use client";

import { useState, useEffect, useCallback } from "react";
import { CheckCircle, AlertCircle, Loader2, Volume2 } from "lucide-react";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { useAccountContext } from "@/lib/auth/useAccountContext";

interface GreetingCacheButtonProps {
  assistantId: string;
  hasUnsavedChanges: boolean;
}

interface CacheStatus {
  cached: boolean;
  cached_at: string | null;
  supported: boolean;
}

function timeAgo(isoString: string): string {
  const diff = Date.now() - new Date(isoString).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min${mins === 1 ? "" : "s"} ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} hr${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

export default function GreetingCacheButton({
  assistantId,
  hasUnsavedChanges,
}: GreetingCacheButtonProps) {
  const { authFetch } = useAuthToken();
  const { accountId } = useAccountContext();

  const [status, setStatus] = useState<CacheStatus | null>(null);
  const [isFetching, setIsFetching] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    if (!assistantId || !accountId) return;
    setIsFetching(true);
    setError(null);
    try {
      const res = await authFetch(
        `/api/assistants/${assistantId}/greeting-cache-status?account_id=${accountId}`
      );
      if (!res.ok) throw new Error("Failed to fetch status");
      const data = await res.json();
      setStatus(data);
    } catch {
      setStatus(null);
    } finally {
      setIsFetching(false);
    }
  }, [assistantId, accountId, authFetch]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const handleGenerate = async () => {
    if (!assistantId || !accountId || isGenerating) return;
    setIsGenerating(true);
    setError(null);
    try {
      const res = await authFetch(
        `/api/assistants/${assistantId}/cache-greeting?account_id=${accountId}`,
        { method: "POST" }
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Generation failed");
      }
      const data = await res.json();
      setStatus((prev) => ({
        ...prev!,
        cached: data.cached,
        cached_at: data.cached_at,
        supported: prev?.supported ?? true,
      }));
    } catch (err: any) {
      setError(err.message || "Failed to generate audio");
    } finally {
      setIsGenerating(false);
    }
  };

  if (status && !status.supported) return null;

  const buttonDisabled = hasUnsavedChanges || isGenerating || isFetching;
  const buttonTitle = hasUnsavedChanges ? "Save changes first" : undefined;

  return (
    <div className="mt-2 flex items-center gap-3 flex-wrap">
      <button
        onClick={handleGenerate}
        disabled={buttonDisabled}
        title={buttonTitle}
        className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
          ${buttonDisabled
            ? "bg-gray-800 text-gray-500 cursor-not-allowed"
            : "bg-blue-700 hover:bg-blue-600 text-white cursor-pointer"
          }`}
      >
        {isGenerating ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Volume2 className="h-3.5 w-3.5" />
        )}
        {isGenerating
          ? "Generating…"
          : status?.cached
          ? "Regenerate Audio"
          : "Generate Audio"}
      </button>

      <span className="text-xs text-gray-500 flex items-center gap-1">
        {isFetching ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : status?.cached && status.cached_at ? (
          <>
            <CheckCircle className="h-3.5 w-3.5 text-green-500 flex-shrink-0" />
            <span className="text-green-400">Cached {timeAgo(status.cached_at)}</span>
          </>
        ) : (
          <>
            <AlertCircle className="h-3.5 w-3.5 text-gray-500 flex-shrink-0" />
            <span>Not generated yet</span>
          </>
        )}
      </span>

      {error && (
        <span className="text-xs text-red-400 w-full">{error}</span>
      )}
    </div>
  );
}
