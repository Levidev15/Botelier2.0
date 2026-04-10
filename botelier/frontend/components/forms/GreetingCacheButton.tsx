"use client";

import { useState, useEffect, useCallback } from "react";
import { CheckCircle, AlertCircle, AlertTriangle, Loader2, Volume2 } from "lucide-react";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { useAccountContext } from "@/lib/auth/useAccountContext";

interface GreetingCacheButtonProps {
  assistantId: string;
  hasUnsavedChanges: boolean;
  greetingText?: string;
}

interface CacheStatus {
  cached: boolean;
  cached_at: string | null;
  text_matches_cache: boolean;
  outdated: boolean;
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
  greetingText,
}: GreetingCacheButtonProps) {
  const { authFetch } = useAuthToken();
  const { accountId } = useAccountContext();

  const [status, setStatus] = useState<CacheStatus | null>(null);
  const [isFetching, setIsFetching] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const buildTextParam = (text?: string) =>
    text ? `&greeting_text=${encodeURIComponent(text)}` : "";

  const fetchStatus = useCallback(async () => {
    if (!assistantId || !accountId) return;
    setIsFetching(true);
    setError(null);
    try {
      const res = await authFetch(
        `/api/assistants/${assistantId}/greeting-cache-status?account_id=${accountId}${buildTextParam(greetingText)}`
      );
      if (!res.ok) throw new Error("Failed to fetch status");
      const data: CacheStatus = await res.json();
      setStatus(data);
    } catch {
      setStatus(null);
    } finally {
      setIsFetching(false);
    }
  }, [assistantId, accountId, greetingText, authFetch]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const handleGenerate = async () => {
    if (!assistantId || !accountId || isGenerating) return;
    setIsGenerating(true);
    setError(null);
    try {
      const res = await authFetch(
        `/api/assistants/${assistantId}/cache-greeting?account_id=${accountId}${buildTextParam(greetingText)}`,
        { method: "POST" }
      );
      if (!res.ok) {
        const body: unknown = await res.json().catch(() => ({}));
        const detail =
          body !== null &&
          typeof body === "object" &&
          "detail" in body &&
          typeof (body as Record<string, unknown>).detail === "string"
            ? (body as Record<string, string>).detail
            : "Generation failed";
        throw new Error(detail);
      }
      const data: CacheStatus = await res.json();
      setStatus((prev) =>
        prev
          ? { ...prev, ...data }
          : { ...data, supported: true }
      );
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Failed to generate audio"
      );
    } finally {
      setIsGenerating(false);
    }
  };

  if (status && !status.supported) return null;

  const buttonDisabled = hasUnsavedChanges || isGenerating || isFetching;
  const buttonTitle = hasUnsavedChanges ? "Save changes first" : undefined;

  const isOutdated = status ? !status.cached && status.outdated : false;
  const isCached = status?.cached ?? false;

  return (
    <div className="mt-2 flex items-center gap-3 flex-wrap">
      <button
        onClick={handleGenerate}
        disabled={buttonDisabled}
        title={buttonTitle}
        className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
          ${buttonDisabled
            ? "bg-gray-800 text-gray-500 cursor-not-allowed"
            : isOutdated
            ? "bg-yellow-700 hover:bg-yellow-600 text-white cursor-pointer"
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
          : isCached
          ? "Regenerate Audio"
          : "Generate Audio"}
      </button>

      <span className="text-xs text-gray-500 flex items-center gap-1">
        {isFetching ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : isCached && status?.cached_at ? (
          <>
            <CheckCircle className="h-3.5 w-3.5 text-green-500 flex-shrink-0" />
            <span className="text-green-400">Cached {timeAgo(status.cached_at)}</span>
          </>
        ) : isOutdated && status?.cached_at ? (
          <>
            <AlertTriangle className="h-3.5 w-3.5 text-yellow-500 flex-shrink-0" />
            <span className="text-yellow-400">
              Outdated — regenerate to update
            </span>
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
