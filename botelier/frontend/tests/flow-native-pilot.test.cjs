const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

function loadModule(relative, dependencies = {}, extras = {}) {
  const source = fs.readFileSync(path.join(__dirname, "..", relative), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, {
    exports,
    URL,
    Response,
    Headers,
    console: { error() {}, warn() {} },
    require: name => {
      if (!(name in dependencies)) throw new Error(`Unexpected dependency: ${name}`);
      return dependencies[name];
    },
    ...extras,
  });
  return exports;
}

function loadSimulator() {
  return loadModule("components/flow-simulator/nativePilot.ts");
}

function loadFlowEditorData() {
  return loadModule("components/flow-editor/flowEditorData.ts");
}

function loadResponsePreview() {
  return loadModule("components/flow-editor/inspectors/responsePreview.ts");
}

function loadQuoteEditor() {
  return loadModule("components/flow-editor/inspectors/quoteEditor.ts");
}

function loadMCPNativePolicy() {
  return loadModule("components/mcpNativePolicy.ts");
}

function validSnapshot(overrides = {}) {
  return {
    assistantId: "assistant-7",
    isDirty: false,
    currentSource: "published",
    currentVersionNumber: 12,
    publishedVersionNumber: 12,
    currentVersionId: "flow-version-12",
    ...overrides,
  };
}

test("connected API nodes render a saved endpoint without requiring a custom URL", () => {
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const empty = () => null;
  const { default: APIRequestNode } = loadModule("components/flow-editor/nodes/APIRequestNode.tsx", {
    react: React,
    "react/jsx-runtime": require("react/jsx-runtime"),
    "@xyflow/react": { Handle: empty, Position: { Top: "top", Bottom: "bottom" } },
    "lucide-react": { Globe: empty, Grip: empty, ArrowRightLeft: empty, AlertTriangle: empty },
  });
  for (const api of [
    { method: "GET", apiSource: "integration", endpointId: "rooms-get", endpointName: "Rooms endpoint" },
    { method: "GET", apiSource: "integration", endpointId: "rooms-get" },
    { method: "GET", apiSource: "custom", url: undefined },
    { method: "GET", apiSource: "custom", url: 42 },
    { method: "GET", apiSource: "custom", url: "https://example.test/rooms" },
  ]) {
    const html = renderToStaticMarkup(React.createElement(APIRequestNode, {
      data: { name: "Synthetic API", api },
    }));
    assert.match(html, /Synthetic API/);
    if (api.endpointName) assert.match(html, /Rooms endpoint/);
    if (typeof api.url === "string") assert.match(html, /example.test/);
  }
});

test("legacy remains the exact default-compatible payload and native is explicit", () => {
  const { buildSimulationStartPayload } = loadSimulator();
  assert.deepEqual(
    JSON.parse(JSON.stringify(buildSimulationStartPayload({ toolId: "tool-3" }))),
    { tool_id: "tool-3" },
  );
  assert.deepEqual(
    JSON.parse(JSON.stringify(buildSimulationStartPayload({ toolId: "tool-3", engine: "legacy" }))),
    { tool_id: "tool-3" },
  );
  assert.deepEqual(
    JSON.parse(JSON.stringify(buildSimulationStartPayload({
      toolId: "tool-3",
      engine: "native",
      snapshot: validSnapshot(),
    }))),
    {
      tool_id: "tool-3",
      assistant_id: "assistant-7",
      engine: "native_pilot",
      source: "published",
      source_version: 12,
    },
  );
});

test("native eligibility rejects drafts, edits, missing assistant, and stale version before fetch", async () => {
  const { requestSimulationStart } = loadSimulator();
  for (const snapshot of [
    validSnapshot({ currentSource: "draft" }),
    validSnapshot({ isDirty: true }),
    validSnapshot({ assistantId: "" }),
    validSnapshot({ currentVersionNumber: 0 }),
    validSnapshot({ currentVersionNumber: 11 }),
    validSnapshot({ currentVersionId: null }),
  ]) {
    let calls = 0;
    await assert.rejects(
      requestSimulationStart({
        authFetch: async () => { calls += 1; throw new Error("must not fetch"); },
        toolId: "tool-3",
        engine: "native",
        snapshot,
      }),
    );
    assert.equal(calls, 0, JSON.stringify(snapshot));
  }
});

test("native runtime identity mismatch refuses the session and deletes a returned session id", async () => {
  const { requestSimulationStart } = loadSimulator();
  const calls = [];
  const result = await requestSimulationStart({
    authFetch: async (url, options) => {
      calls.push({ url, options });
      if (url === "/api/simulate/start") {
        return new Response(JSON.stringify({
          session_id: "session-untrusted",
          messages: [{ role: "assistant", content: "not to be shown" }],
          state: {},
          runtime: {
            engine: "native_pilot", source: "published", tool_id: "tool-3", assistant_id: "assistant-7",
            account_id: "account-2", property_id: "property-4", flow_version_id: "another-version",
            version_number: 12, llm_provider: "hidden", llm_model: "hidden",
          },
        }), { status: 200 });
      }
      return new Response("", { status: 204 });
    },
    toolId: "tool-3",
    engine: "native",
    snapshot: validSnapshot(),
  });
  assert.equal(result.ok, false);
  assert.equal(result.session, null);
  assert.equal(calls.length, 2);
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    tool_id: "tool-3",
    assistant_id: "assistant-7",
    engine: "native_pilot",
    source: "published",
    source_version: 12,
  });
  assert.deepEqual(JSON.parse(JSON.stringify(calls[1])), {
    url: "/api/simulate/session/session-untrusted",
    options: { method: "DELETE" },
  });
});

