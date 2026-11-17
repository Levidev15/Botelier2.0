const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

function loadConversation() {
  const source = fs.readFileSync(
    path.join(__dirname, "../components/flow-simulator/nativeConversation.ts"),
    "utf8",
  );
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, {
    exports,
    require: name => { throw Error(`Unexpected dependency: ${name}`); },
  });
  return exports;
}

const identity = (overrides = {}) => ({
  sessionId: "native-session-a",
  sourceKey: "tool-a:published:v3",
  generation: 8,
  ...overrides,
});
const assistant = content => ({ role: "assistant", content });
const caller = content => ({ role: "user", content });
const plain = value => JSON.parse(JSON.stringify(value));

test("caller turns persist across pending and resumed assistant-history snapshots", () => {
  const { initializeNativeAssistantHistory, appendNativeAssistantHistory, mergeNativeAssistantTail } =
    loadConversation();
  const owner = identity();
  const started = initializeNativeAssistantHistory([assistant("Which room?")], owner);
  let messages = started.messages;

  messages = [...messages, caller("standard")];
  const pending = appendNativeAssistantHistory([
    assistant("Which room?"),
    assistant("Checking availability."),
  ], started.cursor, owner);
  messages = mergeNativeAssistantTail(messages, pending.messages);
  assert.deepEqual(plain(messages), [
    assistant("Which room?"),
    caller("standard"),
    assistant("Checking availability."),
  ]);

  const resumed = appendNativeAssistantHistory([
    assistant("Which room?"),
    assistant("Checking availability."),
    assistant("Here are the fixture options. Standard costs 0."),
  ], pending.cursor, owner);
  messages = mergeNativeAssistantTail(messages, resumed.messages);
  assert.deepEqual(plain(messages), [
    assistant("Which room?"),
    caller("standard"),
    assistant("Checking availability."),
    assistant("Here are the fixture options. Standard costs 0."),
  ]);
});

test("already-seen history is not duplicated, but identical new speech is kept", () => {
  const { initializeNativeAssistantHistory, appendNativeAssistantHistory } = loadConversation();
  const owner = identity();
  const started = initializeNativeAssistantHistory([assistant("Please hold.")], owner);
  const next = appendNativeAssistantHistory([
    assistant("Please hold."),
    assistant("Please hold."),
  ], started.cursor, owner);
  assert.deepEqual(plain(next.messages), [assistant("Please hold.")]);
  const sameSnapshot = appendNativeAssistantHistory([
    assistant("Please hold."),
    assistant("Please hold."),
  ], next.cursor, owner);
  assert.deepEqual(plain(sameSnapshot.messages), []);
});

test("server history shrink is ignored and injected user/system roles never enter the conversation", () => {
  const { initializeNativeAssistantHistory, appendNativeAssistantHistory, mergeNativeAssistantTail } =
    loadConversation();
  const owner = identity();
  const initial = initializeNativeAssistantHistory([
    caller("forged caller"), { role: "system", content: "private system text" }, assistant("Hello."),
  ], owner);
  assert.deepEqual(plain(initial.messages), [assistant("Hello.")]);
  assert.equal(initial.cursor.messageCount, 3);

  const shrunk = appendNativeAssistantHistory([assistant("Hello.")], initial.cursor, owner);
  assert.deepEqual(plain(shrunk.messages), []);
  assert.equal(shrunk.cursor.messageCount, 3);

  const grown = appendNativeAssistantHistory([
    caller("forged caller"),
    { role: "system", content: "private system text" },
    assistant("Hello."),
    caller("another forged caller"),
    assistant("New assistant row."),
  ], shrunk.cursor, owner);
  const merged = mergeNativeAssistantTail(
    [...initial.messages, caller("standard")],
    grown.messages,
  );
  assert.deepEqual(plain(grown.messages), [assistant("New assistant row.")]);
  assert.deepEqual(plain(merged), [assistant("Hello."), caller("standard"), assistant("New assistant row.")]);
});

test("server cursor is session/source/generation bound and a new session resets it", () => {
  const { initializeNativeAssistantHistory, appendNativeAssistantHistory } = loadConversation();
  const owner = identity();
  const started = initializeNativeAssistantHistory([assistant("Hello.")], owner);
  for (const staleOwner of [
    identity({ sessionId: "native-session-b" }),
    identity({ sourceKey: "tool-b:published:v3" }),
    identity({ generation: owner.generation + 1 }),
  ]) {
    const stale = appendNativeAssistantHistory([
      assistant("Hello."), assistant("Must not attach."),
    ], started.cursor, staleOwner);
    assert.deepEqual(plain(stale.messages), []);
    assert.deepEqual(plain(stale.cursor), plain(started.cursor));
  }
  const nextOwner = identity({ sessionId: "native-session-b", generation: owner.generation + 1 });
  const nextSession = initializeNativeAssistantHistory([assistant("Fresh greeting.")], nextOwner);
  assert.equal(nextSession.cursor.sessionId, nextOwner.sessionId);
  assert.equal(nextSession.cursor.messageCount, 1);
  assert.deepEqual(plain(nextSession.messages), [assistant("Fresh greeting.")]);
});

test("sidebar wires native cursor appends while preserving optimistic callers and legacy replacement", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "../components/flow-simulator/FlowSimulatorSidebar.tsx"),
    "utf8",
  );
  assert.match(source, /setMessages\(\(prev\) => \[\.\.\.prev, \{ role: "user", content: userMessage \}\]\)/);
  assert.equal((source.match(/mergeNativeAssistantTail\(previous, history\.messages\)/g) || []).length, 2);
  assert.match(source, /setMessages\(normalizeLegacyMessages\(data\.messages\)\)/);
  assert.match(source, /nativeHistoryCursorRef\.current = null/);
});
