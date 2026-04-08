"use client";

import { useFlowStore, SetVariableNodeData } from "../store";

interface Props {
  data: SetVariableNodeData;
  nodeId: string;
}

export default function SetVariableNodePanel({ data, nodeId }: Props) {
  const { updateNodeData, variables } = useFlowStore();
  const setVariable = data.setVariable || {
    variableKey: "",
    valueType: "static",
    value: "",
  };

  const updateSetVariable = (updates: Partial<typeof setVariable>) => {
    updateNodeData(nodeId, { setVariable: { ...setVariable, ...updates } });
  };

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Variable to Set</label>
        <select
          value={setVariable.variableKey || ""}
          onChange={(e) => updateSetVariable({ variableKey: e.target.value })}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-violet-500 focus:outline-none"
        >
          <option value="">Select variable...</option>
          {variables.map((v) => (
            <option key={v.key} value={v.key}>{v.key}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Value Type</label>
        <select
          value={setVariable.valueType || "static"}
          onChange={(e) => updateSetVariable({ valueType: e.target.value as any })}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-violet-500 focus:outline-none"
        >
          <option value="static">Static Value</option>
          <option value="template">Template (with variables)</option>
          <option value="expression">Expression</option>
        </select>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Value
          {setVariable.valueType === "template" && (
            <span className="text-xs text-violet-400 ml-2">Use {"{{variable}}"}</span>
          )}
        </label>
        {setVariable.valueType === "expression" ? (
          <textarea
            value={setVariable.value || ""}
            onChange={(e) => updateSetVariable({ value: e.target.value })}
            rows={2}
            className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm font-mono focus:border-violet-500 focus:outline-none resize-none"
            placeholder="guest_count * 2"
          />
        ) : (
          <input
            type="text"
            value={setVariable.value || ""}
            onChange={(e) => updateSetVariable({ value: e.target.value })}
            className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-violet-500 focus:outline-none"
            placeholder={setVariable.valueType === "template" ? "Hello, {{guest_name}}!" : "confirmed"}
          />
        )}
      </div>

      {setVariable.valueType === "template" && variables.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {variables.map((v) => (
            <button
              key={v.key}
              onClick={() => updateSetVariable({ value: (setVariable.value || "") + `{{${v.key}}}` })}
              className="text-xs bg-violet-900/30 text-violet-400 rounded px-1.5 py-0.5 hover:bg-violet-900/50"
            >
              {`{{${v.key}}}`}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
