"use client";

import { useEffect, useRef } from "react";
import { useSMSData } from "./hooks/useSMSData";
import { ConversationList } from "./components/ConversationList";
import { MessageThread } from "./components/MessageThread";
import { SMSSettingsPanel } from "./components/SMSSettingsPanel";
import { usePagePermission, AccessDeniedPage } from "@/components/ui/PermissionGate";
import { useAccountContext } from "@/lib/auth/useAccountContext";

export default function MessagesPage() {
  const { hasAccess, loading: permLoading } = usePagePermission("messages", "view");
  const { accountId } = useAccountContext();
  const data = useSMSData();

  // Deep link from a captured record's source: /dashboard/messages?conversation=<id>
  // opens that conversation once. fetchConversation no-ops until the account
  // context resolves, so we must not consume the one-shot guard until accountId
  // is truthy — otherwise the guard burns on the initial no-op call and the
  // conversation never opens.
  const deepLinkedRef = useRef(false);
  const { fetchConversation } = data;
  useEffect(() => {
    if (!accountId || deepLinkedRef.current || typeof window === "undefined") return;
    const convId = new URLSearchParams(window.location.search).get("conversation");
    if (!convId) return;
    deepLinkedRef.current = true;
    fetchConversation(convId);
  }, [accountId, fetchConversation]);

  if (permLoading) return null;
  if (!hasAccess) return <AccessDeniedPage />;

  return (
    <div className="flex h-full bg-[#0a0a0a]">

      {/* Left panel — conversation list */}
      <ConversationList
        conversations={data.conversations}
        loading={data.loading}
        search={data.search}
        setSearch={data.setSearch}
        statusFilter={data.statusFilter}
        setStatusFilter={data.setStatusFilter}
        assistantFilter={data.assistantFilter}
        setAssistantFilter={data.setAssistantFilter}
        needsAttentionFilter={data.needsAttentionFilter}
        setNeedsAttentionFilter={data.setNeedsAttentionFilter}
        assistants={data.assistants}
        selectedConvId={data.selectedConv?.id ?? null}
        onSelectConversation={data.fetchConversation}
        onOpenSettings={() => {
          data.setSettingsOpen(true);
          data.fetchTemplates();
          data.fetchNotifSettings();
        }}
      />

      {/* Right panel — message thread */}
      <div className="flex-1 flex flex-col min-w-0">
        <MessageThread
          selectedConv={data.selectedConv}
          loadingConv={data.loadingConv}
          generatingSummary={data.generatingSummary}
          handoffLoading={data.handoffLoading}
          replyText={data.replyText}
          setReplyText={data.setReplyText}
          sendingReply={data.sendingReply}
          attachedFiles={data.attachedFiles}
          setAttachedFiles={data.setAttachedFiles}
          uploading={data.uploading}
          showTemplates={data.showTemplates}
          setShowTemplates={data.setShowTemplates}
          groupedTemplates={data.groupedTemplates}
          messagesEndRef={data.messagesEndRef}
          fileInputRef={data.fileInputRef}
          currentUserId={data.user?.id}
          onGenerateSummary={data.handleGenerateSummary}
          onCloseConversation={data.handleCloseConversation}
          onTakeOver={data.handleTakeOver}
          onReturnToAI={data.handleReturnToAI}
          onSendReply={data.handleSendReply}
          onFileSelect={data.handleFileSelect}
          onInsertTemplate={data.handleInsertTemplate}
        />
      </div>

      {/* Settings slide-out panel */}
      {data.settingsOpen && (
        <SMSSettingsPanel
          settingsTab={data.settingsTab}
          setSettingsTab={data.setSettingsTab}
          onClose={() => data.setSettingsOpen(false)}
          templates={data.templates}
          editingTemplate={data.editingTemplate}
          setEditingTemplate={data.setEditingTemplate}
          newTemplate={data.newTemplate}
          setNewTemplate={data.setNewTemplate}
          showNewTemplate={data.showNewTemplate}
          setShowNewTemplate={data.setShowNewTemplate}
          onSaveTemplate={data.handleSaveTemplate}
          onUpdateTemplate={data.handleUpdateTemplate}
          onDeleteTemplate={data.handleDeleteTemplate}
          notifSettings={data.notifSettings}
          setNotifSettings={data.setNotifSettings}
          savingSettings={data.savingSettings}
          onSaveNotifSettings={data.handleSaveNotifSettings}
          onPreviewSound={data.previewNotifSound}
        />
      )}
    </div>
  );
}
