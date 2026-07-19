// OpenRouter SSE-repair proxy.
//
// Forwards Anthropic-protocol traffic to OpenRouter unmodified, with one
// repair: an assistant response must not END on a `thinking` or
// `redacted_thinking` block. When it does, Claude Code yields an empty
// result with exit 0 and no stderr while still billing the tokens. The fix
// moves the most recent text block to the end of the response.
//
// The repair is deliberately narrow. The evidence supports only the
// must-not-end-on-reasoning constraint, so blocks are otherwise left in
// upstream order: the client replays that order back on the next turn, and
// rewriting it would corrupt the conversation record the model reads.

const http = require("http");
const https = require("https");
const { URL } = require("url");
const { StringDecoder } = require("string_decoder");

const TARGET = { protocol: "https:", hostname: "openrouter.ai" };

/** Request bodies are buffered whole (see proxyRequest), so they need a
 *  ceiling. Generous next to any real conversation payload. */
const MAX_REQUEST_BODY_BYTES = 100 * 1024 * 1024;

/** Idle deadline for streaming responses. Long enough to outlast any real
 *  pause between tokens, short enough that a stalled connection is reclaimed. */
const SSE_IDLE_TIMEOUT_MS = 15 * 60 * 1000;

// Headers a proxy must own: connection-scoped hop-by-hop headers
// (RFC 9110 §7.6.1) plus the routing headers rebuilt for the upstream hop.
const HEADERS_REMOVE = new Set(["host", "x-forwarded-for"]);
const HOP_BY_HOP = new Set([
  "connection", "keep-alive", "proxy-authenticate",
  "proxy-authorization", "te", "trailers",
  "transfer-encoding", "upgrade",
]);

/** Anthropic-format streams announce themselves with these event names. An
 *  OpenAI-format stream carries none of them, which is how a stream is
 *  classified as repairable — see createSSEFixer. */
const ANTHROPIC_EVENTS = new Set([
  "message_start", "message_delta", "message_stop",
  "content_block_start", "content_block_delta", "content_block_stop",
]);

/** Block types that must not be the final block in a response. */
const REASONING_BLOCKS = new Set(["thinking", "redacted_thinking"]);

/** SSE events are separated by a blank line, in either LF or CRLF form. */
const EVENT_DELIMITER = /\r?\n\r?\n/;

/** Logs go to stderr: stdout belongs to the child `claude` process, and it
 *  carries the JSON result that is the entire point of the exercise. */
function defaultLog(msg) {
  process.stderr.write(`[proxy] ${msg}\n`);
}

// ─── Header helpers ────────────────────────────────────────────────

function buildProxyHeaders(original) {
  const h = { ...original };
  for (const key of HEADERS_REMOVE) delete h[key];
  for (const key of HOP_BY_HOP) delete h[key];
  return h;
}

// ─── SSE utilities ─────────────────────────────────────────────────

function isSSEResponse(headers) {
  return (headers["content-type"] || "").includes("text/event-stream");
}

function isStreamingRequest(headers) {
  return (headers["accept"] || "").includes("text/event-stream");
}

/** Parse a raw SSE event block into { event, data }. */
function parseSSEBlock(block) {
  let event = "";
  let data = null;
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith("data:")) {
      try { data = JSON.parse(line.slice(5).trim()); } catch { /* non-JSON payload */ }
    } else if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    }
  }
  return { event, data };
}

// ─── Request-body repair ───────────────────────────────────────────

/** Split user messages that mix tool_result blocks with text blocks.
 *  When OpenRouter translates these to OpenAI format for providers like
 *  DeepSeek, the tool response must land before the next user message or the
 *  provider rejects the request ("insufficient tool messages following
 *  tool_calls message"). */
function splitMixedMessages(messages) {
  if (!Array.isArray(messages)) return messages;
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg?.role !== "user" || !Array.isArray(msg.content)) continue;
    const toolBlocks = msg.content.filter((b) => b?.type === "tool_result");
    const otherBlocks = msg.content.filter((b) => b?.type !== "tool_result");
    if (toolBlocks.length > 0 && otherBlocks.length > 0) {
      msg.content = toolBlocks;
      messages.splice(i + 1, 0, { role: "user", content: otherBlocks });
    }
  }
  return messages;
}

