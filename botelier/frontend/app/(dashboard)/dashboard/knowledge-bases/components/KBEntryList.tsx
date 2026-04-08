"use client";

import { BookOpen, Plus, Pencil, Trash2, Tag, AlertCircle } from "lucide-react";
import type { Entry, ParsedRow, ImportResult } from "../types";
import { formatDate } from "../types";
import EntryModal from "./EntryModal";
import ReviewModal from "./ReviewModal";
import ResultModal from "./ResultModal";

interface KBEntryListProps {
  filteredEntries: Entry[];
  view: "grid" | "table";
  canCreate: boolean;
  canEdit: boolean;
  canDelete: boolean;
  knowledgeBaseId: string;
  onAddEntry: () => void;
  onEditEntry: (entry: Entry) => void;
  onDeleteEntry: (entry: Entry) => void;
  showAddEntryModal: boolean;
  editingEntry: Entry | null;
  onEntryClose: () => void;
  onEntrySave: (entry: Entry) => void;
  reviewRows: ParsedRow[] | null;
  replaceDuplicates: boolean;
  onToggleReplace: () => void;
  onCancelReview: () => void;
  onImportConfirm: () => void;
  importResult: ImportResult | null;
  onDismissResult: () => void;
}

export default function KBEntryList({
  filteredEntries,
  view,
  canCreate,
  canEdit,
  canDelete,
  knowledgeBaseId,
  onAddEntry,
  onEditEntry,
  onDeleteEntry,
  showAddEntryModal,
  editingEntry,
  onEntryClose,
  onEntrySave,
  reviewRows,
  replaceDuplicates,
  onToggleReplace,
  onCancelReview,
  onImportConfirm,
  importResult,
  onDismissResult,
}: KBEntryListProps) {
  return (
    <>
      {filteredEntries.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <BookOpen className="w-12 h-12 text-white/20 mb-4" />
          <h3 className="text-lg font-medium text-white/80 mb-2">No entries yet</h3>
          <p className="text-white/40 text-sm mb-4">Add Q&A entries to build your knowledge base</p>
          {canCreate && (
            <button onClick={onAddEntry} className="flex items-center gap-2 px-4 py-2 bg-[#3B82F6] hover:bg-[#3B82F6]/80 text-black font-medium rounded-lg transition-colors">
              <Plus className="w-4 h-4" />
              Add First Entry
            </button>
          )}
        </div>
      ) : view === "grid" ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredEntries.map((entry) => (
            <div key={entry.id} className="bg-[#1A1A1A] border border-white/10 rounded-xl p-4 hover:border-white/20 transition-colors group">
              <div className="flex items-start justify-between gap-2 mb-2">
                <h3 className="text-white font-medium line-clamp-2">{entry.question}</h3>
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  {canEdit && (
                    <button onClick={() => onEditEntry(entry)} className="p-1.5 hover:bg-white/5 rounded">
                      <Pencil className="w-3.5 h-3.5 text-white/60" />
                    </button>
                  )}
                  {canDelete && (
                    <button onClick={() => onDeleteEntry(entry)} className="p-1.5 hover:bg-red-500/20 rounded">
                      <Trash2 className="w-3.5 h-3.5 text-red-400" />
                    </button>
                  )}
                </div>
              </div>
              <p className="text-white/60 text-sm line-clamp-3 mb-3">{entry.answer}</p>
              <div className="flex items-center justify-between">
                {entry.category && (
                  <span className="inline-flex items-center gap-1 px-2 py-1 bg-[#3B82F6]/10 text-[#3B82F6] text-xs rounded-full">
                    <Tag className="w-3 h-3" />
                    {entry.category}
                  </span>
                )}
                <span className="text-white/40 text-xs ml-auto">{formatDate(entry.updated_at)}</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="bg-[#1A1A1A] border border-white/10 rounded-xl overflow-hidden">
          <table className="w-full">
            <thead className="bg-[#2A2A2A]">
              <tr>
                <th className="text-left text-xs text-white/60 font-medium px-4 py-3">Question</th>
                <th className="text-left text-xs text-white/60 font-medium px-4 py-3">Answer</th>
                <th className="text-left text-xs text-white/60 font-medium px-4 py-3 w-24">Category</th>
                <th className="text-left text-xs text-white/60 font-medium px-4 py-3 w-28">Expiration</th>
                <th className="text-left text-xs text-white/60 font-medium px-4 py-3 w-24">Updated</th>
                <th className="w-20"></th>
              </tr>
            </thead>
            <tbody>
              {filteredEntries.map((entry) => (
                <tr key={entry.id} className="border-t border-white/5 hover:bg-white/[0.02]">
                  <td className="px-4 py-3 text-white text-sm">{entry.question}</td>
                  <td className="px-4 py-3 text-white/60 text-sm line-clamp-2">{entry.answer}</td>
                  <td className="px-4 py-3">
                    {entry.category && (
                      <span className="inline-flex items-center gap-1 px-2 py-1 bg-[#3B82F6]/10 text-[#3B82F6] text-xs rounded-full">
                        {entry.category}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {entry.expiration_date ? (
                      <span className={`text-xs ${entry.is_expired ? 'text-red-400' : 'text-white/60'}`}>
                        {new Date(entry.expiration_date).toLocaleDateString()}
                        {entry.is_expired && <AlertCircle className="w-3 h-3 inline ml-1" />}
                      </span>
                    ) : (
                      <span className="text-white/30 text-xs">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-white/40 text-xs">{formatDate(entry.updated_at)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1">
                      {canEdit && (
                        <button onClick={() => onEditEntry(entry)} className="p-1.5 hover:bg-white/5 rounded">
                          <Pencil className="w-3.5 h-3.5 text-white/60" />
                        </button>
                      )}
                      {canDelete && (
                        <button onClick={() => onDeleteEntry(entry)} className="p-1.5 hover:bg-red-500/20 rounded">
                          <Trash2 className="w-3.5 h-3.5 text-red-400" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showAddEntryModal && (
        <EntryModal
          entry={editingEntry}
          knowledgeBaseId={knowledgeBaseId}
          onClose={onEntryClose}
          onSave={onEntrySave}
        />
      )}

      {reviewRows && (
        <ReviewModal
          rows={reviewRows}
          replaceDuplicates={replaceDuplicates}
          onToggleReplace={onToggleReplace}
          onCancel={onCancelReview}
          onImport={onImportConfirm}
        />
      )}

      {importResult && (
        <ResultModal
          result={importResult}
          onDone={onDismissResult}
        />
      )}
    </>
  );
}
