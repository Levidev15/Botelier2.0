const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

test("browser output remains in the ignored generated-artifacts directory", () => {
  const config = require("./offline-playwright.config.cjs");
  assert.equal(
    config.outputDir,
    path.resolve(__dirname, "../../../generated-artifacts/frontend-browser"),
  );
});

test("offline verification reports the failed child command, not a new reference error", () => {
  const source = fs.readFileSync(path.join(__dirname, "offline-check.cjs"), "utf8");
  // Execute the actual small helper without starting the runner or replacing
  // app/build behavior. Only the failed external process boundary is synthetic.
  const helper = source.match(/function runCommand\([\s\S]*?\n}/);
  assert.ok(helper, "The command helper must be available to exercise");
  const runCommand = vm.runInNewContext(`(${helper[0]})`, {
    frontend: "/synthetic-frontend",
    syntheticEnv: {},
    spawnSync: () => ({ status: 42 }),
  });
  assert.throws(
    () => runCommand("node", ["--verify-fixture"]),
    /Command failed with exit code 42: node --verify-fixture/,
  );
});