// ─── SSE stream processor ──────────────────────────────────────────

/**
 * Creates handlers for processing an SSE response stream.
 *
 * The repair is selected by stream content, not client identity: the first
 * recognizable event classifies the stream, an Anthropic-format stream is
 * repaired, and anything else is passed through byte-for-byte.
 *
 * Repairing means buffering. Which block is last is only known at
 * message_stop, so a repaired response is assembled in full and replayed —
 * the client sees it at once rather than incrementally. Passthrough streams
 * stream normally.
 */
function createSSEFixer(res, log = defaultLog) {
  let buffer = "";
  let mode = "detecting"; // detecting | repair | passthrough
  let sawMessageStop = false;
  const decoder = new StringDecoder("utf8");

  const preamble = [];       // message_start and anything before the blocks
  const tail = [];           // message_delta and friends
  const pending = [];        // raw events seen before the stream is classified
  const blocks = new Map();  // index -> { type, events: [{ event, data }] }
  const order = [];          // block indexes, in arrival order

  /** Classify a stream from its first meaningful event. Checks the event name
   *  and the payload type, since OpenAI-format streams carry bare "data:"
   *  lines with no event name at all. */
  function classify(raw, event, data) {
    if (ANTHROPIC_EVENTS.has(event) || ANTHROPIC_EVENTS.has(data?.type)) return "repair";
    // Blank lines and ":" heartbeats carry no evidence — keep looking.
    const trimmed = raw.trim();
    if (!trimmed || trimmed.startsWith(":")) return "detecting";
    return "passthrough";
  }

  /** Accumulate one event into the block model. */
  function collect(raw, event, data) {
    // Terminators are regenerated on replay; drop the originals so a duplicate
    // or early message_stop cannot survive into the output. Record that a real
    // one arrived — replay must not invent completion for a truncated stream.
    if (event === "message_stop" || raw.trimEnd().endsWith("[DONE]")) {
      sawMessageStop = true;
      return;
    }

    if (event === "content_block_start") {
      // A repeated index would orphan the first block's deltas and replay the
      // index twice. Upstream should never do it; if it does, say so rather
      // than losing content quietly.
      if (blocks.has(data?.index)) {
        log(`WARNING: duplicate content_block_start at index ${data?.index} — ignoring the repeat`);
        return;
      }
      blocks.set(data?.index, {
        type: data?.content_block?.type || "unknown",
        events: [{ event, data }],
      });
      order.push(data?.index);
      return;
    }
    if (event === "content_block_delta") {
      const block = blocks.get(data?.index);
      if (!block) {
        log(`WARNING: content_block_delta for unstarted index ${data?.index} — dropped`);
        return;
      }
      block.events.push({ event, data });
      return;
    }
    // content_block_stop is regenerated per block on replay — the upstream
    // ordering of these is precisely what is broken.
    if (event === "content_block_stop") return;

    (order.length ? tail : preamble).push({ event, data, raw });
  }

  /** Move the most recent text block to the end when the response would
   *  otherwise finish on a reasoning block. */
  function reorderTrailingText() {
    if (order.length === 0) return;

    const lastType = blocks.get(order[order.length - 1])?.type;
    if (!REASONING_BLOCKS.has(lastType)) return;

    for (let i = order.length - 1; i >= 0; i--) {
      if (blocks.get(order[i])?.type !== "text") continue;
      const [moved] = order.splice(i, 1);
      order.push(moved);
      log(`reordered: response ended on ${lastType}; moved trailing text block to the end`);
      return;
    }
    // Nothing to promote. The response is already broken and the proxy cannot
    // invent content, so it ships as-is with the reason recorded.
    log(`WARNING: response ends on ${lastType} and contains no text block to promote`);
  }

  function emit(event, data, raw) {
    if (data === null || data === undefined) {
      if (raw) res.write(raw + "\n\n");
      return;
    }
    res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  }

  /** Emit the assembled response, renumbering block indexes to match their new
   *  positions — deltas reference the index, so it cannot be left stale. */
  function replay() {
    for (const { event, data, raw } of preamble) emit(event, data, raw);

    order.forEach((originalIdx, position) => {
      const block = blocks.get(originalIdx);
      if (!block) return;
      for (const { event, data } of block.events) {
        emit(event, { ...data, index: position });
      }
      emit("content_block_stop", { type: "content_block_stop", index: position });
    });

    for (const { event, data, raw } of tail) emit(event, data, raw);

    // Only re-emit the terminators that were actually dropped above. Upstream
    // can end without a message_stop (a provider-side truncation), and
    // synthesizing one there would dress a failed response up as a complete
    // one — leaving the caller to consume partial output instead of retrying.
    if (sawMessageStop) {
      emit("message_stop", { type: "message_stop" });
      res.write("event: data\ndata: [DONE]\n\n");
    } else {
      log("WARNING: upstream stream ended without message_stop — forwarding as incomplete");
    }
  }

  function processChunk(chunk) {
    // Decode through a stateful decoder, not per-chunk. A multibyte character
    // split across two network chunks would otherwise decode to U+FFFD on
    // each side and silently corrupt any non-ASCII model output.
    buffer += decoder.write(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));

    // SSE permits CRLF line endings. Splitting on "\n\n" alone would leave a
    // CRLF stream as one unsplit block that never classifies, so it would be
    // passed through unrepaired — reproducing the empty-result failure this
    // proxy exists to fix.
    const events = buffer.split(EVENT_DELIMITER);
    buffer = events.pop();

    for (const raw of events) {
      const { event, data } = parseSSEBlock(raw);

      if (mode === "detecting") {
        mode = classify(raw, event, data);
        if (mode === "detecting") {
          // Blank line or ":" heartbeat. Hold it rather than writing it out:
          // this function is either fully buffered or fully passthrough, and
          // leaking bytes ahead of a repaired response breaks that contract.
          pending.push(raw);
          continue;
        }
        for (const held of pending) {
          if (mode === "repair") collect(held, "", null);
          else res.write(held + "\n\n");
        }
        pending.length = 0;
      }

      if (mode !== "repair") {
        res.write(raw + "\n\n");
        continue;
      }
      collect(raw, event, data);
    }
  }

  function finish() {
    // Release any bytes the decoder is still holding for an incomplete
    // character, so a truncated final code point is not lost outright.
    buffer += decoder.end();

    if (mode === "repair") {
      // A stream that ends without a trailing blank line leaves its final
      // event in `buffer`. Collect it before replaying — dropping it would
      // truncate the response silently, the exact failure this proxy exists
      // to prevent.
      if (buffer.trim().length > 0) {
        const { event, data } = parseSSEBlock(buffer);
        collect(buffer, event, data);
      }
      reorderTrailingText();
      replay();
    } else {
      // Never classified (nothing but heartbeats) or plain passthrough:
      // release anything held, then the trailing partial event.
      for (const held of pending) res.write(held + "\n\n");
      if (buffer.length > 0) res.write(buffer);
    }
    res.end();
  }

  return { processChunk, finish };
}

