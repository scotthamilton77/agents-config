# AGENTS.md — `docs/`

What each subtree is, and how staleness is judged there.

- `guide/` — user guide for people *running* the deployed assets: install,
  configure a project, run the agentic SDLC.
- `specs/` — dated point-in-time design proposals; status varies from draft
  through implemented. A spec describes its full intent, and partial per-PR
  implementation is expected — a spec that describes code nobody has written
  yet is working as designed, not a defect to file or annotate.
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
