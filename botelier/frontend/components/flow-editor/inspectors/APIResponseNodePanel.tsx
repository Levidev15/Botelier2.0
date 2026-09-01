"use client";

import { useRef, useState, useCallback } from "react";
import { AlertTriangle } from "lucide-react";
import { useFlowStore, APIResponseNodeData, APIResponseConfig } from "../store";

interface Props {
  data: APIResponseNodeData;
  nodeId: string;
}

// ── Template token definitions ────────────────────────────────────────────────

const BUILT_IN_TOKENS = [
  { token: "{{index}}", label: "index", description: "Item number (1, 2, 3…)" },
  { token: "{{item}}", label: "item",  description: "The full value for plain string arrays" },
];

const TYPE_LABELS: Record<string, string> = {
  text:   "text",
  date:   "date",
  number: "number",
  phone:  "phone",
  email:  "email",
  time:   "time",
  choice: "choice",
};

// ── Field identifiers ─────────────────────────────────────────────────────────

type FieldKey = "intro" | "template" | "outro" | "noResults";

const FIELD_LABELS: Record<FieldKey, string> = {
  intro:     "Intro text",
  template:  "Per-item template",
  outro:     "Outro text",
  noResults: "No-results text",
};

// ── Utilities ─────────────────────────────────────────────────────────────────

/** Insert `token` at the current cursor position of `el` and call `onChange`. */
function insertAtCursor(
  el: HTMLTextAreaElement | null,
  token: string,
  onChange: (val: string) => void,
) {
  if (!el) return;
  const start = el.selectionStart ?? el.value.length;
  const end   = el.selectionEnd   ?? el.value.length;
  const next  = el.value.slice(0, start) + token + el.value.slice(end);
  onChange(next);
  // Restore cursor after React re-renders the controlled value
  requestAnimationFrame(() => {
    el.focus();
    el.setSelectionRange(start + token.length, start + token.length);
  });
}

/**
 * Detect any `{{word}}` tokens already in the template that aren't built-in
 * and aren't flow-variable keys — these are likely dict field references.
 */
function detectFieldTokens(template: string, knownKeys: Set<string>): string[] {
  const matches = Array.from(template.matchAll(/\{\{(\w+)\}\}/g));
  const builtIn = new Set(BUILT_IN_TOKENS.map((t) => t.label));
  const seen = new Set<string>();
  const out: string[] = [];
  for (const m of matches) {
    const name = m[1];
    if (!builtIn.has(name) && !knownKeys.has(name) && !seen.has(name)) {
      seen.add(name);
      out.push(name);
    }
  }
  return out;
}

// ── Main component ────────────────────────────────────────────────────────────

