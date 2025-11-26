"use client";

import { useState } from "react";

interface FunctionPickerProps {
  functions: Array<{
    name: string;
    description: string;
    parameters: {
      type?: string;
      properties?: Record<string, { type: string; description: string }>;
      required?: string[];
    };
  }>;
  onExecute: (functionName: string, args: Record<string, unknown>) => void;
  disabled?: boolean;
}

export default function FunctionPicker({
  functions,
  onExecute,
  disabled = false,
}: FunctionPickerProps) {
  const [selectedFunction, setSelectedFunction] = useState<string>("");
  const [args, setArgs] = useState<Record<string, string>>({});

  const selectedFunctionDef = functions.find((f) => f.name === selectedFunction);
  const parameters = selectedFunctionDef?.parameters?.properties || {};
  const requiredParams = selectedFunctionDef?.parameters?.required || [];

  const handleExecute = () => {
    if (!selectedFunction) return;

    const parsedArgs: Record<string, unknown> = {};
    Object.entries(args).forEach(([key, value]) => {
      const paramDef = parameters[key];
      if (paramDef?.type === "number") {
        parsedArgs[key] = parseFloat(value) || 0;
      } else if (paramDef?.type === "boolean") {
        parsedArgs[key] = value === "true";
      } else {
        parsedArgs[key] = value;
      }
    });

    onExecute(selectedFunction, parsedArgs);
    setArgs({});
  };

  return (
    <div className="bg-[#1a1a1a] rounded-lg border border-[#2a2a2a] p-4">
      <h3 className="text-sm font-medium text-gray-300 mb-3">Execute Function</h3>

      <div className="space-y-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Function</label>
          <select
            value={selectedFunction}
            onChange={(e) => {
              setSelectedFunction(e.target.value);
              setArgs({});
            }}
            disabled={disabled}
            className="w-full bg-[#2a2a2a] border border-[#3a3a3a] rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
          >
            <option value="">Select a function...</option>
            {functions.map((func) => (
              <option key={func.name} value={func.name}>
                {func.name}
              </option>
            ))}
          </select>
        </div>

        {selectedFunctionDef && (
          <>
            <p className="text-xs text-gray-500">{selectedFunctionDef.description}</p>

            {Object.entries(parameters).map(([paramName, paramDef]) => (
              <div key={paramName}>
                <label className="block text-xs text-gray-500 mb-1">
                  {paramName}
                  {requiredParams.includes(paramName) && (
                    <span className="text-red-400 ml-1">*</span>
                  )}
                  <span className="ml-2 text-gray-600">({paramDef.type})</span>
                </label>
                <input
                  type={paramDef.type === "number" ? "number" : "text"}
                  value={args[paramName] || ""}
                  onChange={(e) =>
                    setArgs((prev) => ({ ...prev, [paramName]: e.target.value }))
                  }
                  placeholder={paramDef.description}
                  disabled={disabled}
                  className="w-full bg-[#2a2a2a] border border-[#3a3a3a] rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
                />
              </div>
            ))}

            <button
              onClick={handleExecute}
              disabled={disabled || !selectedFunction}
              className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium py-2 px-4 rounded transition-colors"
            >
              Execute Function
            </button>
          </>
        )}
      </div>
    </div>
  );
}
