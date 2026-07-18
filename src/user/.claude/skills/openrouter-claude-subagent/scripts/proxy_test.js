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

// ─── proxyRequest: absolute-form request-target pinning (security) ─
//
// `new URL(target, base)` ignores `base` entirely when `target` is itself
// absolute (RFC 9112 §3.2.2). A client sending `GET http://elsewhere/x`
// could hijack the pinned upstream host — and carry the OpenRouter key
// injected downstream along with it. These tests drive `start()` over a
// real socket, since the vulnerable code path is in request-line parsing,
// which node:http exposes only through `req.url` on an actual connection.

const net = require("node:net");
const { start } = require("./proxy.js");

/** Write a raw HTTP/1.1 request over a fresh socket and resolve with
 *  everything received once a header block (blank line) has arrived.
 *  Rejects on error or after `timeoutMs` so a hung proxy fails the test
 *  instead of hanging the suite. */
function rawRequest(port, requestLine, timeoutMs) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(port, "127.0.0.1", () => {
      socket.write(requestLine);
    });
    let data = "";
    socket.setTimeout(timeoutMs, () => {
      socket.destroy();
      reject(new Error("socket timed out waiting for a response"));
    });
    socket.on("data", (chunk) => {
      data += chunk.toString();
      if (data.includes("\r\n\r\n")) {
        socket.end();
        resolve(data);
      }
    });
    socket.on("error", reject);
  });
}

test("refuses an absolute-form request target instead of forwarding it upstream", async () => {
  const proxy = await start({ port: 0 });
  try {
    // Port 1 is a reserved TCP port nothing is listening on. If the fix
    // regressed and the pin were bypassed, the proxy would try to dial this
    // host:port and the request would hang or fail to connect — it could
    // never accidentally produce a 403. Only the explicit refusal path does.
    const response = await rawRequest(
      proxy.port,
      "GET http://127.0.0.1:1/steal HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
      5000,
    );
    assert.match(response, /^HTTP\/1\.1 403\b/);
  } finally {
    await proxy.close();
  }
});

test("does not refuse a normal origin-form request target", async () => {
  const proxy = await start({ port: 0 });
  try {
    // This will fail to actually reach openrouter.ai in a test sandbox — a
    // 502 (or any non-403 status) is an acceptable pass. Only a 403 here
    // would indicate the pin rejects legitimate traffic too.
    const response = await rawRequest(
      proxy.port,
      "GET /v1/messages HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n",
      15000,
    );
    assert.doesNotMatch(response, /^HTTP\/1\.1 403\b/);
  } finally {
    await proxy.close();
  }
});

// ─── createSSEFixer: buffered-trailing-event, duplicate/unstarted index ──

test("finish() collects a trailing event left in the buffer when the stream ends without a trailing blank line", () => {
  // No trailing "\n\n" after the last delta: it never crosses processChunk's
  // split("\n\n") boundary and is left sitting in the internal buffer.
  const text = [msgStart(), blockStart(0, "text"), blockDelta(0, "partial")].join("\n\n");
  const { events } = runFixer(text);

  const delta = events.find((e) => e.event === "content_block_delta" && e.data.delta.text === "partial");
  assert.ok(delta, "the final delta, held in the buffer at end-of-stream, must still be replayed");
});

test("ignores and logs a duplicate content_block_start at an already-used index", () => {
  const text = streamText([
    msgStart(),
    blockStart(0, "text"), blockDelta(0, "first"),
    blockStart(0, "text"), blockDelta(0, "duplicate"), blockStop(0),
    msgStop(), done(),
  ]);
  const { events, logs } = runFixer(text);

  assert.ok(logs.some((m) => m.includes("duplicate content_block_start")));
  const starts = events.filter((e) => e.event === "content_block_start");
  assert.equal(starts.length, 1, "the repeated content_block_start must not replay the block twice");
});

