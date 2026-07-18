// Unit tests for proxy.js — built-in node:test / node:assert only, no deps.
//
// Scope: the four pure/testable exports (createSSEFixer, splitMixedMessages,
// parseSSEBlock, buildProxyHeaders). `start` opens real sockets and is
// covered elsewhere.

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  createSSEFixer,
  splitMixedMessages,
  parseSSEBlock,
  buildProxyHeaders,
} = require("./proxy.js");

// ─── SSE fixtures ──────────────────────────────────────────────────
//
// An SSE "block" is one `event:`/`data:` pair; blocks are joined by blank
// lines. Building them by hand in every test would bury intent in string
// soup, so a block is described as [eventName, dataObject] and joined here.

/** One SSE block: "event: X\ndata: {...}". Omit `event` for a bare
 *  `data:`-only line (OpenAI-format streams carry no event name). */
function block(event, data) {
  const lines = [];
  if (event) lines.push(`event: ${event}`);
  if (data !== undefined) lines.push(`data: ${typeof data === "string" ? data : JSON.stringify(data)}`);
  return lines.join("\n");
}

/** Join blocks into a full SSE stream body, terminated so the fixer's
 *  internal split-on-"\n\n" leaves no dangling buffer. */
function streamText(blocks) {
  return blocks.join("\n\n") + "\n\n";
}

const msgStart = () => block("message_start", { type: "message_start", message: { id: "msg_1" } });
const msgDelta = () => block("message_delta", { type: "message_delta", delta: { stop_reason: "end_turn" } });
const msgStop = () => block("message_stop", { type: "message_stop" });
const done = () => block(undefined, "[DONE]");
const blockStart = (index, type) =>
  block("content_block_start", { type: "content_block_start", index, content_block: { type } });
const blockDelta = (index, text) =>
  block("content_block_delta", { type: "content_block_delta", index, delta: { type: "text_delta", text } });
const blockStop = (index) => block("content_block_stop", { type: "content_block_stop", index });

/** Fake `res`: records writes, tracks whether `end()` was called. */
function fakeRes() {
  const writes = [];
  return {
    writes,
    ended: false,
    write(s) { writes.push(s); },
    end() { this.ended = true; },
    output() { return writes.join(""); },
  };
}

/** Run a full stream through the fixer in one shot and return the parsed
 *  output events plus the fixture (res, logs). */
function runFixer(text) {
  const res = fakeRes();
  const logs = [];
  const fixer = createSSEFixer(res, (msg) => logs.push(msg));
  fixer.processChunk(text);
  fixer.finish();
  const events = res.output()
    .split("\n\n")
    .filter((s) => s.trim().length > 0)
    .map(parseSSEBlock);
  return { events, res, logs };
}

// ─── createSSEFixer: repair path ───────────────────────────────────

test("moves the most recent text block to the end when the stream ends on a thinking block", () => {
  const text = streamText([
    msgStart(),
    blockStart(0, "text"), blockDelta(0, "hello"), blockStop(0),
    blockStart(1, "thinking"), blockDelta(1, "pondering"), blockStop(1),
    msgDelta(), msgStop(), done(),
  ]);
  const { events } = runFixer(text);

  const starts = events.filter((e) => e.event === "content_block_start");
  assert.equal(starts.length, 2);
  assert.equal(starts[0].data.content_block.type, "thinking");
  assert.equal(starts[1].data.content_block.type, "text");
});

test("renumbers block indexes to their final replay position, not their original index", () => {
  const text = streamText([
    msgStart(),
    blockStart(0, "text"), blockDelta(0, "hello"), blockStop(0),
    blockStart(1, "thinking"), blockDelta(1, "pondering"), blockStop(1),
    msgDelta(), msgStop(), done(),
  ]);
  const { events } = runFixer(text);

  // thinking (originally index 1) now replays first, at position 0;
  // text (originally index 0) now replays last, at position 1.
  const thinkingDelta = events.find((e) => e.event === "content_block_delta" && e.data.delta.text === "pondering");
  const textDelta = events.find((e) => e.event === "content_block_delta" && e.data.delta.text === "hello");
  assert.equal(thinkingDelta.data.index, 0);
  assert.equal(textDelta.data.index, 1);
});

test("does not reorder a stream that already ends on a text block", () => {
  const text = streamText([
    msgStart(),
    blockStart(0, "thinking"), blockDelta(0, "pondering"), blockStop(0),
    blockStart(1, "text"), blockDelta(1, "hello"), blockStop(1),
    msgDelta(), msgStop(), done(),
  ]);
  const { events } = runFixer(text);

  const starts = events.filter((e) => e.event === "content_block_start");
  assert.equal(starts[0].data.content_block.type, "thinking");
  assert.equal(starts[0].data.index, 0);
  assert.equal(starts[1].data.content_block.type, "text");
  assert.equal(starts[1].data.index, 1);
});

