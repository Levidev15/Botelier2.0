const path = require("node:path");

module.exports = {
  testDir: path.join(__dirname, "browser"),
  outputDir: path.resolve(__dirname, "../../../generated-artifacts/frontend-browser"),
  testMatch: process.env.NATIVE_EDITOR_BROWSER === "1"
    ? ["mfa.spec.js", "native-editor.spec.js"]
    : "mfa.spec.js",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.MFA_BROWSER_BASE_URL || "http://127.0.0.1:5011",
    headless: true,
    trace: "off",
    screenshot: "off",
    launchOptions: {
      executablePath: process.env.CHROMIUM_PATH || "/repl/tools/bin/chromium",
      args: ["--no-sandbox"],
    },
  },
};
