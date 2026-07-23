"use client";

import { useState, useEffect, useCallback } from "react";
import {
  X,
  Loader2,
  AlertCircle,
  CheckCircle,
  ChevronRight,
  Play,
  Send,
  Shield,
  Eye,
  ToggleLeft,
  ToggleRight,
  Search,
  RefreshCcw,
  Plus,
  Trash2,
} from "lucide-react";
import type { Operation, OperationPolicy, OperationVariable, ToolSet } from "../types";

interface OperationCatalogPanelProps {
  accountId: string;
  connectionId: string;
  connectionName: string;
  integrationName: string;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
  onNotify: (type: "success" | "error", message: string) => void;
  onClose: () => void;
}

const METHOD_COLORS: Record<string, string> = {
  GET: "bg-green-900/40 text-green-300 border-green-800",
  POST: "bg-blue-900/40 text-blue-300 border-blue-800",
  PUT: "bg-yellow-900/40 text-yellow-300 border-yellow-800",
  PATCH: "bg-orange-900/40 text-orange-300 border-orange-800",
  DELETE: "bg-red-900/40 text-red-300 border-red-800",
};

const TEST_STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  untested: { label: "Untested", cls: "text-gray-400 bg-gray-800/40 border-gray-700" },
  passed: { label: "Tested", cls: "text-green-300 bg-green-900/40 border-green-800" },
  failed: { label: "Test Failed", cls: "text-red-300 bg-red-900/40 border-red-800" },
};

const RISK_LEVELS = ["read", "write", "financial", "destructive", "admin", "sensitive"];
const CHANNELS = ["voice", "sms", "flow", "test"];

