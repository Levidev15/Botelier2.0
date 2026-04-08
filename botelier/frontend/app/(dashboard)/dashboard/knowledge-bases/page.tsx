"use client";

import { useState, useEffect, useRef } from "react";
import { notify, confirmAction } from "@/lib/notifications";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { usePagePermission, AccessDeniedPage } from "@/components/ui/PermissionGate";
import { usePermissions } from "@/lib/auth/usePermissions";
import { useAuthToken } from "@/lib/auth/useAuthToken";

import type { KnowledgeBase, Entry, ParsedRow, ImportResult } from "./types";
import { parseCSVLine, formatDate } from "./types";
import KBList from "./components/KBList";
import KBDetailHeader from "./components/KBDetailHeader";
import KBEntryList from "./components/KBEntryList";

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
        <KBDetailHeader
          selectedKB={selectedKB}
          importProgress={importProgress}
          goBack={goBack}
          searchQuery={searchQuery}
          setSearchQuery={setSearchQuery}
          categoryFilter={categoryFilter}
          setCategoryFilter={setCategoryFilter}
          uniqueCategories={uniqueCategories}
          expiredCount={expiredCount}
          showExpired={showExpired}
          setShowExpired={setShowExpired}
          view={view}
          setView={setView}
          handleExportCSV={handleExportCSV}
          canImport={canImport}
          importFileRef={importFileRef}
          handleFileChange={handleFileChange}
          canCreate={canCreate}
          onAddEntry={() => setShowAddEntryModal(true)}
        />

        <div className="p-8">
          <KBEntryList
            filteredEntries={filteredEntries}
            view={view}
            canCreate={canCreate}
            canEdit={canEdit}
            canDelete={canDelete}
            knowledgeBaseId={selectedKB.id}
            onAddEntry={() => setShowAddEntryModal(true)}
            onEditEntry={(entry) => { setEditingEntry(entry); setShowAddEntryModal(true); }}
            onDeleteEntry={handleDeleteEntry}
            showAddEntryModal={showAddEntryModal}
            editingEntry={editingEntry}
            onEntryClose={() => { setShowAddEntryModal(false); setEditingEntry(null); }}
            onEntrySave={(saved) => {
              setShowAddEntryModal(false);
              setEditingEntry(null);
              setEntries(prev => {
                const exists = prev.some(e => e.id === saved.id);
                return exists ? prev.map(e => e.id === saved.id ? saved : e) : [saved, ...prev];
              });
            }}
            reviewRows={reviewRows}
            replaceDuplicates={replaceDuplicates}
            onToggleReplace={() => setReplaceDuplicates(r => !r)}
            onCancelReview={() => setReviewRows(null)}
            onImportConfirm={handleImportConfirm}
            importResult={importResult}
            onDismissResult={() => setImportResult(null)}
          />
        </div>
      </div>
    );
  }

  if (!permLoading && !hasAccess) {
    return <AccessDeniedPage message="You don't have permission to view knowledge bases." />;
  }

  return (
    <KBList
      knowledgeBases={knowledgeBases}
      canCreate={canCreate}
      canEdit={canEdit}
      canDelete={canDelete}
      onSelect={selectKnowledgeBase}
      onEdit={(kb) => { setEditingKB(kb); setShowCreateModal(true); }}
      onDelete={handleDeleteKB}
      showCreateModal={showCreateModal}
      setShowCreateModal={setShowCreateModal}
      editingKB={editingKB}
      setEditingKB={setEditingKB}
      accountId={accountId!}
      onKBSaved={() => { setShowCreateModal(false); setEditingKB(null); fetchKnowledgeBases(); }}
      formatDate={formatDate}
    />
  );
}
