"use client";

import { useState, useEffect } from "react";
import { ChevronDown, ChevronRight, Plus, X } from "lucide-react";
import { useFlowStore, APIRequestNodeData } from "../store";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import APIRequestHeadersSection from "./APIRequestHeadersSection";

interface APIAccountIntegration {
  id: string;
  integration_type_id: string;
  integration_type: {
    id: string;
    name: string;
    slug: string;
    endpoints: Array<{
      id: string;
      name: string;
      method: string;
      path: string;
      description?: string;
      request_schema?: Record<string, unknown>;
      response_schema?: Record<string, unknown>;
    }>;
  };
  status: string;
}

interface Props {
  data: APIRequestNodeData;
  nodeId: string;
}

export default function APIRequestNodePanel({ data, nodeId }: Props) {
  const { updateNodeData, variables } = useFlowStore();
  const { authFetch } = useAuthToken();
  const { accountId } = useAccountContext();
  const api = data.api || { method: "GET" as const, url: "", apiSource: "custom" as const };
  const [showHeaders, setShowHeaders] = useState(
    !!(api.headers && Object.keys(api.headers).length > 0)
  );
  const [showResponseMapping, setShowResponseMapping] = useState(
    !!(api.responseMapping && Object.keys(api.responseMapping).length > 0)
  );
  const [integrations, setIntegrations] = useState<APIAccountIntegration[]>([]);
  const [loadingIntegrations, setLoadingIntegrations] = useState(false);
  const [availableSecrets, setAvailableSecrets] = useState<Array<{ key: string; name: string }>>([]);
  const [secretPickerIndex, setSecretPickerIndex] = useState<number | null>(null);

  useEffect(() => {
    const fetchIntegrations = async () => {
      setLoadingIntegrations(true);
      try {
        const response = await authFetch("/api/integrations/connections");
        if (response.ok) {
          const resData = await response.json();
          setIntegrations(resData.filter((i: APIAccountIntegration) => i.status === "active"));
        }
      } catch (error) {
        console.error("Failed to fetch integrations:", error);
      } finally {
        setLoadingIntegrations(false);
      }
    };
    const fetchSecrets = async () => {
      if (!accountId) return;
      try {
        const response = await authFetch(`/api/secrets/account/${accountId}`);
        if (response.ok) {
          const resData = await response.json();
          setAvailableSecrets(resData.map((s: { key: string; name: string }) => ({ key: s.key, name: s.name })));
        }
      } catch {
        // non-fatal
      }
    };
    fetchIntegrations();
    fetchSecrets();
  }, [accountId]);

  const updateApi = (updates: Partial<typeof api>) => {
    updateNodeData(nodeId, { api: { ...api, ...updates } });
  };

  const selectedIntegration = integrations.find(i => i.id === api.integrationId);
  const selectedEndpoint = selectedIntegration?.integration_type.endpoints.find(e => e.id === api.endpointId);

  const handleIntegrationChange = (integrationId: string) => {
    const integration = integrations.find(i => i.id === integrationId);
    updateApi({
      integrationId,
      integrationSlug: integration?.integration_type.slug,
      endpointId: undefined,
      endpointName: undefined,
      url: "",
      method: "GET" as const,
      bodyTemplate: "",
    });
  };

  const handleEndpointChange = (endpointId: string) => {
    const endpoint = selectedIntegration?.integration_type.endpoints.find(e => e.id === endpointId);
    if (endpoint) {
      let bodyTemplate = "";
      if (endpoint.request_schema && (endpoint.method === "POST" || endpoint.method === "PUT")) {
        bodyTemplate = JSON.stringify(endpoint.request_schema, null, 2);
      }
      updateApi({
        endpointId,
        endpointName: endpoint.name,
        method: endpoint.method as "GET" | "POST" | "PUT" | "DELETE",
        url: endpoint.path,
        bodyTemplate,
      });
    }
  };

  const headerEntries = Object.entries(api.headers || {});
  const addHeader = () => {
    const newHeaders = { ...(api.headers || {}), "": "" };
    updateApi({ headers: newHeaders });
  };
  const updateHeader = (oldKey: string, newKey: string, value: string, index: number) => {
    const entries = Object.entries(api.headers || {});
    const newHeaders: Record<string, string> = {};
    entries.forEach(([k, v], i) => {
      if (i === index) {
        newHeaders[newKey] = value;
      } else {
        newHeaders[k] = v;
      }
    });
    updateApi({ headers: newHeaders });
  };
  const removeHeader = (index: number) => {
    const entries = Object.entries(api.headers || {});
    const newHeaders: Record<string, string> = {};
    entries.forEach(([k, v], i) => {
      if (i !== index) newHeaders[k] = v;
    });
    updateApi({ headers: newHeaders });
  };

  const responseMappingEntries = Object.entries(api.responseMapping || {});
  const addResponseMapping = () => {
    const newMapping = { ...(api.responseMapping || {}), "": "" };
    updateApi({ responseMapping: newMapping });
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

  const apiSource = api.apiSource || "custom";
  const inputCls = "w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-orange-500 focus:outline-none";
  const smallInputCls = "flex-1 bg-[#1a1a1a] border border-gray-700 rounded px-2 py-1 text-white text-xs focus:border-orange-500 focus:outline-none font-mono";

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">API Source</label>
        <select
          value={apiSource}
          onChange={(e) => {
            const newSource = e.target.value as "custom" | "integration";
            updateApi({
              apiSource: newSource,
              integrationId: undefined,
              integrationSlug: undefined,
              endpointId: undefined,
              endpointName: undefined,
              url: newSource === "custom" ? api.url : "",
            });
          }}
          className={inputCls}
        >
          <option value="custom">Custom URL</option>
          <option value="integration">Integration</option>
        </select>
      </div>

      {apiSource === "integration" && (
        <>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">Connected Integration</label>
            <select
              value={api.integrationId || ""}
              onChange={(e) => handleIntegrationChange(e.target.value)}
              className={inputCls}
              disabled={loadingIntegrations}
            >
              <option value="">
                {loadingIntegrations ? "Loading..." : integrations.length === 0 ? "No integrations connected" : "Select integration..."}
              </option>
              {integrations.map((integration) => (
                <option key={integration.id} value={integration.id}>
                  {integration.integration_type.name}
                </option>
              ))}
            </select>
            {integrations.length === 0 && !loadingIntegrations && (
              <p className="text-xs text-gray-500 mt-1">
                Connect integrations in the Integrations page to use them here.
              </p>
            )}
          </div>

          {selectedIntegration && (
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">Endpoint</label>
              <select
                value={api.endpointId || ""}
                onChange={(e) => handleEndpointChange(e.target.value)}
                className={inputCls}
              >
                <option value="">Select endpoint...</option>
                {selectedIntegration.integration_type.endpoints.map((endpoint) => (
                  <option key={endpoint.id} value={endpoint.id}>
                    {endpoint.method} - {endpoint.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {selectedEndpoint && (
            <div className="bg-[#1a1a1a] rounded-lg p-3 border border-gray-700">
              <div className="flex items-center gap-2 mb-2">
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                  selectedEndpoint.method === "GET" ? "bg-green-900/50 text-green-400" :
                  selectedEndpoint.method === "POST" ? "bg-blue-900/50 text-blue-400" :
                  selectedEndpoint.method === "PUT" ? "bg-yellow-900/50 text-yellow-400" :
                  "bg-red-900/50 text-red-400"
                }`}>
                  {selectedEndpoint.method}
                </span>
                <code className="text-xs text-gray-400 font-mono">{selectedEndpoint.path}</code>
              </div>
              {selectedEndpoint.description && (
                <p className="text-xs text-gray-500">{selectedEndpoint.description}</p>
              )}
            </div>
          )}
        </>
      )}

      {apiSource === "custom" && (
        <div className="grid grid-cols-3 gap-2">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">Method</label>
            <select
              value={api.method}
              onChange={(e) => updateApi({ method: e.target.value as typeof api.method })}
              className={inputCls}
            >
              <option value="GET">GET</option>
              <option value="POST">POST</option>
              <option value="PUT">PUT</option>
              <option value="DELETE">DELETE</option>
            </select>
          </div>

          <div className="col-span-2">
            <label className="block text-sm font-medium text-gray-400 mb-1">URL</label>
            <input
              type="text"
              value={api.url || ""}
              onChange={(e) => updateApi({ url: e.target.value })}
              className={`${inputCls} font-mono text-xs`}
              placeholder="https://api.example.com/endpoint"
            />
          </div>
        </div>
      )}

      <APIRequestHeadersSection
        showHeaders={showHeaders}
        onToggle={() => setShowHeaders(!showHeaders)}
        headerEntries={headerEntries}
        addHeader={addHeader}
        updateHeader={updateHeader}
        removeHeader={removeHeader}
        availableSecrets={availableSecrets}
        secretPickerIndex={secretPickerIndex}
        setSecretPickerIndex={setSecretPickerIndex}
        smallInputCls={smallInputCls}
      />

      {(api.method === "POST" || api.method === "PUT") && (
        <div>
          <label className="block text-sm font-medium text-gray-400 mb-1">
            Request Body (JSON)
            <span className="text-xs text-purple-400 ml-2">Use {"{{variable}}"}</span>
          </label>
          <textarea
            value={api.bodyTemplate || ""}
            onChange={(e) => updateApi({ bodyTemplate: e.target.value })}
            rows={4}
            className={`${inputCls} resize-none font-mono text-xs`}
            placeholder='{"check_in": "{{check_in_date}}", "guests": {{guest_count}}}'
          />

          {variables.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {variables.map((v) => (
                <button
                  key={v.key}
                  onClick={() => updateApi({ bodyTemplate: (api.bodyTemplate || "") + `{{${v.key}}}` })}
                  className="text-xs bg-purple-900/30 text-purple-400 rounded px-1.5 py-0.5 hover:bg-purple-900/50"
                >
                  {`{{${v.key}}}`}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <div>
        <button
          onClick={() => setShowResponseMapping(!showResponseMapping)}
          className="flex items-center gap-2 text-sm font-medium text-gray-300"
        >
          {showResponseMapping ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          Response Mapping
          {responseMappingEntries.length > 0 && <span className="text-xs text-gray-500">({responseMappingEntries.length})</span>}
        </button>

        {showResponseMapping && (
          <div className="mt-2 space-y-2">
            <p className="text-xs text-gray-500">Extract response fields into flow variables (dot notation: data.guest.name)</p>
            {responseMappingEntries.map(([key, path], i) => (
              <div key={i} className="flex gap-2 items-center">
                <input
                  type="text"
                  value={key}
                  onChange={(e) => updateResponseMapping(key, e.target.value, path, i)}
                  className={smallInputCls}
                  placeholder="variable_name"
                />
                <span className="text-gray-500">=</span>
                <input
                  type="text"
                  value={path}
                  onChange={(e) => updateResponseMapping(key, key, e.target.value, i)}
                  className={smallInputCls}
                  placeholder="data.guest.name"
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
              className="text-xs text-orange-400 hover:text-orange-300 flex items-center gap-1"
            >
              <Plus className="h-3 w-3" /> Add Mapping
            </button>
          </div>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Response Instructions
        </label>
        <textarea
          value={api.responseInstructions || ""}
          onChange={(e) => updateApi({ responseInstructions: e.target.value })}
          rows={3}
          className={`${inputCls} resize-none text-xs`}
          placeholder="Tell the AI how to present the API response to the caller (e.g., 'Summarize the reservation details including room type, dates, and price')"
        />
        <p className="text-xs text-gray-500 mt-1">
          Instructions for how the AI should format and present the response
        </p>
      </div>
    </div>
  );
}
