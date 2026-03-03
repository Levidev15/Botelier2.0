"use client";

import { useRef } from "react";
import {
  MessageSquare, Paperclip, Bookmark, Send, Sparkles, Eye, X, FileText,
  Image as ImageIcon,
} from "lucide-react";
import {
  ConversationDetail,
  SMSTemplate,
  AttachedFile,
  statusColor,
  isPresenceActive,
  isImageUrl,
  formatFullTime,
} from "../hooks/useSMSData";

interface Props {
  selectedConv: ConversationDetail | null;
  loadingConv: boolean;
  generatingSummary: boolean;
  handoffLoading: boolean;
  replyText: string;
  setReplyText: (v: string) => void;
  sendingReply: boolean;
  attachedFiles: AttachedFile[];
  setAttachedFiles: (fn: (prev: AttachedFile[]) => AttachedFile[]) => void;
  uploading: boolean;
  showTemplates: boolean;
  setShowTemplates: (v: boolean) => void;
  groupedTemplates: Record<string, SMSTemplate[]>;
  messagesEndRef: React.RefObject<HTMLDivElement>;
  fileInputRef: React.RefObject<HTMLInputElement>;
  currentUserId?: string | null;
  onGenerateSummary: () => void;
  onCloseConversation: () => void;
  onTakeOver: () => void;
  onReturnToAI: () => void;
  onSendReply: () => void;
  onFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onInsertTemplate: (t: SMSTemplate) => void;
}

