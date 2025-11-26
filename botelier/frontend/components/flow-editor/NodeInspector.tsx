"use client";

import { useState } from "react";
import { Trash2, ChevronDown, ChevronRight, Plus, X, Variable } from "lucide-react";
import { 
  useFlowStore, 
  NodeData,
  InitialNodeData,
  MessageNodeData,
  CollectSlotNodeData,
  APIRequestNodeData,
  ConditionNodeData,
  TransferNodeData,
  EndNodeData,
  SlotType,
  NodeType,
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
    </div>
  );
}

function MessageNodePanel({ data, nodeId }: { data: MessageNodeData; nodeId: string }) {
  const { updateNodeData, variables } = useFlowStore();

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
  const { updateNodeData, addVariable } = useFlowStore();
  const slot = data.slot || { variableKey: "", prompt: "", type: "text" as SlotType };

  const updateSlot = (updates: Partial<typeof slot>) => {
    updateNodeData(nodeId, { slot: { ...slot, ...updates } });
  };

  const handleVariableKeyChange = (key: string) => {
    const sanitized = key.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "");
    updateSlot({ variableKey: sanitized });
    if (sanitized) {
      addVariable({
        key: sanitized,
        type: slot.type,
        description: `Collected from: ${data.name}`,
        required: true,
      });
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-sm font-medium text-gray-400 mb-1">Variable Name</label>
          <input
            type="text"
            value={slot.variableKey || ""}
            onChange={(e) => handleVariableKeyChange(e.target.value)}
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

function APIRequestNodePanel({ data, nodeId }: { data: APIRequestNodeData; nodeId: string }) {
  const { updateNodeData, variables } = useFlowStore();
  const api = data.api || { method: "GET" as const, url: "" };
  const [showResponseMapping, setShowResponseMapping] = useState(false);

  const updateApi = (updates: Partial<typeof api>) => {
    updateNodeData(nodeId, { api: { ...api, ...updates } });
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2">
        <div>
          <label className="block text-sm font-medium text-gray-400 mb-1">Method</label>
          <select
            value={api.method}
            onChange={(e) => updateApi({ method: e.target.value as typeof api.method })}
            className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-orange-500 focus:outline-none"
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
            className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-orange-500 focus:outline-none font-mono text-xs"
            placeholder="https://api.example.com/endpoint"
          />
        </div>
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
            className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-orange-500 focus:outline-none resize-none font-mono text-xs"
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
        </button>
        
        {showResponseMapping && (
          <div className="mt-2 space-y-2">
            <p className="text-xs text-gray-500">Map response fields to variables</p>
            {Object.entries(api.responseMapping || {}).map(([key, path], i) => (
              <div key={i} className="flex gap-2">
                <input
                  type="text"
                  value={key}
                  className="flex-1 bg-[#1a1a1a] border border-gray-700 rounded px-2 py-1 text-white text-xs focus:border-orange-500 focus:outline-none font-mono"
                  placeholder="variable_name"
                  readOnly
                />
                <span className="text-gray-500">=</span>
                <input
                  type="text"
                  value={path}
                  className="flex-1 bg-[#1a1a1a] border border-gray-700 rounded px-2 py-1 text-white text-xs focus:border-orange-500 focus:outline-none font-mono"
                  placeholder="response.data.id"
                  readOnly
                />
              </div>
            ))}
          </div>
        )}
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

function TransferNodePanel({ data, nodeId }: { data: TransferNodeData; nodeId: string }) {
  const { updateNodeData } = useFlowStore();
  const transfer = data.transfer || { phoneNumber: "", preTransferMessage: "" };

  const updateTransfer = (updates: Partial<typeof transfer>) => {
    updateNodeData(nodeId, { transfer: { ...transfer, ...updates } });
  };

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
      
      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id="warmTransfer"
          checked={transfer.warmTransfer ?? false}
          onChange={(e) => updateTransfer({ warmTransfer: e.target.checked })}
          className="w-4 h-4 bg-[#1a1a1a] border-gray-700 rounded text-cyan-500 focus:ring-cyan-500"
        />
        <label htmlFor="warmTransfer" className="text-sm text-gray-400">
          Warm transfer (brief human before connecting)
        </label>
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
      case "api_request":
        return <APIRequestNodePanel data={data as APIRequestNodeData} nodeId={selectedNode.id} />;
      case "condition":
        return <ConditionNodePanel data={data as ConditionNodeData} nodeId={selectedNode.id} />;
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
    api_request: "border-orange-500",
    condition: "border-yellow-500",
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
      </div>
    </div>
  );
}
