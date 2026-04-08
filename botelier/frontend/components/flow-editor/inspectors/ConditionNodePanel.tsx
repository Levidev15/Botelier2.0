"use client";

import { useFlowStore, ConditionNodeData } from "../store";
import { operators } from "./shared";

interface Props {
  data: ConditionNodeData;
  nodeId: string;
}

export default function ConditionNodePanel({ data, nodeId }: Props) {
  const { updateNodeData, variables } = useFlowStore();
  const condition = data.condition || { variable: "", operator: "equals" as const, value: "" };

  const updateCondition = (updates: Partial<typeof condition>) => {
    updateNodeData(nodeId, { condition: { ...condition, ...updates } });
  };

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Variable to Check</label>
        <select
          value={condition.variable || ""}
          onChange={(e) => updateCondition({ variable: e.target.value })}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-yellow-500 focus:outline-none"
        >
          <option value="">Select variable...</option>
          {variables.map((v) => (
            <option key={v.key} value={v.key}>{v.key}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Operator</label>
        <select
          value={condition.operator}
          onChange={(e) => updateCondition({ operator: e.target.value as typeof condition.operator })}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-yellow-500 focus:outline-none"
        >
          {operators.map((op) => (
            <option key={op.value} value={op.value}>{op.label}</option>
          ))}
        </select>
      </div>

      {!["is_empty", "is_not_empty"].includes(condition.operator) && (
        <div>
          <label className="block text-sm font-medium text-gray-400 mb-1">Compare Value</label>
          <input
            type="text"
            value={condition.value || ""}
            onChange={(e) => updateCondition({ value: e.target.value })}
            className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-yellow-500 focus:outline-none"
            placeholder="true, 5, available, etc."
          />
        </div>
      )}

      <div className="bg-[#1a1a1a] rounded-lg p-3 text-xs text-gray-400">
        <p className="font-medium text-gray-300 mb-1">Connection Guide:</p>
        <div className="flex items-center gap-2 mb-1">
          <span className="w-2 h-2 bg-green-500 rounded-full" />
          <span>Green handle = True (condition met)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 bg-red-500 rounded-full" />
          <span>Red handle = False (condition not met)</span>
        </div>
      </div>
    </div>
  );
}
