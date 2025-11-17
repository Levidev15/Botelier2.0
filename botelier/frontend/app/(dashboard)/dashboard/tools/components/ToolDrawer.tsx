"use client";

import { X } from "lucide-react";
import { useState } from "react";
import ToolTypeSelector from "./ToolTypeSelector";
import TransferCallForm from "./tool-types/TransferCallForm";

interface ToolDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  onToolCreated: (tool: any) => void;
}

export type ToolType =
  | "transfer_call"
  | "api_request"
  | "end_call"
  | "send_sms"
  | "send_email";

export default function ToolDrawer({ isOpen, onClose, onToolCreated }: ToolDrawerProps) {
  const [selectedType, setSelectedType] = useState<ToolType | null>(null);

  const handleReset = () => {
    setSelectedType(null);
  };

  const handleToolCreated = (tool: any) => {
    onToolCreated(tool);
    handleReset();
  };

  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 z-40"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="fixed right-0 top-0 h-full w-full max-w-4xl bg-[#0a0a0a] border-l border-gray-800 z-50 flex overflow-hidden">
        {/* Left Sidebar - Tool Type Selector */}
        <div className="w-64 bg-[#141414] border-r border-gray-800 p-4 overflow-y-auto">
          <div className="mb-6">
            <h3 className="text-sm font-semibold text-gray-400 mb-4">TOOL TYPES</h3>
            <ToolTypeSelector
              selectedType={selectedType}
              onSelectType={setSelectedType}
            />
          </div>
        </div>

        {/* Right Panel - Tool Configuration Form */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between p-6 border-b border-gray-800">
            <div>
              <h2 className="text-xl font-bold">
                {selectedType ? "Configure Tool" : "Select Tool Type"}
              </h2>
              <p className="text-sm text-gray-400 mt-1">
                {selectedType
                  ? "Fill in the configuration details"
                  : "Choose a tool type from the left sidebar"}
              </p>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-gray-800 rounded-lg transition-colors"
            >
              <X size={20} />
            </button>
          </div>

          {/* Form Content */}
          <div className="flex-1 overflow-y-auto p-6">
            {selectedType === "transfer_call" && (
              <TransferCallForm
                onSuccess={handleToolCreated}
                onCancel={handleReset}
              />
            )}

            {selectedType === "api_request" && (
              <div className="text-center py-12 text-gray-400">
                API Request form coming soon...
              </div>
            )}

            {selectedType === "end_call" && (
              <div className="text-center py-12 text-gray-400">
                End Call form coming soon...
              </div>
            )}

            {selectedType === "send_sms" && (
              <div className="text-center py-12 text-gray-400">
                Send SMS form coming soon...
              </div>
            )}

            {selectedType === "send_email" && (
              <div className="text-center py-12 text-gray-400">
                Send Email form coming soon...
              </div>
            )}

            {!selectedType && (
              <div className="text-center py-12 text-gray-400">
                <p>Select a tool type from the left sidebar to get started</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