test("treats a stream ending on redacted_thinking as reasoning and reorders it", () => {
  const text = streamText([
    msgStart(),
    blockStart(0, "text"), blockDelta(0, "hello"), blockStop(0),
    blockStart(1, "redacted_thinking"), blockStop(1),
    msgStop(), done(),
  ]);
  const { events } = runFixer(text);

  const starts = events.filter((e) => e.event === "content_block_start");
  assert.equal(starts[0].data.content_block.type, "redacted_thinking");
  assert.equal(starts[1].data.content_block.type, "text");
});

test("logs a warning and still emits output when reasoning ends the stream with no text block to promote", () => {
  const text = streamText([
    msgStart(),
    blockStart(0, "thinking"), blockDelta(0, "pondering"), blockStop(0),
    msgStop(), done(),
  ]);
  const { events, logs } = runFixer(text);

  assert.ok(logs.some((m) => m.includes("no text block to promote")));
  const starts = events.filter((e) => e.event === "content_block_start");
  assert.equal(starts.length, 1);
  assert.equal(starts[0].data.content_block.type, "thinking");
});

test("moves the most recently arrived text block, not the first one, when several exist", () => {
  const text = streamText([
    msgStart(),
    blockStart(0, "text"), blockDelta(0, "first"), blockStop(0),
    blockStart(1, "text"), blockDelta(1, "second"), blockStop(1),
    blockStart(2, "thinking"), blockStop(2),
    msgStop(), done(),
  ]);
  const { events } = runFixer(text);

  const deltas = events.filter((e) => e.event === "content_block_delta");
  // "second" arrived most recently among the text blocks — it should be last.
  assert.equal(deltas[deltas.length - 1].data.delta.text, "second");
  const starts = events.filter((e) => e.event === "content_block_start");
  assert.equal(starts[starts.length - 1].data.content_block.type, "text");
});

test("output ends with exactly one regenerated message_stop and [DONE], even when upstream sent them too", () => {
  const text = streamText([
    msgStart(),
    blockStart(0, "text"), blockDelta(0, "hello"), blockStop(0),
    msgStop(), done(),
  ]);
  const { events } = runFixer(text);

  const stops = events.filter((e) => e.event === "message_stop");
  assert.equal(stops.length, 1);
  assert.equal(events[events.length - 1].data, null); // "[DONE]" is not JSON
  assert.equal(events[events.length - 2].event, "message_stop");
});

test("emits preamble events before content blocks and tail events after them", () => {
  const text = streamText([
    msgStart(),
    blockStart(0, "text"), blockDelta(0, "hello"), blockStop(0),
    msgDelta(),
    msgStop(), done(),
  ]);
  const { events } = runFixer(text);

  const order = events.map((e) => e.event);
  assert.equal(order[0], "message_start");
  const deltaPos = order.indexOf("message_delta");
  const blockStartPos = order.indexOf("content_block_start");
  assert.ok(blockStartPos < deltaPos, "content block must precede the tail message_delta");
});

test("calls res.end() when finish() runs", () => {
  const text = streamText([
    msgStart(), blockStart(0, "text"), blockDelta(0, "hi"), blockStop(0), msgStop(), done(),
  ]);
  const { res } = runFixer(text);
  assert.equal(res.ended, true);
});

// ─── createSSEFixer: passthrough path ──────────────────────────────

test("passes an OpenAI-format stream through unmodified without buffering", () => {
  const openaiChunk = (id, content) =>
    block(undefined, { id, object: "chat.completion.chunk", choices: [{ delta: { content } }] });
  const text = streamText([openaiChunk("c1", "hello"), openaiChunk("c2", " world")]);

  const res = fakeRes();
  const fixer = createSSEFixer(res);
  fixer.processChunk(text);
  fixer.finish();

  assert.equal(res.output(), text);
});

test("leading blank lines and heartbeat comments do not prevent classifying a real message_start as repair", () => {
  const text = streamText([
    block(undefined, undefined), // blank block
    ": heartbeat",
    msgStart(),
    blockStart(0, "text"), blockDelta(0, "hello"), blockStop(0),
    blockStart(1, "thinking"), blockStop(1),
    msgStop(), done(),
  ]);
  const { events } = runFixer(text);

  // If the heartbeat had wrongly classified the stream as passthrough, the
  // thinking-ending stream would never be reordered.
  const starts = events.filter((e) => e.event === "content_block_start");
  assert.equal(starts[starts.length - 1].data.content_block.type, "text");
});

test("reassembles an event split across chunk boundaries", () => {
  const text = streamText([
    msgStart(),
    blockStart(0, "text"), blockDelta(0, "hello world"), blockStop(0),
    msgStop(), done(),
  ]);
  // Cut mid-way through the content_block_delta block, not on a "\n\n" boundary.
  const cut = text.indexOf('"hello world"') + 4;
  const res = fakeRes();
  const logs = [];
  const fixer = createSSEFixer(res, (m) => logs.push(m));
  fixer.processChunk(text.slice(0, cut));
  fixer.processChunk(text.slice(cut));
  fixer.finish();

  const events = res.output().split("\n\n").filter((s) => s.trim()).map(parseSSEBlock);
  const delta = events.find((e) => e.event === "content_block_delta");
  assert.equal(delta.data.delta.text, "hello world");
});