// ─── HTTP proxy ────────────────────────────────────────────────────

function proxyRequest(clientReq, clientRes, log) {
  // The request target must not be able to choose the upstream host. In
  // absolute-form (RFC 9112 §3.2.2) `new URL(target, base)` ignores the base
  // entirely, so `GET http://elsewhere/x` would send this request — carrying
  // the OpenRouter credentials injected downstream — to `elsewhere`. Any
  // local process can reach the loopback port, and most of them do not
  // otherwise hold the key, so refuse rather than silently re-pin.
  // Node's HTTP parser accepts request targets that WHATWG URL rejects (e.g.
  // `GET http://[/x`), so this parse can throw on input the server already
  // let through. Unguarded it kills the process — and the proxy is in-process
  // with the launcher, so that would strand the running claude child.
  let requested;
  try {
    requested = new URL(clientReq.url, `${TARGET.protocol}//${TARGET.hostname}`);
  } catch {
    log(`refused: unparseable request target`);
    clientReq.resume();
    clientRes.writeHead(400, { "Content-Type": "text/plain" });
    clientRes.end("Bad Request: unparseable request target");
    return;
  }

  if (requested.hostname !== TARGET.hostname) {
    log(`refused: request target names ${requested.hostname}, not ${TARGET.hostname}`);
    // Drain the body before replying; an unconsumed request stalls a
    // keep-alive connection.
    clientReq.resume();
    clientRes.writeHead(403, { "Content-Type": "text/plain" });
    clientRes.end("Forbidden: this proxy only forwards to " + TARGET.hostname);
    return;
  }

  // Rebuild from the pinned target, carrying over only path and query.
  const targetUrl = new URL(`${TARGET.protocol}//${TARGET.hostname}`);
  targetUrl.pathname = requested.pathname;
  targetUrl.search = requested.search;

  // Rewrite /v1/* → /api/v1/*: OpenRouter's Anthropic-compatible endpoint
  // lives under /api, but clients address it as a bare Anthropic base URL.
  if (targetUrl.pathname === "/v1" || targetUrl.pathname.startsWith("/v1/")) {
    targetUrl.pathname = "/api" + targetUrl.pathname;
  }

  const headers = buildProxyHeaders(clientReq.headers);
  headers["host"] = TARGET.hostname;

  const wantSSE = isStreamingRequest(clientReq.headers);
  const proto = targetUrl.protocol === "https:" ? https : http;

  const proxyReq = proto.request({
    hostname: targetUrl.hostname,
    port: targetUrl.port || (targetUrl.protocol === "https:" ? 443 : 80),
    path: targetUrl.pathname + targetUrl.search,
    method: clientReq.method,
    headers,
  }, (proxyRes) => {
    const sse = isSSEResponse(proxyRes.headers);
    const resHeaders = { ...proxyRes.headers };

    // Hop-by-hop headers are scoped to the upstream connection; Node manages
    // the client-side equivalents itself. Forwarding them verbatim causes
    // double transfer-encoding and stale keep-alive negotiation.
    for (const key of HOP_BY_HOP) delete resHeaders[key];

    // The SSE fixer parses the body as text, which is only valid on an
    // identity-encoded stream. Fall back to a byte-for-byte pipe otherwise.
    const encoded = !["", "identity"].includes(
      (proxyRes.headers["content-encoding"] || "").trim().toLowerCase()
    );

    if (sse) {
      delete resHeaders["content-length"];
      resHeaders["cache-control"] = "no-cache, no-transform";
      resHeaders["connection"] = "keep-alive";
      resHeaders["x-accel-buffering"] = "no";
    }

    clientRes.writeHead(proxyRes.statusCode, proxyRes.statusMessage, resHeaders);

    if (sse && !encoded) {
      // The fixer classifies the stream itself and passes through anything
      // that isn't Anthropic-format, so it is safe to install unconditionally.
      const fixer = createSSEFixer(clientRes, log);
      proxyRes.on("data", fixer.processChunk);
      proxyRes.on("end", fixer.finish);
    } else {
      proxyRes.pipe(clientRes);
    }

    // Surface upstream error bodies. Without this an HTTP 400 reaches the
    // client but leaves only a status code behind, which is exactly the case
    // worth reading when a follow-up turn is rejected.
    if (proxyRes.statusCode >= 400) {
      // Collect bytes and decode once at the end: decoding each chunk on
      // arrival would mangle any multibyte character split across chunks.
      const errChunks = [];
      let errBytes = 0;
      proxyRes.on("data", (c) => {
        if (errBytes >= 2048) return;
        errBytes += c.length;
        errChunks.push(c);
      });
      proxyRes.on("end", () => {
        const errBody = Buffer.concat(errChunks).toString("utf8");
        log(`upstream ${proxyRes.statusCode} ${clientReq.method} ${targetUrl.pathname} — ${errBody.trim().slice(0, 1000)}`);
      });
    }

    proxyRes.on("error", (err) => {
      log(`upstream response error: ${err.message}`);
      if (!clientRes.headersSent) clientRes.writeHead(502, { "Content-Type": "text/plain" });
      clientRes.end("Bad Gateway: upstream response error");
    });
  });

  // Buffer the request body so mixed-content user messages can be split
  // before forwarding (see splitMixedMessages). Buffering is why the size is
  // capped: without a ceiling any local sender could exhaust memory and take
  // the launcher down with the proxy.
  const chunks = [];
  let bodyBytes = 0;
  let bodyTooLarge = false;
  clientReq.on("data", (chunk) => {
    if (bodyTooLarge) return;
    bodyBytes += chunk.length;
    if (bodyBytes > MAX_REQUEST_BODY_BYTES) {
      bodyTooLarge = true;
      log(`refused: request body exceeds ${MAX_REQUEST_BODY_BYTES} bytes`);
      chunks.length = 0;
      proxyReq.destroy();
      if (!clientRes.headersSent) {
        clientRes.writeHead(413, { "Content-Type": "text/plain" });
        clientRes.end("Payload Too Large");
      }
      return;
    }
    chunks.push(chunk);
  });
  clientReq.on("end", () => {
    if (bodyTooLarge) return;
    const raw = Buffer.concat(chunks).toString();
    let body = raw;
    try {
      const obj = JSON.parse(raw);
      if (obj.messages) {
        splitMixedMessages(obj.messages);
        body = JSON.stringify(obj);
      }
    } catch { /* pass non-JSON bodies through unmodified */ }
    proxyReq.setHeader("Content-Length", Buffer.byteLength(body));
    proxyReq.write(body);
    proxyReq.end();
  });

  clientReq.on("error", (err) => {
    log(`client request error: ${err.message}`);
    proxyReq.destroy();
  });

  proxyReq.on("error", (err) => {
    log(`upstream request error: ${err.message}`);
    if (!clientRes.headersSent) clientRes.writeHead(502, { "Content-Type": "text/plain" });
    clientRes.end(`Bad Gateway: ${err.message}`);
  });

  // Streaming responses need a far longer idle deadline than request/response
  // traffic, but not an unlimited one: `wantSSE` comes from a client-supplied
  // Accept header, so disabling the timeout outright would let any local
  // sender park upstream connections and file descriptors indefinitely.
  proxyReq.setTimeout(wantSSE ? SSE_IDLE_TIMEOUT_MS : 60000, () => {
    log("upstream request timeout");
    proxyReq.destroy();
  });
}

