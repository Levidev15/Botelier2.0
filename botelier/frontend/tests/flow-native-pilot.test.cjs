const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

function loadModule(relative, dependencies = {}, extras = {}) {
  const source = fs.readFileSync(path.join(__dirname, "..", relative), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, {
    exports,
    URL,
    Response,
    Headers,
    console: { error() {}, warn() {} },
    require: name => {
      if (!(name in dependencies)) throw new Error(`Unexpected dependency: ${name}`);
      return dependencies[name];
    },
    ...extras,
  });
  return exports;
}

function loadSimulator() {
  return loadModule("components/flow-simulator/nativePilot.ts");
}

function validSnapshot(overrides = {}) {
  return {
    assistantId: "assistant-7",
    isDirty: false,
    currentSource: "published",
    currentVersionNumber: 12,
    publishedVersionNumber: 12,
    currentVersionId: "flow-version-12",
    ...overrides,
  };
}

test("connected API nodes render a saved endpoint without requiring a custom URL", () => {
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const empty = () => null;
  const { default: APIRequestNode } = loadModule("components/flow-editor/nodes/APIRequestNode.tsx", {
    react: React,
    "react/jsx-runtime": require("react/jsx-runtime"),
    "@xyflow/react": { Handle: empty, Position: { Top: "top", Bottom: "bottom" } },
    "lucide-react": { Globe: empty, Grip: empty, ArrowRightLeft: empty, AlertTriangle: empty },
  });
  for (const api of [
    { method: "GET", apiSource: "integration", endpointId: "rooms-get", endpointName: "Rooms endpoint" },
    { method: "GET", apiSource: "integration", endpointId: "rooms-get" },
    { method: "GET", apiSource: "custom", url: undefined },
    { method: "GET", apiSource: "custom", url: 42 },
    { method: "GET", apiSource: "custom", url: "https://example.test/rooms" },
  ]) {
    const html = renderToStaticMarkup(React.createElement(APIRequestNode, {
      data: { name: "Synthetic API", api },
    }));
    assert.match(html, /Synthetic API/);
    if (api.endpointName) assert.match(html, /Rooms endpoint/);
    if (typeof api.url === "string") assert.match(html, /example.test/);
  }
});

test("legacy remains the exact default-compatible payload and native is explicit", () => {
  const { buildSimulationStartPayload } = loadSimulator();
  assert.deepEqual(
    JSON.parse(JSON.stringify(buildSimulationStartPayload({ toolId: "tool-3" }))),
    { tool_id: "tool-3" },
  );
  assert.deepEqual(
    JSON.parse(JSON.stringify(buildSimulationStartPayload({ toolId: "tool-3", engine: "legacy" }))),
    { tool_id: "tool-3" },
  );
  assert.deepEqual(
    JSON.parse(JSON.stringify(buildSimulationStartPayload({
      toolId: "tool-3",
      engine: "native",
      snapshot: validSnapshot(),
    }))),
    {
      tool_id: "tool-3",
      assistant_id: "assistant-7",
      engine: "native_pilot",
      source: "published",
      source_version: 12,
    },
  );
});

test("native eligibility rejects drafts, edits, missing assistant, and stale version before fetch", async () => {
  const { requestSimulationStart } = loadSimulator();
  for (const snapshot of [
    validSnapshot({ currentSource: "draft" }),
    validSnapshot({ isDirty: true }),
    validSnapshot({ assistantId: "" }),
    validSnapshot({ currentVersionNumber: 0 }),
    validSnapshot({ currentVersionNumber: 11 }),
    validSnapshot({ currentVersionId: null }),
  ]) {
    let calls = 0;
    await assert.rejects(
      requestSimulationStart({
        authFetch: async () => { calls += 1; throw new Error("must not fetch"); },
        toolId: "tool-3",
        engine: "native",
        snapshot,
      }),
    );
    assert.equal(calls, 0, JSON.stringify(snapshot));
  }
});

test("native runtime identity mismatch refuses the session and deletes a returned session id", async () => {
  const { requestSimulationStart } = loadSimulator();
  const calls = [];
  const result = await requestSimulationStart({
    authFetch: async (url, options) => {
      calls.push({ url, options });
      if (url === "/api/simulate/start") {
        return new Response(JSON.stringify({
          session_id: "session-untrusted",
          messages: [{ role: "assistant", content: "not to be shown" }],
          state: {},
          runtime: {
            engine: "native_pilot", source: "published", tool_id: "tool-3", assistant_id: "assistant-7",
            account_id: "account-2", property_id: "property-4", flow_version_id: "another-version",
            version_number: 12, llm_provider: "hidden", llm_model: "hidden",
          },
        }), { status: 200 });
      }
      return new Response("", { status: 204 });
    },
    toolId: "tool-3",
    engine: "native",
    snapshot: validSnapshot(),
  });
  assert.equal(result.ok, false);
  assert.equal(result.session, null);
  assert.equal(calls.length, 2);
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    tool_id: "tool-3",
    assistant_id: "assistant-7",
    engine: "native_pilot",
    source: "published",
    source_version: 12,
  });
  assert.deepEqual(JSON.parse(JSON.stringify(calls[1])), {
    url: "/api/simulate/session/session-untrusted",
    options: { method: "DELETE" },
  });
});

