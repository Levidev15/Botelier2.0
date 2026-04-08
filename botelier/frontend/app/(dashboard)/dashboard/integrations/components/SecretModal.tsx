"use client";

import { Loader2, X, Eye, EyeOff } from "lucide-react";
import type { AccountSecret } from "../types";

interface SecretForm {
  name: string;
  key: string;
  description: string;
  value: string;
}

interface SecretModalProps {
  editingSecret: AccountSecret | null;
  secretForm: SecretForm;
  setSecretForm: (fn: (prev: SecretForm) => SecretForm) => void;
  showSecretValue: boolean;
  setShowSecretValue: (fn: (prev: boolean) => boolean) => void;
  handleSaveSecret: () => void;
  savingSecret: boolean;
  onClose: () => void;
}

export default function SecretModal({
  editingSecret,
  secretForm,
  setSecretForm,
  showSecretValue,
  setShowSecretValue,
  handleSaveSecret,
  savingSecret,
  onClose,
}: SecretModalProps) {
  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-[#1a1a1a] border border-gray-800 rounded-xl w-full max-w-md">
        <div className="flex items-center justify-between p-4 border-b border-gray-800">
          <h2 className="text-lg font-semibold">
            {editingSecret ? "Edit Secret" : "Add Secret"}
          </h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-800 rounded-lg transition">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="p-5 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Name <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              placeholder="My API Key"
              value={secretForm.name}
              onChange={(e) => setSecretForm(prev => ({ ...prev, name: e.target.value }))}
              className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Key <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              placeholder="my_api_key"
              value={secretForm.key}
              disabled={!!editingSecret}
              onChange={(e) => setSecretForm(prev => ({ ...prev, key: e.target.value.replace(/[^a-zA-Z0-9_]/g, "_") }))}
              className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm font-mono disabled:opacity-50"
            />
            <p className="text-xs text-gray-500 mt-1">
              Used as <code className="text-blue-400">{`{{secrets.${secretForm.key || "key_name"}}}`}</code> in flows
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Description</label>
            <input
              type="text"
              placeholder="Optional description"
              value={secretForm.description}
              onChange={(e) => setSecretForm(prev => ({ ...prev, description: e.target.value }))}
              className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Value {!editingSecret && <span className="text-red-400">*</span>}
              {editingSecret && <span className="text-gray-500 font-normal"> (leave blank to keep current)</span>}
            </label>
            <div className="relative">
              <input
                type={showSecretValue ? "text" : "password"}
                placeholder="••••••••"
                value={secretForm.value}
                onChange={(e) => setSecretForm(prev => ({ ...prev, value: e.target.value }))}
                className="w-full px-3 py-2 pr-10 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm font-mono"
              />
              <button
                type="button"
                onClick={() => setShowSecretValue(v => !v)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
              >
                {showSecretValue ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>
        </div>
        <div className="flex items-center justify-end gap-3 p-4 border-t border-gray-800">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-300 hover:text-white transition"
          >
            Cancel
          </button>
          <button
            onClick={handleSaveSecret}
            disabled={savingSecret}
            className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition disabled:opacity-50"
          >
            {savingSecret ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
            {editingSecret ? "Update Secret" : "Save Secret"}
          </button>
        </div>
      </div>
    </div>
  );
}
