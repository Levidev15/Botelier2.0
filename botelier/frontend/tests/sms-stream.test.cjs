const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");

test("SMS streaming uses the HttpOnly session, encodes account identity, and closes on cleanup", () => {
  const effects = [];
  const streams = [];
  class FixtureEventSource {
    constructor(url, options) {
      this.url = url;
      this.options = options;
      this.listeners = new Map();
      this.closed = false;
      streams.push(this);
    }
    addEventListener(name, callback) { this.listeners.set(name, callback); }
    removeEventListener(name, callback) {
      assert.equal(this.listeners.get(name), callback);
      this.listeners.delete(name);
    }
    close() { this.closed = true; }
  }
  const dependencies = {
    react: {
      ...React,
      useRef: value => ({ current: value }),
      useEffect: effect => effects.push(effect),
      useCallback: callback => callback,
    },
    "react/jsx-runtime": require("react/jsx-runtime"),
    "@/lib/auth/useAccountContext": {
      useAccountContext: () => ({ accountId: "fixture-account&not-a-param=1" }),
    },
  };
  const source = fs.readFileSync(
    path.join(__dirname, "../contexts/SMSStreamContext.tsx"), "utf8",
  );
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, {
    exports, Map, Set, EventSource: FixtureEventSource, console,
    window: {
      localStorage: {
        getItem() { throw new Error("Bearer credentials must not enter the SSE URL"); },
      },
    },
    require: name => {
      assert.ok(name in dependencies, `Unexpected dependency: ${name}`);
      return dependencies[name];
    },
  });
  exports.SMSStreamProvider({ children: null });
  assert.equal(effects.length, 1);
  const cleanup = effects[0]();
  assert.equal(streams.length, 1);
  const stream = streams[0];
  assert.equal(
    stream.url,
    "/api/sms/stream?account_id=fixture-account%26not-a-param%3D1",
  );
  assert.equal(stream.options.withCredentials, true);
  assert.deepEqual([...stream.listeners.keys()], [
    "new_message", "new_reply", "handoff_requested", "handler_changed",
  ]);
  cleanup();
  assert.equal(stream.closed, true);
  assert.equal(stream.listeners.size, 0);
});
