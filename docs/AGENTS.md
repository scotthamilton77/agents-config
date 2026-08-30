# AGENTS.md — `docs/`

What each subtree is, and how staleness is judged there.

- `guide/` — user guide for people *running* the deployed assets: install,
  configure a project, run the agentic SDLC.
- `specs/` — dated point-in-time design proposals; status varies from draft
  through implemented. A spec describes its full intent, and partial per-PR
  implementation is expected — a spec that describes code nobody has written
  yet is working as designed, not a defect to file or annotate. The dated
  filename is what puts a file in `spec-lint`'s scope, and the lint has no
  allowlist by design — so a companion record that is not a spec (a rationale
  or evidence file beside one) stays undated on purpose; dating it demands
  acceptance criteria it cannot honestly carry. Under an acceptance-criteria
  heading the lint wants at least one `- **<ID>** text` entry whose ID matches
  `[A-Z0-9]+-[A-Z]\d+` or `AC\d+` — a letter before the digits (`S6-A1`,
  not `AUTH-1`).
- `architecture/` — evergreen HLD artifacts (C4 levels, sequence diagrams,
  state machines, data-flow views), grouped per subsystem with an `index.md`
  orientation file. Amended in place; filenames are undated and describe
  content.
- `primers/` — explainers for the key primitives of this architecture
  (skills, agents, rules, commands).
- `research/` — analyses converted from external sources, kept verbatim under
  a provenance header. Their worked examples cite codebases that are not this
  one, which is why `doc-lint` does not read the tree.
- `adr/`, `reference/`, `prototypes/` — supporting material. There is no
  `plans/` tree: the prose plan is retired as an artifact class.
