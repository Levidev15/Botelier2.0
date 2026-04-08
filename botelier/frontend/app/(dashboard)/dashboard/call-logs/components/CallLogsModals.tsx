"use client";

import TranscriptModal from "./TranscriptModal";
import EventLogModal from "./EventLogModal";
import EditCallLogModal from "./EditCallLogModal";
import DeleteCallLogDialog from "./DeleteCallLogDialog";
import type { CallLog } from "../types";

interface CallLogsModalsProps {
  showTranscript: boolean;
  selectedLog: CallLog | null;
  showEventLog: boolean;
  eventLogLog: CallLog | null;
  editLogTarget: CallLog | null;
  deleteLogTarget: CallLog | null;
  deletingId: string | null;
  accountId: string | null;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
  onTranscriptClose: () => void;
  onLogUpdated: (updates: Partial<CallLog>) => void;
  onViewEventLog: (log: CallLog) => void;
  onEventLogClose: () => void;
  onEditClose: () => void;
  onEditSaved: (updates: Partial<CallLog>) => void;
  onDeleteCancel: () => void;
  onDeleteConfirm: () => void;
}

export default function CallLogsModals({
  showTranscript,
  selectedLog,
  showEventLog,
  eventLogLog,
  editLogTarget,
  deleteLogTarget,
  deletingId,
  accountId,
  authFetch,
  onTranscriptClose,
  onLogUpdated,
  onViewEventLog,
  onEventLogClose,
  onEditClose,
  onEditSaved,
  onDeleteCancel,
  onDeleteConfirm,
}: CallLogsModalsProps) {
  return (
    <>
      {showTranscript && selectedLog && (
        <TranscriptModal
          log={selectedLog as any}
          onClose={onTranscriptClose}
          onLogUpdated={onLogUpdated as any}
          onViewEventLog={onViewEventLog as any}
        />
      )}

      {showEventLog && eventLogLog && (
        <EventLogModal log={eventLogLog as any} onClose={onEventLogClose} />
      )}

      {editLogTarget && accountId && (
        <EditCallLogModal
          log={editLogTarget}
          accountId={accountId}
          authFetch={authFetch}
          onClose={onEditClose}
          onSaved={onEditSaved as any}
        />
      )}

      {deleteLogTarget && (
        <DeleteCallLogDialog
          log={deleteLogTarget}
          deletingId={deletingId}
          onCancel={onDeleteCancel}
          onConfirm={onDeleteConfirm}
        />
      )}
    </>
  );
}
