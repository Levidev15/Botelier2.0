"use client";

import { Trash2 } from "lucide-react";
import {
  useFlowStore,
  NodeData,
  InitialNodeData,
  MessageNodeData,
  CollectSlotNodeData,
  CollectFormNodeData,
  APIRequestNodeData,
  ConditionNodeData,
  RouterNodeData,
  ConfirmationNodeData,
  SetVariableNodeData,
  TransferNodeData,
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
import TransferNodePanel from "./inspectors/TransferNodePanel";
import EndNodePanel from "./inspectors/EndNodePanel";

export default function NodeInspector() {
  const { selectedNode, updateNodeData, deleteNode } = useFlowStore();

  if (!selectedNode) {
    return (
      <div className="w-80 bg-[#141414] border-l border-gray-800 p-4">
        <VariablesPanel />
        <div className="mt-4 text-gray-400 text-sm">
          <p>Select a node to edit its properties</p>
        </div>
      </div>
    );
  }

  const nodeType = selectedNode.type as NodeType;
  const data = selectedNode.data;

  const renderNodePanel = () => {
    switch (nodeType) {
      case "initial":
        return <InitialNodePanel data={data as InitialNodeData} nodeId={selectedNode.id} />;
      case "message":
        return <MessageNodePanel data={data as MessageNodeData} nodeId={selectedNode.id} />;
      case "collect_slot":
        return <CollectSlotNodePanel data={data as CollectSlotNodeData} nodeId={selectedNode.id} />;
      case "collect_form":
        return <CollectFormNodePanel data={data as CollectFormNodeData} nodeId={selectedNode.id} />;
      case "api_request":
        return <APIRequestNodePanel data={data as APIRequestNodeData} nodeId={selectedNode.id} />;
      case "condition":
        return <ConditionNodePanel data={data as ConditionNodeData} nodeId={selectedNode.id} />;
      case "router":
        return <RouterNodePanel data={data as RouterNodeData} nodeId={selectedNode.id} />;
      case "confirmation":
        return <ConfirmationNodePanel data={data as ConfirmationNodeData} nodeId={selectedNode.id} />;
      case "set_variable":
        return <SetVariableNodePanel data={data as SetVariableNodeData} nodeId={selectedNode.id} />;
      case "transfer":
        return <TransferNodePanel data={data as TransferNodeData} nodeId={selectedNode.id} />;
      case "end":
        return <EndNodePanel data={data as EndNodeData} nodeId={selectedNode.id} />;
      default:
        return <div className="text-gray-400 text-sm">Unknown node type</div>;
    }
  };

  const nodeColors: Record<string, string> = {
    initial: "border-green-500",
    message: "border-blue-500",
    collect_slot: "border-purple-500",
    collect_form: "border-violet-500",
    api_request: "border-orange-500",
    condition: "border-yellow-500",
    router: "border-indigo-500",
    confirmation: "border-emerald-500",
    set_variable: "border-teal-500",
    transfer: "border-cyan-500",
    end: "border-red-500",
  };

  return (
    <div className="w-80 bg-[#141414] border-l border-gray-800 overflow-y-auto">
      <VariablesPanel />

      <div className={`p-4 border-b border-gray-800 flex items-center justify-between ${nodeColors[nodeType] || ""}`}>
        <h3 className="font-semibold text-white">Node Properties</h3>
        <button
          onClick={() => deleteNode(selectedNode.id)}
          className="p-1 text-gray-400 hover:text-red-400 transition"
          title="Delete node"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      <div className="p-4 space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-400 mb-1">Node Name</label>
          <input
            type="text"
            value={(data as any).name || ""}
            onChange={(e) => updateNodeData(selectedNode.id, { name: e.target.value })}
            className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>

        {renderNodePanel()}

        <div className="pt-4 border-t border-gray-800">
          <label className="block text-sm font-medium text-gray-400 mb-1">
            AI Instructions
            <span className="text-xs text-gray-500 ml-2">(private)</span>
          </label>
          <textarea
            value={(data as any).instructions || ""}
            onChange={(e) => updateNodeData(selectedNode.id, { instructions: e.target.value })}
            rows={3}
            className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-gray-500 focus:outline-none resize-none"
            placeholder="e.g., Be empathetic, confirm date includes year, offer examples if guest seems confused..."
          />
          <p className="text-xs text-gray-500 mt-1">
            Private guidance for the AI on how to handle this step
          </p>
        </div>
      </div>
    </div>
  );
}
