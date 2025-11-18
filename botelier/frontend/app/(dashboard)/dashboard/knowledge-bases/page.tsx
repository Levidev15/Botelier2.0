"use client";

import { useState, useEffect } from "react";
import { BookOpen, Plus, Grid3x3, List, Upload, Pencil, Trash2, AlertCircle, X } from "lucide-react";

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

export default function KnowledgeBasesPage() {
  const [view, setView] = useState<"grid" | "table">("grid");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  const [showExpired, setShowExpired] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showCSVModal, setShowCSVModal] = useState(false);
  const [editEntry, setEditEntry] = useState<Entry | null>(null);

  useEffect(() => {
    fetchEntries();
  }, [showExpired]);

  const fetchEntries = async () => {
    try {
      setLoading(true);
      const res = await fetch(`/api/entries?hotel_id=${HOTEL_ID}&include_expired=${showExpired}`);
      const data = await res.json();
      setEntries(data.entries || []);
    } catch (error) {
      console.error("Failed to fetch entries:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (entryId: string) => {
    if (!confirm("Delete this entry?")) return;
    try {
      const res = await fetch(`/api/entries/${entryId}`, { method: "DELETE" });
      if (res.ok) fetchEntries();
    } catch (error) {
      console.error("Delete failed:", error);
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
          <div className="flex items-center justify-between">
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
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
          </div>
        ) : entries.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 bg-gray-900 rounded-lg border border-gray-800">
            <BookOpen className="h-16 w-16 text-gray-700 mb-4" />
            <h3 className="text-xl font-semibold text-white mb-2">No entries yet</h3>
            <p className="text-gray-400 mb-6">Create Q&A entries for your AI assistants</p>
            <button 
              onClick={() => setShowAddModal(true)}
              className="flex items-center px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg"
            >
              <Plus className="h-5 w-5 mr-2" />
              Add Entry
            </button>
          </div>
        ) : view === "grid" ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {entries.map((entry) => (
              <div key={entry.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4 hover:border-gray-700">
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
            ))}
          </div>
        ) : (
          <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-800 border-b border-gray-700">
                <tr>
                  <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Question</th>
                  <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Answer</th>
                  <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Category</th>
                  <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Expires</th>
                  <th className="text-right px-6 py-3 text-xs font-medium text-gray-400 uppercase">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {entries.map((entry) => (
                  <tr key={entry.id} className={entry.is_expired ? "bg-orange-900/10" : ""}>
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

        {showAddModal && <AddEntryModal entry={editEntry} onClose={() => { setShowAddModal(false); setEditEntry(null); }} onSaved={() => { setShowAddModal(false); setEditEntry(null); fetchEntries(); }} />}
        {showCSVModal && <CSVModal onClose={() => setShowCSVModal(false)} onUploaded={() => { setShowCSVModal(false); fetchEntries(); }} />}
      </div>
    </div>
  );
}

function AddEntryModal({ entry, onClose, onSaved }: any) {
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
              <input value={category} onChange={e => setCategory(e.target.value)} className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white" placeholder="Front Desk" />
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