export default function APIResponseNodePanel({ data, nodeId }: Props) {
  const { updateNodeData, variables } = useFlowStore();

  const cfg: APIResponseConfig = data.responsePresentation || {
    arrayVariable: "",
    introText:     "",
    itemTemplate:  "",
    outroText:     "",
    noResultsText: "No results were found.",
  };

  const update = useCallback(
    (patch: Partial<APIResponseConfig>) =>
      updateNodeData(nodeId, { responsePresentation: { ...cfg, ...patch } }),
    [nodeId, cfg, updateNodeData],
  );

  // ── Refs for each textarea ─────────────────────────────────────────────────
  const introRef     = useRef<HTMLTextAreaElement>(null);
  const templateRef  = useRef<HTMLTextAreaElement>(null);
  const outroRef     = useRef<HTMLTextAreaElement>(null);
  const noResultsRef = useRef<HTMLTextAreaElement>(null);

  const [activeField, setActiveField] = useState<FieldKey>("intro");

  const fieldRefs: Record<FieldKey, React.RefObject<HTMLTextAreaElement>> = {
    intro:     introRef,
    template:  templateRef,
    outro:     outroRef,
    noResults: noResultsRef,
  };

  const fieldUpdaters: Record<FieldKey, (val: string) => void> = {
    intro:     (val) => update({ introText:     val }),
    template:  (val) => update({ itemTemplate:  val }),
    outro:     (val) => update({ outroText:     val }),
    noResults: (val) => update({ noResultsText: val }),
  };

  // Insert token into the currently-active textarea
  const insertToken = useCallback(
    (token: string) => {
      insertAtCursor(fieldRefs[activeField].current, token, fieldUpdaters[activeField]);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [activeField, cfg],
  );

  // ── Derived data ───────────────────────────────────────────────────────────
  const varKeySet = new Set(variables.map((v) => v.key));
  const detectedFieldTokens = detectFieldTokens(cfg.itemTemplate || "", varKeySet);

  // Variables referenced in any text field that aren't defined
  const allText = [cfg.introText, cfg.itemTemplate, cfg.outroText, cfg.noResultsText]
    .filter(Boolean)
    .join(" ");
  const referencedVars = Array.from(new Set(
    Array.from(allText.matchAll(/\{\{(\w+)\}\}/g)).map((m) => m[1]),
  )).filter((name) => {
    const builtIn = new Set(["index", "item", ...detectedFieldTokens]);
    return !builtIn.has(name);
  });
  const undefinedRefs = referencedVars.filter((name) => !varKeySet.has(name));

  // ── Shared classes ─────────────────────────────────────────────────────────
  const textareaCls = (field: FieldKey) =>
    `w-full bg-gray-800 border rounded px-3 py-2 text-sm text-white focus:outline-none resize-none transition-colors ${
      activeField === field
        ? "border-amber-500/70"
        : "border-gray-700 focus:border-amber-500"
    }`;

  // ── Variable palette ───────────────────────────────────────────────────────
  const showTemplateTokens = cfg.arrayVariable && activeField === "template";
  const hasVariables = variables.length > 0;

  const PillButton = ({
    token,
    label,
    description,
    variant = "blue",
  }: {
    token: string;
    label?: string;
    description?: string;
    variant?: "amber" | "blue" | "gray";
  }) => {
    const colors = {
      amber: "bg-amber-900/25 text-amber-300 border border-amber-600/30 hover:bg-amber-900/40 hover:border-amber-500/50",
      blue:  "bg-blue-900/20 text-blue-300 border border-blue-600/25 hover:bg-blue-900/35 hover:border-blue-500/40",
      gray:  "bg-gray-700/40 text-gray-300 border border-gray-600/30 hover:bg-gray-700/60",
    }[variant];

    return (
      <button
        type="button"
        title={description}
        onMouseDown={(e) => e.preventDefault()} // keep textarea selection
        onClick={() => insertToken(token)}
        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono transition-colors ${colors}`}
      >
        {token}
        {label && label !== token.replace(/[{}]/g, "") && (
          <span className="font-sans text-[10px] opacity-60 ml-0.5">{label}</span>
        )}
      </button>
    );
  };

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-5">

      {/* Name */}
      <div>
        <label className="block text-xs font-medium text-gray-400 mb-1">Node name</label>
        <input
          type="text"
          value={data.name || ""}
          onChange={(e) => updateNodeData(nodeId, { name: e.target.value })}
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
              {`{{${v.key}}}`} — {v.description || TYPE_LABELS[v.type] || v.type}
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
          ref={introRef}
          value={cfg.introText || ""}
          onChange={(e) => update({ introText: e.target.value })}
          onFocus={() => setActiveField("intro")}
          rows={2}
          className={textareaCls("intro")}
          placeholder="I have found rooms available for your stay."
        />
      </div>

      {/* Per-Item Template — only shown when an array variable is selected */}
      {cfg.arrayVariable && (
        <div>
          <label className="block text-xs font-medium text-gray-400 mb-1">
            Per-item template
          </label>
          <textarea
            ref={templateRef}
            value={cfg.itemTemplate || ""}
            onChange={(e) => update({ itemTemplate: e.target.value })}
            onFocus={() => setActiveField("template")}
            rows={3}
            className={`${textareaCls("template")} font-mono`}
            placeholder="Option {{index}}: {{room_name}} — {{price}} per night."
          />
        </div>
      )}

      {/* Outro Text */}
      <div>
        <label className="block text-xs font-medium text-gray-400 mb-1">
          Outro text{" "}
          <span className="text-gray-600 font-normal">(spoken after the list)</span>
        </label>
        <textarea
          ref={outroRef}
          value={cfg.outroText || ""}
          onChange={(e) => update({ outroText: e.target.value })}
          onFocus={() => setActiveField("outro")}
          rows={2}
          className={textareaCls("outro")}
          placeholder="Which option would you prefer?"
        />
      </div>

      {/* No Results Text */}
      <div>
        <label className="block text-xs font-medium text-gray-400 mb-1">
          No-results text
        </label>
        <textarea
          ref={noResultsRef}
          value={cfg.noResultsText || ""}
          onChange={(e) => update({ noResultsText: e.target.value })}
          onFocus={() => setActiveField("noResults")}
          rows={2}
          className={textareaCls("noResults")}
          placeholder="No results were found."
        />
      </div>

      {/* ── Variable Palette ──────────────────────────────────────────────── */}
      {(showTemplateTokens || hasVariables) && (
        <div className="rounded-lg border border-gray-700/60 bg-gray-900/40 p-3 space-y-3">
          {/* Header */}
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-gray-400">Insert variable</p>
            <span className="text-[10px] text-gray-600 bg-gray-800 rounded px-1.5 py-0.5">
              → {FIELD_LABELS[activeField]}
            </span>
          </div>

          {/* Template tokens — shown only when per-item template is active */}
          {showTemplateTokens && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-1.5">
                Template tokens
              </p>
              <div className="flex flex-wrap gap-1.5">
                {BUILT_IN_TOKENS.map(({ token, description }) => (
                  <PillButton
                    key={token}
                    token={token}
                    description={description}
                    variant="amber"
                  />
                ))}
                {/* Detected dict-field tokens already used in the template */}
                {detectedFieldTokens.map((name) => (
                  <PillButton
                    key={name}
                    token={`{{${name}}}`}
                    description={`Dict field: ${name}`}
                    variant="amber"
                  />
                ))}
              </div>
              {/* Mini reference legend */}
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-0.5 text-[10px] text-gray-600">
                <span><span className="text-amber-400/70 font-mono">{"{{index}}"}</span> — item number</span>
                <span><span className="text-amber-400/70 font-mono">{"{{item}}"}</span> — plain string value</span>
                <span><span className="text-amber-400/70 font-mono">{"{{fieldName}}"}</span> — dict field</span>
              </div>
            </div>
          )}

          {/* Separator between sections */}
          {showTemplateTokens && hasVariables && (
            <div className="border-t border-gray-700/50" />
          )}

          {/* Flow variables */}
          {hasVariables && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-1.5">
                Flow variables
              </p>
              <div className="flex flex-wrap gap-1.5">
                {variables.map((v) => (
                  <PillButton
                    key={v.key}
                    token={`{{${v.key}}}`}
                    description={v.description ? `${v.description} (${TYPE_LABELS[v.type] ?? v.type})` : TYPE_LABELS[v.type] ?? v.type}
                    variant="blue"
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Undefined-variable warnings ───────────────────────────────────── */}
      {undefinedRefs.length > 0 && (
        <div className="rounded-lg border border-yellow-700/30 bg-yellow-900/10 p-3 space-y-1.5">
          <div className="flex items-center gap-1.5 text-xs text-yellow-400/80">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span className="font-medium">Undefined variable references</span>
          </div>
          <div className="flex flex-wrap gap-1">
            {undefinedRefs.map((name) => (
              <span
                key={name}
                className="font-mono text-xs px-1.5 py-0.5 rounded bg-yellow-800/20 text-yellow-400 border border-yellow-700/30"
              >
                {`{{${name}}}`}
              </span>
            ))}
          </div>
          <p className="text-[11px] text-yellow-500/60">
            These names are not declared in this flow's variable list. Check for typos or add them as flow variables.
          </p>
        </div>
      )}

      {/* ── How it works callout ─────────────────────────────────────────── */}
      <div className="bg-amber-900/10 border border-amber-700/30 rounded-lg p-3 text-xs text-amber-300/70 space-y-1">
        <p className="font-medium text-amber-300/90">How it works</p>
        <p>
          This node speaks the API result <strong>directly</strong> via TTS — no LLM narration turn.
          Place it immediately after an API Request node. The platform auto-executes it as soon as
          the API result lands.
        </p>
        {cfg.arrayVariable && (
          <p>
            The <code className="text-amber-400/80">{`{{${cfg.arrayVariable}}}`}</code> variable will
            be parsed as a JSON array. Each element is rendered through the per-item template and
            spoken in sequence.
          </p>
        )}
      </div>
    </div>
  );
}
