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

export type SlotType = "text" | "date" | "number" | "phone" | "email" | "time" | "choice";

export interface FlowVariable {
  key: string;
  type: SlotType;
  description: string;
  required: boolean;
  defaultValue?: string;
  choices?: string[];
}

export interface SlotConfig {
  variableKey: string;
  prompt: string;
  type: SlotType;
  validation?: {
    pattern?: string;
    min?: number;
    max?: number;
    choices?: string[];
  };
  retryPrompt?: string;
  maxRetries?: number;
}

export interface APIRequestConfig {
  method: "GET" | "POST" | "PUT" | "DELETE";
  url: string;
  headers?: Record<string, string>;
  bodyTemplate?: string;
  responseMapping?: Record<string, string>;
  onSuccess?: string;
  onError?: string;
}

export interface ConditionConfig {
  variable: string;
  operator: "equals" | "not_equals" | "contains" | "greater_than" | "less_than" | "is_empty" | "is_not_empty";
  value: string;
  trueTarget?: string;
  falseTarget?: string;
}

export interface TransferConfig {
  phoneNumber: string;
  preTransferMessage?: string;
  warmTransfer?: boolean;
}

export type NodeType = 
  | "initial" 
  | "message" 
  | "collect_slot" 
  | "api_request" 
  | "condition" 
  | "transfer" 
  | "end";

export interface BaseNodeData {
  name: string;
  description?: string;
  [key: string]: unknown;
}

export interface InitialNodeData extends BaseNodeData {
  systemPrompt: string;
  greeting: string;
}

export interface MessageNodeData extends BaseNodeData {
  message: string;
  waitForResponse?: boolean;
}

export interface CollectSlotNodeData extends BaseNodeData {
  slot: SlotConfig;
}

export interface APIRequestNodeData extends BaseNodeData {
  api: APIRequestConfig;
}

export interface ConditionNodeData extends BaseNodeData {
  condition: ConditionConfig;
}

export interface TransferNodeData extends BaseNodeData {
  transfer: TransferConfig;
}

export interface EndNodeData extends BaseNodeData {
  closingMessage?: string;
}

export type NodeData = BaseNodeData;

export interface FlowState {
  nodes: Node<NodeData>[];
  edges: Edge[];
  variables: FlowVariable[];
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
  addNode: (type: NodeType, position: { x: number; y: number }) => void;
  deleteNode: (nodeId: string) => void;
  
  addVariable: (variable: FlowVariable) => void;
  updateVariable: (key: string, variable: Partial<FlowVariable>) => void;
  deleteVariable: (key: string) => void;
  
  loadFlow: (toolId: string, hotelId: string) => Promise<void>;
  saveFlow: () => Promise<void>;
  applyTemplate: (templateId: string) => void;
  clearFlow: () => void;
  
  setIsDirty: (dirty: boolean) => void;
  setToolId: (id: string) => void;
  setHotelId: (id: string) => void;
  
  getFlowConfig: () => { 
    nodes: any[]; 
    edges: any[]; 
    variables: FlowVariable[];
    initial_node: string | null;
  };
}

let nodeIdCounter = 0;

const generateNodeId = () => {
  nodeIdCounter += 1;
  return `node_${Date.now()}_${nodeIdCounter}`;
};

const getDefaultNodeData = (type: NodeType): NodeData => {
  switch (type) {
    case "initial":
      return {
        name: "Start",
        systemPrompt: "You are a helpful hotel concierge assistant. Be friendly, professional, and helpful.",
        greeting: "Hello! Thank you for calling. How may I assist you today?",
      } as InitialNodeData;
    
    case "message":
      return {
        name: "Message",
        message: "Enter your message here. Use {{variable_name}} to include collected data.",
        waitForResponse: true,
      } as MessageNodeData;
    
    case "collect_slot":
      return {
        name: "Collect Info",
        slot: {
          variableKey: "guest_name",
          prompt: "May I have your name, please?",
          type: "text",
          retryPrompt: "I didn't catch that. Could you please repeat your name?",
          maxRetries: 3,
        },
      } as CollectSlotNodeData;
    
    case "api_request":
      return {
        name: "API Call",
        api: {
          method: "POST",
          url: "https://api.example.com/reservations",
          headers: { "Content-Type": "application/json" },
          bodyTemplate: '{"check_in": "{{check_in_date}}", "guests": "{{guest_count}}"}',
          responseMapping: {
            "reservation_id": "response.id",
            "room_number": "response.room",
          },
        },
      } as APIRequestNodeData;
    
    case "condition":
      return {
        name: "Check Condition",
        condition: {
          variable: "room_available",
          operator: "equals",
          value: "true",
        },
      } as ConditionNodeData;
    
    case "transfer":
      return {
        name: "Transfer Call",
        transfer: {
          phoneNumber: "",
          preTransferMessage: "Let me connect you with our front desk team. Please hold.",
          warmTransfer: false,
        },
      } as TransferNodeData;
    
    case "end":
      return {
        name: "End Call",
        closingMessage: "Thank you for calling! Have a wonderful day.",
      } as EndNodeData;
    
    default:
      return { name: "Node" };
  }
};

