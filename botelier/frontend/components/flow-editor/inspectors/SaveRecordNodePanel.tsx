"use client";

import { useEffect, useState } from "react";
import { Phone, Info } from "lucide-react";
import { useFlowStore, SaveRecordNodeData } from "../store";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { collectFlowVariables, findCompatibleRecordSources } from "../flowEditorData";

interface Props {
  data: SaveRecordNodeData;
  nodeId: string;
}

interface RTField {
  key: string;
  label: string;
  type: string;
  required?: boolean;
}

interface RTStatus {
  value: string;
  label: string;
}

interface RecordTypeLite {
  id: string;
  name: string;
  fields: RTField[];
  status_options: RTStatus[];
  is_active: boolean;
}

export default function SaveRecordNodePanel({ data, nodeId }: Props) {
  const { updateNodeData, variables } = useFlowStore();
  const nodes = useFlowStore((state) => state.nodes);
  const edges = useFlowStore((state) => state.edges);
  const availableVariables = collectFlowVariables(variables, nodes);
  const { accountId } = useAccountContext();
  const { authFetch } = useAuthToken();

  const saveRecord = data.saveRecord || {
    recordTypeId: "",
    recordTypeName: "",
    mapping: {},
    status: "",
  };

  const [recordTypes, setRecordTypes] = useState<RecordTypeLite[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    if (!accountId) {
      setRecordTypes([]);
      setLoading(false);
      return () => { active = false; };
    }
    (async () => {
      try {
        setLoading(true);
        setLoadError(null);
        const res = await authFetch(`/api/record-types?account_id=${accountId}`);
        if (!res.ok) throw new Error("Could not load Record types.");
        const json = await res.json();
        if (active) setRecordTypes(Array.isArray(json) ? json : []);
      } catch {
        if (active) {
          setRecordTypes([]);
          setLoadError("Could not load Record types.");
        }
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [accountId, authFetch]);

  const selectedType = recordTypes.find((t) => t.id === saveRecord.recordTypeId) || null;
  const compatibleSources = findCompatibleRecordSources(nodes, edges, nodeId, saveRecord.recordTypeId);

  const update = (updates: Partial<typeof saveRecord>) => {
    updateNodeData(nodeId, { saveRecord: { ...saveRecord, ...updates } });
  };

  const onSelectType = (id: string) => {
    const rt = recordTypes.find((t) => t.id === id);
    update({
      recordTypeId: id,
      recordTypeName: rt?.name || "",
      mapping: {},
      status: "",
    });
  };

  const setMapping = (fieldKey: string, value: string) => {
    const next = { ...(saveRecord.mapping || {}) };
    if (value) next[fieldKey] = value;
    else delete next[fieldKey];
    update({ mapping: next });
  };

  const inputCls =
    "w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-rose-500 focus:outline-none";

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2 text-xs text-gray-400 bg-rose-900/10 border border-rose-800/30 rounded-lg px-3 py-2">
        <Phone className="h-3.5 w-3.5 text-rose-400 mt-0.5 shrink-0" />
        <span>
          Save Record runs during <span className="text-rose-300">voice calls only</span>. It
          writes a record when this step is reached.
        </span>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Record Type</label>
        <select
          value={saveRecord.recordTypeId || ""}
          onChange={(e) => onSelectType(e.target.value)}
          className={inputCls}
          disabled={loading}
        >
          <option value="">{loading ? "Loading…" : "Select record type…"}</option>
          {recordTypes.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
              {!t.is_active ? " (inactive)" : ""}
            </option>
          ))}
        </select>
        {!loading && recordTypes.length === 0 && (
          <p className="text-xs text-gray-500 mt-1">
            No record types defined yet. Create one under Records → Manage Types.
          </p>
        )}
        {loadError && <p role="alert" className="mt-1 text-xs text-red-400">{loadError}</p>}
      </div>

      {selectedType && (
        <>
          <div className="rounded-lg border border-gray-800 bg-[#111111] p-3">
            <label className="block text-sm font-medium text-gray-300 mb-1">Record action</label>
            <select
              value={saveRecord.updateSourceNodeId || ""}
              onChange={(event) => update({ updateSourceNodeId: event.target.value || undefined })}
              className={inputCls}
              aria-label="Record create or update source"
            >
              <option value="">Create a new Record</option>
              {compatibleSources.map((source) => (
                <option key={source.id} value={source.id}>
                  Update Record created by {source.data.name || source.id}
                </option>
              ))}
            </select>
            {saveRecord.updateSourceNodeId && !compatibleSources.some((source) => source.id === saveRecord.updateSourceNodeId) ? (
              <p role="alert" className="mt-1 text-xs text-amber-300">
                The selected create node is no longer reachable or compatible. Choose a valid source or select Create a new Record.
              </p>
            ) : (
              <p className="mt-1 text-[11px] text-gray-500">
                Updates require a reachable earlier create node using this same Record type. Otherwise this step creates a new Record.
              </p>
            )}
          </div>
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <label className="block text-sm font-medium text-gray-400">Field Mapping</label>
              <span className="text-xs text-gray-500">— use {"{{variable}}"}</span>
            </div>
            {selectedType.fields.length === 0 && (
              <p className="text-xs text-gray-500">This record type has no columns yet.</p>
            )}
            <div className="space-y-3">
              {selectedType.fields.map((f) => (
                <div key={f.key}>
                  <label className="block text-xs text-gray-400 mb-1">
                    {f.label || f.key}
                    {f.required && <span className="text-rose-400 ml-0.5">*</span>}
                  </label>
                  <input
                    type="text"
                    value={saveRecord.mapping?.[f.key] || ""}
                    onChange={(e) => setMapping(f.key, e.target.value)}
                    placeholder={`e.g. {{${availableVariables[0]?.key || "variable"}}}`}
                    className={inputCls}
                  />
                  {availableVariables.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {availableVariables.map((v) => (
                        <button
                          key={v.key}
                          onClick={() =>
                            setMapping(
                              f.key,
                              (saveRecord.mapping?.[f.key] || "") + `{{${v.key}}}`
                            )
                          }
                          className="text-xs bg-rose-900/30 text-rose-300 rounded px-1.5 py-0.5 hover:bg-rose-900/50"
                        >
                          {`{{${v.key}}}`}{v.origin === "mapped" ? " · mapped JSON" : ""}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {selectedType.status_options.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">
                Status <span className="text-xs text-gray-500">(optional)</span>
              </label>
              <select
                value={saveRecord.status || ""}
                onChange={(e) => update({ status: e.target.value })}
                className={inputCls}
              >
                <option value="">— None —</option>
                {selectedType.status_options.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="flex items-start gap-2 text-xs text-gray-500">
            <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <span>
              Empty mappings are skipped. Values are resolved from collected variables at the
              moment this step runs.
            </span>
          </div>
        </>
      )}
    </div>
  );
}
