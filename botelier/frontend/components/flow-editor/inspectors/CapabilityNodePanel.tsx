"use client";

import { useEffect, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { useFlowStore, CapabilityNodeData, APIRequestConfig } from "../store";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface CapabilityParam {
  type?: string;
  description?: string;
}

interface Capability {
  name: string;
  description: string;
  parameters: Record<string, CapabilityParam>;
  required: string[];
  mutating: boolean;
  service_backed: boolean;
}

interface Props {
  data: CapabilityNodeData;
  nodeId: string;
}

function prettify(name: string): string {
  return name
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export default function CapabilityNodePanel({ data, nodeId }: Props) {
  const { updateNodeData } = useFlowStore();
  const { authFetch } = useAuthToken();

  const api: APIRequestConfig =
    data.api || { method: "GET", url: "", apiSource: "capability", capability: "" };

  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    const fetchCapabilities = async () => {
      setLoading(true);
      setLoadError(null);
      try {
        const response = await authFetch("/api/capabilities");
        if (response.ok) {
          const resData = await response.json();
          setCapabilities(Array.isArray(resData) ? resData : []);
        } else {
          setLoadError("Failed to load capabilities");
        }
      } catch {
        setLoadError("Failed to load capabilities");
      } finally {
        setLoading(false);
      }
    };
    fetchCapabilities();
  }, [authFetch]);

  const updateApi = (patch: Partial<APIRequestConfig>) => {
    updateNodeData(nodeId, { api: { ...api, ...patch } });
  };

  const selected = capabilities.find((c) => c.name === api.capability);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-purple-400">
        <Sparkles className="h-4 w-4" />
        <span className="text-sm font-medium">Universal Capability</span>
      </div>

      <p className="text-xs text-gray-500">
        The AI calls an abstract capability (e.g. search availability). At runtime
        it resolves to this account&apos;s connected provider for the active
        property — the AI never sees the vendor.
      </p>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Capability
        </label>
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-gray-500 py-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading capabilities...
          </div>
        ) : (
          <select
            value={api.capability || ""}
            onChange={(e) => updateApi({ capability: e.target.value })}
            className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-purple-500 focus:outline-none"
          >
            <option value="">Select a capability...</option>
            {capabilities.map((c) => (
              <option key={c.name} value={c.name}>
                {prettify(c.name)}
              </option>
            ))}
          </select>
        )}
        {loadError && (
          <p className="text-xs text-red-500 mt-1">{loadError}</p>
        )}
      </div>

      {selected && (
        <div className="rounded-lg border border-gray-800 bg-[#1a1a1a] p-3 space-y-2">
          <p className="text-xs text-gray-400">{selected.description}</p>
          <div className="flex flex-wrap gap-1">
            {selected.mutating && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-400 font-medium">
                Write action
              </span>
            )}
            {selected.service_backed && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-900/40 text-blue-400 font-medium">
                Managed service
              </span>
            )}
          </div>

          <div>
            <div className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">
              Parameters
            </div>
            {Object.keys(selected.parameters).length === 0 ? (
              <p className="text-xs text-gray-500">No parameters.</p>
            ) : (
              <ul className="space-y-1">
                {Object.entries(selected.parameters).map(([key, param]) => (
                  <li key={key} className="text-xs text-gray-400">
                    <span className="font-mono text-purple-300">{key}</span>
                    {selected.required.includes(key) && (
                      <span className="text-red-500 ml-1">*</span>
                    )}
                    {param.description && (
                      <span className="text-gray-500"> — {param.description}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <p className="text-[11px] text-gray-600 mt-2">
              Parameters are filled automatically from matching flow variables
              (by name). Collect them earlier in the flow.
            </p>
          </div>
        </div>
      )}

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Thinking Message
          <span className="text-xs text-gray-500 ml-2">(optional)</span>
        </label>
        <input
          type="text"
          value={api.thinkingMessage || ""}
          onChange={(e) => updateApi({ thinkingMessage: e.target.value })}
          placeholder="e.g., Let me check that for you..."
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-purple-500 focus:outline-none"
        />
        <p className="text-xs text-gray-500 mt-1">
          Spoken while the capability runs.
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Response Instructions
          <span className="text-xs text-gray-500 ml-2">(optional)</span>
        </label>
        <textarea
          value={api.responseInstructions || ""}
          onChange={(e) => updateApi({ responseInstructions: e.target.value })}
          rows={3}
          placeholder="How should the AI present the result to the caller?"
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-purple-500 focus:outline-none resize-none"
        />
      </div>
    </div>
  );
}
