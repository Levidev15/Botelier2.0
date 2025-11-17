"use client";

import { useState, useEffect } from "react";
import { X, FileText, Upload, Trash2 } from "lucide-react";

interface KnowledgeBase {
  id: string;
  hotel_id: string;
  name: string;
  description: string | null;
  document_count: number;
  created_at: string;
  updated_at: string | null;
}

interface Document {
  id: string;
  knowledge_base_id: string;
  filename: string;
  content_type: string;
  character_count: number;
  created_at: string;
}

interface AddKnowledgeBaseDrawerProps {
  hotelId: string;
  knowledgeBase: KnowledgeBase | null;
  onClose: () => void;
  onSaved: () => void;
}

export default function AddKnowledgeBaseDrawer({ hotelId, knowledgeBase, onClose, onSaved }: AddKnowledgeBaseDrawerProps) {
  const [activeTab, setActiveTab] = useState<"basic" | "documents">("basic");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [documents, setDocuments] = useState<Document[]>([]);
  const [newDocContent, setNewDocContent] = useState("");
  const [newDocFilename, setNewDocFilename] = useState("");
  const [loading, setLoading] = useState(false);
  const [documentsLoading, setDocumentsLoading] = useState(false);

  const isEditing = !!knowledgeBase;

  useEffect(() => {
    if (knowledgeBase) {
      setName(knowledgeBase.name);
      setDescription(knowledgeBase.description || "");
      fetchDocuments();
    }
  }, [knowledgeBase]);

  const fetchDocuments = async () => {
    if (!knowledgeBase) return;
    
    try {
      setDocumentsLoading(true);
      const response = await fetch(`/api/knowledge-bases/${knowledgeBase.id}/documents`);
      const data = await response.json();
      setDocuments(data.documents || []);
    } catch (error) {
      console.error("Failed to fetch documents:", error);
    } finally {
      setDocumentsLoading(false);
    }
  };

  const handleSave = async () => {
    if (!name.trim()) {
      alert("Please enter a name");
      return;
    }

    setLoading(true);

    try {
      const method = isEditing ? "PUT" : "POST";
      const url = isEditing ? `/api/knowledge-bases/${knowledgeBase.id}` : `/api/knowledge-bases`;

      const body = isEditing
        ? { name: name.trim(), description: description.trim() || null }
        : { hotel_id: hotelId, name: name.trim(), description: description.trim() || null };

      const response = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (response.ok) {
        onSaved();
      } else {
        alert("Failed to save knowledge base");
      }
    } catch (error) {
      console.error("Failed to save knowledge base:", error);
      alert("Failed to save knowledge base");
    } finally {
      setLoading(false);
    }
  };

  const handleAddDocument = async () => {
    if (!knowledgeBase) {
      alert("Please save the knowledge base first");
      return;
    }

    if (!newDocFilename.trim() || !newDocContent.trim()) {
      alert("Please enter both filename and content");
      return;
    }

    setLoading(true);

    try {
      const response = await fetch(`/api/knowledge-bases/${knowledgeBase.id}/documents`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: newDocFilename.trim(),
          content: newDocContent.trim(),
          content_type: "text",
        }),
      });

      if (response.ok) {
        setNewDocFilename("");
        setNewDocContent("");
        fetchDocuments();
      } else {
        alert("Failed to add document");
      }
    } catch (error) {
      console.error("Failed to add document:", error);
      alert("Failed to add document");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteDocument = async (docId: string) => {
    if (!knowledgeBase) return;
    if (!confirm("Are you sure you want to delete this document?")) return;

    try {
      const response = await fetch(`/api/knowledge-bases/${knowledgeBase.id}/documents/${docId}`, {
        method: "DELETE",
      });

      if (response.ok) {
        fetchDocuments();
      } else {
        alert("Failed to delete document");
      }
    } catch (error) {
      console.error("Failed to delete document:", error);
      alert("Failed to delete document");
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-end z-50" onClick={onClose}>
      <div
        className="bg-gray-900 w-full max-w-2xl h-full overflow-y-auto shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-gray-900 border-b border-gray-800 p-6 z-10">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-2xl font-bold text-white">
              {isEditing ? "Edit Knowledge Base" : "Add Knowledge Base"}
            </h2>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-white transition-colors"
            >
              <X className="h-6 w-6" />
            </button>
          </div>

          <div className="flex space-x-2 border-b border-gray-800">
            <button
              onClick={() => setActiveTab("basic")}
              className={`px-4 py-2 font-medium transition-colors ${
                activeTab === "basic"
                  ? "text-blue-600 border-b-2 border-blue-600"
                  : "text-gray-400 hover:text-white"
              }`}
            >
              Basic Info
            </button>
            <button
              onClick={() => setActiveTab("documents")}
              disabled={!isEditing}
              className={`px-4 py-2 font-medium transition-colors ${
                activeTab === "documents"
                  ? "text-blue-600 border-b-2 border-blue-600"
                  : "text-gray-400 hover:text-white"
              } ${!isEditing ? "opacity-50 cursor-not-allowed" : ""}`}
            >
              Documents ({documents.length})
            </button>
          </div>
        </div>

        <div className="p-6">
          {activeTab === "basic" && (
            <div className="space-y-6">
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-2">
                  Name *
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-blue-600"
                  placeholder="e.g., Hotel Policies"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-400 mb-2">
                  Description
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-blue-600 resize-none"
                  placeholder="Describe what this knowledge base contains"
                />
              </div>

              <div className="pt-4 border-t border-gray-800 flex space-x-3">
                <button
                  onClick={handleSave}
                  disabled={loading}
                  className="flex-1 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
                >
                  {loading ? "Saving..." : isEditing ? "Save Changes" : "Create Knowledge Base"}
                </button>
                <button
                  onClick={onClose}
                  className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {activeTab === "documents" && isEditing && (
            <div className="space-y-6">
              <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
                <h3 className="text-lg font-semibold text-white mb-4 flex items-center">
                  <Upload className="h-5 w-5 mr-2" />
                  Add Document
                </h3>

                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-400 mb-2">
                      Filename *
                    </label>
                    <input
                      type="text"
                      value={newDocFilename}
                      onChange={(e) => setNewDocFilename(e.target.value)}
                      className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-blue-600"
                      placeholder="e.g., check-in-policy.txt"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-400 mb-2">
                      Content *
                    </label>
                    <textarea
                      value={newDocContent}
                      onChange={(e) => setNewDocContent(e.target.value)}
                      rows={8}
                      className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-blue-600 resize-none font-mono text-sm"
                      placeholder="Paste your document content here..."
                    />
                  </div>

                  <button
                    onClick={handleAddDocument}
                    disabled={loading}
                    className="w-full bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
                  >
                    {loading ? "Adding..." : "Add Document"}
                  </button>
                </div>
              </div>

              <div>
                <h3 className="text-lg font-semibold text-white mb-4 flex items-center">
                  <FileText className="h-5 w-5 mr-2" />
                  Documents
                </h3>

                {documentsLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                  </div>
                ) : documents.length === 0 ? (
                  <div className="text-center py-8 text-gray-400">
                    No documents yet. Add one above to get started.
                  </div>
                ) : (
                  <div className="space-y-3">
                    {documents.map((doc) => (
                      <div
                        key={doc.id}
                        className="bg-gray-800 border border-gray-700 rounded-lg p-4 flex items-center justify-between"
                      >
                        <div className="flex items-center space-x-3 flex-1 min-w-0">
                          <FileText className="h-5 w-5 text-blue-600 flex-shrink-0" />
                          <div className="flex-1 min-w-0">
                            <p className="text-white font-medium truncate">{doc.filename}</p>
                            <p className="text-sm text-gray-400">
                              {doc.character_count.toLocaleString()} characters
                            </p>
                          </div>
                        </div>
                        <button
                          onClick={() => handleDeleteDocument(doc.id)}
                          className="ml-4 p-2 text-red-400 hover:text-red-300 hover:bg-red-900/20 rounded-lg transition-colors"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