test("matching native runtime evidence is returned only after exact snapshot verification", async () => {
  const { requestSimulationStart } = loadSimulator();
  const runtime = {
    engine: "native_pilot",
    source: "published",
    tool_id: "tool-3",
    assistant_id: "assistant-7",
    account_id: "account-2",
    property_id: "property-4",
    flow_version_id: "flow-version-12",
    version_number: 12,
    llm_provider: "private-provider",
    llm_model: "private-model",
  };
  let calls = 0;
  const result = await requestSimulationStart({
    authFetch: async () => {
      calls += 1;
      return new Response(JSON.stringify({
        session_id: "verified-session",
        messages: [{ role: "assistant", content: "ready" }],
        state: { collected_slots: {}, current_node: null },
        runtime,
      }), { status: 200 });
    },
    toolId: "tool-3",
    engine: "native",
    snapshot: validSnapshot(),
  });
  assert.equal(result.ok, true);
  assert.equal(calls, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(result.data.runtime)), runtime);
});

test("native runtime verification rejects each identity or source field mismatch", () => {
  const { verifyNativeRuntime } = loadSimulator();
  const snapshot = validSnapshot();
  const runtime = {
    engine: "native_pilot",
    source: "published",
    tool_id: "tool-3",
    assistant_id: "assistant-7",
    version_number: 12,
    flow_version_id: "flow-version-12",
  };
  assert.equal(verifyNativeRuntime(runtime, "tool-3", snapshot), true);
  for (const changed of [
    { engine: "legacy" },
    { source: "draft" },
    { tool_id: "other-tool" },
    { assistant_id: "other-assistant" },
    { version_number: 11 },
    { flow_version_id: "other-version" },
  ]) {
    assert.equal(verifyNativeRuntime({ ...runtime, ...changed }, "tool-3", snapshot), false);
  }
});

test("native HTTP errors are allowlisted and never trigger a legacy retry", async () => {
  const { requestSimulationStart } = loadSimulator();
  for (const detail of [
    "Native pilot requires a published flow",
    { code: "native_simulation_flow_unsupported", diagnostic: "provider-secret-must-not-display" },
  ]) {
    let calls = 0;
    await assert.rejects(
      requestSimulationStart({
        authFetch: async () => {
          calls += 1;
          return new Response(JSON.stringify({ detail }), { status: 422 });
        },
        toolId: "tool-3",
        engine: "native",
        snapshot: validSnapshot(),
      }),
      error => {
        assert.match(error.message, /published|server could not admit/i);
        assert.doesNotMatch(error.message, /exactly six-node|read-only shape/i);
        assert.doesNotMatch(error.message, /provider-secret/);
        return true;
      },
    );
    assert.equal(calls, 1);
  }
});

test("fixed native errors are actionable and unexpected structured detail is non-leaking", () => {
  const { formatNativeError } = loadSimulator();
  const unsupported = formatNativeError({
    code: "native_simulation_flow_unsupported",
    diagnostic: "node_types",
  });
  assert.match(unsupported, /server could not admit this published flow/i);
  assert.doesNotMatch(unsupported, /six-node|read-only/i);
  assert.match(formatNativeError({
    code: "native_simulation_flow_unsupported",
    diagnostic: "global_instructions",
  }), /server could not admit this published flow/i);
  assert.match(formatNativeError({
    code: "native_simulation_flow_unsupported",
    diagnostic: "connected_get",
  }), /server could not admit this published flow/i);
  assert.match(formatNativeError({
    code: "native_simulation_flow_unsupported",
    diagnostic: "unlisted_provider_payload",
  }), /server could not admit this published flow/i);
  assert.match(formatNativeError("Native pilot requires a published flow"), /published/i);
  const safe = formatNativeError({
    code: "provider_secret_dump",
    diagnostic: "Bearer secret-provider-token",
  });
  assert.match(safe, /could not start/i);
  assert.doesNotMatch(safe, /secret-provider-token|Bearer/);
});

test("native error allowlists reject inherited object keys instead of rendering functions or objects", () => {
  const { formatNativeError } = loadSimulator();
  for (const key of ["__proto__", "constructor", "toString", "valueOf"]) {
    for (const detail of [
      key,
      { code: key },
      { code: "native_simulation_flow_unsupported", diagnostic: key },
    ]) {
      const message = formatNativeError(detail);
      assert.equal(typeof message, "string", JSON.stringify(detail));
   assert.match(message, /could not start|server could not admit/i);
    }
  }
});

test("mapped API outputs become downstream choices without changing their JSON values", () => {
  const { collectFlowVariables } = loadFlowEditorData();
  const variables = [{ key: "guest_name", type: "text", description: "", required: true }];
  const nodes = [{
    id: "lookup",
    type: "api_request",
    data: { api: {
      responseMapping: { available_rooms: "$.rooms" },
      responseVariables: [{ variableKey: "total", jsonPath: "$.total", defaultValue: 0 }],
    } },
  }];
  const result = collectFlowVariables(variables, nodes);
  assert.deepEqual(JSON.parse(JSON.stringify(result.map(({ key, type, required, origin }) => ({
    key, type, required, origin,
  })))), [
    { key: "guest_name", type: "text", required: true, origin: "declared" },
    { key: "available_rooms", type: "text", required: false, origin: "mapped" },
    { key: "total", type: "text", required: false, origin: "mapped" },
  ]);
  assert.equal(result[1].description.includes("array or object"), true);
  assert.deepEqual(variables, [{ key: "guest_name", type: "text", description: "", required: true }]);
});

