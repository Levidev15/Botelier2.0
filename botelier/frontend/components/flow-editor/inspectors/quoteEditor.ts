export const REQUIRED_QUOTE_FIELDS = [
  "room_id",
  "check_in",
  "check_out",
  "adults",
  "children",
  "pricing.basis",
  "pricing.currency",
  "pricing.subtotal",
  "pricing.tax_total",
  "pricing.tax_treatment",
  "pricing.fees_total",
  "pricing.fees_treatment",
  "pricing.total",
] as const;

export const OPTIONAL_QUOTE_FIELDS = [
  "quote_id",
  "hotel_id",
  "rate_id",
  "offer_id",
  "terms",
  "expires_at",
  "pricing.tax_lines",
  "pricing.fee_lines",
  "pricing.rounding_adjustment",
  "pricing.discount_total",
  "pricing.due_now",
  "pricing.pay_at_property",
] as const;

export const QUOTE_FIELD_LABELS: Record<string, string> = {
  room_id: "Room identity",
  check_in: "Check-in",
  check_out: "Check-out",
  adults: "Adults",
  children: "Children",
  "pricing.basis": "Pricing basis",
  "pricing.currency": "Currency",
  "pricing.subtotal": "Stay subtotal",
  "pricing.tax_total": "Tax total",
  "pricing.tax_treatment": "Tax treatment",
  "pricing.fees_total": "Fees total",
  "pricing.fees_treatment": "Fees treatment",
  "pricing.total": "Stay total",
  quote_id: "Quote identity",
  hotel_id: "Hotel identity",
  rate_id: "Rate identity",
  offer_id: "Offer identity",
  terms: "Quote terms",
  expires_at: "Quote expiry",
  "pricing.tax_lines": "Tax line items",
  "pricing.fee_lines": "Fee line items",
  "pricing.rounding_adjustment": "Rounding adjustment",
  "pricing.discount_total": "Discount total",
  "pricing.due_now": "Due now",
  "pricing.pay_at_property": "Pay at property",
};

export interface QuotePolicyEditorValue {
  allowedCheckoutOrigins: string[];
  requireCheckoutLink: boolean;
  providerSelectedDimensions: Array<"rate_id" | "offer_id">;
  fingerprintVariable: string;
  privateUrlVariable: string;
  publicConfirmationFields: Record<string, string>;
}

export const DEFAULT_QUOTE_POLICY: QuotePolicyEditorValue = {
  allowedCheckoutOrigins: [],
  requireCheckoutLink: true,
  providerSelectedDimensions: [],
  fingerprintVariable: "quote_fingerprint",
  privateUrlVariable: "private_checkout_url",
  publicConfirmationFields: Object.fromEntries(
    REQUIRED_QUOTE_FIELDS.map((path) => [path, `quote_${path.replaceAll(".", "_")}`]),
  ),
};

export const DEFAULT_QUOTE_ARGUMENTS =
  '{\n  "quote": {{provider_quote}},\n  "expected": {{selected_option}}\n}';

export interface QuoteResponseBindings {
  responseMapping: Record<string, string>;
  responseVariables: Array<{ variableKey: string; jsonPath: string }>;
  responseProjection: { fields: Array<{ variable: string }> };
}

export function buildQuoteResponseBindings(
  policy: QuotePolicyEditorValue,
  projectedVariables?: string[],
): QuoteResponseBindings {
  const responseMapping: Record<string, string> = {};
  for (const [path, variable] of Object.entries(policy.publicConfirmationFields)) {
    responseMapping[variable] = `$.public.${path}`;
  }
  responseMapping[policy.fingerprintVariable] = "$.fingerprint";
  responseMapping[policy.privateUrlVariable] = "$.private.checkout_url";

  const selected = new Set(projectedVariables ?? Object.values(policy.publicConfirmationFields));
  const publicKeys = new Set(Object.values(policy.publicConfirmationFields));
  return {
    responseMapping,
    responseVariables: Object.entries(responseMapping).map(([variableKey, jsonPath]) => ({
      variableKey,
      jsonPath,
    })),
    responseProjection: {
      fields: Object.values(policy.publicConfirmationFields)
        .filter((variable) => publicKeys.has(variable) && selected.has(variable))
        .map((variable) => ({ variable })),
    },
  };
}

export function isSafeFlowVariableKey(value: string): boolean {
  return /^[A-Za-z_][A-Za-z0-9_]{0,47}$/.test(value) && !value.startsWith("__native");
}

export function validateAllowedCheckoutOrigins(value: string): {
  origins: string[];
  error?: string;
} {
  const origins: string[] = [];
  for (const line of value.split(/\r?\n/)) {
    const entry = line.trim();
    if (!entry) continue;
    try {
      const url = new URL(entry);
      if (
        url.protocol !== "https:" ||
        !url.hostname ||
        url.username ||
        url.password ||
        (url.pathname !== "/" && url.pathname !== "") ||
        url.search ||
        url.hash
      ) return { origins, error: "Enter HTTPS origins only (scheme and host, with no path, query or fragment)." };
      origins.push(url.origin);
    } catch {
      return { origins, error: "Enter a valid HTTPS origin." };
    }
  }
  if (new Set(origins.map((origin) => origin.toLowerCase())).size !== origins.length) {
    return { origins, error: "Each checkout origin must be unique." };
  }
  return { origins };
}

