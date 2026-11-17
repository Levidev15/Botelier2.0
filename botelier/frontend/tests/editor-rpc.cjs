// Test transport only: Chromium -> JSON-lines -> guarded in-process ASGI.
// No application endpoint, network listener, stored token, or auth bypass.
const path = require("node:path");

const MAX_LINE_BYTES = 64 * 1024;

function fixtureInvocation({ repo, ci = false, image, pythonPath, packageRoot, testTools, path: searchPath }) {
  const env = {
    PATH: searchPath || "/usr/bin:/bin",
    HOME: "/tmp",
    PYTHONDONTWRITEBYTECODE: "1",
    PYTEST_DISABLE_PLUGIN_AUTOLOAD: "1",
    LOGURU_LEVEL: "ERROR",
    NEXTAUTH_SECRET: "botelier-editor-trial-only-synthetic-nextauth-secret-v1",
    INTEGRATION_ENCRYPTION_KEY: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    BOTELIER_ENV: "development",
    BOTELIER_NATIVE_FLOWS_DEV: "1",
    NEXTAUTH_URL: "http://127.0.0.1:5011",
    NLTK_DATA: ci ? "/opt/nltk_data" : "/home/runner/nltk_data",
  };
  if (!ci) {
    if (image) throw new Error("Editor candidate containers are CI-only.");
    if (!path.isAbsolute(pythonPath || "") || !path.isAbsolute(packageRoot || "")) {
      throw new Error("Installed test tools and the approved Pipecat source are required.");
    }
    return {
      command: "python",
      args: [
        "-B", path.join(repo, "examples/features/botelier-flow-trial/editor_guard.py"),
        "--backend-root", path.join(repo, "botelier/backend"),
        "--package-root", packageRoot, "--stdio",
      ],
      env: { ...env, PYTHONPATH: pythonPath },
    };
  }
  if (!/^voice-flow-candidate:[a-f0-9]{40}$/.test(image || "")) {
    throw new Error("An exact candidate image is required.");
  }
  if (!path.isAbsolute(testTools || "")) throw new Error("Read-only CI test tools are required.");
  return {
    command: "docker",
    args: [
      "run", "--rm", "--interactive", "--network", "none", "--read-only",
      "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m",
      "-v", `${path.join(repo, "examples/features/botelier-flow-trial")}:/ci/examples/features/botelier-flow-trial:ro`,
      "-v", `${testTools}:/test-tools:ro`,
      "--entrypoint", "env", image, "-i",
      ...Object.entries({ ...env, PATH: "/usr/local/bin:/usr/bin:/bin", PYTHONPATH: "/test-tools" })
        .map(([key, value]) => `${key}=${value}`),
      "python", "-B", "/ci/examples/features/botelier-flow-trial/editor_guard.py",
      "--backend-root", "/app",
      "--package-root", "/usr/local/lib/python3.11/site-packages/pipecat", "--stdio",
    ],
    env: { PATH: env.PATH, HOME: env.HOME },
  };
}

function connectEditorFixture(child, { timeoutMs = 30_000 } = {}) {
  let buffer = "";
  let nextId = 1;
  let isReady = false;
  let failed;
  let exited = false;
  let counters;
  let resolveReady;
  let rejectReady;
  let resolveExit;
  const pending = new Map();
  const ready = new Promise((resolve, reject) => { resolveReady = resolve; rejectReady = reject; });
  // Startup failure can arrive before a caller attaches its awaited handler.
  ready.catch(() => {});
  const exit = new Promise(resolve => { resolveExit = resolve; });

  function fail(message) {
    if (failed) return;
    failed = new Error(message);
    clearTimeout(startupTimer);
    rejectReady(failed);
    for (const entry of pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(failed);
    }
    pending.clear();
    if (!exited) child.kill("SIGTERM");
  }

  const startupTimer = setTimeout(() => fail("Editor fixture startup timed out."), timeoutMs);
  child.on("error", () => fail("Editor fixture process failed."));
  child.on("exit", code => {
    exited = true;
    clearTimeout(startupTimer);
    if (code !== 0 || !isReady || pending.size) {
      fail("Editor fixture exited before completing verification.");
    }
    resolveExit(code);
  });
  child.stdout.setEncoding("utf8");
  child.stdout.on("data", chunk => {
    buffer += chunk;
    if (Buffer.byteLength(buffer) > MAX_LINE_BYTES * 8) {
      fail("Editor fixture protocol exceeded its output limit.");
      return;
    }
    while (buffer.includes("\n") && !failed) {
      const end = buffer.indexOf("\n");
      const line = buffer.slice(0, end);
      buffer = buffer.slice(end + 1);
      let record;
      try {
        record = JSON.parse(line);
      } catch {
        fail("Editor fixture protocol was not valid JSON-lines.");
        return;
      }
      if (!record || typeof record !== "object" || Array.isArray(record)) {
        fail("Editor fixture protocol returned an invalid record.");
        return;
      }
      if (record.type === "guard_counters") {
        counters = record.blocked_attempts;
        if (counters !== 0) fail("Editor fixture guard refused an operation.");
      } else if (!isReady && record.type === "ready") {
        isReady = true;
        clearTimeout(startupTimer);
        resolveReady(record);
      } else {
        const entry = pending.get(record.id);
        if (!entry || record.type === "error") {
          fail("Editor fixture protocol returned an unexpected response.");
          return;
        }
        pending.delete(record.id);
        clearTimeout(entry.timer);
        entry.resolve(record);
      }
    }
  });

  async function send(action, body = {}) {
    await ready;
    if (failed || exited) throw failed || new Error("Editor fixture exited.");
    const id = nextId++;
    const encoded = JSON.stringify({ ...body, action, id }) + "\n";
    if (Buffer.byteLength(encoded) > MAX_LINE_BYTES) {
      throw new Error("Editor fixture request exceeded its input limit.");
    }
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => fail("Editor fixture request timed out."), timeoutMs);
      pending.set(id, { resolve, reject, timer });
      child.stdin.write(encoded, error => {
        if (error) fail("Editor fixture input failed.");
      });
    });
  }

  return {
    ready,
    request: payload => send("request", payload),
    totp: async () => (await send("totp")).code,
    async close() {
      if (!failed && !exited) {
        try {
          const result = await send("shutdown");
          if (result.blocked_attempts !== 0) fail("Editor fixture guard refused an operation.");
          child.stdin.end();
        } catch {
          fail("Editor fixture shutdown failed.");
        }
      }
      let shutdownTimer;
      try {
        const code = await Promise.race([
          exit,
          new Promise((_, reject) => {
            shutdownTimer = setTimeout(() => {
              fail("Editor fixture shutdown timed out.");
              if (!exited) child.kill("SIGKILL");
              reject(new Error("Editor fixture shutdown timed out."));
            }, timeoutMs);
          }),
        ]);
        if (code !== 0 || counters !== 0 || failed) {
          throw new Error("Editor fixture did not exit cleanly with zero guard refusals.");
        }
        return { blocked_attempts: counters };
      } finally {
        clearTimeout(shutdownTimer);
      }
    },
  };
}

module.exports = { connectEditorFixture, fixtureInvocation };
