"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { notify } from "@/lib/notifications";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import type { KnowledgeBase } from "../types";

interface KBModalProps {
  kb: KnowledgeBase | null;
  accountId: string;
  onClose: () => void;
  onSave: () => void;
}

export default function KBModal({ kb, accountId, onClose, onSave }: KBModalProps) {
  const { authFetch } = useAuthToken();
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

      const res = await authFetch(url, {
        method,
        body: JSON.stringify(body),
      });

      if (res.ok) {
        notify.success(kb ? "Knowledge base updated" : "Knowledge base created");
        onSave();
      } else {
        notify.error("Failed to save knowledge base");
      }
    } catch {
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
