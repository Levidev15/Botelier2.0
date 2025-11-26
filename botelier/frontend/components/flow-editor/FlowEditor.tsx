"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  ReactFlowProvider,
  Edge,
  EdgeProps,
  getBezierPath,
  BaseEdge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useFlowStore } from "./store";
import { nodeTypes } from "./nodes";
import NodeInspector from "./NodeInspector";
import FlowToolbar from "./FlowToolbar";
import { FlowSimulatorSidebar } from "@/components/flow-simulator";
import { notify } from "@/lib/notifications";
import { X } from "lucide-react";

interface FlowEditorProps {
  toolId: string;
  hotelId: string;
  toolName?: string;
}

function DeletableEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
  selected,
}: EdgeProps) {
  const deleteEdge = useFlowStore((state) => state.deleteEdge);
  
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const onEdgeClick = (evt: React.MouseEvent) => {
    evt.stopPropagation();
    deleteEdge(id);
  };

  return (
    <>
      <BaseEdge path={edgePath} markerEnd={markerEnd} style={style} />
      {selected && (
        <foreignObject
          width={20}
          height={20}
          x={labelX - 10}
          y={labelY - 10}
          className="edgebutton-foreignobject"
          requiredExtensions="http://www.w3.org/1999/xhtml"
        >
          <div className="flex items-center justify-center w-full h-full">
            <button
              className="w-5 h-5 bg-red-500 hover:bg-red-600 rounded-full flex items-center justify-center cursor-pointer border-2 border-[#0a0a0a] transition-colors"
              onClick={onEdgeClick}
              title="Delete connection"
            >
              <X className="w-3 h-3 text-white" />
            </button>
          </div>
        </foreignObject>
      )}
    </>
  );
}

const edgeTypes = {
  deletable: DeletableEdge,
};

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
    activeNodeId,
    setActiveNodeId,
  } = useFlowStore();

  const [isSaving, setIsSaving] = useState(false);
  const [showSimulator, setShowSimulator] = useState(false);

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


  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center bg-[#0a0a0a]">
        <div className="text-center">
          <div className="animate-spin h-8 w-8 border-4 border-cyan-600 border-t-transparent rounded-full mx-auto" />
          <p className="mt-4 text-gray-400">Loading flow...</p>
        </div>
      </div>
    );
  }

  const nodesWithHighlight = nodes.map((node) => ({
    ...node,
    data: {
      ...node.data,
      isActive: node.id === activeNodeId,
    },
  }));

  return (
    <div className="h-full flex flex-col bg-[#0a0a0a]">
      <FlowToolbar 
        onSave={handleSave} 
        isSaving={isSaving} 
        showSimulator={showSimulator}
        onToggleSimulator={() => setShowSimulator(!showSimulator)}
      />
      
      <div className="flex-1 flex min-h-0">
        <div className="flex-1 relative">
          <ReactFlow
            nodes={nodesWithHighlight as any}
            edges={edges}
            onNodesChange={onNodesChange as any}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            nodeTypes={nodeTypes as any}
            edgeTypes={edgeTypes}
            fitView
            snapToGrid
            snapGrid={[15, 15]}
            edgesReconnectable
            defaultEdgeOptions={{
              type: "deletable",
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
                if (node.id === activeNodeId) return "#22d3ee";
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
                  case "router":
                    return "#6366f1";
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

        {showSimulator && (
          <div className="w-80 flex-shrink-0">
            <FlowSimulatorSidebar
              toolId={toolId}
              toolName={toolName || "Flow"}
              onClose={() => setShowSimulator(false)}
              onNodeChange={setActiveNodeId}
            />
          </div>
        )}
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
