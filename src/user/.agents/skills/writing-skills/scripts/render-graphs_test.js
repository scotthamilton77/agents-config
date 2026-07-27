// Tests for render-graphs.js — the dot-fence extractor and graph combiner
// behind the writing-skills diagram renderer.
//
// Scope is the three pure functions: extractDotBlocks, extractGraphBody and
// combineGraphs. renderToSvg and main() pipe through the graphviz `dot`
// binary, so they are deliberately left out — this suite has to pass on a
// machine with no graphviz installed.

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  extractDotBlocks,
  extractGraphBody,
  combineGraphs,
} = require("./render-graphs.js");

/** Build a markdown fixture line by line, so fence markers need no escaping. */
const md = (...lines) => lines.join("\n");

// ─── extractDotBlocks ──────────────────────────────────────────────

test("two adjacent dot fences extract as two blocks, not one", () => {
  // The fence regex is non-greedy on purpose: a greedy one would run from the
  // first opening fence to the last closing fence and swallow everything in
  // between into a single unparseable block.
  const blocks = extractDotBlocks(md(
    "```dot",
    "digraph first { a -> b; }",
    "```",
    "",
    "Prose between the diagrams.",
    "",
    "```dot",
    "digraph second { c -> d; }",
    "```",
  ));

  assert.deepEqual(blocks.map((b) => b.name), ["first", "second"]);
  assert.ok(
    !blocks[0].content.includes("Prose between"),
    "the first block swallowed the interstitial prose"
  );
});

test("only dot fences are extracted, not other fenced languages", () => {
  // A SKILL.md is mostly bash and mermaid fences; picking those up would hand
  // graphviz text that is not dot at all.
  const blocks = extractDotBlocks(md(
    "```bash",
    "echo not a diagram",
    "```",
    "```dot",
    "digraph only_me { a -> b; }",
    "```",
    "```mermaid",
    "graph TD; a-->b;",
    "```",
  ));

  assert.deepEqual(blocks.map((b) => b.name), ["only_me"]);
});

test("a named digraph takes its name from the digraph identifier", () => {
  // The name is the per-diagram output filename, so it has to come from the
  // source rather than from the position.
  const blocks = extractDotBlocks(md(
    "```dot",
    "digraph review_loop {",
    "  a -> b;",
    "}",
    "```",
  ));

  assert.deepEqual(blocks.map((b) => b.name), ["review_loop"]);
});

test("an unnamed digraph falls back to a 1-based positional name", () => {
  // Same filename consequence: the first diagram must land as graph_1.svg,
  // not graph_0.svg.
  const blocks = extractDotBlocks(md(
    "```dot",
    "digraph {",
    "  a -> b;",
    "}",
    "```",
  ));

  assert.deepEqual(blocks.map((b) => b.name), ["graph_1"]);
});

test("the positional fallback counts all blocks, not just the unnamed ones", () => {
  // Position is over every discovered block, so a fallback name tracks where
  // the diagram sits in SKILL.md even when earlier diagrams carry real names.
  const blocks = extractDotBlocks(md(
    "```dot",
    "digraph named { a -> b; }",
    "```",
    "```dot",
    "digraph { c -> d; }",
    "```",
  ));

  assert.deepEqual(blocks.map((b) => b.name), ["named", "graph_2"]);
});

test("markdown with no dot fences yields an empty list rather than throwing", () => {
  // main() branches on blocks.length === 0 to report "no diagrams" and exit 0,
  // which only works if a diagram-free SKILL.md is a normal return.
  assert.deepEqual(extractDotBlocks("# A skill\n\nNo diagrams here.\n"), []);
});

// ─── extractGraphBody ──────────────────────────────────────────────

test("extractGraphBody drops a per-block rankdir", () => {
  // The combiner sets rankdir once at the top level; a rankdir carried in on a
  // block body would fight that single declaration.
  const body = extractGraphBody(md(
    "digraph flow {",
    "  rankdir=LR;",
    "  a -> b;",
    "}",
  ));

  assert.ok(!body.includes("rankdir"), `rankdir survived extraction: ${body}`);
  assert.ok(body.includes("a -> b;"), "the surrounding statements must survive");
});

test("extractGraphBody keeps a nested subgraph and the statements after it", () => {
  // The closing-brace match is greedy on purpose: stopping at the first `}`
  // would truncate the body at the nested subgraph and silently drop edges.
  const body = extractGraphBody(md(
    "digraph outer {",
    "  subgraph cluster_inner {",
    "    a -> b;",
    "  }",
    "  c -> d;",
    "}",
  ));

  assert.ok(body.includes("subgraph cluster_inner {"), "the nested subgraph was lost");
  assert.ok(body.includes("c -> d;"), "statements after the nested block were truncated");
});

test("extractGraphBody returns an empty body for input that is not a digraph", () => {
  // combineGraphs maps over every block unconditionally, so an unparseable
  // block has to degrade to an empty body instead of throwing mid-combine.
  assert.equal(extractGraphBody("Just some prose that never opens a digraph."), "");
});

// ─── combineGraphs ─────────────────────────────────────────────────

test("each block becomes a cluster_N subgraph labelled with the block name", () => {
  // The `cluster_` prefix is what makes graphviz draw a box around the group,
  // and the label is the only thing telling a reader which diagram a box is.
  const combined = combineGraphs(
    [
      { name: "intake", content: "digraph intake { a -> b; }" },
      { name: "review", content: "digraph review { c -> d; }" },
    ],
    "my_skill"
  );

  assert.match(combined, /subgraph cluster_0 \{\s*label="intake";/);
  assert.match(combined, /subgraph cluster_1 \{\s*label="review";/);
});

test("each block's statements land inside that block's own cluster", () => {
  // Grouping is the whole point of --combine: edges from different diagrams
  // must not spill into one shared cluster.
  const combined = combineGraphs(
    [
      { name: "intake", content: "digraph intake { a -> b; }" },
      { name: "review", content: "digraph review { c -> d; }" },
    ],
    "my_skill"
  );

  const firstCluster = combined.indexOf("cluster_0");
  const secondCluster = combined.indexOf("cluster_1");
  const firstEdge = combined.indexOf("a -> b;");
  const secondEdge = combined.indexOf("c -> d;");

  assert.ok(firstCluster < firstEdge && firstEdge < secondCluster,
    "the first block's edge escaped its cluster");
  assert.ok(secondCluster < secondEdge, "the second block's edge escaped its cluster");
});

test("the combined graph declares rankdir exactly once, at the top level", () => {
  // Cross-checks the strip in extractGraphBody: blocks that each carry
  // rankdir=LR must not smuggle it past the combiner's single rankdir=TB.
  const combined = combineGraphs(
    [
      { name: "one", content: md("digraph one {", "  rankdir=LR;", "  a -> b;", "}") },
      { name: "two", content: md("digraph two {", "  rankdir=LR;", "  c -> d;", "}") },
    ],
    "my_skill"
  );

  assert.deepEqual(combined.match(/rankdir\s*=\s*\w+/g), ["rankdir=TB"]);
});

test("the combined graph is named <skillName>_combined", () => {
  // main() writes the result to <skillName>_combined.svg and .dot; the graph
  // id inside the file is meant to agree with those filenames.
  const combined = combineGraphs(
    [{ name: "only", content: "digraph only { a -> b; }" }],
    "my_skill"
  );

  assert.match(combined, /^digraph my_skill_combined \{/);
});