test("copy/paste remaps Record update references only when the source node is copied too", () => {
  const { duplicateFlowSelection } = loadFlowEditorData();
  const nodes = [
    { id: "record-create", type: "save_record", position: { x: 1, y: 2 }, data: { name: "Create", saveRecord: { recordTypeId: "booking" } } },
    { id: "record-update", type: "save_record", position: { x: 3, y: 4 }, data: { name: "Update", saveRecord: { recordTypeId: "booking", updateSourceNodeId: "record-create" } } },
    { id: "other-update", type: "save_record", position: { x: 5, y: 6 }, data: { name: "Other", saveRecord: { recordTypeId: "booking", updateSourceNodeId: "record-create" } } },
  ];
  const edges = [{ id: "create-update", source: "record-create", target: "record-update", type: "deletable" }];
  let id = 0;
  const both = duplicateFlowSelection(nodes.slice(0, 2), edges, () => `copy-${++id}`);
  const copiedCreate = both.nodes.find((node) => node.data.name === "Create");
  const copiedUpdate = both.nodes.find((node) => node.data.name === "Update");
  assert.equal(copiedUpdate.data.saveRecord.updateSourceNodeId, copiedCreate.id);
  assert.equal(both.edges[0].source, copiedCreate.id);
  assert.equal(both.edges[0].target, copiedUpdate.id);
  const updateOnly = duplicateFlowSelection([nodes[1]], edges, () => `solo-${++id}`);
  assert.equal(Object.hasOwn(updateOnly.nodes[0].data.saveRecord, "updateSourceNodeId"), false);
  assert.deepEqual(JSON.parse(JSON.stringify(updateOnly.remappedReferences)), [updateOnly.nodes[0].id]);
});

test("copy/paste remaps quote delivery references and clears external validator links", () => {
  const { duplicateFlowSelection } = loadFlowEditorData();
  const nodes = [
    {
      id: "quote-validator",
      type: "api_request",
      position: { x: 0, y: 0 },
      data: { api: { apiSource: "capability", capability: "validate_reservation_quote" } },
    },
    {
      id: "quote-sender",
      type: "api_request",
      position: { x: 2, y: 2 },
      data: { api: { apiSource: "tool", toolId: "sms-tool", argumentsTemplate: "{\"body\":\"{{private_checkout_url}}\"}", quoteDelivery: { quoteNodeId: "quote-validator", recipientVariable: "caller_phone" } } },
    },
  ];
  let id = 0;
  const both = duplicateFlowSelection(nodes, [{ id: "quote-send", source: "quote-validator", target: "quote-sender" }], () => `copy-${++id}`);
  const copiedValidator = both.nodes.find((node) => node.data.api?.capability === "validate_reservation_quote");
  const copiedSender = both.nodes.find((node) => node.data.api?.toolId === "sms-tool");
  assert.equal(copiedSender.data.api.quoteDelivery.quoteNodeId, copiedValidator.id);
  assert.equal(both.clearedReferences.length, 0);
  const senderOnly = duplicateFlowSelection([nodes[1]], [], () => `solo-${++id}`);
  assert.equal(Object.hasOwn(senderOnly.nodes[0].data.api, "quoteDelivery"), false);
  assert.equal(senderOnly.nodes[0].data.api.argumentsTemplate, "");
  assert.deepEqual(JSON.parse(JSON.stringify(senderOnly.clearedReferences)), [senderOnly.nodes[0].id]);
});

test("Record update source choices require same type and a real directed path", () => {
  const { findCompatibleRecordSources } = loadFlowEditorData();
  const nodes = [
    { id: "create", type: "save_record", data: { name: "Reservation", saveRecord: { recordTypeId: "booking" } } },
    { id: "target", type: "save_record", data: { name: "Edit reservation", saveRecord: { recordTypeId: "booking" } } },
    { id: "wrong-type", type: "save_record", data: { saveRecord: { recordTypeId: "guest" } } },
    { id: "already-update", type: "save_record", data: { saveRecord: { recordTypeId: "booking", updateSourceNodeId: "create" } } },
  ];
  const choices = findCompatibleRecordSources(nodes, [
    { source: "create", target: "target" },
    { source: "wrong-type", target: "target" },
    { source: "already-update", target: "target" },
  ], "target", "booking");
  assert.deepEqual(choices.map((node) => node.id), ["create"]);
});

test("quote confirmation requirements bind public fields, fingerprint and delivery recipient only", () => {
  const {
    findQuoteConfirmationContext,
    findQuoteSpeechProtections,
    hasQuotePrivateSpeech,
  } = loadFlowEditorData();
  const { DEFAULT_QUOTE_POLICY, DEFAULT_QUOTE_ARGUMENTS } = loadQuoteEditor();
  const nodes = [
    { id: "quote", type: "api_request", data: { name: "Quote", api: {
      apiSource: "capability",
      capability: "validate_reservation_quote",
      quotePolicy: DEFAULT_QUOTE_POLICY,
      argumentsTemplate: DEFAULT_QUOTE_ARGUMENTS,
    } } },
    { id: "confirm", type: "confirmation", data: {} },
    { id: "send", type: "api_request", data: { api: {
      apiSource: "tool",
      quoteDelivery: { quoteNodeId: "quote", recipientVariable: "caller_email" },
    } } },
    { id: "speech", type: "message", data: {} },
  ];
  const edges = [
    { source: "quote", target: "confirm" },
    { source: "confirm", target: "send" },
    { source: "confirm", target: "speech" },
  ];
  const context = findQuoteConfirmationContext(nodes, edges, "confirm");
  assert.equal(context.validators[0].id, "quote");
  assert.equal(context.publicVariables.length, 13);
  assert.deepEqual(JSON.parse(JSON.stringify(context.fingerprintVariables)), ["quote_fingerprint"]);
  assert.deepEqual(JSON.parse(JSON.stringify(context.recipientVariables)), ["caller_email"]);
  assert.deepEqual(JSON.parse(JSON.stringify(context.privateVariables)), ["private_checkout_url"]);
  const speech = findQuoteSpeechProtections(nodes, edges, "speech");
  assert.deepEqual(JSON.parse(JSON.stringify(speech.privateVariables)), ["private_checkout_url"]);
  assert.deepEqual(JSON.parse(JSON.stringify(speech.fingerprintVariables)), ["quote_fingerprint"]);
  assert.deepEqual(JSON.parse(JSON.stringify(speech.rawQuoteVariables)), ["provider_quote"]);
  const allFlowSpeech = findQuoteSpeechProtections(nodes, edges);
  assert.equal(hasQuotePrivateSpeech("Use {{private_checkout_url}}", allFlowSpeech), true);
  assert.equal(hasQuotePrivateSpeech("Use {{private_checkout_url.host}}", allFlowSpeech), true);
  assert.equal(hasQuotePrivateSpeech("Use {{quote_fingerprint}}", allFlowSpeech), true);
  assert.equal(hasQuotePrivateSpeech("Use {{provider_quote}}", allFlowSpeech), true);
  assert.equal(hasQuotePrivateSpeech("Visit https://checkout.example.test/x", allFlowSpeech), true);
  assert.equal(hasQuotePrivateSpeech("Your total is {{stay_total}}", allFlowSpeech), false);
  assert.equal(hasQuotePrivateSpeech("Visit https://help.example.test", { privateVariables: [], fingerprintVariables: [], rawQuoteVariables: [] }), false);
});

