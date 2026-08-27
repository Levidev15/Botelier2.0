"use client";

import { useState, useEffect } from "react";
import { Trash2 } from "lucide-react";
import {
  useFlowStore,
  InitialNodeData,
  MessageNodeData,
  CollectSlotNodeData,
  CollectFormNodeData,
  APIRequestNodeData,
  ConditionNodeData,
  RouterNodeData,
  ConfirmationNodeData,
  SetVariableNodeData,
  SaveRecordNodeData,
  TransferNodeData,
  CapabilityNodeData,
  EndNodeData,
  NodeType,
} from "./store";

import VariablesPanel from "./inspectors/VariablesPanel";
import InitialNodePanel from "./inspectors/InitialNodePanel";
import MessageNodePanel from "./inspectors/MessageNodePanel";
import CollectSlotNodePanel from "./inspectors/CollectSlotNodePanel";
import CollectFormNodePanel from "./inspectors/CollectFormNodePanel";
import APIRequestNodePanel from "./inspectors/APIRequestNodePanel";
import ConditionNodePanel from "./inspectors/ConditionNodePanel";
import RouterNodePanel from "./inspectors/RouterNodePanel";
import ConfirmationNodePanel from "./inspectors/ConfirmationNodePanel";
import SetVariableNodePanel from "./inspectors/SetVariableNodePanel";
import SaveRecordNodePanel from "./inspectors/SaveRecordNodePanel";
import TransferNodePanel from "./inspectors/TransferNodePanel";
import CapabilityNodePanel from "./inspectors/CapabilityNodePanel";
import EndNodePanel from "./inspectors/EndNodePanel";

type Tab = "properties" | "variables" | "instructions";

interface NodeInspectorProps {
  assistantId?: string;
  assistantTtsProvider?: string;
}

const nodeAccentColors: Record<string, string> = {
  initial:      "border-green-500",
  message:      "border-blue-500",
  collect_slot: "border-purple-500",
  collect_form: "border-violet-500",
  api_request:  "border-orange-500",
  condition:    "border-yellow-500",
  router:       "border-indigo-500",
  confirmation: "border-emerald-500",
  set_variable: "border-teal-500",
  save_record:  "border-rose-500",
  transfer:     "border-cyan-500",
  capability:   "border-purple-500",
  end:          "border-red-500",
};

const nodeTypeLabels: Record<string, string> = {
  initial:      "Greeting",
  message:      "Message",
  collect_slot: "Collect Input",
  collect_form: "Collect Form",
  api_request:  "API Request",
  condition:    "Condition",
  router:       "Router",
  confirmation: "Confirmation",
  set_variable: "Set Variable",
  save_record:  "Save Record",
  transfer:     "Transfer",
  capability:   "Capability",
  end:          "End",
};

