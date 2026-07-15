"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Loader2, Plus, Sparkles, X } from "lucide-react";
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
  const { updateNodeData, variables } = useFlowStore();
  const { authFetch } = useAuthToken();

  const api: APIRequestConfig =
    data.api || { method: "GET", url: "", apiSource: "capability", capability: "" };

  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showResponseMapping, setShowResponseMapping] = useState(
    !!(api.responseMapping && Object.keys(api.responseMapping).length > 0)
  );

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

  const responseMappingEntries = Object.entries(api.responseMapping || {});

  const addResponseMapping = () => {
    updateApi({ responseMapping: { ...(api.responseMapping || {}), "": "" } });
  };

  const updateResponseMapping = (oldKey: string, newKey: string, value: string, index: number) => {
    const entries = Object.entries(api.responseMapping || {});
    const newMapping: Record<string, string> = {};
    entries.forEach(([k, v], i) => {
      if (i === index) {
        newMapping[newKey] = value;
      } else {
        newMapping[k] = v;
      }
    });
    updateApi({ responseMapping: newMapping });
  };

  const removeResponseMapping = (index: number) => {
    const entries = Object.entries(api.responseMapping || {});
    const newMapping: Record<string, string> = {};
    entries.forEach(([k, v], i) => {
      if (i !== index) newMapping[k] = v;
    });
    updateApi({ responseMapping: newMapping });
  };

  const smallInputCls =
    "flex-1 bg-[#1a1a1a] border border-gray-700 rounded px-2 py-1 text-white text-xs focus:border-purple-500 focus:outline-none font-mono";

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
        <button
          onClick={() => setShowResponseMapping(!showResponseMapping)}
          className="flex items-center gap-2 text-sm font-medium text-gray-300"
        >
          {showResponseMapping ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
          Response Mapping
          {responseMappingEntries.length > 0 && (
            <span className="text-xs text-gray-500">({responseMappingEntries.length})</span>
          )}
        </button>

        {showResponseMapping && (
          <div className="mt-2 space-y-2">
            <div className="rounded bg-gray-900 border border-gray-800 px-3 py-2 text-xs text-gray-400">
              Capture fields from the capability&apos;s returned data into flow variables.
              Use JSONPath (e.g.{" "}
              <code className="text-purple-400">$.items[0].confirmation_number</code>) or dot
              notation (e.g. <code className="text-purple-400">items.0.rate</code>).
              Mapped variables are available to downstream nodes and{" "}
              <code className="text-purple-400">{"{{variable}}"}</code> references.
            </div>
            {responseMappingEntries.map(([key, path], i) => (
              <div key={i} className="flex gap-2 items-center">
                <input
                  type="text"
                  value={key}
                  onChange={(e) => updateResponseMapping(key, e.target.value, path, i)}
                  className={smallInputCls}
                  placeholder="variable_name"
                />
                <span className="text-gray-500 text-xs">=</span>
                <input
                  type="text"
                  value={path}
                  onChange={(e) => updateResponseMapping(key, key, e.target.value, i)}
                  className={`${smallInputCls} flex-1`}
                  placeholder="$.items[0].confirmation_number"
                />
                <button
                  onClick={() => removeResponseMapping(i)}
                  className="text-red-400 hover:text-red-300 p-1"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
            <button
              onClick={addResponseMapping}
              className="text-xs text-purple-400 hover:text-purple-300 flex items-center gap-1"
            >
              <Plus className="h-3 w-3" /> Add Mapping
            </button>

            {variables.length > 0 && responseMappingEntries.length > 0 && (
              <p className="text-[11px] text-gray-600">
                Existing flow variables:{" "}
                {variables
                  .filter((v) => v.key)
                  .map((v) => v.key)
                  .join(", ")}
              </p>
            )}
          </div>
        )}
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
          placeholder={
            responseMappingEntries.length > 0
              ? "How should the AI present the result? Use {{variable_name}} to embed mapped values."
              : "How should the AI present the result to the caller?"
          }
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-purple-500 focus:outline-none resize-none"
        />
        {responseMappingEntries.length > 0 && (
          <p className="text-xs text-gray-500 mt-1">
            Use <code className="text-purple-400">{"{{variable_name}}"}</code> to embed
            mapped values — e.g.,{" "}
            <code className="text-purple-400">
              {`Confirmation number: {{${responseMappingEntries.find(([k]) => k)?.[0] || "confirmation_number"}}}`}
            </code>
          </p>
        )}
      </div>
    </div>
  );
}
