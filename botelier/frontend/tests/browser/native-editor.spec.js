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
    path: process.env.PATH,
  });
  child = spawn(invocation.command, invocation.args, {
    env: invocation.env, stdio: ["pipe", "pipe", "inherit"],
  });
  bridge = connectEditorFixture(child, { timeoutMs: 45_000 });
  fixture = await bridge.ready;
  expect(fixture.scope).toBe("test_only_editor_leaf_routes_not_main_app_startup");
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

async function routeBrowser(page) {
  const observed = { real: [], unexpected: [], responses: [], pageErrors: [] };
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
          flows: { view: true, edit: true, publish: true },
          assistants: { view: true },
        },
      },
      "/api/account/features": {},
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

async function signInToEditor(page) {
  const observations = await routeBrowser(page);
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

async function openNativeTest(page) {
  await page.getByRole("button", { name: "Test", exact: true }).click();
  await expect(page.getByLabel("Test engine")).toHaveValue("legacy");
  await page.getByLabel("Test engine").selectOption("native");
}

test("real sign-in, editor save/reload/publish and native execution use one pinned definition", async ({ page }) => {
  const observations = await signInToEditor(page);
  await openNativeTest(page);
  await page.locator('.react-flow__node[data-id="query"]').click();
  const question = page.getByPlaceholder("May I have your name, please?");
  await question.fill("Which synthetic room should I check?");
  await page.getByRole("button", { name: "Instructions", exact: true }).click();
  const instructionPlaceholder = "e.g., Be empathetic, confirm the date includes the year, offer examples if the caller seems confused...";
  await page.getByPlaceholder(instructionPlaceholder).fill("Private synthetic rule: collect only the caller's room preference.");
  await page.getByRole("button", { name: "Start native development test" }).click();
  await expect(page.getByRole("alert", { name: "Simulation error" })).toContainText(/save|unsaved/i);
  expect(observations.real.some(item => item.path === "/api/simulate/start")).toBe(false);

  await page.getByRole("button", { name: "Save Draft", exact: true }).click();
  await expect(page.getByRole("button", { name: "Save Draft", exact: true })).toBeDisabled();
  await page.reload();
  await expect(page.locator('.react-flow__node[data-id="query"]')).toBeVisible();
  await page.locator('.react-flow__node[data-id="query"]').click();
  await expect(page.getByPlaceholder("May I have your name, please?")).toHaveValue("Which synthetic room should I check?");
  await page.getByRole("button", { name: "Instructions", exact: true }).click();
  await expect(page.getByPlaceholder(instructionPlaceholder)).toHaveValue("Private synthetic rule: collect only the caller's room preference.");
  await openNativeTest(page);
  await page.getByRole("button", { name: "Start native development test" }).click();
  await expect(page.getByRole("alert", { name: "Simulation error" })).toContainText(/publish/i);
  expect(observations.real.some(item => item.path === "/api/simulate/start")).toBe(false);
  await page.getByRole("button", { name: "Publish", exact: true }).click();
  const publishResponse = page.waitForResponse(response =>
    new URL(response.url()).pathname === `/api/tools/${fixture.tool_id}/flow/publish`,
  );
  await page.getByRole("button", { name: "Publish Now", exact: true }).click();
  expect((await publishResponse).status()).toBe(200);
  await expect(page.getByRole("button", { name: "Publish Now", exact: true })).not.toBeVisible();

  await page.getByLabel("Test engine").selectOption("native");
  await page.getByRole("button", { name: "Start native development test" }).click();
  const evidence = page.getByLabel("Simulation runtime evidence");
  await expect(evidence).toContainText("native_pilot");
  await expect(evidence).toContainText("published v2");
  await expect(page.getByRole("region", { name: "Flow Simulator" }).getByText(
    "Which synthetic room should I check?", { exact: true },
  )).toBeVisible();
  expect(startedPrivateText(observations)).not.toContain("Private synthetic rule");
  const started = observations.responses.find(item => item.path === "/api/simulate/start" && item.status === 200);
  const published = observations.responses.find(item => item.path.endsWith("/publish") && item.status === 200);
  expect(started.body.variables_to_collect.map(item => item.key)).toEqual(["query", "choice"]);
  expect(started.body.runtime.flow_version_id).toBe(published.body.version_id);
  expect(started.body.runtime.version_number).toBe(2);

  await page.getByPlaceholder("Type as guest...").fill("Please check standard.");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect.poll(() => observations.responses.filter(item => item.path === "/api/simulate/message").length).toBe(1);
  const turn = observations.responses.find(item => item.path === "/api/simulate/message");
  expect(turn.status).toBe(200);
  expect(turn.body.state.current_node).toBe("choice");
  expect(turn.body.function_result.data.rooms).toEqual([{ name: "Standard", price: 0 }]);
  expect(turn.body.runtime.flow_version_id).toBe(published.body.version_id);
  await expect(page.getByRole("region", { name: "Flow Simulator" }).getByRole("paragraph")
    .filter({ hasText: /Standard costs 0/ })).toBeVisible();
  const screenshot = path.join(repo, "generated-artifacts/native-editor-checkpoint.png");
  fs.mkdirSync(path.dirname(screenshot), { recursive: true });
  await page.screenshot({ path: screenshot, fullPage: true });

  await page.getByRole("button", { name: "Reset simulation", exact: true }).click();
  await expect.poll(() => observations.real.filter(item => item.method === "DELETE").length).toBe(1);
  expect(observations.pageErrors).toEqual([]);
  expect(observations.unexpected).toEqual([]);
});

function startedPrivateText(observations) {
  const started = observations.responses.find(item => item.path === "/api/simulate/start" && item.status === 200);
  return JSON.stringify(started?.body?.messages || []);
}

test("server-side version changes and unsupported instructions surface without legacy fallback", async ({ page }) => {
  const observations = await signInToEditor(page);
  await openNativeTest(page);
  const headers = await page.evaluate(() => ({
    authorization: "Bearer " + localStorage.getItem("botelier_token"),
    origin: window.location.origin,
    "content-type": "application/json",
  }));
  const root = `/api/tools/${fixture.tool_id}/flow?account_id=${fixture.account_id}`;
  const current = await bridge.request({ method: "GET", path: root, headers });
  const config = current.body.flow_config;
  config.nodes.find(node => node.id === "query").data.slot.prompt = "Which concurrently edited room?";
  const saved = await bridge.request({
    method: "PUT", path: root.replace("/flow?", "/flow/draft?"), headers,
    body: { flow_config: config },
  });
  expect(saved.status).toBe(200);
  const published = await bridge.request({
    method: "POST", path: root.replace("/flow?", "/flow/publish?"), headers,
    body: { description: "Synthetic concurrent supported draft" },
  });
  expect(published.status).toBe(200);

  await page.getByRole("button", { name: "Start native development test" }).click();
  await expect(page.getByRole("alert", { name: "Simulation error" })).toContainText(/no longer current|reload/i);
  expect(observations.real.filter(item => item.path === "/api/simulate/start")).toHaveLength(1);
  expect(observations.responses.find(item => item.path === "/api/simulate/start").status).toBe(409);
  config.globalPrompt = "Private unsupported fixture guidance; never expose this in the error.";
  const unsupportedDraft = await bridge.request({
    method: "PUT", path: root.replace("/flow?", "/flow/draft?"), headers,
    body: { flow_config: config },
  });
  expect(unsupportedDraft.status).toBe(200);
  const unsupportedVersion = await bridge.request({
    method: "POST", path: root.replace("/flow?", "/flow/publish?"), headers,
    body: { description: "Synthetic unsupported draft" },
  });
  expect(unsupportedVersion.status).toBe(200);
  await page.reload();
  await expect(page.locator('.react-flow__node[data-id="query"]')).toBeVisible();
  await openNativeTest(page);
  await page.getByRole("button", { name: "Start native development test" }).click();
  await expect(page.getByRole("alert", { name: "Simulation error" })).toContainText(/global|instructions/i);
  await expect(page.getByRole("alert", { name: "Simulation error" })).not.toContainText("Private unsupported fixture guidance");
  expect(observations.responses.filter(item => item.path === "/api/simulate/start").map(item => item.status)).toEqual([409, 400]);
  await expect(page.getByLabel("Simulation runtime evidence")).toHaveCount(0);
  expect(observations.pageErrors).toEqual([]);
  expect(observations.unexpected).toEqual([]);
});
