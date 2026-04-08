"use client";

import { useState, useEffect, useRef } from "react";
import { BookOpen, Plus, Pencil, Trash2, ChevronRight, ArrowLeft, Upload, Download, Search, Tag, AlertCircle, X, Grid3x3, List } from "lucide-react";
import { notify, confirmAction } from "@/lib/notifications";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { usePagePermission, PermissionGate, AccessDeniedPage } from "@/components/ui/PermissionGate";
import { usePermissions } from "@/lib/auth/usePermissions";
import { useAuthToken } from "@/lib/auth/useAuthToken";

import type { KnowledgeBase, Entry, ParsedRow, ImportResult } from "./types";
import { parseCSVLine, formatDate } from "./types";
import ReviewModal from "./components/ReviewModal";
import ResultModal from "./components/ResultModal";
import KBModal from "./components/KBModal";
import EntryModal from "./components/EntryModal";

export default function KnowledgeBasesPage() {
  const { accountId, loading: contextLoading } = useAccountContext();
  const { hasAccess, loading: permLoading } = usePagePermission("knowledge_base", "view");
  const { can, isPlatformAdmin } = usePermissions();
  const { authFetch } = useAuthToken();
  const canCreate = isPlatformAdmin || can("knowledge_base", "create");
  const canEdit = isPlatformAdmin || can("knowledge_base", "edit");
  const canDelete = isPlatformAdmin || can("knowledge_base", "delete");
  const canImport = isPlatformAdmin || can("knowledge_base", "import");

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

  const [reviewRows, setReviewRows] = useState<ParsedRow[] | null>(null);
  const [replaceDuplicates, setReplaceDuplicates] = useState(false);
  const [importProgress, setImportProgress] = useState<{ done: number; total: number } | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const importFileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!contextLoading && accountId) {
      fetchKnowledgeBases();
    }
  }, [accountId, contextLoading]);

  const fetchKnowledgeBases = async () => {
    if (!accountId) return;
    try {
      setLoading(true);
      const res = await authFetch(`/api/knowledge-bases?account_id=${accountId}`);
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
      const res = await authFetch(`/api/knowledge-bases/${kbId}/entries`);
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
      `Delete knowledge base "${kb.name}"? This will permanently delete all ${kb.entry_count} entries.`
    );
    if (!confirmed) return;

    try {
      const res = await authFetch(`/api/knowledge-bases/${kb.id}`, { method: "DELETE" });
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
      "Are you sure you want to delete this Q&A entry?"
    );
    if (!confirmed) return;

    try {
      const res = await authFetch(`/api/knowledge-bases/${selectedKB?.id}/entries/${entry.id}`, { method: "DELETE" });
      if (res.ok) {
        notify.success("Entry deleted");
        setEntries(prev => prev.filter(e => e.id !== entry.id));
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

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !selectedKB) return;

    try {
      const text = await file.text();
      const lines = text.split("\n").filter(line => line.trim());

      if (lines.length < 2) {
        notify.error("CSV file must have a header row and at least one data row");
        if (importFileRef.current) importFileRef.current.value = "";
        return;
      }

      const headerLine = lines[0].toLowerCase();
      const headers = parseCSVLine(headerLine);
      const qIdx = headers.indexOf("question");
      const aIdx = headers.indexOf("answer");
      const cIdx = headers.indexOf("category");
      const eIdx = headers.indexOf("expiration_date");

      if (qIdx === -1 || aIdx === -1) {
        notify.error("CSV must have 'question' and 'answer' columns");
        if (importFileRef.current) importFileRef.current.value = "";
        return;
      }

      const existingQuestions = new Set(entries.map(e => e.question.trim().toLowerCase()));

      const rows: ParsedRow[] = [];
      for (let i = 1; i < lines.length; i++) {
        const values = parseCSVLine(lines[i]);
        const question = values[qIdx] || "";
        const answer = values[aIdx] || "";
        if (!question && !answer) continue;
        rows.push({
          question,
          answer,
          category: cIdx !== -1 ? (values[cIdx] || null) : null,
          expiration_date: eIdx !== -1 ? (values[eIdx] || null) : null,
          isDuplicate: existingQuestions.has(question.trim().toLowerCase()),
        });
      }

      if (rows.length === 0) {
        notify.error("No valid rows found in CSV");
        if (importFileRef.current) importFileRef.current.value = "";
        return;
      }

      setReplaceDuplicates(false);
      setReviewRows(rows);
    } catch (error) {
      notify.error("Failed to read CSV file");
    }

    if (importFileRef.current) importFileRef.current.value = "";
  };

  const handleImportConfirm = async () => {
    if (!reviewRows || !selectedKB) return;

    const rows = reviewRows;
    setReviewRows(null);

    const BATCH_SIZE = 20;
    const totalRows = rows.length;
    setImportProgress({ done: 0, total: totalRows });

    const aggregated: ImportResult = { created: 0, replaced: 0, skipped: 0, errors: 0, error_details: [] };

    for (let offset = 0; offset < rows.length; offset += BATCH_SIZE) {
      const batch = rows.slice(offset, offset + BATCH_SIZE);

      const csvLines = ["question,answer,category,expiration_date"];
      for (const r of batch) {
        const q = `"${(r.question || '').replace(/"/g, '""')}"`;
        const a = `"${(r.answer || '').replace(/"/g, '""')}"`;
        const c = `"${(r.category || '').replace(/"/g, '""')}"`;
        const e = `"${r.expiration_date || ''}"`;
        csvLines.push(`${q},${a},${c},${e}`);
      }
      const csvBlob = new Blob([csvLines.join("\n")], { type: "text/csv" });
      const formData = new FormData();
      formData.append("file", csvBlob, "batch.csv");

      try {
        const res = await authFetch(
          `/api/knowledge-bases/${selectedKB.id}/entries/import-csv?replace_duplicates=${replaceDuplicates}`,
          { method: "POST", body: formData }
        );
        if (res.ok) {
          const data = await res.json();
          aggregated.created += data.created || 0;
          aggregated.replaced += data.replaced || 0;
          aggregated.skipped += data.skipped || 0;
          aggregated.errors += data.errors || 0;
          if (data.error_details) {
            aggregated.error_details.push(...data.error_details);
          }
        } else {
          aggregated.errors += batch.length;
          aggregated.error_details.push(`Batch at row ${offset + 2} failed with status ${res.status}`);
        }
      } catch (err) {
        aggregated.errors += batch.length;
        aggregated.error_details.push(`Batch at row ${offset + 2} failed: network error`);
      }

      setImportProgress({ done: Math.min(offset + BATCH_SIZE, totalRows), total: totalRows });
    }

    setImportProgress(null);
    setImportResult(aggregated);
    fetchEntries(selectedKB.id);
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
      <div className="h-full">
        <div className="border-b border-gray-800 bg-[#0a0a0a] sticky top-0 z-10">
          <div className="px-8 py-6">
            <h1 className="text-2xl font-bold">Knowledge Bases</h1>
            <p className="text-sm text-gray-400 mt-1">Manage Q&A knowledge for your AI assistants</p>
          </div>
        </div>
        <div className="flex items-center justify-center py-24">
          <div className="text-gray-400">Loading...</div>
        </div>
      </div>
    );
  }

  if (selectedKB) {
    return (
      <div className="h-full">
        {importProgress && (
          <div className="fixed top-0 left-0 right-0 z-50 bg-blue-600 text-white text-sm font-medium px-6 py-3 flex items-center justify-center gap-3 shadow-lg">
            <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
            Syncing {importProgress.done} of {importProgress.total} entries…
          </div>
        )}

        <div className={`border-b border-gray-800 bg-[#0a0a0a] sticky z-10 ${importProgress ? "top-10" : "top-0"}`}>
          <div className="px-8 py-6">
            <div className="flex items-center gap-4">
              <button onClick={goBack} className="p-2 hover:bg-gray-800 rounded-lg transition-colors">
                <ArrowLeft className="w-5 h-5 text-gray-400" />
              </button>
              <div className="flex-1">
                <h1 className="text-2xl font-bold">{selectedKB.name}</h1>
                <p className="text-sm text-gray-400 mt-0.5">{selectedKB.description || "Knowledge base entries"}</p>
              </div>
              <div className="flex items-center gap-2">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                  <input
                    type="text"
                    placeholder="Search entries..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-10 pr-4 py-2 bg-[#141414] border border-gray-800 rounded-lg text-white placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-600 w-64 text-sm"
                  />
                </div>
                {uniqueCategories.length > 0 && (
                  <select
                    value={categoryFilter}
                    onChange={(e) => setCategoryFilter(e.target.value)}
                    className="px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
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
                        : "bg-[#141414] border border-gray-800 text-gray-400 hover:text-white"
                    }`}
                  >
                    <AlertCircle className="w-4 h-4" />
                    {showExpired ? "Hide" : "Show"} Expired ({expiredCount})
                  </button>
                )}
                <div className="flex items-center bg-[#141414] border border-gray-800 rounded-lg">
                  <button onClick={() => setView("grid")} className={`p-2 ${view === "grid" ? "text-blue-500" : "text-gray-500"}`}>
                    <Grid3x3 className="w-4 h-4" />
                  </button>
                  <button onClick={() => setView("table")} className={`p-2 ${view === "table" ? "text-blue-500" : "text-gray-500"}`}>
                    <List className="w-4 h-4" />
                  </button>
                </div>
                <button onClick={handleExportCSV} className="flex items-center gap-2 px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg text-gray-400 hover:text-white transition-colors text-sm">
                  <Download className="w-4 h-4" />
                  Export
                </button>
                {canImport && (
                  <label className="flex items-center gap-2 px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg text-gray-400 hover:text-white transition-colors cursor-pointer text-sm">
                    <Upload className="w-4 h-4" />
                    Import
                    <input ref={importFileRef} type="file" accept=".csv" onChange={handleFileChange} className="hidden" />
                  </label>
                )}
                {canCreate && (
                  <button onClick={() => setShowAddEntryModal(true)} className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium">
                    <Plus className="h-4 w-4 mr-2" />
                    Add Entry
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="p-8">
        {filteredEntries.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <BookOpen className="w-12 h-12 text-white/20 mb-4" />
            <h3 className="text-lg font-medium text-white/80 mb-2">No entries yet</h3>
            <p className="text-white/40 text-sm mb-4">Add Q&A entries to build your knowledge base</p>
            {canCreate && (
              <button onClick={() => setShowAddEntryModal(true)} className="flex items-center gap-2 px-4 py-2 bg-[#3B82F6] hover:bg-[#3B82F6]/80 text-black font-medium rounded-lg transition-colors">
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
                      <button onClick={() => { setEditingEntry(entry); setShowAddEntryModal(true); }} className="p-1.5 hover:bg-white/5 rounded">
                        <Pencil className="w-3.5 h-3.5 text-white/60" />
                      </button>
                    )}
                    {canDelete && (
                      <button onClick={() => handleDeleteEntry(entry)} className="p-1.5 hover:bg-red-500/20 rounded">
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
                          <button onClick={() => { setEditingEntry(entry); setShowAddEntryModal(true); }} className="p-1.5 hover:bg-white/5 rounded">
                            <Pencil className="w-3.5 h-3.5 text-white/60" />
                          </button>
                        )}
                        {canDelete && (
                          <button onClick={() => handleDeleteEntry(entry)} className="p-1.5 hover:bg-red-500/20 rounded">
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
            knowledgeBaseId={selectedKB.id}
            onClose={() => { setShowAddEntryModal(false); setEditingEntry(null); }}
            onSave={(saved) => {
              setShowAddEntryModal(false);
              setEditingEntry(null);
              setEntries(prev => {
                const exists = prev.some(e => e.id === saved.id);
                return exists ? prev.map(e => e.id === saved.id ? saved : e) : [saved, ...prev];
              });
            }}
          />
        )}

        {reviewRows && (
          <ReviewModal
            rows={reviewRows}
            replaceDuplicates={replaceDuplicates}
            onToggleReplace={() => setReplaceDuplicates(r => !r)}
            onCancel={() => { setReviewRows(null); }}
            onImport={handleImportConfirm}
          />
        )}

        {importResult && (
          <ResultModal
            result={importResult}
            onDone={() => setImportResult(null)}
          />
        )}
        </div>
      </div>
    );
  }

  if (!permLoading && !hasAccess) {
    return <AccessDeniedPage message="You don't have permission to view knowledge bases." />;
  }

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
              <button onClick={() => setShowCreateModal(true)} className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium">
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
            <button onClick={() => setShowCreateModal(true)} className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg transition-colors">
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
              onClick={() => selectKnowledgeBase(kb)}
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
                  <div className="text-sm text-gray-400">{formatDate(kb.updated_at)}</div>
                  <div className="text-xs text-gray-500">modified</div>
                </div>
                {(canEdit || canDelete) && (
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
                    {canEdit && (
                      <button onClick={(e) => { e.stopPropagation(); setEditingKB(kb); setShowCreateModal(true); }} className="p-1.5 hover:bg-white/5 rounded">
                        <Pencil className="w-4 h-4 text-gray-500" />
                      </button>
                    )}
                    {canDelete && (
                      <button onClick={(e) => { e.stopPropagation(); handleDeleteKB(kb); }} className="p-1.5 hover:bg-red-500/20 rounded">
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
          accountId={accountId!}
          onClose={() => { setShowCreateModal(false); setEditingKB(null); }}
          onSave={() => { setShowCreateModal(false); setEditingKB(null); fetchKnowledgeBases(); }}
        />
      )}
    </div>
  );
}
