"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { notify } from "@/lib/notifications";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import type { Entry } from "../types";

interface EntryModalProps {
  entry: Entry | null;
  knowledgeBaseId: string;
  onClose: () => void;
  onSave: (saved: Entry) => void;
}

export default function EntryModal({ entry, knowledgeBaseId, onClose, onSave }: EntryModalProps) {
  const { authFetch } = useAuthToken();
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

      const res = await authFetch(url, {
        method,
        body: JSON.stringify({
          question,
          answer,
          category: category || null,
          expiration_date: expirationDate || null,
        }),
      });

      if (res.ok) {
        const saved: Entry = await res.json();
        notify.success(entry ? "Entry updated" : "Entry created");
        onSave(saved);
      } else {
        notify.error("Failed to save entry");
      }
    } catch {
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
