"use client";

import { useState, useEffect } from "react";
import { AlertCircle, CheckCircle2, ChevronDown, ChevronRight, Loader2, Play, Plus, X } from "lucide-react";
import { useFlowStore, APIRequestNodeData, APIRequestConfig } from "../store";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import APIRequestHeadersSection from "./APIRequestHeadersSection";
import VariableReferencePills from "./VariableReferencePills";

interface EndpointVariable {
  key: string;
  label?: string;
  description?: string;
  placeholder?: string;
  type?: string;
  required?: boolean;
  default?: unknown;
}

interface APIAccountIntegration {
  id: string;
  integration_type_id: string;
  connection_name?: string | null;
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
      variables?: EndpointVariable[];
      query_params?: Array<{ key: string; value: string; required?: boolean }>;
      response_mapping?: Record<string, string>;
      response_mapping_labels?: Record<string, string>;
      source?: "seeded" | "imported";
    }>;
    origin?: "platform_certified" | "customer_imported";
  };
  status: string;
}

interface Props {
  data: APIRequestNodeData;
  nodeId: string;
  assistantId?: string;
}

export default function APIRequestNodePanel({ data, nodeId, assistantId }: Props) {
  const { updateNodeData, variables, toolId } = useFlowStore();
  const { authFetch } = useAuthToken();
  const { accountId } = useAccountContext();
  const api = data.api || { method: "GET" as const, url: "", apiSource: "custom" as const };
  const [showHeaders, setShowHeaders] = useState(
    !!(api.headers && Object.keys(api.headers).length > 0)
  );
  const [showResponseMapping, setShowResponseMapping] = useState(
    !!(api.responseMapping && Object.keys(api.responseMapping).length > 0)
  );
  const [showResponseMessages, setShowResponseMessages] = useState(
    !!(api.onSuccess || api.onError || api.onNotFound || api.onAuthError)
  );
  const [showQueryParams, setShowQueryParams] = useState(true);
  const [integrations, setIntegrations] = useState<APIAccountIntegration[]>([]);
  const [loadingIntegrations, setLoadingIntegrations] = useState(false);
  const [availableSecrets, setAvailableSecrets] = useState<Array<{ key: string; name: string }>>([]);
  const [secretPickerIndex, setSecretPickerIndex] = useState<number | null>(null);
  const [testVariables, setTestVariables] = useState<Record<string, string>>({});
  const [testLoading, setTestLoading] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<null | {
    success: boolean;
    status_code: number;
    elapsed_ms: number;
    body: unknown;
    error_type?: string | null;
    error_message?: string | null;
    extracted_variables?: Record<string, unknown>;
    request_id?: string | null;
  }>(null);

  useEffect(() => {
    const fetchIntegrations = async () => {
      // Do not let the backend guess an account while the dashboard context is
      // still hydrating. A multi-account user must only ever see connections
      // for the account currently selected in the dashboard.
      if (!accountId) {
        setIntegrations([]);
        setLoadingIntegrations(false);
        return;
      }
      setLoadingIntegrations(true);
      try {
        const params: Record<string, string> = { account_id: accountId };
        if (assistantId) params.assistant_id = assistantId;
        const query = new URLSearchParams(params).toString();
        const response = await authFetch(`/api/integrations/connections?${query}`);
        if (response.ok) {
          const resData = await response.json();
          setIntegrations(resData.filter((i: APIAccountIntegration) => i.status === "connected"));
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
  }, [accountId, assistantId, authFetch]);

  // Auto-select integration + endpoint when a template pre-wires integrationSlug / endpointId
  // but leaves integrationId blank (account-specific IDs are unknown at template-author time).
  useEffect(() => {
    if (!integrations.length) return;
    const currentApi = data.api;
    if (!currentApi || currentApi.integrationId || !currentApi.integrationSlug) return;

    const matches = integrations.filter(
      (i) => i.integration_type.slug === currentApi.integrationSlug
    );
    if (matches.length !== 1) return; // Ambiguous or none — let user choose manually

    const integration = matches[0];
    const prewiredEndpoint = currentApi.endpointId
      ? integration.integration_type.endpoints.find((e) => e.id === currentApi.endpointId)
      : null;

    if (prewiredEndpoint) {
      let bodyTemplate = currentApi.bodyTemplate ?? "";
      if (
        !bodyTemplate &&
        prewiredEndpoint.request_schema &&
        ["POST", "PUT", "PATCH"].includes(prewiredEndpoint.method)
      ) {
        bodyTemplate = JSON.stringify(prewiredEndpoint.request_schema, null, 2);
      }
      const endpointMapping = prewiredEndpoint.response_mapping ?? {};
      const hasMapping = Object.keys(endpointMapping).length > 0;
      updateNodeData(nodeId, {
        api: {
          ...currentApi,
          integrationId: integration.id,
          integrationSlug: integration.integration_type.slug,
          endpointId: prewiredEndpoint.id,
          endpointName: prewiredEndpoint.name,
          method: prewiredEndpoint.method as APIRequestConfig["method"],
          url: prewiredEndpoint.path,
          bodyTemplate,
          responseMapping: hasMapping ? { ...endpointMapping } : (currentApi.responseMapping ?? {}),
          autoMappingSource: hasMapping ? { ...endpointMapping } : currentApi.autoMappingSource,
        },
      });
      if (hasMapping) setShowResponseMapping(true);
    } else {
      updateNodeData(nodeId, {
        api: {
          ...currentApi,
          integrationId: integration.id,
          integrationSlug: integration.integration_type.slug,
        },
      });
    }
  // Run only when integrations first populate; intentionally omit api/updateNodeData from deps.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [integrations]);

  const updateApi = (updates: Partial<typeof api>) => {
    updateNodeData(nodeId, { api: { ...api, ...updates } });
  };

  const selectedIntegration = integrations.find(i => i.id === api.integrationId);
  const selectedEndpoint = selectedIntegration?.integration_type.endpoints.find(e => e.id === api.endpointId);
  const endpointGroups = (selectedIntegration?.integration_type.endpoints ?? []).reduce(
    (groups, endpoint) => {
      const label = endpoint.source === "imported"
        ? "Imported Operations"
        : "Integration Endpoints";
      (groups[label] ??= []).push(endpoint);
      return groups;
    },
    {} as Record<string, APIAccountIntegration["integration_type"]["endpoints"]>
  );
  const testableVariables = variables.filter(v => v.key);

  const setQueryParamOverride = (key: string, value: string) => {
    updateApi({ queryParamOverrides: { ...(api.queryParamOverrides ?? {}), [key]: value } });
  };

  const resetQueryParamOverride = (key: string) => {
    const next = { ...(api.queryParamOverrides ?? {}) };
    delete next[key];
    updateApi({ queryParamOverrides: Object.keys(next).length ? next : undefined });
  };

  // Resolve the label/description for a query param from the endpoint's variable
  // metadata: match on the param key first, then fall back to the {{var}} name
  // embedded in the seed default value.
  const findQueryParamMeta = (
    qp: { key: string; value: string }
  ): EndpointVariable | undefined => {
    const byKey = selectedEndpoint?.variables?.find((v) => v.key === qp.key);
    if (byKey) return byKey;
    const match = /\{\{(\w+)\}\}/.exec(qp.value || "");
    if (match) return selectedEndpoint?.variables?.find((v) => v.key === match![1]);
    return undefined;
  };

  const areMappingsEqual = (a: Record<string, string>, b: Record<string, string>): boolean => {
    const aKeys = Object.keys(a);
    const bKeys = Object.keys(b);
    if (aKeys.length !== bKeys.length) return false;
    return aKeys.every(k => a[k] === b[k]);
  };

  const formatMappingLabel = (key: string) =>
    key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());

  const handleIntegrationChange = (integrationId: string) => {
    const integration = integrations.find(i => i.id === integrationId);
    // Preserve a pre-wired endpointId if it still exists in the newly selected integration.
    const prewired = api.endpointId
      ? integration?.integration_type.endpoints.find((e) => e.id === api.endpointId)
      : null;

    if (prewired) {
      let bodyTemplate = api.bodyTemplate ?? "";
      if (
        !bodyTemplate &&
        prewired.request_schema &&
        ["POST", "PUT", "PATCH"].includes(prewired.method)
      ) {
        bodyTemplate = JSON.stringify(prewired.request_schema, null, 2);
      }
      const endpointMapping = prewired.response_mapping ?? {};
      const hasMapping = Object.keys(endpointMapping).length > 0;
      updateApi({
        integrationId,
        integrationSlug: integration?.integration_type.slug,
        endpointId: prewired.id,
        endpointName: prewired.name,
        method: prewired.method as APIRequestConfig["method"],
        url: prewired.path,
        bodyTemplate,
        responseMapping: hasMapping ? { ...endpointMapping } : (api.responseMapping ?? {}),
        autoMappingSource: hasMapping ? { ...endpointMapping } : api.autoMappingSource,
      });
      if (hasMapping) setShowResponseMapping(true);
    } else {
      updateApi({
        integrationId,
        integrationSlug: integration?.integration_type.slug,
        endpointId: undefined,
        endpointName: undefined,
        url: "",
        method: "GET" as const,
        bodyTemplate: "",
        autoMappingSource: undefined,
        queryParamOverrides: undefined,
      });
    }
  };

  const handleEndpointChange = (endpointId: string) => {
    const endpoint = selectedIntegration?.integration_type.endpoints.find(e => e.id === endpointId);
    if (!endpoint) return;

    let bodyTemplate = "";
    if (endpoint.request_schema && (endpoint.method === "POST" || endpoint.method === "PUT" || endpoint.method === "PATCH")) {
      bodyTemplate = JSON.stringify(endpoint.request_schema, null, 2);
    }

    const currentMapping = api.responseMapping || {};
    const autoSource = api.autoMappingSource;
    const endpointMapping = endpoint.response_mapping || {};
    const endpointHasMapping = Object.keys(endpointMapping).length > 0;
    const hasCurrentMappings = Object.keys(currentMapping).length > 0;

    // Customized = has mappings that differ from the last auto-populated source,
    // or has mappings that were manually created (no autoMappingSource set)
    const isCustomized = hasCurrentMappings && (
      !autoSource || !areMappingsEqual(currentMapping, autoSource)
    );

    let newResponseMapping: Record<string, string>;
    let newAutoMappingSource: Record<string, string> | undefined;

    if (endpointHasMapping) {
      if (isCustomized) {
        const confirmed = window.confirm(
          `Replace your customized response mappings with the defaults for "${endpoint.name}"?`
        );
        newResponseMapping = confirmed ? { ...endpointMapping } : currentMapping;
      } else {
        newResponseMapping = { ...endpointMapping };
      }
      newAutoMappingSource = { ...endpointMapping };
      setShowResponseMapping(true);
    } else {
      // New endpoint has no mapping — strip auto-populated rows, keep user-added ones
      if (autoSource) {
        const customOnly: Record<string, string> = {};
        for (const [k, v] of Object.entries(currentMapping)) {
          if (!(k in autoSource) || autoSource[k] !== v) customOnly[k] = v;
        }
        newResponseMapping = customOnly;
      } else if (isCustomized) {
        const confirmed = window.confirm(
          `"${endpoint.name}" has no default response mappings. Clear your existing mappings?`
        );
        newResponseMapping = confirmed ? {} : currentMapping;
      } else {
        newResponseMapping = {};
      }
      newAutoMappingSource = undefined;
    }

    updateApi({
      endpointId,
      endpointName: endpoint.name,
      method: endpoint.method as "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
      url: endpoint.path,
      bodyTemplate,
      responseMapping: newResponseMapping,
      autoMappingSource: newAutoMappingSource,
      // Query-param overrides are keyed per endpoint; drop them when the endpoint changes.
      queryParamOverrides: undefined,
    });
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

  const validateBeforeTest = () => {
    const method = api.method || "GET";
    if (apiSource === "integration") {
      if (!api.integrationId) return "Select a connected integration first";
      if (!api.endpointId) return "Select an integration endpoint first";
      const overrides = api.queryParamOverrides ?? {};
      for (const qp of selectedEndpoint?.query_params ?? []) {
        if (!qp.required) continue;
        const effective = qp.key in overrides ? overrides[qp.key] : qp.value;
        if (!effective || !effective.trim()) {
          return `Required query parameter "${qp.key}" cannot be blank`;
        }
      }
    } else if (!api.url?.trim()) {
      return "URL is required";
    }
    if (["POST", "PUT", "PATCH"].includes(method) && api.bodyTemplate?.trim()) {
      try {
        JSON.parse(api.bodyTemplate);
      } catch {
        return "Request body must be valid JSON before testing";
      }
    }
    for (const [key, path] of Object.entries(api.responseMapping || {})) {
      if (!key.trim() || !path.trim()) {
        return "Response mappings need both a variable name and JSON path";
      }
    }
    return null;
  };

  const handleTestApi = async () => {
    if (!accountId) {
      setTestError("Account context is still loading");
      return;
    }
    const validationError = validateBeforeTest();
    if (validationError) {
      setTestError(validationError);
      return;
    }
    setTestLoading(true);
    setTestError(null);
    setTestResult(null);
    try {
      const response = await authFetch("/api/api-tester/test", {
        method: "POST",
        body: JSON.stringify({
          account_id: accountId,
          method: api.method,
          url: api.url || "",
          headers: api.headers || {},
          bodyTemplate: api.bodyTemplate || undefined,
          timeout: api.timeout ?? 8,
          retryCount: api.retryCount ?? 0,
          variables: testVariables,
          responseMapping: api.responseMapping || {},
          apiSource,
          integrationId: api.integrationId,
          endpointId: api.endpointId,
          queryParamOverrides: api.queryParamOverrides || undefined,
          endpointName: api.endpointName,
          nodeId,
          flowToolId: toolId,
          sourceLabel: data.name || api.endpointName || "API Request",
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || "API test failed");
      }
      setTestResult(result);
    } catch (error) {
      setTestError(error instanceof Error ? error.message : "API test failed");
    } finally {
      setTestLoading(false);
    }
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
                {loadingIntegrations ? "Loading..." : integrations.length === 0 ? "No integrations connected" : "Select connection..."}
              </option>
              {Object.entries(
                integrations.reduce((acc, i) => {
                  const key = i.integration_type.name;
                  if (!acc[key]) acc[key] = [];
                  acc[key].push(i);
                  return acc;
                }, {} as Record<string, APIAccountIntegration[]>)
              ).map(([typeName, conns]) =>
                conns.length === 1 && !conns[0].connection_name ? (
                  <option key={conns[0].id} value={conns[0].id}>
                    {typeName}
                  </option>
                ) : (
                  <optgroup key={typeName} label={typeName}>
                    {conns.map((integration) => (
                      <option key={integration.id} value={integration.id}>
                        {integration.connection_name || typeName}
                      </option>
                    ))}
                  </optgroup>
                )
              )}
            </select>
            {integrations.length === 0 && !loadingIntegrations && (
              <p className="text-xs text-gray-500 mt-1">
                Connect integrations in the Integrations page to use them here.
              </p>
            )}
            {!api.integrationId && api.endpointName && !loadingIntegrations && (
              <p className="text-xs text-gray-500 mt-1">
                Will bind to: <span className="text-orange-400">{api.endpointName}</span>
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
                {Object.entries(endpointGroups).map(([group, endpoints]) => (
                  <optgroup key={group} label={group}>
                    {endpoints.map((endpoint) => (
                      <option key={endpoint.id} value={endpoint.id}>
                        {endpoint.method} - {endpoint.name}
                      </option>
                    ))}
                  </optgroup>
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

          {selectedEndpoint && (selectedEndpoint.query_params?.length ?? 0) > 0 && (
            <div>
              <button
                type="button"
                onClick={() => setShowQueryParams(!showQueryParams)}
                className="flex items-center gap-2 text-sm font-medium text-gray-400 hover:text-gray-300"
              >
                {showQueryParams ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                Query Parameters
                <span className="text-xs text-gray-500">({selectedEndpoint.query_params!.length})</span>
              </button>
              {showQueryParams && (
                <div className="mt-2 space-y-2">
                  <p className="text-xs text-gray-500">
                    Override the value sent for each query parameter. Untouched parameters use the
                    integration&apos;s default. Use {"{{variable}}"} to insert a collected value, or type a literal.
                  </p>
                  {selectedEndpoint.query_params!.map((qp) => {
                    const overrides = api.queryParamOverrides ?? {};
                    const isOverridden = qp.key in overrides;
                    const effectiveValue = isOverridden ? overrides[qp.key] : qp.value;
                    const meta = findQueryParamMeta(qp);
                    const label = meta?.label;
                    const description = meta?.description;
                    const blankRequired = !!qp.required && effectiveValue.trim() === "";
                    return (
                      <div key={qp.key} className="bg-[#1a1a1a] rounded-lg p-2.5 border border-gray-700">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <code className="text-xs text-orange-400 font-mono">{qp.key}</code>
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                            qp.required ? "bg-red-900/40 text-red-400" : "bg-gray-800 text-gray-400"
                          }`}>
                            {qp.required ? "Required" : "Optional"}
                          </span>
                          {isOverridden && (
                            <span className="text-[10px] text-orange-400 bg-orange-900/30 rounded px-1.5 py-0.5">
                              Overridden
                            </span>
                          )}
                          {label && <span className="text-xs text-gray-400">{label}</span>}
                          {isOverridden && (
                            <button
                              type="button"
                              onClick={() => resetQueryParamOverride(qp.key)}
                              className="ml-auto text-[10px] text-gray-400 hover:text-orange-400"
                            >
                              Reset to default
                            </button>
                          )}
                        </div>
                        {description && <p className="text-xs text-gray-500 mb-1.5">{description}</p>}
                        <input
                          type="text"
                          value={effectiveValue}
                          onChange={(e) => setQueryParamOverride(qp.key, e.target.value)}
                          className="w-full bg-[#1a1a1a] border border-gray-700 rounded px-2 py-1 text-white text-xs focus:border-orange-500 focus:outline-none font-mono"
                          placeholder={qp.value || "value"}
                        />
                        {blankRequired && (
                          <p className="text-xs text-red-400 mt-1 flex items-center gap-1">
                            <AlertCircle className="w-3 h-3" /> Required parameter is blank — the call will fail until it is set.
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>
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
              <option value="PATCH">PATCH</option>
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

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Thinking message
        </label>
        <textarea
          value={api.thinkingMessage || ""}
          onChange={(e) => updateApi({ thinkingMessage: e.target.value })}
          rows={2}
          className={`${inputCls} resize-none text-xs`}
          placeholder="What the AI says while the request is in progress — e.g. &quot;Let me check that reservation for you.&quot;"
        />
        <p className="text-xs text-gray-500 mt-1">
          Spoken aloud during the API call so callers don&apos;t hear silence
        </p>
        <VariableReferencePills text={api.thinkingMessage || ""} variables={variables} />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-sm font-medium text-gray-400 mb-1">
            Timeout (seconds)
          </label>
          <input
            type="number"
            min={1}
            max={60}
            value={api.timeout ?? 8}
            onChange={(e) => {
              const val = parseInt(e.target.value, 10);
              updateApi({ timeout: isNaN(val) ? 8 : Math.min(60, Math.max(1, val)) });
            }}
            className={inputCls}
          />
          <p className="text-xs text-gray-500 mt-1">Keep under 10 s for voice</p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-400 mb-1">
            Retry count
          </label>
          <input
            type="number"
            min={0}
            max={3}
            value={api.retryCount ?? 0}
            onChange={(e) => {
              const val = parseInt(e.target.value, 10);
              updateApi({ retryCount: isNaN(val) ? 0 : Math.min(3, Math.max(0, val)) });
            }}
            className={inputCls}
          />
          <p className="text-xs text-gray-500 mt-1">Set to 0 for voice; retries add silence</p>
        </div>
      </div>

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

      {(api.method === "POST" || api.method === "PUT" || api.method === "PATCH") && (
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
            placeholder='{"key": "{{variable_name}}"}'
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

      <div className="border border-gray-800 rounded-lg bg-[#111111] overflow-hidden">
        <div className="px-3 py-2 border-b border-gray-800 flex items-center justify-between gap-3">
          <div>
            <h4 className="text-sm font-medium text-gray-200">Test API request</h4>
            <p className="text-xs text-gray-500">Runs this node with sample variables and stores metadata only</p>
          </div>
          <button
            onClick={handleTestApi}
            disabled={testLoading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-orange-600 hover:bg-orange-700 disabled:opacity-50 text-white text-xs font-medium transition-colors"
          >
            {testLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            {testLoading ? "Testing" : "Run test"}
          </button>
        </div>
        <div className="p-3 space-y-3">
          {(() => {
            const epVars = selectedEndpoint?.variables?.filter(v => v.key) ?? [];
            if (apiSource === "integration" && epVars.length > 0) {
              return (
                <div className="space-y-2">
                  <p className="text-xs text-orange-400/80 font-medium">{selectedEndpoint!.name} — test parameters</p>
                  {epVars.map((variable) => (
                    <div key={variable.key}>
                      <label className="block text-xs text-gray-400 mb-1">
                        {variable.label || variable.key}
                        {variable.required && <span className="text-red-400 ml-1">*</span>}
                      </label>
                      <input
                        value={testVariables[variable.key] ?? (variable.default != null ? String(variable.default) : "")}
                        onChange={(e) =>
                          setTestVariables(prev => ({ ...prev, [variable.key]: e.target.value }))
                        }
                        className={smallInputCls}
                        placeholder={variable.placeholder || (variable.type === "date" ? "YYYY-MM-DD" : variable.type === "number" ? "0" : "")}
                      />
                      {variable.description && (
                        <p className="text-[11px] text-gray-600 mt-0.5">{variable.description}</p>
                      )}
                    </div>
                  ))}
                </div>
              );
            }
            if (testableVariables.length > 0) {
              return (
                <div className="grid grid-cols-1 gap-2">
                  {testableVariables.map((variable) => (
                    <div key={variable.key}>
                      <label className="block text-xs text-gray-500 mb-1">{variable.key}</label>
                      <input
                        value={testVariables[variable.key] ?? variable.defaultValue ?? ""}
                        onChange={(e) =>
                          setTestVariables(prev => ({ ...prev, [variable.key]: e.target.value }))
                        }
                        className={smallInputCls}
                        placeholder={variable.description || variable.type}
                      />
                    </div>
                  ))}
                </div>
              );
            }
            return (
              <p className="text-xs text-gray-500">No flow variables defined yet. The request can still be tested without sample values.</p>
            );
          })()}

          {testError && (
            <div className="flex items-start gap-2 rounded border border-red-900/70 bg-red-950/30 px-3 py-2 text-xs text-red-300">
              <AlertCircle className="h-3.5 w-3.5 mt-0.5 flex-shrink-0" />
              <span>{testError}</span>
            </div>
          )}

          {testResult && (
            <div className="rounded border border-gray-800 bg-[#0b0b0b] overflow-hidden">
              <div className="px-3 py-2 flex items-center gap-3 border-b border-gray-800">
                {testResult.success ? (
                  <CheckCircle2 className="h-4 w-4 text-green-400" />
                ) : (
                  <AlertCircle className="h-4 w-4 text-red-400" />
                )}
                <span className={testResult.success ? "text-green-400" : "text-red-400"}>
                  {testResult.status_code || "Error"}
                </span>
                <span className="text-xs text-gray-500">{Math.round(testResult.elapsed_ms || 0)}ms</span>
                {testResult.request_id && (
                  <code className="text-[11px] text-gray-600 truncate">req {testResult.request_id.slice(0, 10)}</code>
                )}
              </div>
              {testResult.error_message && (
                <div className="px-3 py-2 text-xs text-red-300 border-b border-gray-800">
                  {testResult.error_type ? `${testResult.error_type}: ` : ""}{testResult.error_message}
                </div>
              )}
              {testResult.extracted_variables && Object.keys(testResult.extracted_variables).length > 0 && (
                <div className="px-3 py-2 border-b border-gray-800">
                  <p className="text-xs text-gray-500 mb-1">Extracted variables</p>
                  <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap">
                    {JSON.stringify(testResult.extracted_variables, null, 2)}
                  </pre>
                </div>
              )}
              <pre className="max-h-52 overflow-auto p-3 text-xs text-gray-300 font-mono whitespace-pre-wrap">
                {typeof testResult.body === "object"
                  ? JSON.stringify(testResult.body, null, 2)
                  : String(testResult.body ?? "")}
              </pre>
            </div>
          )}
        </div>
      </div>

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
            <div className="rounded bg-gray-900 border border-gray-800 px-3 py-2 text-xs text-gray-400">
              Maps API response fields into flow variables the AI can reference. Use JSONPath (e.g. <code className="text-orange-400">$.data.guest.name</code>) or dot notation (e.g. <code className="text-orange-400">data.guest.name</code>).
            </div>
            {responseMappingEntries.map(([key, path], i) => {
              const isAuto = !!(api.autoMappingSource && key !== "" && api.autoMappingSource[key] === path);
              const autoLabel = isAuto && key
                ? (selectedEndpoint?.response_mapping_labels?.[key] ?? formatMappingLabel(key))
                : null;
              return (
                <div key={i}>
                  <div className="flex gap-2 items-center">
                    <div className="flex-1 relative">
                      <input
                        type="text"
                        value={key}
                        onChange={(e) => updateResponseMapping(key, e.target.value, path, i)}
                        className={smallInputCls}
                        placeholder="variable_name"
                      />
                      {isAuto && (
                        <span className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[10px] bg-orange-900/40 text-orange-400 rounded px-1 pointer-events-none">auto</span>
                      )}
                    </div>
                    <span className="text-gray-500">=</span>
                    <input
                      type="text"
                      value={path}
                      onChange={(e) => updateResponseMapping(key, key, e.target.value, i)}
                      className={`${smallInputCls} flex-1`}
                      placeholder="$.data.guest.name"
                    />
                    <button
                      onClick={() => removeResponseMapping(i)}
                      className="text-red-400 hover:text-red-300 p-1"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                  {autoLabel && (
                    <p className="text-[11px] text-gray-600 mt-0.5 ml-0.5">{autoLabel}</p>
                  )}
                </div>
              );
            })}
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
          Voice result script
        </label>
        <textarea
          value={api.responseInstructions || ""}
          onChange={(e) => updateApi({ responseInstructions: e.target.value })}
          rows={4}
          className={`${inputCls} resize-none text-xs`}
          placeholder={selectedEndpoint
            ? `For "${selectedEndpoint.name}": this text (with {{variables}} filled in) becomes the tool result the AI reads — e.g., "The available rooms are: {{available_rooms}}. Ask which one the caller prefers."`
            : "This text (with {{variables}} filled in) is exactly what the AI reads as the tool result. Use {{variable_name}} to embed extracted data — e.g., 'Booking confirmed. Reservation code: {{crs_reservation_code}}.'"}
        />
        <p className="text-xs text-gray-500 mt-1">
          Becomes the tool result the AI reads after the API call — use {"{{variable}}"} placeholders to embed extracted values. Leave blank to use the "On success" message.
        </p>
        <VariableReferencePills text={api.responseInstructions || ""} variables={variables} />
      </div>

      <div>
        <button
          onClick={() => setShowResponseMessages(!showResponseMessages)}
          className="flex items-center gap-2 text-sm font-medium text-gray-300"
        >
          {showResponseMessages ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          Response messages
          <span className="text-xs text-gray-600 font-normal">optional</span>
        </button>

        {showResponseMessages && (
          <div className="mt-3 space-y-3">
            <p className="text-xs text-gray-500">Override the default messages the AI hears after each outcome.</p>
            <div>
              <label className="block text-xs text-gray-500 mb-1">On success</label>
              <input
                type="text"
                value={api.onSuccess || ""}
                onChange={(e) => updateApi({ onSuccess: e.target.value })}
                className={inputCls}
                placeholder="Request completed successfully"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">On error</label>
              <input
                type="text"
                value={api.onError || ""}
                onChange={(e) => updateApi({ onError: e.target.value })}
                className={inputCls}
                placeholder="There was an issue processing your request"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">On not found (404)</label>
              <input
                type="text"
                value={api.onNotFound || ""}
                onChange={(e) => updateApi({ onNotFound: e.target.value })}
                className={inputCls}
                placeholder="The requested information was not found"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">On auth error</label>
              <input
                type="text"
                value={api.onAuthError || ""}
                onChange={(e) => updateApi({ onAuthError: e.target.value })}
                className={inputCls}
                placeholder="There was an authentication issue with the system"
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
