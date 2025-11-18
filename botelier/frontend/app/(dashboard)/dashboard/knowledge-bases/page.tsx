"use client";

import { useState, useEffect, useMemo } from "react";
import { BookOpen, Plus, Grid3x3, List, Upload, Pencil, Trash2, AlertCircle, X, Search, Tag } from "lucide-react";

const HOTEL_ID = "6b410bcc-f843-40df-b32d-078d3e01ac7f";

interface Entry {
  id: string;
  hotel_id: string;
  question: string;
  answer: string;
  category: string | null;
  expiration_date: string | null;
  is_expired: boolean;
  created_at: string;
}

type SortOption = "newest" | "oldest" | "alphabetical" | "expiring" | "expired";

export default function KnowledgeBasesPage() {
  const [view, setView] = useState<"grid" | "table">("grid");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  const [showExpired, setShowExpired] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showCSVModal, setShowCSVModal] = useState(false);
  const [showBulkCategorizeModal, setShowBulkCategorizeModal] = useState(false);
  const [editEntry, setEditEntry] = useState<Entry | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [sortBy, setSortBy] = useState<SortOption>("newest");

  useEffect(() => {
    fetchEntries();
  }, [showExpired]);

  const fetchEntries = async () => {
    try {
      setLoading(true);
      const res = await fetch(`/api/entries?hotel_id=${HOTEL_ID}&include_expired=${showExpired}`);
      const data = await res.json();
      setEntries(data.entries || []);
      setSelectedIds(new Set());
    } catch (error) {
      console.error("Failed to fetch entries:", error);
    } finally {
      setLoading(false);
    }
  };

  const uniqueCategories = useMemo(() => {
    const cats = new Set<string>();
    entries.forEach(e => {
      if (e.category) cats.add(e.category);
    });
    return Array.from(cats).sort();
  }, [entries]);

  const filteredAndSortedEntries = useMemo(() => {
    let filtered = entries;

    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(e =>
        e.question.toLowerCase().includes(query) ||
        e.answer.toLowerCase().includes(query) ||
        (e.category && e.category.toLowerCase().includes(query))
      );
    }

    if (categoryFilter !== "all") {
      filtered = filtered.filter(e => e.category === categoryFilter);
    }

    const sorted = [...filtered];
    switch (sortBy) {
      case "newest":
        sorted.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
        break;
      case "oldest":
        sorted.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
        break;
      case "alphabetical":
        sorted.sort((a, b) => a.question.localeCompare(b.question));
        break;
      case "expiring":
        sorted.sort((a, b) => {
          if (!a.expiration_date) return 1;
          if (!b.expiration_date) return -1;
          return new Date(a.expiration_date).getTime() - new Date(b.expiration_date).getTime();
        });
        break;
      case "expired":
        sorted.sort((a, b) => {
          if (a.is_expired && !b.is_expired) return -1;
          if (!a.is_expired && b.is_expired) return 1;
          return 0;
        });
        break;
    }

    return sorted;
  }, [entries, searchQuery, categoryFilter, sortBy]);

  const handleDelete = async (entryId: string) => {
    if (!confirm("Delete this entry?")) return;
    try {
      const res = await fetch(`/api/entries/${entryId}`, { method: "DELETE" });
      if (res.ok) fetchEntries();
    } catch (error) {
      console.error("Delete failed:", error);
    }
  };

  const handleBulkDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!confirm(`Delete ${selectedIds.size} selected entries?`)) return;

    try {
      const res = await fetch(`/api/entries/bulk`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entry_ids: Array.from(selectedIds) })
      });
      if (res.ok) fetchEntries();
    } catch (error) {
      console.error("Bulk delete failed:", error);
    }
  };

  const handleBulkCategorize = async (category: string | null) => {
    if (selectedIds.size === 0) return;

    try {
      const res = await fetch(`/api/entries/bulk`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entry_ids: Array.from(selectedIds), category })
      });
      if (res.ok) {
        setShowBulkCategorizeModal(false);
        fetchEntries();
      }
    } catch (error) {
      console.error("Bulk categorize failed:", error);
    }
  };

  const toggleSelection = (id: string) => {
    const newSelected = new Set(selectedIds);
    if (newSelected.has(id)) newSelected.delete(id);
    else newSelected.add(id);
    setSelectedIds(newSelected);
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === filteredAndSortedEntries.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredAndSortedEntries.map(e => e.id)));
    }
  };

  const activeCount = entries.filter(e => !e.is_expired).length;
  const expiredCount = entries.filter(e => e.is_expired).length;

  return (
    <div className="flex-1 overflow-auto bg-[#0a0a0a]">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-white mb-2 flex items-center">
              <BookOpen className="h-8 w-8 mr-3 text-blue-600" />
              Knowledge Base
            </h1>
            <p className="text-gray-400">Manage Q&A entries for AI assistants</p>
          </div>
          <div className="flex space-x-3">
            <button 
              onClick={() => setShowCSVModal(true)}
              className="flex items-center px-4 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg transition-colors"
            >
              <Upload className="h-4 w-4 mr-2" />
              Import CSV
            </button>
            <button 
              onClick={() => { setEditEntry(null); setShowAddModal(true); }}
              className="flex items-center px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
            >
              <Plus className="h-5 w-5 mr-2" />
              Add Entry
            </button>
          </div>
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 mb-6">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center space-x-8">
              <div>
                <div className="text-3xl font-bold text-white">{entries.length}</div>
                <div className="text-sm text-gray-400">Total Entries</div>
              </div>
              <div>
                <div className="text-2xl font-semibold text-green-500">{activeCount}</div>
                <div className="text-sm text-gray-400">Active</div>
              </div>
              <div>
                <div className="text-2xl font-semibold text-orange-500">{expiredCount}</div>
                <div className="text-sm text-gray-400">Expired</div>
              </div>
            </div>

            <div className="flex items-center space-x-4">
              <label className="flex items-center space-x-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={showExpired}
                  onChange={(e) => setShowExpired(e.target.checked)}
                  className="w-4 h-4 text-blue-600 bg-gray-800 border-gray-700 rounded"
                />
                <span className="text-sm text-gray-400">Show Expired</span>
              </label>

              <div className="flex bg-gray-800 rounded-lg p-1">
                <button
                  onClick={() => setView("grid")}
                  className={`p-2 rounded ${view === "grid" ? "bg-blue-600 text-white" : "text-gray-400"}`}
                >
                  <Grid3x3 className="h-4 w-4" />
                </button>
                <button
                  onClick={() => setView("table")}
                  className={`p-2 rounded ${view === "table" ? "bg-blue-600 text-white" : "text-gray-400"}`}
                >
                  <List className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-500" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search questions and answers..."
                className="w-full pl-10 pr-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-600"
              />
            </div>

            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="px-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-blue-600"
            >
              <option value="all">All Categories</option>
              {uniqueCategories.map(cat => (
                <option key={cat} value={cat}>{cat}</option>
              ))}
            </select>

            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as SortOption)}
              className="px-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-blue-600"
            >
              <option value="newest">Newest First</option>
              <option value="oldest">Oldest First</option>
              <option value="alphabetical">Alphabetical</option>
              <option value="expiring">Expiring Soonest</option>
              <option value="expired">Expired First</option>
            </select>
          </div>
        </div>

        {selectedIds.size > 0 && (
          <div className="bg-blue-900/20 border border-blue-600 rounded-lg p-4 mb-6 flex items-center justify-between">
            <div className="text-white font-medium">{selectedIds.size} selected</div>
            <div className="flex space-x-3">
              <button
                onClick={() => setShowBulkCategorizeModal(true)}
                className="flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
              >
                <Tag className="h-4 w-4 mr-2" />
                Categorize Selected
              </button>
              <button
                onClick={handleBulkDelete}
                className="flex items-center px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg transition-colors"
              >
                <Trash2 className="h-4 w-4 mr-2" />
                Delete Selected
              </button>
            </div>
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
          </div>
        ) : filteredAndSortedEntries.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 bg-gray-900 rounded-lg border border-gray-800">
            <BookOpen className="h-16 w-16 text-gray-700 mb-4" />
            <h3 className="text-xl font-semibold text-white mb-2">No entries found</h3>
            <p className="text-gray-400 mb-6">
              {entries.length === 0 ? "Create Q&A entries for your AI assistants" : "Try adjusting your filters"}
            </p>
            {entries.length === 0 && (
              <button 
                onClick={() => setShowAddModal(true)}
                className="flex items-center px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg"
              >
                <Plus className="h-5 w-5 mr-2" />
                Add Entry
              </button>
            )}
          </div>
        ) : view === "grid" ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredAndSortedEntries.map((entry) => (
              <div key={entry.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4 hover:border-gray-700 relative">
                <input
                  type="checkbox"
                  checked={selectedIds.has(entry.id)}
                  onChange={() => toggleSelection(entry.id)}
                  className="absolute top-4 left-4 w-4 h-4 text-blue-600 bg-gray-800 border-gray-700 rounded cursor-pointer"
                />
                <div className="ml-8">
                  {entry.is_expired && (
                    <div className="flex items-center text-orange-500 text-sm mb-2">
                      <AlertCircle className="h-4 w-4 mr-1" />
                      Expired
                    </div>
                  )}
                  <div className="mb-3">
                    <div className="text-sm font-semibold text-blue-600 mb-1">Q:</div>
                    <div className="text-white font-medium">{entry.question}</div>
                  </div>
                  <div className="mb-3">
                    <div className="text-sm font-semibold text-green-600 mb-1">A:</div>
                    <div className="text-gray-400 text-sm line-clamp-3">{entry.answer}</div>
                  </div>
                  <div className="flex items-center justify-between text-xs text-gray-500 mt-3 pt-3 border-t border-gray-800">
                    <div>
                      {entry.category && <span className="bg-gray-800 px-2 py-1 rounded">{entry.category}</span>}
                    </div>
                    <div className="flex space-x-2">
                      <button onClick={() => { setEditEntry(entry); setShowAddModal(true); }} className="p-1 hover:text-white">
                        <Pencil className="h-4 w-4" />
                      </button>
                      <button onClick={() => handleDelete(entry.id)} className="p-1 hover:text-red-400">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-800 border-b border-gray-700">
                <tr>
                  <th className="w-10 px-6 py-3">
                    <input
                      type="checkbox"
                      checked={selectedIds.size === filteredAndSortedEntries.length && filteredAndSortedEntries.length > 0}
                      onChange={toggleSelectAll}
                      className="w-4 h-4 text-blue-600 bg-gray-800 border-gray-700 rounded cursor-pointer"
                    />
                  </th>
                  <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Question</th>
                  <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Answer</th>
                  <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Category</th>
                  <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Expires</th>
                  <th className="text-right px-6 py-3 text-xs font-medium text-gray-400 uppercase">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {filteredAndSortedEntries.map((entry) => (
                  <tr key={entry.id} className={entry.is_expired ? "bg-orange-900/10" : ""}>
                    <td className="px-6 py-4">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(entry.id)}
                        onChange={() => toggleSelection(entry.id)}
                        className="w-4 h-4 text-blue-600 bg-gray-800 border-gray-700 rounded cursor-pointer"
                      />
                    </td>
                    <td className="px-6 py-4 text-white">{entry.question}</td>
                    <td className="px-6 py-4 text-gray-400 max-w-md truncate">{entry.answer}</td>
                    <td className="px-6 py-4 text-gray-400">{entry.category || "-"}</td>
                    <td className="px-6 py-4 text-gray-400 text-sm">{entry.expiration_date || "-"}</td>
                    <td className="px-6 py-4 text-right space-x-2">
                      <button onClick={() => { setEditEntry(entry); setShowAddModal(true); }} className="text-gray-400 hover:text-white">
                        <Pencil className="h-4 w-4 inline" />
                      </button>
                      <button onClick={() => handleDelete(entry.id)} className="text-gray-400 hover:text-red-400">
                        <Trash2 className="h-4 w-4 inline" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {showAddModal && <AddEntryModal entry={editEntry} categories={uniqueCategories} onClose={() => { setShowAddModal(false); setEditEntry(null); }} onSaved={() => { setShowAddModal(false); setEditEntry(null); fetchEntries(); }} />}
        {showCSVModal && <CSVModal onClose={() => setShowCSVModal(false)} onUploaded={() => { setShowCSVModal(false); fetchEntries(); }} />}
        {showBulkCategorizeModal && <BulkCategorizeModal categories={uniqueCategories} onClose={() => setShowBulkCategorizeModal(false)} onSubmit={handleBulkCategorize} />}
      </div>
    </div>
  );
}

function AddEntryModal({ entry, categories, onClose, onSaved }: any) {
  const [question, setQuestion] = useState(entry?.question || "");
  const [answer, setAnswer] = useState(entry?.answer || "");
  const [category, setCategory] = useState(entry?.category || "");
  const [expiration, setExpiration] = useState(entry?.expiration_date || "");
  const [loading, setLoading] = useState(false);

  const handleSave = async () => {
    if (!question.trim() || !answer.trim()) {
      alert("Question and answer are required");
      return;
    }

    setLoading(true);
    try {
      const url = entry ? `/api/entries/${entry.id}` : `/api/entries`;
      
      const res = await fetch(url, {
        method: entry ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          hotel_id: HOTEL_ID,
          question: question.trim(),
          answer: answer.trim(),
          category: category.trim() || null,
          expiration_date: expiration || null
        })
      });

      if (res.ok) onSaved();
      else alert("Failed to save entry");
    } catch (error) {
      console.error("Save failed:", error);
      alert("Failed to save entry");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-gray-900 rounded-lg w-full max-w-2xl p-6" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-white">{entry ? "Edit Entry" : "Add Entry"}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white"><X className="h-6 w-6" /></button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-2">Question *</label>
            <textarea value={question} onChange={e => setQuestion(e.target.value)} rows={2} className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white resize-none" placeholder="What time is checkout?" />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-400 mb-2">Answer *</label>
            <textarea value={answer} onChange={e => setAnswer(e.target.value)} rows={4} className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white resize-none" placeholder="Checkout is at 11:00 AM" />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-2">Category</label>
              <input 
                value={category} 
                onChange={e => setCategory(e.target.value)} 
                list="entry-categories"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white" 
                placeholder="Select or type a category" 
              />
              <datalist id="entry-categories">
                {categories.map((cat: string) => (
                  <option key={cat} value={cat} />
                ))}
              </datalist>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-400 mb-2">Expiration Date</label>
              <input type="date" value={expiration} onChange={e => setExpiration(e.target.value)} className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white" />
            </div>
          </div>

          <div className="flex space-x-3 pt-4">
            <button onClick={handleSave} disabled={loading} className="flex-1 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg disabled:opacity-50">
              {loading ? "Saving..." : entry ? "Save Changes" : "Create Entry"}
            </button>
            <button onClick={onClose} className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg">Cancel</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function CSVModal({ onClose, onUploaded }: any) {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);

  const handleUpload = async () => {
    if (!file) {
      alert("Please select a CSV file");
      return;
    }

    setLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(`/api/entries/import-csv?hotel_id=${HOTEL_ID}`, {
        method: "POST",
        body: formData
      });

      const data = await res.json();
      if (res.ok) {
        alert(`Imported ${data.created} entries${data.errors > 0 ? `, ${data.errors} errors` : ""}`);
        onUploaded();
      } else {
        alert("Failed to import CSV");
      }
    } catch (error) {
      console.error("Upload failed:", error);
      alert("Failed to upload CSV");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-gray-900 rounded-lg w-full max-w-xl p-6" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-white">Import CSV</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white"><X className="h-6 w-6" /></button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-2">CSV File *</label>
            <input type="file" accept=".csv" onChange={e => setFile(e.target.files?.[0] || null)} className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white file:mr-4 file:py-2 file:px-4 file:rounded file:border-0 file:bg-blue-600 file:text-white hover:file:bg-blue-700" />
          </div>

          <div className="bg-gray-800 rounded-lg p-4 text-sm text-gray-400">
            <strong>Required columns:</strong> question, answer<br />
            <strong>Optional columns:</strong> category, expiration_date (YYYY-MM-DD)
          </div>

          <div className="flex space-x-3 pt-4">
            <button onClick={handleUpload} disabled={loading} className="flex-1 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg disabled:opacity-50">
              {loading ? "Importing..." : "Import CSV"}
            </button>
            <button onClick={onClose} className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg">Cancel</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function BulkCategorizeModal({ categories, onClose, onSubmit }: any) {
  const [category, setCategory] = useState("");

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-gray-900 rounded-lg w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-white">Categorize Selected</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white"><X className="h-6 w-6" /></button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-2">Category</label>
            <input
              value={category}
              onChange={e => setCategory(e.target.value)}
              list="categories"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white"
              placeholder="Enter or select category"
            />
            <datalist id="categories">
              {categories.map((cat: string) => <option key={cat} value={cat} />)}
            </datalist>
          </div>

          <div className="flex space-x-3 pt-4">
            <button onClick={() => onSubmit(category.trim() || null)} className="flex-1 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg">
              Apply Category
            </button>
            <button onClick={onClose} className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg">Cancel</button>
          </div>
        </div>
      </div>
    </div>
  );
}