function replaceTemplateTokens(template: string): string {
  return template.replace(/\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}/g, (_match, key: string, offset: number) => {
    const before = template[offset - 1];
    const after = template[offset + _match.length];
    const insideString = (() => {
      let quoted = false;
      let escaped = false;
      for (let index = 0; index < offset; index += 1) {
        const char = template[index];
        if (escaped) escaped = false;
        else if (char === "\\") escaped = true;
        else if (char === '"') quoted = !quoted;
      }
      return quoted;
    })();
    const sentinel = `__FLOWVAR_${key}__`;
    if (insideString && before === '"' && after === '"') return sentinel;
    if (insideString) return sentinel;
    return JSON.stringify(sentinel);
  });
}

export function validateQuoteArgumentsTemplate(template: string): string | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(replaceTemplateTokens(template));
  } catch {
    return "Use valid JSON with typed {{variable}} tokens.";
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return "The arguments template must be a JSON object.";
  }
  const value = parsed as Record<string, unknown>;
  if (Object.keys(value).length !== 2 || !Object.hasOwn(value, "quote") || !Object.hasOwn(value, "expected")) {
    return 'The quote capability accepts exactly two top-level keys: "quote" and "expected".';
  }
  for (const key of ["quote", "expected"]) {
    const item = value[key];
    const bareObjectToken = new RegExp(
      `"${key}"\\s*:\\s*\\{\\{[A-Za-z_][A-Za-z0-9_]*\\}\\}`,
    ).test(template);
    if (
      (!item || typeof item !== "object" || Array.isArray(item)) &&
      !(
        typeof item === "string" &&
        /^__FLOWVAR_[A-Za-z_][A-Za-z0-9_]*__$/.test(item) &&
        bareObjectToken
      )
    ) return `"${key}" must render as a typed JSON object.`;
  }
  return null;
}

export function quoteObjectInputVariable(template: string): string | null {
  const match = template.match(/"quote"\s*:\s*\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/);
  return match?.[1] ?? null;
}

export function defaultQuoteDeliveryTemplate(
  toolType: "SEND_SMS" | "SEND_EMAIL",
  recipientVariable: string,
  privateUrlVariable: string,
): string {
  if (toolType === "SEND_EMAIL") {
    return JSON.stringify({
      recipient: `{{${recipientVariable}}}`,
      subject: "Your reservation quote",
      body: `Review your selected reservation:\n{{${privateUrlVariable}}}`,
    }, null, 2);
  }
  return JSON.stringify({
    recipient: `{{${recipientVariable}}}`,
    body: `Review your selected reservation:\n{{${privateUrlVariable}}}`,
  }, null, 2);
}

export function validateQuoteDeliveryTemplate(
  template: string,
  toolType: "SEND_SMS" | "SEND_EMAIL",
  recipientVariable: string,
  privateUrlVariable: string,
): string | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(replaceTemplateTokens(template));
  } catch {
    return "Use a valid JSON arguments object with typed variable tokens.";
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return "Delivery arguments must be a JSON object.";
  }
  const args = parsed as Record<string, unknown>;
  const allowed = toolType === "SEND_EMAIL"
    ? ["recipient", "subject", "body"]
    : ["recipient", "body"];
  if (
    Object.keys(args).length !== allowed.length ||
    allowed.some((key) => !Object.hasOwn(args, key))
  ) return `This ${toolType === "SEND_EMAIL" ? "email" : "SMS"} link delivery requires only ${allowed.join(", ")}.`;

  const expectedRecipient = `__FLOWVAR_${recipientVariable}__`;
  if (args.recipient !== expectedRecipient) {
    return "The delivery recipient must be the selected recipient variable.";
  }
  if (typeof args.body !== "string") return "The message body must be plain text.";
  const privateToken = `{{${privateUrlVariable}}}`;
  if (template.split(privateToken).length - 1 !== 1) {
    return "The body must include the private checkout URL variable exactly once.";
  }
  const bodyWithoutToken = template.replace(privateToken, "");
  if (/https?:\/\/[^\s"<>]+/i.test(bodyWithoutToken)) {
    return "The body may not contain another URL; the validated quote link is inserted at delivery.";
  }
  if (/<\/?[a-z][^>]*>/i.test(args.body)) {
    return "Use a text-only message. HTML delivery is not supported.";
  }
  if (
    typeof args.subject === "string" &&
    (
      args.subject.includes(privateToken) ||
      args.subject.includes(`__FLOWVAR_${privateUrlVariable}__`) ||
      /https?:\/\//i.test(args.subject)
    )
  ) return "The subject must not contain a URL.";
  return null;
}