test("every human-facing flow prompt panel uses shared graph-derived quote privacy", () => {
  for (const relative of [
    "components/flow-editor/inspectors/InitialNodePanel.tsx",
    "components/flow-editor/inspectors/CollectSlotNodePanel.tsx",
    "components/flow-editor/inspectors/CollectFormNodePanel.tsx",
    "components/flow-editor/inspectors/TransferNodePanel.tsx",
    "components/flow-editor/inspectors/EndNodePanel.tsx",
    "components/flow-editor/inspectors/MessageNodePanel.tsx",
    "components/flow-editor/inspectors/ConfirmationNodePanel.tsx",
    "components/flow-editor/inspectors/APIRequestNodePanel.tsx",
    "components/flow-editor/inspectors/APIResponseNodePanel.tsx",
    "components/flow-editor/inspectors/CapabilityNodePanel.tsx",
    "components/flow-editor/inspectors/OptionPickerNodePanel.tsx",
    "components/flow-editor/FlowToolbar.tsx",
  ]) {
    const source = fs.readFileSync(path.join(__dirname, "..", relative), "utf8");
    assert.match(source, /useQuoteSpeechPrivacy|findQuoteSpeechProtections|findQuoteConfirmationContext/, relative);
  }
});

test("quote editor emits exact canonical output paths, no defaults, and public-only projection", () => {
  const {
    DEFAULT_QUOTE_POLICY,
    REQUIRED_QUOTE_FIELDS,
    buildQuoteResponseBindings,
  } = loadQuoteEditor();
  const bindings = buildQuoteResponseBindings(DEFAULT_QUOTE_POLICY);
  const mapping = JSON.parse(JSON.stringify(bindings.responseMapping));
  assert.equal(Object.keys(mapping).length, 15);
  for (const path of REQUIRED_QUOTE_FIELDS) {
    const variable = DEFAULT_QUOTE_POLICY.publicConfirmationFields[path];
    assert.equal(mapping[variable], `$.public.${path}`);
  }
  assert.equal(mapping[DEFAULT_QUOTE_POLICY.fingerprintVariable], "$.fingerprint");
  assert.equal(mapping[DEFAULT_QUOTE_POLICY.privateUrlVariable], "$.private.checkout_url");
  assert.equal(bindings.responseVariables.some((entry) => Object.hasOwn(entry, "defaultValue")), false);
  const projection = bindings.responseProjection.fields.map((field) => field.variable);
  assert.equal(projection.includes(DEFAULT_QUOTE_POLICY.fingerprintVariable), false);
  assert.equal(projection.includes(DEFAULT_QUOTE_POLICY.privateUrlVariable), false);
  assert.equal(projection.length, 13);
});

test("quote policy helpers require typed quote and expected objects and immutable origins", () => {
  const {
    DEFAULT_QUOTE_ARGUMENTS,
    DEFAULT_QUOTE_POLICY,
    validateQuoteArgumentsTemplate,
    validateAllowedCheckoutOrigins,
    isSafeFlowVariableKey,
  } = loadQuoteEditor();
  assert.equal(validateQuoteArgumentsTemplate(DEFAULT_QUOTE_ARGUMENTS), null);
  assert.equal(validateQuoteArgumentsTemplate('{"quote":{{quote}},"expected":{{selection}},"price":2}')?.includes("exactly two"), true);
  assert.equal(validateQuoteArgumentsTemplate('{"quote":"{{quote}}","expected":{}}')?.includes("typed JSON object"), true);
  const origins = validateAllowedCheckoutOrigins("https://bookings.example.com\nhttps://pay.example.org");
  assert.equal(origins.error, undefined);
  assert.deepEqual(JSON.parse(JSON.stringify(origins.origins)), ["https://bookings.example.com", "https://pay.example.org"]);
  assert.ok(validateAllowedCheckoutOrigins("https://example.com/checkout").error);
  assert.ok(validateAllowedCheckoutOrigins("http://example.com").error);
  assert.equal(isSafeFlowVariableKey("__native_quote"), false);
  assert.equal(isSafeFlowVariableKey(DEFAULT_QUOTE_POLICY.fingerprintVariable), true);
});

