"use client";

import { useState } from "react";
import { Check, Pencil, Plus, X } from "lucide-react";
import { useFlowStore, SlotType } from "../store";

const ALL_TYPES: SlotType[] = ["text", "number", "date", "phone", "email", "time", "choice"];

/** Normalise a raw string to a safe variable key */
function formatKey(raw: string): string {
  return raw.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "");
}

export default function VariablesPanel() {
  const { variables, addVariable, updateVariable, deleteVariable } = useFlowStore();

  // Add-row state
  const [newVarKey, setNewVarKey] = useState("");
  const [newVarType, setNewVarType] = useState<SlotType>("text");

  // Inline-rename state
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);

  // ── Add ────────────────────────────────────────────────────────────────────
  const handleAdd = () => {
    const key = formatKey(newVarKey);
    if (!key) return;
    // addVariable in the store now deduplicates: existing key → merge (not append)
    addVariable({ key, type: newVarType, description: "", required: false });
    setNewVarKey("");
    setNewVarType("text");
  };

  // ── Rename ─────────────────────────────────────────────────────────────────
  const startEdit = (key: string) => {
    setEditingKey(key);
    setEditValue(key);
    setRenameError(null);
  };

  const commitEdit = (oldKey: string) => {
    const newKey = formatKey(editValue);
    if (!newKey) {
      setEditingKey(null);
      setRenameError(null);
      return;
    }
    if (newKey !== oldKey) {
      // Collision check in the panel before calling the store
      if (variables.some((v) => v.key === newKey)) {
        setRenameError(`"${newKey}" is already declared`);
        return; // keep editing — show the error inline
      }
      // updateVariable handles atomic migration of all references in node data
      updateVariable(oldKey, { key: newKey });
    }
    setEditingKey(null);
    setEditValue("");
    setRenameError(null);
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* ── Scrollable variable list ─────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto p-4 space-y-1 min-h-0">
        {variables.length === 0 && (
          <p className="text-xs text-gray-500 text-center pt-6">
            No variables declared yet.
          </p>
        )}

        {variables.map((v) => (
          <div key={v.key} className="space-y-0.5">
            <div className="flex items-center gap-2 bg-[#1a1a1a] rounded px-2 py-1.5 group">
              {editingKey === v.key ? (
                /* ── Inline rename input ── */
                <>
                  <input
                    autoFocus
                    type="text"
                    value={editValue}
                    onChange={(e) => {
                      setEditValue(formatKey(e.target.value));
                      setRenameError(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") commitEdit(v.key);
                      if (e.key === "Escape") {
                        setEditingKey(null);
                        setRenameError(null);
                      }
                    }}
                    onBlur={() => commitEdit(v.key)}
                    className="flex-1 bg-[#0a0a0a] border border-purple-500 rounded px-1.5 py-0.5 text-purple-300 text-xs font-mono focus:outline-none"
                  />
                  <button
                    onMouseDown={(e) => e.preventDefault()} // prevent blur before click
                    onClick={() => commitEdit(v.key)}
                    className="text-green-400 hover:text-green-300 flex-shrink-0"
                    title="Save rename"
                  >
                    <Check className="h-3 w-3" />
                  </button>
                </>
              ) : (
                /* ── Read-only key display ── */
                <>
                  <button
                    onClick={() => startEdit(v.key)}
                    className="text-xs text-purple-400 font-mono flex-1 truncate text-left hover:text-purple-300 transition-colors"
                    title="Click to rename"
                  >
                    {`{{${v.key}}}`}
                  </button>
                  <Pencil className="h-2.5 w-2.5 text-gray-600 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" />
                </>
              )}

              {/* Type selector — all 7 SlotType values */}
              <select
                value={v.type || "text"}
                onChange={(e) => updateVariable(v.key, { type: e.target.value as SlotType })}
                className="text-[10px] text-gray-500 bg-[#1a1a1a] border-none outline-none cursor-pointer hover:text-purple-400 flex-shrink-0 rounded px-1 py-0.5"
                title="Change variable type"
              >
                {ALL_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>

              {/* Delete */}
              <button
                onClick={() => deleteVariable(v.key)}
                className="text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                title={`Delete ${v.key}`}
              >
                <X className="h-3 w-3" />
              </button>
            </div>

            {/* Inline rename collision error */}
            {editingKey === v.key && renameError && (
              <p className="text-[10px] text-red-400 pl-2">{renameError}</p>
            )}
          </div>
        ))}
      </div>

      {/* ── Pinned add-variable area ─────────────────────────────────────── */}
      <div className="p-4 border-t border-gray-800 flex-shrink-0 bg-[#141414]">
        {/* Name input + type select + add button */}
        <div className="flex gap-2 items-center">
          <input
            type="text"
            value={newVarKey}
            onChange={(e) => setNewVarKey(formatKey(e.target.value))}
            placeholder="new_variable_name"
            className="flex-1 bg-[#1a1a1a] border border-gray-700 rounded px-2 py-1.5 text-white text-xs focus:border-purple-500 focus:outline-none font-mono"
            onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          />
          <select
            value={newVarType}
            onChange={(e) => setNewVarType(e.target.value as SlotType)}
            className="bg-[#1a1a1a] border border-gray-700 rounded px-1.5 py-1.5 text-gray-400 text-xs focus:border-purple-500 focus:outline-none cursor-pointer flex-shrink-0"
            title="Variable type"
          >
            {ALL_TYPES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <button
            onClick={handleAdd}
            disabled={!newVarKey.trim()}
            className="px-2 py-1.5 bg-[#1a1a1a] border border-gray-700 rounded text-purple-400 hover:text-purple-300 hover:border-purple-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex-shrink-0"
            title="Add variable"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>

        <p className="text-xs text-gray-600 mt-1.5">
          Use{" "}
          <span className="font-mono text-gray-500">{"{{variable_name}}"}</span>{" "}
          in any text field
        </p>
      </div>
    </div>
  );
}