const getNodeStyle = (type: NodeType) => {
  switch (type) {
    case "condition":
      return { stroke: "#f59e0b", strokeWidth: 2 };
    default:
      return { stroke: "#3b82f6", strokeWidth: 2 };
  }
};

const ROOM_BOOKING_TEMPLATE = {
  variables: [
    { key: "guest_name", type: "text" as SlotType, description: "Guest full name", required: true },
    { key: "check_in_date", type: "date" as SlotType, description: "Check-in date", required: true },
    { key: "check_out_date", type: "date" as SlotType, description: "Check-out date", required: true },
    { key: "guest_count", type: "number" as SlotType, description: "Number of guests", required: true },
    { key: "room_type", type: "choice" as SlotType, description: "Room type preference", required: false, choices: ["Standard", "Deluxe", "Suite"] },
    { key: "phone_number", type: "phone" as SlotType, description: "Contact phone number", required: true },
    { key: "email", type: "email" as SlotType, description: "Email address", required: false },
  ],
  nodes: [
    {
      id: "start_1",
      type: "initial",
      position: { x: 250, y: 0 },
      data: {
        name: "Greeting",
        systemPrompt: "You are a friendly hotel reservation assistant. Help guests book rooms efficiently.",
        greeting: "Hello! Thank you for calling. I'd be happy to help you with a room reservation. Let me gather a few details.",
      },
    },
    {
      id: "collect_name",
      type: "collect_slot",
      position: { x: 250, y: 120 },
      data: {
        name: "Get Name",
        slot: {
          variableKey: "guest_name",
          prompt: "May I have your full name for the reservation?",
          type: "text",
          retryPrompt: "I'm sorry, I didn't catch that. Could you please spell your name?",
          maxRetries: 3,
        },
      },
    },
    {
      id: "collect_checkin",
      type: "collect_slot",
      position: { x: 250, y: 240 },
      data: {
        name: "Check-in Date",
        slot: {
          variableKey: "check_in_date",
          prompt: "What date would you like to check in?",
          type: "date",
          retryPrompt: "Please provide a valid date, for example, December 15th.",
          maxRetries: 3,
        },
      },
    },
    {
      id: "collect_checkout",
      type: "collect_slot",
      position: { x: 250, y: 360 },
      data: {
        name: "Check-out Date",
        slot: {
          variableKey: "check_out_date",
          prompt: "And what date will you be checking out?",
          type: "date",
          retryPrompt: "Please provide a valid checkout date.",
          maxRetries: 3,
        },
      },
    },
    {
      id: "collect_guests",
      type: "collect_slot",
      position: { x: 250, y: 480 },
      data: {
        name: "Guest Count",
        slot: {
          variableKey: "guest_count",
          prompt: "How many guests will be staying?",
          type: "number",
          validation: { min: 1, max: 10 },
          retryPrompt: "Please tell me the number of guests, between 1 and 10.",
          maxRetries: 2,
        },
      },
    },
    {
      id: "collect_phone",
      type: "collect_slot",
      position: { x: 250, y: 600 },
      data: {
        name: "Phone Number",
        slot: {
          variableKey: "phone_number",
          prompt: "What's the best phone number to reach you?",
          type: "phone",
          retryPrompt: "Could you please repeat your phone number?",
          maxRetries: 2,
        },
      },
    },
    {
      id: "confirm_booking",
      type: "message",
      position: { x: 250, y: 720 },
      data: {
        name: "Confirm Details",
        message: "Perfect! Let me confirm: {{guest_name}}, checking in on {{check_in_date}}, checking out on {{check_out_date}}, for {{guest_count}} guests. I'll reach you at {{phone_number}}. Is this correct?",
        waitForResponse: true,
      },
    },
    {
      id: "end_success",
      type: "end",
      position: { x: 250, y: 840 },
      data: {
        name: "Booking Complete",
        closingMessage: "Wonderful! Your reservation is confirmed. You'll receive a confirmation email shortly. Is there anything else I can help you with today?",
      },
    },
  ],
  edges: [
    { id: "e1", source: "start_1", target: "collect_name" },
    { id: "e2", source: "collect_name", target: "collect_checkin" },
    { id: "e3", source: "collect_checkin", target: "collect_checkout" },
    { id: "e4", source: "collect_checkout", target: "collect_guests" },
    { id: "e5", source: "collect_guests", target: "collect_phone" },
    { id: "e6", source: "collect_phone", target: "confirm_booking" },
    { id: "e7", source: "confirm_booking", target: "end_success" },
  ],
};

