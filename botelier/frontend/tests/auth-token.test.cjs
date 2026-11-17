const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const crypto = require("node:crypto");

function loadModule(relative, dependencies, extras = {}) {
  const source = fs.readFileSync(path.join(__dirname, "..", relative), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const exports = {};
  const sandbox = {
    exports, URL, Response, Headers, Date,
    process: { env: { NEXTAUTH_SECRET: "unit-test-only", NEXTAUTH_URL: "http://localhost:5000", BACKEND_URL: "http://backend.test" } },
    require: name => {
      if (!(name in dependencies)) throw new Error("Unexpected dependency");
      return dependencies[name];
    },
    ...extras,
  };
  vm.runInNewContext(compiled, sandbox);
  return exports;
}

function exchange({ cookie, origin = "http://localhost:5000", csrf = "1", token = "unit-test-identity" } = {}) {
  let forwarded;
  const route = loadModule("app/api/auth/token/route.ts", {
    "next-auth/jwt": { getToken: async () => token },
    "next/server": { NextResponse: { json: (body, options) => new Response(JSON.stringify(body), options) } },
    "node:crypto": crypto,
  }, {
    fetch: async (url, options) => {
      forwarded = { url, ...options };
      return new Response(JSON.stringify({ mfa_required: true }), { status: 200, headers: { "Set-Cookie": "botelier_mfa_session=rotated; HttpOnly; SameSite=Strict; Path=/" } });
    },
  });
  const request = {
    nextUrl: new URL("http://localhost:5000/api/auth/token"),
    headers: new Headers({ Origin: origin, ...(csrf ? { "X-MFA-CSRF": csrf } : {}), "Cookie": "unrelated=do-not-forward", "X-Forwarded-For": "untrusted-caller-ip" }),
    cookies: { get: name => name === "botelier_mfa_session" && cookie ? { value: cookie } : undefined },
  };
  return { route, request, forwarded: () => forwarded };
}

async function bootCustomServer({ revertNativeRoutes = false } = {}) {
  let source = fs.readFileSync(path.join(__dirname, "..", "server.js"), "utf8");
  if (revertNativeRoutes) {
    const restoredRoutes = "        '/api/auth/mfa',\n        '/api/auth/preferences'\n";
    const reverted = source.replace(restoredRoutes, "");
    if (reverted === source) throw new Error("Native route mutation was not applied");
    source = reverted;
  }

  const backendCalls = [];
  const nextCalls = [];
  let requestHandler;
  let listening = false;
  const app = {
    prepare: () => Promise.resolve(),
    getRequestHandler: () => async (req, res, parsedUrl) => {
      nextCalls.push({ url: req.url, pathname: parsedUrl.pathname });
    },
    getUpgradeHandler: () => () => {},
  };
  const fakeServer = {
    on: () => fakeServer,
    listen: (_port, _hostname, callback) => {
      listening = true;
      if (callback) callback();
      return fakeServer;
    },
  };
  const dependencies = {
    http: { createServer: handler => { requestHandler = handler; return fakeServer; } },
    url: require("node:url"),
    net: { connect: () => { throw new Error("Unexpected raw socket connection"); } },
    next: () => app,
    "http-proxy-middleware": {
      createProxyMiddleware: options => {
        assert.equal(options.target, "http://127.0.0.1:9");
        return (req, _res) => backendCalls.push({ url: req.url, method: req.method });
      },
    },
  };
  vm.runInNewContext(source, {
    require: name => {
      if (!(name in dependencies)) throw new Error(`Unexpected server dependency: ${name}`);
      return dependencies[name];
    },
    process: { env: { NODE_ENV: "production", PORT: "5011", BACKEND_URL: "http://127.0.0.1:9" } },
    console: { log: () => {}, error: () => {} },
    URL,
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(listening, true);
  assert.equal(typeof requestHandler, "function");

  async function request(url) {
    await requestHandler(
      { url, method: "GET", headers: {} },
      { writeHead: () => {}, end: () => {} },
    );
  }

  return { request, backendCalls, nextCalls };
}

async function exerciseCustomServer(server) {
  await server.request("/api/auth/mfa/status");
  await server.request("/api/auth/preferences?scope=account");
  await server.request("/api/auth/token");
  await server.request("/api/auth/session");
}

function assertCorrectCustomServerRoutes(server) {
  assert.deepEqual(server.backendCalls, [
    { url: "/api/auth/mfa/status", method: "GET" },
    { url: "/api/auth/preferences?scope=account", method: "GET" },
  ]);
  assert.deepEqual(server.nextCalls.map(call => call.pathname), [
    "/api/auth/token",
    "/api/auth/session",
  ]);
}

test("Replit exchange forwards only the exact opaque MFA session cookie", async () => {
  const cookie = "a".repeat(43);
  const harness = exchange({ cookie });
  const response = await harness.route.POST(harness.request);
  assert.equal(response.status, 200);
  assert.equal(harness.forwarded().headers.Cookie, `botelier_mfa_session=${cookie}`);
  assert.equal(harness.forwarded().headers["X-Forwarded-For"], undefined);
  assert.equal(harness.forwarded().headers.Authorization, "Bearer unit-test-identity");
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.ok(response.headers.get("set-cookie").includes("HttpOnly"));
  assert.equal((await response.json()).token, undefined);
});

test("malformed cookie values cannot inject another cookie into exchange", async () => {
  const harness = exchange({ cookie: `${"a".repeat(43)}; injected=bad` });
  await harness.route.POST(harness.request);
  assert.equal(harness.forwarded().headers.Cookie, undefined);
});

test("exchange attestation is server-only and cryptographically bound to the exact identity token", async () => {
  const first = exchange({ token: "first-unit-identity" });
  const second = exchange({ token: "second-unit-identity" });
  const firstResponse = await first.route.POST(first.request);
  const secondResponse = await second.route.POST(second.request);
  const firstMarker = first.forwarded().headers["X-Botelier-Auth-Exchange"];
  const secondMarker = second.forwarded().headers["X-Botelier-Auth-Exchange"];
  assert.equal(firstMarker, crypto.createHmac("sha256", "unit-test-only")
    .update("botelier-mfa-exchange-v1\nfirst-unit-identity").digest("hex"));
  assert.match(firstMarker, /^[a-f0-9]{64}$/);
  assert.notEqual(firstMarker, secondMarker);
  for (const response of [firstResponse, secondResponse]) {
    assert.equal(response.headers.get("X-Botelier-Auth-Exchange"), null);
    const body = await response.text();
    assert.ok(!body.includes(firstMarker) && !body.includes(secondMarker));
    assert.ok(!body.includes("unit-identity"));
  }
  assert.equal(first.route.runtime, "nodejs");
});

test("exchange rejects cross-origin/missing-CSRF requests without contacting backend", async () => {
  for (const input of [{ origin: "https://untrusted.test" }, { csrf: "" }]) {
    const harness = exchange(input);
    assert.equal((await harness.route.POST(harness.request)).status, 403);
    assert.equal(harness.forwarded(), undefined);
  }
});

test("exchange rejects missing NextAuth identity and never exposes raw JWT via GET", async () => {
  const harness = exchange({ token: null });
  assert.equal((await harness.route.POST(harness.request)).status, 401);
  assert.equal((await harness.route.GET()).status, 405);
  assert.equal(harness.forwarded(), undefined);
});

test("custom server executes MFA/preferences through backend proxy and retains NextAuth dispatch", async () => {
  const server = await bootCustomServer();
  await exerciseCustomServer(server);
  assertCorrectCustomServerRoutes(server);
});

test("custom server dispatch regression is detected when restored native routes are removed", async () => {
  const reverted = await bootCustomServer({ revertNativeRoutes: true });
  await exerciseCustomServer(reverted);
  assert.throws(() => assertCorrectCustomServerRoutes(reverted), assert.AssertionError);
});

test("rolling NextAuth JWT callbacks do not refresh primary authentication time", async () => {
  const { authOptions } = loadModule("lib/auth/config.ts", {});
  const token = await authOptions.callbacks.jwt({
    token: {}, user: { id: "test-user", authTime: 1234 }, account: { access_token: "provider-test-token" },
  });
  assert.equal(token.auth_time, 1234);
  const refreshed = await authOptions.callbacks.jwt({ token, user: undefined, account: undefined });
  assert.equal(refreshed.auth_time, 1234);
  assert.equal(authOptions.providers[0].authorization.params.max_age, 0);
});
