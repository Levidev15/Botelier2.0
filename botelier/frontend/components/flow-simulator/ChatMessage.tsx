"use client";

interface ChatMessageProps {
  role: "user" | "assistant";
  content: string;
  metadata?: {
    function_called?: string;
    function_result?: Record<string, unknown>;
  };
}

export default function ChatMessage({ role, content, metadata }: ChatMessageProps) {
  const isUser = role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}>
      <div
        className={`max-w-[80%] rounded-lg px-4 py-2 ${
          isUser
            ? "bg-blue-600 text-white"
            : "bg-[#2a2a2a] text-gray-200 border border-[#3a3a3a]"
        }`}
      >
        <p className="text-sm whitespace-pre-wrap">{content}</p>
        
        {metadata?.function_called && (
          <div className="mt-2 pt-2 border-t border-gray-600">
            <div className="flex items-center gap-2 text-xs text-gray-400">
              <span className="bg-[#3a3a3a] px-2 py-0.5 rounded font-mono">
                {metadata.function_called}
              </span>
              <span className="text-green-400">executed</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
