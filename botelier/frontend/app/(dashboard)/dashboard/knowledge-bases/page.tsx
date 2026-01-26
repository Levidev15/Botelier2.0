"use client";

import { useState, useEffect } from "react";
import { BookOpen, Plus, Pencil, Trash2, ChevronRight, ArrowLeft, Upload, Download, Search, Tag, AlertCircle, X, Grid3x3, List } from "lucide-react";
import { notify, confirmAction } from "@/lib/notifications";
import { useAccountContext } from "@/lib/auth/useAccountContext";

interface KnowledgeBase {
  id: string;
  account_id: string;
  name: string;
  description: string | null;
  entry_count: number;
  created_at: string | null;
  updated_at: string | null;
}

interface Entry {
  id: string;
  knowledge_base_id: string;
  question: string;
  answer: string;
  category: string | null;
  expiration_date: string | null;
  is_expired: boolean;
  created_at: string;
  updated_at: string;
}

function formatDate(dateString: string | null): string {
  if (!dateString) return "N/A";
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined });
}

export default function KnowledgeBasesPage() {
  const { accountId, loading: contextLoading } = useAccountContext();
  
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKB, setSelectedKB] = useState<KnowledgeBase | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingKB, setEditingKB] = useState<KnowledgeBase | null>(null);
  
  const [showAddEntryModal, setShowAddEntryModal] = useState(false);
  const [editingEntry, setEditingEntry] = useState<Entry | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [view, setView] = useState<"grid" | "table">("grid");
  const [categoryFilter, setCategoryFilter] = useState<string>("");
  const [showExpired, setShowExpired] = useState(false);

  useEffect(() => {
    if (!contextLoading && accountId) {
      fetchKnowledgeBases();
    }
  }, [accountId, contextLoading]);

  const fetchKnowledgeBases = async () => {
    if (!accountId) return;
    try {
      setLoading(true);
      const res = await fetch(`/api/knowledge-bases?account_id=${accountId}`);
      const data = await res.json();
      setKnowledgeBases(data.knowledge_bases || []);
    } catch (error) {
      console.error("Failed to fetch knowledge bases:", error);
    } finally {
      setLoading(false);
    }
  };

  const fetchEntries = async (kbId: string) => {
    try {
      setLoading(true);
      const res = await fetch(`/api/knowledge-bases/${kbId}/entries`);
      const data = await res.json();
      setEntries(data.entries || []);
    } catch (error) {
      console.error("Failed to fetch entries:", error);
    } finally {
      setLoading(false);
    }
  };

  const selectKnowledgeBase = (kb: KnowledgeBase) => {
    setSelectedKB(kb);
    fetchEntries(kb.id);
  };

  const goBack = () => {
    setSelectedKB(null);
    setEntries([]);
    setSearchQuery("");
  };

  const handleDeleteKB = async (kb: KnowledgeBase) => {
    const confirmed = await confirmAction(
      "Delete Knowledge Base",
      `Are you sure you want to delete "${kb.name}"? This will permanently delete all ${kb.entry_count} entries.`
    );
    if (!confirmed) return;

    try {
      const res = await fetch(`/api/knowledge-bases/${kb.id}`, { method: "DELETE" });
      if (res.ok) {
        notify.success("Knowledge base deleted");
        fetchKnowledgeBases();
      } else {
        notify.error("Failed to delete knowledge base");
      }
    } catch (error) {
      notify.error("Failed to delete knowledge base");
    }
  };

  const handleDeleteEntry = async (entry: Entry) => {
    const confirmed = await confirmAction(
      "Delete Entry",
      `Are you sure you want to delete this Q&A entry?`
    );
    if (!confirmed) return;

    try {
      const res = await fetch(`/api/knowledge-bases/${selectedKB?.id}/entries/${entry.id}`, { method: "DELETE" });
      if (res.ok) {
        notify.success("Entry deleted");
        if (selectedKB) fetchEntries(selectedKB.id);
      } else {
        notify.error("Failed to delete entry");
      }
    } catch (error) {
      notify.error("Failed to delete entry");
    }
  };

  const handleExportCSV = () => {
    if (!entries.length) {
      notify.error("No entries to export");
      return;
    }

    const headers = ["question", "answer", "category", "expiration_date"];
    const csvContent = [
      headers.join(","),
      ...entries.map(e => [
        `"${e.question.replace(/"/g, '""')}"`,
        `"${e.answer.replace(/"/g, '""')}"`,
        `"${(e.category || '').replace(/"/g, '""')}"`,
        `"${e.expiration_date || ''}"`
      ].join(","))
    ].join("\n");

    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${selectedKB?.name || 'knowledge-base'}-entries.csv`;
    link.click();
    notify.success("Entries exported successfully");
  };

  const handleImportCSV = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !selectedKB) return;

    try {
      const text = await file.text();
      const lines = text.split("\n").filter(line => line.trim());
      
      if (lines.length < 2) {
        notify.error("CSV file must have a header row and at least one data row");
        return;
      }

      const header = lines[0].toLowerCase();
      if (!header.includes("question") || !header.includes("answer")) {
        notify.error("CSV must have 'question' and 'answer' columns");
        return;
      }

      let imported = 0;
      let failed = 0;
      for (let i = 1; i < lines.length; i++) {
        const values = lines[i].match(/("([^"]|"")*"|[^,]+)/g) || [];
        const cleanValue = (v: string) => v?.replace(/^"|"$/g, '').replace(/""/g, '"').trim() || '';
        
        const question = cleanValue(values[0]);
        const answer = cleanValue(values[1]);
        const category = cleanValue(values[2]) || null;
        const expiration_date = cleanValue(values[3]) || null;

        if (question && answer) {
          const res = await fetch(`/api/knowledge-bases/${selectedKB.id}/entries`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question, answer, category, expiration_date }),
          });
          if (res.ok) {
            imported++;
          } else {
            failed++;
          }
        }
      }

      if (failed > 0) {
        notify.info(`Imported ${imported} entries, ${failed} failed`);
      } else {
        notify.success(`Imported ${imported} entries`);
      }
      fetchEntries(selectedKB.id);
    } catch (error) {
      notify.error("Failed to import CSV");
    }

    e.target.value = "";
  };

  const uniqueCategories = Array.from(new Set(entries.filter(e => e.category).map(e => e.category as string)));
  const expiredCount = entries.filter(e => e.is_expired).length;

  const filteredEntries = entries.filter(e => {
    if (!showExpired && e.is_expired) return false;
    if (categoryFilter && e.category !== categoryFilter) return false;
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return e.question.toLowerCase().includes(q) || e.answer.toLowerCase().includes(q) || (e.category && e.category.toLowerCase().includes(q));
  });

  if (contextLoading || loading) {
    return (
      <div className="p-6">
        <div className="flex items-center justify-center h-64">
          <div className="text-white/60">Loading...</div>
        </div>
      </div>
    );
  }

  if (selectedKB) {
    return (
      <div className="p-6">
        <div className="flex items-center gap-4 mb-6">
          <button onClick={goBack} className="p-2 hover:bg-white/5 rounded-lg transition-colors">
            <ArrowLeft className="w-5 h-5 text-white/60" />
          </button>
          <div className="flex-1">
            <h1 className="text-2xl font-semibold text-white">{selectedKB.name}</h1>
            <p className="text-white/60 text-sm">{selectedKB.description || "Knowledge base entries"}</p>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
              <input
                type="text"
                placeholder="Search entries..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10 pr-4 py-2 bg-[#2A2A2A] border border-white/10 rounded-lg text-white placeholder:text-white/40 focus:outline-none focus:border-[#3B82F6]/50 w-64"
              />
            </div>
            {uniqueCategories.length > 0 && (
              <select
                value={categoryFilter}
                onChange={(e) => setCategoryFilter(e.target.value)}
                className="px-3 py-2 bg-[#2A2A2A] border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-[#3B82F6]/50"
              >
                <option value="">All Categories</option>
                {uniqueCategories.map((cat) => (
                  <option key={cat} value={cat}>{cat}</option>
                ))}
              </select>
            )}
            {expiredCount > 0 && (
              <button
                onClick={() => setShowExpired(!showExpired)}
                className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                  showExpired 
                    ? "bg-red-500/20 border border-red-500/50 text-red-400" 
                    : "bg-[#2A2A2A] border border-white/10 text-white/60 hover:text-white"
                }`}
              >
                <AlertCircle className="w-4 h-4" />
                {showExpired ? "Hide" : "Show"} Expired ({expiredCount})
              </button>
            )}
            <div className="flex items-center bg-[#2A2A2A] border border-white/10 rounded-lg">
              <button onClick={() => setView("grid")} className={`p-2 ${view === "grid" ? "text-[#3B82F6]" : "text-white/60"}`}>
                <Grid3x3 className="w-4 h-4" />
              </button>
              <button onClick={() => setView("table")} className={`p-2 ${view === "table" ? "text-[#3B82F6]" : "text-white/60"}`}>
                <List className="w-4 h-4" />
              </button>
            </div>
            <button onClick={handleExportCSV} className="flex items-center gap-2 px-3 py-2 bg-[#2A2A2A] border border-white/10 rounded-lg text-white/80 hover:text-white hover:border-white/20 transition-colors">
              <Download className="w-4 h-4" />
              Export
            </button>
            <label className="flex items-center gap-2 px-3 py-2 bg-[#2A2A2A] border border-white/10 rounded-lg text-white/80 hover:text-white hover:border-white/20 transition-colors cursor-pointer">
              <Upload className="w-4 h-4" />
              Import
              <input type="file" accept=".csv" onChange={handleImportCSV} className="hidden" />
            </label>
            <button onClick={() => setShowAddEntryModal(true)} className="flex items-center gap-2 px-4 py-2 bg-[#3B82F6] hover:bg-[#3B82F6]/80 text-white font-medium rounded-lg transition-colors">
              <Plus className="w-4 h-4" />
              Add Entry
            </button>
          </div>
        </div>

        {filteredEntries.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <BookOpen className="w-12 h-12 text-white/20 mb-4" />
            <h3 className="text-lg font-medium text-white/80 mb-2">No entries yet</h3>
            <p className="text-white/40 text-sm mb-4">Add Q&A entries to build your knowledge base</p>
            <button onClick={() => setShowAddEntryModal(true)} className="flex items-center gap-2 px-4 py-2 bg-[#3B82F6] hover:bg-[#3B82F6]/80 text-black font-medium rounded-lg transition-colors">
              <Plus className="w-4 h-4" />
              Add First Entry
            </button>
          </div>
        ) : view === "grid" ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredEntries.map((entry) => (
              <div key={entry.id} className="bg-[#1A1A1A] border border-white/10 rounded-xl p-4 hover:border-white/20 transition-colors group">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <h3 className="text-white font-medium line-clamp-2">{entry.question}</h3>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button onClick={() => { setEditingEntry(entry); setShowAddEntryModal(true); }} className="p-1.5 hover:bg-white/5 rounded">
                      <Pencil className="w-3.5 h-3.5 text-white/60" />
                    </button>
                    <button onClick={() => handleDeleteEntry(entry)} className="p-1.5 hover:bg-red-500/20 rounded">
                      <Trash2 className="w-3.5 h-3.5 text-red-400" />
                    </button>
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
                        <button onClick={() => { setEditingEntry(entry); setShowAddEntryModal(true); }} className="p-1.5 hover:bg-white/5 rounded">
                          <Pencil className="w-3.5 h-3.5 text-white/60" />
                        </button>
                        <button onClick={() => handleDeleteEntry(entry)} className="p-1.5 hover:bg-red-500/20 rounded">
                          <Trash2 className="w-3.5 h-3.5 text-red-400" />
                        </button>
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
            knowledgeBaseId={selectedKB.id}
            onClose={() => { setShowAddEntryModal(false); setEditingEntry(null); }}
            onSave={() => { setShowAddEntryModal(false); setEditingEntry(null); fetchEntries(selectedKB.id); }}
          />
        )}
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-white">Knowledge Bases</h1>
          <p className="text-white/60 text-sm mt-1">Manage Q&A knowledge for your AI assistants</p>
        </div>
        <button onClick={() => setShowCreateModal(true)} className="flex items-center gap-2 px-4 py-2 bg-[#3B82F6] hover:bg-[#3B82F6]/80 text-black font-medium rounded-lg transition-colors">
          <Plus className="w-4 h-4" />
          Create Knowledge Base
        </button>
      </div>

      {knowledgeBases.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <BookOpen className="w-12 h-12 text-white/20 mb-4" />
          <h3 className="text-lg font-medium text-white/80 mb-2">No knowledge bases yet</h3>
          <p className="text-white/40 text-sm mb-4">Create a knowledge base to store Q&A content for your assistants</p>
          <button onClick={() => setShowCreateModal(true)} className="flex items-center gap-2 px-4 py-2 bg-[#3B82F6] hover:bg-[#3B82F6]/80 text-black font-medium rounded-lg transition-colors">
            <Plus className="w-4 h-4" />
            Create First Knowledge Base
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {knowledgeBases.map((kb) => (
            <div key={kb.id} onClick={() => selectKnowledgeBase(kb)} className="bg-[#1A1A1A] border border-white/10 rounded-xl p-5 hover:border-[#3B82F6]/50 transition-colors cursor-pointer group">
              <div className="flex items-start justify-between mb-3">
                <div className="p-2 bg-[#3B82F6]/10 rounded-lg">
                  <BookOpen className="w-5 h-5 text-[#3B82F6]" />
                </div>
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
                  <button onClick={(e) => { e.stopPropagation(); setEditingKB(kb); setShowCreateModal(true); }} className="p-1.5 hover:bg-white/5 rounded">
                    <Pencil className="w-4 h-4 text-white/60" />
                  </button>
                  <button onClick={(e) => { e.stopPropagation(); handleDeleteKB(kb); }} className="p-1.5 hover:bg-red-500/20 rounded">
                    <Trash2 className="w-4 h-4 text-red-400" />
                  </button>
                </div>
              </div>
              <h3 className="text-white font-medium text-lg mb-1">{kb.name}</h3>
              <p className="text-white/60 text-sm mb-4 line-clamp-2">{kb.description || "No description"}</p>
              <div className="flex items-center justify-between">
                <span className="text-white/40 text-sm">{kb.entry_count} entries</span>
                <ChevronRight className="w-4 h-4 text-white/40 group-hover:text-[#3B82F6] transition-colors" />
              </div>
            </div>
          ))}
        </div>
      )}

      {showCreateModal && (
        <KBModal
          kb={editingKB}
          accountId={accountId!}
          onClose={() => { setShowCreateModal(false); setEditingKB(null); }}
          onSave={() => { setShowCreateModal(false); setEditingKB(null); fetchKnowledgeBases(); }}
        />
      )}
    </div>
  );
}

