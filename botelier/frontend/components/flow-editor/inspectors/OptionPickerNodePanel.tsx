"use client";

import { Plus, X, AlertTriangle } from "lucide-react";
import { useFlowStore, OptionPickerNodeData, OptionPickerConfig, OptionPickerWrite } from "../store";

interface Props {
  data: OptionPickerNodeData;
  nodeId: string;
}

export default function OptionPickerNodePanel({ data, nodeId }: Props) {
  const { updateNodeData, variables } = useFlowStore();

  const picker: OptionPickerConfig = data.optionPicker || {
    sourceVariable: "",
    labelPath: "",
    prompt: "",
    retryPrompt: "",
    maxRetries: 3,
    writes: [],
  };

  const update = (patch: Partial<OptionPickerConfig>) =>
    updateNodeData(nodeId, { optionPicker: { ...picker, ...patch } });

  const writes = picker.writes || [];

  const addWrite = () => {
    const newWrite: OptionPickerWrite = { variableKey: "", path: "" };
    update({ writes: [...writes, newWrite] });
  };

  const updateWrite = (index: number, patch: Partial<OptionPickerWrite>) => {
    update({
      writes: writes.map((w, i) => (i === index ? { ...w, ...patch } : w)),
    });
  };

  const removeWrite = (index: number) => {
    update({ writes: writes.filter((_, i) => i !== index) });
  };

  const duplicateKeys = writes
    .map((w) => w.variableKey)
    .filter((key, i, arr) => key && arr.indexOf(key) !== i);

  return (
    <div className="space-y-4">
      {/* Source array variable */}
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Source list variable
        </label>
        <select
          value={picker.sourceVariable || ""}
          onChange={(e) => update({ sourceVariable: e.target.value })}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-teal-500 focus:outline-none"
        >
          <option value="">Select variable...</option>
          {variables.map((v) => (
            <option key={v.key} value={v.key}>{v.key}</option>
          ))}
        </select>
        <p className="mt-1 text-xs text-gray-500">
          The array of items the caller is choosing from — usually produced by an earlier API Request's response mapping.
        </p>
      </div>

      {/* Label path */}
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Label field (dot-path)
        </label>
        <input
          type="text"
          value={picker.labelPath || ""}
          onChange={(e) => update({ labelPath: e.target.value })}
          placeholder="e.g. name, or rate.name"
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm font-mono focus:border-teal-500 focus:outline-none"
        />
        <p className="mt-1 text-xs text-gray-500">
          Field inside each item used to match what the caller says by name, and to confirm the pick back to them.
        </p>
      </div>

      {/* Prompt */}
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Prompt
        </label>
        <textarea
          value={picker.prompt || ""}
          onChange={(e) => update({ prompt: e.target.value })}
          rows={2}
          placeholder="Which one would you like?"
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-teal-500 focus:outline-none resize-none"
        />
      </div>

      {/* Retry prompt + max retries */}
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Retry prompt <span className="text-gray-600 font-normal">(optional)</span>
        </label>
        <textarea
          value={picker.retryPrompt || ""}
          onChange={(e) => update({ retryPrompt: e.target.value })}
          rows={2}
          placeholder="Sorry, which option was that — the first or the second?"
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-teal-500 focus:outline-none resize-none"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Max retries
        </label>
        <input
          type="number"
          min={1}
          value={picker.maxRetries ?? 3}
          onChange={(e) => update({ maxRetries: Math.max(1, parseInt(e.target.value, 10) || 1) })}
          className="w-24 bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-teal-500 focus:outline-none"
        />
      </div>

      {/* Writes list */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-medium text-gray-400">Bind fields to variables</label>
          <button
            onClick={addWrite}
            className="text-xs text-teal-400 hover:text-teal-300 flex items-center gap-1"
          >
            <Plus className="h-3 w-3" />
            Add binding
          </button>
        </div>

        <div className="space-y-2">
          {writes.map((write, index) => (
            <div key={index} className="flex items-center gap-2 bg-[#1a1a1a] rounded-lg p-2">
              <div className="flex-1 space-y-1">
                <select
                  value={write.variableKey}
                  onChange={(e) => updateWrite(index, { variableKey: e.target.value })}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white text-xs focus:border-teal-500 focus:outline-none"
                >
                  <option value="">Select variable to write...</option>
                  {variables.map((v) => (
                    <option key={v.key} value={v.key}>{v.key}</option>
                  ))}
                </select>
                <input
                  type="text"
                  value={write.path}
                  onChange={(e) => updateWrite(index, { path: e.target.value })}
                  placeholder="Field path (e.g. rate.code) — blank = whole item"
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white text-xs font-mono focus:border-teal-500 focus:outline-none"
                />
              </div>
              <button
                onClick={() => removeWrite(index)}
                className="text-gray-500 hover:text-red-400 p-1"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ))}

          {writes.length === 0 && (
            <p className="text-xs text-gray-500 text-center py-2">
              No bindings yet. Add one for each piece of the chosen item you need later in the flow.
            </p>
          )}
        </div>
      </div>

      {duplicateKeys.length > 0 && (
        <div className="rounded-lg border border-yellow-700/30 bg-yellow-900/10 p-3 space-y-1">
          <div className="flex items-center gap-1.5 text-xs text-yellow-400/80">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span className="font-medium">Duplicate destination variable</span>
          </div>
          <p className="text-[11px] text-yellow-500/60">
            {Array.from(new Set(duplicateKeys)).join(", ")} — each bound variable should appear only once.
          </p>
        </div>
      )}

      <div className="bg-[#1a1a1a] rounded-lg p-3 text-xs text-gray-400">
        <p className="font-medium text-gray-300 mb-1">Connection guide:</p>
        <div className="flex items-center gap-2 mt-1">
          <span className="w-2 h-2 bg-teal-500 rounded-full" />
          <span>Teal handle = Selected (a valid pick was bound)</span>
        </div>
        <div className="flex items-center gap-2 mt-1">
          <span className="w-2 h-2 bg-gray-500 rounded-full" />
          <span>Gray handle = Fallback (optional — after max retries fail)</span>
        </div>
        <p className="mt-2 text-gray-500">
          The caller can select by spoken name or by position ("the first one"). Every bound
          variable is rewritten in full on each selection, so choosing again later safely
          replaces the earlier pick.
        </p>
      </div>
    </div>
  );
}
