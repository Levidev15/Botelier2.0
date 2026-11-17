// Real password/MFA, publisher, SQLAlchemy and native SDK behind test-only IPC.
// Dashboard shell metadata and external model/API transports are synthetic.
const { expect, test } = require("@playwright/test");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { connectEditorFixture, fixtureInvocation } = require("../editor-rpc.cjs");

const baseURL = "http://127.0.0.1:5011";
const repo = path.resolve(__dirname, "../../../..");
let bridge;
let fixture;
let child;

test.beforeEach(async () => {
  const invocation = fixtureInvocation({
    repo,
    ci: process.env.EDITOR_CI === "1",
    image: process.env.EDITOR_CANDIDATE_IMAGE,
    testTools: process.env.EDITOR_TEST_TOOLS,
    pythonPath: process.env.EDITOR_PYTHONPATH,
    packageRoot: process.env.EDITOR_PACKAGE_ROOT,
    fixtureProfile: "v1-browser",
    path: process.env.PATH,
  });
  child = spawn(invocation.command, invocation.args, {
    env: invocation.env, stdio: ["pipe", "pipe", "inherit"],
  });
  bridge = connectEditorFixture(child, { timeoutMs: 45_000 });
  fixture = await bridge.ready;
  expect(fixture.scope).toBe("test_only_editor_leaf_routes_not_main_app_startup");
  expect(fixture.profile).toBe("v1-browser");
});

test.afterEach(async () => {
  if (bridge) {
    const result = await bridge.close();
    expect(result.blocked_attempts).toBe(0);
    console.log("EDITOR_BROWSER_GUARD_BLOCKED_ATTEMPTS=0");
  } else if (child && child.exitCode === null) {
    child.kill("SIGTERM");
  }
  bridge = undefined;
  child = undefined;
});

async function routeBrowser(page, { integrationsManage = true, mcpConfigured = false } = {}) {
  const observed = {
    real: [], mocked: [], unexpected: [], responses: [], pageErrors: [],
    mcpRequests: [], mcpTestCalls: 0, mcpDtos: [], simulationRequests: [],
  };
  let mcpDto = {
    id: "synthetic-mcp-connection",
    account_id: fixture.account_id,
    name: "Synthetic inventory server",
    description: "Safe catalog fixture",
    server_url: "https://mcp.synthetic.invalid/private-path?test_only=checkpoint",
    transport_type: "streamable_http",
    auth_type: "none",
    status: "connected",
    is_active: true,
    discovered_tools: [
      {
        name: "inventory_lookup",
        description: "Read-only fixture lookup",
        parameters: {
          type: "object",
          properties: { room: { type: "string", description: "Room identifier" } },
          required: ["room"],
        },
      },
      {
        name: "inventory_adjust",
        description: "Writable fixture action",
        parameters: {
          type: "object",
          properties: { quantity: { type: "number", description: "Quantity" } },
          required: ["quantity"],
        },
      },
    ],
    native_flow_policy: mcpConfigured
      ? {
        configured: true,
        scope: "property",
        property_id: "property-synthetic-21",
        enabled_tools: ["inventory_lookup", "inventory_adjust"],
        read_only_tools: ["inventory_lookup"],
      }
      : {
        configured: false,
        scope: null,
        property_id: null,
        enabled_tools: [],
        read_only_tools: [],
      },
  };
  const safeMcpDto = () => JSON.parse(JSON.stringify(mcpDto));
  const apiTools = {
    tools: [
      {
        id: "synthetic-saved-api",
        name: "Fixture availability API",
        description: "Read-only synthetic API binding",
        tool_type: "API_REQUEST",
        config: { parameters: { check_in: { type: "string", required: true } } },
      },
      {
        id: "synthetic-sms-sender",
        name: "Synthetic SMS sender",
        description: "Text-only fixture sender",
        tool_type: "SEND_SMS",
        config: {},
      },
      {
        id: "synthetic-email-sender",
        name: "Synthetic email sender",
        description: "Text-only fixture sender",
        tool_type: "SEND_EMAIL",
        config: {},
      },
    ],
  };
  const capabilities = [
    {
      name: "search_availability",
      description: "Synthetic availability lookup.",
      parameters: { check_in: { type: "string", description: "Arrival date" } },
      required: ["check_in"],
      mutating: false,
      service_backed: true,
      native_flow_only: false,
    },
    {
      name: "validate_reservation_quote",
      description: "Pure reservation quote validation.",
      parameters: {
        quote: { type: "object", description: "Provider quote" },
        expected: { type: "object", description: "Caller-selected values" },
      },
      required: ["quote", "expected"],
      mutating: false,
      service_backed: false,
      native_flow_only: true,
    },
  ];
  const integrations = [{
    id: "00000000-0000-0000-0000-000000000103",
    integration_type_id: "synthetic-stay-api",
    connection_name: "Fixture Stay API",
    status: "connected",
    integration_type: {
      id: "synthetic-stay-api",
      name: "Synthetic Stay API",
      slug: "synthetic_stay",
      origin: "customer_imported",
      endpoints: [{
        id: "editor-fixture-endpoint",
        name: "Fixture availability",
        method: "GET",
        path: "/availability",
        description: "Read-only fixture endpoint",
        variables: [{ key: "check_in", type: "date", required: true }],
        query_params: [{ key: "check_in", value: "{{check_in}}", required: true }],
        response_mapping: { rooms: "$.rooms", quote: "$.quote" },
      }],
    },
  }];
  const recordTypes = [{
    ...fixture.browser_fixtures.record_type,
    created_at: null,
    updated_at: null,
  }];
  page.on("pageerror", error => observed.pageErrors.push(error.message));
  await page.route("**/*", async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== baseURL) return route.abort("blockedbyclient");
    if (!url.pathname.startsWith("/api/")) return route.continue();
    // NextAuth's own anonymous session endpoint remains on the actual frontend.
    if (url.pathname === "/api/auth/session") return route.continue();
    const flowPrefix = `/api/tools/${fixture.tool_id}/flow`;
    if (url.pathname === "/api/auth/login" ||
        url.pathname.startsWith("/api/auth/mfa/") ||
        url.pathname === flowPrefix || url.pathname.startsWith(flowPrefix + "/") ||
        url.pathname.startsWith("/api/simulate/")) {
      const incoming = await request.allHeaders();
      const headers = {};
      for (const key of ["authorization", "origin", "x-mfa-csrf", "content-type"]) {
        if (incoming[key]) headers[key] = incoming[key];
      }
      // Forward the actual browser-issued MFA cookie, not unrelated NextAuth
      // cookies. Never manufacture an Origin, CSRF header, cookie or token.
      const mfaCookie = (incoming.cookie || "").split(";")
        .map(value => value.trim()).find(value => value.startsWith("botelier_mfa_session="));
      if (mfaCookie) headers.cookie = mfaCookie;
      const body = request.postData() ? request.postDataJSON() : undefined;
      if (url.pathname === "/api/simulate/message" && body && typeof body === "object") {
        const previewResult = body.preview_result;
        observed.simulationRequests.push({
          message: body.message,
          previewResult: previewResult && typeof previewResult === "object"
            ? {
              requestId: previewResult.request_id,
              statusCode: previewResult.status_code,
              dataJson: previewResult.data_json,
              ...(Object.hasOwn(previewResult, "success")
                ? { success: previewResult.success }
                : {}),
              ...(Object.hasOwn(previewResult, "error_type")
                ? { errorType: previewResult.error_type }
                : {}),
              hasParsedData: Object.hasOwn(previewResult, "data"),
            }
            : null,
        });
      }
      const result = await bridge.request({
        method: request.method(), path: url.pathname + url.search, headers, body,
      });
      observed.real.push({ path: url.pathname, method: request.method() });
      // Deliberately keep credentials/cookies out of recorded result evidence.
      if (url.pathname === "/api/simulate/start" || url.pathname === "/api/simulate/message" ||
          url.pathname === flowPrefix || url.pathname === flowPrefix + "/publish") {
        observed.responses.push({ path: url.pathname, status: result.status, body: result.body });
      }
      const responseHeaders = {};
      for (const [key, value] of result.headers) {
        if (["content-length", "transfer-encoding", "content-encoding"].includes(key.toLowerCase())) continue;
        responseHeaders[key] = responseHeaders[key] ? `${responseHeaders[key]}\n${value}` : value;
      }
      return route.fulfill({
        status: result.status, headers: responseHeaders, body: JSON.stringify(result.body),
      });
    }

    // Read-only account catalogs used by the real editor. The flow/auth/
    // version/preview execution boundary above is never mocked here.
    if (request.method() === "GET" && url.pathname === "/api/capabilities") {
      observed.mocked.push({ path: url.pathname, method: request.method(), purpose: "capability catalog" });
      return route.fulfill({ json: capabilities });
    }
    if (request.method() === "GET" && url.pathname === "/api/integrations/connections") {
      observed.mocked.push({ path: url.pathname, method: request.method(), purpose: "integration catalog" });
      return route.fulfill({ json: integrations });
    }
    if (request.method() === "GET" && url.pathname === `/api/secrets/account/${fixture.account_id}`) {
      observed.mocked.push({ path: url.pathname, method: request.method(), purpose: "secret names only" });
      return route.fulfill({ json: [] });
    }
    if (request.method() === "GET" && url.pathname === `/api/record-types`) {
      observed.mocked.push({ path: url.pathname, method: request.method(), purpose: "Record type catalog" });
      return route.fulfill({ json: recordTypes });
    }
    if (request.method() === "GET" && url.pathname === "/api/tools") {
      observed.mocked.push({ path: url.pathname, method: request.method(), purpose: "saved Tool catalog" });
      return route.fulfill({ json: apiTools });
    }
    if (
      request.method() === "GET" &&
      url.pathname === `/api/assistants/${fixture.assistant_id}/greeting-cache-status`
    ) {
      observed.mocked.push({ path: url.pathname, method: request.method(), purpose: "read-only greeting cache status" });
      return route.fulfill({
        json: { cached: false, cached_at: null, text_matches_cache: false, outdated: false, supported: true },
      });
    }
    if (url.pathname === "/api/mcp-connections" && request.method() === "GET") {
      observed.mocked.push({ path: url.pathname, method: request.method(), purpose: "safe MCP DTO catalog" });
      const result = [safeMcpDto()];
      observed.mcpDtos.push(result);
      return route.fulfill({ json: result });
    }
    if (url.pathname === "/api/mcp-connections/synthetic-mcp-connection/test") {
      observed.mcpTestCalls += 1;
      return route.fulfill({ status: 403, json: { detail: "Explicit provider tests are disabled in this browser fixture." } });
    }
    if (url.pathname === "/api/mcp-connections/synthetic-mcp-connection" && request.method() === "PUT") {
      const payload = request.postDataJSON();
      observed.mcpRequests.push({ method: "PUT", payload });
      const sensitive = ["server_url", "transport_type", "auth_type", "credentials"]
        .some((key) => Object.hasOwn(payload, key));
      if (!integrationsManage && sensitive) {
        return route.fulfill({ status: 403, json: { detail: "Manager permission required." } });
      }
      if (typeof payload.name === "string") mcpDto.name = payload.name;
      if (typeof payload.description === "string" || payload.description === null) {
        mcpDto.description = payload.description || "";
      }
      if (typeof payload.server_url === "string") mcpDto.server_url = payload.server_url;
      if (sensitive && !Object.hasOwn(payload, "connection_config")) {
        mcpDto.native_flow_policy = {
          configured: false, scope: null, property_id: null, enabled_tools: [], read_only_tools: [],
        };
      }
      if (Object.hasOwn(payload, "connection_config")) {
        const grant = payload.connection_config;
        const property = typeof grant.property_id === "string";
        const account = grant.account_global === true;
        if (
          !integrationsManage ||
          property === account ||
          !Array.isArray(grant.native_enabled_tools) ||
          !Array.isArray(grant.native_read_only_tools) ||
          grant.native_read_only_tools.some((tool) => !grant.native_enabled_tools.includes(tool))
        ) {
          return route.fulfill({ status: 400, json: { detail: "Invalid synthetic manager grant." } });
        }
        mcpDto.native_flow_policy = {
          configured: true,
          scope: property ? "property" : "account",
          property_id: property ? grant.property_id : null,
          enabled_tools: [...grant.native_enabled_tools],
          read_only_tools: [...grant.native_read_only_tools],
        };
      }
      const result = safeMcpDto();
      observed.mcpDtos.push([result]);
      return route.fulfill({ json: result });
    }

    // Supporting page metadata only, not auth, flow persistence or execution.
    const user = { id: fixture.user_id, email: fixture.email, user_type: "account_user" };
    const shell = {
      "/api/admin/me": {
        ...user, memberships: [{
          account_id: fixture.account_id, account_name: "Synthetic editor checkpoint",
          account_slug: "editor-checkpoint",
        }],
      },
      "/api/admin/me/permissions": {
        is_platform_admin: false, role: { slug: "editor-pilot" },
        permissions: {
          tools: { view: true, edit: true },
          flows: { view: true, edit: true, publish: true, revert: true },
          assistants: { view: true },
          integrations: { view: true, manage: integrationsManage },
        },
      },
      "/api/account/features": {},
      "/api/integrations/types": [],
      [`/api/integrations/account/${fixture.account_id}`]: [],
      "/api/sms/pending-handoffs": { count: 0 },
      [`/api/tools/${fixture.tool_id}`]: {
        id: fixture.tool_id, account_id: fixture.account_id,
        name: "Synthetic availability flow", tool_type: "FLOW", config: {},
      },
      [`/api/tools/${fixture.tool_id}/primary-assistant`]: {
        assistant_id: fixture.assistant_id, tts_provider: "deepgram",
      },
    };
    if (Object.hasOwn(shell, url.pathname)) return route.fulfill({ json: shell[url.pathname] });
    if (url.pathname === "/api/sms/stream") {
      return route.fulfill({ contentType: "text/event-stream", body: ": synthetic shell only\n\n" });
    }
    observed.unexpected.push(url.pathname);
    return route.fulfill({ status: 404, json: { detail: "Outside the isolated browser fixture" } });
  });
  return observed;
}

