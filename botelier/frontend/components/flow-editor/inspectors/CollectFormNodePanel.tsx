"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Plus, Trash2 } from "lucide-react";
import { useFlowStore, CollectFormNodeData, FormSlotConfig, SlotType } from "../store";
import { slotTypes, defaultPromptsByType, defaultRetryByType } from "./shared";

interface Props {
  data: CollectFormNodeData;
  nodeId: string;
}

export default function CollectFormNodePanel({ data, nodeId }: Props) {
  const { updateNodeData, addVariable, variables } = useFlowStore();
  const slots = data.slots || [];
  const [expandedSlot, setExpandedSlot] = useState<string | null>(null);
  const [draggedSlot, setDraggedSlot] = useState<string | null>(null);

  const sortedSlots = [...slots].sort((a, b) => a.order - b.order);

  const addSlot = () => {
    const newSlot: FormSlotConfig = {
      id: `slot_${Date.now()}`,
      order: slots.length,
      variableKey: `field_${slots.length + 1}`,
      prompt: "What would you like to provide?",
      type: "text",
      retryPrompt: "I didn't catch that. Could you please repeat?",
      maxRetries: 3,
    };
    updateNodeData(nodeId, { slots: [...slots, newSlot] });
    setExpandedSlot(newSlot.id);
  };

  const updateSlot = (slotId: string, updates: Partial<FormSlotConfig>) => {
    const newSlots = slots.map((s) => {
      if (s.id !== slotId) return s;
      const updated = { ...s, ...updates };
      if (updates.type && !updates.prompt) {
        updated.prompt = defaultPromptsByType[updates.type];
        updated.retryPrompt = defaultRetryByType[updates.type];
      }
      return updated;
    });
    updateNodeData(nodeId, { slots: newSlots });
  };

  const removeSlot = (slotId: string) => {
    const newSlots = slots
      .filter((s) => s.id !== slotId)
      .map((s, i) => ({ ...s, order: i }));
    updateNodeData(nodeId, { slots: newSlots });
    if (expandedSlot === slotId) setExpandedSlot(null);
  };

  const commitVariableKey = (slotId: string, key: string) => {
    const sanitized = key.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "");
    if (!sanitized) return;

    const slot = slots.find((s) => s.id === slotId);
    if (!slot) return;

    updateSlot(slotId, { variableKey: sanitized });

    const existingVar = variables.find((v) => v.key === sanitized);
    if (!existingVar) {
      addVariable({
        key: sanitized,
        type: slot.type,
        description: `Collected from form: ${data.name}`,
        required: true,
      });
    }
  };

  const handleDragStart = (slotId: string) => {
    setDraggedSlot(slotId);
  };

  const handleDragOver = (e: React.DragEvent, targetSlotId: string) => {
    e.preventDefault();
    if (!draggedSlot || draggedSlot === targetSlotId) return;
  };

  const handleDrop = (targetSlotId: string) => {
    if (!draggedSlot || draggedSlot === targetSlotId) return;

    const dragIndex = slots.findIndex((s) => s.id === draggedSlot);
    const dropIndex = slots.findIndex((s) => s.id === targetSlotId);

    const newSlots = [...slots];
    const [removed] = newSlots.splice(dragIndex, 1);
    newSlots.splice(dropIndex, 0, removed);

    const reordered = newSlots.map((s, i) => ({ ...s, order: i }));
    updateNodeData(nodeId, { slots: reordered });
    setDraggedSlot(null);
  };

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Intro Message
          <span className="text-xs text-gray-500 ml-2">(optional)</span>
        </label>
        <textarea
          value={data.introMessage || ""}
          onChange={(e) => updateNodeData(nodeId, { introMessage: e.target.value })}
          rows={2}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-violet-500 focus:outline-none resize-none"
          placeholder="I'll need to collect a few details from you..."
        />
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-sm font-medium text-gray-400">
            Form Fields ({sortedSlots.length})
          </label>
          <button
            onClick={addSlot}
            className="flex items-center gap-1 text-xs text-violet-400 hover:text-violet-300"
          >
            <Plus className="h-3 w-3" />
            Add Field
          </button>
        </div>

        <div className="space-y-2">
          {sortedSlots.map((slot, index) => (
            <div
              key={slot.id}
              draggable
              onDragStart={() => handleDragStart(slot.id)}
              onDragOver={(e) => handleDragOver(e, slot.id)}
              onDrop={() => handleDrop(slot.id)}
              className={`bg-[#1a1a1a] rounded-lg border transition-all ${
                draggedSlot === slot.id
                  ? "border-violet-500 opacity-50"
                  : expandedSlot === slot.id
                  ? "border-violet-500"
                  : "border-gray-700"
              }`}
            >
              <div
                onClick={() => setExpandedSlot(expandedSlot === slot.id ? null : slot.id)}
                className="flex items-center gap-2 px-3 py-2 cursor-pointer"
              >
                <div className="flex items-center justify-center w-5 h-5 rounded-full bg-violet-600/40 text-violet-300 text-xs font-medium cursor-grab">
                  {index + 1}
                </div>
                <span className="text-sm text-white flex-1 truncate font-mono">
                  {slot.variableKey}
                </span>
                <span className="text-xs text-gray-500 bg-gray-800 px-1.5 py-0.5 rounded">
                  {slot.type}
                </span>
                {expandedSlot === slot.id ? (
                  <ChevronDown className="h-4 w-4 text-gray-400" />
                ) : (
                  <ChevronRight className="h-4 w-4 text-gray-400" />
                )}
              </div>

              {expandedSlot === slot.id && (
                <div className="px-3 pb-3 space-y-3 border-t border-gray-800 mt-1 pt-3">
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">Variable</label>
                      <input
                        type="text"
                        value={slot.variableKey}
                        onChange={(e) => updateSlot(slot.id, { variableKey: e.target.value })}
                        onBlur={(e) => commitVariableKey(slot.id, e.target.value)}
                        className="w-full bg-[#0a0a0a] border border-gray-700 rounded px-2 py-1.5 text-white text-xs focus:border-violet-500 focus:outline-none font-mono"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">Type</label>
                      <select
                        value={slot.type}
                        onChange={(e) => updateSlot(slot.id, { type: e.target.value as SlotType })}
                        className="w-full bg-[#0a0a0a] border border-gray-700 rounded px-2 py-1.5 text-white text-xs focus:border-violet-500 focus:outline-none"
                      >
                        {slotTypes.map((t) => (
                          <option key={t.value} value={t.value}>{t.label}</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Question Prompt</label>
                    <textarea
                      value={slot.prompt}
                      onChange={(e) => updateSlot(slot.id, { prompt: e.target.value })}
                      rows={2}
                      className="w-full bg-[#0a0a0a] border border-gray-700 rounded px-2 py-1.5 text-white text-xs focus:border-violet-500 focus:outline-none resize-none"
                    />
                  </div>

                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Retry Prompt</label>
                    <textarea
                      value={slot.retryPrompt || ""}
                      onChange={(e) => updateSlot(slot.id, { retryPrompt: e.target.value })}
                      rows={2}
                      className="w-full bg-[#0a0a0a] border border-gray-700 rounded px-2 py-1.5 text-white text-xs focus:border-violet-500 focus:outline-none resize-none"
                    />
                  </div>

                  {slot.type === "number" && (
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-xs text-gray-500 mb-1">Min</label>
                        <input
                          type="number"
                          value={slot.validation?.min ?? ""}
                          onChange={(e) => updateSlot(slot.id, {
                            validation: { ...slot.validation, min: e.target.value ? parseInt(e.target.value) : undefined }
                          })}
                          className="w-full bg-[#0a0a0a] border border-gray-700 rounded px-2 py-1.5 text-white text-xs focus:border-violet-500 focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-gray-500 mb-1">Max</label>
                        <input
                          type="number"
                          value={slot.validation?.max ?? ""}
                          onChange={(e) => updateSlot(slot.id, {
                            validation: { ...slot.validation, max: e.target.value ? parseInt(e.target.value) : undefined }
                          })}
                          className="w-full bg-[#0a0a0a] border border-gray-700 rounded px-2 py-1.5 text-white text-xs focus:border-violet-500 focus:outline-none"
                        />
                      </div>
                    </div>
                  )}

                  {slot.type === "choice" && (
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">Options (comma separated)</label>
                      <input
                        type="text"
                        value={slot.validation?.choices?.join(", ") || ""}
                        onChange={(e) => updateSlot(slot.id, {
                          validation: { ...slot.validation, choices: e.target.value.split(",").map(s => s.trim()).filter(Boolean) }
                        })}
                        className="w-full bg-[#0a0a0a] border border-gray-700 rounded px-2 py-1.5 text-white text-xs focus:border-violet-500 focus:outline-none"
                        placeholder="Option 1, Option 2, Option 3"
                      />
                    </div>
                  )}

                  <button
                    onClick={() => removeSlot(slot.id)}
                    className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300"
                  >
                    <Trash2 className="h-3 w-3" />
                    Remove Field
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>

        {sortedSlots.length === 0 && (
          <div className="text-center py-4 text-gray-500 text-sm">
            No fields yet. Click &quot;Add Field&quot; to start.
          </div>
        )}
      </div>
    </div>
  );
}
