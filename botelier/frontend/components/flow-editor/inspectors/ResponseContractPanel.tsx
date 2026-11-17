"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Plus, Sparkles, X } from "lucide-react";
import type { APIRequestConfig, APIRequestNodeData, FlowVariable } from "../store";
import { useFlowStore } from "../store";
import { buildResponsePreviewPayload, looksFinancialVariable, previewMappedResponse } from "./responsePreview";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { useAccountContext } from "@/lib/auth/useAccountContext";

interface Props {
  nodeId: string;
  toolId: string | null;
  api: APIRequestConfig;
  variables: FlowVariable[];
  sampleFromTest?: unknown;
}

function formatJSON(value: unknown): string {
  try {
    return JSON.stringify(value ?? null, null, 2);
  } catch {
    return "null";
  }
}

export default function ResponseContractPanel({ nodeId, toolId, api, variables, sampleFromTest }: Props) {
  const { authFetch } = useAuthToken();
  const { accountId } = useAccountContext();
  const updateNodeData = useFlowStore((state) => state.updateNodeData);
  const [sampleText, setSampleText] = useState("{\n  \n}");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ mapped_variables: Record<string, unknown>; llm_data: Record<string, unknown> } | null>(null);
  const [sampleRevision, setSampleRevision] = useState(0);
  const requestRef = useRef(0);
  const mappingKeys = Object.keys(api.responseMapping ?? {}).filter(Boolean);
  const outputKeys = Array.from(new Set([
    ...mappingKeys,
    ...(api.responseVariables ?? []).map((entry) => entry.variableKey).filter(Boolean),
  ]));
  const availableVariables = Array.from(new Set([
    ...variables.map((variable) => variable.key),
    ...outputKeys,
  ])).filter(Boolean).sort();
  const fields = api.responseProjection?.fields ?? [];
  const getLatestApi = (): APIRequestConfig => {
    const node = useFlowStore.getState().nodes.find((candidate) => candidate.id === nodeId);
    return (node?.data as APIRequestNodeData | undefined)?.api ?? api;
  };
  const update = (patch: Partial<APIRequestConfig>) => {
    updateNodeData(nodeId, { api: { ...getLatestApi(), ...patch } });
  };

  useEffect(() => {
    if (sampleFromTest === undefined) return;
    setSampleText(formatJSON(sampleFromTest));
    setSampleRevision((revision) => revision + 1);
    setResult(null);
    setError(null);
  }, [sampleFromTest]);

  useEffect(() => {
    requestRef.current += 1;
    setLoading(false);
    setResult(null);
    setError(null);
  }, [toolId, accountId, api.responseMapping, api.responseVariables, api.responseProjection, sampleRevision]);

  useEffect(() => () => { requestRef.current += 1; }, []);

  const runPreview = async () => {
    if (!toolId || !accountId) {
      setError("Wait for the flow tool and account context to finish loading.");
      return;
    }
    let sample: unknown;
    try {
      sample = JSON.parse(sampleText);
    } catch {
      setError("Sample response must be valid JSON.");
      return;
    }
    const requestId = ++requestRef.current;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const preview = await previewMappedResponse({
        authFetch,
        toolId,
        accountId,
        sample,
        configuration: api,
        variableDeclarations: variables,
      });
      if (requestId === requestRef.current) setResult(preview);
    } catch (previewError) {
      if (requestId === requestRef.current) {
        setError(previewError instanceof Error ? previewError.message : "Response preview failed.");
      }
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  };

  const updateResponseVariable = (index: number, patch: Partial<NonNullable<APIRequestConfig["responseVariables"]>[number]>) => {
    const next = [...(api.responseVariables ?? [])];
    next[index] = { ...next[index], ...patch };
    update({ responseVariables: next });
  };

  const updateProjectionField = (
    index: number,
    patch: Partial<NonNullable<APIRequestConfig["responseProjection"]>["fields"][number]>,
  ) => {
    const next = [...fields];
    next[index] = { ...next[index], ...patch };
    update({ responseProjection: { fields: next } });
  };

  return (
    <section className="rounded-lg border border-gray-800 bg-[#111111] overflow-hidden" aria-label="Response mapping and exact model JSON">
      <div className="px-3 py-2 border-b border-gray-800 flex items-center justify-between gap-3">
        <div>
          <h4 className="text-sm font-medium text-gray-200">Mapped outputs &amp; model payload</h4>
          <p className="text-xs text-gray-500">Configure exact fields the model receives. Preview uses only the sample below.</p>
        </div>
        <button
          type="button"
          onClick={runPreview}
          disabled={loading || !accountId || !toolId}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs font-medium"
        >
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          Preview mapping
        </button>
      </div>

      <div className="p-3 space-y-4">
        <div>
          <div className="flex items-center justify-between mb-2">
            <div>
              <p className="text-xs font-medium text-gray-300">Optional mapped outputs</p>
              <p className="text-[11px] text-gray-500">Defaults are JSON values; 0, false, null, arrays and objects are preserved exactly.</p>
            </div>
            <button
              type="button"
              onClick={() => update({ responseVariables: [...(api.responseVariables ?? []), { variableKey: "", jsonPath: "" }] })}
              className="inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
            >
              <Plus className="h-3 w-3" /> Add output
            </button>
          </div>
          <div className="space-y-2">
            {(api.responseVariables ?? []).map((entry, index) => (
              <div key={`response-variable-${index}`} className="grid grid-cols-1 gap-2 rounded bg-[#171717] border border-gray-800 p-2 sm:grid-cols-[1fr_1.3fr_1fr_auto]">
                <input
                  aria-label={`Output variable ${index + 1}`}
                  value={entry.variableKey}
                  onChange={(event) => updateResponseVariable(index, { variableKey: event.target.value })}
                  placeholder="variable_name"
                  className="min-w-0 bg-[#0d0d0d] border border-gray-700 rounded px-2 py-1.5 text-xs text-white font-mono"
                />
                <input
                  aria-label={`JSON path for output ${index + 1}`}
                  value={entry.jsonPath}
                  onChange={(event) => updateResponseVariable(index, { jsonPath: event.target.value })}
                  placeholder="$.result.value"
                  className="min-w-0 bg-[#0d0d0d] border border-gray-700 rounded px-2 py-1.5 text-xs text-white font-mono"
                />
                <input
                  aria-label={`JSON default for output ${index + 1}`}
                  value={entry.defaultValue === undefined ? "" : formatJSON(entry.defaultValue)}
                  onChange={(event) => {
                    const value = event.target.value;
                    if (!value.trim()) {
                      const next = [...(api.responseVariables ?? [])];
                      const updated = { ...next[index] };
                      delete updated.defaultValue;
                      next[index] = updated;
                      update({ responseVariables: next });
                      return;
                    }
                    try {
                      updateResponseVariable(index, { defaultValue: JSON.parse(value) });
                    } catch {
                      // Keep the last valid saved JSON value while the user types.
                    }
                  }}
                  placeholder="Default JSON (optional)"
                  className="min-w-0 bg-[#0d0d0d] border border-gray-700 rounded px-2 py-1.5 text-xs text-white font-mono"
                />
                <button
                  type="button"
                  aria-label={`Remove output ${index + 1}`}
                  onClick={() => update({ responseVariables: (api.responseVariables ?? []).filter((_, i) => i !== index) })}
                  className="justify-self-end text-gray-500 hover:text-red-400 p-1"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
            {!(api.responseVariables?.length) && (
              <p className="text-[11px] text-gray-600">No optional outputs yet. Existing response mappings remain available above.</p>
            )}
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <div>
              <p className="text-xs font-medium text-gray-300">Exact model JSON projection</p>
              <p className="text-[11px] text-gray-500">Only selected fields are sent as structured tool result data. Cleanup is opt-in and nonfinancial.</p>
            </div>
            <button
              type="button"
              onClick={() => update({ responseProjection: { fields: [...fields, { variable: "" }] } })}
              className="inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
            >
              <Plus className="h-3 w-3" /> Add field
            </button>
          </div>
          <div className="space-y-2">
            {fields.map((field, index) => {
              const financial = looksFinancialVariable(field.variable);
              return (
                <div key={`projection-field-${index}`} className="rounded bg-[#171717] border border-gray-800 p-2">
                  <div className="flex gap-2 items-center">
                    <select
                      aria-label={`Projected field ${index + 1}`}
                      value={field.variable}
                      onChange={(event) => updateProjectionField(index, { variable: event.target.value })}
                      className="flex-1 min-w-0 bg-[#0d0d0d] border border-gray-700 rounded px-2 py-1.5 text-xs text-white font-mono"
                    >
                      <option value="">Select mapped output…</option>
                      {outputKeys.map((key) => <option key={key} value={key}>{key}</option>)}
                    </select>
                    <button
                      type="button"
                      aria-label={`Remove projected field ${index + 1}`}
                      onClick={() => update({ responseProjection: { fields: fields.filter((_, i) => i !== index) } })}
                      className="text-gray-500 hover:text-red-400 p-1"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
                    {(["trim", "collapse_whitespace", "clean_text"] as const).map((operation) => {
                      const checked = (field.cleanup ?? []).includes(operation);
                      const disabled = financial || (!checked && (field.cleanup?.length ?? 0) >= 3);
                      return (
                        <label key={operation} className={`inline-flex items-center gap-1.5 text-[11px] ${disabled ? "text-gray-600" : "text-gray-400"}`}>
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={disabled}
                            onChange={(event) => {
                              const cleanup = new Set(field.cleanup ?? []);
                              event.target.checked ? cleanup.add(operation) : cleanup.delete(operation);
                              updateProjectionField(index, { cleanup: cleanup.size ? Array.from(cleanup) : undefined });
                            }}
                          />
                          {operation}
                        </label>
                      );
                    })}
                  </div>
                  {financial && <p className="mt-1 text-[10px] text-amber-400">Cleanup disabled for financial-looking fields; values remain untouched.</p>}
                </div>
              );
            })}
            {!fields.length && (
              <p className="rounded border border-gray-800 bg-[#171717] p-2 text-[11px] text-gray-500">
                No projected fields. The exact model payload is empty until you select fields.
              </p>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <div>
            <label className="block text-xs font-medium text-gray-300 mb-1">Raw sample JSON</label>
            <textarea
              value={sampleText}
              onChange={(event) => {
                setSampleText(event.target.value);
                setSampleRevision((revision) => revision + 1);
              }}
              rows={7}
              spellCheck={false}
              className="w-full resize-y rounded border border-gray-800 bg-[#0b0b0b] p-2 font-mono text-xs text-gray-300 focus:border-blue-500 focus:outline-none"
              aria-label="Raw sample JSON"
            />
            {sampleFromTest !== undefined && (
              <p className="mt-1 text-[10px] text-gray-500">Filled from the explicit API test result; preview does not issue another provider request.</p>
            )}
          </div>
          <div className="space-y-2">
            {error && (
              <div role="alert" className="flex items-start gap-2 rounded border border-red-900/70 bg-red-950/30 px-3 py-2 text-xs text-red-300">
                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
              </div>
            )}
            {result ? (
              <>
                <div className="flex items-center gap-1.5 text-xs text-green-400"><CheckCircle2 className="h-3.5 w-3.5" /> Sample-only preview complete</div>
                <div>
                  <p className="mb-1 text-[11px] font-medium text-gray-400">Mapped flow variables — raw values</p>
                  <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded border border-gray-800 bg-[#0b0b0b] p-2 font-mono text-[11px] text-gray-300">{formatJSON(result.mapped_variables)}</pre>
                </div>
                <div>
                  <p className="mb-1 text-[11px] font-medium text-gray-400">Exact projected model JSON</p>
                  <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded border border-gray-800 bg-[#0b0b0b] p-2 font-mono text-[11px] text-gray-300">{formatJSON(result.llm_data)}</pre>
                </div>
              </>
            ) : (
              <div className="rounded border border-gray-800 bg-[#171717] p-3 text-xs text-gray-500">
                Preview shows mapping and the exact model payload only. It does not execute an API, MCP or Tool action.
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