test("matching native runtime evidence is returned only after exact snapshot verification", async () => {
  const { requestSimulationStart } = loadSimulator();
  const runtime = {
    engine: "native_pilot",
    source: "published",
    tool_id: "tool-3",
    assistant_id: "assistant-7",
    account_id: "account-2",
    property_id: "property-4",
    flow_version_id: "flow-version-12",
    version_number: 12,
    llm_provider: "private-provider",
    llm_model: "private-model",
  };
  let calls = 0;
  const result = await requestSimulationStart({
    authFetch: async () => {
      calls += 1;
      return new Response(JSON.stringify({
        session_id: "verified-session",
        messages: [{ role: "assistant", content: "ready" }],
        state: { collected_slots: {}, current_node: null },
        runtime,
      }), { status: 200 });
    },
    toolId: "tool-3",
    engine: "native",
    snapshot: validSnapshot(),
  });
  assert.equal(result.ok, true);
  assert.equal(calls, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(result.data.runtime)), runtime);
});

test("native runtime verification rejects each identity or source field mismatch", () => {
  const { verifyNativeRuntime } = loadSimulator();
  const snapshot = validSnapshot();
  const runtime = {
    engine: "native_pilot",
    source: "published",
    tool_id: "tool-3",
    assistant_id: "assistant-7",
    version_number: 12,
    flow_version_id: "flow-version-12",
  };
  assert.equal(verifyNativeRuntime(runtime, "tool-3", snapshot), true);
  for (const changed of [
    { engine: "legacy" },
    { source: "draft" },
    { tool_id: "other-tool" },
    { assistant_id: "other-assistant" },
    { version_number: 11 },
    { flow_version_id: "other-version" },
  ]) {
    assert.equal(verifyNativeRuntime({ ...runtime, ...changed }, "tool-3", snapshot), false);
  }
});

test("native HTTP errors are allowlisted and never trigger a legacy retry", async () => {
  const { requestSimulationStart } = loadSimulator();
  for (const detail of [
    "Native pilot requires a published flow",
    { code: "native_simulation_flow_unsupported", diagnostic: "provider-secret-must-not-display" },
  ]) {
    let calls = 0;
    await assert.rejects(
      requestSimulationStart({
        authFetch: async () => {
          calls += 1;
          return new Response(JSON.stringify({ detail }), { status: 422 });
        },
        toolId: "tool-3",
        engine: "native",
        snapshot: validSnapshot(),
      }),
      error => {
        assert.match(error.message, /published|six-node pilot/i);
        assert.doesNotMatch(error.message, /provider-secret/);
        return true;
      },
    );
    assert.equal(calls, 1);
  }
});

test("fixed native errors are actionable and unexpected structured detail is non-leaking", () => {
  const { formatNativeError } = loadSimulator();
  assert.match(formatNativeError({
    code: "native_simulation_flow_unsupported",
    diagnostic: "node_types",
  }), /exactly six-node, read-only shape/i);
  assert.match(formatNativeError({
    code: "native_simulation_flow_unsupported",
    diagnostic: "global_instructions",
  }), /global instructions/i);
  assert.match(formatNativeError({
    code: "native_simulation_flow_unsupported",
    diagnostic: "connected_get",
  }), /connected GET\/API/i);
  assert.match(formatNativeError({
    code: "native_simulation_flow_unsupported",
    diagnostic: "unlisted_provider_payload",
  }), /exactly six-node, read-only shape/i);
  assert.match(formatNativeError("Native pilot requires a published flow"), /published/i);
  const safe = formatNativeError({
    code: "provider_secret_dump",
    diagnostic: "Bearer secret-provider-token",
  });
  assert.match(safe, /could not start/i);
  assert.doesNotMatch(safe, /secret-provider-token|Bearer/);
});

test("native error allowlists reject inherited object keys instead of rendering functions or objects", () => {
  const { formatNativeError } = loadSimulator();
  for (const key of ["__proto__", "constructor", "toString", "valueOf"]) {
    for (const detail of [
      key,
      { code: key },
      { code: "native_simulation_flow_unsupported", diagnostic: key },
    ]) {
      const message = formatNativeError(detail);
      assert.equal(typeof message, "string", JSON.stringify(detail));
      assert.match(message, /could not start|six-node/i);
    }
  }
});

