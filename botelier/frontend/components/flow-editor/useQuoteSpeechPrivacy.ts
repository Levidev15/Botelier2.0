"use client";

import { useMemo } from "react";
import { useFlowStore } from "./store";
import {
  findQuoteSpeechProtections,
  hasQuotePrivateSpeech,
} from "./flowEditorData";

export function useQuoteSpeechPrivacy(targetNodeId?: string) {
  const nodes = useFlowStore((state) => state.nodes);
  const edges = useFlowStore((state) => state.edges);
  const protections = useMemo(
    () => findQuoteSpeechProtections(nodes, edges, targetNodeId),
    [nodes, edges, targetNodeId],
  );
  const protectedVariables = useMemo(
    () => Array.from(new Set([
      ...protections.privateVariables,
      ...protections.fingerprintVariables,
      ...protections.rawQuoteVariables,
    ])),
    [protections],
  );

  return {
    protections,
    protectedVariables,
    hasUnsafeText: (value: string | undefined) =>
      !!value && hasQuotePrivateSpeech(value, protections),
    safeVariables: <T extends { key: string }>(variables: T[]) =>
      variables.filter((variable) => !protectedVariables.includes(variable.key)),
  };
}
