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
  native_dev_disabled: "Native development is not enabled for this workspace. Ask an administrator about development access.",
  native_dev_selection: "The selected tool or assistant is not eligible for native development. Link a primary assistant in Tool settings and reload, or use Legacy.",
  native_dev_resources: "The assistant's configured resources or tool scope could not be admitted for native development. Review its setup and access policy.",
  native_dev_ownership: "This assistant is not available for native testing in the current workspace. Select an authorized assistant or use Legacy.",
  native_dev_published_version: "Native development requires the current published version. Reload the flow before trying again.",
  native_simulation_published_source_required: "Native development requires a published flow. Publish a validated version before testing.",
  native_simulation_version_required: "The current published version could not be identified. Reload the flow before starting a native test.",
  native_simulation_version_changed: "The selected published version is no longer current. Reload the flow before starting a native test.",
  native_simulation_provider_unsupported: "The configured model provider cannot be constructed in this native development environment. No provider fallback was attempted.",
  native_simulation_model_configuration: "The configured model settings are not supported by this native development environment. Review the assistant configuration.",
  native_simulation_model_unconfigured: "No usable model is configured for native development. Ask an administrator to configure one.",
  native_simulation_flow_unsupported: "The server could not admit this published flow for native development. Review the safe diagnostic, correct the configuration, save, publish, and retry.",
  native_simulation_start_failed: "Native development could not start this session. Review the published flow and account configuration, then try again.",
  native_simulation_failed: "Native development could not complete this request. Review the published flow and try again.",
  native_simulation_invalid_input: "That message could not be used in this development test. Try a shorter, plain-text message.",
  native_simulation_manual_calls_disabled: "Manual calls are not available in this text simulation. Continue with the development text test.",
  native_simulation_not_found: "This simulation session is no longer available. Reset the test and start again.",
  native_simulation_closed: "This simulation has ended. Reset the test to start a new session.",
  native_simulation_busy: "The native simulation is still processing. Wait a moment before sending another message.",
  native_simulation_turn_limit: "This native development test reached its turn limit. Reset the test to continue.",
  native_simulation_rate_limit: "Native development is receiving too many requests. Wait briefly and try again.",
  native_simulation_start_rate: "Too many native development tests were started recently. Wait briefly.",
  native_simulation_owner_limit: "This workspace has reached its native development test limit. Close another test.",
  native_simulation_capacity: "Native development is at capacity. Try again later.",
  native_simulation_output_limit: "The response exceeded the native development size limit. Try a shorter message.",
  native_simulation_expired: "This simulation session expired. Reset the test to start again.",
  native_simulation_disabled: "Native development is temporarily unavailable. Try again later.",
  native_simulation_shutdown: "Native development is temporarily restarting. Try again later.",
  native_simulation_timeout: "Native development took too long to respond. Try again.",
};

const NATIVE_ERROR_STRINGS: Record<string, string> = {
  "Native pilot requires a published flow": NATIVE_ERROR_MESSAGES.native_simulation_published_source_required,
  "Native pilot requires a current published version": NATIVE_ERROR_MESSAGES.native_simulation_version_changed,
  "Native pilot requires an assistant": "Link a primary assistant in Tool settings and reload before starting a native development test.",
};

const FLOW_DIAGNOSTIC_MESSAGES: Record<string, string> = {
  global_instructions: NATIVE_ERROR_MESSAGES.native_simulation_flow_unsupported,
  initial: NATIVE_ERROR_MESSAGES.native_simulation_flow_unsupported,
  node_types: NATIVE_ERROR_MESSAGES.native_simulation_flow_unsupported,
  slot: NATIVE_ERROR_MESSAGES.native_simulation_flow_unsupported,
  variables: NATIVE_ERROR_MESSAGES.native_simulation_flow_unsupported,
  connected_get: NATIVE_ERROR_MESSAGES.native_simulation_flow_unsupported,
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
       return NATIVE_ERROR_MESSAGES.native_simulation_flow_unsupported;
    }
    const message = ownMessage(NATIVE_ERROR_MESSAGES, code);
    if (message) return message;
  }
      return "The simulation could not start or continue. Check the published flow and try again.";
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
