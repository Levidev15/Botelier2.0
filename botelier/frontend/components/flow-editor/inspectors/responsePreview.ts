import type { APIRequestConfig, FlowVariable } from "../store";

export interface ResponsePreviewResult {
  mapped_variables: Record<string, unknown>;
  llm_data: Record<string, unknown>;
}

export function buildResponsePreviewPayload(
  sample: unknown,
  configuration: Pick<APIRequestConfig, "responseMapping" | "responseVariables" | "responseProjection">,
  variableDeclarations: FlowVariable[],
) {
  return {
    sample,
    configuration: {
      responseMapping: configuration.responseMapping ?? {},
      responseVariables: configuration.responseVariables ?? [],
      responseProjection: configuration.responseProjection ?? { fields: [] },
    },
    variableDeclarations,
  };
}

export async function previewMappedResponse({
  authFetch,
  toolId,
  accountId,
  sample,
  configuration,
  variableDeclarations,
}: {
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
  toolId: string;
  accountId: string;
  sample: unknown;
  configuration: Pick<APIRequestConfig, "responseMapping" | "responseVariables" | "responseProjection">;
  variableDeclarations: FlowVariable[];
}): Promise<ResponsePreviewResult> {
  const response = await authFetch(
    `/api/tools/${encodeURIComponent(toolId)}/flow/preview-response?account_id=${encodeURIComponent(accountId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildResponsePreviewPayload(sample, configuration, variableDeclarations)),
    },
  );
  const result = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = result?.detail;
    const code = typeof detail === "object" && detail ? detail.code : detail;
    throw new Error(typeof code === "string" ? `Preview unavailable (${code}).` : "Response preview failed.");
  }
  if (!result || typeof result.mapped_variables !== "object" || typeof result.llm_data !== "object") {
    throw new Error("Response preview returned an invalid result.");
  }
  return result as ResponsePreviewResult;
}

export function looksFinancialVariable(name: string): boolean {
  return /(?:^|_)(?:amount|balance|charge|cost|currency|deposit|due|fee|price|rate|tax|total)(?:_|$)/i.test(name);
}
