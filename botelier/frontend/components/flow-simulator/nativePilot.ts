export type SimulationEngine = "legacy" | "native";

export interface NativePilotSnapshot {
  assistantId?: string;
  isDirty: boolean;
  currentSource: string;
  currentVersionNumber: number;
  publishedVersionNumber: number;
  currentVersionId: string | null;
}

export interface SimulationState {
  collected_slots: Record<string, unknown>;
  current_node: string | null;
  pending_slot: string | null;
  is_complete: boolean;
  is_ended: boolean;
  progress: { collected: number; total: number; percentage: number };
}

export interface SimulationVariable {
  key: string;
  type: string;
  description: string;
  required: boolean;
  choices?: string[];
}

export interface SimulationResponse {
  session_id?: string;
  messages?: Array<{ role: "user" | "assistant" | "system"; content: string }>;
  state?: SimulationState;
  variables_to_collect?: SimulationVariable[];
  runtime?: Record<string, unknown>;
}

const NATIVE_ERROR_MESSAGES: Record<string, string> = {
  native_assistant_required: "Link a primary assistant in Tool settings and reload before starting a native development test.",
  native_published_flow_required: "Native development requires a published flow. Publish a validated version before testing.",
  native_version_mismatch: "The selected published version is no longer current. Reload the flow before starting a native test.",
  native_dev_disabled: "Native development is not enabled for this workspace. Use Legacy or ask an administrator about pilot access.",
  native_dev_selection: "The selected tool or assistant is not eligible for native development. Link a primary assistant in Tool settings and reload, or use Legacy.",
  native_dev_resources: "The selected assistant is missing a resource required by the pilot. Review its setup or use Legacy.",
  native_dev_ownership: "This assistant is not available for native testing in the current workspace. Select an authorized assistant or use Legacy.",
  native_dev_published_version: "Native development requires the current published version. Reload the flow before trying again.",
  native_simulation_published_source_required: "Native development requires a published flow. Publish a validated version before testing.",
  native_simulation_version_required: "The current published version could not be identified. Reload the flow before starting a native test.",
  native_simulation_version_changed: "The selected published version is no longer current. Reload the flow before starting a native test.",
  native_simulation_provider_unsupported: "The assistant's configured model provider is outside the native pilot. Use Legacy or select a supported configuration.",
  native_simulation_model_configuration: "The assistant's model configuration is not supported by the native pilot. Review the configuration or use Legacy.",
  native_simulation_model_unconfigured: "The assistant has no supported model configured for the native pilot. Ask an administrator to configure one or use Legacy.",
  native_simulation_flow_unsupported: "This flow is outside the native pilot's exactly six-node, read-only shape. Use Legacy or test a supported published flow.",
  native_simulation_start_failed: "The native pilot could not start this session. Try again or use Legacy.",
  native_simulation_failed: "The native pilot could not complete this request. Review the published flow or use Legacy.",
  native_simulation_invalid_input: "That message could not be used by the native pilot. Try a shorter, plain-text message.",
  native_simulation_manual_calls_disabled: "Manual calls are not available in this native test. Continue with a text simulation or use Legacy.",
  native_simulation_not_found: "This simulation session is no longer available. Reset the test and start again.",
  native_simulation_closed: "This simulation has ended. Reset the test to start a new session.",
  native_simulation_busy: "The native simulation is still processing. Wait a moment before sending another message.",
  native_simulation_turn_limit: "This native test reached its turn limit. Reset the test or use Legacy.",
  native_simulation_rate_limit: "The native pilot is receiving too many requests. Wait briefly and try again.",
  native_simulation_start_rate: "Too many native tests were started recently. Wait briefly or use Legacy.",
  native_simulation_owner_limit: "This workspace has reached its native test limit. Close another test or use Legacy.",
  native_simulation_capacity: "The native pilot is at capacity. Try again later or use Legacy.",
  native_simulation_output_limit: "The response exceeded the native pilot's size limit. Try a shorter message.",
  native_simulation_expired: "This simulation session expired. Reset the test to start again.",
  native_simulation_disabled: "Native development is temporarily unavailable. Use Legacy or try again later.",
  native_simulation_shutdown: "The native pilot is temporarily restarting. Try again later or use Legacy.",
  native_simulation_timeout: "The native pilot took too long to respond. Try again or use Legacy.",
};

const NATIVE_ERROR_STRINGS: Record<string, string> = {
  "Native pilot requires a published flow": NATIVE_ERROR_MESSAGES.native_simulation_published_source_required,
  "Native pilot requires a current published version": NATIVE_ERROR_MESSAGES.native_simulation_version_changed,
  "Native pilot supports only the bounded six-node subset": "The flow is outside the native pilot's exactly six-node, read-only shape. Use Legacy or test a supported published flow.",
  "Native pilot requires an assistant": "Link a primary assistant in Tool settings and reload before starting a native development test.",
};

const FLOW_DIAGNOSTIC_MESSAGES: Record<string, string> = {
  global_instructions: "This flow uses global instructions that the native pilot does not support. Use Legacy or simplify the flow's global instructions.",
  initial: "The initial node uses instructions outside the native pilot. Use Legacy or simplify the initial node for the bounded test.",
  node_types: "This flow includes node types outside the native pilot's exactly six-node, read-only shape. Use Legacy or test a supported published flow.",
  slot: "This flow's slot constraints are outside the native pilot. Use Legacy or simplify the slot requirements for the bounded test.",
  variables: "This flow's variable constraints are outside the native pilot. Use Legacy or simplify the variables for the bounded test.",
  connected_get: "This flow uses a connected GET/API action outside the native pilot. Use Legacy or test a supported published flow.",
};

