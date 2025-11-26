"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  ReactFlowProvider,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useFlowStore } from "./store";
import { nodeTypes } from "./nodes";
import NodeInspector from "./NodeInspector";
import FlowToolbar from "./FlowToolbar";
import { notify } from "@/lib/notifications";

interface FlowEditorProps {
  toolId: string;
  hotelId: string;
  toolName?: string;
}

function FlowEditorInner({ toolId, hotelId, toolName }: FlowEditorProps) {
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    selectNode,
    selectedNode,
    loadFlow,
    saveFlow,
    isLoading,
    isDirty,
  } = useFlowStore();

  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    loadFlow(toolId, hotelId);
  }, [toolId, hotelId, loadFlow]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: any) => {
      selectNode(node);
    },
    [selectNode]
  );

  const onPaneClick = useCallback(() => {
    selectNode(null);
  }, [selectNode]);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await saveFlow();
      notify.success("Flow saved successfully");
    } catch (error) {
      notify.error("Failed to save flow");
    } finally {
      setIsSaving(false);
    }
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        if (isDirty && !isSaving) {
          handleSave();
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isDirty, isSaving]);


  return (
    <div className="h-full flex flex-col bg-[#0a0a0a]">
      <FlowToolbar onSave={handleSave} isSaving={isSaving} />
      
      <div className="flex-1 flex">
        <div className="flex-1 relative">
          <ReactFlow
            nodes={nodes as any}
            edges={edges}
            onNodesChange={onNodesChange as any}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            nodeTypes={nodeTypes as any}
            fitView
            snapToGrid
            snapGrid={[15, 15]}
            defaultEdgeOptions={{
              type: "smoothstep",
              animated: true,
              style: { stroke: "#3b82f6", strokeWidth: 2 },
            }}
            proOptions={{ hideAttribution: true }}
            className="bg-[#0a0a0a]"
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={20}
              size={1}
              color="#333"
            />
            <Controls
              className="!bg-[#141414] !border-gray-700 !shadow-lg"
              showInteractive={false}
            />
            <MiniMap
              className="!bg-[#141414] !border-gray-700"
              maskColor="rgba(0, 0, 0, 0.8)"
              nodeColor={(node) => {
                switch (node.type) {
                  case "initial":
                    return "#22c55e";
                  case "collect_slot":
                    return "#a855f7";
                  case "message":
                    return "#3b82f6";
                  case "api_request":
                    return "#f97316";
                  case "condition":
                    return "#eab308";
                  case "transfer":
                    return "#06b6d4";
                  case "end":
                    return "#ef4444";
                  default:
                    return "#3b82f6";
                }
              }}
            />
          </ReactFlow>

          {nodes.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div className="text-center">
                <p className="text-gray-400 text-lg mb-2">No flow configured</p>
                <p className="text-gray-500 text-sm">
                  Click &quot;Add Node&quot; or select a template to get started
                </p>
              </div>
            </div>
          )}
        </div>

        <NodeInspector />
      </div>
    </div>
  );
}

export default function FlowEditor(props: FlowEditorProps) {
  return (
    <ReactFlowProvider>
      <FlowEditorInner {...props} />
    </ReactFlowProvider>
  );
}
