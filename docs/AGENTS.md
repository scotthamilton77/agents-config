# AGENTS.md — `docs/`

What each subtree is, and how staleness is judged there.

- `guide/` — user guide for people *running* the deployed assets: install,
  configure a project, run the agentic SDLC.
- `specs/` — dated point-in-time design proposals; status varies from draft
  through implemented. A spec describes its full intent, and partial per-PR
  implementation is expected — a spec that describes code nobody has written
  yet is working as designed, not a defect to file or annotate. `spec-lint`
  reads a spec whose filename begins `YYYY-MM-DD-` with a date of 2026-07-24
  or later, and it always reads the harness-rework charter,
  `specs/2026-07-21-harness-rework-way-forward.md`, whatever its date. The
  lint has no allowlist by design. An evidence sidecar,
  `<spec-stem>-evidence.md`, is dated because it is named for its spec. The
  lint reads it as that spec's ledger only when the spec sits beside it, so
  the file's place in the tree is what exempts it. Any other companion record,
  such as a rationale, stays undated, because dating it demands acceptance
  criteria it cannot honestly carry. Under an acceptance-criteria heading the
  lint wants at least one `- **<ID>** text` entry whose ID matches
  `[A-Z0-9]+-[A-Z]\d+` or `AC\d+` — a letter before the digits (`S6-A1`,
  not `AUTH-1`).
- `architecture/` — evergreen HLD artifacts (C4 levels, sequence diagrams,
  state machines, data-flow views), grouped per subsystem. A subsystem folder
  opens with an `index.md` orientation file, or with a `CONTEXT.md` glossary
  when the subsystem is documented as a vocabulary. Amended in place;
  filenames are undated and describe content.
- `primers/` — explainers for the key primitives of this architecture
  (skills, agents, rules, commands).
- `research/` — analyses converted from external sources, kept verbatim under
  a provenance header. Their worked examples cite codebases that are not this
  one, which is why `doc-lint` exempts `research/spec-science/`. The exemption
  names that folder only, so a note filed anywhere else under `research/` is
  linted unless its filename carries a date.
- `reference/`, `prototypes/` — supporting material. There is no
  `plans/` tree: the prose plan is retired as an artifact class.