async function signInToEditor(page, routeOptions) {
  const observations = await routeBrowser(page, routeOptions);
  const editorPath = `/dashboard/tools/${fixture.tool_id}/flow`;
  await page.goto(`/login?callbackUrl=${encodeURIComponent(editorPath)}`);
  await page.locator('input[type="email"]').fill(fixture.email);
  await page.locator('input[type="password"]').fill(fixture.password);
  await page.getByRole("button", { name: "Sign In", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Verify your authenticator" })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("botelier_token"))).toBeNull();
  await page.getByLabel("Authenticator code").fill(await bridge.totp());
  await page.getByRole("button", { name: "Verify", exact: true }).click();
  await expect(page.getByText("Authenticator verified.")).toBeVisible();
  expect(await page.evaluate(() => !!localStorage.getItem("botelier_token"))).toBe(true);
  // Navigating uses only the token/cookie actually issued by those real routes.
  await page.goto(editorPath);
  await expect(page.getByText("Synthetic availability flow", { exact: true })).toBeVisible();
  await expect.poll(async () => observations.pageErrors.length
    ? observations.pageErrors
    : await page.locator('.react-flow__node[data-id="query"]').count(),
  ).toBe(1);
  await expect(page.locator('.react-flow__node[data-id="query"]')).toBeVisible();
  return observations;
}

async function authHeaders(page) {
  return page.evaluate(() => ({
    authorization: "Bearer " + localStorage.getItem("botelier_token"),
    origin: window.location.origin,
    "content-type": "application/json",
  }));
}

async function loadDraft(page) {
  return bridge.request({
    method: "GET",
    path: `/api/tools/${fixture.tool_id}/flow?account_id=${fixture.account_id}`,
    headers: await authHeaders(page),
  });
}

async function getControlForLabel(page, label) {
  return page.locator("label").filter({ hasText: label }).last().locator("..").locator("input, textarea, select").first();
}

test("synthetic MFA login, draft save/reload, published versions and history use the real editor API", async ({ page }) => {
  const observations = await signInToEditor(page);
  const baselinePublished = await bridge.request({
    method: "GET",
    path: `/api/tools/${fixture.tool_id}/flow?account_id=${fixture.account_id}&source=published`,
    headers: await authHeaders(page),
  });
  expect(baselinePublished.status).toBe(200);
  const baselinePrompt = baselinePublished.body.flow_config.nodes
    .find(node => node.id === "query").data.slot.prompt;
  const prompt = "Which synthetic room should I check?";
  const instructionPlaceholder = "e.g., Be empathetic, confirm the date includes the year, offer examples if the caller seems confused...";

  await page.locator('.react-flow__node[data-id="query"]').click();
  await page.getByPlaceholder("May I have your name, please?").fill(prompt);
  await page.getByRole("button", { name: "Instructions", exact: true }).click();
  await page.getByPlaceholder(instructionPlaceholder)
    .fill("Private editor note: ask one clear question, then wait.");
  await expect(page.getByRole("button", { name: "Undo last flow edit" })).toBeEnabled();
  await page.getByRole("button", { name: "Undo last flow edit" }).click();
  await expect(page.getByPlaceholder(instructionPlaceholder))
    .toHaveValue("Private node guidance: use only the fixture results.");
  await page.getByRole("button", { name: "Redo flow edit" }).click();
  await expect(page.getByPlaceholder(instructionPlaceholder))
    .toHaveValue("Private editor note: ask one clear question, then wait.");

  await page.getByRole("button", { name: "Save Draft", exact: true }).click();
  await expect(page.getByRole("button", { name: "Save Draft", exact: true })).toBeDisabled();
  const saved = await loadDraft(page);
  expect(saved.status).toBe(200);
  expect(saved.body.flow_config.nodes.find(node => node.id === "query").data.slot.prompt).toBe(prompt);
  expect(saved.body.flow_config.nodes.find(node => node.id === "query").data.instructions)
    .toBe("Private editor note: ask one clear question, then wait.");

  await page.reload();
  await expect(page.locator('.react-flow__node[data-id="query"]')).toBeVisible();
  await page.locator('.react-flow__node[data-id="query"]').click();
  await expect(page.getByPlaceholder("May I have your name, please?")).toHaveValue(prompt);
  await page.getByRole("button", { name: "Instructions", exact: true }).click();
  await expect(page.getByPlaceholder(instructionPlaceholder))
    .toHaveValue("Private editor note: ask one clear question, then wait.");

  await page.getByRole("button", { name: "Publish", exact: true }).click();
  await page.getByPlaceholder("What changed in this version?").fill("Synthetic editor checkpoint");
  const publishResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === `/api/tools/${fixture.tool_id}/flow/publish`,
  );
  await page.getByRole("button", { name: "Publish Now", exact: true }).click();
  expect((await publishResponse).status()).toBe(200);
  await expect(page.getByRole("button", { name: "Publish Now", exact: true })).not.toBeVisible();

  const headers = await authHeaders(page);
  const versions = await bridge.request({
    method: "GET",
    path: `/api/tools/${fixture.tool_id}/flow/versions?account_id=${fixture.account_id}`,
    headers,
  });
  expect(versions.status).toBe(200);
  expect(versions.body.versions.some(version => version.version_number === 2 && version.status === "published")).toBe(true);
  const published = await bridge.request({
    method: "GET",
    path: `/api/tools/${fixture.tool_id}/flow?account_id=${fixture.account_id}&source=published`,
    headers,
  });
  expect(published.status).toBe(200);
  expect(published.body.flow_config.nodes.find(node => node.id === "query").data.slot.prompt).toBe(prompt);

  const versionButton = page.getByRole("button").filter({ hasText: /Published\s*v2|Draft\s*v2/ }).first();
  await versionButton.click();
  await expect(page.getByText("Version History", { exact: true })).toBeVisible();
  await expect(page.getByText("v2", { exact: true })).toBeVisible();
  await expect(page.getByTitle("Revert to this version").first()).toBeVisible();
  page.once("dialog", dialog => dialog.accept());
  const revertResponsePromise = page.waitForResponse(response =>
    new URL(response.url()).pathname ===
      `/api/tools/${fixture.tool_id}/flow/versions/1/revert`,
  );
  await page.getByTitle("Revert to this version").first().click();
  const revertResponse = await revertResponsePromise;
  expect(revertResponse.request().method()).toBe("POST");
  expect(revertResponse.status()).toBe(200);
  const reverted = await revertResponse.json();
  expect(reverted.flow_config.nodes.find(node => node.id === "query").data.slot.prompt)
    .toBe(baselinePrompt);
  const reloadedDraft = await bridge.request({
    method: "GET",
    path: `/api/tools/${fixture.tool_id}/flow?account_id=${fixture.account_id}&source=draft`,
    headers: await authHeaders(page),
  });
  expect(reloadedDraft.status).toBe(200);
  expect(reloadedDraft.body.flow_config.nodes.find(node => node.id === "query").data.slot.prompt)
    .toBe(baselinePrompt);
  await page.reload();
  await page.locator('.react-flow__node[data-id="query"]').click();
  await expect(page.getByPlaceholder("May I have your name, please?"))
    .toHaveValue(baselinePrompt);

  const screenshot = path.join(repo, "generated-artifacts/native-editor-version-checkpoint.png");
  fs.mkdirSync(path.dirname(screenshot), { recursive: true });
  await page.screenshot({ path: screenshot, fullPage: true });
  expect(observations.real.some(item => item.path === "/api/simulate/start")).toBe(false);
  expect(observations.real.some(item =>
    item.path === `/api/tools/${fixture.tool_id}/flow/versions/1/revert` &&
    item.method === "POST",
  )).toBe(true);
  expect(observations.pageErrors).toEqual([]);
  expect(observations.unexpected).toEqual([]);
});

async function addNodeFromToolbar(page, label) {
  const before = await page.locator(".react-flow__node").count();
  await page.getByRole("button", { name: "Add Node" }).click();
  await page.getByRole("button", { name: label, exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(before + 1);
  await page.getByRole("button", { name: "Fit View" }).click();
  const node = page.locator(".react-flow__node").last();
  await node.click({ force: true });
  return node.getAttribute("data-id");
}

async function connectNodeHandles(page, sourceId, targetId, sourceHandle = "success") {
  const handleSelector = sourceHandle
    ? `.react-flow__handle.source[data-handleid="${sourceHandle}"]`
    : ".react-flow__handle.source";
  const source = page.locator(`.react-flow__node[data-id="${sourceId}"] ${handleSelector}`).first();
  const target = page.locator(`.react-flow__node[data-id="${targetId}"] .react-flow__handle.target`);
  await expect(source).toBeVisible();
  await expect(target).toBeVisible();
  const sourceBox = await source.boundingBox();
  const targetBox = await target.boundingBox();
  if (!sourceBox || !targetBox) throw new Error("Flow connector handles are not measurable.");
  const edgeCount = await page.locator(".react-flow__edge").count();
  const targetX = targetBox.x + targetBox.width / 2;
  const targetY = targetBox.y + targetBox.height / 2;
  await page.mouse.move(sourceBox.x + sourceBox.width / 2, sourceBox.y + sourceBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(targetX, targetY, { steps: 10 });
  await page.mouse.up();
  await page.waitForTimeout(150);
  const nextCount = await page.locator(".react-flow__edge").count();
  expect(nextCount, `edge added for ${sourceId} -> ${targetId}`).toBe(edgeCount + 1);
}

test("the 15-node inspector is reachable and typed capability/quote bindings persist without provider execution", async ({ page }) => {
  const observations = await signInToEditor(page, { mcpConfigured: true });
  await page.setViewportSize({ width: 1600, height: 3000 });
  const originalNodeIds = new Set(await page.locator(".react-flow__node").evaluateAll(
    nodes => nodes.map(node => node.getAttribute("data-id")),
  ));
  const labels = [
    "Start", "Message", "Collect Input", "Collect Form", "Confirmation",
    "API Request", "API Response", "Capability", "Condition", "Router",
    "Set Variable", "Save Record", "Transfer Call", "End Call", "Option Picker",
  ];
  await page.getByRole("button", { name: "Add Node" }).click();
  for (const label of labels.slice(1)) {
    await expect(page.getByRole("button", { name: label, exact: true })).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "Capability", exact: true })).toBeVisible();
  await page.locator(".fixed.inset-0.z-40").click({ position: { x: 1000, y: 500 } });

  const ids = {};
  for (const label of labels.slice(1)) ids[label] = await addNodeFromToolbar(page, label);
  ids.CustomAPI = await addNodeFromToolbar(page, "API Request");
  ids.IntegrationAPI = await addNodeFromToolbar(page, "API Request");
  ids.SavedAPI = await addNodeFromToolbar(page, "API Request");
  ids.SMS = await addNodeFromToolbar(page, "API Request");
  ids.MCP = await addNodeFromToolbar(page, "API Request");
  ids.RecordUpdate = await addNodeFromToolbar(page, "Save Record");
  expect(Object.keys(ids)).toHaveLength(20);
  await page.locator('.react-flow__node[data-id="start"]').click({ force: true });
  await expect(page.getByText("System Prompt", { exact: true })).toBeVisible();
  for (const label of labels.slice(1)) {
    await page.locator(`.react-flow__node[data-id="${ids[label]}"]`).click({ force: true });
    await expect(page.locator('input[placeholder="Unnamed node"]')).toBeVisible();
    await expect(page.getByText("Unknown node type", { exact: true })).toHaveCount(0);
  }

  // Bind the native-only pure validator as a real capability catalog item.
  const quoteId = ids.Capability;
  await page.locator(`.react-flow__node[data-id="${quoteId}"]`).click({ force: true });
  const capabilitySelect = await getControlForLabel(page, "Capability");
  await expect(capabilitySelect.locator("option[value='validate_reservation_quote']")).toHaveCount(1);
  await capabilitySelect.selectOption("validate_reservation_quote");
  await expect(page.getByText("Reservation quote contract", { exact: false })).toBeVisible();

  const args = page.getByLabel("Quote capability arguments template");
  await args.fill('{"quote":{"room_id":"{{query}}"},"expected":{"room_id":"{{choice}}"}}');
  await page.getByLabel("Allowed checkout origins").fill("https://booking.synthetic.invalid");
  const roomBinding = page.getByLabel("Room identity variable");
  await roomBinding.fill("stay_room_id");
  await roomBinding.blur();
  await expect(roomBinding).toHaveValue("stay_room_id");
  const totalBinding = page.getByLabel("Stay total variable");
  await totalBinding.fill("quote_total");
  await totalBinding.blur();
  await page.getByLabel("Due now").check();
  await page.getByLabel("Room identity variable").blur();

  // Exercise every supported request source against safe synthetic catalogs.
  await page.locator(`.react-flow__node[data-id="${ids.CustomAPI}"]`).click({ force: true });
  await getControlForLabel(page, "API Source").then(control => control.selectOption("custom"));
  await page.getByPlaceholder("https://api.example.com/endpoint").fill("https://api.synthetic.invalid/v1/availability");
  await expect(page.getByText("Retry count", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Add output", exact: true }).click();
  await page.getByLabel("Output variable 1").fill("stock_count");
  await page.getByLabel("JSON path for output 1").fill("$.stock_count");
  await page.getByLabel("JSON default for output 1").fill("0");
  await page.getByRole("button", { name: "Add output", exact: true }).click();
  await page.getByLabel("Output variable 2").fill("rooms");
  await page.getByLabel("JSON path for output 2").fill("$.result.rooms");
  await page.getByLabel("JSON default for output 2").fill("[]");
  await page.getByRole("button", { name: "Add output", exact: true }).click();
  await page.getByLabel("Output variable 3").fill("selected_offer");
  await page.getByLabel("JSON path for output 3").fill("$.offer");
  await page.getByLabel("JSON default for output 3").fill('{"rate":{"code":"SYNTH"}}');
  await page.getByRole("button", { name: "Add output", exact: true }).click();
  await page.getByLabel("Output variable 4").fill("quote_total");
  await page.getByLabel("JSON path for output 4").fill("$.pricing.total");
  await page.getByLabel("JSON default for output 4").fill("0");
  await page.getByRole("button", { name: "Add output", exact: true }).click();
  await page.getByLabel("Output variable 5").fill("is_member");
  await page.getByLabel("JSON path for output 5").fill("$.is_member");
  await page.getByLabel("JSON default for output 5").fill("false");
  await page.getByRole("button", { name: "Add output", exact: true }).click();
  await page.getByLabel("Output variable 6").fill("room_label");
  await page.getByLabel("JSON path for output 6").fill("$.room_label");
  await page.getByRole("button", { name: "Add field", exact: true }).click();
  await page.locator('select[aria-label="Projected field 1"]').selectOption("stock_count");
  await page.getByRole("button", { name: "Add field", exact: true }).click();
  await page.locator('select[aria-label="Projected field 2"]').selectOption("quote_total");
  await expect(page.getByRole("checkbox", { name: "trim" }).nth(1)).toBeDisabled();
  await page.getByRole("button", { name: "Add field", exact: true }).click();
  await page.locator('select[aria-label="Projected field 3"]').selectOption("rooms");
  await page.getByRole("button", { name: "Add field", exact: true }).click();
  await page.locator('select[aria-label="Projected field 4"]').selectOption("is_member");
  await page.getByRole("button", { name: "Add field", exact: true }).click();
  await page.locator('select[aria-label="Projected field 5"]').selectOption("selected_offer");
  await page.getByRole("button", { name: "Add field", exact: true }).click();
  await page.locator('select[aria-label="Projected field 6"]').selectOption("room_label");
  await page.getByRole("checkbox", { name: "trim" }).nth(5).check();
  const sampleControl = page.getByText("Raw sample JSON", { exact: true }).locator("..").locator("textarea");
  await sampleControl.fill('{"result":{"rooms":[{"name":"Quiet","count":2,"price":0}]},"pricing":{"total":0},"stock_count":0,"offer":{"rate":{"code":"SYNTH"}},"is_member":false,"room_label":"  Quiet Lounge  "}');
  await expect(page.getByText("Preview uses only the sample below.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: /Response Mapping/ }).click();
  const responseMappingSection = page.getByRole("button", { name: /Response Mapping/ }).locator("..");
  await responseMappingSection.getByRole("button", { name: "Add Mapping", exact: true }).click();
  await responseMappingSection.locator('input[placeholder="$.data.guest.name"]').last().fill("$.result.rooms");
  await responseMappingSection.locator('input[placeholder="variable_name"]').last().fill("rooms");
  await expect(responseMappingSection.locator('input[placeholder="variable_name"]').last()).toHaveValue("rooms");
  const previewResponsePromise = page.waitForResponse(response =>
    new URL(response.url()).pathname === `/api/tools/${fixture.tool_id}/flow/preview-response`);
  await page.getByRole("button", { name: "Preview mapping", exact: true }).click();
  const previewResponse = await previewResponsePromise;
  expect(previewResponse.request().method()).toBe("POST");
  expect(previewResponse.status()).toBe(200);
  const preview = await previewResponse.json();
  expect(preview.mapped_variables).toMatchObject({
    stock_count: 0,
    rooms: [{ name: "Quiet", count: 2, price: 0 }],
    selected_offer: { rate: { code: "SYNTH" } },
    quote_total: 0,
    is_member: false,
    room_label: "  Quiet Lounge  ",
  });
  expect(preview.llm_data).toEqual({
    stock_count: 0,
    quote_total: 0,
    rooms: [{ name: "Quiet", count: 2, price: 0 }],
    is_member: false,
    selected_offer: { rate: { code: "SYNTH" } },
    room_label: "Quiet Lounge",
  });
  await expect(page.getByText("Sample-only preview complete", { exact: true })).toBeVisible();

  await page.locator(`.react-flow__node[data-id="${ids["API Response"]}"]`).click({ force: true });
  await getControlForLabel(page, "Array variable").then(control => control.selectOption("rooms"));
  await page.getByPlaceholder("I have found rooms available for your stay.").fill("I found these synthetic options.");
  await page.getByPlaceholder("Option {{index}}: {{room_name}} — {{price}} per night.")
    .fill("{{index}} {{name}}, count {{count}}, price {{price}}");
  await page.getByPlaceholder("Which option would you prefer?").fill("Which synthetic room should I hold?");

  await page.locator(`.react-flow__node[data-id="${ids["Option Picker"]}"]`).click({ force: true });
  await getControlForLabel(page, "Source list variable").then(control => control.selectOption("rooms"));
  await getControlForLabel(page, "Label field (dot-path)").then(control => control.fill("name"));
  await page.getByPlaceholder("Which one would you like?").fill("Say the name of your preferred synthetic room.");
  await getControlForLabel(page, "Max retries").then(control => control.fill("2"));
  await page.getByRole("button", { name: "Add binding", exact: true }).click();
  const firstPath = page.getByPlaceholder("Field path (e.g. rate.code) — blank = whole item").first();
  await firstPath.locator("..").locator("select").selectOption("choice");
  await firstPath.fill("name");
  await page.getByRole("button", { name: "Add binding", exact: true }).click();
  const secondPath = page.getByPlaceholder("Field path (e.g. rate.code) — blank = whole item").nth(1);
  await secondPath.locator("..").locator("select").selectOption("stock_count");
  await secondPath.fill("count");

  await page.locator(`.react-flow__node[data-id="${ids.IntegrationAPI}"]`).click({ force: true });
  await getControlForLabel(page, "API Source").then(control => control.selectOption("integration"));
  await getControlForLabel(page, "Connected Integration").then(control => control.selectOption("00000000-0000-0000-0000-000000000103"));
  await getControlForLabel(page, "Endpoint").then(control => control.selectOption("editor-fixture-endpoint"));
  await expect(page.getByText("Fixture availability", { exact: true })).toBeVisible();

  await page.locator(`.react-flow__node[data-id="${ids.SavedAPI}"]`).click({ force: true });
  await getControlForLabel(page, "API Source").then(control => control.selectOption("tool"));
  const savedApiSelect = page.locator("label").filter({ hasText: "Saved Tool" }).last().locator("..").locator("select");
  await savedApiSelect.selectOption("synthetic-saved-api");
  await page.getByLabel("Arguments template (JSON object)")
    .fill('{"check_in":"{{query}}","include_rooms":true,"adults":0}');

  await page.locator(`.react-flow__node[data-id="${ids.MCP}"]`).click({ force: true });
  await getControlForLabel(page, "API Source").then(control => control.selectOption("mcp"));
  await getControlForLabel(page, "Connected MCP server").then(control => control.selectOption("synthetic-mcp-connection"));
  await getControlForLabel(page, "Discovered tool").then(control => control.selectOption("inventory_lookup"));
  await expect(page.getByText("configured read-only", { exact: false })).toBeVisible();
  await page.getByLabel("Arguments template (JSON object)")
    .fill('{"room":"{{query}}","limit":0}');

  // A real quote -> confirmation edge exposes the required canonical consent
  // controls. Delivery metadata is independently configured and serialized.
  const confirmationId = ids.Confirmation;
  const senderId = ids["API Request"];
  await connectNodeHandles(page, quoteId, confirmationId);
  await page.locator(`.react-flow__node[data-id="${confirmationId}"]`).click({ force: true });
  await expect(page.getByText("Canonical public fields", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Quote confirmation requires every public quote field", { exact: false })).toBeVisible();

  // Add a safe email fact using Variables, then bind a saved email sender.
  await page.getByRole("button", { name: "Variables", exact: true }).click();
  await page.getByPlaceholder("new_variable_name").fill("caller_email");
  await page.locator('select[title="Variable type"]').selectOption("email");
  await page.getByTitle("Add variable").click();
  const variableName = page.getByText("{{caller_email}}", { exact: true });
  await expect(variableName).toBeVisible();
  await page.getByPlaceholder("new_variable_name").fill("nightly_price");
  await page.locator('select[title="Variable type"]').selectOption("number");
  await page.getByTitle("Add variable").click();
  await page.getByPlaceholder("new_variable_name").fill("caller_phone");
  await page.locator('select[title="Variable type"]').selectOption("phone");
  await page.getByTitle("Add variable").click();
  await page.getByRole("button", { name: "Properties", exact: true }).click();

  // Create/update Record controls resolve only through a reachable earlier
  // create node with the same server-owned Record type catalog entry.
  const recordCreateId = ids["Save Record"];
  await page.locator(`.react-flow__node[data-id="${recordCreateId}"]`).click({ force: true });
  await getControlForLabel(page, "Record Type").then(control => control.selectOption(fixture.browser_fixtures.record_type.id));
  await getControlForLabel(page, "Guest email").then(control => control.fill("{{caller_email}}"));
  await getControlForLabel(page, "Quoted amount").then(control => control.fill("{{nightly_price}}"));
  await getControlForLabel(page, "Status (optional)").then(control => control.selectOption("confirmed"));
  await connectNodeHandles(page, recordCreateId, ids.RecordUpdate, "");
  await page.locator(`.react-flow__node[data-id="${ids.RecordUpdate}"]`).click({ force: true });
  await getControlForLabel(page, "Record Type").then(control => control.selectOption(fixture.browser_fixtures.record_type.id));
  const updateRecordControl = page.getByLabel("Record create or update source");
  await expect(updateRecordControl.locator(`option[value="${recordCreateId}"]`)).toHaveCount(1);
  await updateRecordControl.selectOption(recordCreateId);
  await getControlForLabel(page, "Guest email").then(control => control.fill("{{caller_email}}"));
  await getControlForLabel(page, "Quoted amount").then(control => control.fill("{{nightly_price}}"));
  await getControlForLabel(page, "Status (optional)").then(control => control.selectOption("confirmed"));

  await page.locator(`.react-flow__node[data-id="${senderId}"]`).click({ force: true });
  await getControlForLabel(page, "API Source").then(control => control.selectOption("tool"));
  const savedToolSelect = page.locator("label").filter({ hasText: "Saved Tool" }).last().locator("..").locator("select");
  await expect(savedToolSelect.locator('option[value="synthetic-email-sender"]')).toHaveCount(1);
  await savedToolSelect.selectOption("synthetic-email-sender");
  await expect(page.getByText("Optional quote-link delivery", { exact: true })).toBeVisible();
  const quoteSelect = await getControlForLabel(page, "Quote validator in this flow");
  await quoteSelect.selectOption(quoteId);
  const recipientSelect = await getControlForLabel(page, "Confirmed recipient fact");
  await recipientSelect.selectOption("caller_email");
  await page.locator(`.react-flow__node[data-id="${ids.SMS}"]`).click({ force: true });
  await getControlForLabel(page, "API Source").then(control => control.selectOption("tool"));
  const smsToolSelect = page.locator("label").filter({ hasText: "Saved Tool" }).last().locator("..").locator("select");
  await smsToolSelect.selectOption("synthetic-sms-sender");
  await getControlForLabel(page, "Quote validator in this flow").then(control => control.selectOption(quoteId));
  await getControlForLabel(page, "Confirmed recipient fact").then(control => control.selectOption("caller_phone"));
  await page.getByRole("button", { name: "Variables", exact: true }).click();
  await page.getByRole("button", { name: "{{caller_email}}", exact: true }).click();
  const renameEmailInput = page.locator("input:focus");
  await renameEmailInput.fill("guest_email");
  await renameEmailInput.press("Enter");
  await expect(page.getByRole("button", { name: "{{guest_email}}", exact: true })).toBeVisible();
  await page.locator(`.react-flow__node[data-id="${quoteId}"]`).click({ force: true });
  await page.getByLabel("Quote fingerprint variable").fill("quote_digest");
  await page.getByLabel("Quote fingerprint variable").blur();
  await page.getByLabel("Private checkout URL variable").fill("private_reservation_link");
  await page.getByLabel("Private checkout URL variable").blur();
  await page.locator(`.react-flow__node[data-id="${senderId}"]`).click({ force: true });
  await expect(page.getByLabel("Quote link delivery arguments"))
    .toHaveValue(/private_reservation_link/);
  await expect(page.getByLabel("Quote link delivery arguments"))
    .toHaveValue(/guest_email/);
  await page.locator(`.react-flow__node[data-id="${confirmationId}"]`).click({ force: true });
  await expect(page.getByText("guest_email", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("quote_digest", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("private_reservation_link", { exact: false })).toHaveCount(0);

  await page.locator(`.react-flow__node[data-id="${confirmationId}"]`).click({ force: true });
  await expect(page.getByText("Quote confirmation requires every public quote field", { exact: false })).toBeVisible();
  for (const key of ["stay_room_id", "quote_check_in", "quote_check_out", "quote_adults",
    "quote_children", "quote_pricing_basis", "quote_pricing_currency", "quote_pricing_subtotal",
    "quote_pricing_tax_total", "quote_pricing_tax_treatment", "quote_pricing_fees_total",
    "quote_pricing_fees_treatment", "quote_total"]) {
    await expect(page.getByText(key, { exact: false }).first()).toBeVisible();
  }

  // Human-facing speech surfaces are checked against the shared graph-aware
  // privacy hook in the offline CJS suite; this browser flow keeps the quote
  // path focused on confirmation and verifies each editor remains reachable.
  for (const [nodeId, placeholder] of [
    [ids.Message, "Message"],
    [ids["Collect Input"], "May I have your name, please?"],
    [ids["Collect Form"], "I'll need to collect a few details from you..."],
    [ids["API Response"], "I have found rooms available for your stay."],
  ]) {
    await page.locator(`.react-flow__node[data-id="${nodeId}"]`).click({ force: true });
    await expect(page.getByPlaceholder(placeholder).first()).toBeVisible();
  }
  await page.locator(`.react-flow__node[data-id="${ids["Transfer Call"]}"]`).click({ force: true });
  await expect(page.getByPlaceholder("Please hold while I connect you...")).toBeVisible();
  await page.locator(`.react-flow__node[data-id="${ids["End Call"]}"]`).click({ force: true });
  await expect(page.getByPlaceholder("Thank you for calling! Have a wonderful day.")).toBeVisible();
  await page.locator('.react-flow__node[data-id="start"]').click({ force: true });
  await expect(page.getByPlaceholder("Describe the AI's role and behavior...")).toBeVisible();

  const beforePairDuplicate = await page.locator(".react-flow__node").count();
  await page.locator(`.react-flow__node[data-id="${quoteId}"]`).click({ force: true });
  await page.locator(`.react-flow__node[data-id="${senderId}"]`).click({ force: true, modifiers: ["Control"] });
  await page.getByRole("button", { name: "Duplicate selected nodes" }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(beforePairDuplicate + 2);

  const saveResponsePromise = page.waitForResponse(response =>
    new URL(response.url()).pathname === `/api/tools/${fixture.tool_id}/flow/draft` &&
    response.request().method() === "PUT");
  await page.getByRole("button", { name: "Save Draft", exact: true }).click();
  const saveResponse = await saveResponsePromise;
  const saveBody = await saveResponse.json();
  const saveDiagnostic = saveBody?.detail ?? saveBody?.error ?? saveBody?.message ?? saveBody?.errors ?? saveBody;
  console.log(`Synthetic flow save status: ${saveResponse.status()}; diagnostic: ${JSON.stringify(saveDiagnostic).slice(0, 1000)}`);
  expect(saveResponse.status()).toBe(200);
  const saved = await loadDraft(page);
  expect(saved.status).toBe(200);
  const savedNodes = saved.body.flow_config.nodes;
  const quoteNode = savedNodes.find(node => node.id === quoteId);
  expect(quoteNode.data.api.capability).toBe("validate_reservation_quote");
  const corePublicPaths = [
    "room_id", "check_in", "check_out", "adults", "children", "pricing.basis",
    "pricing.currency", "pricing.subtotal", "pricing.tax_total",
    "pricing.tax_treatment", "pricing.fees_total", "pricing.fees_treatment", "pricing.total",
  ];
  expect(Object.keys(quoteNode.data.api.quotePolicy.publicConfirmationFields)).toHaveLength(14);
  expect(corePublicPaths.every(path => Object.hasOwn(quoteNode.data.api.quotePolicy.publicConfirmationFields, path))).toBe(true);
  expect(Object.hasOwn(quoteNode.data.api.quotePolicy.publicConfirmationFields, "pricing.due_now")).toBe(true);
  expect(quoteNode.data.api.quotePolicy.publicConfirmationFields["room_id"]).toBe("stay_room_id");
  expect(quoteNode.data.api.quotePolicy.publicConfirmationFields["pricing.total"]).toBe("quote_total");
  expect(quoteNode.data.api.quotePolicy.allowedCheckoutOrigins).toEqual(["https://booking.synthetic.invalid"]);
  expect(quoteNode.data.api.argumentsTemplate).toBe('{"quote":{"room_id":"{{query}}"},"expected":{"room_id":"{{choice}}"}}');
  expect(quoteNode.data.api.quotePolicy.privateUrlVariable).toBe("private_reservation_link");
  expect(quoteNode.data.api.quotePolicy.fingerprintVariable).toBe("quote_digest");
  expect(quoteNode.data.api.responseMapping[quoteNode.data.api.quotePolicy.privateUrlVariable]).toBe("$.private.checkout_url");
  expect(quoteNode.data.api.responseMapping[quoteNode.data.api.quotePolicy.fingerprintVariable]).toBe("$.fingerprint");
  const projectionKeys = quoteNode.data.api.responseProjection.fields.map(field => field.variable);
  expect(projectionKeys).not.toContain(quoteNode.data.api.quotePolicy.privateUrlVariable);
  expect(projectionKeys).not.toContain(quoteNode.data.api.quotePolicy.fingerprintVariable);
  expect(quoteNode.data.api.responseVariables.every(binding => !Object.hasOwn(binding, "defaultValue"))).toBe(true);
  const sender = savedNodes.find(node => node.id === senderId);
  expect(sender.data.api.quoteDelivery).toEqual({ quoteNodeId: quoteId, recipientVariable: "guest_email" });
  expect(sender.data.api.argumentsTemplate).toContain("{{guest_email}}");
  expect(sender.data.api.argumentsTemplate).toContain("{{private_reservation_link}}");
  expect(sender.data.api.argumentsTemplate).not.toContain("{{private_checkout_url}}");
  expect(sender.data.api.apiSource).toBe("tool");
  const quoteCopy = savedNodes.find(node => node.id !== quoteId && node.data.api?.capability === "validate_reservation_quote");
  const senderCopy = savedNodes.find(node =>
    node.id !== senderId &&
    node.data.api?.toolId === "synthetic-email-sender" &&
    node.data.api?.quoteDelivery,
  );
  expect(quoteCopy).toBeDefined();
  expect(senderCopy.data.api.quoteDelivery.quoteNodeId).toBe(quoteCopy.id);
  const sms = savedNodes.find(node => node.id === ids.SMS).data.api;
  expect(sms.quoteDelivery).toEqual({ quoteNodeId: quoteId, recipientVariable: "caller_phone" });
  expect(sms.argumentsTemplate).toContain("{{private_reservation_link}}");
  const custom = savedNodes.find(node => node.id === ids.CustomAPI).data.api;
  expect(custom).toMatchObject({
    apiSource: "custom",
    url: "https://api.synthetic.invalid/v1/availability",
    responseMapping: { rooms: "$.result.rooms" },
  });
  expect(custom.responseVariables).toEqual([
    { variableKey: "stock_count", jsonPath: "$.stock_count", defaultValue: 0 },
    { variableKey: "rooms", jsonPath: "$.result.rooms", defaultValue: [] },
    { variableKey: "selected_offer", jsonPath: "$.offer", defaultValue: { rate: { code: "SYNTH" } } },
    { variableKey: "quote_total", jsonPath: "$.pricing.total", defaultValue: 0 },
    { variableKey: "is_member", jsonPath: "$.is_member", defaultValue: false },
    { variableKey: "room_label", jsonPath: "$.room_label" },
  ]);
  expect(custom.responseProjection.fields).toEqual([
    { variable: "stock_count" },
    { variable: "quote_total" },
    { variable: "rooms" },
    { variable: "is_member" },
    { variable: "selected_offer" },
    { variable: "room_label", cleanup: ["trim"] },
  ]);
  const response = savedNodes.find(node => node.id === ids["API Response"]).data.responsePresentation;
  expect(response).toMatchObject({
    arrayVariable: "rooms",
    introText: "I found these synthetic options.",
    itemTemplate: "{{index}} {{name}}, count {{count}}, price {{price}}",
    outroText: "Which synthetic room should I hold?",
  });
  const picker = savedNodes.find(node => node.id === ids["Option Picker"]).data.optionPicker;
  expect(picker).toMatchObject({
    sourceVariable: "rooms",
    labelPath: "name",
    prompt: "Say the name of your preferred synthetic room.",
    maxRetries: 2,
    writes: [
      { variableKey: "choice", path: "name" },
      { variableKey: "stock_count", path: "count" },
    ],
  });
  const integration = savedNodes.find(node => node.id === ids.IntegrationAPI).data.api;
  expect(integration).toMatchObject({ apiSource: "integration", integrationId: "00000000-0000-0000-0000-000000000103", endpointId: "editor-fixture-endpoint" });
  const savedApi = savedNodes.find(node => node.id === ids.SavedAPI).data.api;
  expect(savedApi).toMatchObject({
    apiSource: "tool",
    toolId: "synthetic-saved-api",
    argumentsTemplate: '{"check_in":"{{query}}","include_rooms":true,"adults":0}',
  });
  const mcp = savedNodes.find(node => node.id === ids.MCP).data.api;
  expect(mcp).toMatchObject({
    apiSource: "mcp",
    mcpConnectionId: "synthetic-mcp-connection",
    mcpToolName: "inventory_lookup",
    argumentsTemplate: '{"room":"{{query}}","limit":0}',
  });
  const createRecord = savedNodes.find(node => node.id === recordCreateId).data.saveRecord;
  const updateRecord = savedNodes.find(node => node.id === ids.RecordUpdate).data.saveRecord;
  expect(createRecord).toMatchObject({
    recordTypeId: fixture.browser_fixtures.record_type.id,
    recordTypeName: fixture.browser_fixtures.record_type.name,
    mapping: { guest_email: "{{guest_email}}", amount: "{{nightly_price}}" },
    status: "confirmed",
  });
  expect(updateRecord).toMatchObject({
    recordTypeId: fixture.browser_fixtures.record_type.id,
    recordTypeName: fixture.browser_fixtures.record_type.name,
    mapping: { guest_email: "{{guest_email}}", amount: "{{nightly_price}}" },
    status: "confirmed",
    updateSourceNodeId: recordCreateId,
  });
  await page.reload();
  await expect(page.locator(`.react-flow__node[data-id="${recordCreateId}"]`)).toBeVisible();
  await expect(page.locator(`.react-flow__node[data-id="${ids.RecordUpdate}"]`)).toBeVisible();
  await page.locator(`.react-flow__node[data-id="${ids.RecordUpdate}"]`).click({ force: true });
  await expect(page.getByLabel("Record create or update source")).toHaveValue(recordCreateId);

  // Save a small publishable graph through the same authenticated ASGI draft
  // route: retain the original valid graph plus the already UI-configured
  // create/update pair, and make that pair reachable from Start.
  const publishableNodeIds = new Set([
    ...originalNodeIds, recordCreateId, ids.RecordUpdate,
  ]);
  const publishableFlowConfig = {
    ...saved.body.flow_config,
    nodes: saved.body.flow_config.nodes.filter(node => publishableNodeIds.has(node.id)),
    edges: saved.body.flow_config.edges.filter(edge =>
      publishableNodeIds.has(edge.source) && publishableNodeIds.has(edge.target),
    ),
  };
  publishableFlowConfig.edges.push({
    id: "start-to-fixture-record-create",
    source: "start",
    target: recordCreateId,
  });
  const minimalGraphSave = await bridge.request({
    method: "PUT",
    path: `/api/tools/${fixture.tool_id}/flow/draft?account_id=${fixture.account_id}`,
    headers: await authHeaders(page),
    body: {
      flow_config: publishableFlowConfig,
      description: "Fixture-owned Record create/update browser verification",
    },
  });
  expect(minimalGraphSave.status).toBe(200);
  await page.reload();
  await page.locator(`.react-flow__node[data-id="${ids.RecordUpdate}"]`).click({ force: true });
  await expect(page.getByLabel("Record create or update source")).toHaveValue(recordCreateId);

  await page.getByRole("button", { name: "Publish", exact: true }).click();
  await page.getByPlaceholder("What changed in this version?").fill("Publish fixture-owned Record nodes");
  const publishResponsePromise = page.waitForResponse(response =>
    new URL(response.url()).pathname === `/api/tools/${fixture.tool_id}/flow/publish`,
  );
  await page.getByRole("button", { name: "Publish Now", exact: true }).click();
  const publishResponse = await publishResponsePromise;
  expect(publishResponse.status()).toBe(200);
  const publishedRecordFlow = await bridge.request({
    method: "GET",
    path: `/api/tools/${fixture.tool_id}/flow?account_id=${fixture.account_id}&source=published`,
    headers: await authHeaders(page),
  });
  expect(publishedRecordFlow.status).toBe(200);
  expect(publishedRecordFlow.body.flow_config.nodes.find(node => node.id === recordCreateId).data.saveRecord.recordTypeId)
    .toBe(fixture.browser_fixtures.record_type.id);
  expect(publishedRecordFlow.body.flow_config.nodes.find(node => node.id === ids.RecordUpdate).data.saveRecord.updateSourceNodeId)
    .toBe(recordCreateId);
  const copiedQuotes = savedNodes.filter(node =>
    node.id !== quoteId &&
    node.data.api?.apiSource === "capability" &&
    node.data.api?.capability === "validate_reservation_quote",
  );
  expect(copiedQuotes).toHaveLength(1);
  const copiedSenders = savedNodes.filter(node =>
    node.id !== senderId && node.data.api?.toolId === "synthetic-email-sender",
  );
  expect(copiedSenders).toHaveLength(1);
  expect(copiedSenders[0].data.api.quoteDelivery.quoteNodeId).toBe(copiedQuotes[0].id);
  expect(observations.mcpTestCalls).toBe(0);
  expect(observations.real.some(item =>
    item.path === `/api/tools/${fixture.tool_id}/flow/preview-response` &&
    item.method === "POST",
  )).toBe(true);
  expect(observations.real.some(item => /api-tester\/test/.test(item.path))).toBe(false);
  expect(observations.pageErrors).toEqual([]);
  expect(observations.unexpected).toEqual([]);
});

test("authenticated native Text Lab resumes a paused API action with the exact raw sample", async ({ page }) => {
  const observations = await signInToEditor(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open Test Lab" }).click();
  await page.getByLabel("Test engine").selectOption("native");

  const startResponsePromise = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/simulate/start" &&
    response.request().method() === "POST");
  await page.getByRole("button", { name: "Start native development test" }).click();
  const startResponse = await startResponsePromise;
  expect(startResponse.status()).toBe(200);
  const startEvidence = observations.responses.find(item => item.path === "/api/simulate/start");
  expect(startEvidence.body.runtime).toMatchObject({
    engine: "native_pilot",
    execution_mode: "preview",
    effect_mode: "simulation",
    effects_simulated: true,
    tool_id: fixture.tool_id,
    assistant_id: fixture.assistant_id,
  });
  const testLab = page.getByLabel("Flow Simulator");
  const labBounds = await testLab.boundingBox();
  expect(labBounds).not.toBeNull();
  expect(labBounds.x).toBe(0);
  expect(labBounds.width).toBeGreaterThanOrEqual(389);
  expect(labBounds.height).toBeGreaterThanOrEqual(843);

  // The model double extracts the caller's real test message; its native
  // callback then pauses at this HTTP node before any external I/O.
  const callerMessage = "standard";
  await page.getByLabel("Message as guest").fill(callerMessage);
  const callerResponsePromise = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/simulate/message" &&
    response.request().method() === "POST");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  expect((await callerResponsePromise).status()).toBe(200);
  const callerRequest = observations.simulationRequests.at(-1);
  expect(callerRequest.message).toBe(callerMessage);
  expect(callerRequest.previewResult).toBeNull();
  await expect(page.getByRole("form", { name: "Supply sample action response" })).toBeVisible();
  const actionPause = observations.responses
    .filter(item => item.path === "/api/simulate/message").at(-1);
  const pendingPreview = actionPause.body.state.pending_preview;
  expect(pendingPreview).toMatchObject({
    node_id: "lookup",
    source_kind: "http",
  });
  await page.screenshot({
    path: path.join(repo, "generated-artifacts/native-action-preview-mobile-checkpoint.png"),
  });

  const sampleField = page.getByLabel("Sample response JSON");
  const sampleBounds = await sampleField.boundingBox();
  expect(sampleBounds).not.toBeNull();
  expect(sampleBounds.width).toBeGreaterThanOrEqual(340);
  await expect(page.getByLabel("Message as guest")).toBeDisabled();

  const rawSample = '{"rooms":[{"name":"Standard","price":0}],"reservation_id":9007199254740993,"active":false}';
  await sampleField.fill(rawSample);
  const sampleResponsePromise = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/simulate/message" &&
    response.request().method() === "POST");
  await page.getByRole("button", { name: "Continue with sample", exact: true }).click();
  const sampleResponse = await sampleResponsePromise;
  expect(sampleResponse.status()).toBe(200);
  const sampleRequest = observations.simulationRequests.at(-1);
  expect(sampleRequest).toMatchObject({
    message: "",
    previewResult: {
      requestId: pendingPreview.request_id,
      statusCode: 200,
      dataJson: rawSample,
      hasParsedData: false,
    },
  });
  expect(sampleRequest.previewResult).not.toHaveProperty("success");
  expect(await page.getByRole("form", { name: "Supply sample action response" }).count()).toBe(0);
  await expect(page.getByText(
    "Here are the fixture options. Standard costs 0.",
    { exact: true },
  )).toBeVisible();
  await expect(testLab.getByText("Which option?", { exact: true })).toHaveCount(1);
  await expect(testLab.locator("div.flex.justify-end p")).toHaveCount(1);
  await expect(testLab.locator("div.flex.justify-end p").first()).toHaveText("standard");
  await expect(testLab.getByText("I am checking the fixture.", { exact: true })).toHaveCount(1);
  const continued = observations.responses
    .filter(item => item.path === "/api/simulate/message").at(-1).body;
  expect(continued.state.current_node).toBe("choice");
  expect(continued.state.pending_slot).toBe("choice");
  expect(continued.state.collected_slots.query).toBe("standard");
  expect(continued.state.pending_preview).toBeFalsy();
  await expect(page.getByLabel("Message as guest")).toBeEnabled();
  await expect(page.getByText(/configured model may incur provider usage/i)).toBeVisible();
  await page.screenshot({
    path: path.join(repo, "generated-artifacts/native-continuation-mobile-checkpoint.png"),
  });
  expect(observations.real.filter(item => item.path.startsWith("/api/simulate/"))
    .map(item => `${item.method} ${item.path}`)).toContain("POST /api/simulate/start");
  expect(observations.real.filter(item => item.path === "/api/simulate/message")).toHaveLength(2);
  expect(observations.mocked.some(item => item.path.startsWith("/api/simulate/"))).toBe(false);
  expect(observations.unexpected).toEqual([]);
  expect(observations.pageErrors).toEqual([]);
});

test("Test Lab opens as a full-width mobile panel and closes accessibly", async ({ page }) => {
  const observations = await signInToEditor(page);
  await page.getByRole("button", { name: "Test", exact: true }).click();
  const desktopLab = page.getByLabel("Flow Simulator");
  const desktopBounds = await desktopLab.boundingBox();
  expect(desktopBounds.width).toBeGreaterThanOrEqual(310);
  expect(desktopBounds.width).toBeLessThanOrEqual(321);
  fs.mkdirSync(path.join(repo, "generated-artifacts"), { recursive: true });
  await page.screenshot({
    path: path.join(repo, "generated-artifacts/native-test-lab-desktop-checkpoint.png"),
  });
  await page.getByRole("button", { name: "Close simulator" }).click();
  await expect(desktopLab).toBeHidden();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open Test Lab" }).click();
  await expect(desktopLab).toBeVisible();
  const mobileBounds = await desktopLab.boundingBox();
  expect(mobileBounds.x).toBe(0);
  expect(mobileBounds.width).toBeGreaterThanOrEqual(389);
  expect(mobileBounds.height).toBeGreaterThanOrEqual(843);
  await page.screenshot({
    path: path.join(repo, "generated-artifacts/native-test-lab-mobile-checkpoint.png"),
  });
  await expect(page.getByRole("button", { name: "Close simulator" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(desktopLab).toBeHidden();
  expect(observations.pageErrors).toEqual([]);
  expect(observations.unexpected).toEqual([]);
});

test("MCP manager grants use the safe policy DTO and sensitive rebind revokes unless explicitly re-granted", async ({ page }) => {
  const observations = await signInToEditor(page);
  await page.goto("/dashboard/integrations");
  await expect(page.getByText("MCP Connections", { exact: true })).toBeVisible();
  await expect(page.getByText("No stored native Flow grant.", { exact: false })).toBeVisible();

  const cards = page.locator("text=Synthetic inventory server");
  await expect(cards.first()).toBeVisible();
  await page.getByRole("button", { name: "Edit Synthetic inventory server" }).click();
  await page.getByPlaceholder("My MCP Server").fill("Synthetic inventory — reviewed");
  await page.getByRole("button", { name: "Update", exact: true }).click();
  await expect.poll(() => observations.mcpRequests.length).toBe(1);
  expect(observations.mcpRequests[0].payload.name).toBe("Synthetic inventory — reviewed");
  expect(observations.mcpRequests[0].payload).not.toHaveProperty("connection_config");
  expect(observations.mcpTestCalls).toBe(0);

  await page.getByRole("button", { name: "Edit Synthetic inventory — reviewed" }).click();
  await page.getByRole("checkbox", { name: "Submit a fresh native Flow grant with this save" }).check();
  await page.getByRole("radio", { name: "One property" }).check();
  await page.getByPlaceholder("Property UUID").fill("property-synthetic-21");
  await page.getByRole("checkbox", { name: "inventory_lookup" }).check();
  await page.getByRole("checkbox", { name: "inventory_adjust" }).check();
  await page.getByRole("checkbox", { name: "Read-only" }).first().check();
  await page.getByRole("button", { name: "Update", exact: true }).click();
  await expect.poll(() => observations.mcpRequests.length).toBe(2);
  const grant = observations.mcpRequests[1].payload.connection_config;
  expect(grant).toMatchObject({
    property_id: "property-synthetic-21",
    native_enabled_tools: ["inventory_lookup", "inventory_adjust"],
    native_read_only_tools: ["inventory_lookup"],
  });
  expect(observations.mcpDtos.at(-1)[0].native_flow_policy).toEqual({
    configured: true,
    scope: "property",
    property_id: "property-synthetic-21",
    enabled_tools: ["inventory_lookup", "inventory_adjust"],
    read_only_tools: ["inventory_lookup"],
  });

  await page.getByRole("button", { name: "Edit Synthetic inventory — reviewed" }).click();
  await page.getByPlaceholder(/Current host:/).fill("https://mcp-rebound.synthetic.invalid/endpoint");
  await page.getByRole("button", { name: "Update", exact: true }).click();
  await expect.poll(() => observations.mcpRequests.length).toBe(3);
  expect(observations.mcpRequests[2].payload.server_url).toContain("mcp-rebound.synthetic.invalid");
  expect(observations.mcpRequests[2].payload).not.toHaveProperty("connection_config");
  expect(observations.mcpDtos.at(-1)[0].native_flow_policy.configured).toBe(false);
  const body = await page.locator("body").innerText();
  expect(body).not.toContain("private-path");
  expect(JSON.stringify(observations.mcpDtos)).not.toMatch(/credential|secret|encrypted|grant_seal|connection_config/i);
  expect(observations.mcpTestCalls).toBe(0);
  expect(observations.pageErrors).toEqual([]);
  expect(observations.unexpected).toEqual([]);
});

test("MCP view-only permission allows a name/description edit but exposes no grant or rebind controls", async ({ page }) => {
  const observations = await signInToEditor(page, { integrationsManage: false });
  await page.goto("/dashboard/integrations");
  await expect(page.getByText("MCP Connections", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Edit Synthetic inventory server" }).click();
  await expect(page.getByRole("checkbox", { name: "Submit a fresh native Flow grant with this save" })).toHaveCount(0);
  await expect(page.getByPlaceholder(/Current host:/)).toBeDisabled();
  await expect(page.getByText(/Read-only server access/)).toBeVisible();
  await page.getByPlaceholder("My MCP Server").fill("View-only safe label");
  await page.getByRole("button", { name: "Update", exact: true }).click();
  await expect.poll(() => observations.mcpRequests.length).toBe(1);
  expect(observations.mcpRequests[0].payload).toMatchObject({
    account_id: fixture.account_id,
    name: "View-only safe label",
    description: "Safe catalog fixture",
  });
  expect(observations.mcpRequests[0].payload).not.toHaveProperty("connection_config");
  expect(observations.mcpRequests[0].payload).not.toHaveProperty("server_url");
  expect(observations.mcpRequests[0].payload).not.toHaveProperty("credentials");
  expect(observations.mcpTestCalls).toBe(0);
  expect(observations.unexpected).toEqual([]);
});

test("the native editor inspector remains usable on desktop and opens a viewport-wide mobile drawer", async ({ page }) => {
  const observations = await signInToEditor(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.locator('.react-flow__node[data-id="query"]').click({ force: true });
  await expect(page.getByPlaceholder("May I have your name, please?")).toBeVisible();
  const inspector = page.getByTestId("node-inspector");
  await expect(inspector).toBeVisible();
  const desktopBounds = await inspector.boundingBox();
  const desktopFieldBounds = await page.getByPlaceholder("May I have your name, please?").boundingBox();
  expect(desktopBounds).not.toBeNull();
  expect(desktopBounds.width).toBeGreaterThanOrEqual(470);
  expect(desktopBounds.x + desktopBounds.width).toBeLessThanOrEqual(1440);
  expect(desktopFieldBounds).not.toBeNull();
  expect(desktopFieldBounds.width).toBeGreaterThanOrEqual(400);

  const screenshotDir = path.join(repo, "generated-artifacts");
  fs.mkdirSync(screenshotDir, { recursive: true });
  await page.screenshot({ path: path.join(screenshotDir, "native-editor-desktop-inspector-checkpoint.png") });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByPlaceholder("May I have your name, please?")).toBeVisible();
  await expect(page.getByRole("button", { name: "Back to flow canvas" })).toBeVisible();
  const mobileBounds = await inspector.boundingBox();
  const mobileField = page.getByPlaceholder("May I have your name, please?");
  const mobileFieldBounds = await mobileField.boundingBox();
  expect(mobileBounds).not.toBeNull();
  expect(mobileBounds.x).toBe(0);
  expect(mobileBounds.y).toBe(0);
  expect(mobileBounds.width).toBeGreaterThanOrEqual(389);
  expect(mobileBounds.height).toBeGreaterThanOrEqual(843);
  expect(mobileBounds.x + mobileBounds.width).toBeLessThanOrEqual(390);
  expect(mobileFieldBounds).not.toBeNull();
  expect(mobileFieldBounds.width).toBeGreaterThanOrEqual(320);
  expect(mobileFieldBounds.x).toBeGreaterThanOrEqual(0);
  expect(mobileFieldBounds.x + mobileFieldBounds.width).toBeLessThanOrEqual(390);

  for (const name of ["Properties", "Variables", "Instructions"]) {
    const tab = page.getByRole("button", { name, exact: true });
    await expect(tab).toBeVisible();
    const tabMetrics = await tab.evaluate(element => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(tabMetrics.scrollWidth).toBeLessThanOrEqual(tabMetrics.clientWidth + 1);
  }

  await page.getByRole("button", { name: "Instructions", exact: true }).click();
  const instructions = page.getByPlaceholder(/Be empathetic, confirm the date includes the year/);
  await expect(instructions).toBeVisible();
  const instructionsBounds = await instructions.boundingBox();
  expect(instructionsBounds.width).toBeGreaterThanOrEqual(320);
  await page.getByRole("button", { name: "Properties", exact: true }).click();
  await page.screenshot({ path: path.join(screenshotDir, "native-editor-mobile-checkpoint.png") });
  await page.getByRole("button", { name: "Back to flow canvas" }).click();
  await expect(inspector).toBeHidden();

  expect(observations.pageErrors).toEqual([]);
  expect(observations.unexpected).toEqual([]);
});