function nativeEligibilityError(snapshot?: NativePilotSnapshot): string | null {
  if (!snapshot?.assistantId?.trim()) return NATIVE_ERROR_MESSAGES.native_assistant_required;
  if (snapshot.isDirty) return "Save or discard unsaved changes before starting a native development test.";
  if (snapshot.currentSource !== "published") return NATIVE_ERROR_MESSAGES.native_published_flow_required;
  if (!Number.isInteger(snapshot.currentVersionNumber) || snapshot.currentVersionNumber <= 0 ||
      snapshot.currentVersionNumber !== snapshot.publishedVersionNumber ||
      typeof snapshot.currentVersionId !== "string" || snapshot.currentVersionId.trim() === "") {
    return NATIVE_ERROR_MESSAGES.native_version_mismatch;
  }
  return null;
}

export function buildSimulationStartPayload({
  toolId,
  engine = "legacy",
  snapshot,
}: {
  toolId: string;
  engine?: SimulationEngine;
  snapshot?: NativePilotSnapshot;
}): Record<string, unknown> {
  if (engine === "legacy") return { tool_id: toolId };
  const error = nativeEligibilityError(snapshot);
  if (error) throw new Error(error);
  return {
    tool_id: toolId,
    assistant_id: snapshot!.assistantId,
    engine: "native_pilot",
    source: "published",
    source_version: snapshot!.currentVersionNumber,
  };
}

export function verifyNativeRuntime(
  runtime: Record<string, unknown> | undefined,
  toolId: string,
  snapshot: NativePilotSnapshot,
): boolean {
  return !!runtime &&
    runtime.engine === "native_pilot" &&
    runtime.source === "published" &&
    runtime.tool_id === toolId &&
    runtime.assistant_id === snapshot.assistantId &&
    runtime.version_number === snapshot.currentVersionNumber &&
    runtime.flow_version_id === snapshot.currentVersionId;
}

function ownMessage(messages: Record<string, string>, key: unknown): string | undefined {
  return typeof key === "string" && Object.prototype.hasOwnProperty.call(messages, key)
    ? messages[key]
    : undefined;
}

export function formatNativeError(detail: unknown): string {
  if (typeof detail === "string") {
    const message = ownMessage(NATIVE_ERROR_STRINGS, detail) || ownMessage(NATIVE_ERROR_MESSAGES, detail);
    if (message) return message;
  }
  if (detail && typeof detail === "object") {
    const { code, diagnostic } = detail as { code?: unknown; diagnostic?: unknown };
    if (code === "native_simulation_flow_unsupported") {
      const message = ownMessage(FLOW_DIAGNOSTIC_MESSAGES, diagnostic);
      if (message) return message;
      return "This flow is outside the native pilot's exactly six-node, read-only shape. Use Legacy or test a supported published flow.";
    }
    const message = ownMessage(NATIVE_ERROR_MESSAGES, code);
    if (message) return message;
  }
  return "The simulation could not start or continue. Check the published flow and try again, or use Legacy.";
}

async function responseDetail(response: Response): Promise<unknown> {
  try {
    const body = await response.json();
    return body?.detail ?? body?.error;
  } catch {
    return undefined;
  }
}

function isValidSessionId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(value);
}

export async function requestSimulationStart({
  authFetch,
  toolId,
  engine = "legacy",
  snapshot,
}: {
  authFetch: (url: string, options: RequestInit) => Promise<Response>;
  toolId: string;
  engine?: SimulationEngine;
  snapshot?: NativePilotSnapshot;
}): Promise<{ ok: true; data: SimulationResponse } | { ok: false; error: string; session: null }> {
  const payload = buildSimulationStartPayload({ toolId, engine, snapshot });
  const response = await authFetch("/api/simulate/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await responseDetail(response);
    throw new Error(engine === "native" ? formatNativeError(detail) : "Failed to start simulation. Try again.");
  }

  let data: SimulationResponse;
  try {
    data = await response.json();
  } catch {
    throw new Error("The simulation returned an invalid response. Try again.");
  }
  if (!isValidSessionId(data.session_id)) {
    throw new Error("The simulation returned an invalid response. Try again.");
  }

  if (engine === "native" && !verifyNativeRuntime(data.runtime, toolId, snapshot!)) {
    try {
      await authFetch(`/api/simulate/session/${encodeURIComponent(data.session_id)}`, { method: "DELETE" });
    } catch {
      // Refuse the unverified session even if best-effort cleanup fails.
    }
    return {
      ok: false,
      error: "Native runtime evidence did not match the selected published flow. The session was refused; reload the flow before trying again.",
      session: null,
    };
  }
  return { ok: true, data };
}

export async function deleteSimulationSession(
  authFetch: (url: string, options: RequestInit) => Promise<Response>,
  sessionId: string | null,
): Promise<void> {
  if (!isValidSessionId(sessionId)) return;
  await authFetch(`/api/simulate/session/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
}