const CONCIERGE_TEMPLATE = {
  variables: [
    { key: "guest_name", type: "text" as SlotType, description: "Guest name", required: false },
    { key: "room_number", type: "text" as SlotType, description: "Room number", required: false },
    { key: "request_type", type: "choice" as SlotType, description: "Type of request", required: true, choices: ["Restaurant", "Spa", "Transportation", "Activities", "Other"] },
  ],
  nodes: [
    {
      id: "start_1",
      type: "initial",
      position: { x: 250, y: 0 },
      data: {
        name: "Concierge Greeting",
        systemPrompt: "You are a knowledgeable hotel concierge. Help guests with dining recommendations, spa bookings, transportation, and local activities.",
        greeting: "Good day! This is your hotel concierge. How may I assist you today?",
      },
    },
    {
      id: "identify_need",
      type: "message",
      position: { x: 250, y: 120 },
      data: {
        name: "Identify Request",
        message: "I can help you with restaurant reservations, spa appointments, transportation, or local activities. What would you like assistance with?",
        waitForResponse: true,
      },
    },
    {
      id: "end_help",
      type: "end",
      position: { x: 250, y: 240 },
      data: {
        name: "Closing",
        closingMessage: "It was my pleasure to assist you. Enjoy your stay, and please don't hesitate to call if you need anything else!",
      },
    },
  ],
  edges: [
    { id: "e1", source: "start_1", target: "identify_need" },
    { id: "e2", source: "identify_need", target: "end_help" },
  ],
};

const ROOM_SERVICE_TEMPLATE = {
  variables: [
    { key: "room_number", type: "text" as SlotType, description: "Guest room number", required: true },
    { key: "guest_name", type: "text" as SlotType, description: "Guest name", required: false },
    { key: "order_items", type: "text" as SlotType, description: "Items ordered", required: true },
    { key: "special_instructions", type: "text" as SlotType, description: "Special dietary needs or requests", required: false },
    { key: "delivery_time", type: "time" as SlotType, description: "Preferred delivery time", required: false },
  ],
  nodes: [
    {
      id: "start_1",
      type: "initial",
      position: { x: 250, y: 0 },
      data: {
        name: "Room Service Greeting",
        systemPrompt: "You are a friendly room service operator. Help guests place orders from the in-room dining menu. Be patient and helpful with menu questions.",
        greeting: "Good evening, room service! How may I help you tonight?",
      },
    },
    {
      id: "collect_room",
      type: "collect_slot",
      position: { x: 250, y: 120 },
      data: {
        name: "Get Room Number",
        slot: {
          variableKey: "room_number",
          prompt: "May I have your room number, please?",
          type: "text",
          retryPrompt: "I'm sorry, could you repeat your room number?",
          maxRetries: 2,
        },
      },
    },
    {
      id: "take_order",
      type: "collect_slot",
      position: { x: 250, y: 240 },
      data: {
        name: "Take Order",
        slot: {
          variableKey: "order_items",
          prompt: "What would you like to order from our menu?",
          type: "text",
          retryPrompt: "Could you please repeat your order?",
          maxRetries: 3,
        },
      },
    },
    {
      id: "special_requests",
      type: "message",
      position: { x: 250, y: 360 },
      data: {
        name: "Special Requests",
        message: "Do you have any allergies or special dietary requirements I should note?",
        waitForResponse: true,
      },
    },
    {
      id: "confirm_order",
      type: "message",
      position: { x: 250, y: 480 },
      data: {
        name: "Confirm Order",
        message: "Let me confirm your order for room {{room_number}}: {{order_items}}. Your order will be delivered in approximately 30-45 minutes. Is this correct?",
        waitForResponse: true,
      },
    },
    {
      id: "end_success",
      type: "end",
      position: { x: 250, y: 600 },
      data: {
        name: "Order Complete",
        closingMessage: "Wonderful! Your order has been placed. Enjoy your meal, and please call again if you need anything else!",
      },
    },
  ],
  edges: [
    { id: "e1", source: "start_1", target: "collect_room" },
    { id: "e2", source: "collect_room", target: "take_order" },
    { id: "e3", source: "take_order", target: "special_requests" },
    { id: "e4", source: "special_requests", target: "confirm_order" },
    { id: "e5", source: "confirm_order", target: "end_success" },
  ],
};