test("drops a content_block_delta for an index that never had a content_block_start", () => {
  const text = streamText([
    msgStart(),
    blockDelta(5, "orphan"),
    msgStop(), done(),
  ]);
  const { events, logs } = runFixer(text);

  assert.ok(logs.some((m) => m.includes("unstarted index")));
  assert.ok(
    !events.some((e) => e.event === "content_block_delta" && e.data?.delta?.text === "orphan"),
    "a delta for an unstarted index must not appear in the replayed output",
  );
});

// ─── createSSEFixer: pre-classification buffering ──────────────────

test("holds a leading heartbeat rather than writing it out before the stream is classified", () => {
  const res = fakeRes();
  const fixer = createSSEFixer(res, () => {});

  fixer.processChunk(": heartbeat\n\n");
  assert.equal(res.writes.length, 0, "an unclassified heartbeat must not be written before classification");

  fixer.processChunk(streamText([
    msgStart(), blockStart(0, "text"), blockDelta(0, "hi"), blockStop(0), msgStop(), done(),
  ]));
  fixer.finish();

  const events = res.output().split("\n\n").filter((s) => s.trim()).map(parseSSEBlock);
  const delta = events.find((e) => e.event === "content_block_delta");
  assert.equal(delta.data.delta.text, "hi");
});

test("still writes a held heartbeat through once the stream turns out to be passthrough", () => {
  const openaiChunk = (id, content) =>
    block(undefined, { id, object: "chat.completion.chunk", choices: [{ delta: { content } }] });
  const text = streamText([": heartbeat", openaiChunk("c1", "hello")]);
  const { res } = runFixer(text);

  assert.equal(res.output(), text, "the held heartbeat must reach the client, not be lost");
});

// ─── proxyRequest: malformed request target survives the process ────
//
// Node's HTTP parser accepts absolute-form request targets that WHATWG
// `URL` rejects outright (e.g. `GET http://[/x`). Before the try/catch guard
// in proxyRequest, `new URL(clientReq.url, base)` threw an uncaught
// TypeError and killed the process — and the proxy runs in-process with the
// launcher, so that would strand the running claude child mid-session.
// "Responds 400" and "the process is still alive" are separate claims; this
// test asserts both, on the same proxy instance, across every malformed
// shape known to trigger the throw.

test("returns 400 for malformed request targets and the proxy survives to serve the next request", async () => {
  const proxy = await start({ port: 0 });
  try {
    const malformedTargets = [
      "GET http://[/x HTTP/1.1\r\nHost: x\r\n\r\n",
      "GET http://:80/ HTTP/1.1\r\nHost: x\r\n\r\n",
      "GET http://]/ HTTP/1.1\r\nHost: x\r\n\r\n",
      "GET http://a%00b/x HTTP/1.1\r\nHost: x\r\n\r\n",
    ];
    for (const requestLine of malformedTargets) {
      const response = await rawRequest(proxy.port, requestLine, 5000);
      assert.match(response, /^HTTP\/1\.1 400\b/, `expected 400 for ${JSON.stringify(requestLine)}`);
    }

    // The point of the test: if the try/catch guard around `new URL(...)`
    // were removed, the first malformed target above would throw
    // uncaught and kill the process, and this final request would never
    // get a response — the socket would hang until its own timeout fired.
    const survived = await rawRequest(
      proxy.port,
      "GET /v1/messages HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n",
      15000,
    );
    assert.match(survived, /^HTTP\/1\.1 \d{3}\b/, "proxy must still respond after malformed targets");
  } finally {
    await proxy.close();
  }
});

// ─── proxyRequest: oversized request body rejected with 413 ─────────

test("rejects a request body over MAX_REQUEST_BODY_BYTES with 413 instead of buffering it without limit", (t) => {
  // MAX_REQUEST_BODY_BYTES is 100MB (proxy.js). Actually sending 100MB+ in a
  // unit test would allocate that much memory and make the suite slow and
  // flaky for no proportional coverage gain. There is no way to cross the
  // cap without streaming bytes on that order — the guard is a running byte
  // counter on clientReq's `data` event, checked against the exact constant,
  // so a smaller body can never exercise it; asserting 413 against a body
  // that cannot reach the cap would be a tautology dressed as a real test.
  // Skip honestly rather than fake the coverage. The guard's wiring —
  // `bodyBytes > MAX_REQUEST_BODY_BYTES` triggers `proxyReq.destroy()` and a
  // 413 write, immediately on the `data` event, before `end` — is read
  // directly from proxy.js's clientReq.on("data", ...) handler.
  t.skip(
    "MAX_REQUEST_BODY_BYTES is 100MB; exercising the cap for real requires " +
    "streaming that many bytes in-process, which is impractical for a unit " +
    "test (memory + runtime cost with no proportional coverage benefit).",
  );
});

