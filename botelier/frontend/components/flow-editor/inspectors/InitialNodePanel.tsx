"use client";

import { useFlowStore, InitialNodeData } from "../store";
import GreetingCacheButton from "@/components/forms/GreetingCacheButton";

interface Props {
  data: InitialNodeData;
  nodeId: string;
  assistantId?: string;
  assistantTtsProvider?: string;
}

export default function InitialNodePanel({ data, nodeId, assistantId, assistantTtsProvider }: Props) {
  const { updateNodeData, isDirty } = useFlowStore();

  const showCacheButton =
    !!assistantId && (assistantTtsProvider || "").toLowerCase() === "deepgram";

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
        {showCacheButton && (
          <GreetingCacheButton
            assistantId={assistantId!}
            hasUnsavedChanges={isDirty}
            greetingText={data.greeting || undefined}
          />
        )}
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
