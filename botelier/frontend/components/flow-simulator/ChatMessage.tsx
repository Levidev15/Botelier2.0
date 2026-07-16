"use client";

import { CheckCircle2, AlertTriangle } from "lucide-react";

export interface ChatMessageProps {
  role: "user" | "assistant" | "system";
  content: string;
  metadata?: {
    function_called?: string;
    function_result?: Record<string, unknown>;
    record_saved?: boolean;
  };
  compact?: boolean;
}

export default function ChatMessage({ role, content, metadata, compact }: ChatMessageProps) {
  if (role === "system") {
    const saved = metadata?.record_saved !== false;
    return (
      <div className={`flex justify-center ${compact ? "mb-2" : "mb-3"}`}>
        <div
          className={`flex items-start gap-2 max-w-[95%] rounded-lg ${compact ? "px-2.5 py-1.5" : "px-3 py-2"} ${
            saved
              ? "bg-green-900/25 border border-green-700/50 text-green-300"
              : "bg-amber-900/25 border border-amber-700/50 text-amber-300"
          }`}
        >
          {saved ? (
            <CheckCircle2 className={`${compact ? "w-3 h-3" : "w-3.5 h-3.5"} mt-0.5 shrink-0`} />
          ) : (
            <AlertTriangle className={`${compact ? "w-3 h-3" : "w-3.5 h-3.5"} mt-0.5 shrink-0`} />
          )}
          <p className={`${compact ? "text-xs" : "text-sm"} leading-snug`}>{content}</p>
        </div>
      </div>
    );
  }

  const isUser = role === "user";
  const functionResult = metadata?.function_result as Record<string, unknown> | undefined;
  const collectedData = functionResult?.collected as Record<string, unknown> | undefined;

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} ${compact ? "mb-2" : "mb-3"}`}>
      <div
        className={`max-w-[85%] rounded-lg ${compact ? "px-3 py-1.5" : "px-4 py-2"} ${
          isUser
            ? "bg-blue-600 text-white"
            : "bg-[#2a2a2a] text-gray-200 border border-[#3a3a3a]"
        }`}
      >
        <p className={`${compact ? "text-xs" : "text-sm"} whitespace-pre-wrap`}>{content}</p>
        
        {metadata?.function_called && (
          <div className={`${compact ? "mt-1 pt-1" : "mt-2 pt-2"} border-t border-gray-600/50`}>
            <div className="flex items-center gap-2 text-xs">
              <CheckCircle2 className={`${compact ? "w-3 h-3" : "w-3.5 h-3.5"} text-green-400`} />
              <span className="text-gray-400">
                {formatFunctionName(metadata.function_called)}
              </span>
            </div>
            {!compact && collectedData && Object.keys(collectedData).length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {Object.entries(collectedData).map(([key, value]) => (
                  <span
                    key={key}
                    className="bg-green-900/30 text-green-300 px-2 py-0.5 rounded text-xs"
                  >
                    {key}: {String(value)}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function formatFunctionName(name: string): string {
  if (name.startsWith("collect_")) {
    const varName = name.replace("collect_", "");
    return `Collected ${varName.replace(/_/g, " ")}`;
  }
  if (name.startsWith("end_call_")) {
    return "Call ended";
  }
  if (name.startsWith("transfer_")) {
    return "Call transferred";
  }
  return name.replace(/_/g, " ");
}