function createStore() {
  const reactFlow = {
    addEdge: (_connection, edges) => edges,
    applyNodeChanges: (_changes, nodes) => nodes,
    applyEdgeChanges: (_changes, edges) => edges,
  };
  const accountContext = { getAccountContext: () => null };
  const storeModule = loadModule("components/flow-editor/store.ts", {
    zustand: {
      create: initializer => {
        let state;
        const set = patch => { state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) }; };
        const get = () => state;
        state = initializer(set, get);
        return Object.assign(selector => selector ? selector(state) : state, { getState: get, setState: set });
      },
      ...reactFlow,
    },
    "@xyflow/react": reactFlow,
    "@/lib/auth/accountContext": accountContext,
  }, {
    window: { localStorage: { getItem: () => "unit-test-auth-token" } },
    localStorage: { getItem: () => "unit-test-auth-token" },
    fetch: (...args) => global.fetch(...args),
  });
  return storeModule.useFlowStore;
}

test("node measurements and selection preserve published cleanliness while graph edits require saving", () => {
  const store = createStore();
  store.getState().setIsDirty(false);
  for (const changes of [
    [{ id: "query", type: "dimensions", dimensions: { width: 240, height: 180 } }],
    [{ id: "query", type: "select", selected: true }],
  ]) {
    store.getState().onNodesChange(changes);
    assert.equal(store.getState().isDirty, false, changes[0].type);
  }
  store.getState().onEdgesChange([{ id: "start-q", type: "select", selected: true }]);
  assert.equal(store.getState().isDirty, false);
  store.getState().onNodesChange([{ id: "query", type: "position", position: { x: 40, y: 200 } }]);
  assert.equal(store.getState().isDirty, true);
  store.getState().onNodesChange([{ id: "query", type: "select", selected: false }]);
  assert.equal(store.getState().isDirty, true, "selection must not discard an actual edit");
  store.getState().setIsDirty(false);
  store.getState().onEdgesChange([{ id: "start-q", type: "remove" }]);
  assert.equal(store.getState().isDirty, true);
});

test("late version history cannot restore a cleared tool or overwrite another tool", async () => {
  const store = createStore();
  const previousFetch = global.fetch;
  let finish;
  global.fetch = () => new Promise(resolve => { finish = resolve; });
  try {
    store.setState({
      toolId: "tool-a", accountId: "account-a", versions: [{ version_number: 1 }],
    });
    const oldHistory = store.getState().loadVersions();
    store.getState().clearFlow();
    const clearedVersions = store.getState().versions;
    store.setState({
      toolId: "tool-b", accountId: "account-b", publishedVersionNumber: 3,
      hasDraft: false, versions: [{ version_number: 3 }],
    });
    finish(new Response(JSON.stringify({
      versions: [{ version_number: 99 }], published_version_number: 99, has_draft: true,
    })));
    await oldHistory;
    assert.deepEqual(JSON.parse(JSON.stringify({
      clearedVersions,
      versions: store.getState().versions,
      published: store.getState().publishedVersionNumber,
      draft: store.getState().hasDraft,
    })), {
      clearedVersions: [], versions: [{ version_number: 3 }], published: 3, draft: false,
    });
  } finally { global.fetch = previousFetch; }
});

test("newer version history wins over a slower request for the same tool", async () => {
  const store = createStore();
  const previousFetch = global.fetch;
  const pending = [];
  global.fetch = () => new Promise(resolve => { pending.push(resolve); });
  try {
    store.setState({ toolId: "tool-a", accountId: "account-a" });
    const older = store.getState().loadVersions();
    const newer = store.getState().loadVersions();
    pending[1](new Response(JSON.stringify({
      versions: [{ version_number: 5 }], published_version_number: 5, has_draft: true,
    })));
    await newer;
    pending[0](new Response(JSON.stringify({
      versions: [{ version_number: 4 }], published_version_number: 4, has_draft: false,
    })));
    await older;
    assert.equal(store.getState().publishedVersionNumber, 5);
    assert.equal(store.getState().hasDraft, true);
  } finally { global.fetch = previousFetch; }
});

