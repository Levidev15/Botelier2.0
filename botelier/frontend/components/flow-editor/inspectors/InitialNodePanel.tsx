"use client";

import { useState } from "react";
import { AlertCircle } from "lucide-react";
import { useFlowStore, InitialNodeData } from "../store";
import GreetingCacheButton from "@/components/forms/GreetingCacheButton";
import { useQuoteSpeechPrivacy } from "../useQuoteSpeechPrivacy";

interface Props {
  data: InitialNodeData;
  nodeId: string;
  assistantId?: string;
  assistantTtsProvider?: string;
}

export default function InitialNodePanel({ data, nodeId, assistantId, assistantTtsProvider }: Props) {
  const { updateNodeData, isDirty } = useFlowStore();
  const { hasUnsafeText } = useQuoteSpeechPrivacy();
  const [speechError, setSpeechError] = useState<string | null>(null);
  const writeSpeech = (field: "systemPrompt" | "greeting", value: string) => {
    if (hasUnsafeText(value)) {
      setSpeechError("Keep quote-private URLs, fingerprints and raw quote values out of flow instructions and speech.");
      return;
    }
    setSpeechError(null);
    updateNodeData(nodeId, { [field]: value });
  };
  const unsafeStoredSpeech = hasUnsafeText(data.systemPrompt || "") || hasUnsafeText(data.greeting || "");

  const showCacheButton =
    !!assistantId && (assistantTtsProvider || "").toLowerCase() === "deepgram";

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">System Prompt</label>
        <textarea
          value={data.systemPrompt || ""}
          onChange={(e) => writeSpeech("systemPrompt", e.target.value)}
          rows={4}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-green-500 focus:outline-none resize-none"
          placeholder="Describe the AI's role and behavior..."
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Greeting Message</label>
        <textarea
          value={data.greeting || ""}
          onChange={(e) => writeSpeech("greeting", e.target.value)}
          rows={3}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-green-500 focus:outline-none resize-none"
          placeholder="Hello! How may I assist you today?"
        />
        {(speechError || unsafeStoredSpeech) && (
          <p role="alert" className="mt-1 flex items-start gap-1.5 text-[10px] text-amber-300">
            <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
            {speechError || "Existing greeting or system instructions reference quote-private data. Remove it before continuing."}
          </p>
        )}
        {showCacheButton && !hasUnsafeText(data.greeting || "") && (
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
