"use client";

import { Plus, X } from "lucide-react";
import { useFlowStore, RouterNodeData, RouterOption } from "../store";

interface Props {
  data: RouterNodeData;
  nodeId: string;
}

export default function RouterNodePanel({ data, nodeId }: Props) {
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
          {router.options.map((option) => (
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
