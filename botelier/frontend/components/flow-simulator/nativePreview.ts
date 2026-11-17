/** Operator samples resume one server-owned SDK action; they are never user turns. */
export interface PendingNativePreview {
  request_id: string;
  node_id: string;
  source_kind: "http" | "integration" | "tool" | "mcp" | "mcp_read" | "record" | "transfer";
  expires_in_seconds: number;
}

export type NativePreviewOutcome = "auto" | "success" | "error";
export interface NativePreviewInput {
  requestId: string;
  dataJson: string;
  statusCode: number;
  outcome: NativePreviewOutcome;
}
export interface NativePreviewOwnership {
  requestId: string;
  sessionId: string;
  sourceKey: string;
  generation: number;
  inFlightToken: number;
}

export function isNativePreviewCurrent(
  owner: NativePreviewOwnership,
  current: NativePreviewOwnership,
): boolean {
  return owner.requestId === current.requestId &&
    owner.sessionId === current.sessionId &&
    owner.sourceKey === current.sourceKey &&
    owner.generation === current.generation &&
    owner.inFlightToken === current.inFlightToken;
}

export const MAX_NATIVE_PREVIEW_JSON_BYTES = 65_536;
const SAFE_ID = /^[A-Za-z0-9_-]{1,128}$/;
const SOURCE_KINDS = ["http", "integration", "tool", "mcp", "mcp_read", "record", "transfer"];

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

export function hasNativePendingPreview(state: unknown): boolean {
  return record(state) && state.pending_preview !== undefined && state.pending_preview !== null;
}

export function getNativePendingPreview(state: unknown): PendingNativePreview | null {
  if (!record(state) || !record(state.pending_preview)) return null;
  const value = state.pending_preview;
  if (typeof value.request_id !== "string" || !SAFE_ID.test(value.request_id) ||
      typeof value.node_id !== "string" || !SAFE_ID.test(value.node_id) ||
      typeof value.source_kind !== "string" || !SOURCE_KINDS.includes(value.source_kind) ||
      typeof value.expires_in_seconds !== "number" ||
      !Number.isFinite(value.expires_in_seconds) ||
      value.expires_in_seconds < 0 || value.expires_in_seconds > 600) return null;
  // Never reflect prepared request headers, bodies, credentials or arbitrary metadata.
  return {
    request_id: value.request_id,
    node_id: value.node_id,
    source_kind: value.source_kind as PendingNativePreview["source_kind"],
    expires_in_seconds: value.expires_in_seconds,
  };
}

function wellFormed(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const point = value.charCodeAt(index);
    if (point >= 0xD800 && point <= 0xDBFF) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xDC00 && next <= 0xDFFF)) return false;
      index += 1;
    } else if (point >= 0xDC00 && point <= 0xDFFF) return false;
  }
  return true;
}

function finiteJson(value: unknown): boolean {
  const stack: Array<{ value: unknown; depth: number }> = [{ value, depth: 0 }];
  while (stack.length) {
    const item = stack.pop()!;
    if (item.depth > 64) return false;
    if (typeof item.value === "number" && !Number.isFinite(item.value)) return false;
    if (typeof item.value === "string" && !wellFormed(item.value)) return false;
    if (Array.isArray(item.value)) {
      for (const child of item.value) stack.push({ value: child, depth: item.depth + 1 });
    } else if (record(item.value)) {
      for (const [key, child] of Object.entries(item.value)) {
        if (!wellFormed(key)) return false;
        stack.push({ value: child, depth: item.depth + 1 });
      }
    }
  }
  return true;
}

export function buildNativePreviewMessage({
  sessionId, pending, dataJson, statusCode, outcome = "auto",
}: {
  sessionId: string;
  pending: PendingNativePreview;
  dataJson: string;
  statusCode: number;
  outcome?: NativePreviewOutcome;
}) {
  const current = getNativePendingPreview({ pending_preview: pending });
  if (typeof sessionId !== "string" || !SAFE_ID.test(sessionId) ||
      !current || current.expires_in_seconds <= 0) {
    throw new Error("This sample no longer has a waiting action. Reset the test and try again.");
  }
  if (!Number.isInteger(statusCode) || (statusCode !== 0 && (statusCode < 200 || statusCode > 599))) {
    throw new Error("Use an HTTP status from 200 to 599, or 0 for a network failure.");
  }
  if (!["auto", "success", "error"].includes(outcome) ||
      (outcome === "success" && (statusCode < 200 || statusCode >= 300)) ||
      (outcome === "error" && statusCode >= 200 && statusCode < 300)) {
    throw new Error("Sample outcome must agree with its HTTP status.");
  }
  if (typeof dataJson !== "string" || !dataJson.trim() ||
      new TextEncoder().encode(dataJson).byteLength > MAX_NATIVE_PREVIEW_JSON_BYTES) {
    throw new Error("Enter sample JSON no larger than 64 KiB.");
  }
  try {
    if (!finiteJson(JSON.parse(dataJson))) throw new Error("invalid");
  } catch {
    throw new Error("Use valid, finite JSON with at most 64 nested levels.");
  }
  return {
    session_id: sessionId,
    message: "",
    preview_result: {
      request_id: current.request_id,
      status_code: statusCode,
      // Keep the source text: parsing/restringifying in JS can round 64-bit IDs.
      data_json: dataJson,
      ...(outcome === "auto" ? {} : { success: outcome === "success" }),
    },
  };
}

const EFFECT_LABELS: Record<string, string> = {
  send_sms: "SMS simulated — not sent",
  send_email: "Email simulated — not sent",
  record_create: "Record creation simulated — not saved",
  record_update: "Record update simulated — not saved",
  transfer: "Transfer simulated — no call was moved",
  mcp_read: "MCP read used supplied sample data",
};

export function nativePreviewEffectMessages(value: unknown): Array<{ node_id: string; label: string }> {
  if (!Array.isArray(value)) return [];
  return value.slice(-16).flatMap((effect) => {
    if (!record(effect) || effect.simulated !== true ||
        typeof effect.node_id !== "string" || !SAFE_ID.test(effect.node_id) ||
        typeof effect.kind !== "string" ||
        !Object.prototype.hasOwnProperty.call(EFFECT_LABELS, effect.kind)) return [];
    return [{ node_id: effect.node_id, label: EFFECT_LABELS[effect.kind] }];
  });
}
