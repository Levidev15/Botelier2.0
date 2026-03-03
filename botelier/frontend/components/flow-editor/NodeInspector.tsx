"use client";

import { useState, useEffect } from "react";
import { Trash2, ChevronDown, ChevronRight, Plus, X, Variable } from "lucide-react";
import { 
  useFlowStore, 
  NodeData,
  InitialNodeData,
  MessageNodeData,
  CollectSlotNodeData,
  CollectFormNodeData,
  FormSlotConfig,
  APIRequestNodeData,
  ConditionNodeData,
  RouterNodeData,
  ConfirmationNodeData,
  SetVariableNodeData,
  TransferNodeData,
  EndNodeData,
  SlotType,
  NodeType,
  RouterOption,
  DeliveryMode,
} from "./store";

const slotTypes: { value: SlotType; label: string }[] = [
  { value: "text", label: "Text" },
  { value: "date", label: "Date" },
  { value: "number", label: "Number" },
  { value: "phone", label: "Phone Number" },
  { value: "email", label: "Email" },
  { value: "time", label: "Time" },
  { value: "choice", label: "Choice (Select)" },
];

const operators = [
  { value: "equals", label: "Equals" },
  { value: "not_equals", label: "Not Equals" },
  { value: "contains", label: "Contains" },
  { value: "greater_than", label: "Greater Than" },
  { value: "less_than", label: "Less Than" },
  { value: "is_empty", label: "Is Empty" },
  { value: "is_not_empty", label: "Has Value" },
];

