// Tests for quiz.js — the click handler behind an explainer's quiz section.
//
// quiz.js is browser code that gets inlined verbatim into a <script> tag, so it
// exports nothing and registers its listener at load time. Rather than adding a
// module shim to a file whose whole contract is "paste this into HTML", the
// suite evaluates it in a vm context holding a fake `document`, captures the
// handler it registers, and drives that against hand-built questions.
//
// The fake implements only what quiz.js reaches for: class and data-attribute
// selectors, upward `closest`, downward `querySelector(All)`, `classList.add`,
// `dataset`, `disabled` and `textContent`. An unsupported selector throws
// rather than silently matching nothing, so a future change to quiz.js that
// needs more of the DOM fails loudly here instead of passing vacuously.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// ─── Fake DOM ──────────────────────────────────────────────────────

// `.cls` optionally followed by one [data-attr="value"] predicate. That is the
// whole selector grammar quiz.js uses.
const SELECTOR = /^\.([\w-]+)(?:\[data-([\w-]+)="([^"]*)"\])?$/;

/** `data-foo-bar` addresses `dataset.fooBar`, as in a real DOMStringMap. */
const toDatasetKey = (attr) =>
  attr.replace(/-([a-z])/g, (_, c) => c.toUpperCase());

class El {
  constructor(classes, dataset = {}) {
    this.classes = new Set(classes);
    this.dataset = { ...dataset };
    this.children = [];
    this.parent = null;
    this.disabled = false;
    this.textContent = "";
    this.classList = { add: (c) => this.classes.add(c) };
  }

  append(child) {
    child.parent = this;
    this.children.push(child);
    return child;
  }

  matches(selector) {
    const m = SELECTOR.exec(selector);
    if (m === null) {
      throw new Error(`fake DOM: unsupported selector ${selector}`);
    }
    if (!this.classes.has(m[1])) return false;
    return m[2] === undefined || this.dataset[toDatasetKey(m[2])] === m[3];
  }

  closest(selector) {
    for (let node = this; node !== null; node = node.parent) {
      if (node.matches(selector)) return node;
    }
    return null;
  }

  descendants() {
    return this.children.flatMap((c) => [c, ...c.descendants()]);
  }

  querySelectorAll(selector) {
    return this.descendants().filter((n) => n.matches(selector));
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] ?? null;
  }
}

// ─── Loading the handler under test ────────────────────────────────

function loadHandler() {
  const source = fs.readFileSync(path.join(__dirname, "quiz.js"), "utf8");
  let handler = null;
  const sandbox = {
    document: {
      addEventListener(type, fn) {
        if (type === "click") handler = fn;
      },
    },
  };
  vm.runInNewContext(source, sandbox, { filename: "quiz.js" });
  assert.ok(handler !== null, "quiz.js registered no click handler");
  return handler;
}

/**
 * One question in the markup shape palette.md documents: two false distractors
 * (one of them the comic foil), one true answer, and a feedback div.
 */
function question({ done = false, withFeedback = true } = {}) {
  const q = new El(["q"]);
  if (done) q.dataset.done = "1";
  const wrong = q.append(new El(["opt"], { correct: "false", fb: "It is not." }));
  const right = q.append(new El(["opt"], { correct: "true", fb: "It is." }));
  const comic = q.append(
    new El(["opt"], { correct: "false", comic: "true", fb: "Absurdly not." })
  );
  const feedback = withFeedback ? q.append(new El(["feedback"])) : null;
  return { q, wrong, right, comic, feedback };
}

const click = (handler, target) => handler({ target });

// ─── Tests ─────────────────────────────────────────────────────────

test("a right answer marks only itself and locks every option", () => {
  const handler = loadHandler();
  const { q, wrong, right, comic } = question();

  click(handler, right);

  assert.ok(right.classes.has("correct"));
  assert.ok(!wrong.classes.has("correct") && !wrong.classes.has("incorrect"));
  assert.ok(!comic.classes.has("correct") && !comic.classes.has("incorrect"));
  assert.deepEqual(
    [wrong, right, comic].map((o) => o.disabled),
    [true, true, true],
    "every option must be disabled once the question is answered"
  );
  assert.equal(q.dataset.done, "1");
});

test("a wrong answer marks itself incorrect AND reveals the right one", () => {
  // The reveal is the point: a reader who missed has to be shown the answer,
  // not merely told they were wrong.
  const handler = loadHandler();
  const { wrong, right } = question();

  click(handler, wrong);

  assert.ok(wrong.classes.has("incorrect"));
  assert.ok(right.classes.has("correct"));
});

test("the comic foil is scored as an ordinary wrong answer", () => {
  // data-comic marks it for the author, not for the handler — nothing in the
  // scoring path may treat it as a third outcome.
  const handler = loadHandler();
  const { comic, right } = question();

  click(handler, comic);

  assert.ok(comic.classes.has("incorrect"));
  assert.ok(right.classes.has("correct"));
});

test("missing appends the right answer's rationale; getting it right does not", () => {
  const handler = loadHandler();

  const missed = question();
  click(handler, missed.wrong);
  assert.match(missed.feedback.textContent, /^Not quite\. It is not\./);
  assert.ok(
    missed.feedback.textContent.includes("It is."),
    "a missed question must also carry the correct option's rationale"
  );

  const hit = question();
  click(handler, hit.right);
  assert.equal(hit.feedback.textContent, "Correct. It is.");
});

test("feedback becomes visible on answering", () => {
  const handler = loadHandler();
  const { right, feedback } = question();

  assert.ok(!feedback.classes.has("show"), "feedback starts hidden");
  click(handler, right);
  assert.ok(feedback.classes.has("show"));
});

test("an already-answered question ignores further clicks", () => {
  // The lock is what stops a reader clicking through every option until the
  // page tells them which one was right.
  const handler = loadHandler();
  const { wrong, right } = question({ done: true });

  click(handler, right);
  click(handler, wrong);

  assert.equal(right.classes.size, 1, "no scoring class may be added");
  assert.equal(right.disabled, false);
});

test("a click outside any option is ignored", () => {
  const handler = loadHandler();
  const { q } = question();
  const prose = q.append(new El(["stem"]));

  assert.doesNotThrow(() => click(handler, prose));
  assert.equal(q.dataset.done, undefined);
});

test("an option outside a question is ignored", () => {
  // Reached when an author copies an .opt button outside its .q wrapper; the
  // handler must not throw and take the rest of the page's interactivity down.
  const handler = loadHandler();
  const orphan = new El(["opt"], { correct: "true", fb: "unreachable" });

  assert.doesNotThrow(() => click(handler, orphan));
  assert.equal(orphan.classes.size, 1);
});

test("a question with no feedback div still scores and locks", () => {
  const handler = loadHandler();
  const { wrong, right } = question({ withFeedback: false });

  assert.doesNotThrow(() => click(handler, wrong));
  assert.ok(wrong.classes.has("incorrect"));
  assert.ok(right.classes.has("correct"));
  assert.equal(right.disabled, true);
});

test("an option with no rationale yields feedback without 'undefined'", () => {
  const handler = loadHandler();
  const q = new El(["q"]);
  const bare = q.append(new El(["opt"], { correct: "true" }));
  const feedback = q.append(new El(["feedback"]));

  click(handler, bare);

  assert.equal(feedback.textContent, "Correct. ");
});
