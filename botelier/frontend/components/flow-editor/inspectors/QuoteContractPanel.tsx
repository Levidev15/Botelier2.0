"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, Info, X } from "lucide-react";
import type { APIRequestConfig } from "../store";
import type { FlowOutputVariable } from "../flowEditorData";
import {
  DEFAULT_QUOTE_ARGUMENTS,
  DEFAULT_QUOTE_POLICY,
  OPTIONAL_QUOTE_FIELDS,
  QUOTE_FIELD_LABELS,
  REQUIRED_QUOTE_FIELDS,
  buildQuoteResponseBindings,
  isSafeFlowVariableKey,
  validateAllowedCheckoutOrigins,
  validateQuoteArgumentsTemplate,
  type QuotePolicyEditorValue,
} from "./quoteEditor";

interface Props {
  nodeId: string;
  api: APIRequestConfig;
  update: (patch: Partial<APIRequestConfig>) => void;
  variables: FlowOutputVariable[];
}

const fieldInput =
  "w-full rounded border border-gray-700 bg-[#0b0b0b] px-2.5 py-2 text-xs text-gray-100 focus:border-emerald-500 focus:outline-none";

function projectionKeys(api: APIRequestConfig, policy: QuotePolicyEditorValue): string[] {
  const configured = api.responseProjection?.fields
    ?.map((field) => field.variable)
    .filter((key): key is string => typeof key === "string");
  return configured ?? Object.values(policy.publicConfirmationFields);
}

