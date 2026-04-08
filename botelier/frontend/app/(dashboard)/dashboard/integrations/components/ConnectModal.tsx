"use client";

import { useState } from "react";
import { Loader2, X, AlertCircle, ExternalLink } from "lucide-react";
import type { IntegrationType } from "../types";

interface ConnectModalProps {
  selectedType: IntegrationType;
  accountId: string;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
  onSuccess: () => void;
  onNotify: (type: "success" | "error", message: string) => void;
  onClose: () => void;
}

export default function ConnectModal({
  selectedType,
  accountId,
  authFetch,
  onSuccess,
  onNotify,
  onClose,
}: ConnectModalProps) {
  const [credentials, setCredentials] = useState<Record<string, string>>(() => {
    const defaults: Record<string, string> = {};
    selectedType.required_fields.forEach((field) => {
      if (field.type === "select" && field.options && field.options.length > 0) {
        defaults[field.key] = field.options[0];
      }
    });
    return defaults;
  });
  const [connectError, setConnectError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);

  const handleSubmitConnect = async () => {
    setConnectError(null);

    if (!credentials["_connection_name"]?.trim()) {
      setConnectError("Please enter a connection name");
      return;
    }

    const visibleFields = selectedType.required_fields.filter((field) => {
      if (!field.show_when) return true;
      return Object.entries(field.show_when).every(
        ([key, value]) => (credentials[key] || selectedType.required_fields.find((f) => f.key === key)?.options?.[0]) === value
      );
    });

    const missingFields = visibleFields.filter((f) => f.required && !credentials[f.key]).map((f) => f.label);
    if (missingFields.length > 0) {
      setConnectError(`Missing required fields: ${missingFields.join(", ")}`);
      return;
    }

    setConnecting(true);
    const { _connection_name, ...apiCredentials } = credentials;

    try {
      const response = await authFetch(`/api/integrations/account/${accountId}/connect`, {
        method: "POST",
        body: JSON.stringify({
          integration_type_id: selectedType.id,
          credentials: apiCredentials,
          connection_name: _connection_name,
        }),
      });

      const result = await response.json();

      if (result.status === "connected") {
        onSuccess();
        onNotify("success", `${_connection_name} connected successfully`);
        onClose();
      } else if (result.status === "error" || result.last_error) {
        setConnectError(result.last_error || "Connection failed — check your credentials and try again");
        onSuccess();
      } else if (result.detail) {
        setConnectError(result.detail);
      } else {
        setConnectError("Connection failed — an unexpected error occurred");
      }
    } catch (error: any) {
      setConnectError(error?.message || "Connection failed — please check your network and try again");
    } finally {
      setConnecting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-[#1a1a1a] border border-gray-800 rounded-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-gray-800">
          <h2 className="text-lg font-semibold">Connect {selectedType.name}</h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-800 rounded-lg transition">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          <p className="text-sm text-gray-400">
            Enter your credentials to connect to {selectedType.name}.{" "}
            Your credentials are encrypted and stored securely.
          </p>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Connection Name <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              placeholder={`e.g., ${selectedType.name} - Hotel Name`}
              value={credentials["_connection_name"] || ""}
              onChange={(e) => setCredentials((prev) => ({ ...prev, _connection_name: e.target.value }))}
              className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
            />
            <p className="text-xs text-gray-500 mt-1">A label to identify this connection (e.g., hotel or property name)</p>
          </div>

          {selectedType.required_fields.map((field) => {
            if (field.show_when) {
              const shouldShow = Object.entries(field.show_when).every(
                ([key, value]) => (credentials[key] || selectedType.required_fields.find((f) => f.key === key)?.options?.[0]) === value
              );
              if (!shouldShow) return null;
            }
            return (
              <div key={field.key}>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  {field.label}
                  {field.required && <span className="text-red-400 ml-1">*</span>}
                </label>
                {field.type === "select" && field.options ? (
                  <select
                    value={credentials[field.key] || field.options[0] || ""}
                    onChange={(e) => setCredentials((prev) => ({ ...prev, [field.key]: e.target.value }))}
                    className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                  >
                    {field.options.map((opt) => (
                      <option key={opt} value={opt}>
                        {field.option_labels?.[opt] || opt.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={field.type === "password" ? "password" : "text"}
                    placeholder={field.placeholder}
                    value={credentials[field.key] || ""}
                    onChange={(e) => setCredentials((prev) => ({ ...prev, [field.key]: e.target.value }))}
                    className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                  />
                )}
                {field.description && <p className="text-xs text-gray-500 mt-1">{field.description}</p>}
              </div>
            );
          })}

          {connectError && (
            <div className="flex items-start gap-2 p-3 bg-red-900/30 border border-red-800 rounded-lg">
              <AlertCircle className="h-4 w-4 text-red-400 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-red-300">{connectError}</p>
            </div>
          )}

          {selectedType.documentation_url && (
            <a href={selectedType.documentation_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center text-sm text-blue-400 hover:text-blue-300">
              Need help finding your credentials?
              <ExternalLink className="h-3 w-3 ml-1" />
            </a>
          )}
        </div>

        <div className="flex items-center justify-end gap-3 p-4 border-t border-gray-800">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-gray-300 hover:text-white transition">
            Cancel
          </button>
          <button
            onClick={handleSubmitConnect}
            disabled={connecting}
            className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition disabled:opacity-50"
          >
            {connecting ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Connecting...
              </>
            ) : (
              "Connect Integration"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
