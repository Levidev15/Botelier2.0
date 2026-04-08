"use client";

import { useFlowStore, EndNodeData } from "../store";

interface Props {
  data: EndNodeData;
  nodeId: string;
}

export default function EndNodePanel({ data, nodeId }: Props) {
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
