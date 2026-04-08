"use client";

import { useState, useEffect } from "react";
import { useFlowStore, CollectSlotNodeData, SlotType } from "../store";
import { slotTypes } from "./shared";

interface Props {
  data: CollectSlotNodeData;
  nodeId: string;
}

export default function CollectSlotNodePanel({ data, nodeId }: Props) {
  const { updateNodeData, addVariable, updateVariable, variables } = useFlowStore();
  const slot = data.slot || { variableKey: "", prompt: "", type: "text" as SlotType };
  const [localVarKey, setLocalVarKey] = useState(slot.variableKey || "");

  useEffect(() => {
    setLocalVarKey(slot.variableKey || "");
  }, [nodeId, slot.variableKey]);

  const updateSlot = (updates: Partial<typeof slot>) => {
    const newSlot = { ...slot, ...updates };
    updateNodeData(nodeId, { slot: newSlot });

    if (updates.type && newSlot.variableKey) {
      updateVariable(newSlot.variableKey, { type: updates.type });
    }
  };

  const handleVariableKeyInput = (key: string) => {
    const sanitized = key.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "");
    setLocalVarKey(sanitized);
  };

  const commitVariableKey = () => {
    const key = localVarKey.trim();
    if (key && key !== slot.variableKey) {
      updateNodeData(nodeId, { slot: { ...slot, variableKey: key } });
      const existingVar = variables.find(v => v.key === key);
      if (!existingVar) {
        addVariable({
          key,
          type: slot.type,
          description: `Collected from: ${data.name}`,
          required: true,
        });
      } else {
        updateVariable(key, { type: slot.type });
      }
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-sm font-medium text-gray-400 mb-1">Variable Name</label>
          <input
            type="text"
            value={localVarKey}
            onChange={(e) => handleVariableKeyInput(e.target.value)}
            onBlur={commitVariableKey}
            onKeyDown={(e) => e.key === "Enter" && commitVariableKey()}
            className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-purple-500 focus:outline-none font-mono"
            placeholder="guest_name"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-400 mb-1">Type</label>
          <select
            value={slot.type || "text"}
            onChange={(e) => updateSlot({ type: e.target.value as SlotType })}
            className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-purple-500 focus:outline-none"
          >
            {slotTypes.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Question Prompt</label>
        <textarea
          value={slot.prompt || ""}
          onChange={(e) => updateSlot({ prompt: e.target.value })}
          rows={2}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-purple-500 focus:outline-none resize-none"
          placeholder="May I have your name, please?"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Retry Prompt (if invalid)</label>
        <textarea
          value={slot.retryPrompt || ""}
          onChange={(e) => updateSlot({ retryPrompt: e.target.value })}
          rows={2}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-purple-500 focus:outline-none resize-none"
          placeholder="I didn't catch that. Could you please repeat?"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Max Retries</label>
        <input
          type="number"
          value={slot.maxRetries || 3}
          onChange={(e) => updateSlot({ maxRetries: parseInt(e.target.value) || 3 })}
          min={1}
          max={10}
          className="w-20 bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-purple-500 focus:outline-none"
        />
      </div>

      {slot.type === "number" && (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">Min Value</label>
            <input
              type="number"
              value={slot.validation?.min ?? ""}
              onChange={(e) => updateSlot({
                validation: { ...slot.validation, min: e.target.value ? parseInt(e.target.value) : undefined }
              })}
              className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-purple-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">Max Value</label>
            <input
              type="number"
              value={slot.validation?.max ?? ""}
              onChange={(e) => updateSlot({
                validation: { ...slot.validation, max: e.target.value ? parseInt(e.target.value) : undefined }
              })}
              className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-purple-500 focus:outline-none"
            />
          </div>
        </div>
      )}

      {slot.type === "choice" && (
        <div>
          <label className="block text-sm font-medium text-gray-400 mb-1">Options (comma separated)</label>
          <input
            type="text"
            value={slot.validation?.choices?.join(", ") || ""}
            onChange={(e) => updateSlot({
              validation: { ...slot.validation, choices: e.target.value.split(",").map(s => s.trim()).filter(Boolean) }
            })}
            className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-purple-500 focus:outline-none"
            placeholder="Option 1, Option 2, Option 3"
          />
        </div>
      )}
    </div>
  );
}
