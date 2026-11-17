"use client";

import { useState } from "react";
import { AlertCircle } from "lucide-react";
import { useFlowStore, EndNodeData } from "../store";
import { useQuoteSpeechPrivacy } from "../useQuoteSpeechPrivacy";

interface Props {
  data: EndNodeData;
  nodeId: string;
}

export default function EndNodePanel({ data, nodeId }: Props) {
  const { updateNodeData, variables } = useFlowStore();
  const { safeVariables, hasUnsafeText } = useQuoteSpeechPrivacy(nodeId);
  const [speechError, setSpeechError] = useState<string | null>(null);
  const safeFlowVariables = safeVariables(variables);
  const unsafeStoredMessage = hasUnsafeText(data.closingMessage);
  const updateClosingMessage = (value: string) => {
    if (hasUnsafeText(value)) {
      setSpeechError("Keep quote-private URLs, fingerprints and raw quote values out of spoken output.");
      return;
    }
    setSpeechError(null);
    updateNodeData(nodeId, { closingMessage: value });
  };

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Closing Message
          <span className="text-xs text-purple-400 ml-2">Use {"{{variable}}"} for dynamic content</span>
        </label>
        <textarea
          value={data.closingMessage || ""}
          onChange={(e) => updateClosingMessage(e.target.value)}
          rows={3}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-red-500 focus:outline-none resize-none"
          placeholder="Thank you for calling! Have a wonderful day."
        />

        {(speechError || unsafeStoredMessage) && (
          <p role="alert" className="mt-1 flex items-start gap-1.5 text-[10px] text-amber-300">
            <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
            {speechError || "Existing closing text references quote-private data. Remove it before continuing."}
          </p>
        )}
        {safeFlowVariables.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {safeFlowVariables.map((v) => (
              <button
                type="button"
                key={v.key}
                onClick={() => updateClosingMessage((data.closingMessage || "") + `{{${v.key}}}`)}
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
