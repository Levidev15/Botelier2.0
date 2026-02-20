"use client";

import { useState, useMemo } from "react";
import { X, Copy, Check } from "lucide-react";
import { useFlowStore } from "./store";

interface FlowSchemaPanelProps {
  onClose: () => void;
}

function syntaxHighlight(json: string): string {
  return json.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
    (match) => {
      let cls = "text-yellow-400";
      if (/^"/.test(match)) {
        if (/:$/.test(match)) {
          cls = "text-blue-400";
        } else {
          cls = "text-green-400";
        }
      } else if (/true|false/.test(match)) {
        cls = "text-orange-400";
      } else if (/null/.test(match)) {
        cls = "text-gray-500";
      }
      return `<span class="${cls}">${match}</span>`;
    }
  );
}

export default function FlowSchemaPanel({ onClose }: FlowSchemaPanelProps) {
  const { nodes, edges, variables, globalPrompt } = useFlowStore();
  const [copied, setCopied] = useState(false);

  const schema = useMemo(() => {
    const cleanNodes = nodes.map((node) => {
      const data = { ...node.data };
      Object.keys(data).forEach((key) => {
        if (typeof (data as any)[key] === "function") {
          delete (data as any)[key];
        }
      });
      return {
        id: node.id,
        type: node.type,
        position: { x: Math.round(node.position.x), y: Math.round(node.position.y) },
        data,
      };
    });

    return {
      ...(globalPrompt ? { globalPrompt } : {}),
      variables: variables.map((v) => ({
        key: v.key,
        type: v.type,
        ...(v.description ? { description: v.description } : {}),
        ...(v.required ? { required: v.required } : {}),
        ...(v.defaultValue ? { defaultValue: v.defaultValue } : {}),
        ...(v.choices?.length ? { choices: v.choices } : {}),
      })),
      nodes: cleanNodes,
      edges: edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        ...(edge.sourceHandle ? { sourceHandle: edge.sourceHandle } : {}),
        ...(edge.targetHandle ? { targetHandle: edge.targetHandle } : {}),
      })),
    };
  }, [nodes, edges, variables, globalPrompt]);

  const jsonString = useMemo(() => JSON.stringify(schema, null, 2), [schema]);
  const highlightedHtml = useMemo(() => syntaxHighlight(jsonString), [jsonString]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(jsonString);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = jsonString;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const lineCount = jsonString.split("\n").length;

  return (
    <div className="h-full flex flex-col bg-[#141414] border-l border-gray-800">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800 shrink-0">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-white">Flow Schema</h3>
          <span className="text-xs text-gray-500">JSON</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleCopy}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition ${
              copied
                ? "bg-green-600/20 text-green-400"
                : "bg-gray-800 hover:bg-gray-700 text-gray-300"
            }`}
          >
            {copied ? (
              <>
                <Check className="h-3 w-3" />
                Copied
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" />
                Copy
              </>
            )}
          </button>
          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-800 rounded-md transition"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        <pre
          className="p-4 font-mono text-xs leading-relaxed whitespace-pre text-gray-300"
          dangerouslySetInnerHTML={{ __html: highlightedHtml }}
        />
      </div>

      <div className="px-4 py-2 border-t border-gray-800 flex items-center justify-between shrink-0">
        <span className="text-xs text-gray-500">
          {nodes.length} node{nodes.length !== 1 ? "s" : ""} &middot; {edges.length} edge{edges.length !== 1 ? "s" : ""} &middot; {variables.length} var{variables.length !== 1 ? "s" : ""}
        </span>
        <span className="text-xs text-gray-600">
          {lineCount} lines &middot; {(jsonString.length / 1024).toFixed(1)} KB
        </span>
      </div>
    </div>
  );
}
