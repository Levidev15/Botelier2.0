"use client";

import { useState, useEffect } from "react";
import { BookOpen, Plus, Grid3x3, List, Upload, Filter, Pencil, Trash2, AlertCircle } from "lucide-react";

const HOTEL_ID = "6b410bcc-f843-40df-b32d-078d3e01ac7f";

interface Entry {
  id: string;
  knowledge_base_id: string;
  question: string;
  answer: string;
  category: string | null;
  expiration_date: string | null;
  is_expired: boolean;
  created_at: string;
}

interface KB {
  id: string;
  name: string;
  entry_count: number;
}

export default function KnowledgeBasesPage() {
  const [view, setView] = useState<"grid" | "table">("grid");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [kbs, setKbs] = useState<KB[]>([]);
  const [loading, setLoading] = useState(true);
  const [showExpired, setShowExpired] = useState(false);

  useEffect(() => {
    fetchData();
  }, [showExpired]);

  const fetchData = async () => {
    try {
      setLoading(true);
      const kbRes = await fetch(`/api/knowledge-bases?hotel_id=${HOTEL_ID}`);
      const kbData = await kbRes.json();
      setKbs(kbData.knowledge_bases || []);

      const allEntries: Entry[] = [];
      for (const kb of (kbData.knowledge_bases || [])) {
        const entryRes = await fetch(`/api/knowledge-bases/${kb.id}/entries?include_expired=${showExpired}`);
        const entryData = await entryRes.json();
        allEntries.push(...(entryData.entries || []));
      }
      setEntries(allEntries);
    } catch (error) {
      console.error("Failed to fetch data:", error);
    } finally {
      setLoading(false);
    }
  };

  const getKBName = (kb_id: string) => {
    return kbs.find((k) => k.id === kb_id)?.name || "Unknown";
  };

  const activeCount = entries.filter((e) => !e.is_expired).length;
  const expiredCount = entries.filter((e) => e.is_expired).length;

  return (
    <div className="flex-1 overflow-auto bg-[#0a0a0a]">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-white mb-2 flex items-center">
              <BookOpen className="h-8 w-8 mr-3 text-blue-600" />
              Knowledge Base Entries
            </h1>
            <p className="text-gray-400">Manage Q&A entries for AI assistants</p>
          </div>
          <div className="flex space-x-3">
            <button className="flex items-center px-4 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg transition-colors">
              <Upload className="h-4 w-4 mr-2" />
              Import CSV
            </button>
            <button className="flex items-center px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors">
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
                  className="w-4 h-4 text-blue-600 bg-gray-800 border-gray-700 rounded focus:ring-blue-600"
                />
                <span className="text-sm text-gray-400">Show Expired</span>
              </label>

              <div className="flex bg-gray-800 rounded-lg p-1">
                <button
                  onClick={() => setView("grid")}
                  className={`p-2 rounded ${view === "grid" ? "bg-blue-600 text-white" : "text-gray-400 hover:text-white"}`}
                >
                  <Grid3x3 className="h-4 w-4" />
                </button>
                <button
                  onClick={() => setView("table")}
                  className={`p-2 rounded ${view === "table" ? "bg-blue-600 text-white" : "text-gray-400 hover:text-white"}`}
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
          </div>
        ) : view === "grid" ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {entries.map((entry) => (
              <div key={entry.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4 hover:border-gray-700 transition-colors">
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
                    <span className="ml-2">{getKBName(entry.knowledge_base_id)}</span>
                  </div>
                  <div className="flex space-x-2">
                    <button className="p-1 hover:text-white"><Pencil className="h-4 w-4" /></button>
                    <button className="p-1 hover:text-red-400"><Trash2 className="h-4 w-4" /></button>
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
                  <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">KB</th>
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
                    <td className="px-6 py-4 text-gray-500 text-sm">{getKBName(entry.knowledge_base_id)}</td>
                    <td className="px-6 py-4 text-gray-400 text-sm">{entry.expiration_date || "-"}</td>
                    <td className="px-6 py-4 text-right space-x-2">
                      <button className="text-gray-400 hover:text-white"><Pencil className="h-4 w-4 inline" /></button>
                      <button className="text-gray-400 hover:text-red-400"><Trash2 className="h-4 w-4 inline" /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
