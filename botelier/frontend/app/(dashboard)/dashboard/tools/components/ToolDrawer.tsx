"use client";

import { X } from "lucide-react";
import { useState, useEffect } from "react";
import ToolTypeSelector from "./ToolTypeSelector";
import TransferCallForm from "./tool-types/TransferCallForm";
import FlowForm from "./tool-types/FlowForm";
import ApiRequestForm from "./tool-types/ApiRequestForm";

interface Tool {
  id: string;
  name: string;
  description: string;
  tool_type: string;
  config: any;
  is_active: boolean;
}

interface ToolDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  onToolCreated: (tool: any) => void;
  onToolUpdated?: (tool: any) => void;
  editTool?: Tool | null;
  accountId: string;
  toolSetId?: string;
}

export type ToolType =
  | "TRANSFER_CALL"
  | "API_REQUEST"
  | "END_CALL"
  | "SEND_SMS"
  | "SEND_EMAIL"
  | "FLOW";

export default function ToolDrawer({ isOpen, onClose, onToolCreated, onToolUpdated, editTool, accountId, toolSetId }: ToolDrawerProps) {
  const [selectedType, setSelectedType] = useState<ToolType | null>(null);

  const isEditMode = !!editTool;

  useEffect(() => {
    if (editTool) {
      setSelectedType(editTool.tool_type as ToolType);
    } else {
      setSelectedType(null);
    }
  }, [editTool, isOpen]);

  const handleReset = () => {
    setSelectedType(null);
    onClose();
  };

  const handleToolSaved = (tool: any) => {
    if (isEditMode && onToolUpdated) {
      onToolUpdated(tool);
    } else {
      onToolCreated(tool);
    }
    handleReset();
  };

  if (!isOpen) return null;

  return (
    <>
      <div
        className="fixed inset-0 bg-black/50 z-40"
        onClick={onClose}
      />

      <div className="fixed right-0 top-0 h-full w-full max-w-4xl bg-[#0a0a0a] border-l border-gray-800 z-50 flex overflow-hidden">
        {!isEditMode && (
          <div className="w-64 bg-[#141414] border-r border-gray-800 p-4 overflow-y-auto">
            <div className="mb-6">
              <h3 className="text-sm font-semibold text-gray-400 mb-4">TOOL TYPES</h3>
              <ToolTypeSelector
                selectedType={selectedType}
                onSelectType={setSelectedType}
              />
            </div>
          </div>
        )}

        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex items-center justify-between p-6 border-b border-gray-800">
            <div>
              <h2 className="text-xl font-bold">
                {isEditMode ? `Edit ${editTool?.name}` : selectedType ? "Configure Tool" : "Select Tool Type"}
              </h2>
              <p className="text-sm text-gray-400 mt-1">
                {isEditMode
                  ? "Update the tool configuration"
                  : selectedType
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

          <div className="flex-1 overflow-y-auto p-6">
            {selectedType === "TRANSFER_CALL" && (
              <TransferCallForm
                onSuccess={handleToolSaved}
                onCancel={handleReset}
                tool={editTool || undefined}
                accountId={accountId}
                toolSetId={toolSetId}
              />
            )}

            {selectedType === "API_REQUEST" && (
              <ApiRequestForm
                onSuccess={handleToolSaved}
                onCancel={handleReset}
                tool={editTool || undefined}
                accountId={accountId}
                toolSetId={toolSetId}
              />
            )}

            {selectedType === "END_CALL" && (
              <div className="text-center py-12 text-gray-400">
                End Call form coming soon...
              </div>
            )}

            {selectedType === "SEND_SMS" && (
              <div className="text-center py-12 text-gray-400">
                Send SMS form coming soon...
              </div>
            )}

            {selectedType === "SEND_EMAIL" && (
              <div className="text-center py-12 text-gray-400">
                Send Email form coming soon...
              </div>
            )}

            {selectedType === "FLOW" && !isEditMode && (
              <FlowForm
                onSuccess={handleToolSaved}
                onCancel={handleReset}
                accountId={accountId}
                toolSetId={toolSetId}
              />
            )}

            {!selectedType && !isEditMode && (
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
