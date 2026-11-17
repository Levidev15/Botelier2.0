"use client";

import { useState } from "react";
import { AlertCircle } from "lucide-react";
import { useFlowStore, MessageNodeData } from "../store";
import { collectFlowVariables, findQuoteSpeechProtections, hasQuotePrivateSpeech } from "../flowEditorData";

interface Props {
  data: MessageNodeData;
  nodeId: string;
}

export default function MessageNodePanel({ data, nodeId }: Props) {
  const { updateNodeData, variables, nodes, edges } = useFlowStore();
  const [speechError, setSpeechError] = useState<string | null>(null);
  const deliveryMode = data.deliveryMode || "guided";
  const flowVariables = collectFlowVariables(variables, nodes);
  const quoteProtection = findQuoteSpeechProtections(nodes, edges, nodeId);
  const protectedKeys = new Set([
    ...quoteProtection.privateVariables,
    ...quoteProtection.fingerprintVariables,
    ...quoteProtection.rawQuoteVariables,
  ]);
  const spokenContent = data.message || "";
  const containsProtectedReference = (value: string) => hasQuotePrivateSpeech(value, quoteProtection);
  const messageError = containsProtectedReference(spokenContent)
    ? "A quote fingerprint, raw quote or private checkout URL cannot be included in spoken text."
    : null;
  const updateMessage = (value: string) => {
    if (protectedKeys.size && containsProtectedReference(value)) {
      setSpeechError("Keep the quote fingerprint, raw quote and private checkout URL out of spoken text.");
      return;
    }
    setSpeechError(null);
    updateNodeData(nodeId, { message: value });
  };

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Message
          <span className="text-xs text-purple-400 ml-2">Use {"{{variable}}"} for dynamic content</span>
        </label>
        <textarea
          value={data.message || ""}
          onChange={(e) => updateMessage(e.target.value)}
          rows={4}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none resize-none"
          placeholder="Your message here..."
        />

        {(messageError || speechError) && (
          <p role="alert" className="mt-1 flex items-start gap-1.5 text-[10px] text-amber-300">
            <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />{speechError || messageError}
          </p>
        )}
        {flowVariables.filter((variable) => !protectedKeys.has(variable.key)).length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {flowVariables.filter((variable) => !protectedKeys.has(variable.key)).map((v) => (
              <button
                key={v.key}
                onClick={() => updateMessage((data.message || "") + `{{${v.key}}}`)}
                className="text-xs bg-purple-900/30 text-purple-400 rounded px-1.5 py-0.5 hover:bg-purple-900/50"
              >
                {`{{${v.key}}}`}{v.origin === "mapped" ? " · mapped" : ""}
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
