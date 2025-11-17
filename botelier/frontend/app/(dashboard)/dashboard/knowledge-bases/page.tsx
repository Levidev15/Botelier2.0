"use client";

import { useState, useEffect } from "react";
import { Plus, BookOpen } from "lucide-react";
import KnowledgeBaseCard from "./components/KnowledgeBaseCard";
import AddKnowledgeBaseDrawer from "./components/AddKnowledgeBaseDrawer";

interface KnowledgeBase {
  id: string;
  hotel_id: string;
  name: string;
  description: string | null;
  document_count: number;
  created_at: string;
  updated_at: string | null;
}

export default function KnowledgeBasesPage() {
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [selectedKB, setSelectedKB] = useState<KnowledgeBase | null>(null);
  const [loading, setLoading] = useState(true);

  const hotelId = "6b410bcc-f843-40df-b32d-078d3e01ac7f"; // Demo Hotel ID

  const fetchKnowledgeBases = async () => {
    try {
      setLoading(true);
      const response = await fetch(`/api/knowledge-bases?hotel_id=${hotelId}`);
      const data = await response.json();
      setKnowledgeBases(data.knowledge_bases || []);
    } catch (error) {
      console.error("Failed to fetch knowledge bases:", error);
      setKnowledgeBases([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchKnowledgeBases();
  }, []);

  const handleKnowledgeBaseSaved = () => {
    setIsDrawerOpen(false);
    setSelectedKB(null);
    fetchKnowledgeBases();
  };

  const handleEdit = (kb: KnowledgeBase) => {
    setSelectedKB(kb);
    setIsDrawerOpen(true);
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Are you sure you want to delete this knowledge base? All associated documents will be removed.")) return;

    try {
      const response = await fetch(`/api/knowledge-bases/${id}`, {
        method: "DELETE",
      });

      if (response.ok) {
        fetchKnowledgeBases();
      } else {
        alert("Failed to delete knowledge base");
      }
    } catch (error) {
      console.error("Failed to delete knowledge base:", error);
      alert("Failed to delete knowledge base");
    }
  };

  return (
    <div className="flex-1 overflow-auto bg-[#0a0a0a]">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-white mb-2">Knowledge Bases</h1>
            <p className="text-gray-400">Manage hotel information for AI assistants</p>
          </div>
          <button
            onClick={() => setIsDrawerOpen(true)}
            className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg transition-colors"
          >
            <Plus className="h-5 w-5" />
            <span>Add Knowledge Base</span>
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
          </div>
        ) : knowledgeBases.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 px-4">
            <div className="bg-gray-800/50 rounded-full p-6 mb-6">
              <BookOpen className="h-12 w-12 text-gray-600" />
            </div>
            <h3 className="text-xl font-semibold text-white mb-2">No knowledge bases yet</h3>
            <p className="text-gray-400 mb-6 text-center max-w-md">
              Create knowledge bases to give your AI assistants information about hotel policies, menus, and services
            </p>
            <button
              onClick={() => setIsDrawerOpen(true)}
              className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg transition-colors"
            >
              <Plus className="h-5 w-5" />
              <span>Add Knowledge Base</span>
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {knowledgeBases.map((kb) => (
              <KnowledgeBaseCard
                key={kb.id}
                knowledgeBase={kb}
                onEdit={handleEdit}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}
      </div>

      {isDrawerOpen && (
        <AddKnowledgeBaseDrawer
          hotelId={hotelId}
          knowledgeBase={selectedKB}
          onClose={() => {
            setIsDrawerOpen(false);
            setSelectedKB(null);
          }}
          onSaved={handleKnowledgeBaseSaved}
        />
      )}
    </div>
  );
}
