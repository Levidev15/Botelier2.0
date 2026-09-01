"use client";

import { useFlowStore, APIResponseNodeData, APIResponseConfig } from "../store";
import VariableReferencePills from "./VariableReferencePills";

interface Props {
  data: APIResponseNodeData;
  nodeId: string;
}

export default function APIResponseNodePanel({ data, nodeId }: Props) {
  const { updateNodeData, variables } = useFlowStore();

  const cfg: APIResponseConfig = data.responsePresentation || {
    arrayVariable: "",
    introText: "",
    itemTemplate: "",
    outroText: "",
    noResultsText: "No results were found.",
  };

  const update = (patch: Partial<APIResponseConfig>) => {
    updateNodeData(nodeId, {
      responsePresentation: { ...cfg, ...patch },
    });
  };

  const combinedTemplateText = [
    cfg.introText,
    cfg.itemTemplate,
    cfg.outroText,
    cfg.noResultsText,
  ]
    .filter(Boolean)
    .join(" ");

  // All variables are candidates — arrays are commonly stored as JSON text
  // in a text-typed variable (the flow variable type system has no array type).
  const arrayVariableCandidates = variables;

  return (
    <div className="space-y-5">
      {/* Name */}
      <div>
        <label className="block text-xs font-medium text-gray-400 mb-1">Node name</label>
        <input
          type="text"
          value={data.name || ""}
          onChange={(e) =>
            updateNodeData(nodeId, { name: e.target.value })
          }
          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
          placeholder="Present Results"
        />
      </div>

      {/* Array Variable Selector */}
      <div>
        <label className="block text-xs font-medium text-gray-400 mb-1">
          Array variable{" "}
          <span className="text-gray-600 font-normal">(optional — leave blank to speak intro text only)</span>
        </label>
        <select
          value={cfg.arrayVariable || ""}
          onChange={(e) => update({ arrayVariable: e.target.value })}
          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
        >
          <option value="">— none / speak intro text only —</option>
          {variables.map((v) => (
            <option key={v.key} value={v.key}>
              {`{{${v.key}}}`} — {v.description || v.type}
            </option>
          ))}
        </select>
        {cfg.arrayVariable && (
          <p className="mt-1 text-xs text-gray-500">
            The platform will parse this variable as a JSON array and iterate each item through the template below.
          </p>
        )}
      </div>

      {/* Intro Text */}
      <div>
        <label className="block text-xs font-medium text-gray-400 mb-1">
          Intro text{" "}
          <span className="text-gray-600 font-normal">(spoken before the list)</span>
        </label>
        <textarea
          value={cfg.introText || ""}
          onChange={(e) => update({ introText: e.target.value })}
          rows={2}
          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500 resize-none"
          placeholder="Here are the available options:"
        />
      </div>

      {/* Per-Item Template */}
      {cfg.arrayVariable && (
        <div>
          <label className="block text-xs font-medium text-gray-400 mb-1">
            Per-item template
          </label>
          <textarea
            value={cfg.itemTemplate || ""}
            onChange={(e) => update({ itemTemplate: e.target.value })}
            rows={3}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500 resize-none font-mono"
            placeholder="Option {{index}}: {{room_name}} — {{price}} per night."
          />
          <p className="mt-1 text-xs text-gray-500">
            Use <code className="text-amber-400/80">{"{{index}}"}</code> for the item number,{" "}
            <code className="text-amber-400/80">{"{{fieldName}}"}</code> for dict fields, or{" "}
            <code className="text-amber-400/80">{"{{item}}"}</code> for a plain string item.
          </p>
        </div>
      )}

      {/* Outro Text */}
      <div>
        <label className="block text-xs font-medium text-gray-400 mb-1">
          Outro text{" "}
          <span className="text-gray-600 font-normal">(spoken after the list)</span>
        </label>
        <textarea
          value={cfg.outroText || ""}
          onChange={(e) => update({ outroText: e.target.value })}
          rows={2}
          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500 resize-none"
          placeholder="Which option would you prefer?"
        />
      </div>

      {/* No Results Text */}
      <div>
        <label className="block text-xs font-medium text-gray-400 mb-1">
          No-results text
        </label>
        <textarea
          value={cfg.noResultsText || ""}
          onChange={(e) => update({ noResultsText: e.target.value })}
          rows={2}
          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500 resize-none"
          placeholder="No results were found."
        />
      </div>

      {/* Variable reference pills */}
      {combinedTemplateText && (
        <VariableReferencePills text={combinedTemplateText} variables={variables} />
      )}

      {/* How it works callout */}
      <div className="bg-amber-900/10 border border-amber-700/30 rounded-lg p-3 text-xs text-amber-300/70 space-y-1">
        <p className="font-medium text-amber-300/90">How it works</p>
        <p>
          This node speaks the API result <strong>directly</strong> via TTS — no LLM
          narration turn. Place it immediately after an API Request node. The platform
          auto-executes it as soon as the API result lands.
        </p>
        {cfg.arrayVariable && (
          <p>
            The <code className="text-amber-400/80">{`{{${cfg.arrayVariable}}}`}</code> variable
            will be parsed as a JSON array. Each element is rendered through the per-item
            template and spoken in sequence.
          </p>
        )}
      </div>
    </div>
  );
}