export default function NodeInspector({
  assistantId,
  assistantTtsProvider,
}: NodeInspectorProps = {}) {
  const { selectedNode, updateNodeData, deleteNode } = useFlowStore();
  const [activeTab, setActiveTab] = useState<Tab>("variables");

  // Switch to Properties when a node is selected; back to Variables when deselected
  useEffect(() => {
    setActiveTab(selectedNode ? "properties" : "variables");
  }, [selectedNode?.id]);

  const nodeType = selectedNode?.type as NodeType | undefined;
  const accentBorder = nodeType ? (nodeAccentColors[nodeType] ?? "border-blue-500") : "";

  const renderNodePanel = () => {
    if (!selectedNode) return null;
    const data = selectedNode.data;
    switch (selectedNode.type as NodeType) {
      case "initial":
        return (
          <InitialNodePanel
            data={data as InitialNodeData}
            nodeId={selectedNode.id}
            assistantId={assistantId}
            assistantTtsProvider={assistantTtsProvider}
          />
        );
      case "message":
        return <MessageNodePanel data={data as MessageNodeData} nodeId={selectedNode.id} />;
      case "collect_slot":
        return <CollectSlotNodePanel data={data as CollectSlotNodeData} nodeId={selectedNode.id} />;
      case "collect_form":
        return <CollectFormNodePanel data={data as CollectFormNodeData} nodeId={selectedNode.id} />;
      case "api_request":
        return (
          <APIRequestNodePanel
            data={data as APIRequestNodeData}
            nodeId={selectedNode.id}
            assistantId={assistantId}
          />
        );
      case "condition":
        return <ConditionNodePanel data={data as ConditionNodeData} nodeId={selectedNode.id} />;
      case "router":
        return <RouterNodePanel data={data as RouterNodeData} nodeId={selectedNode.id} />;
      case "confirmation":
        return <ConfirmationNodePanel data={data as ConfirmationNodeData} nodeId={selectedNode.id} />;
      case "set_variable":
        return <SetVariableNodePanel data={data as SetVariableNodeData} nodeId={selectedNode.id} />;
      case "save_record":
        return <SaveRecordNodePanel data={data as SaveRecordNodeData} nodeId={selectedNode.id} />;
      case "transfer":
        return <TransferNodePanel data={data as TransferNodeData} nodeId={selectedNode.id} />;
      case "capability":
        return <CapabilityNodePanel data={data as CapabilityNodeData} nodeId={selectedNode.id} />;
      case "end":
        return <EndNodePanel data={data as EndNodeData} nodeId={selectedNode.id} />;
      default:
        return <p className="text-gray-400 text-sm">Unknown node type</p>;
    }
  };

  const tabs: { id: Tab; label: string; disabled?: boolean }[] = [
    { id: "properties",   label: "Properties",   disabled: !selectedNode },
    { id: "variables",    label: "Variables" },
    { id: "instructions", label: "Instructions",  disabled: !selectedNode },
  ];

  return (
    <div className="w-[480px] bg-[#141414] border-l border-gray-800 flex flex-col overflow-hidden flex-shrink-0">
      {/* ── Node header ─────────────────────────────────────────────────────── */}
      {selectedNode ? (
        <div
          className={`px-4 py-3 border-b border-gray-800 flex items-start gap-3 flex-shrink-0 border-l-4 ${accentBorder}`}
        >
          <div className="flex-1 min-w-0">
            <p className="text-[10px] uppercase tracking-wider text-gray-500 mb-0.5">
              {nodeTypeLabels[selectedNode.type as string] ?? selectedNode.type}
            </p>
            <input
              type="text"
              value={(selectedNode.data as any).name ?? ""}
              onChange={(e) => updateNodeData(selectedNode.id, { name: e.target.value })}
              className="w-full bg-transparent text-white text-sm font-semibold focus:outline-none placeholder:text-gray-600 border-b border-transparent focus:border-gray-600 transition-colors pb-0.5"
              placeholder="Unnamed node"
            />
          </div>
          <button
            onClick={() => deleteNode(selectedNode.id)}
            className="p-1.5 text-gray-500 hover:text-red-400 transition-colors rounded hover:bg-red-400/10 flex-shrink-0 mt-0.5"
            title="Delete node"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <div className="px-4 py-3 border-b border-gray-800 flex-shrink-0">
          <p className="text-sm font-semibold text-gray-300">Flow Inspector</p>
          <p className="text-xs text-gray-500 mt-0.5">Select a node to edit it</p>
        </div>
      )}

      {/* ── Tab bar ─────────────────────────────────────────────────────────── */}
      <div className="flex border-b border-gray-800 flex-shrink-0">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => !tab.disabled && setActiveTab(tab.id)}
            disabled={tab.disabled}
            className={[
              "flex-1 py-2.5 text-xs font-medium transition-colors select-none",
              activeTab === tab.id
                ? "text-white border-b-2 border-blue-500 -mb-px bg-[#1a1a1a]"
                : "text-gray-500",
              tab.disabled
                ? "opacity-30 cursor-not-allowed"
                : "hover:text-gray-300 cursor-pointer",
            ].join(" ")}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Tab content ─────────────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 overflow-hidden">

        {/* Properties */}
        {activeTab === "properties" && (
          <div className="h-full overflow-y-auto">
            {selectedNode ? (
              <div className="p-4 space-y-4">{renderNodePanel()}</div>
            ) : (
              <p className="text-gray-500 text-sm text-center mt-10 px-4">
                Select a node to view its properties
              </p>
            )}
          </div>
        )}

        {/* Variables */}
        {activeTab === "variables" && (
          <div className="h-full flex flex-col overflow-hidden">
            {!selectedNode && (
              <p className="px-4 pt-3 pb-0 text-xs text-gray-500">
                Variables declared here can be read and written by any node.
              </p>
            )}
            <div className="flex-1 min-h-0 overflow-hidden">
              <VariablesPanel />
            </div>
          </div>
        )}

        {/* Instructions */}
        {activeTab === "instructions" && (
          <div className="h-full overflow-y-auto p-4">
            {selectedNode ? (
              <>
                <label className="block text-sm font-medium text-gray-400 mb-1">
                  AI Instructions
                  <span className="text-xs text-gray-500 ml-2">(private)</span>
                </label>
                <textarea
                  value={(selectedNode.data as any).instructions ?? ""}
                  onChange={(e) =>
                    updateNodeData(selectedNode.id, { instructions: e.target.value })
                  }
                  rows={10}
                  className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-gray-500 focus:outline-none resize-none"
                  placeholder="e.g., Be empathetic, confirm the date includes the year, offer examples if the caller seems confused..."
                />
                <p className="text-xs text-gray-500 mt-2">
                  Private guidance for the AI on how to handle this step. Never spoken to the caller.
                </p>
              </>
            ) : (
              <p className="text-gray-500 text-sm text-center mt-10 px-4">
                Select a node to edit its AI instructions
              </p>
            )}
          </div>
        )}

      </div>
    </div>
  );
}
