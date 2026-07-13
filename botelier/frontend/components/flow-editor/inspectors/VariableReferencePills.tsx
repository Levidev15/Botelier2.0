"use client";

import { AlertTriangle } from "lucide-react";
import type { FlowVariable } from "../store";

interface Props {
  text: string;
  variables: FlowVariable[];
}

const TYPE_LABELS: Record<string, string> = {
  text: "text",
  date: "date",
  number: "number",
  phone: "phone",
  email: "email",
  time: "time",
  choice: "choice",
};

function isJsonBlobVariable(v: FlowVariable): boolean {
  const desc = (v.description || "").toLowerCase();
  return (
    v.type === "text" &&
    (desc.includes("json") ||
      desc.includes("array of") ||
      desc.includes("list of") ||
      desc.includes("combinations") ||
      desc.includes("full ") && desc.includes(" from"))
  );
}

export default function VariableReferencePills({ text, variables }: Props) {
  const matches = [...text.matchAll(/\{\{(\w+)\}\}/g)];
  const unique = [...new Set(matches.map((m) => m[1]))];

  if (unique.length === 0) return null;

  return (
    <div className="mt-2 space-y-1.5">
      <p className="text-xs text-gray-500">Variable references</p>
      <div className="flex flex-wrap gap-1.5">
        {unique.map((name) => {
          const variable = variables.find((v) => v.key === name);

          if (!variable) {
            return (
              <span
                key={name}
                title={`"${name}" is not defined in this flow's variable list — check for a typo.`}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs bg-amber-500/15 text-amber-400 border border-amber-500/30"
              >
                <AlertTriangle className="h-3 w-3 shrink-0" />
                <span className="font-mono">{`{{${name}}}`}</span>
                <span className="text-amber-500/70 font-normal">undefined</span>
              </span>
            );
          }

          const jsonBlob = isJsonBlobVariable(variable);

          return (
            <div key={name} className="flex flex-col gap-0.5">
              <span
                title={variable.description || variable.key}
                className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs bg-blue-500/10 text-blue-400 border border-blue-500/20"
              >
                <span className="font-mono">{`{{${name}}}`}</span>
                <span className="text-gray-600">·</span>
                <span className="text-gray-400">{TYPE_LABELS[variable.type] ?? variable.type}</span>
                {variable.description && (
                  <>
                    <span className="text-gray-600">·</span>
                    <span
                      className="text-gray-500 truncate max-w-[180px]"
                      title={variable.description}
                    >
                      {variable.description}
                    </span>
                  </>
                )}
              </span>
              {jsonBlob && (
                <span className="inline-flex items-center gap-1 text-xs text-amber-400/80 pl-1">
                  <AlertTriangle className="h-3 w-3 shrink-0" />
                  Renders as JSON — avoid in spoken instructions; use a formatter variable instead.
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