for (const action of ["discardDraft", "revertToVersion"]) {
  test(`${action} cannot reload a tool after the editor has been cleared`, async () => {
    const store = createStore();
    const previousFetch = global.fetch;
    const requests = [];
    let finish;
    global.fetch = url => {
      requests.push(url);
      if (requests.length === 1) return new Promise(resolve => { finish = resolve; });
      return Promise.resolve(new Response(JSON.stringify({
        flow_config: { nodes: [], edges: [], variables: [] },
        source: "published", version_number: 1, version_id: "stale-version",
      })));
    };
    try {
      store.setState({ toolId: "tool-a", accountId: "account-a" });
      const operation = store.getState()[action](1);
      store.getState().clearFlow();
      finish(new Response("{}"));
      await operation;
      assert.equal(store.getState().toolId, null);
      assert.equal(store.getState().currentVersionId, null);
      assert.equal(store.getState().isLoading, false);
      assert.equal(requests.length, 1);
      // The same protection must still permit an ordinary current-tool action.
      global.fetch = async (url, options = {}) => new Response(JSON.stringify(
        ["POST", "DELETE"].includes(options.method) ? {} :
          url.includes("/flow/versions?") ? {
            versions: [], published_version_number: 7, has_draft: false,
          } : {
            flow_config: { nodes: [], edges: [], variables: [] },
            source: "published", version_number: 7, version_id: "current-tool-b",
            published_version_number: 7,
          },
      ));
      store.setState({ toolId: "tool-b", accountId: "account-b" });
      await store.getState()[action](1);
      assert.equal(store.getState().toolId, "tool-b");
      assert.equal(store.getState().currentVersionId, "current-tool-b");
      assert.equal(store.getState().isLoading, false);
    } finally { global.fetch = previousFetch; }
  });
}

test("store tracks version identity through load, save, publish, empty and failed cross-tool load", async () => {
  const store = createStore();
  const previousFetch = global.fetch;
  let mode = "load";
  global.fetch = async (url, options = {}) => {
    if (url.includes("/flow/versions")) {
      return new Response(JSON.stringify({ versions: [], published_version_number: 13, has_draft: false }));
    }
    if (url.includes("&version=")) {
      return new Response(JSON.stringify({
        flow_config: { nodes: [], edges: [], variables: [] },
        source: "published",
        version_number: 11,
        version_id: "historical-11",
      }));
    }
    if (options.method === "PUT") {
      return new Response(JSON.stringify({ version_number: 13, version_id: "draft-13" }));
    }
    if (options.method === "POST") {
      return new Response(JSON.stringify({ version_number: 14, version_id: "published-14" }));
    }
    if (mode === "fail") return new Response(JSON.stringify({ detail: "load failed" }), { status: 500 });
    if (mode === "empty") return new Response(JSON.stringify({ flow_config: null }));
    return new Response(JSON.stringify({
      flow_config: { nodes: [], edges: [], variables: [] },
      source: "published",
      version_number: 12,
      version_id: "loaded-12",
      published_version_number: 12,
      has_published: true,
    }));
  };

  try {
    assert.equal(store.getState().currentVersionId, null);
    await store.getState().loadFlow("tool-a", "account-a");
    assert.equal(store.getState().currentVersionId, "loaded-12");
    await store.getState().loadVersion(11);
    assert.equal(store.getState().currentVersionId, "historical-11");
    assert.equal(store.getState().currentVersionNumber, 11);
    await store.getState().loadFlow("tool-a", "account-a");
    await store.getState().saveFlow();
    assert.equal(store.getState().currentVersionId, "draft-13");
    await store.getState().publishFlow();
    assert.equal(store.getState().currentVersionId, "published-14");

    mode = "empty";
    await store.getState().loadFlow("tool-b", "account-a");
    assert.equal(store.getState().currentVersionId, null);

    mode = "load";
    await store.getState().loadFlow("tool-a", "account-a");
    assert.equal(store.getState().currentVersionId, "loaded-12");
    mode = "fail";
    await store.getState().loadFlow("tool-b", "account-a");
    assert.equal(store.getState().currentVersionId, null);

    await store.getState().loadFlow("tool-a", "account-a");
    store.getState().clearFlow();
    assert.equal(store.getState().currentVersionId, null);
  } finally {
    global.fetch = previousFetch;
  }
});

test("clearFlow invalidates a pending flow response so it cannot restore stale identity", async () => {
  const store = createStore();
  const previousFetch = global.fetch;
  let resolveFetch;
  global.fetch = () => new Promise(resolve => { resolveFetch = resolve; });
  try {
    const pendingLoad = store.getState().loadFlow("tool-pending", "account-a");
    await new Promise(resolve => setImmediate(resolve));
    store.getState().clearFlow();
    resolveFetch(new Response(JSON.stringify({
      flow_config: { nodes: [], edges: [], variables: [] },
      source: "published",
      version_number: 4,
      version_id: "stale-version-4",
      published_version_number: 4,
    })));
    await pendingLoad;
    assert.equal(store.getState().currentVersionId, null);
    assert.equal(store.getState().toolId, null);
    assert.equal(store.getState().isLoading, false);
  } finally {
    global.fetch = previousFetch;
  }
});