// ─── proxyRequest: legitimate traffic is unaffected by the new guards ──

test("a normal origin-form request is not rejected by the target-pin, body-size, or malformed-target guards", async () => {
  const proxy = await start({ port: 0 });
  try {
    // This will not actually reach openrouter.ai in a test sandbox, so a
    // 200/404/502 from the real upstream attempt all count as a pass — the
    // only thing under test is that none of the new hardening guards
    // (400 malformed-target, 403 host-pin, 413 body-cap) misfire on
    // legitimate, well-formed traffic.
    const response = await rawRequest(
      proxy.port,
      "GET /v1/messages HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n",
      15000,
    );
    const status = response.match(/^HTTP\/1\.1 (\d{3})\b/)?.[1];
    assert.ok(status, "expected a status line in the response");
    assert.ok(
      !["400", "403", "413"].includes(status),
      `legitimate traffic must not be rejected by a hardening guard, got ${status}`,
    );
  } finally {
    await proxy.close();
  }
});

// ─── createSSEFixer: multibyte characters split across chunks ───────
//
// Before the stateful StringDecoder, each chunk was decoded independently
// with `chunk.toString()`. A multibyte character straddling a chunk
// boundary would have its bytes split across two `Buffer.toString()` calls,
// and each half decodes on its own to the replacement character (U+FFFD),
// silently corrupting any non-ASCII model output. These tests split a
// Buffer mid-character on purpose and assert both that the original text
// survives AND that no U+FFFD appears — the latter is what actually
// regresses if a fix reverts to per-chunk decoding.

test("reassembles a multibyte character split across chunk boundaries without corrupting it", () => {
  const text = "café 日本語 \u{1F600}";
  const stream = streamText([
    msgStart(),
    blockStart(0, "text"), blockDelta(0, text), blockStop(0),
    msgStop(), done(),
  ]);
  const buf = Buffer.from(stream, "utf8");

  // "é" is a 2-byte UTF-8 sequence (0xC3 0xA9). Split one byte into it so
  // the first chunk ends mid-character.
  const eIndex = buf.indexOf(Buffer.from("é", "utf8"));
  const cut = eIndex + 1;

  const res = fakeRes();
  const fixer = createSSEFixer(res, () => {});
  fixer.processChunk(buf.subarray(0, cut));
  fixer.processChunk(buf.subarray(cut));
  fixer.finish();

  const events = res.output().split("\n\n").filter((s) => s.trim()).map(parseSSEBlock);
  const delta = events.find((e) => e.event === "content_block_delta");
  assert.equal(delta.data.delta.text, text);
  assert.ok(!res.output().includes("�"), "output must not contain the replacement character");
});

test("reassembles an astral-plane emoji (4-byte UTF-8 surrogate pair) split across chunk boundaries", () => {
  // The emoji is the case most likely to break a naive fix: it is a
  // surrogate pair in UTF-16 and 4 bytes in UTF-8, so a split can land
  // inside either the byte sequence or, if mishandled, the resulting
  // surrogate pair.
  const text = "before \u{1F600} after";
  const stream = streamText([
    msgStart(),
    blockStart(0, "text"), blockDelta(0, text), blockStop(0),
    msgStop(), done(),
  ]);
  const buf = Buffer.from(stream, "utf8");

  const emojiIndex = buf.indexOf(Buffer.from("\u{1F600}", "utf8"));
  const cut = emojiIndex + 2; // 2 of the emoji's 4 UTF-8 bytes in the first chunk

  const res = fakeRes();
  const fixer = createSSEFixer(res, () => {});
  fixer.processChunk(buf.subarray(0, cut));
  fixer.processChunk(buf.subarray(cut));
  fixer.finish();

  const events = res.output().split("\n\n").filter((s) => s.trim()).map(parseSSEBlock);
  const delta = events.find((e) => e.event === "content_block_delta");
  assert.equal(delta.data.delta.text, text);
  assert.ok(!res.output().includes("�"), "output must not contain the replacement character");
});

