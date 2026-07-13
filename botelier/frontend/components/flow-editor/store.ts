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
import { getAccountContext } from "@/lib/auth/accountContext";

function getAuthHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = localStorage.getItem("botelier_token");
  if (!token) return {};
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
  };
  const ctx = getAccountContext();
  if (ctx?.isAdminSession && ctx.sessionToken) {
    headers["X-Support-Session"] = ctx.sessionToken;
    headers["X-Account-Id"] = ctx.accountId;
  }
  return headers;
}

export type SlotType = "text" | "date" | "number" | "phone" | "email" | "time" | "choice";

export interface FlowVariable {
  key: string;
  type: SlotType;
  description: string;
  required: boolean;
  defaultValue?: string;
  choices?: string[];
}

export interface SlotValidation {
  pattern?: string;
  min?: number;
  max?: number;
  minLength?: number;
  maxLength?: number;
  choices?: string[];
  requireFuture?: boolean;
  minDaysAhead?: number;
  maxDaysAhead?: number;
  allowDecimal?: boolean;
  crossFieldCheck?: {
    compareWith: string;
    operator: "after" | "before" | "greater" | "less";
    errorMessage: string;
  };
}

export interface SlotConfig {
  variableKey: string;
  prompt: string;
  type: SlotType;
  validation?: SlotValidation;
  retryPrompt?: string;
  maxRetries?: number;
  useBuiltInValidator?: boolean;
}

export interface APIRequestConfig {
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  url: string;
  headers?: Record<string, string>;
  bodyTemplate?: string;
  responseMapping?: Record<string, string>;
  responseInstructions?: string;
  thinkingMessage?: string;
  timeout?: number;
  retryCount?: number;
  retryDelay?: number;
  onSuccess?: string;
  onError?: string;
  onNotFound?: string;
  onAuthError?: string;
  apiSource?: "custom" | "integration";
  integrationId?: string;
  integrationSlug?: string;
  endpointId?: string;
  endpointName?: string;
  autoMappingSource?: Record<string, string>;
  queryParamOverrides?: Record<string, string>;
}

export interface ConfirmationConfig {
  summaryTemplate: string;
  confirmPrompt: string;
  editPrompt?: string;
  variablesToConfirm: string[];
  allowEdit?: boolean;
  deliveryMode?: DeliveryMode;
}

export interface SetVariableConfig {
  variableKey: string;
  valueType: "static" | "template" | "expression";
  value: string;
}

export interface SaveRecordConfig {
  recordTypeId: string;
  recordTypeName?: string;
  // Map of record-type field key -> template string (supports {{variable}}).
  mapping: Record<string, string>;
  // Optional static/template status; validated against the type's status_options.
  status?: string;
}

export interface ConditionConfig {
  variable: string;
  operator: "equals" | "not_equals" | "contains" | "greater_than" | "less_than" | "is_empty" | "is_not_empty";
  value: string;
  trueTarget?: string;
  falseTarget?: string;
}

export interface RouterOption {
  id: string;
  value: string;
  label: string;
}

export interface RouterConfig {
  variable: string;
  options: RouterOption[];
}

export interface TransferConfig {
  phoneNumber: string;
  preTransferMessage?: string;
  warmTransfer?: boolean;
  transferMode?: "warm" | "cold";
}

export type NodeType = 
  | "initial" 
  | "message" 
  | "collect_slot"
  | "collect_form"
  | "api_request" 
  | "condition" 
  | "router"
  | "confirmation"
  | "set_variable"
  | "save_record"
  | "transfer" 
  | "end";

export interface BaseNodeData {
  name: string;
  description?: string;
  instructions?: string; // Private LLM instructions for how to handle this node
  [key: string]: unknown;
}

export interface InitialNodeData extends BaseNodeData {
  systemPrompt: string;
  greeting: string;
  waitForResponse?: boolean;
}

export type DeliveryMode = "guided" | "static";

export interface MessageNodeData extends BaseNodeData {
  message: string;
  waitForResponse?: boolean;
  deliveryMode?: DeliveryMode;
}

export interface CollectSlotNodeData extends BaseNodeData {
  slot: SlotConfig;
}

export interface FormSlotConfig extends SlotConfig {
  id: string;
  order: number;
}

export interface CollectFormNodeData extends BaseNodeData {
  introMessage?: string;
  slots: FormSlotConfig[];
}

export interface APIRequestNodeData extends BaseNodeData {
  api: APIRequestConfig;
}

export interface ConditionNodeData extends BaseNodeData {
  condition: ConditionConfig;
}

export interface RouterNodeData extends BaseNodeData {
  router: RouterConfig;
}

export interface ConfirmationNodeData extends BaseNodeData {
  confirmation: ConfirmationConfig;
}

export interface SetVariableNodeData extends BaseNodeData {
  setVariable: SetVariableConfig;
}

export interface SaveRecordNodeData extends BaseNodeData {
  saveRecord: SaveRecordConfig;
}

export interface TransferNodeData extends BaseNodeData {
  transfer: TransferConfig;
}

export interface EndNodeData extends BaseNodeData {
  closingMessage?: string;
}

export type NodeData = BaseNodeData;

export interface FlowVersionInfo {
  id: string;
  version_number: number;
  status: "draft" | "published";
  description: string | null;
  created_at: string | null;
  published_at: string | null;
}

export interface FlowState {
  nodes: Node<NodeData>[];
  edges: Edge[];
  variables: FlowVariable[];
  globalPrompt: string;
  selectedNode: Node<NodeData> | null;
  activeNodeId: string | null; // For simulator highlighting
  isDirty: boolean;
  isLoading: boolean;
  toolId: string | null;
  accountId: string | null;
  
  // Versioning state
  currentSource: "draft" | "published" | "legacy";
  currentVersionNumber: number;
  publishedVersionNumber: number;
  hasDraft: boolean;
  hasPublished: boolean;
  versions: FlowVersionInfo[];
  draftDescription: string;