export function MessageThread({
  selectedConv,
  loadingConv,
  generatingSummary,
  handoffLoading,
  replyText,
  setReplyText,
  sendingReply,
  attachedFiles,
  setAttachedFiles,
  uploading,
  showTemplates,
  setShowTemplates,
  groupedTemplates,
  messagesEndRef,
  fileInputRef,
  currentUserId,
  onGenerateSummary,
  onCloseConversation,
  onTakeOver,
  onReturnToAI,
  onSendReply,
  onFileSelect,
  onInsertTemplate,
}: Props) {
  if (!selectedConv) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-gray-400">
        <MessageSquare className="h-12 w-12 text-gray-600 mb-4" />
        <p className="text-lg font-medium">Select a conversation</p>
        <p className="text-sm text-gray-500 mt-1">Choose one from the list to view messages</p>
      </div>
    );
  }

  if (loadingConv) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
        Loading messages...
      </div>
    );
  }

  return (
    <>
      {/* Thread header */}
      <div className="p-4 border-b border-gray-800 bg-[#141414] flex-shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-white">{selectedConv.customer_number}</h2>
              <span className={`text-xs px-2 py-0.5 rounded ${statusColor(selectedConv.status)}`}>
                {selectedConv.status}
              </span>
            </div>
            <p className="text-xs text-gray-500 mt-0.5">
              {selectedConv.botelier_number} · {selectedConv.message_count} messages
              {selectedConv.tools_used && ` · Tools: ${selectedConv.tools_used}`}
            </p>
            {selectedConv.active_agent_name &&
              isPresenceActive(selectedConv.agent_active_at) &&
              selectedConv.active_agent_id !== currentUserId && (
              <div className="flex items-center gap-1.5 mt-1">
                <Eye className="h-3 w-3 text-amber-400" />
                <span className="text-[11px] text-amber-400">
                  {selectedConv.active_agent_name} is viewing
                </span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            {selectedConv.status === "active" && (
              selectedConv.handler_mode === "human" ? (
                <button
                  onClick={onReturnToAI}
                  disabled={handoffLoading}
                  className="flex items-center gap-1.5 px-3 py-1.5 border border-indigo-500/50 hover:bg-indigo-600/10 text-indigo-400 rounded-lg text-xs transition-colors disabled:opacity-50"
                >
                  {handoffLoading ? "..." : "Return to AI"}
                </button>
              ) : (
                <button
                  onClick={onTakeOver}
                  disabled={handoffLoading}
                  className="flex items-center gap-1.5 px-3 py-1.5 border border-amber-500/50 hover:bg-amber-600/10 text-amber-400 rounded-lg text-xs transition-colors disabled:opacity-50"
                >
                  {handoffLoading ? "..." : "Take Over"}
                </button>
              )
            )}
            <button
              onClick={onGenerateSummary}
              disabled={generatingSummary}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600/10 hover:bg-indigo-600/20 text-indigo-400 rounded-lg text-xs transition-colors disabled:opacity-50"
            >
              <Sparkles className="h-3.5 w-3.5" />
              {generatingSummary ? "Generating..." : "AI Summary"}
            </button>
            {selectedConv.status === "active" && (
              <button
                onClick={onCloseConversation}
                className="px-3 py-1.5 bg-gray-700/50 hover:bg-gray-700 text-gray-300 rounded-lg text-xs transition-colors"
              >
                Close
              </button>
            )}
          </div>
        </div>

        {selectedConv.ai_summary && (
          <div className="mt-3 p-3 bg-indigo-600/5 border border-indigo-600/20 rounded-lg">
            <div className="flex items-center gap-1.5 mb-1">
              <Sparkles className="h-3 w-3 text-indigo-400" />
              <span className="text-xs font-medium text-indigo-400">AI Summary</span>
            </div>
            <p className="text-xs text-gray-300 whitespace-pre-wrap">{selectedConv.ai_summary}</p>
          </div>
        )}
      </div>

      {/* Handoff banner */}
      {selectedConv.needs_attention && selectedConv.status === "active" && (
        <div className="mx-4 mt-3 mb-1 flex items-center gap-2.5 px-3 py-2.5 bg-amber-500/10 border border-amber-500/30 rounded-lg">
          <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse flex-shrink-0" />
          <p className="text-xs text-amber-300 flex-1">
            <span className="font-semibold">AI paused.</span> This conversation is waiting for a human agent. Replies from the AI are disabled until you return it to AI mode.
          </p>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {selectedConv.messages.map((msg) => (
          <div key={msg.id}>
            {msg.session_boundary && (
              <div className="flex items-center gap-3 my-4">
                <div className="flex-1 border-t border-dashed border-gray-700" />
                <span className="text-[10px] text-gray-500 whitespace-nowrap px-2">
                  New session — {formatFullTime(msg.created_at)}
                </span>
                <div className="flex-1 border-t border-dashed border-gray-700" />
              </div>
            )}
            <div className={`flex ${msg.sender === "customer" ? "justify-start" : "justify-end"}`}>
              <div
                className={`max-w-[70%] rounded-2xl px-4 py-2.5 ${
                  msg.sender === "customer"
                    ? "bg-[#1a1a1a] border border-gray-700 text-white rounded-bl-sm"
                    : msg.sender === "agent"
                    ? "bg-emerald-600 text-white rounded-br-sm"
                    : "bg-indigo-600 text-white rounded-br-sm"
                }`}
              >
                {msg.content && (
                  <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                )}
                {msg.media_urls && msg.media_urls.length > 0 && (
                  <div className="mt-2 space-y-2">
                    {msg.media_urls.map((url, i) =>
                      isImageUrl(url) ? (
                        <a key={i} href={url} target="_blank" rel="noopener noreferrer">
                          <img
                            src={url}
                            alt="Attachment"
                            className="max-w-full max-h-48 rounded-lg border border-white/10"
                          />
                        </a>
                      ) : (
                        <a
                          key={i}
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-2 px-3 py-2 bg-white/10 rounded-lg hover:bg-white/20 transition-colors"
                        >
                          <FileText className="h-4 w-4 flex-shrink-0" />
                          <span className="text-xs underline">Download attachment</span>
                        </a>
                      )
                    )}
                  </div>
                )}
                <div className={`flex items-center gap-1.5 mt-1 ${
                  msg.sender === "customer"
                    ? "text-gray-500"
                    : msg.sender === "agent"
                    ? "text-emerald-200"
                    : "text-indigo-200"
                }`}>
                  <span className="text-[10px]">{formatFullTime(msg.created_at)}</span>
                  {msg.sender === "agent" && (
                    <span className="text-[10px] px-1 bg-white/10 rounded">Agent</span>
                  )}
                  {msg.tool_calls && msg.tool_calls.length > 0 && (
                    <span className="text-[10px] px-1 bg-white/10 rounded">
                      {msg.tool_calls.map((tc: any) => tc.name).join(", ")}
                    </span>
                  )}
                  {msg.status === "failed" && (
                    <span className="text-[10px] text-red-400">Failed</span>
                  )}
                </div>
              </div>
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Reply area */}
      {selectedConv.status === "active" && (
        <div className="p-3 border-t border-gray-800 bg-[#141414] flex-shrink-0">
          {attachedFiles.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2 px-1">
              {attachedFiles.map((f, i) => (
                <div key={i} className="flex items-center gap-1.5 px-2 py-1 bg-[#1a1a1a] border border-gray-700 rounded-lg text-xs text-gray-300">
                  {f.content_type.startsWith("image/")
                    ? <ImageIcon className="h-3 w-3 text-indigo-400" />
                    : <FileText className="h-3 w-3 text-indigo-400" />
                  }
                  <span className="max-w-[120px] truncate">{f.filename}</span>
                  <button
                    onClick={() => setAttachedFiles(prev => prev.filter((_, idx) => idx !== i))}
                    className="text-gray-500 hover:text-red-400"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="flex items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/gif,image/webp,application/pdf"
              multiple
              onChange={onFileSelect}
              className="hidden"
            />

            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading || attachedFiles.length >= 10}
              className="p-2.5 text-gray-400 hover:text-white hover:bg-[#1a1a1a] rounded-xl transition-colors disabled:opacity-50"
              title="Attach file"
            >
              <Paperclip className="h-4 w-4" />
            </button>

            <div className="relative">
              <button
                onClick={() => setShowTemplates(!showTemplates)}
                className="p-2.5 text-gray-400 hover:text-white hover:bg-[#1a1a1a] rounded-xl transition-colors"
                title="Canned responses"
              >
                <Bookmark className="h-4 w-4" />
              </button>
              {showTemplates && (
                <div className="absolute bottom-12 left-0 w-72 bg-[#1a1a1a] border border-gray-700 rounded-xl shadow-xl z-50 max-h-80 overflow-y-auto">
                  <div className="p-2 border-b border-gray-700">
                    <span className="text-xs font-medium text-gray-400">Canned Responses</span>
                  </div>
                  {Object.keys(groupedTemplates).length === 0 ? (
                    <div className="p-4 text-center text-xs text-gray-500">
                      No templates yet. Create one in Settings.
                    </div>
                  ) : (
                    Object.entries(groupedTemplates).map(([cat, tmpls]) => (
                      <div key={cat}>
                        <div className="px-3 py-1.5 text-[10px] font-medium text-gray-500 uppercase tracking-wider bg-[#141414]">
                          {cat}
                        </div>
                        {tmpls.filter(t => t.is_active).map(t => (
                          <button
                            key={t.id}
                            onClick={() => onInsertTemplate(t)}
                            className="w-full text-left px-3 py-2 hover:bg-[#252525] transition-colors"
                          >
                            <span className="text-xs font-medium text-white block">{t.name}</span>
                            <span className="text-[10px] text-gray-500 truncate block mt-0.5">{t.content}</span>
                          </button>
                        ))}
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>

            <input
              type="text"
              value={replyText}
              onChange={(e) => setReplyText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  onSendReply();
                }
              }}
              placeholder="Type a reply..."
              disabled={sendingReply}
              className="flex-1 px-4 py-2.5 bg-[#1a1a1a] border border-gray-700 rounded-xl text-sm text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500 disabled:opacity-50"
            />

            <button
              onClick={onSendReply}
              disabled={sendingReply || (!replyText.trim() && attachedFiles.length === 0)}
              className="p-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded-xl transition-colors"
            >
              <Send className="h-4 w-4" />
            </button>
          </div>

          <p className="text-[10px] text-gray-600 mt-1.5 ml-1">
            {uploading ? "Uploading..." : "Replies are sent as your team, not the AI"}
          </p>
        </div>
      )}
    </>
  );
}