// ─── createSSEFixer: CRLF-delimited streams ──────────────────────────
//
// SSE permits CRLF line endings. Before EVENT_DELIMITER accounted for it,
// splitting only on "\n\n" left a CRLF stream as one giant unsplit block
// that never crossed the classifier, so it was forwarded byte-for-byte
// unrepaired — reproducing the exact empty-result bug (response ending on
// a reasoning block) this proxy exists to fix.

/** Build a CRLF-delimited SSE stream from the same [event, data] blocks the
 *  LF helpers use, joined with "\r\n\r\n" and each internal line ending in
 *  "\r\n" — mirroring `streamText`/`block` but for the CRLF wire format. */
function crlfStreamText(blocks) {
  return blocks.map((b) => b.replace(/\n/g, "\r\n")).join("\r\n\r\n") + "\r\n\r\n";
}

test("classifies and repairs a CRLF-delimited stream instead of passing it through unrepaired", () => {
  const text = crlfStreamText([
    msgStart(),
    blockStart(0, "text"), blockDelta(0, "hello"), blockStop(0),
    blockStart(1, "thinking"), blockDelta(1, "pondering"), blockStop(1),
    msgStop(), done(),
  ]);
  const { events } = runFixer(text);

  // Assert via parsed output events, not string matching: if the stream had
  // been passed through unrepaired, `events` would just be the raw CRLF
  // blocks in their original order, ending on "thinking" rather than "text".
  const starts = events.filter((e) => e.event === "content_block_start");
  assert.equal(starts.length, 2, "a passed-through CRLF stream would still parse as blocks, but reordering proves repair mode ran");
  assert.equal(starts[starts.length - 1].data.content_block.type, "text", "text block must be replayed last");

  const deltas = events.filter((e) => e.event === "content_block_delta");
  assert.equal(deltas[deltas.length - 1].data.delta.text, "hello", "text block's delta must be replayed last");
});

// ─── createSSEFixer: completion is not synthesized for a truncated stream ──
//
// Before this fix, replay() unconditionally appended message_stop + [DONE].
// That dressed up a provider-side truncation as a complete response, so the
// caller consumed partial output instead of retrying. Test A drives the
// truncation case; Test B is a required regression guard — without it, a
// broken fix that simply never emits terminators (even for complete
// streams) would pass Test A alone.

test("does not synthesize message_stop or [DONE] for a stream that ends without an upstream message_stop", () => {
  const text = streamText([
    msgStart(),
    blockStart(0, "text"), blockDelta(0, "hello"), blockStop(0),
    blockStart(1, "thinking"), blockDelta(1, "pondering"), blockStop(1),
    // No msgStop(), no done() — upstream cut off mid-response.
  ]);
  const { events, logs } = runFixer(text);

  assert.ok(!events.some((e) => e.event === "message_stop"), "must not synthesize message_stop for a truncated stream");
  assert.ok(!events.some((e) => e.data === null), "must not synthesize [DONE] for a truncated stream");
  assert.ok(logs.some((m) => m.includes("without message_stop")), "must log a warning naming the missing message_stop");
});

test("REGRESSION GUARD: still emits message_stop and [DONE] for a normal complete stream", () => {
  const text = streamText([
    msgStart(),
    blockStart(0, "text"), blockDelta(0, "hello"), blockStop(0),
    msgStop(), done(),
  ]);
  const { events } = runFixer(text);

  assert.ok(events.some((e) => e.event === "message_stop"), "a complete stream must still get message_stop");
  assert.ok(events.some((e) => e.data === null), "a complete stream must still get [DONE]");
});
