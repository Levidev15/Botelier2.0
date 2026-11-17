"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  ReactFlowProvider,
  useReactFlow,
  Edge,
  EdgeProps,
  getSmoothStepPath,
  BaseEdge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useFlowStore } from "./store";
import { duplicateFlowSelection } from "./flowEditorData";
import { nodeTypes } from "./nodes";
import NodeInspector from "./NodeInspector";
import FlowToolbar from "./FlowToolbar";
import FlowSchemaPanel from "./FlowSchemaPanel";
import FlowAIBuilderSidebar from "./FlowAIBuilderSidebar";
import { FlowSimulatorSidebar } from "@/components/flow-simulator";
import { notify } from "@/lib/notifications";
import { X } from "lucide-react";

interface FlowEditorProps {
  toolId: string;
  accountId: string;
  toolName?: string;
  assistantId?: string;
  assistantTtsProvider?: string;
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
  
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 8,
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

function FlowEditorInner({ toolId, accountId, toolName, assistantId, assistantTtsProvider }: FlowEditorProps) {
  const { fitView } = useReactFlow();
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    selectNode,
    selectedNode,
    duplicateSelectedNodes,
    pasteFlowSelection,
    undoFlow,
    redoFlow,
    loadFlow,
    saveFlow,
    isLoading,
    isDirty,
    activeNodeId,
    setActiveNodeId,
    errorNodeIds,
    currentSource,
    currentVersionNumber,
    currentVersionId,
    publishedVersionNumber,
  } = useFlowStore();

  const [isSaving, setIsSaving] = useState(false);
  const [showSimulator, setShowSimulator] = useState(false);
  const [showSchema, setShowSchema] = useState(false);
  const [showAIBuilder, setShowAIBuilder] = useState(false);
  const clipboardRef = useRef<{ nodes: typeof nodes; edges: Edge[] } | null>(null);

  useEffect(() => {
    loadFlow(toolId, accountId);
  }, [toolId, accountId, loadFlow]);

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
      notify.error(error instanceof Error ? error.message : "Failed to save flow");
    } finally {
      setIsSaving(false);
    }
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const editingText = !!target && (
        target.isContentEditable ||
        ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)
      );
      if (editingText) return;
      const command = e.metaKey || e.ctrlKey;
      if (command && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) redoFlow();
        else undoFlow();
      }
      if (command && e.key.toLowerCase() === "y") {
        e.preventDefault();
        redoFlow();
      }
      if (command && e.key.toLowerCase() === "c") {
        const selected = nodes.filter((node) => node.selected);
        const selection = selected.length
          ? selected
          : selectedNode
            ? nodes.filter((node) => node.id === selectedNode.id)
            : [];
        if (selection.length) {
          e.preventDefault();
          clipboardRef.current = {
            nodes: selection.map((node) => JSON.parse(JSON.stringify(node))),
            edges: edges
              .filter((edge) =>
                selection.some((node) => node.id === edge.source) &&
                selection.some((node) => node.id === edge.target)
              )
              .map((edge) => JSON.parse(JSON.stringify(edge))),
          };
        }
      }
      if (command && e.key.toLowerCase() === "v" && clipboardRef.current) {
        e.preventDefault();
        let counter = 0;
        const pasted = duplicateFlowSelection(
          clipboardRef.current.nodes,
          clipboardRef.current.edges,
          (kind) => `${kind}_${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}_${++counter}_${Math.random().toString(36).slice(2)}`}`,
        );
        pasteFlowSelection(pasted.nodes, pasted.edges);
        if (pasted.clearedReferences.length) {
          notify.info("Copied node lost an outside Record or quote reference. Review the copied node before saving.");
        }
      }
      if (command && e.key.toLowerCase() === "d") {
        e.preventDefault();
        if (duplicateSelectedNodes().length) {
          notify.info("Duplicated node lost an outside Record or quote reference. Review the copied node before saving.");
        }
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        if (isDirty && !isSaving) {
          handleSave();
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [duplicateSelectedNodes, edges, isDirty, isSaving, nodes, pasteFlowSelection, redoFlow, selectedNode, undoFlow]);

  // Scroll to error nodes whenever errorNodeIds changes (publish failure).
  // Must be before any early return to satisfy Rules of Hooks.
  useEffect(() => {
    if (errorNodeIds.length > 0) {
      fitView({
        nodes: errorNodeIds.map((id) => ({ id })),
        duration: 400,
        padding: 0.6,
        maxZoom: 1.2,
      });
    }
  }, [errorNodeIds, fitView]);

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
      isError: errorNodeIds.includes(node.id),
    },
  }));

  return (
    <div className="h-full flex flex-col bg-[#0a0a0a]">
      <FlowToolbar 
        onSave={handleSave} 
        isSaving={isSaving} 
        showSimulator={showSimulator}
        onToggleSimulator={() => { setShowSimulator(!showSimulator); setShowAIBuilder(false); setShowSchema(false); }}
        showSchema={showSchema}
        onToggleSchema={() => { setShowSchema(!showSchema); setShowAIBuilder(false); }}
        showAIBuilder={showAIBuilder}
        onToggleAIBuilder={() => { setShowAIBuilder(!showAIBuilder); setShowSchema(false); }}
      />
      
      <div className="flex-1 flex min-h-0 flex-col md:flex-row">
        <div className="flex-1 relative min-h-[32vh] md:min-h-0">
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

        <NodeInspector assistantId={assistantId} assistantTtsProvider={assistantTtsProvider} />

        {showSimulator && (
          <div className="w-80 flex-shrink-0">
            <FlowSimulatorSidebar
              toolId={toolId}
              toolName={toolName || "Flow"}
              assistantId={assistantId}
              isDirty={isDirty}
              currentSource={currentSource}
              currentVersionNumber={currentVersionNumber}
              currentVersionId={currentVersionId}
              publishedVersionNumber={publishedVersionNumber}
              isFlowLoading={isLoading}
              onClose={() => setShowSimulator(false)}
              onNodeChange={setActiveNodeId}
            />
          </div>
        )}

        {showAIBuilder && (
          <div className="w-80 flex-shrink-0">
            <FlowAIBuilderSidebar
              toolId={toolId}
              accountId={accountId}
              onClose={() => setShowAIBuilder(false)}
            />
          </div>
        )}

        {showSchema && (
          <div className="w-[420px] flex-shrink-0">
            <FlowSchemaPanel onClose={() => setShowSchema(false)} />
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
