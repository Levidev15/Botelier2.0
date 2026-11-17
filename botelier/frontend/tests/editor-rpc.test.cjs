const test = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const { PassThrough } = require("node:stream");
const path = require("node:path");
const { connectEditorFixture, fixtureInvocation } = require("./editor-rpc.cjs");

function childFixture() {
  const child = new EventEmitter();
  child.stdin = new PassThrough();
  child.stdout = new PassThrough();
  child.exitCode = null;
  child.kill = () => {
    child.exitCode = 1;
    child.emit("exit", 1);
  };
  return child;
}

test("editor bridge preserves actual HTTP status, JSON and authentication cookie headers", async () => {
  const child = childFixture();
  const bridge = connectEditorFixture(child, { timeoutMs: 500 });
  const ready = { type: "ready", tool_id: "fixture-tool" };
  child.stdout.write(JSON.stringify(ready).slice(0, 10));
  child.stdout.write(JSON.stringify(ready).slice(10) + "\n");
  assert.deepEqual(await bridge.ready, ready);

  let request;
  child.stdin.once("data", chunk => { request = JSON.parse(chunk); });
  const result = bridge.request({
    method: "POST", path: "/api/auth/login",
    headers: { origin: "http://127.0.0.1:5011", "x-mfa-csrf": "1" },
    body: { email: "synthetic@example.test", password: "fixture-password" },
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(request.action, "request");
  assert.equal(request.method, "POST");
  assert.equal(request.headers["x-mfa-csrf"], "1");
  child.stdout.write(JSON.stringify({
    id: request.id, status: 403, body: { detail: "mfa_required" },
    headers: [["set-cookie", "synthetic=opaque; HttpOnly; SameSite=Strict; Path=/"]],
  }) + "\n");
  assert.deepEqual(await result, {
    id: request.id, status: 403, body: { detail: "mfa_required" },
    headers: [["set-cookie", "synthetic=opaque; HttpOnly; SameSite=Strict; Path=/"]],
  });
  child.emit("exit", 0);
});

test("editor bridge rejects malformed protocol without treating it as an HTTP success", async () => {
  const child = childFixture();
  const bridge = connectEditorFixture(child, { timeoutMs: 500 });
  child.stdout.write("not-json\n");
  await assert.rejects(bridge.ready, /protocol/);
});

test("fixture cleanup remains bounded when a failed process ignores graceful termination", async () => {
  const child = childFixture();
  const signals = [];
  child.kill = signal => {
    signals.push(signal);
    if (signal === "SIGKILL") {
      child.exitCode = 1;
      child.emit("exit", 1);
    }
  };
  const bridge = connectEditorFixture(child, { timeoutMs: 30 });
  child.stdout.write("not-json\n");
  await assert.rejects(bridge.ready, /protocol/);
  await assert.rejects(bridge.close(), /cleanly|timed out/);
  assert.deepEqual(signals, ["SIGTERM", "SIGKILL"]);
});

test("a prior protocol failure cannot pass cleanup even if the process later reports zero counters", async () => {
  const child = childFixture();
  child.kill = () => {};
  const bridge = connectEditorFixture(child, { timeoutMs: 50 });
  child.stdout.write('{"type":"guard_counters","blocked_attempts":0}\nnot-json\n');
  await assert.rejects(bridge.ready, /protocol/);
  child.emit("exit", 0);
  await assert.rejects(bridge.close(), /cleanly/);
});

test("editor bridge refuses pending work when its guarded backend exits", async () => {
  const child = childFixture();
  const bridge = connectEditorFixture(child, { timeoutMs: 500 });
  child.stdout.write('{"type":"ready","tool_id":"fixture-tool"}\n');
  await bridge.ready;
  const pending = bridge.request({ method: "GET", path: "/api/auth/mfa/status" });
  child.exitCode = 3;
  child.emit("exit", 3);
  await assert.rejects(pending, /exited/);
  await assert.rejects(bridge.request({ method: "GET", path: "/api/auth/mfa/status" }), /exited/);
});

test("editor bridge times out a missing backend response and closes the failed fixture", async () => {
  const child = childFixture();
  const bridge = connectEditorFixture(child, { timeoutMs: 30 });
  child.stdout.write('{"type":"ready","tool_id":"fixture-tool"}\n');
  await bridge.ready;
  await assert.rejects(bridge.request({ method: "GET", path: "/api/auth/mfa/status" }), /timed out/);
  assert.equal(child.exitCode, 1);
});

test("editor bridge rejects oversized IPC input before sending it to the backend", async () => {
  const child = childFixture();
  const bridge = connectEditorFixture(child, { timeoutMs: 500 });
  child.stdout.write('{"type":"ready","tool_id":"fixture-tool"}\n');
  await bridge.ready;
  let sent = false;
  child.stdin.on("data", () => { sent = true; });
  await assert.rejects(bridge.request({ body: "a".repeat(600_000) }), /limit/);
  assert.equal(sent, false);
  child.emit("exit", 0);
});

const repo = path.resolve(__dirname, "../../..");

test("local editor backend uses only the guarded candidate fixture and fixed synthetic environment", () => {
  const invocation = fixtureInvocation({
    repo, pythonPath: "/installed-test-tools", packageRoot: "/installed-sdk/pipecat",
    path: "/usr/bin:/bin",
  });
  assert.equal(invocation.command, "python");
  assert.deepEqual(invocation.args, [
    "-B", path.join(repo, "examples/features/botelier-flow-trial/editor_guard.py"),
    "--backend-root", path.join(repo, "botelier/backend"),
    "--package-root", "/installed-sdk/pipecat", "--stdio",
  ]);
  assert.equal(invocation.env.PYTHONPATH, "/installed-test-tools");
  assert.equal(invocation.env.BOTELIER_ENV, "development");
  assert.equal(invocation.env.BOTELIER_NATIVE_FLOWS_DEV, "1");
  assert.equal(invocation.env.DATABASE_URL, undefined);
  assert.equal(invocation.env.OPENAI_API_KEY, undefined);
});

test("CI editor backend runs the exact candidate image without network, credentials or a writable source", () => {
  const image = "voice-flow-candidate:" + "a".repeat(40);
  const invocation = fixtureInvocation({
    repo, ci: true, image, testTools: "/runner/test-tools", path: "/usr/bin:/bin",
  });
  assert.equal(invocation.command, "docker");
  assert.equal(invocation.args[invocation.args.indexOf("--network") + 1], "none");
  assert.ok(invocation.args.includes("--read-only"));
  assert.ok(invocation.args.includes("--interactive"));
  assert.ok(invocation.args.includes(image));
  assert.ok(invocation.args.includes(`${repo}/examples/features/botelier-flow-trial:/ci/trial:ro`));
  assert.ok(invocation.args.includes("/runner/test-tools:/test-tools:ro"));
  assert.ok(invocation.args.includes("/app"));
  assert.ok(invocation.args.includes("/usr/local/lib/python3.11/site-packages/pipecat"));
  assert.ok(invocation.args.includes("-i"));
  assert.equal(invocation.args.includes("--publish"), false);
  assert.equal(invocation.args.includes("-p"), false);
  assert.equal(invocation.args.some(value => value.startsWith("DATABASE_URL=")), false);
  assert.equal(invocation.args.some(value => value.startsWith("OPENAI_API_KEY=")), false);
});

test("editor image runner refuses noncandidate images and unintended local container execution", () => {
  assert.throws(() => fixtureInvocation({ repo, ci: true, image: "production:latest" }), /candidate image/);
  assert.throws(() => fixtureInvocation({ repo, image: "voice-flow-candidate:" + "a".repeat(40) }), /CI-only/);
  assert.throws(() => fixtureInvocation({ repo, ci: true }), /candidate image/);
});
