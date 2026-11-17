#!/usr/bin/env node
// Reproducible candidate-only offline verification. The optional --browser
// mode serves the built candidate briefly on 127.0.0.1:5011 and tears it down.
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");

const frontend = path.resolve(__dirname, "..");
const args = process.argv.slice(2);
const runBrowser = args.includes("--browser");
if (args.some(arg => arg !== "--browser")) {
  console.error("Usage: node tests/offline-check.cjs [--browser]");
  process.exit(2);
}

const packageRoots = (process.env.NODE_PATH || "")
  .split(path.delimiter)
  .filter(Boolean)
  .map(root => path.resolve(root));
const modulesRoot = packageRoots.find(root =>
  fs.existsSync(path.join(root, "next", "package.json")) &&
  fs.existsSync(path.join(root, "typescript", "package.json"))
);
const playwrightRoot = packageRoots.find(root =>
  fs.existsSync(path.join(root, "@playwright", "test", "cli.js"))
);
if (!modulesRoot) {
  console.error("Set NODE_PATH to the approved installed package/cache directory containing Next and TypeScript.");
  process.exit(2);
}
if (runBrowser && !playwrightRoot) {
  console.error("Browser mode requires the separately installed @playwright/test tool exposed through NODE_PATH.");
  process.exit(2);
}

const linkPath = path.join(frontend, "node_modules");
const buildPath = path.join(frontend, ".next");
const typeBuildInfoPath = path.join(frontend, "tsconfig.tsbuildinfo");
const hadTypeBuildInfo = fs.existsSync(typeBuildInfoPath);
if (fs.existsSync(linkPath)) {
  console.error("Refusing to replace candidate node_modules; expected no candidate dependency directory.");
  process.exit(2);
}
if (fs.existsSync(buildPath)) {
  console.error("Refusing to overwrite existing candidate .next output; remove only known test output before retrying.");
  process.exit(2);
}
if (fs.readdirSync(frontend).some(name => /^\.env(?:\.|$)/.test(name))) {
  console.error("Refusing to run Next with a project .env file present; offline verification must use only its synthetic environment.");
  process.exit(2);
}

const guardPath = path.join(__dirname, "offline-network-guard.cjs");
const fontMockPath = path.join(__dirname, "offline-google-font-mocks.cjs");
const generatedRoot = path.resolve(frontend, "../../generated-artifacts");
const appPort = 5011;
const syntheticEnv = {
  PATH: process.env.PATH || "/usr/bin:/bin",
  HOME: process.env.HOME || os.tmpdir(),
  TMPDIR: os.tmpdir(),
  NODE_PATH: packageRoots.join(path.delimiter),
  NODE_OPTIONS: `--require=${guardPath}`,
  NODE_ENV: "production",
  NEXT_TELEMETRY_DISABLED: "1",
  NEXT_FONT_GOOGLE_MOCKED_RESPONSES: fontMockPath,
  NEXTAUTH_URL: `http://127.0.0.1:${appPort}`,
  NEXTAUTH_SECRET: "offline-test-only-not-a-credential-0000000000000000",
  REPL_ID: "offline-test-only",
  BACKEND_URL: "http://127.0.0.1:9",
  PORT: String(appPort),
  OFFLINE_ALLOWED_PORT: String(appPort),
  CHROMIUM_PATH: process.env.CHROMIUM_PATH || "/repl/tools/bin/chromium",
  MFA_BROWSER_BASE_URL: `http://127.0.0.1:${appPort}`,
};

let serverProcess;
let resultCode = 0;
let cleanupPromise;

