export interface MCPNativeFlowPolicy {
  configured: boolean;
  scope: "account" | "property" | null;
  property_id: string | null;
  enabled_tools: string[];
  read_only_tools: string[];
}

export type MCPGrantScope = "account" | "property";

export interface MCPGrantInput {
  scope: MCPGrantScope;
  propertyId: string;
  enabledTools: string[];
  readOnlyTools: string[];
}

export type MCPGrantBuildResult =
  | { ok: true; connectionConfig: Record<string, unknown> }
  | { ok: false; error: string };

export function buildMCPGrantConnectionConfig(input: MCPGrantInput): MCPGrantBuildResult {
  const enabledTools = Array.from(new Set(input.enabledTools.filter(Boolean)));
  const readOnlyTools = Array.from(new Set(input.readOnlyTools.filter(Boolean)));
  if (enabledTools.length === 0) {
    return { ok: false, error: "Select at least one discovered tool for native Flow access." };
  }
  if (readOnlyTools.some((tool) => !enabledTools.includes(tool))) {
    return { ok: false, error: "Read-only tools must also be enabled." };
  }
  if (input.scope === "property") {
    const propertyId = input.propertyId.trim();
    if (!propertyId) return { ok: false, error: "Enter the property ID for property-scoped access." };
    return {
      ok: true,
      connectionConfig: {
        property_id: propertyId,
        native_enabled_tools: enabledTools,
        native_read_only_tools: readOnlyTools,
      },
    };
  }
  return {
    ok: true,
    connectionConfig: {
      account_global: true,
      native_enabled_tools: enabledTools,
      native_read_only_tools: readOnlyTools,
    },
  };
}

export function nativeFlowToolAccess(
  policy: MCPNativeFlowPolicy | null | undefined,
  toolName: string,
): "write" | "read_only" | "unavailable" {
  if (!policy?.configured || !toolName || !policy.enabled_tools.includes(toolName)) {
    return "unavailable";
  }
  return policy.read_only_tools.includes(toolName) ? "read_only" : "write";
}

export function displayMCPServerHost(serverUrl: string): string {
  try {
    return new URL(serverUrl).host || "Endpoint saved";
  } catch {
    return "Endpoint saved";
  }
}