function KBModal({ kb, accountId, onClose, onSave }: { kb: KnowledgeBase | null; accountId: string; onClose: () => void; onSave: () => void }) {
  const [name, setName] = useState(kb?.name || "");
  const [description, setDescription] = useState(kb?.description || "");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!name.trim()) {
      notify.error("Name is required");
      return;
    }

    try {
      setSaving(true);
      const url = kb ? `/api/knowledge-bases/${kb.id}` : "/api/knowledge-bases";
      const method = kb ? "PUT" : "POST";
      const body = kb ? { name, description } : { account_id: accountId, name, description };

      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (res.ok) {
        notify.success(kb ? "Knowledge base updated" : "Knowledge base created");
        onSave();
      } else {
        notify.error("Failed to save knowledge base");
      }
    } catch (error) {
      notify.error("Failed to save knowledge base");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-[#1A1A1A] border border-white/10 rounded-xl w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold text-white">{kb ? "Edit Knowledge Base" : "Create Knowledge Base"}</h2>
          <button onClick={onClose} className="p-1 hover:bg-white/5 rounded">
            <X className="w-5 h-5 text-white/60" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm text-white/60 mb-2">Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Front Desk FAQs"
              className="w-full px-4 py-3 bg-[#2A2A2A] border border-white/10 rounded-lg text-white placeholder:text-white/40 focus:outline-none focus:border-[#3B82F6]/50"
            />
          </div>
          <div>
            <label className="block text-sm text-white/60 mb-2">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What topics does this knowledge base cover?"
              rows={3}
              className="w-full px-4 py-3 bg-[#2A2A2A] border border-white/10 rounded-lg text-white placeholder:text-white/40 focus:outline-none focus:border-[#3B82F6]/50 resize-none"
            />
          </div>
        </div>

        <div className="flex justify-end gap-3 mt-6">
          <button onClick={onClose} className="px-4 py-2 text-white/60 hover:text-white transition-colors">Cancel</button>
          <button onClick={handleSave} disabled={saving} className="px-4 py-2 bg-[#3B82F6] hover:bg-[#3B82F6]/80 text-black font-medium rounded-lg transition-colors disabled:opacity-50">
            {saving ? "Saving..." : kb ? "Update" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

function EntryModal({ entry, knowledgeBaseId, onClose, onSave }: { entry: Entry | null; knowledgeBaseId: string; onClose: () => void; onSave: () => void }) {
  const [question, setQuestion] = useState(entry?.question || "");
  const [answer, setAnswer] = useState(entry?.answer || "");
  const [category, setCategory] = useState(entry?.category || "");
  const [expirationDate, setExpirationDate] = useState(entry?.expiration_date ? entry.expiration_date.split('T')[0] : "");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!question.trim() || !answer.trim()) {
      notify.error("Question and answer are required");
      return;
    }

    try {
      setSaving(true);
      const url = entry ? `/api/knowledge-bases/${knowledgeBaseId}/entries/${entry.id}` : `/api/knowledge-bases/${knowledgeBaseId}/entries`;
      const method = entry ? "PUT" : "POST";

      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          question, 
          answer, 
          category: category || null,
          expiration_date: expirationDate || null
        }),
      });

      if (res.ok) {
        notify.success(entry ? "Entry updated" : "Entry created");
        onSave();
      } else {
        notify.error("Failed to save entry");
      }
    } catch (error) {
      notify.error("Failed to save entry");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-[#1A1A1A] border border-white/10 rounded-xl w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold text-white">{entry ? "Edit Entry" : "Add Entry"}</h2>
          <button onClick={onClose} className="p-1 hover:bg-white/5 rounded">
            <X className="w-5 h-5 text-white/60" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm text-white/60 mb-2">Question *</label>
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="What is your question?"
              className="w-full px-4 py-3 bg-[#2A2A2A] border border-white/10 rounded-lg text-white placeholder:text-white/40 focus:outline-none focus:border-[#3B82F6]/50"
            />
          </div>
          <div>
            <label className="block text-sm text-white/60 mb-2">Answer *</label>
            <textarea
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="Enter the answer..."
              rows={4}
              className="w-full px-4 py-3 bg-[#2A2A2A] border border-white/10 rounded-lg text-white placeholder:text-white/40 focus:outline-none focus:border-[#3B82F6]/50 resize-none"
            />
          </div>
          <div>
            <label className="block text-sm text-white/60 mb-2">Category</label>
            <input
              type="text"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="e.g., Amenities, Check-in, Policies"
              className="w-full px-4 py-3 bg-[#2A2A2A] border border-white/10 rounded-lg text-white placeholder:text-white/40 focus:outline-none focus:border-[#3B82F6]/50"
            />
          </div>
          <div>
            <label className="block text-sm text-white/60 mb-2">Expiration Date</label>
            <input
              type="date"
              value={expirationDate}
              onChange={(e) => setExpirationDate(e.target.value)}
              className="w-full px-4 py-3 bg-[#2A2A2A] border border-white/10 rounded-lg text-white focus:outline-none focus:border-[#3B82F6]/50"
            />
            <p className="text-white/40 text-xs mt-1">Optional - for time-limited promos or seasonal info</p>
          </div>
        </div>

        <div className="flex justify-end gap-3 mt-6">
          <button onClick={onClose} className="px-4 py-2 text-white/60 hover:text-white transition-colors">Cancel</button>
          <button onClick={handleSave} disabled={saving} className="px-4 py-2 bg-[#3B82F6] hover:bg-[#3B82F6]/80 text-black font-medium rounded-lg transition-colors disabled:opacity-50">
            {saving ? "Saving..." : entry ? "Update" : "Add Entry"}
          </button>
        </div>
      </div>
    </div>
  );
}
