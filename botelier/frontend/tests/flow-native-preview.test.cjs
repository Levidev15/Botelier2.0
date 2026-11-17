const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const { TextEncoder } = require("node:util");

function loadPreview() {
  const source = fs.readFileSync(path.join(__dirname, "../components/flow-simulator/nativePreview.ts"), "utf8");
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, { exports, TextEncoder, require: name => { throw Error(`Unexpected dependency: ${name}`); } });
  return exports;
}

const pending = () => ({
  request_id: "8a34baf17d8f42df81917fa809784dda", node_id: "availability",
  source_kind: "http", expires_in_seconds: 120,
});
const plain = value => JSON.parse(JSON.stringify(value));

test("preview messages preserve raw JSON, large IDs, zero, false and decimal strings", () => {
  const { buildNativePreviewMessage } = loadPreview();
  const dataJson = '{"id":9007199254740993,"zero":0,"no":false,"price":"230.00","nested":[null]}';
  const payload = buildNativePreviewMessage({
    sessionId: "native-owned-session", pending: pending(), dataJson, statusCode: 200,
  });
  assert.deepEqual(plain(payload), {
    session_id: "native-owned-session", message: "",
    preview_result: { request_id: pending().request_id, status_code: 200, data_json: dataJson },
  });
  assert.equal("data" in payload.preview_result, false);
  assert.equal("function_call" in payload, false);
  assert.equal("function_args" in payload, false);
});

test("only bounded source-bound pending metadata reaches the UI", () => {
  const { getNativePendingPreview, hasNativePendingPreview } = loadPreview();
  const input = { ...pending(), headers: { Authorization: "private-fixture-only" }, body: "private-body" };
  const result = getNativePendingPreview({ pending_preview: input });
  assert.equal(hasNativePendingPreview({ pending_preview: input }), true);
  input.request_id = "replaced";
  assert.deepEqual(plain(result), pending());
  assert.equal(getNativePendingPreview({}), null);
  assert.equal(hasNativePendingPreview({ pending_preview: null }), false);
  assert.equal(hasNativePendingPreview({ pending_preview: "malformed" }), true);
  for (const invalid of [
    [], "pending", { ...pending(), request_id: "../other" },
    { ...pending(), node_id: "<script>run()</script>" },
    { ...pending(), source_kind: "execute_payment" },
    { ...pending(), expires_in_seconds: -1 },
    { ...pending(), expires_in_seconds: "120" },
  ]) assert.equal(getNativePendingPreview({ pending_preview: invalid }), null);
});

test("late samples cannot own a reset, replaced source, or newer in-flight request", () => {
  const { isNativePreviewCurrent } = loadPreview();
  const owner = {
    requestId: pending().request_id,
    sessionId: "native-owned-session",
    sourceKey: "tool:published:v1",
    generation: 4,
    inFlightToken: 17,
  };
  assert.equal(isNativePreviewCurrent(owner, { ...owner }), true);
  for (const changed of [
    { requestId: "new-pending-id" },
    { sessionId: "new-session" },
    { sourceKey: "another-tool:published:v1" },
    { generation: owner.generation + 1 },
    { inFlightToken: owner.inFlightToken + 1 },
  ]) {
    assert.equal(isNativePreviewCurrent(owner, { ...owner, ...changed }), false);
  }
});

test("malformed and oversized samples never become a request", () => {
  const { buildNativePreviewMessage } = loadPreview();
  for (const dataJson of ["", "{", '{"number":NaN}', JSON.stringify({ tooLarge: "😀".repeat(17_000) })]) {
    assert.throws(() => buildNativePreviewMessage({
      sessionId: "native-owned-session", pending: pending(), dataJson, statusCode: 200,
    }));
  }
  for (const statusCode of [true, "200", 199, 200.5, -1, 600]) {
    assert.throws(() => buildNativePreviewMessage({
      sessionId: "native-owned-session", pending: pending(), dataJson: "{}", statusCode,
    }));
  }
  assert.throws(() => buildNativePreviewMessage({
    sessionId: "foreign/session", pending: pending(), dataJson: "{}", statusCode: 200,
  }));
  assert.throws(() => buildNativePreviewMessage({
    sessionId: "native-owned-session", pending: { ...pending(), expires_in_seconds: 0 },
    dataJson: "{}", statusCode: 200,
  }));
  assert.throws(() => buildNativePreviewMessage({
    sessionId: "native-owned-session", pending: pending(),
    dataJson: "{}", statusCode: 200, outcome: "error",
  }));
});

test("a simulated rejection is explicit and never turns into a caller message", () => {
  const { buildNativePreviewMessage } = loadPreview();
  const payload = buildNativePreviewMessage({
    sessionId: "native-owned-session", pending: { ...pending(), source_kind: "mcp" },
    dataJson: '{"isError":true,"content":[]}', statusCode: 500, outcome: "error",
  });
  assert.equal(payload.preview_result.success, false);
  assert.equal(payload.message, "");
  assert.equal("mapped_variables" in payload.preview_result, false);
});

test("effect labels distinguish samples from real sends, Records and transfers", () => {
  const { nativePreviewEffectMessages } = loadPreview();
  const labels = nativePreviewEffectMessages([
    { node_id: "delivery", kind: "send_sms", simulated: true, data: "private-url" },
    { node_id: "save", kind: "record_create", simulated: true },
    { node_id: "transfer", kind: "transfer", simulated: true },
    { node_id: "fake", kind: "send_sms", simulated: false },
  ]);
  assert.equal(labels.length, 3);
  assert.match(labels[0].label, /not sent/i);
  assert.match(labels[1].label, /not saved/i);
  assert.match(labels[2].label, /no call/i);
  assert.equal(JSON.stringify(labels).includes("private-url"), false);
});