function VariablesPanel() {
  const { variables, addVariable, updateVariable, deleteVariable } = useFlowStore();
  const [isExpanded, setIsExpanded] = useState(true);
  const [newVarKey, setNewVarKey] = useState("");

  const handleAddVariable = () => {
    if (newVarKey.trim()) {
      addVariable({
        key: newVarKey.trim().toLowerCase().replace(/\s+/g, "_"),
        type: "text",
        description: "",
        required: false,
      });
      setNewVarKey("");
    }
  };

  return (
    <div className="border-b border-gray-800 pb-4">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-2 w-full text-left text-sm font-medium text-gray-300 mb-2"
      >
        {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        <Variable className="h-4 w-4 text-purple-400" />
        Flow Variables ({variables.length})
      </button>

      {isExpanded && (
        <div className="space-y-2">
          {variables.map((v) => (
            <div key={v.key} className="flex items-center gap-2 bg-[#1a1a1a] rounded px-2 py-1.5">
              <span className="text-xs text-purple-400 font-mono flex-1">{`{{${v.key}}}`}</span>
              <span className="text-xs text-gray-500">{v.type}</span>
              <button
                onClick={() => deleteVariable(v.key)}
                className="text-gray-500 hover:text-red-400"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
          
          <div className="flex gap-2">
            <input
              type="text"
              value={newVarKey}
              onChange={(e) => setNewVarKey(e.target.value)}
              placeholder="variable_name"
              className="flex-1 bg-[#1a1a1a] border border-gray-700 rounded px-2 py-1 text-white text-xs focus:border-purple-500 focus:outline-none font-mono"
              onKeyDown={(e) => e.key === "Enter" && handleAddVariable()}
            />
            <button
              onClick={handleAddVariable}
              className="text-xs text-purple-400 hover:text-purple-300 px-2"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function InitialNodePanel({ data, nodeId }: { data: InitialNodeData; nodeId: string }) {
  const { updateNodeData } = useFlowStore();

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">System Prompt</label>
        <textarea
          value={data.systemPrompt || ""}
          onChange={(e) => updateNodeData(nodeId, { systemPrompt: e.target.value })}
          rows={4}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-green-500 focus:outline-none resize-none"
          placeholder="You are a helpful hotel assistant..."
        />
      </div>
      
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Greeting Message</label>
        <textarea
          value={data.greeting || ""}
          onChange={(e) => updateNodeData(nodeId, { greeting: e.target.value })}
          rows={3}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-green-500 focus:outline-none resize-none"
          placeholder="Hello! How may I assist you today?"
        />
      </div>
      
      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id="waitForResponse"
          checked={data.waitForResponse ?? true}
          onChange={(e) => updateNodeData(nodeId, { waitForResponse: e.target.checked })}
          className="w-4 h-4 bg-[#1a1a1a] border-gray-700 rounded text-green-500 focus:ring-green-500"
        />
        <label htmlFor="waitForResponse" className="text-sm text-gray-400">
          Wait for guest response before continuing
        </label>
      </div>
    </div>
  );
}

function MessageNodePanel({ data, nodeId }: { data: MessageNodeData; nodeId: string }) {
  const { updateNodeData, variables } = useFlowStore();
  const deliveryMode = data.deliveryMode || "guided";

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Message
          <span className="text-xs text-purple-400 ml-2">Use {"{{variable}}"} for dynamic content</span>
        </label>
        <textarea
          value={data.message || ""}
          onChange={(e) => updateNodeData(nodeId, { message: e.target.value })}
          rows={4}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none resize-none"
          placeholder="Your message here..."
        />
        
        {variables.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {variables.map((v) => (
              <button
                key={v.key}
                onClick={() => updateNodeData(nodeId, { message: (data.message || "") + `{{${v.key}}}` })}
                className="text-xs bg-purple-900/30 text-purple-400 rounded px-1.5 py-0.5 hover:bg-purple-900/50"
              >
                {`{{${v.key}}}`}
              </button>
            ))}
          </div>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Delivery Mode</label>
        <div className="flex gap-2">
          <button
            onClick={() => updateNodeData(nodeId, { deliveryMode: "guided" })}
            className={`flex-1 px-3 py-2 text-xs rounded-lg border transition ${
              deliveryMode === "guided"
                ? "bg-blue-600/20 border-blue-500 text-blue-400"
                : "bg-[#1a1a1a] border-gray-700 text-gray-400 hover:border-gray-600"
            }`}
          >
            <span className="font-medium">Guided</span>
            <p className="text-gray-500 mt-0.5">AI follows intent naturally</p>
          </button>
          <button
            onClick={() => updateNodeData(nodeId, { deliveryMode: "static" })}
            className={`flex-1 px-3 py-2 text-xs rounded-lg border transition ${
              deliveryMode === "static"
                ? "bg-blue-600/20 border-blue-500 text-blue-400"
                : "bg-[#1a1a1a] border-gray-700 text-gray-400 hover:border-gray-600"
            }`}
          >
            <span className="font-medium">Static</span>
            <p className="text-gray-500 mt-0.5">AI says exact text</p>
          </button>
        </div>
      </div>
      
      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id="waitForResponse"
          checked={data.waitForResponse ?? true}
          onChange={(e) => updateNodeData(nodeId, { waitForResponse: e.target.checked })}
          className="w-4 h-4 bg-[#1a1a1a] border-gray-700 rounded text-blue-500 focus:ring-blue-500"
        />
        <label htmlFor="waitForResponse" className="text-sm text-gray-400">
          Wait for guest response
        </label>
      </div>
    </div>
  );
}

function CollectSlotNodePanel({ data, nodeId }: { data: CollectSlotNodeData; nodeId: string }) {
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

const defaultPromptsByType: Record<SlotType, string> = {
  text: "May I have your name, please?",
  date: "What date would you prefer?",
  number: "How many would you like?",
  phone: "What's the best phone number to reach you?",
  email: "What's your email address?",
  time: "What time works best for you?",
  choice: "Which option would you prefer?",
};

const defaultRetryByType: Record<SlotType, string> = {
  text: "I didn't catch that. Could you please repeat?",
  date: "Please provide a valid date, for example, December 15th.",
  number: "Please tell me a number.",
  phone: "Could you please repeat your phone number?",
  email: "Please provide a valid email address.",
  time: "Please provide a valid time, like 3 PM or 15:00.",
  choice: "Please choose one of the available options.",
};

function CollectFormNodePanel({ data, nodeId }: { data: CollectFormNodeData; nodeId: string }) {
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
            No fields yet. Click "Add Field" to start.
          </div>
        )}
      </div>
    </div>
  );
}

interface AccountIntegration {
  id: string;
  integration_type_id: string;
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
    }>;
  };
  status: string;
}

function APIRequestNodePanel({ data, nodeId }: { data: APIRequestNodeData; nodeId: string }) {
  const { updateNodeData, variables } = useFlowStore();
  const api = data.api || { method: "GET" as const, url: "", apiSource: "custom" as const };
  const [showHeaders, setShowHeaders] = useState(
    !!(api.headers && Object.keys(api.headers).length > 0)
  );
  const [showResponseMapping, setShowResponseMapping] = useState(
    !!(api.responseMapping && Object.keys(api.responseMapping).length > 0)
  );
  const [integrations, setIntegrations] = useState<AccountIntegration[]>([]);
  const [loadingIntegrations, setLoadingIntegrations] = useState(false);

  useEffect(() => {
    const fetchIntegrations = async () => {
      setLoadingIntegrations(true);
      try {
        const response = await fetch("/api/integrations/connections");
        if (response.ok) {
          const data = await response.json();
          setIntegrations(data.filter((i: AccountIntegration) => i.status === "active"));
        }
      } catch (error) {
        console.error("Failed to fetch integrations:", error);
      } finally {
        setLoadingIntegrations(false);
      }
    };
    fetchIntegrations();
  }, []);

  const updateApi = (updates: Partial<typeof api>) => {
    updateNodeData(nodeId, { api: { ...api, ...updates } });
  };

  const selectedIntegration = integrations.find(i => i.id === api.integrationId);
  const selectedEndpoint = selectedIntegration?.integration_type.endpoints.find(e => e.id === api.endpointId);

  const handleIntegrationChange = (integrationId: string) => {
    const integration = integrations.find(i => i.id === integrationId);
    updateApi({
      integrationId,
      integrationSlug: integration?.integration_type.slug,
      endpointId: undefined,
      endpointName: undefined,
      url: "",
      method: "GET" as const,
      bodyTemplate: "",
    });
  };

  const handleEndpointChange = (endpointId: string) => {
    const endpoint = selectedIntegration?.integration_type.endpoints.find(e => e.id === endpointId);
    if (endpoint) {
      let bodyTemplate = "";
      if (endpoint.request_schema && (endpoint.method === "POST" || endpoint.method === "PUT")) {
        bodyTemplate = JSON.stringify(endpoint.request_schema, null, 2);
      }
      updateApi({
        endpointId,
        endpointName: endpoint.name,
        method: endpoint.method as "GET" | "POST" | "PUT" | "DELETE",
        url: endpoint.path,
        bodyTemplate,
      });
    }
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
                {loadingIntegrations ? "Loading..." : integrations.length === 0 ? "No integrations connected" : "Select integration..."}
              </option>
              {integrations.map((integration) => (
                <option key={integration.id} value={integration.id}>
                  {integration.integration_type.name}
                </option>
              ))}
            </select>
            {integrations.length === 0 && !loadingIntegrations && (
              <p className="text-xs text-gray-500 mt-1">
                Connect integrations in the Integrations page to use them here.
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
                {selectedIntegration.integration_type.endpoints.map((endpoint) => (
                  <option key={endpoint.id} value={endpoint.id}>
                    {endpoint.method} - {endpoint.name}
                  </option>
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
        <button
          onClick={() => setShowHeaders(!showHeaders)}
          className="flex items-center gap-2 text-sm font-medium text-gray-300"
        >
          {showHeaders ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          Headers
          {headerEntries.length > 0 && <span className="text-xs text-gray-500">({headerEntries.length})</span>}
        </button>

        {showHeaders && (
          <div className="mt-2 space-y-2">
            <p className="text-xs text-gray-500">Add custom HTTP headers for the request</p>
            {headerEntries.map(([key, value], i) => (
              <div key={i} className="flex gap-2 items-center">
                <input
                  type="text"
                  value={key}
                  onChange={(e) => updateHeader(key, e.target.value, value, i)}
                  className={smallInputCls}
                  placeholder="Header-Name"
                />
                <input
                  type="text"
                  value={value}
                  onChange={(e) => updateHeader(key, key, e.target.value, i)}
                  className={smallInputCls}
                  placeholder="value"
                />
                <button
                  onClick={() => removeHeader(i)}
                  className="text-red-400 hover:text-red-300 p-1"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
            <button
              onClick={addHeader}
              className="text-xs text-orange-400 hover:text-orange-300 flex items-center gap-1"
            >
              <Plus className="h-3 w-3" /> Add Header
            </button>
          </div>
        )}
      </div>
      
      {(api.method === "POST" || api.method === "PUT") && (
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
            placeholder='{"check_in": "{{check_in_date}}", "guests": {{guest_count}}}'
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
            <p className="text-xs text-gray-500">Extract response fields into flow variables (dot notation: data.guest.name)</p>
            {responseMappingEntries.map(([key, path], i) => (
              <div key={i} className="flex gap-2 items-center">
                <input
                  type="text"
                  value={key}
                  onChange={(e) => updateResponseMapping(key, e.target.value, path, i)}
                  className={smallInputCls}
                  placeholder="variable_name"
                />
                <span className="text-gray-500">=</span>
                <input
                  type="text"
                  value={path}
                  onChange={(e) => updateResponseMapping(key, key, e.target.value, i)}
                  className={smallInputCls}
                  placeholder="data.guest.name"
                />
                <button
                  onClick={() => removeResponseMapping(i)}
                  className="text-red-400 hover:text-red-300 p-1"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
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
          Response Instructions
        </label>
        <textarea
          value={api.responseInstructions || ""}
          onChange={(e) => updateApi({ responseInstructions: e.target.value })}
          rows={3}
          className={`${inputCls} resize-none text-xs`}
          placeholder="Tell the AI how to present the API response to the caller (e.g., 'Summarize the reservation details including room type, dates, and price')"
        />
        <p className="text-xs text-gray-500 mt-1">
          Instructions for how the AI should format and present the response
        </p>
      </div>
    </div>
  );
}

function ConditionNodePanel({ data, nodeId }: { data: ConditionNodeData; nodeId: string }) {
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

function RouterNodePanel({ data, nodeId }: { data: RouterNodeData; nodeId: string }) {
  const { updateNodeData, variables } = useFlowStore();
  const router = data.router || { variable: "", options: [] };

  const updateRouter = (updates: Partial<typeof router>) => {
    updateNodeData(nodeId, { router: { ...router, ...updates } });
  };

  const addOption = () => {
    const newOption: RouterOption = {
      id: `opt_${Date.now()}`,
      value: "",
      label: "",
    };
    updateRouter({ options: [...router.options, newOption] });
  };

  const updateOption = (id: string, updates: Partial<RouterOption>) => {
    updateRouter({
      options: router.options.map((opt) =>
        opt.id === id ? { ...opt, ...updates } : opt
      ),
    });
  };

  const removeOption = (id: string) => {
    updateRouter({
      options: router.options.filter((opt) => opt.id !== id),
    });
  };

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Variable to Route On</label>
        <select
          value={router.variable || ""}
          onChange={(e) => updateRouter({ variable: e.target.value })}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-indigo-500 focus:outline-none"
        >
          <option value="">Select variable...</option>
          {variables.map((v) => (
            <option key={v.key} value={v.key}>{v.key}</option>
          ))}
        </select>
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-medium text-gray-400">Route Options</label>
          <button
            onClick={addOption}
            className="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1"
          >
            <Plus className="h-3 w-3" />
            Add Option
          </button>
        </div>

        <div className="space-y-2">
          {router.options.map((option, index) => (
            <div key={option.id} className="flex items-center gap-2 bg-[#1a1a1a] rounded-lg p-2">
              <div className="flex-1 space-y-1">
                <input
                  type="text"
                  value={option.value}
                  onChange={(e) => updateOption(option.id, { value: e.target.value })}
                  placeholder="Match value (e.g., new)"
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white text-xs focus:border-indigo-500 focus:outline-none"
                />
                <input
                  type="text"
                  value={option.label}
                  onChange={(e) => updateOption(option.id, { label: e.target.value })}
                  placeholder="Display label (e.g., New Reservation)"
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white text-xs focus:border-indigo-500 focus:outline-none"
                />
              </div>
              <button
                onClick={() => removeOption(option.id)}
                className="text-gray-500 hover:text-red-400 p-1"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ))}

          {router.options.length === 0 && (
            <p className="text-xs text-gray-500 text-center py-2">
              No options yet. Click &quot;Add Option&quot; to add routing paths.
            </p>
          )}
        </div>
      </div>

      <div className="bg-[#1a1a1a] rounded-lg p-3 text-xs text-gray-400">
        <p className="font-medium text-gray-300 mb-1">Connection Guide:</p>
        <p>Each option creates a colored output handle at the bottom of the node.</p>
        <p className="mt-1">Connect each handle to the appropriate flow path.</p>
        <div className="flex items-center gap-2 mt-2">
          <span className="w-2 h-2 bg-gray-500 rounded-full" />
          <span>Gray handle = Default (no match)</span>
        </div>
      </div>
    </div>
  );
}

function ConfirmationNodePanel({ data, nodeId }: { data: ConfirmationNodeData; nodeId: string }) {
  const { updateNodeData, variables } = useFlowStore();
  const confirmation = data.confirmation || { 
    summaryTemplate: "", 
    confirmPrompt: "Is this correct?",
    editPrompt: "What would you like to change?",
    variablesToConfirm: [],
    allowEdit: true,
    deliveryMode: "guided" as DeliveryMode
  };
  const deliveryMode = confirmation.deliveryMode || "guided";

  const updateConfirmation = (updates: Partial<typeof confirmation>) => {
    updateNodeData(nodeId, { confirmation: { ...confirmation, ...updates } });
  };

  const toggleVariable = (varKey: string) => {
    const current = confirmation.variablesToConfirm || [];
    if (current.includes(varKey)) {
      updateConfirmation({ variablesToConfirm: current.filter(v => v !== varKey) });
    } else {
      updateConfirmation({ variablesToConfirm: [...current, varKey] });
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Variables to Confirm</label>
        <div className="flex flex-wrap gap-2">
          {variables.map((v) => (
            <button
              key={v.key}
              onClick={() => toggleVariable(v.key)}
              className={`text-xs rounded px-2 py-1 transition ${
                confirmation.variablesToConfirm?.includes(v.key)
                  ? "bg-emerald-600 text-white"
                  : "bg-gray-700 text-gray-300 hover:bg-gray-600"
              }`}
            >
              {v.key}
            </button>
          ))}
        </div>
        {variables.length === 0 && (
          <p className="text-xs text-gray-500">Add flow variables first</p>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Summary Template
          <span className="text-xs text-emerald-400 ml-2">Use {"{{variable}}"}</span>
        </label>
        <textarea
          value={confirmation.summaryTemplate || ""}
          onChange={(e) => updateConfirmation({ summaryTemplate: e.target.value })}
          rows={3}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-emerald-500 focus:outline-none resize-none"
          placeholder="Let me confirm: {{guest_name}}, checking in {{check_in_date}}..."
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Confirm Prompt</label>
        <input
          type="text"
          value={confirmation.confirmPrompt || ""}
          onChange={(e) => updateConfirmation({ confirmPrompt: e.target.value })}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-emerald-500 focus:outline-none"
          placeholder="Is this information correct?"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Delivery Mode</label>
        <div className="flex gap-2">
          <button
            onClick={() => updateConfirmation({ deliveryMode: "guided" })}
            className={`flex-1 px-3 py-2 text-xs rounded-lg border transition ${
              deliveryMode === "guided"
                ? "bg-emerald-600/20 border-emerald-500 text-emerald-400"
                : "bg-[#1a1a1a] border-gray-700 text-gray-400 hover:border-gray-600"
            }`}
          >
            <span className="font-medium">Guided</span>
            <p className="text-gray-500 mt-0.5">AI follows intent naturally</p>
          </button>
          <button
            onClick={() => updateConfirmation({ deliveryMode: "static" })}
            className={`flex-1 px-3 py-2 text-xs rounded-lg border transition ${
              deliveryMode === "static"
                ? "bg-emerald-600/20 border-emerald-500 text-emerald-400"
                : "bg-[#1a1a1a] border-gray-700 text-gray-400 hover:border-gray-600"
            }`}
          >
            <span className="font-medium">Static</span>
            <p className="text-gray-500 mt-0.5">AI says exact text</p>
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id="allowEdit"
          checked={confirmation.allowEdit ?? true}
          onChange={(e) => updateConfirmation({ allowEdit: e.target.checked })}
          className="w-4 h-4 bg-[#1a1a1a] border-gray-700 rounded text-emerald-500 focus:ring-emerald-500"
        />
        <label htmlFor="allowEdit" className="text-sm text-gray-400">
          Allow guest to edit (uses "Edit" output)
        </label>
      </div>

      {confirmation.allowEdit && (
        <div>
          <label className="block text-sm font-medium text-gray-400 mb-1">Edit Prompt</label>
          <input
            type="text"
            value={confirmation.editPrompt || ""}
            onChange={(e) => updateConfirmation({ editPrompt: e.target.value })}
            className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-emerald-500 focus:outline-none"
            placeholder="What would you like to change?"
          />
        </div>
      )}

      <div className="pt-2 border-t border-gray-800">
        <p className="text-xs text-gray-500">
          <span className="text-emerald-400">Confirmed</span> → proceeds to next step
          {confirmation.allowEdit && (
            <><br/><span className="text-red-400">Edit</span> → loops back to collect info</>
          )}
        </p>
      </div>
    </div>
  );
}

function SetVariableNodePanel({ data, nodeId }: { data: SetVariableNodeData; nodeId: string }) {
  const { updateNodeData, variables } = useFlowStore();
  const setVariable = data.setVariable || { 
    variableKey: "", 
    valueType: "static",
    value: ""
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

function TransferNodePanel({ data, nodeId }: { data: TransferNodeData; nodeId: string }) {
  const { updateNodeData } = useFlowStore();
  const transfer = data.transfer || { phoneNumber: "", preTransferMessage: "", transferMode: "warm" as const };

  const updateTransfer = (updates: Partial<typeof transfer>) => {
    updateNodeData(nodeId, { transfer: { ...transfer, ...updates } });
  };

  const transferMode = transfer.transferMode || "warm";

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Transfer To (Phone Number)</label>
        <input
          type="text"
          value={transfer.phoneNumber || ""}
          onChange={(e) => updateTransfer({ phoneNumber: e.target.value })}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-cyan-500 focus:outline-none"
          placeholder="+1234567890"
        />
      </div>
      
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Pre-Transfer Message</label>
        <textarea
          value={transfer.preTransferMessage || ""}
          onChange={(e) => updateTransfer({ preTransferMessage: e.target.value })}
          rows={2}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-cyan-500 focus:outline-none resize-none"
          placeholder="Let me connect you with our front desk team. Please hold."
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-2">Transfer Mode</label>
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => updateTransfer({ transferMode: "warm" })}
            className={`w-full text-left px-3 py-2.5 rounded-lg border transition-colors ${
              transferMode === "warm"
                ? "border-cyan-600 bg-cyan-900/20"
                : "border-gray-700 bg-[#1a1a1a] hover:border-gray-600"
            }`}
          >
            <div className="flex items-start gap-2">
              <div className={`mt-0.5 w-3.5 h-3.5 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                transferMode === "warm" ? "border-cyan-500" : "border-gray-600"
              }`}>
                {transferMode === "warm" && <div className="w-1.5 h-1.5 rounded-full bg-cyan-500" />}
              </div>
              <div>
                <div className="text-xs font-medium text-white">Warm Transfer</div>
                <div className="text-xs text-gray-500 mt-0.5">Twilio bridges both legs. Full logging and duration tracking. Standard charges apply.</div>
              </div>
            </div>
          </button>

          <button
            type="button"
            onClick={() => updateTransfer({ transferMode: "cold" })}
            className={`w-full text-left px-3 py-2.5 rounded-lg border transition-colors ${
              transferMode === "cold"
                ? "border-amber-600 bg-amber-900/20"
                : "border-gray-700 bg-[#1a1a1a] hover:border-gray-600"
            }`}
          >
            <div className="flex items-start gap-2">
              <div className={`mt-0.5 w-3.5 h-3.5 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                transferMode === "cold" ? "border-amber-500" : "border-gray-600"
              }`}>
                {transferMode === "cold" && <div className="w-1.5 h-1.5 rounded-full bg-amber-500" />}
              </div>
              <div>
                <div className="text-xs font-medium text-white">Cold Transfer (SIP REFER)</div>
                <div className="text-xs text-gray-500 mt-0.5">Twilio exits after handoff. No ongoing charges. Call outcome not tracked.</div>
              </div>
            </div>
          </button>
        </div>

        {transferMode === "cold" && (
          <div className="mt-2 flex items-start gap-1.5 px-2.5 py-2 bg-amber-950/30 border border-amber-800/40 rounded-lg">
            <span className="text-amber-500 text-xs flex-shrink-0 mt-0.5">⚠</span>
            <p className="text-xs text-amber-400">
              After transfer, Botelier can no longer monitor or log this call.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function EndNodePanel({ data, nodeId }: { data: EndNodeData; nodeId: string }) {
  const { updateNodeData, variables } = useFlowStore();

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Closing Message
          <span className="text-xs text-purple-400 ml-2">Use {"{{variable}}"} for dynamic content</span>
        </label>
        <textarea
          value={data.closingMessage || ""}
          onChange={(e) => updateNodeData(nodeId, { closingMessage: e.target.value })}
          rows={3}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-red-500 focus:outline-none resize-none"
          placeholder="Thank you for calling! Have a wonderful day."
        />
        
        {variables.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {variables.map((v) => (
              <button
                key={v.key}
                onClick={() => updateNodeData(nodeId, { closingMessage: (data.closingMessage || "") + `{{${v.key}}}` })}
                className="text-xs bg-purple-900/30 text-purple-400 rounded px-1.5 py-0.5 hover:bg-purple-900/50"
              >
                {`{{${v.key}}}`}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function NodeInspector() {
  const { selectedNode, updateNodeData, deleteNode } = useFlowStore();

  if (!selectedNode) {
    return (
      <div className="w-80 bg-[#141414] border-l border-gray-800 p-4">
        <VariablesPanel />
        <div className="mt-4 text-gray-400 text-sm">
          <p>Select a node to edit its properties</p>
        </div>
      </div>
    );
  }

  const nodeType = selectedNode.type as NodeType;
  const data = selectedNode.data;

  const renderNodePanel = () => {
    switch (nodeType) {
      case "initial":
        return <InitialNodePanel data={data as InitialNodeData} nodeId={selectedNode.id} />;
      case "message":
        return <MessageNodePanel data={data as MessageNodeData} nodeId={selectedNode.id} />;
      case "collect_slot":
        return <CollectSlotNodePanel data={data as CollectSlotNodeData} nodeId={selectedNode.id} />;
      case "collect_form":
        return <CollectFormNodePanel data={data as CollectFormNodeData} nodeId={selectedNode.id} />;
      case "api_request":
        return <APIRequestNodePanel data={data as APIRequestNodeData} nodeId={selectedNode.id} />;
      case "condition":
        return <ConditionNodePanel data={data as ConditionNodeData} nodeId={selectedNode.id} />;
      case "router":
        return <RouterNodePanel data={data as RouterNodeData} nodeId={selectedNode.id} />;
      case "confirmation":
        return <ConfirmationNodePanel data={data as ConfirmationNodeData} nodeId={selectedNode.id} />;
      case "set_variable":
        return <SetVariableNodePanel data={data as SetVariableNodeData} nodeId={selectedNode.id} />;
      case "transfer":
        return <TransferNodePanel data={data as TransferNodeData} nodeId={selectedNode.id} />;
      case "end":
        return <EndNodePanel data={data as EndNodeData} nodeId={selectedNode.id} />;
      default:
        return <div className="text-gray-400 text-sm">Unknown node type</div>;
    }
  };

  const nodeColors: Record<string, string> = {
    initial: "border-green-500",
    message: "border-blue-500",
    collect_slot: "border-purple-500",
    collect_form: "border-violet-500",
    api_request: "border-orange-500",
    condition: "border-yellow-500",
    router: "border-indigo-500",
    confirmation: "border-emerald-500",
    set_variable: "border-teal-500",
    transfer: "border-cyan-500",
    end: "border-red-500",
  };

  return (
    <div className="w-80 bg-[#141414] border-l border-gray-800 overflow-y-auto">
      <VariablesPanel />
      
      <div className={`p-4 border-b border-gray-800 flex items-center justify-between ${nodeColors[nodeType] || ""}`}>
        <h3 className="font-semibold text-white">Node Properties</h3>
        <button
          onClick={() => deleteNode(selectedNode.id)}
          className="p-1 text-gray-400 hover:text-red-400 transition"
          title="Delete node"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      <div className="p-4 space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-400 mb-1">Node Name</label>
          <input
            type="text"
            value={(data as any).name || ""}
            onChange={(e) => updateNodeData(selectedNode.id, { name: e.target.value })}
            className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>

        {renderNodePanel()}

        {/* Instructions field - shown for all node types */}
        <div className="pt-4 border-t border-gray-800">
          <label className="block text-sm font-medium text-gray-400 mb-1">
            AI Instructions
            <span className="text-xs text-gray-500 ml-2">(private)</span>
          </label>
          <textarea
            value={(data as any).instructions || ""}
            onChange={(e) => updateNodeData(selectedNode.id, { instructions: e.target.value })}
            rows={3}
            className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-gray-500 focus:outline-none resize-none"
            placeholder="e.g., Be empathetic, confirm date includes year, offer examples if guest seems confused..."
          />
          <p className="text-xs text-gray-500 mt-1">
            Private guidance for the AI on how to handle this step
          </p>
        </div>
      </div>
    </div>
  );
}