const TEMPLATES: Record<string, typeof ROOM_BOOKING_TEMPLATE> = {
  "room-booking": ROOM_BOOKING_TEMPLATE,
  "concierge": CONCIERGE_TEMPLATE,
  "room-service": ROOM_SERVICE_TEMPLATE,
};

export const useFlowStore = create<FlowState>((set, get) => ({
  nodes: [],
  edges: [],
  variables: [],
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
    const sourceNode = get().nodes.find(n => n.id === connection.source);
    const edgeStyle = sourceNode ? getNodeStyle(sourceNode.type as NodeType) : { stroke: "#3b82f6", strokeWidth: 2 };
    
    set({
      edges: addEdge(
        {
          ...connection,
          type: "smoothstep",
          animated: true,
          style: edgeStyle,
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

  addNode: (type: NodeType, position: { x: number; y: number }) => {
    const id = generateNodeId();
    const defaultData = getDefaultNodeData(type);

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

  addVariable: (variable) => {
    set({
      variables: [...get().variables, variable],
      isDirty: true,
    });
  },

  updateVariable: (key, updates) => {
    set({
      variables: get().variables.map((v) =>
        v.key === key ? { ...v, ...updates } : v
      ),
      isDirty: true,
    });
  },

  deleteVariable: (key) => {
    set({
      variables: get().variables.filter((v) => v.key !== key),
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
            type: n.type || "message",
            position: n.position || { x: 0, y: 0 },
            data: n.data || { name: n.id },
          })),
          edges: data.flow_config.edges || [],
          variables: data.flow_config.variables || [],
          isDirty: false,
        });
      } else {
        set({
          nodes: [],
          edges: [],
          variables: [],
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
    const { toolId, hotelId, nodes, edges, variables } = get();
    if (!toolId || !hotelId) return;

    set({ isLoading: true });
    try {
      const initialNode = nodes.find((n) => n.type === "initial");
      
      const flowConfig = {
        initial_node: initialNode?.id || null,
        variables,
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
          sourceHandle: e.sourceHandle,
          targetHandle: e.targetHandle,
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

  applyTemplate: (templateId: string) => {
    const template = TEMPLATES[templateId];
    if (!template) {
      console.error("Template not found:", templateId);
      return;
    }

    set({
      nodes: template.nodes.map((n: any) => ({
        id: n.id,
        type: n.type,
        position: n.position,
        data: n.data,
      })),
      edges: template.edges.map((e: any) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        type: "smoothstep",
        animated: true,
        style: { stroke: "#3b82f6", strokeWidth: 2 },
      })),
      variables: template.variables,
      isDirty: true,
    });
  },

  clearFlow: () => set({
    nodes: [],
    edges: [],
    variables: [],
    selectedNode: null,
    isDirty: false,
    toolId: null,
  }),

  setIsDirty: (dirty) => set({ isDirty: dirty }),
  setToolId: (id) => set({ toolId: id }),
  setHotelId: (id) => set({ hotelId: id }),

  getFlowConfig: () => {
    const { nodes, edges, variables } = get();
    const initialNode = nodes.find((n) => n.type === "initial");
    
    return {
      initial_node: initialNode?.id || null,
      variables,
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
        sourceHandle: e.sourceHandle,
        targetHandle: e.targetHandle,
      })),
    };
  },
}));

export const AVAILABLE_TEMPLATES = [
  { id: "room-booking", name: "Room Booking", description: "Complete room reservation flow with guest details collection" },
  { id: "concierge", name: "Concierge Services", description: "Help guests with dining, spa, and activity requests" },
  { id: "room-service", name: "Room Service", description: "Take food and beverage orders with special dietary requirements" },
];