// ─── splitMixedMessages ─────────────────────────────────────────────

test("splits a user message mixing tool_result and text into tool_result-first, then a new text-only user message", () => {
  const messages = [
    { role: "user", content: [
      { type: "tool_result", tool_use_id: "t1", content: "ok" },
      { type: "text", text: "follow up" },
    ] },
  ];
  splitMixedMessages(messages);

  assert.equal(messages.length, 2);
  assert.deepEqual(messages[0].content, [{ type: "tool_result", tool_use_id: "t1", content: "ok" }]);
  assert.equal(messages[1].role, "user");
  assert.deepEqual(messages[1].content, [{ type: "text", text: "follow up" }]);
});

test("leaves a user message with only tool_result blocks untouched", () => {
  const messages = [
    { role: "user", content: [{ type: "tool_result", tool_use_id: "t1", content: "ok" }] },
  ];
  splitMixedMessages(messages);
  assert.equal(messages.length, 1);
  assert.equal(messages[0].content.length, 1);
});

test("leaves a user message with only text blocks untouched", () => {
  const messages = [
    { role: "user", content: [{ type: "text", text: "hi" }] },
  ];
  splitMixedMessages(messages);
  assert.equal(messages.length, 1);
  assert.deepEqual(messages[0].content, [{ type: "text", text: "hi" }]);
});

test("never splits an assistant message regardless of content shape", () => {
  const messages = [
    { role: "assistant", content: [
      { type: "tool_result", tool_use_id: "t1", content: "ok" },
      { type: "text", text: "hi" },
    ] },
  ];
  splitMixedMessages(messages);
  assert.equal(messages.length, 1);
  assert.equal(messages[0].content.length, 2);
});

test("splits multiple mixed messages in one array without corrupting indexes", () => {
  const messages = [
    { role: "user", content: [
      { type: "tool_result", tool_use_id: "t1", content: "r1" },
      { type: "text", text: "u1" },
    ] },
    { role: "assistant", content: [{ type: "text", text: "reply" }] },
    { role: "user", content: [
      { type: "tool_result", tool_use_id: "t2", content: "r2" },
      { type: "text", text: "u2" },
    ] },
  ];
  splitMixedMessages(messages);

  assert.equal(messages.length, 5);
  assert.deepEqual(messages.map((m) => m.role), ["user", "user", "assistant", "user", "user"]);
  assert.deepEqual(messages[0].content, [{ type: "tool_result", tool_use_id: "t1", content: "r1" }]);
  assert.deepEqual(messages[1].content, [{ type: "text", text: "u1" }]);
  assert.deepEqual(messages[2].content, [{ type: "text", text: "reply" }]);
  assert.deepEqual(messages[3].content, [{ type: "tool_result", tool_use_id: "t2", content: "r2" }]);
  assert.deepEqual(messages[4].content, [{ type: "text", text: "u2" }]);
});

test("returns non-array input without throwing", () => {
  assert.doesNotThrow(() => splitMixedMessages(undefined));
  assert.doesNotThrow(() => splitMixedMessages({ role: "user" }));
  assert.equal(splitMixedMessages(undefined), undefined);
});

// ─── parseSSEBlock ──────────────────────────────────────────────────

test("parses event and JSON data lines into { event, data }", () => {
  const parsed = parseSSEBlock('event: message_start\ndata: {"type":"message_start"}');
  assert.equal(parsed.event, "message_start");
  assert.deepEqual(parsed.data, { type: "message_start" });
});

test("yields null data for a non-JSON payload instead of throwing", () => {
  const parsed = parseSSEBlock("data: [DONE]");
  assert.equal(parsed.data, null);
  assert.doesNotThrow(() => parseSSEBlock("data: [DONE]"));
});

// ─── buildProxyHeaders ──────────────────────────────────────────────

test("strips host and hop-by-hop headers while passing everything else through, including authorization", () => {
  const original = {
    host: "example.com",
    connection: "keep-alive",
    "transfer-encoding": "chunked",
    authorization: "Bearer xyz",
    "content-type": "application/json",
  };
  const result = buildProxyHeaders(original);

  assert.equal(result.host, undefined);
  assert.equal(result.connection, undefined);
  assert.equal(result["transfer-encoding"], undefined);
  assert.equal(result.authorization, "Bearer xyz");
  assert.equal(result["content-type"], "application/json");
});

test("does not mutate the input headers object", () => {
  const original = { host: "example.com", authorization: "Bearer xyz" };
  buildProxyHeaders(original);
  assert.equal(original.host, "example.com");
  assert.equal(original.authorization, "Bearer xyz");
});