  setNodes: (nodes: Node<NodeData>[]) => void;
  setEdges: (edges: Edge[]) => void;
  onNodesChange: (changes: NodeChange<Node<NodeData>>[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  
  selectNode: (node: Node<NodeData> | null) => void;
  setActiveNodeId: (nodeId: string | null) => void;
  updateNodeData: (nodeId: string, data: Partial<NodeData>) => void;
  addNode: (type: NodeType, position: { x: number; y: number }) => void;
  deleteNode: (nodeId: string) => void;
  deleteEdge: (edgeId: string) => void;
  
  addVariable: (variable: FlowVariable) => void;
  updateVariable: (key: string, variable: Partial<FlowVariable>) => void;
  deleteVariable: (key: string) => void;
  
  setGlobalPrompt: (prompt: string) => void;
  
  loadFlow: (toolId: string, accountId: string, source?: "draft" | "published") => Promise<void>;
  saveFlow: (description?: string) => Promise<void>;
  publishFlow: (description?: string) => Promise<void>;
  discardDraft: () => Promise<void>;
  loadVersions: () => Promise<void>;
  revertToVersion: (versionNumber: number, publishImmediately?: boolean) => Promise<void>;
  setDraftDescription: (description: string) => void;
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
    globalPrompt: string;
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
        systemPrompt: "",
        greeting: "",
        waitForResponse: true,
      } as InitialNodeData;
    
    case "message":
      return {
        name: "Message",
        message: "",
        waitForResponse: true,
      } as MessageNodeData;
    
    case "collect_slot":
      return {
        name: "Collect Info",
        slot: {
          variableKey: "",
          prompt: "",
          type: "text",
          retryPrompt: "",
          maxRetries: 3,
        },
      } as CollectSlotNodeData;
    
    case "collect_form":
      return {
        name: "Collect Form",
        introMessage: "",
        slots: [],
      } as CollectFormNodeData;
    
    case "api_request":
      return {
        name: "API Call",
        api: {
          method: "POST",
          url: "",
          headers: { "Content-Type": "application/json" },
          bodyTemplate: "",
          responseMapping: {},
          timeout: 8,
          retryCount: 0,
        },
      } as APIRequestNodeData;
    
    case "condition":
      return {
        name: "Check Condition",
        condition: {
          variable: "",
          operator: "equals",
          value: "",
        },
      } as ConditionNodeData;
    
    case "router":
      return {
        name: "Router",
        router: {
          variable: "",
          options: [],
        },
      } as RouterNodeData;
    
    case "confirmation":
      return {
        name: "Confirm Details",
        confirmation: {
          summaryTemplate: "",
          confirmPrompt: "",
          editPrompt: "",
          variablesToConfirm: [],
          allowEdit: true,
        },
      } as ConfirmationNodeData;
    
    case "set_variable":
      return {
        name: "Set Variable",
        setVariable: {
          variableKey: "",
          valueType: "static",
          value: "",
        },
      } as SetVariableNodeData;

    case "save_record":
      return {
        name: "Save Record",
        saveRecord: {
          recordTypeId: "",
          recordTypeName: "",
          mapping: {},
          status: "",
        },
      } as SaveRecordNodeData;
    
    case "transfer":
      return {
        name: "Transfer Call",
        transfer: {
          phoneNumber: "",
          preTransferMessage: "",
          warmTransfer: false,
        },
      } as TransferNodeData;
    
    case "end":
      return {
        name: "End Call",
        closingMessage: "",
      } as EndNodeData;
    
    default:
      return { name: "Node" };
  }
};