function runCommand(command, commandArgs, env = syntheticEnv) {
  const result = spawnSync(command, commandArgs, {
    cwd: frontend,
    env,
    stdio: "inherit",
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(
      `Command failed with exit code ${result.status}: ${command} ${commandArgs.join(" ")}`,
    );
  }
}

function waitForServer(child, timeoutMs = 90_000) {
  const startedAt = Date.now();
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearInterval(timer);
      clearTimeout(timeout);
      child.off("exit", onExit);
      child.off("error", onError);
      error ? reject(error) : resolve();
    };
    const probe = () => {
      if (Date.now() - startedAt > timeoutMs) {
        finish(new Error("Timed out waiting for the candidate-only offline server."));
        return;
      }
      const request = http.get(`${syntheticEnv.MFA_BROWSER_BASE_URL}/login`, response => {
        response.resume();
        if (response.statusCode < 500) finish();
      });
      request.setTimeout(1000, () => request.destroy());
      request.on("error", () => {});
    };
    const onExit = (code, signal) => finish(new Error(`Candidate server exited before readiness (${code ?? signal}).`));
    const onError = error => finish(error);
    child.once("exit", onExit);
    child.once("error", onError);
    const timeout = setTimeout(() => finish(new Error("Timed out waiting for the candidate-only offline server.")), timeoutMs);
    const timer = setInterval(probe, 250);
    probe();
  });
}

async function stopServer() {
  if (!serverProcess || serverProcess.exitCode !== null) return;
  const child = serverProcess;
  const exited = new Promise(resolve => child.once("exit", resolve));
  try {
    process.kill(-child.pid, "SIGTERM");
  } catch (error) {
    if (error.code !== "ESRCH") throw error;
  }
  const grace = new Promise(resolve => setTimeout(resolve, 5000, "timeout"));
  const result = await Promise.race([exited.then(() => "exit"), grace]);
  if (result === "timeout") {
    try {
      process.kill(-child.pid, "SIGKILL");
    } catch (error) {
      if (error.code !== "ESRCH") throw error;
    }
    await exited;
  }
  serverProcess = undefined;
}

function cleanup() {
  if (cleanupPromise) return cleanupPromise;
  cleanupPromise = (async () => {
    await stopServer();
    if (fs.existsSync(linkPath) && fs.lstatSync(linkPath).isSymbolicLink()) {
      fs.rmSync(linkPath, { force: true });
    }
    fs.rmSync(buildPath, { recursive: true, force: true });
    if (!hadTypeBuildInfo) fs.rmSync(typeBuildInfoPath, { force: true });
  })();
  return cleanupPromise;
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => {
    resultCode = signal === "SIGINT" ? 130 : 143;
    cleanup().finally(() => process.exit(resultCode));
  });
}

async function main() {
  fs.symlinkSync(modulesRoot, linkPath, "dir");
  try {
    const testEnv = { ...syntheticEnv };
    const unitTests = fs.readdirSync(path.join(frontend, "tests"))
      .filter(name => /\.test\.cjs$/.test(name))
      .sort()
      .map(name => path.join("tests", name));
    if (!unitTests.length) throw new Error("No offline tests/*.test.cjs files were found.");
    runCommand(process.execPath, ["--test", ...unitTests], testEnv);
    runCommand(process.execPath, [path.join(modulesRoot, "next", "dist", "bin", "next"), "build"], testEnv);

    if (!runBrowser) return;
    fs.mkdirSync(generatedRoot, { recursive: true });
    serverProcess = spawn(process.execPath, [
      path.join(modulesRoot, "next", "dist", "bin", "next"),
      "start",
      "--hostname",
      "127.0.0.1",
      "--port",
      String(appPort),
    ], {
      cwd: frontend,
      env: testEnv,
      detached: true,
      stdio: "inherit",
    });
    await waitForServer(serverProcess);
    runCommand(
      process.execPath,
      [path.join(playwrightRoot, "@playwright", "test", "cli.js"), "test", "--config=tests/offline-playwright.config.cjs"],
      testEnv,
    );
    console.log(`Offline login screenshot saved to ${path.join(generatedRoot, "offline-login.png")}`);
  } finally {
    await cleanup();
  }
}

main().catch(error => {
  console.error(error && error.message ? error.message : "Offline verification failed.");
  resultCode = 1;
}).finally(() => {
  process.exitCode = resultCode;
});
