"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";
import { useFlowStore, type APIRequestConfig, type APIRequestNodeData, type FlowVariable } from "../store";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import {
  defaultQuoteDeliveryTemplate,
  validateQuoteDeliveryTemplate,
} from "./quoteEditor";

interface ParameterSchema {
  type?: string;
  description?: string;
  required?: boolean;
}

interface MCPDiscoveredTool {
  name: string;
  description?: string;
  parameters?: {
    type?: string;
    properties?: Record<string, ParameterSchema>;
    required?: string[];
  };
}

interface MCPConnection {
  id: string;
  name: string;
  status: string;
  is_active: boolean;
  discovered_tools?: MCPDiscoveredTool[];
}

interface SavedTool {
  id: string;
  name: string;
  description?: string;
  tool_type: string;
  config?: {
    parameters?: Record<string, ParameterSchema>;
  };
}

interface Capability {
  name: string;
  description?: string;
  parameters?: Record<string, ParameterSchema>;
  required?: string[];
  service_backed?: boolean;
  mutating?: boolean;
}

interface Props {
  api: APIRequestConfig;
  nodeId: string;
  update: (patch: Partial<APIRequestConfig>) => void;
  variables: FlowVariable[];
}

const inputClass =
  "w-full min-w-0 rounded border border-gray-700 bg-[#0b0b0b] px-2.5 py-2 text-xs text-white focus:border-blue-500 focus:outline-none";

function schemaProperties(value: unknown): Record<string, ParameterSchema> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).flatMap(([key, item]) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) return [];
      const schema = item as Record<string, unknown>;
      return [[key, {
        type: typeof schema.type === "string" ? schema.type : "unknown",
        description: typeof schema.description === "string" ? schema.description : "",
      }]];
    }),
  );
}

function templateForMatchingVariables(
  properties: Record<string, ParameterSchema>,
  required: string[],
  variables: FlowVariable[],
): string {
  const known = new Set(variables.map((variable) => variable.key));
  const values = Object.keys(properties)
    .filter((key) => known.has(key))
    .map((key) => {
      const type = properties[key]?.type?.toLowerCase();
      const token = `{{${key}}}`;
      return `"${key}":${["string", "text", "email", "date"].includes(type ?? "")
        ? JSON.stringify(token)
        : token}`;
    });
  if (required.some((key) => !known.has(key))) return "";
  return values.length ? `{\n  ${values.join(",\n  ")}\n}` : "{}";
}

function canReach(edges: Array<{ source: string; target: string }>, from: string, to: string): boolean {
  const pending = [from];
  const visited = new Set<string>();
  while (pending.length) {
    const current = pending.pop()!;
    if (current === to) return true;
    if (visited.has(current)) continue;
    visited.add(current);
    edges.filter((edge) => edge.source === current).forEach((edge) => pending.push(edge.target));
  }
  return false;
}

