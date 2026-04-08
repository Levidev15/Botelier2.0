"use client";

import { useFlowStore, ConfirmationNodeData, DeliveryMode } from "../store";

interface Props {
  data: ConfirmationNodeData;
  nodeId: string;
}

export default function ConfirmationNodePanel({ data, nodeId }: Props) {
  const { updateNodeData, variables } = useFlowStore();
  const confirmation = data.confirmation || {
    summaryTemplate: "",
    confirmPrompt: "Is this correct?",
    editPrompt: "What would you like to change?",
    variablesToConfirm: [],
    allowEdit: true,
    deliveryMode: "guided" as DeliveryMode,
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
          Allow guest to edit (uses &quot;Edit&quot; output)
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
