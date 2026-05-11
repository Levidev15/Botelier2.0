"use client";

import { useState } from "react";
import { X, Globe, Loader2 } from "lucide-react";
import { notify } from "@/lib/notifications";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface ImportURLModalProps {
  knowledgeBaseId: string;
  onClose: () => void;
  onImported: (count: number) => void;
}

export default function ImportURLModal({ knowledgeBaseId, onClose, onImported }: ImportURLModalProps) {
  const { authFetch } = useAuthToken();
  const [url, setUrl] = useState("");
  const [maxPages, setMaxPages] = useState(10);
  const [category, setCategory] = useState("");
  const [importing, setImporting] = useState(false);

  const handleImport = async () => {
    const trimmed = url.trim();
    if (!trimmed) {
      notify.error("Please enter a website URL");
      return;
    }
    if (!/^https?:\/\/.+/i.test(trimmed)) {
      notify.error("URL must start with http:// or https://");
      return;
    }

    try {
      setImporting(true);
      const res = await authFetch(`/api/knowledge-bases/${knowledgeBaseId}/import-url`, {
        method: "POST",
        body: JSON.stringify({
          url: trimmed,
          max_pages: maxPages,
          category: category.trim() || null,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        notify.error(err.detail || "Import failed");
        return;
      }

      const data = await res.json();
      const created = data.entries_created ?? 0;
      const pages = data.pages_crawled ?? 0;
      notify.success(`Imported ${created} Q&A entries from ${pages} page${pages !== 1 ? "s" : ""}`);
      onImported(created);
    } catch {
      notify.error("Import failed — check the URL and try again");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-[#1A1A1A] border border-white/10 rounded-xl w-full max-w-lg p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-[#3B82F6]/15 flex items-center justify-center">
              <Globe className="w-4 h-4 text-[#3B82F6]" />
            </div>
            <h2 className="text-xl font-semibold text-white">Import from website</h2>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-white/5 rounded">
            <X className="w-5 h-5 text-white/60" />
          </button>
        </div>

        <p className="text-sm text-white/50 mb-6">
          The assistant will crawl the website, extract content, and generate voice-ready Q&amp;A entries automatically.
          Static HTML pages work best — dynamically rendered SPAs may yield less content.
        </p>

        <div className="space-y-4">
          <div>
            <label className="block text-sm text-white/60 mb-2">Website URL *</label>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/products"
              autoFocus
              className="w-full px-4 py-3 bg-[#2A2A2A] border border-white/10 rounded-lg text-white placeholder:text-white/30 focus:outline-none focus:border-[#3B82F6]/50 text-sm"
            />
          </div>

          <div>
            <label className="block text-sm text-white/60 mb-2">
              Max pages to crawl
              <span className="ml-2 text-white/30 font-normal">1–20</span>
            </label>
            <div className="flex items-center gap-4">
              <input
                type="range"
                min={1}
                max={20}
                value={maxPages}
                onChange={(e) => setMaxPages(Number(e.target.value))}
                className="flex-1 accent-[#3B82F6]"
              />
              <span className="text-white font-medium w-6 text-center">{maxPages}</span>
            </div>
            <p className="text-white/30 text-xs mt-1">
              Follows links within the same domain. More pages = more entries but takes longer.
            </p>
          </div>

          <div>
            <label className="block text-sm text-white/60 mb-2">
              Category tag
              <span className="ml-2 text-white/30 font-normal">optional</span>
            </label>
            <input
              type="text"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="e.g., Products, Menu, Policies"
              className="w-full px-4 py-3 bg-[#2A2A2A] border border-white/10 rounded-lg text-white placeholder:text-white/30 focus:outline-none focus:border-[#3B82F6]/50 text-sm"
            />
            <p className="text-white/30 text-xs mt-1">
              All generated entries will be tagged with this category so you can filter or bulk-delete them later.
            </p>
          </div>
        </div>

        {importing && (
          <div className="mt-5 flex items-center gap-3 px-4 py-3 bg-[#3B82F6]/10 border border-[#3B82F6]/20 rounded-lg text-sm text-[#3B82F6]">
            <Loader2 className="w-4 h-4 animate-spin shrink-0" />
            <span>Crawling pages and generating Q&amp;A entries — this may take up to a minute…</span>
          </div>
        )}

        <div className="flex justify-end gap-3 mt-6">
          <button
            onClick={onClose}
            disabled={importing}
            className="px-4 py-2 text-white/60 hover:text-white transition-colors disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            onClick={handleImport}
            disabled={importing || !url.trim()}
            className="flex items-center gap-2 px-5 py-2 bg-[#3B82F6] hover:bg-[#3B82F6]/80 text-black font-medium rounded-lg transition-colors disabled:opacity-50"
          >
            {importing ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Importing…
              </>
            ) : (
              <>
                <Globe className="w-4 h-4" />
                Import
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
