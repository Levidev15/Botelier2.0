"use client";

import { BookOpen, Plus, Pencil, Trash2, ChevronRight } from "lucide-react";
import type { KnowledgeBase } from "../types";
import KBModal from "./KBModal";

interface KBListProps {
  knowledgeBases: KnowledgeBase[];
  canCreate: boolean;
  canEdit: boolean;
  canDelete: boolean;
  onSelect: (kb: KnowledgeBase) => void;
  onEdit: (kb: KnowledgeBase) => void;
  onDelete: (kb: KnowledgeBase) => void;
  showCreateModal: boolean;
  setShowCreateModal: (v: boolean) => void;
  editingKB: KnowledgeBase | null;
  setEditingKB: (kb: KnowledgeBase | null) => void;
  accountId: string;
  onKBSaved: () => void;
  formatDate: (date: string) => string;
}

export default function KBList({
  knowledgeBases,
  canCreate,
  canEdit,
  canDelete,
  onSelect,
  onEdit,
  onDelete,
  showCreateModal,
  setShowCreateModal,
  editingKB,
  setEditingKB,
  accountId,
  onKBSaved,
  formatDate,
}: KBListProps) {
  return (
    <div className="h-full">
      <div className="border-b border-gray-800 bg-[#0a0a0a] sticky top-0 z-10">
        <div className="px-8 py-6">
          <div className="flex justify-between items-center">
            <div>
              <h1 className="text-2xl font-bold">Knowledge Bases</h1>
              <p className="text-sm text-gray-400 mt-1">Manage Q&A knowledge for your AI assistants</p>
            </div>
            {canCreate && (
              <button
                onClick={() => setShowCreateModal(true)}
                className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium"
              >
                <Plus className="h-4 w-4 mr-2" />
                Create Knowledge Base
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="p-8">
        {knowledgeBases.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-20 h-20 bg-gray-800 rounded-full flex items-center justify-center mb-4">
              <BookOpen className="h-10 w-10 text-gray-600" />
            </div>
            <h2 className="text-xl font-semibold text-white mb-2">No knowledge bases yet</h2>
            <p className="text-gray-400 text-center mb-6 max-w-md">Create a knowledge base to store Q&A content for your assistants</p>
            {canCreate && (
              <button
                onClick={() => setShowCreateModal(true)}
                className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg transition-colors"
              >
                <Plus className="h-5 w-5" />
                <span>Create Knowledge Base</span>
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {knowledgeBases.map((kb) => (
              <div
                key={kb.id}
                onClick={() => onSelect(kb)}
                className="flex items-center justify-between p-4 bg-[#141414] border border-gray-800 rounded-xl hover:border-gray-700 transition-colors cursor-pointer group"
              >
                <div className="flex items-center gap-4 flex-1 min-w-0">
                  <div className="p-2.5 bg-blue-600/10 rounded-lg shrink-0">
                    <BookOpen className="w-5 h-5 text-blue-500" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <h3 className="text-white font-medium truncate">{kb.name}</h3>
                    <p className="text-gray-500 text-sm truncate mt-0.5">{kb.description || "No description"}</p>
                  </div>
                </div>
                <div className="flex items-center gap-6 shrink-0 ml-4">
                  <div className="text-right">
                    <div className="text-sm text-white">{kb.entry_count}</div>
                    <div className="text-xs text-gray-500">entries</div>
                  </div>
                  <div className="text-right min-w-[80px]">
                    <div className="text-sm text-gray-400">{kb.updated_at ? formatDate(kb.updated_at) : "—"}</div>
                    <div className="text-xs text-gray-500">modified</div>
                  </div>
                  {(canEdit || canDelete) && (
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
                      {canEdit && (
                        <button
                          onClick={(e) => { e.stopPropagation(); onEdit(kb); }}
                          className="p-1.5 hover:bg-white/5 rounded"
                        >
                          <Pencil className="w-4 h-4 text-gray-500" />
                        </button>
                      )}
                      {canDelete && (
                        <button
                          onClick={(e) => { e.stopPropagation(); onDelete(kb); }}
                          className="p-1.5 hover:bg-red-500/20 rounded"
                        >
                          <Trash2 className="w-4 h-4 text-red-400" />
                        </button>
                      )}
                    </div>
                  )}
                  <ChevronRight className="w-4 h-4 text-gray-600 group-hover:text-blue-500 transition-colors" />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showCreateModal && (
        <KBModal
          kb={editingKB}
          accountId={accountId}
          onClose={() => { setShowCreateModal(false); setEditingKB(null); }}
          onSave={onKBSaved}
        />
      )}
    </div>
  );
}