test("saved SMS/email quote delivery requires one private-link token and exact typed recipient", () => {
  const {
    defaultQuoteDeliveryTemplate,
    validateQuoteDeliveryTemplate,
  } = loadQuoteEditor();
  const smsTemplate = defaultQuoteDeliveryTemplate("SEND_SMS", "caller_phone", "private_checkout_url");
  assert.equal(validateQuoteDeliveryTemplate(smsTemplate, "SEND_SMS", "caller_phone", "private_checkout_url"), null);
  const emailTemplate = defaultQuoteDeliveryTemplate("SEND_EMAIL", "caller_email", "private_checkout_url");
  assert.equal(validateQuoteDeliveryTemplate(emailTemplate, "SEND_EMAIL", "caller_email", "private_checkout_url"), null);
  assert.ok(validateQuoteDeliveryTemplate(smsTemplate.replace("{{private_checkout_url}}", "plain text"), "SEND_SMS", "caller_phone", "private_checkout_url"));
  assert.ok(validateQuoteDeliveryTemplate(smsTemplate.replace("{{caller_phone}}", "{{different_phone}}"), "SEND_SMS", "caller_phone", "private_checkout_url"));
  assert.ok(validateQuoteDeliveryTemplate(smsTemplate.replace("Review your selected reservation:", "Visit https://other.example/page"), "SEND_SMS", "caller_phone", "private_checkout_url"));
  assert.ok(validateQuoteDeliveryTemplate(emailTemplate.replace("Your reservation quote", "{{private_checkout_url}}"), "SEND_EMAIL", "caller_email", "private_checkout_url"));
});

test("MCP Flow grants serialize strict account/property scope and readonly subsets", () => {
  const { buildMCPGrantConnectionConfig, nativeFlowToolAccess, displayMCPServerHost } = loadMCPNativePolicy();
  assert.deepEqual(
    JSON.parse(JSON.stringify(buildMCPGrantConnectionConfig({
      scope: "property",
      propertyId: "property-uuid-7",
      enabledTools: ["search", "reserve"],
      readOnlyTools: ["search"],
    }))),
    {
      ok: true,
      connectionConfig: {
        property_id: "property-uuid-7",
        native_enabled_tools: ["search", "reserve"],
        native_read_only_tools: ["search"],
      },
    },
  );
  assert.deepEqual(
    JSON.parse(JSON.stringify(buildMCPGrantConnectionConfig({
      scope: "account",
      propertyId: "ignored-property",
      enabledTools: ["search"],
      readOnlyTools: [],
    }))),
    {
      ok: true,
      connectionConfig: {
        account_global: true,
        native_enabled_tools: ["search"],
        native_read_only_tools: [],
      },
    },
  );
  assert.equal(buildMCPGrantConnectionConfig({
    scope: "property", propertyId: "", enabledTools: ["search"], readOnlyTools: [],
  }).ok, false);
  assert.equal(buildMCPGrantConnectionConfig({
    scope: "account", propertyId: "", enabledTools: [], readOnlyTools: [],
  }).ok, false);
  assert.equal(buildMCPGrantConnectionConfig({
    scope: "account", propertyId: "", enabledTools: ["write"], readOnlyTools: ["other"],
  }).ok, false);
  const policy = { configured: true, scope: "property", property_id: "property-uuid-7", enabled_tools: ["search", "reserve"], read_only_tools: ["search"] };
  assert.equal(nativeFlowToolAccess(policy, "search"), "read_only");
  assert.equal(nativeFlowToolAccess(policy, "reserve"), "write");
  assert.equal(nativeFlowToolAccess({ ...policy, configured: false }, "reserve"), "unavailable");
  assert.equal(nativeFlowToolAccess(policy, "not-granted"), "unavailable");
  assert.equal(displayMCPServerHost("https://agent:secret@mcp.example.test:8443/mcp?token=hidden"), "mcp.example.test:8443");
  assert.equal(displayMCPServerHost("not-a-url-with-secrets"), "Endpoint saved");
});

test("MCP management UI uses the safe DTO, explicit grants and manager-only provider actions", () => {
  const root = path.join(__dirname, "..");
  const modal = fs.readFileSync(path.join(root, "app/(dashboard)/dashboard/integrations/components/MCPModal.tsx"), "utf8");
  const page = fs.readFileSync(path.join(root, "app/(dashboard)/dashboard/integrations/page.tsx"), "utf8");
  const card = fs.readFileSync(path.join(root, "app/(dashboard)/dashboard/integrations/components/MCPConnectionCard.tsx"), "utf8");
  const sourcePanel = fs.readFileSync(path.join(root, "components/flow-editor/inspectors/NativeSourceBindingPanel.tsx"), "utf8");
  assert.match(modal, /submitFreshGrant/);
  assert.match(modal, /payload\.connection_config = grant\.connectionConfig/);
  assert.doesNotMatch(modal, /editingMcp\.connection_config|encrypted_grant|sealed_grant|error\.detail/);
  assert.match(page, /canPerm\("integrations", "view"\)/);
  assert.match(page, /canPerm\("integrations", "manage"\)/);
  assert.match(card, /native_flow_policy/);
  assert.doesNotMatch(card, />\s*\{mcp\.last_error\}/);
  assert.match(sourcePanel, /nativeFlowToolAccess/);
  assert.match(sourcePanel, /runtime authorization and property scope are rechecked/);
  assert.doesNotMatch(sourcePanel, /connection_config|encrypted_grant|sealed_grant/);
});