const getNodeStyle = (type: NodeType) => {
  switch (type) {
    case "condition":
      return { stroke: "#f59e0b", strokeWidth: 2 };
    case "router":
      return { stroke: "#6366f1", strokeWidth: 2 };
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

const OPERA_OHIP_BOOKING_TEMPLATE = {
  variables: [
    { key: "check_in_date",       type: "date"   as SlotType, description: "Check-in date",                                  required: true  },
    { key: "check_out_date",      type: "date"   as SlotType, description: "Check-out date",                                 required: true  },
    { key: "guest_count",         type: "number" as SlotType, description: "Number of adult guests",                         required: true  },
    { key: "available_rooms",     type: "text"   as SlotType, description: "Available room types (from OHIP availability)",  required: false },
    { key: "rates",               type: "text"   as SlotType, description: "Available rate plans (from OHIP availability)",  required: false },
    { key: "room_type",           type: "text"   as SlotType, description: "Selected room type code",                        required: true  },
    { key: "rate_code",           type: "text"   as SlotType, description: "Selected rate plan code",                        required: true  },
    { key: "guest_first_name",    type: "text"   as SlotType, description: "Guest first name",                               required: true  },
    { key: "guest_last_name",     type: "text"   as SlotType, description: "Guest last name",                                required: true  },
    { key: "confirmation_number", type: "text"   as SlotType, description: "Reservation confirmation number (from Opera)",   required: false },
    { key: "booking_id",          type: "text"   as SlotType, description: "System reservation ID (from Opera)",             required: false },
  ],
  nodes: [
    {
      id: "start_1",
      type: "initial",
      position: { x: 250, y: 0 },
      data: {
        name: "Greeting",
        systemPrompt:
          "You are a reservations agent for a property using Oracle Opera OHIP. " +
          "Help callers check room availability and complete a booking. " +
          "Collect check-in and check-out dates and guest count first, then check live availability via the integration. " +
          "Present the available room types and rate plans clearly, ask the caller to choose one of each, " +
          "then collect their name. Always confirm the full booking summary before submitting to Opera.",
        greeting:
          "Thank you for calling. I'd be happy to help you with a reservation. " +
          "Could I start with your desired check-in and check-out dates?",
      } as InitialNodeData,
    },
    {
      id: "collect_checkin",
      type: "collect_slot",
      position: { x: 250, y: 150 },
      data: {
        name: "Check-in Date",
        slot: {
          variableKey: "check_in_date",
          prompt: "What date would you like to check in?",
          type: "date",
          validation: { requireFuture: true },
          retryPrompt: "Please provide a future date — for example, the 15th of December.",
          maxRetries: 3,
          useBuiltInValidator: true,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "collect_checkout",
      type: "collect_slot",
      position: { x: 250, y: 300 },
      data: {
        name: "Check-out Date",
        slot: {
          variableKey: "check_out_date",
          prompt: "And what date will you be checking out?",
          type: "date",
          validation: {
            requireFuture: true,
            crossFieldCheck: {
              compareWith: "check_in_date",
              operator: "after",
              errorMessage: "Check-out must be after your check-in date.",
            },
          },
          retryPrompt: "Your check-out date must be after your check-in date. Could you repeat it?",
          maxRetries: 3,
          useBuiltInValidator: true,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "collect_guests",
      type: "collect_slot",
      position: { x: 250, y: 450 },
      data: {
        name: "Guest Count",
        slot: {
          variableKey: "guest_count",
          prompt: "How many adults will be staying?",
          type: "number",
          validation: { min: 1, max: 10 },
          retryPrompt: "Please give me a number between 1 and 10.",
          maxRetries: 2,
          useBuiltInValidator: true,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "check_availability",
      type: "api_request",
      position: { x: 250, y: 600 },
      data: {
        name: "Check Availability (Opera OHIP)",
        instructions:
          "After this node completes, present the available room types and rate plans to the caller. " +
          "If no rooms are available, apologise and offer to try different dates.",
        api: {
          method: "GET",
          url: "",
          apiSource: "integration",
          integrationId: "",
          integrationSlug: "opera-cloud",
          endpointId: "check_availability",
          endpointName: "Check Room Availability",
          thinkingMessage: "Let me check availability for those dates — one moment please.",
          responseMapping: {
            available_rooms: "$.hotelAvailability[*].roomStays[*].roomRates[*].roomType",
            rates:           "$.hotelAvailability[*].roomStays[*].roomRates[*].ratePlanCode",
          },
          autoMappingSource: {
            available_rooms: "$.hotelAvailability[*].roomStays[*].roomRates[*].roomType",
            rates:           "$.hotelAvailability[*].roomStays[*].roomRates[*].ratePlanCode",
          },
          responseInstructions:
            "Describe the available room types and their rate plans to the caller. " +
            "Ask which room type and rate plan they would like.",
          timeout: 15,
          retryCount: 1,
        } as APIRequestConfig,
      } as APIRequestNodeData,
    },
    {
      id: "collect_room",
      type: "collect_slot",
      position: { x: 250, y: 750 },
      data: {
        name: "Room Type Selection",
        slot: {
          variableKey: "room_type",
          prompt:
            "Which room type would you prefer? The available options are: {{available_rooms}}. " +
            "Please tell me the room type code or name.",
          type: "text",
          retryPrompt: "Could you repeat which room type you'd like?",
          maxRetries: 3,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "collect_rate",
      type: "collect_slot",
      position: { x: 250, y: 900 },
      data: {
        name: "Rate Plan Selection",
        slot: {
          variableKey: "rate_code",
          prompt:
            "And which rate plan would you like? The available plans are: {{rates}}. " +
            "Please tell me the rate plan code or name.",
          type: "text",
          retryPrompt: "Could you repeat which rate plan you'd like?",
          maxRetries: 3,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "collect_first_name",
      type: "collect_slot",
      position: { x: 250, y: 1050 },
      data: {
        name: "Guest First Name",
        slot: {
          variableKey: "guest_first_name",
          prompt: "May I have the guest's first name for the reservation?",
          type: "text",
          retryPrompt: "Could you spell the first name for me?",
          maxRetries: 3,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "collect_last_name",
      type: "collect_slot",
      position: { x: 250, y: 1200 },
      data: {
        name: "Guest Last Name",
        slot: {
          variableKey: "guest_last_name",
          prompt: "And the last name?",
          type: "text",
          retryPrompt: "Could you spell the last name for me?",
          maxRetries: 3,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "confirm_details",
      type: "confirmation",
      position: { x: 250, y: 1350 },
      data: {
        name: "Confirm Booking Details",
        confirmation: {
          summaryTemplate:
            "Just to confirm: a {{room_type}} room on the {{rate_code}} rate plan, " +
            "for {{guest_count}} adult(s), checking in {{check_in_date}} and checking out {{check_out_date}}, " +
            "under {{guest_first_name}} {{guest_last_name}}.",
          confirmPrompt: "Shall I go ahead and create this reservation in Opera?",
          editPrompt: "No problem — what would you like to change?",
          variablesToConfirm: [
            "check_in_date",
            "check_out_date",
            "guest_count",
            "room_type",
            "rate_code",
            "guest_first_name",
            "guest_last_name",
          ],
          allowEdit: true,
          deliveryMode: "guided",
        },
      } as ConfirmationNodeData,
    },
    {
      id: "create_booking",
      type: "api_request",
      position: { x: 250, y: 1500 },
      data: {
        name: "Create Reservation (Opera OHIP)",
        instructions:
          "After this node completes, read the confirmation number back to the caller clearly, " +
          "spelling it out if needed.",
        api: {
          method: "POST",
          url: "",
          apiSource: "integration",
          integrationId: "",
          integrationSlug: "opera-cloud",
          endpointId: "create_reservation",
          endpointName: "Create Reservation",
          thinkingMessage: "Creating your reservation in Opera now — just a moment.",
          responseMapping: {
            confirmation_number: "$.reservationId.id",
            booking_url:         "$.links[0].href",
          },
          autoMappingSource: {
            confirmation_number: "$.reservationId.id",
            booking_url:         "$.links[0].href",
          },
          responseInstructions:
            "Tell the caller their reservation is confirmed in Opera and read out their confirmation number: {{confirmation_number}}. " +
            "Offer to repeat it if needed.",
          timeout: 20,
          retryCount: 1,
        } as APIRequestConfig,
      } as APIRequestNodeData,
    },
    {
      id: "end_success",
      type: "end",
      position: { x: 250, y: 1650 },
      data: {
        name: "Booking Confirmed",
        closingMessage:
          "Your reservation is confirmed in Opera! Your confirmation number is {{confirmation_number}}. " +
          "We look forward to welcoming you. Is there anything else I can help you with?",
      } as EndNodeData,
    },
  ],
  edges: [
    { id: "e1",  source: "start_1",           target: "collect_checkin"    },
    { id: "e2",  source: "collect_checkin",    target: "collect_checkout"   },
    { id: "e3",  source: "collect_checkout",   target: "collect_guests"     },
    { id: "e4",  source: "collect_guests",     target: "check_availability" },
    { id: "e5",  source: "check_availability", target: "collect_room"       },
    { id: "e6",  source: "collect_room",       target: "collect_rate"       },
    { id: "e7",  source: "collect_rate",       target: "collect_first_name" },
    { id: "e8",  source: "collect_first_name", target: "collect_last_name"  },
    { id: "e9",  source: "collect_last_name",  target: "confirm_details"    },
    { id: "e10", source: "confirm_details",    target: "create_booking"     },
    { id: "e11", source: "create_booking",     target: "end_success"        },
  ],
};

const GUESTCENTRIC_CRS_BOOKING_TEMPLATE = {
  variables: [
    { key: "hotel_id",               type: "text"   as SlotType, description: "GuestCentric hotel ID for this property",                       required: true,  defaultValue: "" },
    { key: "hotel_name",             type: "text"   as SlotType, description: "Hotel name as registered in GuestCentric (used in booking payload)", required: true, defaultValue: "" },
    { key: "hotel_reservations_email", type: "text" as SlotType, description: "Hotel reservations email GuestCentric will notify",                required: true,  defaultValue: "" },
    { key: "checkin",                type: "date"   as SlotType, description: "Check-in date (GuestCentric `checkin` param)",                     required: true  },
    { key: "checkout",               type: "date"   as SlotType, description: "Check-out date (GuestCentric `checkout` param)",                   required: true  },
    { key: "adults",                 type: "number" as SlotType, description: "Number of adult guests (GuestCentric `adults` query param for availability)", required: true  },
    { key: "number_of_adults",       type: "number" as SlotType, description: "Number of adult guests (GuestCentric `number_of_adults` body field for booking — auto-copied from `adults`)", required: false, defaultValue: "1" },
    { key: "available_rooms",        type: "text"   as SlotType, description: "Available room names (from GuestCentric hotel rooms)",             required: false },
    { key: "rates",                  type: "text"   as SlotType, description: "Available rate plan codes (from GuestCentric hotel rooms)",         required: false },
    { key: "room_rates",             type: "text"   as SlotType, description: "Full room+rate combinations JSON (from GuestCentric hotel rooms)", required: false },
    { key: "room_type_code",         type: "text"   as SlotType, description: "Selected room type code",                                          required: true  },
    { key: "rate_plan_code",         type: "text"   as SlotType, description: "Selected rate plan code",                                          required: true  },
    { key: "room_rate_code",         type: "text"   as SlotType, description: "Room + rate combination code (auto-derived by re-checking availability for the selected room + rate)", required: true },
    { key: "total_price",            type: "number" as SlotType, description: "Total stay price for the selected room/rate (auto-derived by re-checking availability)", required: true },
    { key: "number_of_rooms",        type: "number" as SlotType, description: "Number of rooms to book",                                          required: false, defaultValue: "1" },
    { key: "number_of_children",     type: "number" as SlotType, description: "Number of children",                                               required: false, defaultValue: "0" },
    { key: "guest_first_name",       type: "text"   as SlotType, description: "Guest first name",                                                 required: true  },
    { key: "guest_last_name",        type: "text"   as SlotType, description: "Guest last name",                                                  required: true  },
    { key: "guest_email",            type: "text"   as SlotType, description: "Guest email address",                                              required: true  },
    { key: "guest_phone",            type: "text"   as SlotType, description: "Guest phone number",                                               required: true  },
    { key: "guest_address",          type: "text"   as SlotType, description: "Guest mailing address (required by GuestCentric)",                 required: true  },
    { key: "guest_city",             type: "text"   as SlotType, description: "Guest city (required by GuestCentric)",                            required: true  },
    { key: "guest_postal_code",      type: "text"   as SlotType, description: "Guest postal code (required by GuestCentric)",                     required: true  },
    { key: "guest_country",          type: "text"   as SlotType, description: "Guest country (required by GuestCentric)",                         required: true  },
    { key: "hotels",                 type: "text"   as SlotType, description: "JSON array of hotel IDs for the Cancellation Policies lookup (auto-built from hotel_id)", required: false },
    { key: "cancellation_policy_id", type: "text"   as SlotType, description: "Cancellation policy ID for this property (auto-derived from the Cancellation Policies endpoint)", required: true },
    { key: "meal_plan_id",           type: "text"   as SlotType, description: "Included meal plan ID for the selected room/rate (auto-derived by re-checking availability)", required: true },
    { key: "meal_plan_net",          type: "number" as SlotType, description: "Meal plan net price",                                              required: false, defaultValue: "0" },
    { key: "meal_plan_tax",          type: "number" as SlotType, description: "Meal plan tax",                                                    required: false, defaultValue: "0" },
    { key: "meal_plan_total",        type: "number" as SlotType, description: "Meal plan total price",                                            required: false, defaultValue: "0" },
    { key: "crs_reservation_code",   type: "text"   as SlotType, description: "CRS reservation code (from GuestCentric)",                         required: false },
    { key: "hotel_reservation_code", type: "text"   as SlotType, description: "Hotel-side reservation code (from GuestCentric)",                  required: false },
    { key: "booking_status",         type: "text"   as SlotType, description: "Reservation status (from GuestCentric)",                           required: false },
  ],
  nodes: [
    {
      id: "start_1",
      type: "initial",
      position: { x: 250, y: 0 },
      data: {
        name: "Greeting",
        systemPrompt:
          "You are a reservations agent for a property using the GuestCentric CRS. " +
          "Help callers check room availability and complete a booking. " +
          "Collect check-in and check-out dates and guest count first, then check live availability via the integration. " +
          "Present the available room types and rate plans clearly, ask the caller to choose one of each, " +
          "then collect their name, email, and phone. Always confirm the full booking summary before submitting to GuestCentric.",
        greeting:
          "Thank you for calling. I'd be happy to help you check availability and book a room. " +
          "Could I start with your desired check-in and check-out dates?",
      } as InitialNodeData,
    },
    {
      id: "collect_checkin",
      type: "collect_slot",
      position: { x: 250, y: 150 },
      data: {
        name: "Check-in Date",
        slot: {
          variableKey: "checkin",
          prompt: "What date would you like to check in?",
          instructions: "Once the caller provides the date, store it in YYYY-MM-DD format (e.g. 2025-12-15). The date must be today or a future date.",
          type: "date",
          validation: { requireFuture: true },
          retryPrompt: "Please provide a future check-in date.",
          maxRetries: 3,
          useBuiltInValidator: true,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "collect_checkout",
      type: "collect_slot",
      position: { x: 250, y: 300 },
      data: {
        name: "Check-out Date",
        slot: {
          variableKey: "checkout",
          prompt: "And what date will you be checking out?",
          instructions: "Once the caller provides the date, store it in YYYY-MM-DD format (e.g. 2025-12-18). The date must be after the check-in date.",
          type: "date",
          validation: {
            requireFuture: true,
            crossFieldCheck: {
              compareWith: "checkin",
              operator: "after",
              errorMessage: "Check-out must be after your check-in date.",
            },
          },
          retryPrompt: "Your check-out date must be after your check-in date. Could you repeat it?",
          maxRetries: 3,
          useBuiltInValidator: true,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "collect_guests",
      type: "collect_slot",
      position: { x: 250, y: 450 },
      data: {
        name: "Guest Count",
        slot: {
          variableKey: "adults",
          prompt: "How many adults will be staying?",
          type: "number",
          validation: { min: 1, max: 10 },
          retryPrompt: "Please give me a number between 1 and 10.",
          maxRetries: 2,
          useBuiltInValidator: true,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "sync_number_of_adults",
      type: "set_variable",
      position: { x: 250, y: 525 },
      data: {
        name: "Sync Adults for Booking",
        setVariable: {
          variableKey: "number_of_adults",
          valueType: "template",
          value: "{{adults}}",
        },
      } as SetVariableNodeData,
    },
    {
      id: "check_availability",
      type: "api_request",
      position: { x: 250, y: 600 },
      data: {
        name: "Check Availability (GuestCentric)",
        instructions:
          "After this node completes, present the available room types clearly by name, then present the available " +
          "rate plans. Ask the caller to choose one of each. " +
          "If no rooms are available or this call fails, apologise and ask if they would like to try different " +
          "dates — do NOT transfer the call.",
        api: {
          method: "GET",
          url: "",
          apiSource: "integration",
          integrationId: "",
          integrationSlug: "guestcentric-crs",
          endpointId: "hotel_rooms",
          endpointName: "Hotel Rooms & Rates",
          thinkingMessage: "Let me check room availability for those dates — one moment please.",
          responseMapping: {
            available_rooms: "$.rooms[*].name",
            rates:           "$.rates[*].rate_plan_name",
            room_rates:      "$.room_rates",
          },
          autoMappingSource: {
            available_rooms: "$.rooms[*].name",
            rates:           "$.rates[*].rate_plan_name",
            room_rates:      "$.room_rates",
          },
          responseInstructions:
            "Availability results: {{room_rates}}\n\n" +
            "Each JSON object in this list contains:\n" +
            "- room_type_name: display name to speak to the caller (e.g. \"Superior Room\")\n" +
            "- room_type_code: internal code to store as room_type_code when that room is chosen (e.g. \"SUP\")\n" +
            "- rate_plan_name: rate plan display name (e.g. \"Best Available Rate\")\n" +
            "- rate_plan_code: internal code to store as rate_plan_code when that plan is chosen\n" +
            "- total_price: total stay price\n\n" +
            "Steps:\n" +
            "1. Extract unique room types (deduplicate by room_type_code). List each by its room_type_name.\n" +
            "2. Extract unique rate plans (deduplicate by rate_plan_code). List each by its rate_plan_name.\n" +
            "3. Ask the caller which room type they prefer.\n" +
            "4. When they choose by name, find the matching room_type_code and store it — never store the display name.\n" +
            "5. Then ask which rate plan they prefer; find and store the matching rate_plan_code.\n\n" +
            "If the list is empty, apologise and offer to try different dates.",
          onError:
            "I wasn't able to retrieve available rooms right now. Would you like to try different check-in or check-out dates?",
          timeout: 15,
          retryCount: 1,
        } as APIRequestConfig,
      } as APIRequestNodeData,
    },
    {
      id: "collect_room",
      type: "collect_slot",
      position: { x: 250, y: 750 },
      data: {
        name: "Room Type Selection",
        instructions:
          "Present the unique room types by name (from {{available_rooms}}). " +
          "The {{room_rates}} data contains the full name→code mapping: each item has room_type_name and room_type_code. " +
          "When the caller picks a room type by name, find the matching room_type_code in {{room_rates}} and store " +
          "THAT CODE as room_type_code — never store the display name.",
        slot: {
          variableKey: "room_type_code",
          prompt:
            "Which room type would you prefer? The available options are: {{available_rooms}}. " +
            "I will record the exact room type code for your selection.",
          type: "text",
          retryPrompt: "Could you repeat which room type you'd like?",
          maxRetries: 3,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "collect_rate",
      type: "collect_slot",
      position: { x: 250, y: 900 },
      data: {
        name: "Rate Plan Selection",
        instructions:
          "Present the unique rate plans by name (from {{rates}}). " +
          "The {{room_rates}} data contains the full name→code mapping: each item has rate_plan_name and rate_plan_code. " +
          "When the caller picks a rate plan by name, find the matching rate_plan_code in {{room_rates}} and store " +
          "THAT CODE as rate_plan_code — never store the display name.",
        slot: {
          variableKey: "rate_plan_code",
          prompt:
            "And which rate plan would you like? The available plans are: {{rates}}. " +
            "I will record the exact rate plan code for your selection.",
          type: "text",
          retryPrompt: "Could you repeat which rate plan you'd like?",
          maxRetries: 3,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "confirm_room_rate",
      type: "api_request",
      position: { x: 250, y: 1050 },
      data: {
        name: "Confirm Room Rate (GuestCentric)",
        instructions:
          "Re-checks availability filtered to the caller's selected room type and rate plan codes to capture the " +
          "exact room_rate_code, total_price, and included meal_plan_id needed to book. This should return a single " +
          "matching room + rate combination. Do not narrate this step to the caller — proceed silently.",
        api: {
          method: "GET",
          url: "",
          apiSource: "integration",
          integrationId: "",
          integrationSlug: "guestcentric-crs",
          endpointId: "hotel_rooms",
          endpointName: "Hotel Rooms & Rates",
          thinkingMessage: "",
          responseMapping: {
            room_rate_code: "$.room_rates[0].room_rate_code",
            total_price:    "$.room_rates[0].total_price",
            meal_plan_id:   "$.room_rates[0].meal_plan_prices.included.id",
          },
          autoMappingSource: {
            room_rate_code: "$.room_rates[0].room_rate_code",
            total_price:    "$.room_rates[0].total_price",
            meal_plan_id:   "$.room_rates[0].meal_plan_prices.included.id",
          },
          queryParamOverrides: {
            room_type_code: "{{room_type_code}}",
            rate_plan_code: "{{rate_plan_code}}",
          },
          responseInstructions:
            "Do not mention this lookup to the caller. If no matching room rate is returned, apologise and offer " +
            "to pick a different room type or rate plan.",
          onError:
            "I wasn't able to confirm that room and rate combination. Please choose a different room type or rate plan.",
          timeout: 15,
          retryCount: 1,
        } as APIRequestConfig,
      } as APIRequestNodeData,
    },
    {
      id: "build_hotels_array",
      type: "set_variable",
      position: { x: 250, y: 1200 },
      data: {
        name: "Build Hotels Array",
        setVariable: {
          variableKey: "hotels",
          valueType: "template",
          value: '["{{hotel_id}}"]',
        },
      } as SetVariableNodeData,
    },
    {
      id: "check_cancellation_policy",
      type: "api_request",
      position: { x: 250, y: 1350 },
      data: {
        name: "Get Cancellation Policy (GuestCentric)",
        instructions:
          "Looks up the property's cancellation policy ID required by the booking endpoint. Do not narrate this " +
          "step to the caller — proceed silently to collecting their contact details.",
        api: {
          method: "GET",
          url: "",
          apiSource: "integration",
          integrationId: "",
          integrationSlug: "guestcentric-crs",
          endpointId: "hotel_cancellation_policies",
          endpointName: "Cancellation Policies",
          thinkingMessage: "",
          responseMapping: {
            cancellation_policy_id: "$[0].id",
          },
          autoMappingSource: {
            cancellation_policy_id: "$[0].id",
          },
          responseInstructions: "Do not mention this lookup to the caller.",
          onError:
            "I had a technical issue retrieving the cancellation policy. I will proceed with the booking and note that the policy should be confirmed.",
          timeout: 15,
          retryCount: 1,
        } as APIRequestConfig,
      } as APIRequestNodeData,
    },
    {
      id: "collect_first_name",
      type: "collect_slot",
      position: { x: 250, y: 1500 },
      data: {
        name: "Guest First Name",
        slot: {
          variableKey: "guest_first_name",
          prompt: "May I have the guest's first name for the reservation?",
          type: "text",
          retryPrompt: "Could you spell the first name for me?",
          maxRetries: 3,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "collect_last_name",
      type: "collect_slot",
      position: { x: 250, y: 1650 },
      data: {
        name: "Guest Last Name",
        slot: {
          variableKey: "guest_last_name",
          prompt: "And the last name?",
          type: "text",
          retryPrompt: "Could you spell the last name for me?",
          maxRetries: 3,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "collect_email",
      type: "collect_slot",
      position: { x: 250, y: 1800 },
      data: {
        name: "Guest Email",
        slot: {
          variableKey: "guest_email",
          prompt: "What's the best email address for the booking confirmation?",
          type: "text",
          retryPrompt: "Could you repeat the email address?",
          maxRetries: 3,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "collect_phone",
      type: "collect_slot",
      position: { x: 250, y: 1950 },
      data: {
        name: "Guest Phone",
        slot: {
          variableKey: "guest_phone",
          prompt: "And a good contact phone number?",
          type: "text",
          retryPrompt: "Could you repeat the phone number?",
          maxRetries: 3,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "collect_guest_address",
      type: "collect_slot",
      position: { x: 250, y: 2100 },
      data: {
        name: "Guest Address",
        slot: {
          variableKey: "guest_address",
          prompt: "Could I get your mailing address for the reservation?",
          type: "text",
          retryPrompt: "Could you repeat your street address?",
          maxRetries: 3,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "collect_guest_city",
      type: "collect_slot",
      position: { x: 250, y: 2250 },
      data: {
        name: "Guest City",
        slot: {
          variableKey: "guest_city",
          prompt: "And what city is that in?",
          type: "text",
          retryPrompt: "Could you repeat the city?",
          maxRetries: 3,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "collect_guest_postal_code",
      type: "collect_slot",
      position: { x: 250, y: 2400 },
      data: {
        name: "Guest Postal Code",
        slot: {
          variableKey: "guest_postal_code",
          prompt: "What's the postal or zip code?",
          type: "text",
          retryPrompt: "Could you repeat the postal code?",
          maxRetries: 3,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "collect_guest_country",
      type: "collect_slot",
      position: { x: 250, y: 2550 },
      data: {
        name: "Guest Country",
        slot: {
          variableKey: "guest_country",
          prompt: "And lastly, what country are you writing from?",
          type: "text",
          retryPrompt: "Could you repeat your country?",
          maxRetries: 3,
        },
      } as CollectSlotNodeData,
    },
    {
      id: "confirm_details",
      type: "confirmation",
      position: { x: 250, y: 2700 },
      data: {
        name: "Confirm Booking Details",
        confirmation: {
          summaryTemplate:
            "Just to confirm: a {{room_type_code}} room on the {{rate_plan_code}} rate plan, total price " +
            "{{total_price}}, for {{adults}} adult(s), checking in {{checkin}} and checking out {{checkout}}, " +
            "under {{guest_first_name}} {{guest_last_name}}.",
          confirmPrompt: "Shall I go ahead and book this reservation with GuestCentric?",
          editPrompt: "No problem — what would you like to change?",
          variablesToConfirm: [
            "checkin",
            "checkout",
            "adults",
            "room_type_code",
            "rate_plan_code",
            "total_price",
            "guest_first_name",
            "guest_last_name",
          ],
          allowEdit: true,
          deliveryMode: "guided",
        },
      } as ConfirmationNodeData,
    },
    {
      id: "create_booking",
      type: "api_request",
      position: { x: 250, y: 2850 },
      data: {
        name: "Book Reservation (GuestCentric)",
        instructions:
          "Submits the reservation to GuestCentric. Guest contact/address details, the room rate, meal plan, and " +
          "cancellation policy are all collected or derived earlier in this flow. This request still requires " +
          "hotel_name and hotel_reservations_email — set these flow variables to match your property's " +
          "GuestCentric configuration before using this template in production. " +
          "After this node completes, read the confirmation code back to the caller clearly, spelling it out if needed.",
        api: {
          method: "POST",
          url: "",
          apiSource: "integration",
          integrationId: "",
          integrationSlug: "guestcentric-crs",
          endpointId: "book_reservation",
          endpointName: "Book Reservation",
          thinkingMessage: "Creating your reservation in GuestCentric now — just a moment.",
          responseMapping: {
            crs_reservation_code:   "$.reservations[0].crs_reservation_code",
            hotel_reservation_code: "$.reservations[0].hotel_reservation_code",
            booking_status:         "$.reservations[0].status",
          },
          autoMappingSource: {
            crs_reservation_code:   "$.reservations[0].crs_reservation_code",
            hotel_reservation_code: "$.reservations[0].hotel_reservation_code",
            booking_status:         "$.reservations[0].status",
          },
          responseInstructions:
            "Tell the caller their reservation is confirmed with GuestCentric and read out their confirmation code: " +
            "{{crs_reservation_code}}. Offer to repeat it if needed.",
          onError:
            "I'm sorry, there was a problem submitting your reservation. Could you confirm your details are correct and I will try once more?",
          timeout: 20,
          retryCount: 1,
        } as APIRequestConfig,
      } as APIRequestNodeData,
    },
    {
      id: "end_success",
      type: "end",
      position: { x: 250, y: 3000 },
      data: {
        name: "Booking Confirmed",
        closingMessage:
          "Your reservation is confirmed! Your confirmation code is {{crs_reservation_code}}. " +
          "We look forward to welcoming you. Is there anything else I can help you with?",
      } as EndNodeData,
    },
  ],
  edges: [
    { id: "e1",  source: "start_1",                    target: "collect_checkin"            },
    { id: "e2",  source: "collect_checkin",             target: "collect_checkout"           },
    { id: "e3",  source: "collect_checkout",            target: "collect_guests"             },
    { id: "e3b", source: "collect_guests",              target: "sync_number_of_adults"      },
    { id: "e4",  source: "sync_number_of_adults",       target: "check_availability"         },
    { id: "e5",  source: "check_availability",          target: "collect_room"               },
    { id: "e6",  source: "collect_room",                target: "collect_rate"               },
    { id: "e6b", source: "collect_rate",                target: "confirm_room_rate"          },
    { id: "e6c", source: "confirm_room_rate",           target: "build_hotels_array"         },
    { id: "e6d", source: "build_hotels_array",          target: "check_cancellation_policy"  },
    { id: "e7",  source: "check_cancellation_policy",   target: "collect_first_name"         },
    { id: "e8",  source: "collect_first_name",          target: "collect_last_name"          },
    { id: "e9",  source: "collect_last_name",           target: "collect_email"              },
    { id: "e10", source: "collect_email",               target: "collect_phone"              },
    { id: "e10b",source: "collect_phone",               target: "collect_guest_address"      },
    { id: "e10c",source: "collect_guest_address",       target: "collect_guest_city"         },
    { id: "e10d",source: "collect_guest_city",          target: "collect_guest_postal_code"  },
    { id: "e10e",source: "collect_guest_postal_code",   target: "collect_guest_country"       },
    { id: "e11", source: "collect_guest_country",       target: "confirm_details"            },
    { id: "e12", source: "confirm_details",             target: "create_booking"             },
    { id: "e13", source: "create_booking",              target: "end_success"                },
  ],
};

interface FlowTemplate {
  variables: FlowVariable[];
  nodes: unknown[];
  edges: unknown[];
}
const TEMPLATES: Record<string, FlowTemplate> = {
  "room-booking":         ROOM_BOOKING_TEMPLATE,
  "concierge":            CONCIERGE_TEMPLATE,
  "room-service":         ROOM_SERVICE_TEMPLATE,
  "opera-ohip-booking":   OPERA_OHIP_BOOKING_TEMPLATE,
  "guestcentric-booking": GUESTCENTRIC_CRS_BOOKING_TEMPLATE,
};

export const useFlowStore = create<FlowState>((set, get) => ({
  nodes: [],
  edges: [],
  variables: [],
  globalPrompt: "",
  selectedNode: null,
  activeNodeId: null,
  isDirty: false,
  isLoading: false,
  toolId: null,
  accountId: null,
  
  // Versioning state
  currentSource: "legacy",
  currentVersionNumber: 0,
  publishedVersionNumber: 0,
  hasDraft: false,
  hasPublished: false,
  versions: [],
  draftDescription: "",

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
          type: "deletable",
          animated: true,
          style: edgeStyle,
        },
        get().edges
      ),
      isDirty: true,
    });
  },

  selectNode: (node) => set({ selectedNode: node }),
  
  setActiveNodeId: (nodeId) => set({ activeNodeId: nodeId }),

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

  deleteEdge: (edgeId) => {
    set({
      edges: get().edges.filter((e) => e.id !== edgeId),
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

  setGlobalPrompt: (prompt: string) => {
    set({
      globalPrompt: prompt,
      isDirty: true,
    });
  },

  loadFlow: async (toolId: string, accountId: string, source?: "draft" | "published") => {
    set({ isLoading: true, toolId, accountId });
    try {
      const sourceParam = source ? `&source=${source}` : "";
      const response = await fetch(`/api/tools/${toolId}/flow?account_id=${accountId}${sourceParam}`, {
        headers: { ...getAuthHeaders() },
      });
      if (!response.ok) throw new Error("Failed to load flow");
      
      const data = await response.json();
      
      if (data.flow_config && data.flow_config.nodes) {
        const loadedEdges = (data.flow_config.edges || []).map((e: any) => ({
          ...e,
          type: "deletable",
          animated: true,
          style: { stroke: "#3b82f6", strokeWidth: 2 },
        }));
        
        set({
          nodes: data.flow_config.nodes.map((n: any) => ({
            id: n.id,
            type: n.type || "message",
            position: n.position || { x: 0, y: 0 },
            data: n.data || { name: n.id },
          })),
          edges: loadedEdges,
          variables: data.flow_config.variables || [],
          globalPrompt: data.flow_config.globalPrompt || data.flow_config.global_prompt || "",
          isDirty: false,
          currentSource: data.source || "legacy",
          currentVersionNumber: data.version_number || 0,
          publishedVersionNumber: data.published_version_number || 0,
          hasDraft: data.has_draft || false,
          hasPublished: data.has_published || false,
          draftDescription: data.description || "",
        });
      } else {
        set({
          nodes: [],
          edges: [],
          globalPrompt: "",
          variables: [],
          isDirty: false,
          currentSource: "legacy",
          currentVersionNumber: 0,
          publishedVersionNumber: 0,
          hasDraft: false,
          hasPublished: false,
        });
      }
      
      // Load version history
      get().loadVersions();
    } catch (error) {
      console.error("Failed to load flow:", error);
    } finally {
      set({ isLoading: false });
    }
  },

  saveFlow: async (description?: string) => {
    const { toolId, accountId, nodes, edges, variables, globalPrompt, draftDescription } = get();
    if (!toolId || !accountId) return;

    set({ isLoading: true });
    try {
      const initialNode = nodes.find((n) => n.type === "initial");
      
      const flowConfig = {
        initial_node: initialNode?.id || null,
        variables,
        globalPrompt,
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

      const response = await fetch(`/api/tools/${toolId}/flow/draft?account_id=${accountId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ 
          flow_config: flowConfig,
          description: description || draftDescription || undefined,
        }),
      });

      if (!response.ok) throw new Error("Failed to save flow");
      
      const result = await response.json();
      
      set({ 
        isDirty: false,
        currentSource: "draft",
        currentVersionNumber: result.version_number,
        hasDraft: true,
      });
      
      // Refresh versions list
      get().loadVersions();
    } catch (error) {
      console.error("Failed to save flow:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },
  
  publishFlow: async (description?: string) => {
    const { toolId, accountId } = get();
    if (!toolId || !accountId) return;
    
    set({ isLoading: true });
    try {
      const response = await fetch(`/api/tools/${toolId}/flow/publish?account_id=${accountId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ description }),
      });
      
      if (!response.ok) {
        const error = await response.json();
        if (error.detail && typeof error.detail === "object" && error.detail.errors) {
          throw new Error(`Flow validation failed: ${error.detail.errors.join(", ")}`);
        }
        throw new Error(error.detail || "Failed to publish flow");
      }
      
      const result = await response.json();
      
      set({
        currentSource: "published",
        currentVersionNumber: result.version_number,
        publishedVersionNumber: result.version_number,
        hasDraft: false,
        hasPublished: true,
      });
      
      // Refresh versions list
      get().loadVersions();
      
      return result;
    } catch (error) {
      console.error("Failed to publish flow:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },
  
  discardDraft: async () => {
    const { toolId, accountId } = get();
    if (!toolId || !accountId) return;
    
    set({ isLoading: true });
    try {
      const response = await fetch(`/api/tools/${toolId}/flow/draft?account_id=${accountId}`, {
        method: "DELETE",
        headers: { ...getAuthHeaders() },
      });
      
      if (!response.ok) throw new Error("Failed to discard draft");
      
      // Reload the published version
      await get().loadFlow(toolId, accountId, "published");
    } catch (error) {
      console.error("Failed to discard draft:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },
  
  loadVersions: async () => {
    const { toolId, accountId } = get();
    if (!toolId || !accountId) return;
    
    try {
      const response = await fetch(`/api/tools/${toolId}/flow/versions?account_id=${accountId}`, {
        headers: { ...getAuthHeaders() },
      });
      if (!response.ok) return;
      
      const data = await response.json();
      set({
        versions: data.versions || [],
        publishedVersionNumber: data.published_version_number || 0,
        hasDraft: data.has_draft || false,
      });
    } catch (error) {
      console.error("Failed to load versions:", error);
    }
  },
  
  revertToVersion: async (versionNumber: number, publishImmediately = false) => {
    const { toolId, accountId } = get();
    if (!toolId || !accountId) return;
    
    set({ isLoading: true });
    try {
      const response = await fetch(
        `/api/tools/${toolId}/flow/versions/${versionNumber}/revert?account_id=${accountId}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...getAuthHeaders() },
          body: JSON.stringify({ publish_immediately: publishImmediately }),
        }
      );
      
      if (!response.ok) throw new Error("Failed to revert to version");
      
      // Reload the flow
      await get().loadFlow(toolId, accountId);
    } catch (error) {
      console.error("Failed to revert to version:", error);
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },
  
  setDraftDescription: (description: string) => set({ draftDescription: description }),

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
  setHotelId: (id) => set({ accountId: id }),

  getFlowConfig: () => {
    const { nodes, edges, variables, globalPrompt } = get();
    const initialNode = nodes.find((n) => n.type === "initial");
    
    return {
      initial_node: initialNode?.id || null,
      variables,
      globalPrompt,
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
  { id: "room-booking",       name: "Room Booking",         description: "Complete room reservation flow with guest details collection" },
  { id: "concierge",          name: "Concierge Services",   description: "Help guests with dining, spa, and activity requests" },
  { id: "room-service",       name: "Room Service",         description: "Take food and beverage orders with special dietary requirements" },
  { id: "opera-ohip-booking", name: "Opera OHIP Booking",   description: "Check availability and create a reservation via Oracle Opera OHIP — includes two pre-wired integration API nodes", complexity: "medium" },
  { id: "guestcentric-booking", name: "GuestCentric CRS Booking", description: "Check hotel room availability and book a reservation via GuestCentric CRS — includes two pre-wired integration API nodes", complexity: "medium" },
];
