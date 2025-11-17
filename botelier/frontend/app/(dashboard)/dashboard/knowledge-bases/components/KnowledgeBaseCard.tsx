"use client";

import { BookOpen, Trash2, Edit2, FileText } from "lucide-react";

interface KnowledgeBase {
  id: string;
  hotel_id: string;
  name: string;
  description: string | null;
  document_count: number;
  created_at: string;
  updated_at: string | null;
}

interface KnowledgeBaseCardProps {
  knowledgeBase: KnowledgeBase;
  onEdit: (kb: KnowledgeBase) => void;
  onDelete: (id: string) => void;
}

export default function KnowledgeBaseCard({ knowledgeBase, onEdit, onDelete }: KnowledgeBaseCardProps) {
  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
  };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 hover:border-gray-700 transition-colors">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center space-x-3">
          <div className="bg-blue-600/10 p-3 rounded-lg">
            <BookOpen className="h-6 w-6 text-blue-600" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">{knowledgeBase.name}</h3>
            <p className="text-sm text-gray-400">{formatDate(knowledgeBase.created_at)}</p>
          </div>
        </div>
      </div>

      {knowledgeBase.description && (
        <p className="text-gray-400 text-sm mb-4 line-clamp-2">{knowledgeBase.description}</p>
      )}

      <div className="flex items-center space-x-4 mb-4 text-sm text-gray-400">
        <div className="flex items-center space-x-1">
          <FileText className="h-4 w-4" />
          <span>{knowledgeBase.document_count} {knowledgeBase.document_count === 1 ? "document" : "documents"}</span>
        </div>
      </div>

      <div className="flex items-center space-x-2 pt-4 border-t border-gray-800">
        <button
          onClick={() => onEdit(knowledgeBase)}
          className="flex-1 flex items-center justify-center space-x-2 px-3 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg transition-colors text-sm"
        >
          <Edit2 className="h-4 w-4" />
          <span>Edit</span>
        </button>
        <button
          onClick={() => onDelete(knowledgeBase.id)}
          className="px-3 py-2 bg-gray-800 hover:bg-red-900/20 text-red-400 hover:text-red-300 rounded-lg transition-colors"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
