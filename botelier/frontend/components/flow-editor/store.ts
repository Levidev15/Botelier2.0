"use client";

import { create } from "zustand";
import {
  Connection,
  Edge,
  EdgeChange,
  Node,
  NodeChange,
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
} from "@xyflow/react";

export interface FlowFunction {
  name: string;
  description: string;
  parameters?: {
    type: string;
    properties: Record<string, any>;
    required: string[];
  };
  transition_to?: string;
}

export interface NodeData {
  name: string;
  role_messages?: Array<{ role: string; content: string }>;
  task_messages?: Array<{ role: string; content: string }>;
  functions?: FlowFunction[];
  is_end_node?: boolean;
  action_type?: "message" | "data_collection" | "api_call" | "decision";
  [key: string]: unknown;
}

export interface FlowState {
  nodes: Node<NodeData>[];
  edges: Edge[];
  selectedNode: Node<NodeData> | null;
  isDirty: boolean;
  isLoading: boolean;
  toolId: string | null;
  hotelId: string | null;

  setNodes: (nodes: Node<NodeData>[]) => void;
  setEdges: (edges: Edge[]) => void;
  onNodesChange: (changes: NodeChange<Node<NodeData>>[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  
  selectNode: (node: Node<NodeData> | null) => void;
  updateNodeData: (nodeId: string, data: Partial<NodeData>) => void;
  addNode: (type: "initial" | "node" | "end", position: { x: number; y: number }) => void;
  deleteNode: (nodeId: string) => void;
  
  loadFlow: (toolId: string, hotelId: string) => Promise<void>;
  saveFlow: () => Promise<void>;
  applyTemplate: (templateId: string) => Promise<void>;
  clearFlow: () => void;
  
  setIsDirty: (dirty: boolean) => void;
  setToolId: (id: string) => void;
  setHotelId: (id: string) => void;
  
  getFlowConfig: () => { nodes: any[]; edges: any[]; initial_node: string | null };
}

let nodeIdCounter = 0;

const generateNodeId = () => {
  nodeIdCounter += 1;
  return `node_${Date.now()}_${nodeIdCounter}`;
};

export const useFlowStore = create<FlowState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNode: null,
  isDirty: false,
  isLoading: false,
  toolId: null,
  hotelId: null,

  setNodes: (nodes) => set({ nodes, isDirty: true }),
  setEdges: (edges) => set({ edges, isDirty: true }),

  onNodesChange: (changes) => {
    set({
      nodes: applyNodeChanges(changes, get().nodes),
      isDirty: true,
    });
  },

  onEdgesChange: (changes) => {
    set({
      edges: applyEdgeChanges(changes, get().edges),
      isDirty: true,
    });
  },

  onConnect: (connection) => {
    set({
      edges: addEdge(
        {
          ...connection,
          type: "smoothstep",
          animated: true,
          style: { stroke: "#3b82f6", strokeWidth: 2 },
        },
        get().edges
      ),
      isDirty: true,
    });
  },

  selectNode: (node) => set({ selectedNode: node }),

  updateNodeData: (nodeId, data) => {
    set({
      nodes: get().nodes.map((node) =>
        node.id === nodeId
          ? { ...node, data: { ...node.data, ...data } }
          : node
      ),
      selectedNode:
        get().selectedNode?.id === nodeId
          ? { ...get().selectedNode!, data: { ...get().selectedNode!.data, ...data } }
          : get().selectedNode,
      isDirty: true,
    });
  },

  addNode: (type, position) => {
    const id = generateNodeId();
    const defaultData: NodeData = {
      name: type === "initial" ? "Greeting" : type === "end" ? "End Call" : "New Node",
      role_messages: type === "initial" ? [{ role: "system", content: "You are a helpful hotel assistant." }] : [],
      task_messages: [{ role: "system", content: type === "initial" ? "Greet the caller warmly." : type === "end" ? "Thank the guest and end the call." : "Handle this step." }],
      functions: [],
      is_end_node: type === "end",
    };

    const newNode: Node<NodeData> = {
      id,
      type,
      position,
      data: defaultData,
    };

    set({
      nodes: [...get().nodes, newNode],
      isDirty: true,
    });
  },

  deleteNode: (nodeId) => {
    set({
      nodes: get().nodes.filter((n) => n.id !== nodeId),
      edges: get().edges.filter((e) => e.source !== nodeId && e.target !== nodeId),
      selectedNode: get().selectedNode?.id === nodeId ? null : get().selectedNode,
      isDirty: true,
    });
  },

  loadFlow: async (toolId: string, hotelId: string) => {
    set({ isLoading: true, toolId, hotelId });
    try {
      const response = await fetch(`/api/tools/${toolId}/flow?hotel_id=${hotelId}`);
      if (!response.ok) throw new Error("Failed to load flow");
      
      const data = await response.json();
      
      if (data.flow_config && data.flow_config.nodes) {
        set({
          nodes: data.flow_config.nodes.map((n: any) => ({
            id: n.id,
            type: n.type || "node",
            position: n.position || { x: 0, y: 0 },
            data: n.data || { name: n.id },
          })),
          edges: data.flow_config.edges || [],
          isDirty: false,
        });
      } else {
        set({
          nodes: [],
          edges: [],
          isDirty: false,
        });
      }
    } catch (error) {
      console.error("Failed to load flow:", error);
    } finally {
      set({ isLoading: false });
    }
  },

  saveFlow: async () => {
    const { toolId, hotelId, nodes, edges } = get();
    if (!toolId || !hotelId) return;

    set({ isLoading: true });
    try {
      const initialNode = nodes.find((n) => n.type === "initial");
      
      const flowConfig = {
        initial_node: initialNode?.id || null,
        nodes: nodes.map((n) => ({
          id: n.id,
          type: n.type,
          position: n.position,
          data: n.data,
        })),
        edges: edges.map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
        })),
      };

      const response = await fetch(`/api/tools/${toolId}/flow?hotel_id=${hotelId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ flow_config: flowConfig }),
      });

      if (!response.ok) throw new Error("Failed to save flow");
      
      set({ isDirty: false });
    } catch (error) {
      console.error("Failed to save flow:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  applyTemplate: async (templateId: string) => {
    set({ isLoading: true });
    try {
      const response = await fetch(`/api/flow-templates/${templateId}`);
      if (!response.ok) throw new Error("Failed to load template");
      
      const template = await response.json();
      const flowConfig = template.flow_config;
      
      set({
        nodes: flowConfig.nodes.map((n: any) => ({
          id: n.id,
          type: n.type || "node",
          position: n.position || { x: 0, y: 0 },
          data: n.data || { name: n.id },
        })),
        edges: flowConfig.edges || [],
        isDirty: true,
      });
    } catch (error) {
      console.error("Failed to apply template:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  clearFlow: () => set({
    nodes: [],
    edges: [],
    selectedNode: null,
    isDirty: false,
    toolId: null,
  }),

  setIsDirty: (dirty) => set({ isDirty: dirty }),
  setToolId: (id) => set({ toolId: id }),
  setHotelId: (id) => set({ hotelId: id }),

  getFlowConfig: () => {
    const { nodes, edges } = get();
    const initialNode = nodes.find((n) => n.type === "initial");
    
    return {
      initial_node: initialNode?.id || null,
      nodes: nodes.map((n) => ({
        id: n.id,
        type: n.type,
        position: n.position,
        data: n.data,
      })),
      edges: edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
      })),
    };
  },
}));