export default function QuoteContractPanel({ nodeId, api, update, variables }: Props) {
  const initializedNodeRef = useRef<string | null>(null);
  const [nameDrafts, setNameDrafts] = useState<Record<string, string>>({});
  const [originDraft, setOriginDraft] = useState("");
  const [protectedDrafts, setProtectedDrafts] = useState<Record<string, string>>({});
  const policy = api.quotePolicy ?? DEFAULT_QUOTE_POLICY;
  const publicPaths = useMemo(() => Object.keys(policy.publicConfirmationFields), [policy.publicConfirmationFields]);
  const publicNames = Object.values(policy.publicConfirmationFields);
  const allProtectedNames = new Set([
    ...publicNames,
    policy.fingerprintVariable,
    policy.privateUrlVariable,
  ]);
  const originText = policy.allowedCheckoutOrigins.join("\n");
  const argumentError = validateQuoteArgumentsTemplate(api.argumentsTemplate ?? "");
  const validatedOrigins = validateAllowedCheckoutOrigins(originDraft);
  const argumentTokens = Array.from(new Set(
    (api.argumentsTemplate ?? "").match(/\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}/g)?.map((token) =>
      token.slice(2, -2),
    ) ?? [],
  ));
  const unresolvedArgumentTokens = argumentTokens.filter(
    (key) => !variables.some((variable) => variable.key === key),
  );

  useEffect(() => {
    setNameDrafts({ ...policy.publicConfirmationFields });
    setProtectedDrafts({
      fingerprintVariable: policy.fingerprintVariable,
      privateUrlVariable: policy.privateUrlVariable,
    });
  }, [policy.publicConfirmationFields, policy.fingerprintVariable, policy.privateUrlVariable]);

  useEffect(() => {
    setOriginDraft(originText);
  }, [originText]);

  useEffect(() => {
    if (initializedNodeRef.current === nodeId) return;
    initializedNodeRef.current = nodeId;
    const currentPolicy = api.quotePolicy ?? DEFAULT_QUOTE_POLICY;
    const selected = projectionKeys(api, currentPolicy);
    const bindings = buildQuoteResponseBindings(currentPolicy, selected);
    update({
      quotePolicy: currentPolicy,
      argumentsTemplate: api.argumentsTemplate || DEFAULT_QUOTE_ARGUMENTS,
      ...bindings,
      method: undefined as unknown as APIRequestConfig["method"],
      url: undefined,
      path: undefined,
      headers: undefined,
      bodyTemplate: undefined,
      queryParamOverrides: undefined,
      thinkingMessage: undefined,
      responseInstructions: undefined,
      onSuccess: undefined,
      onComplete: undefined,
      onError: undefined,
      onNotFound: undefined,
      onAuthError: undefined,
      quoteDelivery: undefined,
    });
  }, [api, nodeId, update]);

  const commitPolicy = (
    nextPolicy: QuotePolicyEditorValue,
    nextProjected: string[] = projectionKeys(api, policy),
  ) => {
    update({
      quotePolicy: nextPolicy,
      ...buildQuoteResponseBindings(nextPolicy, nextProjected),
    });
  };

  const changePublicVariable = (path: string, value: string) => {
    setNameDrafts((current) => ({ ...current, [path]: value }));
    if (!isSafeFlowVariableKey(value)) return;
    const duplicate = Object.entries(policy.publicConfirmationFields)
      .some(([otherPath, otherValue]) => otherPath !== path && otherValue === value);
    if (duplicate || value === policy.fingerprintVariable || value === policy.privateUrlVariable) return;
    const knownQuoteKey = new Set([
      ...Object.values(policy.publicConfirmationFields),
      policy.fingerprintVariable,
      policy.privateUrlVariable,
    ]);
    if (variables.some((variable) =>
      variable.key === value &&
      (variable.origin === "declared" || !knownQuoteKey.has(value))
    )) return;
    const previous = policy.publicConfirmationFields[path];
    const nextPolicy = {
      ...policy,
      publicConfirmationFields: { ...policy.publicConfirmationFields, [path]: value },
    };
    const nextProjected = projectionKeys(api, policy).map((key) => key === previous ? value : key);
    commitPolicy(nextPolicy, nextProjected);
  };

  const changeProtectedVariable = (key: "fingerprintVariable" | "privateUrlVariable", value: string) => {
    setProtectedDrafts((current) => ({ ...current, [key]: value }));
    if (!isSafeFlowVariableKey(value)) return;
    const otherProtected = key === "fingerprintVariable" ? policy.privateUrlVariable : policy.fingerprintVariable;
    if (value === otherProtected || publicNames.includes(value)) return;
    if (variables.some((variable) => variable.key === value && variable.origin === "declared")) return;
    const nextPolicy = { ...policy, [key]: value };
    const selected = projectionKeys(api, policy);
    commitPolicy(nextPolicy, selected);
  };

  const toggleOptionalField = (path: string) => {
    const fields = { ...policy.publicConfirmationFields };
    const existing = fields[path];
    if (existing) {
      delete fields[path];
      const selected = projectionKeys(api, policy).filter((key) => key !== existing);
      commitPolicy({ ...policy, publicConfirmationFields: fields }, selected);
      return;
    }
    const stem = `quote_${path.replaceAll(".", "_")}`;
    const reserved = new Set([...Object.values(fields), policy.fingerprintVariable, policy.privateUrlVariable]);
    let name = stem;
    let suffix = 2;
    while (
      reserved.has(name) ||
      variables.some((variable) => variable.key === name)
    ) name = `${stem}_${suffix++}`;
    fields[path] = name;
    commitPolicy({ ...policy, publicConfirmationFields: fields }, [...projectionKeys(api, policy), name]);
  };

  const projectionSet = new Set(projectionKeys(api, policy));
  const keyError = (path: string) => {
    const value = nameDrafts[path] ?? policy.publicConfirmationFields[path] ?? "";
    if (!value || !isSafeFlowVariableKey(value)) return "Use a unique variable name (letters, numbers and underscores; 48 characters max).";
    if (publicNames.some((name) => name === value && name !== policy.publicConfirmationFields[path])) return "Each quote field needs a unique variable.";
    if (value === policy.fingerprintVariable || value === policy.privateUrlVariable) return "Public fields cannot reuse a protected internal variable.";
    if (variables.some((variable) =>
      variable.key === value &&
      (variable.origin === "declared" || !allProtectedNames.has(value))
    )) return "Choose a name not already used by another flow variable.";
    return null;
  };
  const protectedError = (key: "fingerprintVariable" | "privateUrlVariable") => {
    const value = protectedDrafts[key] ?? policy[key];
    if (!isSafeFlowVariableKey(value)) return "Use a valid variable name.";
    if (allProtectedNames.has(value) && value !== policy[key]) return "Protected variables must be unique and separate from public fields.";
    if (value === (key === "fingerprintVariable" ? policy.privateUrlVariable : policy.fingerprintVariable)) return "Protected variables must be different.";
    if (variables.some((variable) => variable.key === value && variable.origin === "declared")) return "Choose a name not already used by a declared flow variable.";
    return null;
  };

  return (
    <section className="space-y-4 rounded-xl border border-emerald-900/60 bg-[#101615] p-3">
      <header>
        <div className="flex items-center gap-2">
          <h4 className="text-sm font-semibold text-emerald-200">Reservation quote contract</h4>
          <span className="rounded-full border border-emerald-800 px-2 py-0.5 text-[9px] uppercase tracking-wide text-emerald-300">V1 · validation only</span>
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-gray-400">
          Configures pure validation of provider quote data against the caller&apos;s current selection. The server decides execution availability; this editor never fetches a quote, creates a reservation, or starts payment.
        </p>
      </header>

      <div>
        <label className="mb-1 block text-xs font-medium text-gray-300">Quote arguments (typed JSON)</label>
        <textarea
          value={api.argumentsTemplate ?? DEFAULT_QUOTE_ARGUMENTS}
          onChange={(event) => update({ argumentsTemplate: event.target.value })}
          rows={5}
          spellCheck={false}
          className={`${fieldInput} resize-y font-mono`}
          aria-label="Quote capability arguments template"
        />
        <p className="mt-1 text-[10px] leading-relaxed text-gray-500">
          The top-level object is exactly <code>quote</code> and <code>expected</code>. Bind normalized provider data and the selected option/caller facts with typed {"{{variable}}"} tokens; never ask the model to choose the price.
        </p>
        {argumentError && <p role="alert" className="mt-1 flex items-start gap-1.5 text-[10px] text-amber-300"><AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />{argumentError}</p>}
        {unresolvedArgumentTokens.length > 0 && (
          <p role="alert" className="mt-1 text-[10px] text-amber-300">
            Define these typed facts earlier in the flow: {unresolvedArgumentTokens.join(", ")}.
          </p>
        )}
      </div>

      <div>
        <div className="mb-1 flex items-center justify-between gap-2">
          <label className="text-xs font-medium text-gray-300">Approved checkout origins</label>
          <label className="flex items-center gap-1.5 text-[10px] text-gray-400">
            <input
              type="checkbox"
              checked={policy.requireCheckoutLink}
              onChange={(event) => commitPolicy({ ...policy, requireCheckoutLink: event.target.checked })}
              className="accent-emerald-500"
            />
            Link required
          </label>
        </div>
        <textarea
          value={originDraft}
          onChange={(event) => {
            setOriginDraft(event.target.value);
            const parsed = validateAllowedCheckoutOrigins(event.target.value);
            if (!parsed.error) commitPolicy({ ...policy, allowedCheckoutOrigins: parsed.origins });
          }}
          rows={2}
          className={`${fieldInput} resize-y font-mono`}
          placeholder={"https://bookings.your-property.com"}
          aria-label="Allowed checkout origins"
        />
        <p className="mt-1 text-[10px] text-gray-500">One HTTPS origin per line. No paths, query parameters, fragments, credentials or URL checks are performed.</p>
        {validatedOrigins.error && <p role="alert" className="mt-1 text-[10px] text-amber-300">{validatedOrigins.error}</p>}
        {policy.requireCheckoutLink && !policy.allowedCheckoutOrigins.length && (
          <p role="alert" className="mt-1 text-[10px] text-amber-300">Add the actual approved origin before publishing a required-link quote flow.</p>
        )}
        {!policy.requireCheckoutLink && !policy.allowedCheckoutOrigins.length && (
          <p className="mt-1 text-[10px] text-gray-500">If a provider quote supplies a checkout URL, an approved origin is still required to accept it.</p>
        )}
      </div>

      <div className="rounded-lg border border-gray-800 bg-[#0b0b0b] p-2.5">
        <p className="mb-2 text-xs font-medium text-gray-300">Canonical public fields</p>
        <p className="mb-2 text-[10px] text-gray-500">These 13 quote roles are fixed. Edit only their unique variable names; source paths and financial meanings cannot be swapped.</p>
        <div className="space-y-2">
          {REQUIRED_QUOTE_FIELDS.map((path) => {
            const value = nameDrafts[path] ?? policy.publicConfirmationFields[path] ?? "";
            const error = keyError(path);
            return (
              <div key={path} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] items-center gap-2">
                <div>
                  <p className="text-[11px] text-gray-300">{QUOTE_FIELD_LABELS[path]}</p>
                  <code className="text-[9px] text-gray-600">{path}</code>
                </div>
                <div>
                  <input
                    value={value}
                    onChange={(event) => changePublicVariable(path, event.target.value)}
                    onBlur={() => {
                      if (keyError(path)) setNameDrafts((current) => ({ ...current, [path]: policy.publicConfirmationFields[path] }));
                    }}
                    className={fieldInput}
                    aria-label={`${QUOTE_FIELD_LABELS[path]} variable`}
                  />
                  {error && <p className="mt-0.5 text-[9px] text-amber-300">{error}</p>}
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-3 border-t border-gray-800 pt-2">
          <p className="mb-2 text-[10px] uppercase tracking-wide text-gray-500">Optional — include only when the quote supplies it</p>
          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
            {OPTIONAL_QUOTE_FIELDS.map((path) => {
              const variable = policy.publicConfirmationFields[path];
              return (
                <label key={path} className="flex items-center gap-2 text-[10px] text-gray-400">
                  <input type="checkbox" checked={!!variable} onChange={() => toggleOptionalField(path)} className="accent-emerald-500" />
                  <span>{QUOTE_FIELD_LABELS[path]}</span>
                  {variable && <code className="ml-auto text-emerald-300">{variable}</code>}
                </label>
              );
            })}
          </div>
          {publicPaths.some((path) => !(REQUIRED_QUOTE_FIELDS as readonly string[]).includes(path)) && (
            <div className="mt-2 space-y-2">
              {publicPaths.filter((path) => !(REQUIRED_QUOTE_FIELDS as readonly string[]).includes(path)).map((path) => (
                <div key={path} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] items-center gap-2">
                  <span className="text-[11px] text-gray-300">{QUOTE_FIELD_LABELS[path]} <code className="block text-[9px] text-gray-600">{path}</code></span>
                  <div className="flex items-center gap-1">
                    <input
                      value={nameDrafts[path] ?? policy.publicConfirmationFields[path]}
                      onChange={(event) => changePublicVariable(path, event.target.value)}
                      onBlur={() => {
                        if (keyError(path)) setNameDrafts((current) => ({ ...current, [path]: policy.publicConfirmationFields[path] }));
                      }}
                      className={fieldInput}
                      aria-label={`${QUOTE_FIELD_LABELS[path]} variable`}
                    />
                    <button type="button" onClick={() => toggleOptionalField(path)} className="rounded p-1 text-gray-500 hover:text-red-300" aria-label={`Remove ${QUOTE_FIELD_LABELS[path]}`}>
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  {keyError(path) && <p className="col-span-2 text-[9px] text-amber-300">{keyError(path)}</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {(["fingerprintVariable", "privateUrlVariable"] as const).map((key) => (
          <div key={key}>
            <label className="mb-1 block text-xs font-medium text-gray-400">
              {key === "fingerprintVariable" ? "Internal quote fingerprint" : "Private delivery URL variable"}
            </label>
            <input
              value={protectedDrafts[key] ?? policy[key]}
              onChange={(event) => changeProtectedVariable(key, event.target.value)}
              onBlur={() => {
                if (protectedError(key)) setProtectedDrafts((current) => ({ ...current, [key]: policy[key] }));
              }}
              className={fieldInput}
              aria-label={key === "fingerprintVariable" ? "Quote fingerprint variable" : "Private checkout URL variable"}
            />
            {protectedError(key) && <p className="mt-0.5 text-[9px] text-amber-300">{protectedError(key)}</p>}
          </div>
        ))}
      </div>
      <div className="flex items-start gap-2 rounded-lg border border-amber-900/50 bg-amber-950/15 p-2.5 text-[10px] leading-relaxed text-amber-200/80">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <p>The fingerprint and private URL are excluded from caller-facing projection and must never appear in spoken summaries. No missing tax, fee, due-now or other financial values are generated here.</p>
      </div>

      <div className="rounded-lg border border-gray-800 bg-[#0b0b0b] p-2.5">
        <p className="mb-2 text-xs font-medium text-gray-300">Provider-selected dimensions</p>
        <p className="mb-2 text-[10px] text-gray-500">Only the provider may select a rate or offer. Hotel identity is never provider-selected.</p>
        <div className="flex gap-4">
          {(["rate_id", "offer_id"] as const).map((dimension) => (
            <label key={dimension} className="flex items-center gap-2 text-xs text-gray-400">
              <input
                type="checkbox"
                checked={policy.providerSelectedDimensions.includes(dimension)}
                onChange={(event) => {
                  const next = event.target.checked
                    ? [...policy.providerSelectedDimensions, dimension]
                    : policy.providerSelectedDimensions.filter((item) => item !== dimension);
                  commitPolicy({ ...policy, providerSelectedDimensions: next });
                }}
                className="accent-emerald-500"
              />
              {dimension}
            </label>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-gray-800 bg-[#0b0b0b] p-2.5">
        <p className="mb-1 text-xs font-medium text-gray-300">Caller-facing projection</p>
        <p className="mb-2 text-[10px] text-gray-500">Choose which validated public details the model may read. Protected internal fields are never selectable.</p>
        <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
          {Object.entries(policy.publicConfirmationFields).map(([path, variable]) => (
            <label key={path} className="flex items-center gap-2 text-[10px] text-gray-400">
              <input
                type="checkbox"
                checked={projectionSet.has(variable)}
                onChange={(event) => {
                    const next = event.target.checked
                    ? [...Array.from(projectionSet), variable]
                    : Array.from(projectionSet).filter((key) => key !== variable);
                  commitPolicy(policy, next);
                }}
                className="accent-emerald-500"
              />
              <span>{QUOTE_FIELD_LABELS[path]}</span>
            </label>
          ))}
        </div>
      </div>
      <div className="rounded border border-gray-800 bg-[#0b0b0b] p-2 text-[10px] text-gray-500">
        Flow facts available while authoring: {variables.length}. Output mappings are exact JSONPath bindings; protected paths have no defaults and cannot be redirected.
      </div>
    </section>
  );
}
