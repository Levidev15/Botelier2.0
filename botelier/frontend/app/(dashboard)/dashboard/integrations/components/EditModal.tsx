"use client";

import { useState, useEffect } from "react";
import { Loader2, X, AlertCircle, Pencil } from "lucide-react";
import type { IntegrationType, AccountIntegration } from "../types";

interface EditModalProps {
  conn: AccountIntegration;
  selectedType: IntegrationType;
  accountId: string;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
  onSuccess: () => void;
  onNotify: (type: "success" | "error", message: string) => void;
  onClose: () => void;
}

export default function EditModal({
  conn,
  selectedType,
  accountId,
  authFetch,
  onSuccess,
  onNotify,
  onClose,
}: EditModalProps) {
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [connectionName, setConnectionName] = useState(conn.connection_name || "");
  const [loadingCreds, setLoadingCreds] = useState(true);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const fetchCredentials = async () => {
      try {
        const res = await authFetch(
          `/api/integrations/account/${accountId}/integration/${conn.id}/credentials`
        );
        if (res.ok) {
          const data = await res.json();
          setCredentials(data.credentials || {});
          if (data.connection_name) setConnectionName(data.connection_name);
        }
      } catch {
        // Non-fatal — user can still type values manually
      } finally {
        setLoadingCreds(false);
      }
    };
    fetchCredentials();
  }, [conn.id, accountId]);

  const handleSave = async () => {
    setSaveError(null);

    if (!connectionName.trim()) {
      setSaveError("Please enter a connection name");
      return;
    }

    setSaving(true);
    try {
      const response = await authFetch(
        `/api/integrations/account/${accountId}/integration/${conn.id}/credentials`,
        {
          method: "PATCH",
          body: JSON.stringify({
            credentials,
            connection_name: connectionName,
          }),
        }
      );

      const result = await response.json();

      if (result.status === "connected") {
        onSuccess();
        onNotify("success", `${connectionName} updated and reconnected successfully`);
        onClose();
      } else if (result.status === "error" || result.last_error) {
        setSaveError(result.last_error || "Connection failed — check your credentials and try again");
        onSuccess();
      } else if (result.detail) {
        setSaveError(result.detail);
      } else {
        setSaveError("Update failed — an unexpected error occurred");
      }
    } catch (error: any) {
      setSaveError(error?.message || "Update failed — please check your network and try again");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-[#1a1a1a] border border-gray-800 rounded-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-gray-800">
          <div className="flex items-center gap-2">
            <Pencil className="h-4 w-4 text-gray-400" />
            <h2 className="text-lg font-semibold">Edit {selectedType.name}</h2>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-gray-800 rounded-lg transition">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          <p className="text-sm text-gray-400">
            Update your credentials. Password fields can be left blank to keep the current stored value.
          </p>

          {loadingCreds ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
            </div>
          ) : (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  Connection Name <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  value={connectionName}
                  onChange={(e) => setConnectionName(e.target.value)}
                  className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                />
              </div>

              {selectedType.required_fields.map((field) => {
                if (field.show_when) {
                  const shouldShow = Object.entries(field.show_when).every(
                    ([key, value]) =>
                      (credentials[key] ||
                        selectedType.required_fields.find((f) => f.key === key)?.options?.[0]) === value
                  );
                  if (!shouldShow) return null;
                }

                const isPassword = field.type === "password";

                return (
                  <div key={field.key}>
                    <label className="block text-sm font-medium text-gray-300 mb-1">
                      {field.label}
                      {field.required && <span className="text-red-400 ml-1">*</span>}
                    </label>
                    {field.type === "select" && field.options ? (
                      <select
                        value={credentials[field.key] || field.options[0] || ""}
                        onChange={(e) =>
                          setCredentials((prev) => ({ ...prev, [field.key]: e.target.value }))
                        }
                        className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                      >
                        {field.options.map((opt) => (
                          <option key={opt} value={opt}>
                            {field.option_labels?.[opt] ||
                              opt.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type={isPassword ? "password" : "text"}
                        placeholder={
                          isPassword
                            ? "Leave blank to keep current value"
                            : field.placeholder
                        }
                        value={credentials[field.key] || ""}
                        onChange={(e) =>
                          setCredentials((prev) => ({ ...prev, [field.key]: e.target.value }))
                        }
                        className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                      />
                    )}
                    {field.description && (
                      <p className="text-xs text-gray-500 mt-1">{field.description}</p>
                    )}
                  </div>
                );
              })}
            </>
          )}

          {saveError && (
            <div className="flex items-start gap-2 p-3 bg-red-900/30 border border-red-800 rounded-lg">
              <AlertCircle className="h-4 w-4 text-red-400 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-red-300">{saveError}</p>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-3 p-4 border-t border-gray-800">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-300 hover:text-white transition"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || loadingCreds}
            className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition disabled:opacity-50"
          >
            {saving ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Saving...
              </>
            ) : (
              "Save & Reconnect"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
