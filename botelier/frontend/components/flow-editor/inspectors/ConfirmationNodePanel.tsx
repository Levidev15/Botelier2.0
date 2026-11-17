"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle } from "lucide-react";
import { useFlowStore, ConfirmationNodeData, DeliveryMode, CapabilityNodeData } from "../store";
import { collectFlowVariables, findQuoteConfirmationContext, hasQuotePrivateSpeech } from "../flowEditorData";

interface Props {
  data: ConfirmationNodeData;
  nodeId: string;
}

export default function ConfirmationNodePanel({ data, nodeId }: Props) {
  const { updateNodeData, variables, nodes, edges } = useFlowStore();
  const previouslyRequiredRef = useRef<string[]>([]);
  const [speechError, setSpeechError] = useState<string | null>(null);
  const confirmation = data.confirmation || {
    summaryTemplate: "",
    confirmPrompt: "",
    editPrompt: "",
    variablesToConfirm: [],
    allowEdit: true,
    deliveryMode: "guided" as DeliveryMode,
  };
  const deliveryMode = confirmation.deliveryMode || "guided";
  const flowVariables = collectFlowVariables(variables, nodes);
  const getQuoteApi = (id: string) =>
    (nodes.find((node) => node.id === id)?.data as CapabilityNodeData | undefined)?.api;
  const quoteContext = useMemo(
    () => findQuoteConfirmationContext(nodes, edges, nodeId),
    [nodes, edges, nodeId],
  );
  const requiredVariables = [
    ...quoteContext.publicVariables,
    ...quoteContext.fingerprintVariables,
    ...quoteContext.recipientVariables,
  ];
  const requiredSignature = requiredVariables.join("\u0000");
  const quotePrivateVariables = new Set([
    ...quoteContext.privateVariables,
    ...quoteContext.rawQuoteVariables,
  ]);
  const protectedSpeechVariables = new Set([
    ...Array.from(quotePrivateVariables),
    ...quoteContext.fingerprintVariables,
  ]);
  const quoteSpeechProtection = {
    privateVariables: quoteContext.privateVariables,
    fingerprintVariables: quoteContext.fingerprintVariables,
    rawQuoteVariables: quoteContext.rawQuoteVariables,
  };
  const currentVariablesToConfirm = confirmation.variablesToConfirm || [];
  const quoteRoomVariable = quoteContext.validators
    .map(({ id }) => getQuoteApi(id)?.quotePolicy?.publicConfirmationFields?.room_id)
    .find(Boolean);
  const quoteTotalVariable = quoteContext.validators
    .map(({ id }) => getQuoteApi(id)?.quotePolicy?.publicConfirmationFields?.["pricing.total"])
    .find(Boolean);
  const hasStoredUnsafeSpeech = [
    confirmation.summaryTemplate || "",
    confirmation.confirmPrompt || "",
    confirmation.editPrompt || "",
  ].some((value) =>
    hasQuotePrivateSpeech(value, quoteSpeechProtection) ||
    (protectedSpeechVariables.size > 0 && /https?:\/\/\S+/i.test(value)),
  );

  useEffect(() => {
    const retained = currentVariablesToConfirm.filter((key) => !previouslyRequiredRef.current.includes(key));
    const next = Array.from(new Set([...retained, ...requiredVariables]));
    previouslyRequiredRef.current = requiredVariables;
    if (
      next.length !== currentVariablesToConfirm.length ||
      next.some((key, index) => key !== currentVariablesToConfirm[index])
    ) {
      updateNodeData(nodeId, { confirmation: { ...confirmation, variablesToConfirm: next } });
    }
  }, [nodeId, requiredSignature, currentVariablesToConfirm, confirmation, updateNodeData]);

  const writeSpeech = (field: "summaryTemplate" | "confirmPrompt" | "editPrompt", value: string) => {
    if (hasQuotePrivateSpeech(value, quoteSpeechProtection) || /https?:\/\/\S+/i.test(value)) {
      setSpeechError("Keep the fingerprint, raw quote and private URL out of every spoken confirmation field.");
      return;
    }
    setSpeechError(null);
    updateConfirmation({ [field]: value });
  };

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
          {flowVariables.filter((variable) =>
            !quotePrivateVariables.has(variable.key) &&
            !quoteContext.rawQuoteVariables.includes(variable.key),
          ).map((v) => {
            const isRequired = requiredVariables.includes(v.key);
            return (
            <button
              key={v.key}
              onClick={() => toggleVariable(v.key)}
              disabled={isRequired}
              title={isRequired ? "Required by the reservation quote delivery contract" : undefined}
              className={`text-xs rounded px-2 py-1 transition ${
                confirmation.variablesToConfirm?.includes(v.key)
                  ? "bg-emerald-600 text-white"
                  : "bg-gray-700 text-gray-300 hover:bg-gray-600"
              } ${isRequired ? "cursor-not-allowed ring-1 ring-emerald-400/60" : ""}`}
            >
              {v.key}{isRequired ? " · required" : v.origin === "mapped" ? " · mapped" : ""}
            </button>
          );})}
        </div>
        {flowVariables.length === 0 && (
          <p className="text-xs text-gray-500">Add flow variables first</p>
        )}
        {quoteContext.validators.length > 0 && (
          <div className="mt-2 space-y-1 rounded-lg border border-emerald-900/50 bg-emerald-950/10 p-2 text-[10px] text-gray-400">
            <p>Quote confirmation requires every public quote field, the internal fingerprint and the selected delivery recipient. The private URL and raw provider quote cannot be confirmed here.</p>
            {!quoteContext.recipientVariables.length && (
              <p role="alert" className="flex items-start gap-1.5 text-amber-300">
                <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />Bind an existing SMS or email sender to this validator and choose its recipient fact.
              </p>
            )}
          </div>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">
          Summary Template
          <span className="text-xs text-emerald-400 ml-2">Use {"{{variable}}"}</span>
        </label>
        <textarea
          value={confirmation.summaryTemplate || ""}
          onChange={(e) => writeSpeech("summaryTemplate", e.target.value)}
          rows={3}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-emerald-500 focus:outline-none resize-none"
          placeholder={quoteContext.validators.length
            ? `Review ${quoteRoomVariable ? `{{${quoteRoomVariable}}}` : "the selected room"} and stay details, total ${quoteTotalVariable ? `{{${quoteTotalVariable}}}` : "the quoted total"}. Is this correct?`
            : "Summary of collected information: {{variable_name}}..."}
        />
        {quoteContext.validators.length > 0 && <p className="mt-1 text-[10px] text-gray-500">Use only human-readable public details and the recipient. The fingerprint and checkout link are internal delivery controls, never speech.</p>}
        {(speechError || hasStoredUnsafeSpeech) && (
          <p role="alert" className="mt-1 text-[10px] text-amber-300">
            {speechError || "Existing spoken text contains a protected quote reference. Remove it before continuing."}
          </p>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Confirm Prompt</label>
        <input
          type="text"
          value={confirmation.confirmPrompt || ""}
          onChange={(e) => writeSpeech("confirmPrompt", e.target.value)}
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
            onChange={(e) => writeSpeech("editPrompt", e.target.value)}
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