export default function NativeSourceBindingPanel({ api, nodeId, update, variables }: Props) {
  const { authFetch } = useAuthToken();
  const { accountId } = useAccountContext();
  const nodes = useFlowStore((state) => state.nodes);
  const edges = useFlowStore((state) => state.edges);
  const [connections, setConnections] = useState<MCPConnection[]>([]);
  const [tools, setTools] = useState<SavedTool[]>([]);
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let active = true;
    if (!accountId) {
      setConnections([]);
      setTools([]);
      setCapabilities([]);
      setLoading(false);
      return () => { active = false; };
    }
    setLoading(true);
    setLoadError(null);
    Promise.all([
      authFetch(`/api/mcp-connections?account_id=${encodeURIComponent(accountId)}&include_tools=true`)
        .then(async (response) => ({ ok: response.ok, value: response.ok ? await response.json() : [] })),
      authFetch(`/api/tools?account_id=${encodeURIComponent(accountId)}`)
        .then(async (response) => ({ ok: response.ok, value: response.ok ? await response.json() : { tools: [] } })),
      authFetch("/api/capabilities")
        .then(async (response) => ({ ok: response.ok, value: response.ok ? await response.json() : [] })),
    ])
      .then(([mcpResult, toolResult, capabilityResult]) => {
        if (!active) return;
        const mcpRows = mcpResult.value;
        const toolRows = toolResult.value;
        const capabilityRows = capabilityResult.value;
        setConnections(Array.isArray(mcpRows) ? mcpRows.filter(
          (row: MCPConnection) => row.is_active && row.status === "connected",
        ) : []);
        setTools(Array.isArray(toolRows?.tools) ? toolRows.tools.filter(
          (tool: SavedTool) => ["API_REQUEST", "DYNAMIC_OPERATION", "SEND_SMS", "SEND_EMAIL"].includes(tool.tool_type),
        ) : []);
        setCapabilities(Array.isArray(capabilityRows) ? capabilityRows : []);
        if (!mcpResult.ok || !toolResult.ok || !capabilityResult.ok) {
          setLoadError("Some source catalogs are unavailable. Check account scope and view permissions.");
        }
      })
      .catch(() => {
        if (active) setLoadError("Could not load account source options.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [accountId, authFetch, retryKey]);

  const selectedConnection = connections.find((connection) => connection.id === api.mcpConnectionId);
  const selectedMcpTool = selectedConnection?.discovered_tools?.find(
    (tool) => tool.name === api.mcpToolName,
  );
  const selectedTool = tools.find((tool) => tool.id === api.toolId);
  const selectedCapability = capabilities.find((capability) => capability.name === api.capability);
  const quoteNodes = nodes.filter((node) => {
    const nodeApi = (node.data as APIRequestNodeData).api;
    return (node.type === "api_request" || node.type === "capability") &&
      nodeApi?.apiSource === "capability" &&
      nodeApi.capability === "validate_reservation_quote";
  });
  const quoteApi = (quoteNodeId: string | undefined) => {
    const node = nodes.find((item) => item.id === quoteNodeId);
    return node ? (node.data as APIRequestNodeData).api : undefined;
  };
  const deliveryToolType = selectedTool?.tool_type === "SEND_SMS" || selectedTool?.tool_type === "SEND_EMAIL"
    ? selectedTool.tool_type
    : null;
  const boundQuoteNode = quoteNodes.find((node) => node.id === api.quoteDelivery?.quoteNodeId);
  const quoteDeliveryError = deliveryToolType && api.quoteDelivery
    ? validateQuoteDeliveryTemplate(
      api.argumentsTemplate ?? "",
      deliveryToolType,
      api.quoteDelivery.recipientVariable,
      quoteApi(api.quoteDelivery?.quoteNodeId)?.quotePolicy?.privateUrlVariable ?? "private_checkout_url",
    )
    : null;

  const toolSchema = useMemo(() => {
    if (api.apiSource === "mcp") {
      return {
        properties: selectedMcpTool?.parameters?.properties ?? {},
        required: selectedMcpTool?.parameters?.required ?? [],
      };
    }
    if (api.apiSource === "tool") {
      const properties = schemaProperties(selectedTool?.config?.parameters);
      const required = Object.entries(selectedTool?.config?.parameters ?? {})
        .filter(([, schema]) => schema?.required === true)
        .map(([key]) => key);
      if (selectedTool?.tool_type === "SEND_SMS") {
        return { properties: { recipient: { type: "string" }, body: { type: "string" } }, required: ["recipient", "body"] };
      }
      if (selectedTool?.tool_type === "SEND_EMAIL") {
        return { properties: { recipient: { type: "string" }, subject: { type: "string" }, body: { type: "string" } }, required: ["recipient", "body", "subject"] };
      }
      return { properties, required };
    }
    if (api.apiSource === "capability") {
      return {
        properties: selectedCapability?.parameters ?? {},
        required: selectedCapability?.required ?? [],
      };
    }
    return { properties: {}, required: [] as string[] };
  }, [api.apiSource, selectedCapability, selectedMcpTool, selectedTool]);

  const setMcpConnection = (id: string) => {
    update({
      apiSource: "mcp",
      mcpConnectionId: id || undefined,
      mcpToolName: undefined,
      toolId: undefined,
      integrationId: undefined,
      integrationSlug: undefined,
      endpointId: undefined,
      endpointName: undefined,
      capability: undefined,
      quotePolicy: undefined,
      quoteDelivery: undefined,
      argumentsTemplate: "",
      url: undefined,
      path: undefined,
      method: undefined as unknown as APIRequestConfig["method"],
      headers: undefined,
      bodyTemplate: undefined,
      queryParamOverrides: undefined,
    });
  };

  const setMcpTool = (name: string) => {
    update({
      mcpToolName: name || undefined,
      toolId: undefined,
      quotePolicy: undefined,
      quoteDelivery: undefined,
      argumentsTemplate: "",
      url: undefined,
      path: undefined,
      method: undefined as unknown as APIRequestConfig["method"],
      headers: undefined,
      bodyTemplate: undefined,
      queryParamOverrides: undefined,
    });
  };

  const setSavedTool = (id: string) => {
    update({
      apiSource: "tool",
      toolId: id || undefined,
      mcpConnectionId: undefined,
      mcpToolName: undefined,
      integrationId: undefined,
      integrationSlug: undefined,
      endpointId: undefined,
      endpointName: undefined,
      capability: undefined,
      quotePolicy: undefined,
      quoteDelivery: undefined,
      argumentsTemplate: "",
      url: undefined,
      path: undefined,
      method: undefined as unknown as APIRequestConfig["method"],
      headers: undefined,
      bodyTemplate: undefined,
      queryParamOverrides: undefined,
    });
  };

  const setQuoteValidator = (quoteNodeId: string) => {
    if (!quoteNodeId) {
      update({ quoteDelivery: undefined, argumentsTemplate: "" });
      return;
    }
    const currentUrlVariable = quoteApi(api.quoteDelivery?.quoteNodeId)?.quotePolicy?.privateUrlVariable ?? "private_checkout_url";
    const nextUrlVariable = quoteApi(quoteNodeId)?.quotePolicy?.privateUrlVariable ?? "private_checkout_url";
    const recipientVariable = api.quoteDelivery?.recipientVariable ||
      variables.find((variable) => ["phone", "email"].includes(variable.type))?.key ||
      "";
    const reusableTemplate = !!api.quoteDelivery &&
      !!api.argumentsTemplate?.includes(`{{${currentUrlVariable}}}`);
    const template = reusableTemplate
      ? api.argumentsTemplate!.replaceAll(`{{${currentUrlVariable}}}`, `{{${nextUrlVariable}}}`)
      : defaultQuoteDeliveryTemplate(deliveryToolType ?? "SEND_SMS", recipientVariable || "caller_phone", nextUrlVariable);
    update({
      quoteDelivery: { quoteNodeId, recipientVariable },
      argumentsTemplate: template,
    });
  };

  const setDeliveryRecipient = (recipientVariable: string) => {
    const previous = api.quoteDelivery?.recipientVariable;
    if (!recipientVariable) {
      if (api.quoteDelivery) update({ quoteDelivery: { ...api.quoteDelivery, recipientVariable: "" } });
      return;
    }
    const template = previous && api.argumentsTemplate
      ? api.argumentsTemplate.replaceAll(`{{${previous}}}`, `{{${recipientVariable}}}`)
      : defaultQuoteDeliveryTemplate(
        deliveryToolType ?? "SEND_SMS",
        recipientVariable,
        quoteApi(api.quoteDelivery?.quoteNodeId)?.quotePolicy?.privateUrlVariable ?? "private_checkout_url",
      );
    update({
      quoteDelivery: api.quoteDelivery
        ? { ...api.quoteDelivery, recipientVariable }
        : undefined,
      argumentsTemplate: template,
    });
  };

  const template = api.argumentsTemplate ?? "";
  const insertTemplateForMatchedVariables = () => {
    const built = templateForMatchingVariables(toolSchema.properties, toolSchema.required, variables);
    if (built) update({ argumentsTemplate: built });
  };

  return (
    <div className="space-y-3 rounded-lg border border-gray-800 bg-[#111111] p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h4 className="text-sm font-medium text-gray-200">Native source binding</h4>
          <p className="mt-0.5 text-[11px] text-gray-500">Choose a current source and configure its JSON arguments. Credentials and connection configuration are never shown here.</p>
        </div>
        {loading && <span className="text-[10px] text-gray-500">Loading…</span>}
      </div>

      {loadError && (
        <div role="alert" className="flex items-center justify-between gap-2 rounded border border-red-900/60 bg-red-950/20 px-2 py-1.5 text-xs text-red-300">
          <span className="flex items-center gap-1.5"><AlertCircle className="h-3.5 w-3.5" />{loadError}</span>
          <button type="button" onClick={() => setRetryKey((key) => key + 1)} className="inline-flex items-center gap-1 text-red-200 hover:text-white">
            <RefreshCw className="h-3 w-3" /> Retry
          </button>
        </div>
      )}

      {api.apiSource === "mcp" && (
        <>
          <div>
            <label className="mb-1 block text-xs text-gray-400">Connected MCP server</label>
            <select value={api.mcpConnectionId ?? ""} onChange={(event) => setMcpConnection(event.target.value)} disabled={loading || !accountId} className={inputClass}>
              <option value="">{loading ? "Loading MCP servers…" : "Select a connected server…"}</option>
              {connections.map((connection) => <option key={connection.id} value={connection.id}>{connection.name}</option>)}
            </select>
            {!loading && !connections.length && <p className="mt-1 text-[11px] text-gray-500">No active connected MCP servers are available in this account.</p>}
          </div>
          {selectedConnection && (
            <div>
              <label className="mb-1 block text-xs text-gray-400">Discovered tool</label>
              <select value={api.mcpToolName ?? ""} onChange={(event) => setMcpTool(event.target.value)} className={inputClass}>
                <option value="">Select a discovered tool…</option>
                {(selectedConnection.discovered_tools ?? []).map((tool) => <option key={tool.name} value={tool.name}>{tool.name}</option>)}
              </select>
              <p className="mt-1 text-[10px] text-gray-500">Runtime validates the sealed tool allowlist and property/account scope. Discovery is not permission to execute.</p>
            </div>
          )}
          {selectedMcpTool?.description && <p className="text-xs text-gray-400">{selectedMcpTool.description}</p>}
        </>
      )}

      {api.apiSource === "tool" && (
        <>
          <div>
            <label className="mb-1 block text-xs text-gray-400">Saved Tool</label>
            <select value={api.toolId ?? ""} onChange={(event) => setSavedTool(event.target.value)} disabled={loading || !accountId} className={inputClass}>
              <option value="">{loading ? "Loading saved tools…" : "Select an account Tool…"}</option>
              {tools.map((tool) => <option key={tool.id} value={tool.id}>{tool.name} · {tool.tool_type.replaceAll("_", " ")}</option>)}
            </select>
            {!loading && !tools.length && <p className="mt-1 text-[11px] text-gray-500">No supported API, operation, SMS or email Tools are available.</p>}
          </div>
          {selectedTool?.description && <p className="text-xs text-gray-400">{selectedTool.description}</p>}
          {deliveryToolType && (
            <div className="space-y-2 rounded-lg border border-emerald-900/50 bg-emerald-950/10 p-2.5">
              <div>
                <label className="mb-1 block text-xs font-medium text-emerald-200">Optional quote-link delivery</label>
                <p className="text-[10px] leading-relaxed text-gray-500">
                  Configuration only: preview never sends. Runtime execution is separately server-gated; no payment or checkout session is created here.
                </p>
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-gray-400">Quote validator in this flow</label>
                <select
                  value={api.quoteDelivery?.quoteNodeId ?? ""}
                  onChange={(event) => setQuoteValidator(event.target.value)}
                  className={inputClass}
                >
                  <option value="">No quote delivery binding</option>
                  {quoteNodes.map((node) => <option key={node.id} value={node.id}>{node.data.name || "Reservation quote"} · {node.id.slice(0, 8)}</option>)}
                </select>
                {!quoteNodes.length && <p className="mt-1 text-[10px] text-gray-500">Add a Capability node using validate_reservation_quote first.</p>}
              </div>
              {api.quoteDelivery && (
                <>
                  {!boundQuoteNode && (
                    <p role="alert" className="flex items-center justify-between gap-2 text-[10px] text-amber-300">
                      <span>The referenced quote validator is missing. Rebind this delivery or clear it.</span>
                      <button type="button" onClick={() => setQuoteValidator("")} className="text-amber-100 underline">Clear</button>
                    </p>
                  )}
                  <div>
                    <label className="mb-1 block text-[11px] text-gray-400">Confirmed recipient fact</label>
                    <select
                      value={api.quoteDelivery.recipientVariable}
                      onChange={(event) => setDeliveryRecipient(event.target.value)}
                      className={inputClass}
                    >
                      <option value="">Select a caller phone or email variable…</option>
                      {variables.map((variable) => <option key={variable.key} value={variable.key}>{variable.key} · {variable.type}</option>)}
                    </select>
                  </div>
                  {quoteNodes.find((node) => node.id === api.quoteDelivery?.quoteNodeId) &&
                    !canReach(edges, api.quoteDelivery.quoteNodeId, nodeId) && (
                      <p role="alert" className="text-[10px] text-amber-300">Connect the validator to this delivery node through the confirmed flow path.</p>
                    )}
                  {quoteDeliveryError && <p role="alert" className="flex items-start gap-1.5 text-[10px] text-amber-300"><AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />{quoteDeliveryError}</p>}
                </>
              )}
            </div>
          )}
        </>
      )}

      {api.apiSource === "capability" && (
        <div>
          <label className="mb-1 block text-xs text-gray-400">Capability</label>
          <select
            value={api.capability ?? ""}
            onChange={(event) => {
              const capability = event.target.value || undefined;
              const leavingQuote = api.capability === "validate_reservation_quote" && capability !== "validate_reservation_quote";
              update({
                capability,
                ...(leavingQuote ? {
                  quotePolicy: undefined,
                  responseMapping: {},
                  responseVariables: [],
                  responseProjection: { fields: [] },
                  argumentsTemplate: "",
                } : {}),
              });
            }}
            disabled={loading}
            className={inputClass}
          >
            <option value="">Select a capability…</option>
            {capabilities.map((capability) => <option key={capability.name} value={capability.name}>{capability.name.replaceAll("_", " ")}</option>)}
          </select>
          {selectedCapability?.description && <p className="mt-1 text-xs text-gray-400">{selectedCapability.description}</p>}
          {selectedCapability?.service_backed && <p className="mt-1 text-[11px] text-amber-300">Managed-service capability; native availability is verified by the server before a test begins.</p>}
        </div>
      )}

      {["mcp", "tool", "capability"].includes(api.apiSource ?? "") && (
        <>
          {Object.keys(toolSchema.properties).length > 0 && (
            <div className="rounded border border-gray-800 bg-[#0b0b0b] p-2">
              <p className="mb-1 text-[10px] uppercase tracking-wide text-gray-500">Input contract</p>
              <ul className="space-y-1">
                {Object.entries(toolSchema.properties).map(([key, schema]) => (
                  <li key={key} className="text-[11px] text-gray-400">
                    <code className="text-blue-300">{key}</code>
                    <span className="ml-1 text-gray-600">{schema.type ?? "unknown"}{toolSchema.required.includes(key) ? " · required" : ""}</span>
                    {schema.description && <span className="ml-1 text-gray-500">— {schema.description}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {api.apiSource !== "capability" && !api.quoteDelivery && (
            <>
              <div className="flex items-center justify-between gap-2">
                <label htmlFor={`arguments-template-${api.apiSource}`} className="text-xs font-medium text-gray-300">Arguments template (JSON object)</label>
                <button type="button" onClick={insertTemplateForMatchedVariables} disabled={!Object.keys(toolSchema.properties).length || !toolSchema.required.every((key) => variables.some((variable) => variable.key === key))} className="text-[10px] text-blue-400 hover:text-blue-300 disabled:opacity-40">
                  Fill matching variables
                </button>
              </div>
              <textarea
                id={`arguments-template-${api.apiSource}`}
                value={template}
                onChange={(event) => update({ argumentsTemplate: event.target.value })}
                rows={5}
                spellCheck={false}
                className={`${inputClass} resize-y font-mono`}
                placeholder={'{\n  "check_in": "{{check_in_date}}"\n}'}
              />
              <p className="text-[10px] text-gray-500">
                Use JSON values and <code>{"{{variable_name}}"}</code> tokens. Required arguments must be supplied. Native text simulation never pretends an external API/MCP/Tool action succeeded; it reports preview-required until real execution is available.
              </p>
              {variables.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {variables.map((variable) => <span key={variable.key} className="rounded bg-gray-800 px-1.5 py-0.5 font-mono text-[10px] text-gray-400">{`{{${variable.key}}}`}</span>)}
                </div>
              )}
            </>
          )}
          {api.apiSource === "tool" && deliveryToolType && api.quoteDelivery && (
            <>
              <label htmlFor={`arguments-template-${api.apiSource}`} className="block text-xs font-medium text-gray-300">Text-only delivery arguments</label>
              <textarea
                id={`arguments-template-${api.apiSource}`}
                value={template}
                onChange={(event) => update({ argumentsTemplate: event.target.value })}
                rows={5}
                spellCheck={false}
                className={`${inputClass} resize-y font-mono`}
                aria-label="Quote link delivery arguments"
              />
              <p className="text-[10px] text-gray-500">One existing validated HTTPS link is inserted as plain text. This form does not test or send; native delivery remains server-gated.</p>
              {quoteDeliveryError && <p role="alert" className="text-[10px] text-amber-300">{quoteDeliveryError}</p>}
            </>
          )}
        </>
      )}
    </div>
  );
}
