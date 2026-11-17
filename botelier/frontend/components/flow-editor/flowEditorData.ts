import type { Edge, Node } from "@xyflow/react";
import type { APIRequestConfig, FlowVariable, NodeData } from "./store";

function nodeApi(node: Node<NodeData>): APIRequestConfig | undefined {
  return (node.data as NodeData & { api?: APIRequestConfig }).api;
}
export interface FlowOutputVariable extends FlowVariable {
  origin: "declared" | "mapped";
}

/**
 * Return persisted declarations plus response outputs authored elsewhere in the
 * graph. Mapped outputs intentionally remain text-compatible metadata: the
 * backend preserves their exact JSON value, which can be an array or object.
 */
export function collectFlowVariables(
  variables: FlowVariable[],
  nodes: Node<NodeData>[],
): FlowOutputVariable[] {
  const outputKeys = new Set<string>();
  for (const node of nodes) {
    if (node.type !== "api_request" && node.type !== "capability") continue;
    const api = node.data?.api as {
      responseMapping?: Record<string, string>;
      responseVariables?: Array<{ variableKey?: string }>;
    } | undefined;
    Object.keys(api?.responseMapping ?? {}).forEach((key) => key && outputKeys.add(key));
    (api?.responseVariables ?? []).forEach((item) => {
      if (item?.variableKey) outputKeys.add(item.variableKey);
    });
  }

  const declared = variables.filter((variable) => !!variable.key);
  const declaredKeys = new Set(declared.map((variable) => variable.key));
  return [
    ...declared.map((variable) => ({ ...variable, origin: "declared" as const })),
    ...Array.from(outputKeys)
      .filter((key) => !declaredKeys.has(key))
      .sort()
      .map((key) => ({
        key,
        type: "text" as const,
        description: "Mapped output · raw JSON preserved (may be an array or object)",
        required: false,
        origin: "mapped" as const,
      })),
  ];
}

export interface DuplicatedFlowSelection {
  nodes: Node<NodeData>[];
  edges: Edge[];
  remappedReferences: string[];
  clearedReferences: string[];
}

/**
 * Clone selected nodes and their internal edges. Typed node references are
 * remapped only when both endpoints are in the copied selection; external
 * references are cleared rather than silently targeting the original node.
 */
export function duplicateFlowSelection(
  selectedNodes: Node<NodeData>[],
  edges: Edge[],
  createId: (kind: "node" | "edge") => string,
  offset = { x: 48, y: 48 },
): DuplicatedFlowSelection {
  if (!selectedNodes.length) return { nodes: [], edges: [], remappedReferences: [], clearedReferences: [] };

  const nodeIds = new Set(selectedNodes.map((node) => node.id));
  const idMap = new Map<string, string>();
  selectedNodes.forEach((node) => idMap.set(node.id, createId("node")));

  const remappedReferences: string[] = [];
  const clearedReferences: string[] = [];
  const nodes = selectedNodes.map((node) => {
    const copy = JSON.parse(JSON.stringify(node)) as Node<NodeData>;
    copy.id = idMap.get(node.id)!;
    copy.position = { x: node.position.x + offset.x, y: node.position.y + offset.y };
    copy.selected = true;
    if (copy.type === "save_record") {
      const config = copy.data.saveRecord as { updateSourceNodeId?: string } | undefined;
      if (config?.updateSourceNodeId) {
        if (nodeIds.has(config.updateSourceNodeId)) {
          config.updateSourceNodeId = idMap.get(config.updateSourceNodeId)!;
          remappedReferences.push(copy.id);
        } else {
          delete config.updateSourceNodeId;
          remappedReferences.push(copy.id);
          clearedReferences.push(copy.id);
        }
      }
    }
    const copyApi = (copy.data as NodeData & { api?: APIRequestConfig }).api;
    const quoteDelivery = copyApi?.quoteDelivery;
    if (quoteDelivery?.quoteNodeId) {
      if (nodeIds.has(quoteDelivery.quoteNodeId)) {
        quoteDelivery.quoteNodeId = idMap.get(quoteDelivery.quoteNodeId)!;
        remappedReferences.push(copy.id);
      } else {
        if (copyApi) delete copyApi.quoteDelivery;
        if (copyApi) copyApi.argumentsTemplate = "";
        remappedReferences.push(copy.id);
        clearedReferences.push(copy.id);
      }
    }
    return copy;
  });

  const copiedEdges = edges
    .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    .map((edge) => ({
      ...JSON.parse(JSON.stringify(edge)),
      id: createId("edge"),
      source: idMap.get(edge.source)!,
      target: idMap.get(edge.target)!,
      selected: false,
    }));

  return { nodes, edges: copiedEdges, remappedReferences, clearedReferences };
}

export function findCompatibleRecordSources(
  nodes: Node<NodeData>[],
  edges: Edge[],
  targetNodeId: string,
  recordTypeId: string,
): Node<NodeData>[] {
  const target = nodes.find((node) => node.id === targetNodeId);
  if (!target || target.type !== "save_record" || !recordTypeId) return [];
  const targetData = target.data.saveRecord as { recordTypeId?: string } | undefined;
  if (targetData?.recordTypeId !== recordTypeId) return [];
  const outgoing = new Map<string, string[]>();
  for (const edge of edges) {
    const next = outgoing.get(edge.source) ?? [];
    next.push(edge.target);
    outgoing.set(edge.source, next);
  }

  return nodes.filter((node) => {
    if (node.id === targetNodeId || node.type !== "save_record") return false;
    const config = node.data.saveRecord as {
      recordTypeId?: string;
      updateSourceNodeId?: string;
    } | undefined;
    if (config?.recordTypeId !== recordTypeId || config.updateSourceNodeId) return false;
    const visited = new Set<string>();
    const pending = [node.id];
    while (pending.length) {
      const current = pending.pop()!;
      if (current === targetNodeId) return true;
      if (visited.has(current)) continue;
      visited.add(current);
      pending.push(...(outgoing.get(current) ?? []));
    }
    return false;
  });
}

