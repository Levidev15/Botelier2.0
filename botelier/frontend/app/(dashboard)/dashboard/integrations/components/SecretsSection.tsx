"use client";

import { KeyRound, Plus, Pencil, Trash2 } from "lucide-react";
import type { AccountSecret } from "../types";

interface SecretsSectionProps {
  secrets: AccountSecret[];
  onCreateSecret: () => void;
  onEditSecret: (secret: AccountSecret) => void;
  onDeleteSecret: (secret: AccountSecret) => void;
}

export default function SecretsSection({ secrets, onCreateSecret, onEditSecret, onDeleteSecret }: SecretsSectionProps) {
  return (
    <div className="mt-10">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <KeyRound className="h-5 w-5" />
            Secrets
          </h2>
          <p className="text-sm text-gray-400 mt-1">
            Encrypted API keys and credentials — reference them in flows as{" "}
            <code className="text-xs bg-gray-800 px-1.5 py-0.5 rounded font-mono">{"{{secrets.key_name}}"}</code>
          </p>
        </div>
        <button
          onClick={onCreateSecret}
          className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition"
        >
          <Plus className="h-4 w-4 mr-2" />
          Add Secret
        </button>
      </div>

      {secrets.length === 0 ? (
        <div className="bg-[#141414] border border-gray-800 rounded-lg p-12 text-center">
          <KeyRound className="h-12 w-12 text-gray-600 mx-auto mb-4" />
          <p className="text-gray-400 mb-2">No secrets stored yet</p>
          <p className="text-sm text-gray-500">
            Store API keys here and reference them in flows with{" "}
            <span className="font-mono text-xs">{"{{secrets.key_name}}"}</span>
          </p>
        </div>
      ) : (
        <div className="bg-[#141414] border border-gray-800 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-left text-xs text-gray-500 uppercase tracking-wider">
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Key</th>
                <th className="px-4 py-3">Description</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {secrets.map((secret) => (
                <tr key={secret.id} className="hover:bg-gray-800/30 transition">
                  <td className="px-4 py-3 font-medium">{secret.name}</td>
                  <td className="px-4 py-3">
                    <code className="text-xs bg-gray-800 px-1.5 py-0.5 rounded font-mono text-blue-300">
                      {`{{secrets.${secret.key}}}`}
                    </code>
                  </td>
                  <td className="px-4 py-3 text-gray-400">{secret.description || "—"}</td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {new Date(secret.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        onClick={() => onEditSecret(secret)}
                        className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition"
                        title="Edit secret"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() => onDeleteSecret(secret)}
                        className="p-1.5 text-gray-400 hover:text-red-400 hover:bg-gray-700 rounded-lg transition"
                        title="Delete secret"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
