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

### 1.3.1 Edit — dead concept references (deleted section names, not just the filename)

Filename-only grep missed these; the mountain's deleted `<constraints>` items
and `<decision-matrix>` were cited by name elsewhere, independent of the
`INSTRUCTIONS.md` string:

- `src/user/.agents/rules/completion-gate.md` — cited `<verification-checklist>`
  as "in shared instructions... always loaded"; that block is gone entirely,
  not relocated. Repointed at `verify-checklist`'s new canonical definition
  (§1.5, row `<verification-checklist>`).
- `src/user/.agents/skills/verify-checklist/SKILL.md` — same dangling citation,
  in its discovery order and "Source Dependency" section. This skill is now
  the checklist's home (§1.5).
- `src/user/.agents/agents/quality-reviewer.md` — cited "the shared `AGENTS.md`
  constraints" for its 80/70 coverage floor; the survivor has no constraints
  block. Made self-contained: floor stated inline, citation dropped.
- `src/user/.agents/agents/tech-lead.md`, `src/user/.claude/skills/orchestrated-grind/SKILL.md`,
  `src/user/.agents/skills/ralf-implement/subagent-implementer.md` — named the
  deleted `<decision-matrix>` quadrants (`verify-facts` / `decide-in-scope` /
  `escalate-architectural` / `escalate-conflicting`) or the retired "canonical
  decision matrix" label. Rewritten in plain language against the surviving
  `<decisions>` block; quadrant names are not resurrected into the always-on
  surface (they're gone from `AGENTS.md.template`, on purpose).
- root `AGENTS.md` — the "no file-path citations" rule's own example named
  "the canonical decision matrix"; swapped for "the shared decision rules" to
  match.
- `src/user/.agents/rules/worktrees.md` — gained the two load-bearing-but-homeless
  items from §1.5 (`Coordination`, `Database safety`) that this worktree rule's
  own scope makes it the natural owner of.

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

## 1.5 Content disposition (did we lose anything load-bearing?)

Every block and `<constraints>` item the mountain carried, and where it lives
now. Three dispositions: **lives in `<X>` now** (already true before this PR),
**re-homed by this PR to `<X>`** (this PR moved it), or **dies deliberately
per D17/D16** (fails the zero-based admission test and nothing shipped relies
on it — re-enters only through a future admission-bar pass, out of scope
here). Nothing is silently dropped: every "dies deliberately" row was checked
against the live `src/` tree for a dependent shipped artifact before being
marked dead.

**`<laws>`**

| Item | Disposition |
|---|---|
| L0–L3 | lives in `AGENTS.md.template`'s `<laws>` block |

**`<constraints>`** (19 items)

| Item | Disposition |
|---|---|
| Minimal edits | lives in `<conventions>` ("Minimal, surgical edits") |
| Informed edits | dies deliberately per D16 |
| Spec, diagram and code agreement | dies deliberately per D16 |
| State the decision, not its history | lives in `<conventions>` |
| Domain vocabulary | lives in `<conventions>` (CONTEXT.md glossary) |
| Parallel ops | dies deliberately — redundant with Claude Code's harness-native tool-calling guidance (fails D17's not-model-default test) |
| Root causes | dies deliberately per D16 |
| Lead with the outcome | dies deliberately — likely redundant with harness-native response-style defaults (D17's not-model-default test) |
| Turn-handoff text is self-contained | lives in `orchestrated-grind/SKILL.md` already, independently, in full |
| Contracts & boundaries | lives in `improve-codebase-architecture`'s "Designing the contract" section — the deleted text's own named companion for depth |
| Dependencies (context7/docs lookup) | dies deliberately per D16 |
| Observability | dies deliberately per D16 |
| Testing (80% line / 70% branch floor) | **re-homed by this PR** to `quality-reviewer.md` (made self-contained, dangling citation dropped) |
| Git safety | lives in `<hard-lines>` |
| Merge authorization policy | lives in `completion-gate.md` (already fully restated there) and `merge-guard`'s `resolve_policy.py` |
| Worktree hygiene | lives in `worktrees.md` / `worktree-safety.md` |
| Database safety (WAL / worktree-vs-main-tree) | **re-homed by this PR** to `worktrees.md` — load-bearing-but-homeless: dolt-backed beads + worktrees is live, current infrastructure, and no rule warned against the copy hazard |
| Coordination (never `git restore` a sibling's files) | **re-homed by this PR** to `worktrees.md` — load-bearing-but-homeless: that rule's own premise is multi-agent worktree collaboration, which is exactly the hazard this item covers |
| No tracker IDs in code or living docs | dies deliberately per D16 |

**`<decision-matrix>`**

| Item | Disposition |
|---|---|
| verify-facts / decide-in-scope / escalate-architectural / escalate-conflicting quadrants | compressed into `<decisions>`; quadrant names retired (deliberate — D17 lists "the decision matrix (compressed)" as the survivor, not the named quadrants). Plain-language references **re-homed by this PR** in `tech-lead.md`, `orchestrated-grind/SKILL.md`, `ralf-implement/subagent-implementer.md`, and root `AGENTS.md` |

**`<workflow>`**

| Item | Disposition |
|---|---|
| TDD (Design → Tests → Implement → Refactor) | lives in `test-driven-development` skill |
| Commits: semantic prefix | dies deliberately per D16 |
| Delivery: Worktree → Branch → PR → Review → Merge | lives in `completion-gate.md`'s HARD STOP delivery chain (already fully restated there) |

**`<orchestration>`**

| Item | Disposition |
|---|---|
| Plan first | dies deliberately — superseded by the harness-rework's own D6 (plan mode as default), not yet re-admitted |
| Decide, don't defer | duplicate of the `<decision-matrix>` disposition above — the `<decisions>` block *is* this, compressed |
| Subagents | lives in the `orchestrating-subagents` rule/skill |
| Self-improvement (`self-improving-agent` hook) | dies deliberately — **explicit parent-spec call-out** (D17): the hook is deleted; corrections land in memory and become rules only through the admission bar |
| Verify before done | lives in `verify-checklist` (Iron Law framing) + `completion-gate` step 5 |
| Agent Integrity | lives in `verify-checklist`'s Iron Law / evidence-before-claims framing |
| Tracer bullets | dies deliberately per D16 |
| Isolate work | lives in `worktrees.md` + `completion-gate.md`'s delivery chain |
| Elegance check | lives in the `simplify` skill (`completion-gate` `SERIAL` step 3) |

**`<verification-checklist>`**

| Item | Disposition |
|---|---|
| 10-step checklist (Quality gate 1–5, Delivery 6–8, Housekeeping 9–10) + SKIP/SERIAL/HEAVY taxonomy | **re-homed by this PR**: the full 10-step definition now lives in `verify-checklist/SKILL.md` (its natural owner — it's the skill that reports against it); `completion-gate.md` maps steps 1–5 to concrete tools and owns the tier-routing taxonomy, rather than defining the steps itself |

## 3. Acceptance criteria

- **S4-AC1** — `find src -iname 'INSTRUCTIONS.md.template'` returns nothing.
- **S4-AC2** — `grep -rl 'INSTRUCTIONS\.md'` over `src/`, `docs/architecture/`,
  and `packages/installer/src/` (excluding this file and the parent charter,
  which document the deletion itself) returns nothing, **and** a grep of `src/`
  for the dead concept tokens the mountain used to define — `<verification-checklist>`
  (as a live citation, not the historical "no longer carries" explanation in
  `verify-checklist/SKILL.md`), the retired decision-matrix quadrant names
  (`verify-facts`, `decide-in-scope`, `escalate-architectural`,
  `escalate-conflicting`), the "canonical decision matrix" label, and
  "INSTRUCTIONS.md constraints" — also returns nothing outside this file's own
  disposition table (§1.5) and historical explanations.
- **S4-AC3** — Each of the four per-tool main templates (§1.2) DYNAMIC-INCLUDEs
  `src/user/.agents/AGENTS.md.template` where it used to DYNAMIC-INCLUDE the
  mountain.
- **S4-AC4** — `make ci-installer` passes from the edited tree (lint, format,
  typecheck, coverage, audit, entry-verify).
- **S4-AC5** — This document records the DYNAMIC-INCLUDE keep/kill call (§2);
  no separate action item is silently dropped.
- **S4-AC6** — No deployed artifact cites the shared `AGENTS.md` (or any
  always-on surface) for content it does not contain. Verified by reading
  every surviving citation of the shared instruction file against the
  30-line survivor (§1.5 is the audit trail); zero citations claim a
  `<constraints>`, `<decision-matrix>`, `<workflow>`, `<orchestration>`, or
  `<verification-checklist>` block that no longer exists there.

## 4. Verification

`make ci-installer` run from `packages/installer/` after all edits; see PR for
output.