// ─── Server ────────────────────────────────────────────────────────

/**
 * Start the proxy and resolve once it is listening.
 *
 * @param {object} [opts]
 * @param {number} [opts.port] Port to bind. Defaults to 0 — the kernel
 *   assigns an unused port atomically, which is the only collision-free
 *   choice when concurrent sessions each start their own proxy. Picking a
 *   random port and checking it first is a TOCTOU race.
 * @param {string} [opts.host] Interface to bind. Loopback only by default.
 * @param {(msg: string) => void} [opts.log] Log sink; defaults to stderr.
 * @returns {Promise<{ port: number, close: () => Promise<void> }>}
 */
function start({ port = 0, host = "127.0.0.1", log = defaultLog } = {}) {
  // The parse guard in proxyRequest covers the one throw we know about. This
  // covers the ones we don't: because the proxy shares a process with the
  // launcher, an unhandled throw here would kill the running claude child
  // too. A failed request must never be able to end the session.
  const server = http.createServer((req, res) => {
    try {
      proxyRequest(req, res, log);
    } catch (err) {
      log(`request handler error: ${err.message}`);
      if (!res.headersSent) res.writeHead(500, { "Content-Type": "text/plain" });
      res.end("Internal proxy error");
    }
  });

  server.on("clientError", (err, socket) => {
    if (err.code === "ECONNRESET" || !socket.writable) return;
    socket.end("HTTP/1.1 400 Bad Request\r\n\r\n");
  });

  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => {
      server.removeListener("error", reject);
      resolve({
        port: server.address().port,
        close: () => new Promise((done) => server.close(() => done())),
      });
    });
  });
}

module.exports = {
  start,
  // Exported for tests.
  createSSEFixer,
  splitMixedMessages,
  parseSSEBlock,
  buildProxyHeaders,
};