export default function OperationCatalogPanel({
  accountId,
  connectionId,
  connectionName,
  integrationName,
  authFetch,
  onNotify,
  onClose,
}: OperationCatalogPanelProps) {
  const [operations, setOperations] = useState<Operation[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedOp, setSelectedOp] = useState<Operation | null>(null);
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState<"policy" | "test" | "publish">("policy");

  const [policy, setPolicy] = useState<Partial<OperationPolicy>>({});
  const [savingPolicy, setSavingPolicy] = useState(false);

  const [testParams, setTestParams] = useState<Record<string, string>>({});
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    status_code: number | null;
    data: unknown;
    error_message: string | null;
    latency_ms: number | null;
  } | null>(null);

  const [toolSets, setToolSets] = useState<ToolSet[]>([]);
  const [selectedToolSetId, setSelectedToolSetId] = useState<string>("");
  const [publishing, setPublishing] = useState(false);

  const baseUrl = `/api/integrations/account/${accountId}/connection/${connectionId}`;

  const fetchOperations = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const res = await authFetch(`${baseUrl}/operations`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to load operations");
      setOperations(data.operations || []);
    } catch (err: any) {
      setLoadError(err?.message || "Failed to load operations");
    } finally {
      setLoading(false);
    }
  }, [accountId, connectionId]);

  const fetchToolSets = useCallback(async () => {
    try {
      const res = await authFetch(`/api/tool-sets?account_id=${accountId}`);
      if (res.ok) {
        const data = await res.json();
        setToolSets(data.tool_sets || []);
      }
    } catch {
      // non-fatal
    }
  }, [accountId]);

  useEffect(() => {
    fetchOperations();
    fetchToolSets();
  }, [fetchOperations, fetchToolSets]);

  const selectOperation = (op: Operation) => {
    setSelectedOp(op);
    setPolicy(op.policy || {});
    setTestParams({});
    setTestResult(null);
    setActiveTab("policy");
  };

  const refreshSelected = async (opId: string) => {
    const res = await authFetch(`${baseUrl}/operations`);
    if (!res.ok) return;
    const data = await res.json();
    const ops: Operation[] = data.operations || [];
    setOperations(ops);
    const updated = ops.find((o) => o.id === opId);
    if (updated) {
      setSelectedOp(updated);
      setPolicy(updated.policy || {});
    }
  };

  const handleSavePolicy = async () => {
    if (!selectedOp) return;
    setSavingPolicy(true);
    try {
      const res = await authFetch(
        `${baseUrl}/operations/${encodeURIComponent(selectedOp.id)}/policy`,
        {
          method: "PUT",
          body: JSON.stringify({
            enabled: policy.enabled ?? false,
            risk_level: policy.risk_level || null,
            confirm_required: policy.confirm_required ?? false,
            approval_required: policy.approval_required ?? false,
            max_executions_per_conv: policy.max_executions_per_conv || null,
            allowed_channels: policy.allowed_channels || null,
            response_size_bytes: policy.response_size_bytes ?? 32768,
            redact_field_patterns:
              policy.redact_field_patterns && policy.redact_field_patterns.length > 0
                ? policy.redact_field_patterns
                : null,
          }),
        }
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to save policy");
      onNotify("success", "Policy saved");
      await refreshSelected(selectedOp.id);
    } catch (err: any) {
      onNotify("error", err?.message || "Failed to save policy");
    } finally {
      setSavingPolicy(false);
    }
  };

  const handleTest = async () => {
    if (!selectedOp) return;
    setTesting(true);
    setTestResult(null);
    try {
      const res = await authFetch(
        `${baseUrl}/operations/${encodeURIComponent(selectedOp.id)}/test`,
        {
          method: "POST",
          body: JSON.stringify({ variables: testParams }),
        }
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Test failed");
      setTestResult({
        success: data.success,
        status_code: data.status_code,
        data: data.data,
        error_message: data.error_message,
        latency_ms: data.latency_ms,
      });
      await refreshSelected(selectedOp.id);
      if (data.success) onNotify("success", "Test passed");
    } catch (err: any) {
      onNotify("error", err?.message || "Test request failed");
    } finally {
      setTesting(false);
    }
  };

  const handlePublish = async () => {
    if (!selectedOp) return;
    setPublishing(true);
    try {
      const res = await authFetch(
        `${baseUrl}/operations/${encodeURIComponent(selectedOp.id)}/publish`,
        {
          method: "POST",
          body: JSON.stringify({ tool_set_id: selectedToolSetId || null }),
        }
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Publish failed");
      onNotify("success", `"${data.tool_name}" published as a tool`);
      await refreshSelected(selectedOp.id);
    } catch (err: any) {
      onNotify("error", err?.message || "Publish failed");
    } finally {
      setPublishing(false);
    }
  };

  const handleUnpublish = async () => {
    if (!selectedOp) return;
    setPublishing(true);
    try {
      const res = await authFetch(
        `${baseUrl}/operations/${encodeURIComponent(selectedOp.id)}/unpublish`,
        { method: "POST", body: JSON.stringify({}) }
      );
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Unpublish failed");
      }
      onNotify("success", "Tool unpublished");
      await refreshSelected(selectedOp.id);
    } catch (err: any) {
      onNotify("error", err?.message || "Unpublish failed");
    } finally {
      setPublishing(false);
    }
  };

  const llmParams = (selectedOp?.variables || []).filter(
    (v) => !v.ownership || v.ownership === "llm"
  );

  const filtered = operations.filter((op) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      op.id.toLowerCase().includes(q) ||
      (op.name || "").toLowerCase().includes(q) ||
      (op.path || "").toLowerCase().includes(q) ||
      (op.method || "").toLowerCase().includes(q)
    );
  });

  return (
    <div className="fixed inset-0 bg-black/80 z-50 flex">
      <div className="flex flex-col w-full h-full bg-[#0f0f0f]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800 flex-shrink-0">
          <div>
            <h2 className="text-lg font-semibold">{connectionName}</h2>
            <p className="text-sm text-gray-400">
              {integrationName} — Operation Catalog
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchOperations}
              disabled={loading}
              className="p-2 hover:bg-gray-800 rounded-lg transition"
              title="Refresh"
            >
              <RefreshCcw
                className={`h-4 w-4 text-gray-400 ${loading ? "animate-spin" : ""}`}
              />
            </button>
            <button
              onClick={onClose}
              className="p-2 hover:bg-gray-800 rounded-lg transition"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        <div className="flex flex-1 min-h-0">
          {/* Left: operation list */}
          <div className="w-80 flex-shrink-0 border-r border-gray-800 flex flex-col">
            <div className="p-3 border-b border-gray-800">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Filter operations…"
                  className="w-full pl-8 pr-3 py-1.5 bg-[#1a1a1a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-blue-600"
                />
              </div>
            </div>

            <div className="flex-1 overflow-y-auto">
              {loading && (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
                </div>
              )}
              {loadError && (
                <div className="m-3 p-3 rounded-lg border border-red-800 bg-red-900/20 text-sm text-red-300 flex items-start gap-2">
                  <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
                  <span>{loadError}</span>
                </div>
              )}
              {!loading && filtered.length === 0 && (
                <div className="py-12 text-center text-sm text-gray-500">
                  {search ? "No operations match" : "No operations found"}
                </div>
              )}
              {filtered.map((op, opIdx) => {
                const isSelected = selectedOp?.id === op.id;
                const testBadge =
                  TEST_STATUS_BADGE[op.policy?.test_status || "untested"];
                return (
                  <button
                    key={`${op.id}-${opIdx}`}
                    onClick={() => selectOperation(op)}
                    className={`relative w-full text-left px-3 py-3 border-b border-gray-900 transition-colors ${
                      isSelected ? "bg-[#1a2030]" : "hover:bg-[#141414]"
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold border ${
                          METHOD_COLORS[op.method?.toUpperCase() || ""] ||
                          "bg-gray-800 text-gray-300 border-gray-700"
                        }`}
                      >
                        {op.method?.toUpperCase() || "?"}
                      </span>
                      {op.is_published && (
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] border bg-purple-900/40 text-purple-300 border-purple-800">
                          Live
                        </span>
                      )}
                      {op.policy?.enabled && !op.is_published && (
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] border bg-blue-900/30 text-blue-300 border-blue-800">
                          Enabled
                        </span>
                      )}
                      {isSelected && (
                        <ChevronRight className="h-3.5 w-3.5 text-gray-500 ml-auto" />
                      )}
                    </div>
                    <p className="text-xs font-mono text-gray-300 truncate pr-4">
                      {op.path}
                    </p>
                    {op.name && op.name !== op.id && (
                      <p className="text-xs text-gray-500 truncate mt-0.5">{op.name}</p>
                    )}
                    <div className="flex items-center gap-1 mt-1.5">
                      <span
                        className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] border ${testBadge.cls}`}
                      >
                        {testBadge.label}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>

            <div className="px-3 py-2 border-t border-gray-800 text-xs text-gray-500">
              {filtered.length} of {operations.length} operation
              {operations.length !== 1 ? "s" : ""} ·{" "}
              {operations.filter((o) => o.is_published).length} live
            </div>
          </div>

          {/* Right: detail panel */}
          {selectedOp ? (
            <div className="flex-1 flex flex-col min-h-0">
              {/* Operation header */}
              <div className="px-6 py-4 border-b border-gray-800 flex-shrink-0">
                <div className="flex items-center gap-3 mb-1 flex-wrap">
                  <span
                    className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-semibold border ${
                      METHOD_COLORS[selectedOp.method?.toUpperCase() || ""] ||
                      "bg-gray-800 text-gray-300 border-gray-700"
                    }`}
                  >
                    {selectedOp.method?.toUpperCase() || "?"}
                  </span>
                  <code className="text-sm text-gray-200 font-mono">
                    {selectedOp.path}
                  </code>
                  {selectedOp.is_published && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs border bg-purple-900/40 text-purple-300 border-purple-800">
                      <CheckCircle className="h-3 w-3" />
                      Published as tool
                    </span>
                  )}
                </div>
                {(selectedOp.summary || selectedOp.description) && (
                  <p className="text-sm text-gray-400 mt-1">
                    {selectedOp.summary || selectedOp.description}
                  </p>
                )}
              </div>

              {/* Tabs */}
              <div className="flex border-b border-gray-800 px-6 flex-shrink-0">
                {(["policy", "test", "publish"] as const).map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                      activeTab === tab
                        ? "border-blue-500 text-white"
                        : "border-transparent text-gray-400 hover:text-white"
                    }`}
                  >
                    {tab === "policy" ? (
                      <span className="flex items-center gap-1.5">
                        <Shield className="h-3.5 w-3.5" />
                        Policy
                      </span>
                    ) : tab === "test" ? (
                      <span className="flex items-center gap-1.5">
                        <Play className="h-3.5 w-3.5" />
                        Test
                      </span>
                    ) : (
                      <span className="flex items-center gap-1.5">
                        <Send className="h-3.5 w-3.5" />
                        Publish
                      </span>
                    )}
                  </button>
                ))}
              </div>

              {/* Tab content */}
              <div className="flex-1 overflow-y-auto p-6">
                {activeTab === "policy" && (
                  <PolicyTab
                    policy={policy}
                    onChange={setPolicy}
                    onSave={handleSavePolicy}
                    saving={savingPolicy}
                  />
                )}
                {activeTab === "test" && (
                  <TestTab
                    llmParams={llmParams}
                    testParams={testParams}
                    onChange={setTestParams}
                    onRun={handleTest}
                    testing={testing}
                    result={testResult}
                  />
                )}
                {activeTab === "publish" && (
                  <PublishTab
                    operation={selectedOp}
                    toolSets={toolSets}
                    selectedToolSetId={selectedToolSetId}
                    onSelectToolSet={setSelectedToolSetId}
                    onPublish={handlePublish}
                    onUnpublish={handleUnpublish}
                    publishing={publishing}
                  />
                )}
              </div>
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
              <div className="text-center">
                <Eye className="h-8 w-8 mx-auto mb-3 text-gray-600" />
                <p>Select an operation to configure it</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---- Policy Tab ----

function PolicyTab({
  policy,
  onChange,
  onSave,
  saving,
}: {
  policy: Partial<OperationPolicy>;
  onChange: (p: Partial<OperationPolicy>) => void;
  onSave: () => void;
  saving: boolean;
}) {
  const set = (key: keyof OperationPolicy, value: unknown) =>
    onChange({ ...policy, [key]: value });

  const toggleChannel = (ch: string) => {
    const current = policy.allowed_channels || null;
    if (!current) {
      onChange({ ...policy, allowed_channels: CHANNELS.filter((c) => c !== ch) });
    } else if (current.includes(ch)) {
      const next = current.filter((c) => c !== ch);
      onChange({ ...policy, allowed_channels: next.length === 0 ? null : next });
    } else {
      const next = [...current, ch];
      onChange({
        ...policy,
        allowed_channels: next.length === CHANNELS.length ? null : next,
      });
    }
  };

  const isChannelAllowed = (ch: string) =>
    !policy.allowed_channels || policy.allowed_channels.includes(ch);

  return (
    <div className="space-y-6 max-w-lg">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium">Enabled</p>
          <p className="text-xs text-gray-500 mt-0.5">
            Allow this operation to run in agent flows
          </p>
        </div>
        <button onClick={() => set("enabled", !policy.enabled)}>
          {policy.enabled ? (
            <ToggleRight className="h-7 w-7 text-blue-400" />
          ) : (
            <ToggleLeft className="h-7 w-7 text-gray-600" />
          )}
        </button>
      </div>

      <div>
        <label className="block text-sm font-medium mb-1.5">Risk Level</label>
        <select
          value={policy.risk_level || ""}
          onChange={(e) => set("risk_level", e.target.value || null)}
          className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
        >
          <option value="">— not set —</option>
          {RISK_LEVELS.map((r) => (
            <option key={r} value={r}>
              {r.charAt(0).toUpperCase() + r.slice(1)}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-3">
        <p className="text-sm font-medium">Guards</p>
        <div className="flex items-center justify-between py-2 border-b border-gray-800">
          <div>
            <p className="text-sm">Confirm required</p>
            <p className="text-xs text-gray-500">AI must confirm with the user before running</p>
          </div>
          <button onClick={() => set("confirm_required", !policy.confirm_required)}>
            {policy.confirm_required ? (
              <ToggleRight className="h-7 w-7 text-blue-400" />
            ) : (
              <ToggleLeft className="h-7 w-7 text-gray-600" />
            )}
          </button>
        </div>
        <div className="flex items-center justify-between py-2 border-b border-gray-800">
          <div>
            <p className="text-sm">Human approval required</p>
            <p className="text-xs text-gray-500">Execution blocked until a human approves</p>
          </div>
          <button onClick={() => set("approval_required", !policy.approval_required)}>
            {policy.approval_required ? (
              <ToggleRight className="h-7 w-7 text-blue-400" />
            ) : (
              <ToggleLeft className="h-7 w-7 text-gray-600" />
            )}
          </button>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium mb-1.5">
          Max executions per conversation{" "}
          <span className="text-gray-500 font-normal">(optional)</span>
        </label>
        <input
          type="number"
          min={1}
          value={policy.max_executions_per_conv ?? ""}
          onChange={(e) =>
            set("max_executions_per_conv", e.target.value ? parseInt(e.target.value) : null)
          }
          placeholder="Unlimited"
          className="w-40 px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
        />
      </div>

      <div>
        <p className="text-sm font-medium mb-2">
          Allowed Channels{" "}
          <span className="text-gray-500 font-normal text-xs">(all if none selected)</span>
        </p>
        <div className="flex flex-wrap gap-2">
          {CHANNELS.map((ch) => (
            <button
              key={ch}
              onClick={() => toggleChannel(ch)}
              className={`px-3 py-1 rounded text-sm border transition-colors ${
                isChannelAllowed(ch)
                  ? "bg-blue-600 border-blue-500 text-white"
                  : "bg-[#0a0a0a] border-gray-700 text-gray-400"
              }`}
            >
              {ch}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium mb-1.5">
          Response size limit (bytes)
        </label>
        <input
          type="number"
          min={1024}
          step={1024}
          value={policy.response_size_bytes ?? 32768}
          onChange={(e) =>
            set("response_size_bytes", parseInt(e.target.value) || 32768)
          }
          className="w-40 px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
        />
      </div>

      <RedactPatternsEditor
        patterns={policy.redact_field_patterns || []}
        onChange={(patterns) => set("redact_field_patterns", patterns.length ? patterns : null)}
      />

      <div className="pt-2">
        <button
          onClick={onSave}
          disabled={saving}
          className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition disabled:opacity-50"
        >
          {saving ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Saving…
            </>
          ) : (
            "Save Policy"
          )}
        </button>
      </div>
    </div>
  );
}

// ---- Redact Patterns Editor ----

function RedactPatternsEditor({
  patterns,
  onChange,
}: {
  patterns: string[];
  onChange: (patterns: string[]) => void;
}) {
  const [draft, setDraft] = useState("");

  const add = () => {
    const trimmed = draft.trim();
    if (!trimmed || patterns.includes(trimmed)) return;
    onChange([...patterns, trimmed]);
    setDraft("");
  };

  const remove = (idx: number) => {
    onChange(patterns.filter((_, i) => i !== idx));
  };

  return (
    <div>
      <div className="mb-1.5">
        <p className="text-sm font-medium">Redact field patterns</p>
        <p className="text-xs text-gray-500 mt-0.5">
          Regex patterns matched against response field names. Matching fields are
          replaced with <code className="text-gray-400">***</code> before the AI sees
          the response.
        </p>
      </div>

      <div className="space-y-1.5 mb-2">
        {patterns.length === 0 && (
          <p className="text-xs text-gray-600 italic">No patterns — nothing is redacted</p>
        )}
        {patterns.map((p, i) => (
          <div
            key={i}
            className="flex items-center gap-2 px-2.5 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg"
          >
            <code className="flex-1 text-xs text-gray-300 font-mono truncate">{p}</code>
            <button
              onClick={() => remove(i)}
              className="text-gray-600 hover:text-red-400 transition"
              title="Remove pattern"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.preventDefault(); add(); }
          }}
          placeholder="e.g. credit_card|cvv|ssn"
          className="flex-1 px-3 py-1.5 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm font-mono focus:outline-none focus:ring-1 focus:ring-blue-600"
        />
        <button
          onClick={add}
          disabled={!draft.trim()}
          className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-white bg-gray-700 hover:bg-gray-600 rounded-lg transition disabled:opacity-40"
        >
          <Plus className="h-3.5 w-3.5" />
          Add
        </button>
      </div>
    </div>
  );
}

// ---- Test Tab ----

function TestTab({
  llmParams,
  testParams,
  onChange,
  onRun,
  testing,
  result,
}: {
  llmParams: OperationVariable[];
  testParams: Record<string, string>;
  onChange: (p: Record<string, string>) => void;
  onRun: () => void;
  testing: boolean;
  result: {
    success: boolean;
    status_code: number | null;
    data: unknown;
    error_message: string | null;
    latency_ms: number | null;
  } | null;
}) {
  return (
    <div className="space-y-5 max-w-lg">
      <div>
        <p className="text-sm font-medium mb-1">Test Parameters</p>
        <p className="text-xs text-gray-500 mb-4">
          Only LLM-owned parameters are shown. Connection secrets and fixed values
          are injected automatically.
        </p>
        {llmParams.length === 0 ? (
          <p className="text-sm text-gray-500 italic">
            No LLM parameters for this operation
          </p>
        ) : (
          <div className="space-y-3">
            {llmParams.map((param) => (
              <div key={param.name}>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  {param.name}
                  {param.required && <span className="text-red-400 ml-1">*</span>}
                  <span className="text-gray-600 font-normal ml-2 text-xs">
                    ({param.type})
                  </span>
                </label>
                {param.enum && param.enum.length > 0 ? (
                  <select
                    value={testParams[param.name] || ""}
                    onChange={(e) =>
                      onChange({ ...testParams, [param.name]: e.target.value })
                    }
                    className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                  >
                    <option value="">— choose —</option>
                    {param.enum.map((v) => (
                      <option key={v} value={v}>
                        {v}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={testParams[param.name] || ""}
                    onChange={(e) =>
                      onChange({ ...testParams, [param.name]: e.target.value })
                    }
                    placeholder={param.description || param.name}
                    className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                  />
                )}
                {param.description && (
                  <p className="text-xs text-gray-500 mt-1">{param.description}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <button
        onClick={onRun}
        disabled={testing}
        className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-green-700 hover:bg-green-600 rounded-lg transition disabled:opacity-50"
      >
        {testing ? (
          <>
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            Running…
          </>
        ) : (
          <>
            <Play className="h-4 w-4 mr-2" />
            Run Test
          </>
        )}
      </button>

      {result && (
        <div
          className={`rounded-lg border p-4 space-y-3 ${
            result.success
              ? "border-green-800 bg-green-900/20"
              : "border-red-800 bg-red-900/20"
          }`}
        >
          <div className="flex items-center gap-3 text-sm flex-wrap">
            {result.success ? (
              <CheckCircle className="h-4 w-4 text-green-400 flex-shrink-0" />
            ) : (
              <AlertCircle className="h-4 w-4 text-red-400 flex-shrink-0" />
            )}
            <span className={result.success ? "text-green-300" : "text-red-300"}>
              {result.success ? "Test passed" : "Test failed"}
            </span>
            {result.status_code != null && (
              <span className="text-gray-400 text-xs font-mono">
                HTTP {result.status_code}
              </span>
            )}
            {result.latency_ms != null && (
              <span className="text-gray-400 text-xs">{result.latency_ms}ms</span>
            )}
          </div>
          {result.error_message && (
            <p className="text-sm text-red-300">{result.error_message}</p>
          )}
          {result.data != null && (
            <div>
              <p className="text-xs text-gray-500 mb-1">Response</p>
              <pre className="text-xs bg-[#0a0a0a] border border-gray-800 rounded p-3 text-gray-300 overflow-x-auto max-h-64 whitespace-pre-wrap">
                {typeof result.data === "string"
                  ? result.data
                  : JSON.stringify(result.data, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---- Publish Tab ----

function PublishTab({
  operation,
  toolSets,
  selectedToolSetId,
  onSelectToolSet,
  onPublish,
  onUnpublish,
  publishing,
}: {
  operation: Operation;
  toolSets: ToolSet[];
  selectedToolSetId: string;
  onSelectToolSet: (id: string) => void;
  onPublish: () => void;
  onUnpublish: () => void;
  publishing: boolean;
}) {
  const testStatus = operation.policy?.test_status || "untested";

  return (
    <div className="space-y-6 max-w-lg">
      <div className="rounded-lg border border-gray-800 bg-[#141414] p-4 space-y-3">
        <p className="text-sm font-medium">Operation Status</p>
        <div className="space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-gray-400">Enabled</span>
            <span className={operation.policy?.enabled ? "text-green-300" : "text-gray-500"}>
              {operation.policy?.enabled ? "Yes" : "No"}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-400">Test status</span>
            <span
              className={
                testStatus === "passed"
                  ? "text-green-300"
                  : testStatus === "failed"
                  ? "text-red-300"
                  : "text-gray-500"
              }
            >
              {testStatus === "passed"
                ? "Passed"
                : testStatus === "failed"
                ? "Failed"
                : "Not tested"}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-400">Published</span>
            <span
              className={operation.is_published ? "text-purple-300" : "text-gray-500"}
            >
              {operation.is_published ? "Yes — live as tool" : "No"}
            </span>
          </div>
        </div>
      </div>

      {!operation.is_published && (
        <>
          <div>
            <label className="block text-sm font-medium mb-1.5">
              Assign to Tool Set{" "}
              <span className="text-gray-500 font-normal">(optional)</span>
            </label>
            <select
              value={selectedToolSetId}
              onChange={(e) => onSelectToolSet(e.target.value)}
              className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
            >
              <option value="">— no tool set (publish without assignment) —</option>
              {toolSets.map((ts) => (
                <option key={ts.id} value={ts.id}>
                  {ts.name}
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-500 mt-1">
              Assign now or add the tool to a tool set later from the Tools page
            </p>
          </div>

          {testStatus !== "passed" && (
            <div className="flex items-start gap-2 p-3 bg-yellow-900/20 border border-yellow-800 rounded-lg">
              <AlertCircle className="h-4 w-4 text-yellow-400 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-yellow-300">
                This operation has not passed a test yet. Run a test first to confirm it
                works before publishing.
              </p>
            </div>
          )}

          <button
            onClick={onPublish}
            disabled={publishing || testStatus !== "passed"}
            className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-purple-700 hover:bg-purple-600 rounded-lg transition disabled:opacity-50"
          >
            {publishing ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Publishing…
              </>
            ) : (
              <>
                <Send className="h-4 w-4 mr-2" />
                Publish as Tool
              </>
            )}
          </button>
        </>
      )}

      {operation.is_published && (
        <div className="space-y-4">
          <div className="flex items-start gap-2 p-3 bg-purple-900/20 border border-purple-800 rounded-lg">
            <CheckCircle className="h-4 w-4 text-purple-400 flex-shrink-0 mt-0.5" />
            <p className="text-sm text-purple-300">
              This operation is live. Assistants with the assigned tool set can call it.
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5">
              Reassign to Tool Set{" "}
              <span className="text-gray-500 font-normal">(optional)</span>
            </label>
            <select
              value={selectedToolSetId}
              onChange={(e) => onSelectToolSet(e.target.value)}
              className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
            >
              <option value="">— no tool set —</option>
              {toolSets.map((ts) => (
                <option key={ts.id} value={ts.id}>
                  {ts.name}
                </option>
              ))}
            </select>
          </div>
          <div className="flex gap-2 flex-wrap">
            <button
              onClick={onPublish}
              disabled={publishing}
              className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-purple-700 hover:bg-purple-600 rounded-lg transition disabled:opacity-50"
            >
              {publishing ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Republishing…
                </>
              ) : (
                "Republish / Reassign"
              )}
            </button>
            <button
              onClick={onUnpublish}
              disabled={publishing}
              className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-red-800 hover:bg-red-700 rounded-lg transition disabled:opacity-50"
            >
              Unpublish Tool
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
