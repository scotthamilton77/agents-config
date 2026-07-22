# S4 — Instruction-Surface Teardown

**Date:** 2026-07-22
**Status:** Implementing
**Parent:** `docs/specs/2026-07-21-harness-rework-way-forward.md` (D17, slice S4)

Child spec for slice S4 of the harness-rework charter. S0 already extracted
the zero-based survivor content into `src/user/.agents/AGENTS.md.template`
(~450 tokens, matches Appendix A of the parent spec) and hand-deployed it to
the standard homes. S4's job is to remove the now-superseded 154-line
`INSTRUCTIONS.md.template` mountain and everything that points at it, and to
rule on whether the DYNAMIC-INCLUDE assembly machinery still earns its keep.

## 1. Inventory (full sweep)

Search performed: `grep -rl "INSTRUCTIONS\.md"` and `grep -rl "DYNAMIC-INCLUDE"`
over the whole repository (installer code + tests, docs, templates, skills,
rules), then triaged by whether the hit is live/authoritative or historical.

### 1.1 Delete

- `src/user/.agents/INSTRUCTIONS.md.template` — the mountain itself (154 lines).

### 1.2 Edit — per-tool assembly (swap the dead include for the survivor)

Each of these DYNAMIC-INCLUDEs `src/user/.agents/INSTRUCTIONS.md.template` on
one line; the line is repointed at `src/user/.agents/AGENTS.md.template` (the
S0 zero-based survivor) so flattening reproduces what is already hand-deployed
in the standard homes:

- `src/user/.claude/AGENTS.md.template`
- `src/user/.codex/AGENTS.md.template`
- `src/user/.gemini/GEMINI.md.template`
- `src/user/.opencode/AGENTS.md.template`

No other line in these four files changes. This also keeps
`packages/installer/src/installer/core/templates.py`'s existing
`_file_include_dests` dedup working correctly for Gemini/OpenCode/Codex: since
each tool's main file still includes the shared `AGENTS.md.template` by
reference, the flatten step continues to drop its would-be standalone staged
copy — no new stray `AGENTS.md` leaks into a home whose main file is
`GEMINI.md`.

### 1.3 Edit — live prose referencing `INSTRUCTIONS.md`

- `src/user/.agents/AGENTS.md` (meta-doc: install-model example line, swap the
  `INSTRUCTIONS.md.template → ~/.claude/INSTRUCTIONS.md` example for a
  surviving file)
- `src/user/.agents/README.md` (file listing + per-tool file lists)
- `src/user/.agents/SESSION-PRIMER-README.md` (cross-reference to `<laws>`
  ownership)
- `src/user/.agents/agents/quality-reviewer.md` — **shipped agent**; its
  coverage-floor line cites `INSTRUCTIONS.md` constraints, repoint to the
  survivor
- `src/user/.gemini/AGENTS.md`, `src/user/.gemini/README.md`
- `src/user/.codex/AGENTS.md`, `src/user/.codex/README.md`
- `src/user/.claude/README.md`
- root `README.md` (six hits: file tree, install-model bullets, an example
  `cp` command, prose)
- root `AGENTS.md` (project instructions) — two hits: the "no file-path
  citations" rule's own example, and the repo-structure bullet list
- `docs/guide/getting-started.md` (two hits: architecture table, prose)

### 1.4 No change needed

- `packages/installer/src/installer/**` — zero literal `INSTRUCTIONS` hits.
  The flattening mechanism (`templates.py`) is data-driven off whatever a
  template's DYNAMIC-INCLUDE lines name; nothing hardcodes the mountain's
  filename. Fixing 1.2 is sufficient.
- `packages/installer/tests/unit/*.py` — every `INSTRUCTIONS.md.template` hit
  is a synthetic fixture string used to exercise generic "shared root
  template" staging/flattening mechanics (arbitrary example filename against a
  `tmp_path` tree, never the real repo). No installer route is removed by
  deleting the real file, so these fixtures need no edit — verified by running
  `make ci-installer` green after the source edits (§4).
- `docs/architecture/installer/*.md` — references DYNAMIC-INCLUDE as a
  mechanism only, never names `INSTRUCTIONS.md`; nothing to update.
- `docs/plans/*.md`, `docs/specs/*.md` (other than this file and the parent
  charter) — dated, point-in-time proposals; they record the decision as of
  their date and are not amended in place (repo convention).
- `archive/**` — frozen quarantine from a prior cleanup; already historical,
  already referencing already-dead plans. Out of scope.
- `SAVEPOINTS/*.jsonl`, `issues.backup.jsonl`, `graphify-out/**` — frozen
  exports / generated artifacts, not hand-edited. `graphify update .` runs
  after the code edits per repo convention.

## 2. DYNAMIC-INCLUDE fate (D17)

**Decision: keep.** D17 says to reassess "once content shrinks below what
justifies it." Deleting the 154-line mountain does not empty the assembly —
each tool's main file still composes multiple distinct, non-trivial
fragments:

| Fragment | Lines |
|---|---|
| `AGENT-PERSONA.md.template` | 16 |
| `USER-PERSONA.md.template` | 7 |
| `SESSION-PRIMER.md.template` | 66 |
| `AGENTS.md.template` (zero-based survivor) | 30 |
| tool `*-EXTENSIONS.md.template` | 0 (stub today, but a real per-tool extension point) |

Codex, Gemini, and OpenCode additionally flatten their entire `rules/` tree
via `DYNAMIC-INCLUDE-ALL-RULES` (dozens of files) — real, ongoing composition
work no simpler mechanism replaces without inventing one. The machinery stays;
this is a content deletion, not a machinery deletion.

## 3. Acceptance criteria

- **S4-AC1** — `find src -iname 'INSTRUCTIONS.md.template'` returns nothing.
- **S4-AC2** — `grep -rl 'INSTRUCTIONS\.md'` over `src/`, `docs/architecture/`,
  and `packages/installer/src/` (excluding this file and the parent charter,
  which document the deletion itself) returns nothing.
- **S4-AC3** — Each of the four per-tool main templates (§1.2) DYNAMIC-INCLUDEs
  `src/user/.agents/AGENTS.md.template` where it used to DYNAMIC-INCLUDE the
  mountain.
- **S4-AC4** — `make ci-installer` passes from the edited tree (lint, format,
  typecheck, coverage, audit, entry-verify).
- **S4-AC5** — This document records the DYNAMIC-INCLUDE keep/kill call (§2);
  no separate action item is silently dropped.

## 4. Verification

`make ci-installer` run from `packages/installer/` after all edits; see PR for
output.