export interface QuoteConfirmationContext {
  validators: Array<{ id: string; label: string }>;
  publicVariables: string[];
  fingerprintVariables: string[];
  recipientVariables: string[];
  privateVariables: string[];
  rawQuoteVariables: string[];
}

export interface QuoteSpeechProtections {
  privateVariables: string[];
  fingerprintVariables: string[];
  rawQuoteVariables: string[];
}

export function findQuoteSpeechProtections(
  nodes: Node<NodeData>[],
  edges: Edge[],
  targetNodeId?: string,
): QuoteSpeechProtections {
  const validators = nodes.filter((node) =>
    (node.type === "api_request" || node.type === "capability") &&
    nodeApi(node)?.apiSource === "capability" &&
    nodeApi(node)?.capability === "validate_reservation_quote" &&
    (!targetNodeId || canReachNode(edges, node.id, targetNodeId)),
  );
  const privateVariables = new Set<string>();
  const fingerprintVariables = new Set<string>();
  const rawQuoteVariables = new Set<string>();
  for (const validator of validators) {
    const api = nodeApi(validator)!;
    if (api.quotePolicy?.privateUrlVariable) privateVariables.add(api.quotePolicy.privateUrlVariable);
    if (api.quotePolicy?.fingerprintVariable) fingerprintVariables.add(api.quotePolicy.fingerprintVariable);
    const rawQuoteVariable = api.argumentsTemplate?.match(
      /"quote"\s*:\s*\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/,
    )?.[1];
    if (rawQuoteVariable) rawQuoteVariables.add(rawQuoteVariable);
  }
  return {
    privateVariables: Array.from(privateVariables),
    fingerprintVariables: Array.from(fingerprintVariables),
    rawQuoteVariables: Array.from(rawQuoteVariables),
  };
}

export function hasQuotePrivateSpeech(
  value: string,
  protections: QuoteSpeechProtections,
): boolean {
  const protectedVariables = [
    ...protections.privateVariables,
    ...protections.fingerprintVariables,
    ...protections.rawQuoteVariables,
  ];
  const escapeRegExp = (key: string) => key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return protectedVariables.some((key) =>
    !!key && new RegExp(`\\{\\{\\s*${escapeRegExp(key)}(?:\\s*\\.|\\s*\\}\\})`).test(value),
  ) ||
    (protectedVariables.length > 0 && /https?:\/\/\S+/i.test(value));
}

function canReachNode(edges: Edge[], from: string, to: string): boolean {
  const pending = [from];
  const visited = new Set<string>();
  while (pending.length) {
    const current = pending.pop()!;
    if (current === to) return true;
    if (visited.has(current)) continue;
    visited.add(current);
    edges.filter((edge) => edge.source === current).forEach((edge) => pending.push(edge.target));
  }
  return false;
}

export function findQuoteConfirmationContext(
  nodes: Node<NodeData>[],
  edges: Edge[],
  confirmationNodeId: string,
): QuoteConfirmationContext {
  const validators = nodes.filter((node) =>
    (node.type === "api_request" || node.type === "capability") &&
    nodeApi(node)?.apiSource === "capability" &&
    nodeApi(node)?.capability === "validate_reservation_quote" &&
    canReachNode(edges, node.id, confirmationNodeId),
  );
  const publicVariables = new Set<string>();
  const fingerprintVariables = new Set<string>();
  const recipientVariables = new Set<string>();
  const privateVariables = new Set<string>();
  const rawQuoteVariables = new Set<string>();

  for (const validator of validators) {
    const api = nodeApi(validator)!;
    const policy = api.quotePolicy;
    Object.values(policy?.publicConfirmationFields ?? {}).forEach((key) => key && publicVariables.add(key));
    if (policy?.fingerprintVariable) fingerprintVariables.add(policy.fingerprintVariable);
    if (policy?.privateUrlVariable) privateVariables.add(policy.privateUrlVariable);
    const rawQuoteVariable = api.argumentsTemplate?.match(
      /"quote"\s*:\s*\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/,
    )?.[1];
    if (rawQuoteVariable) rawQuoteVariables.add(rawQuoteVariable);

    for (const delivery of nodes) {
      const quoteDelivery = nodeApi(delivery)?.quoteDelivery;
      if (
        quoteDelivery?.quoteNodeId === validator.id &&
        canReachNode(edges, confirmationNodeId, delivery.id)
      ) recipientVariables.add(quoteDelivery.recipientVariable);
    }
  }

  return {
    validators: validators.map((node) => ({ id: node.id, label: node.data.name || "Reservation quote" })),
    publicVariables: Array.from(publicVariables),
    fingerprintVariables: Array.from(fingerprintVariables),
    recipientVariables: Array.from(recipientVariables),
    privateVariables: Array.from(privateVariables),
    rawQuoteVariables: Array.from(rawQuoteVariables),
  };
}
