"use client";

import { useFlowStore, MessageNodeData } from "../store";

interface Props {
  data: MessageNodeData;
  nodeId: string;
}

export default function MessageNodePanel({ data, nodeId }: Props) {
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