test("native-only validator stays in flow catalogs but is excluded from standalone Capability Tool creation", () => {
  const root = path.join(__dirname, "..");
  const standalone = fs.readFileSync(path.join(root, "app/(dashboard)/dashboard/tools/components/tool-types/CapabilityForm.tsx"), "utf8");
  const nativeNode = fs.readFileSync(path.join(root, "components/flow-editor/inspectors/CapabilityNodePanel.tsx"), "utf8");
  const nativeBinding = fs.readFileSync(path.join(root, "components/flow-editor/inspectors/NativeSourceBindingPanel.tsx"), "utf8");
  assert.match(standalone, /!capability\.native_flow_only/);
  assert.match(standalone, /native Flow-only and cannot be created as a standalone Capability Tool/);
  assert.match(nativeNode, /capabilities\.map\(\(c\)/);
  assert.match(nativeNode, /c\.native_flow_only \? " · native Flow only"/);
  assert.match(nativeBinding, /capabilities\.map\(\(capability\)/);
});

test("pure response preview payload keeps exact declarations, mappings and projection", () => {
  const { buildResponsePreviewPayload } = loadResponsePreview();
  const sample = { total: 0, accepted: false, items: [{ id: "A" }] };
  const configuration = {
    responseMapping: { items: "$.items" },
    responseVariables: [{ variableKey: "total", jsonPath: "$.total", defaultValue: 0 }],
    responseProjection: { fields: [{ variable: "items" }, { variable: "total" }] },
  };
  const declarations = [{ key: "total", type: "number", required: false }];
  assert.deepEqual(
    JSON.parse(JSON.stringify(buildResponsePreviewPayload(sample, configuration, declarations))),
    {
      sample,
      configuration,
      variableDeclarations: declarations,
    },
  );
});

test("response preview uses the owned sample-only route and returns exact raw/model values", async () => {
  const { previewMappedResponse } = loadResponsePreview();
  const calls = [];
  const result = await previewMappedResponse({
    authFetch: async (url, options) => {
      calls.push({ url, options });
      return new Response(JSON.stringify({
        mapped_variables: { total: 0, confirmed: false, rooms: [{ code: "S" }] },
        llm_data: { total: 0, confirmed: false, rooms: [{ code: "S" }] },
      }), { status: 200 });
    },
    toolId: "flow-tool-1",
    accountId: "account-1",
    sample: { response: true },
    configuration: { responseMapping: { total: "$.total" } },
    variableDeclarations: [{ key: "total", type: "number", description: "", required: false }],
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/tools/flow-tool-1/flow/preview-response?account_id=account-1");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(result.mapped_variables, { total: 0, confirmed: false, rooms: [{ code: "S" }] });
  assert.deepEqual(result.llm_data, { total: 0, confirmed: false, rooms: [{ code: "S" }] });
});

test("response preview errors are fixed and financial projection cleanup is refused", async () => {
  const { previewMappedResponse, looksFinancialVariable } = loadResponsePreview();
  await assert.rejects(previewMappedResponse({
    authFetch: async () => new Response(JSON.stringify({
      detail: { code: "mapping_projection", secret: "must-not-render" },
    }), { status: 422 }),
    toolId: "flow-tool-1",
    accountId: "account-1",
    sample: {},
    configuration: {},
    variableDeclarations: [],
  }), (error) => {
    assert.equal(error.message, "Preview unavailable (mapping_projection).");
    assert.doesNotMatch(error.message, /must-not-render/);
    return true;
  });
  assert.equal(looksFinancialVariable("nightly_rate"), true);
  assert.equal(looksFinancialVariable("booking_total"), true);
  assert.equal(looksFinancialVariable("guest_name"), false);
});

function createStore() {
  const reactFlow = {
    addEdge: (_connection, edges) => edges,
    applyNodeChanges: (_changes, nodes) => nodes,
    applyEdgeChanges: (_changes, edges) => edges,
  };
  const accountContext = { getAccountContext: () => null };
  const storeModule = loadModule("components/flow-editor/store.ts", {
    zustand: {
      create: initializer => {
        let state;
        const set = patch => { state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) }; };
        const get = () => state;
        state = initializer(set, get);
        return Object.assign(selector => selector ? selector(state) : state, { getState: get, setState: set });
      },
      ...reactFlow,
    },
    "@xyflow/react": reactFlow,
    "@/lib/auth/accountContext": accountContext,
    "./flowEditorData": loadFlowEditorData(),
  }, {
    window: { localStorage: { getItem: () => "unit-test-auth-token" } },
    localStorage: { getItem: () => "unit-test-auth-token" },
    fetch: (...args) => global.fetch(...args),
  });
  return storeModule.useFlowStore;
}

test("renaming typed quote variables updates delivery, protected bindings and round-trips through save/reload", async () => {
  const store = createStore();
  const previousFetch = global.fetch;
  let savedFlowConfig;
  global.fetch = async (url, options = {}) => {
    if (options.method === "PUT") {
      savedFlowConfig = JSON.parse(options.body).flow_config;
      return new Response(JSON.stringify({ version_number: 4, version_id: "draft-4" }));
    }
    if (String(url).includes("/flow/versions?")) {
      return new Response(JSON.stringify({ versions: [], published_version_number: 0, has_draft: true }));
    }
    if (String(url).includes("/flow?")) {
      return new Response(JSON.stringify({ flow_config: savedFlowConfig, source: "draft", version_number: 4 }));
    }
    throw new Error(`Unexpected flow request: ${url}`);
  };
  try {
    store.setState({
      toolId: "rename-tool",
      accountId: "rename-account",
      variables: [
        "caller_email", "stay_total", "quote_fingerprint", "private_checkout_url",
        "provider_quote", "selected_option",
      ].map((key) => ({ key, type: "text", required: false })),
      nodes: [
        {
          id: "quote", type: "capability", position: { x: 0, y: 0 }, data: {
            name: "Quote",
            api: {
              apiSource: "capability",
              capability: "validate_reservation_quote",
              argumentsTemplate: '{\n  "quote": {{provider_quote}},\n  "expected": {{selected_option}}\n}',
              quotePolicy: {
                fingerprintVariable: "quote_fingerprint",
                privateUrlVariable: "private_checkout_url",
                publicConfirmationFields: { room_id: "room_id", "pricing.total": "stay_total" },
              },
              responseMapping: { stay_total: "$.public.pricing.total" },
              responseProjection: { fields: [{ variable: "stay_total" }] },
            },
          },
        },
        {
          id: "sender", type: "api_request", position: { x: 1, y: 1 }, data: {
            api: {
              apiSource: "tool",
              argumentsTemplate: '{"recipient":"{{caller_email}}","body":"{{private_checkout_url}}"}',
              quoteDelivery: { quoteNodeId: "quote", recipientVariable: "caller_email" },
            },
          },
        },
      ],
      edges: [{ id: "quote-send", source: "quote", target: "sender" }],
      globalPrompt: "",
    });
    for (const [oldKey, newKey] of [
      ["caller_email", "confirmed_email"],
      ["stay_total", "booking_total"],
      ["quote_fingerprint", "booking_fingerprint"],
      ["private_checkout_url", "private_quote_url"],
      ["provider_quote", "normalized_quote"],
    ]) {
      store.getState().updateVariable(oldKey, { key: newKey });
    }
    const quote = store.getState().nodes.find((node) => node.id === "quote").data.api;
    const sender = store.getState().nodes.find((node) => node.id === "sender").data.api;
    assert.equal(sender.quoteDelivery.recipientVariable, "confirmed_email");
    assert.match(sender.argumentsTemplate, /\{\{confirmed_email\}\}/);
    assert.match(sender.argumentsTemplate, /\{\{private_quote_url\}\}/);
    assert.equal(quote.quotePolicy.fingerprintVariable, "booking_fingerprint");
    assert.equal(quote.quotePolicy.privateUrlVariable, "private_quote_url");
    assert.equal(quote.quotePolicy.publicConfirmationFields["pricing.total"], "booking_total");
    assert.equal(quote.quotePolicy.publicConfirmationFields.booking_total, undefined, "canonical path keys stay immutable");
    assert.equal(quote.responseMapping.booking_total, "$.public.pricing.total");
    assert.equal(quote.responseProjection.fields[0].variable, "booking_total");
    assert.match(quote.argumentsTemplate, /\{\{normalized_quote\}\}/);

    await store.getState().saveFlow();
    assert.equal(savedFlowConfig.nodes.find((node) => node.id === "sender").data.api.quoteDelivery.recipientVariable, "confirmed_email");
    await store.getState().loadFlow("rename-tool", "rename-account");
    const reloaded = store.getState().nodes.find((node) => node.id === "sender").data.api;
    assert.equal(reloaded.quoteDelivery.recipientVariable, "confirmed_email");
    assert.match(reloaded.argumentsTemplate, /\{\{confirmed_email\}\}/);
    assert.match(reloaded.argumentsTemplate, /\{\{private_quote_url\}\}/);
  } finally {
    global.fetch = previousFetch;
  }
});

test("node measurements and selection preserve published cleanliness while graph edits require saving", () => {
  const store = createStore();
  store.getState().setIsDirty(false);
  for (const changes of [
    [{ id: "query", type: "dimensions", dimensions: { width: 240, height: 180 } }],
    [{ id: "query", type: "select", selected: true }],
  ]) {
    store.getState().onNodesChange(changes);
    assert.equal(store.getState().isDirty, false, changes[0].type);
  }
  store.getState().onEdgesChange([{ id: "start-q", type: "select", selected: true }]);
  assert.equal(store.getState().isDirty, false);
  store.getState().onNodesChange([{ id: "query", type: "position", position: { x: 40, y: 200 } }]);
  assert.equal(store.getState().isDirty, true);
  store.getState().onNodesChange([{ id: "query", type: "select", selected: false }]);
  assert.equal(store.getState().isDirty, true, "selection must not discard an actual edit");
  store.getState().setIsDirty(false);
  store.getState().onEdgesChange([{ id: "start-q", type: "remove" }]);
  assert.equal(store.getState().isDirty, true);
});

test("flow toolbar history restores graph edits and starts a clean scope on load", async () => {
  const store = createStore();
  store.getState().setToolId("history-tool");
  store.getState().setHotelId("history-account");
  store.getState().addNode("message", { x: 10, y: 20 });
  assert.equal(store.getState().nodes.length, 1);
  assert.equal(store.getState().canUndo, true);
  store.getState().undoFlow();
  assert.equal(store.getState().nodes.length, 0);
  assert.equal(store.getState().canRedo, true);
  store.getState().redoFlow();
  assert.equal(store.getState().nodes.length, 1);
  await store.getState().loadFlow("history-tool", "history-account");
  assert.equal(store.getState().canUndo, false);
  assert.equal(store.getState().canRedo, false);
});

test("late version history cannot restore a cleared tool or overwrite another tool", async () => {
  const store = createStore();
  const previousFetch = global.fetch;
  let finish;
  global.fetch = () => new Promise(resolve => { finish = resolve; });
  try {
    store.setState({
      toolId: "tool-a", accountId: "account-a", versions: [{ version_number: 1 }],
    });
    const oldHistory = store.getState().loadVersions();
    store.getState().clearFlow();
    const clearedVersions = store.getState().versions;
    store.setState({
      toolId: "tool-b", accountId: "account-b", publishedVersionNumber: 3,
      hasDraft: false, versions: [{ version_number: 3 }],
    });
    finish(new Response(JSON.stringify({
      versions: [{ version_number: 99 }], published_version_number: 99, has_draft: true,
    })));
    await oldHistory;
    assert.deepEqual(JSON.parse(JSON.stringify({
      clearedVersions,
      versions: store.getState().versions,
      published: store.getState().publishedVersionNumber,
      draft: store.getState().hasDraft,
    })), {
      clearedVersions: [], versions: [{ version_number: 3 }], published: 3, draft: false,
    });
  } finally { global.fetch = previousFetch; }
});

test("newer version history wins over a slower request for the same tool", async () => {
  const store = createStore();
  const previousFetch = global.fetch;
  const pending = [];
  global.fetch = () => new Promise(resolve => { pending.push(resolve); });
  try {
    store.setState({ toolId: "tool-a", accountId: "account-a" });
    const older = store.getState().loadVersions();
    const newer = store.getState().loadVersions();
    pending[1](new Response(JSON.stringify({
      versions: [{ version_number: 5 }], published_version_number: 5, has_draft: true,
    })));
    await newer;
    pending[0](new Response(JSON.stringify({
      versions: [{ version_number: 4 }], published_version_number: 4, has_draft: false,
    })));
    await older;
    assert.equal(store.getState().publishedVersionNumber, 5);
    assert.equal(store.getState().hasDraft, true);
  } finally { global.fetch = previousFetch; }
});

for (const action of ["discardDraft", "revertToVersion"]) {
  test(`${action} cannot reload a tool after the editor has been cleared`, async () => {
    const store = createStore();
    const previousFetch = global.fetch;
    const requests = [];
    let finish;
    global.fetch = url => {
      requests.push(url);
      if (requests.length === 1) return new Promise(resolve => { finish = resolve; });
      return Promise.resolve(new Response(JSON.stringify({
        flow_config: { nodes: [], edges: [], variables: [] },
        source: "published", version_number: 1, version_id: "stale-version",
      })));
    };
    try {
      store.setState({ toolId: "tool-a", accountId: "account-a" });
      const operation = store.getState()[action](1);
      store.getState().clearFlow();
      finish(new Response("{}"));
      await operation;
      assert.equal(store.getState().toolId, null);
      assert.equal(store.getState().currentVersionId, null);
      assert.equal(store.getState().isLoading, false);
      assert.equal(requests.length, 1);
      // The same protection must still permit an ordinary current-tool action.
      global.fetch = async (url, options = {}) => new Response(JSON.stringify(
        ["POST", "DELETE"].includes(options.method) ? {} :
          url.includes("/flow/versions?") ? {
            versions: [], published_version_number: 7, has_draft: false,
          } : {
            flow_config: { nodes: [], edges: [], variables: [] },
            source: "published", version_number: 7, version_id: "current-tool-b",
            published_version_number: 7,
          },
      ));
      store.setState({ toolId: "tool-b", accountId: "account-b" });
      await store.getState()[action](1);
      assert.equal(store.getState().toolId, "tool-b");
      assert.equal(store.getState().currentVersionId, "current-tool-b");
      assert.equal(store.getState().isLoading, false);
    } finally { global.fetch = previousFetch; }
  });
}

test("store tracks version identity through load, save, publish, empty and failed cross-tool load", async () => {
  const store = createStore();
  const previousFetch = global.fetch;
  let mode = "load";
  global.fetch = async (url, options = {}) => {
    if (url.includes("/flow/versions")) {
      return new Response(JSON.stringify({ versions: [], published_version_number: 13, has_draft: false }));
    }
    if (url.includes("&version=")) {
      return new Response(JSON.stringify({
        flow_config: { nodes: [], edges: [], variables: [] },
        source: "published",
        version_number: 11,
        version_id: "historical-11",
      }));
    }
    if (options.method === "PUT") {
      return new Response(JSON.stringify({ version_number: 13, version_id: "draft-13" }));
    }
    if (options.method === "POST") {
      return new Response(JSON.stringify({ version_number: 14, version_id: "published-14" }));
    }
    if (mode === "fail") return new Response(JSON.stringify({ detail: "load failed" }), { status: 500 });
    if (mode === "empty") return new Response(JSON.stringify({ flow_config: null }));
    return new Response(JSON.stringify({
      flow_config: { nodes: [], edges: [], variables: [] },
      source: "published",
      version_number: 12,
      version_id: "loaded-12",
      published_version_number: 12,
      has_published: true,
    }));
  };

  try {
    assert.equal(store.getState().currentVersionId, null);
    await store.getState().loadFlow("tool-a", "account-a");
    assert.equal(store.getState().currentVersionId, "loaded-12");
    await store.getState().loadVersion(11);
    assert.equal(store.getState().currentVersionId, "historical-11");
    assert.equal(store.getState().currentVersionNumber, 11);
    await store.getState().loadFlow("tool-a", "account-a");
    await store.getState().saveFlow();
    assert.equal(store.getState().currentVersionId, "draft-13");
    await store.getState().publishFlow();
    assert.equal(store.getState().currentVersionId, "published-14");

    mode = "empty";
    await store.getState().loadFlow("tool-b", "account-a");
    assert.equal(store.getState().currentVersionId, null);

    mode = "load";
    await store.getState().loadFlow("tool-a", "account-a");
    assert.equal(store.getState().currentVersionId, "loaded-12");
    mode = "fail";
    await store.getState().loadFlow("tool-b", "account-a");
    assert.equal(store.getState().currentVersionId, null);

    await store.getState().loadFlow("tool-a", "account-a");
    store.getState().clearFlow();
    assert.equal(store.getState().currentVersionId, null);
  } finally {
    global.fetch = previousFetch;
  }
});

test("clearFlow invalidates a pending flow response so it cannot restore stale identity", async () => {
  const store = createStore();
  const previousFetch = global.fetch;
  let resolveFetch;
  global.fetch = () => new Promise(resolve => { resolveFetch = resolve; });
  try {
    const pendingLoad = store.getState().loadFlow("tool-pending", "account-a");
    await new Promise(resolve => setImmediate(resolve));
    store.getState().clearFlow();
    resolveFetch(new Response(JSON.stringify({
      flow_config: { nodes: [], edges: [], variables: [] },
      source: "published",
      version_number: 4,
      version_id: "stale-version-4",
      published_version_number: 4,
    })));
    await pendingLoad;
    assert.equal(store.getState().currentVersionId, null);
    assert.equal(store.getState().toolId, null);
    assert.equal(store.getState().isLoading, false);
  } finally {
    global.fetch = previousFetch;
  }
});
