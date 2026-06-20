# Rules Rightsizing — Design Spec

**Date:** 2026-06-20
**Status:** Approved — implementing Phase A (content only)
**Scope:** Audit, rightsize, and de-noise the always-on rule files under
`src/user/.agents/rules/` and `src/user/.claude/rules/`; relocate tool-specific
rules into plugin namespaces; fold skill-duplicating rules into their skills.
**This PR makes zero installer changes** — see Follow-up beads.

---

## 1. Problem

`src/user/.agents/rules/*.md` install to `~/.claude/rules/` (and flatten into
Codex/Gemini/OpenCode instruction files). These are **user-scoped, not
project-scoped** — every rule loads in every session of every repo. Twenty-two
rule files now ride along always-on. Some are universal and earn that slot;
others are tool-specific gotchas burning context in projects that never touch
the tool, or duplicate a skill that already fires at the right moment.

## 2. Evaluation lens — two axes

A rule earns an always-on slot only if **both** hold:

1. **Universal** — fires regardless of which tools a project uses. Tool-specific
   gotchas (beads, crit, graphify, codex) fail this; they belong in a plugin
   namespace that deploys *only when the tool is detected*.
2. **Not better-timed by a skill** — if a skill already owns the workflow and
   triggers at the moment of need, an always-on rule duplicates it.

Token efficiency is the third lever, applied to survivors: terse constraint in
the `.md`; rationale / incident history / "when to revisit" in the companion
`rules-readmes/<name>-readme.md` (source-only, never installed).

## 3. Per-rule disposition

Legend — **KEEP** (universal, trim only) · **MOVE→plugin** · **FOLD→skill** ·
**DELETE**.

### Shared — `src/user/.agents/rules/`

| Rule | Verdict | Action |
|---|---|---|
| `AGENTS.md` (meta) | deferred | Leaks into assembled context; fixed in bead `agents-config-8b833`. Untouched here. |
| `bash-scripting.md` | KEEP (low-priority) | Already terse; readme exists. First candidate if global count must shrink later. |
| `beads.md` | **MOVE→plugin** | → `src/plugins/beads/.agents/rules/beads.md`; readme → `src/plugins/beads/.agents/rules-readmes/`. Deploys on current installer (beads already registered). |
| `completion-gate.md` | KEEP | Drop `(checklist step N)` parentheticals. |
| `crit.md` | **DELETE** | 183 B output-path tip; trivially discoverable via `ls`. Not worth a plugin. No readme exists. |
| `delegation.md` | KEEP | Trim verbose `ralf-*` clauses; replace the `claude-to-codex-routing.md` file-path citation with a concept reference. |
| `delivery.md` | KEEP + **split** | Extract beads "Discovered-work placement" → standalone `src/plugins/beads/.agents/rules/discovered-work.md`; drop checklist parentheticals; move war-story prose to readme. |
| `git-hygiene.md` | **DELETE** | 176 B; low standalone signal. |
| `github-cli.md` | KEEP | Terse; recurs on every PR. |
| `graphify.md` | **MOVE→plugin** | → `src/plugins/graphify/.agents/rules/graphify.md`. Deploy gated on bead `agents-config-r8wsz`. |
| `memory-routing.md` | KEEP | Minor trim only. |
| `pr-authoring.md` | KEEP | Readme exists; recurs on PR creation. |
| `stacked-prs.md` | **DELETE** | Niche; fires rarely. Delete rule **and** its readme. |
| `subagents.md` | KEEP | Move the `.gitignore` worked-example to readme; keep the three constraints. |
| `testing-principles.md` | **FOLD→skill (delete)** | Fully covered by `writing-unit-tests` Tautology Filter (§5). Delete rule + orphaned readme; no skill edit. |
| `user-prompts.md` | KEEP | Tighten prose; content is load-bearing (the 4-option cap). |
| `worktrees.md` | KEEP | Move cleanup bash block + narrative to readme; keep location rule + override terse. |

### Claude-specific — `src/user/.claude/rules/`

| Rule | Verdict | Action |
|---|---|---|
| `AGENTS.md` (meta) | deferred | Same leak; bead `agents-config-8b833`. Untouched here. |
| `claude-sandbox.md` | KEEP | Terse; every sandbox commit. |
| `claude-to-codex-routing.md` | **MOVE→plugin** | → `src/plugins/codex/.claude/rules/codex-routing.md`. Deploy gated on bead `agents-config-r8wsz`. |
| `headless-claude.md` | KEEP (low-priority) | Niche but high cost-of-failure (silent no-op); terse. |
| `orchestrating-subagents.md` | KEEP | Pointer retained for the always-on nudge toward the skill. |
| `skill-model-pinning.md` | **FOLD→skill (delete)** | Not covered by `writing-skills` (§5). Add a tool-neutral note to its Frontmatter section, then delete the rule. |
| `worktree-safety.md` | KEEP | Readme exists; minor trim. |

**Net after this PR:** always-on rules drop **22 → 14** (deletes: crit,
git-hygiene, stacked-prs, testing-principles, skill-model-pinning; moves: beads,
graphify, codex-routing). The four tool-specific rules leave the global set;
graphify + codex go dark until bead `agents-config-r8wsz`.

## 4. Plugin namespace structure

Folders created this PR (contents only — no installer wiring):

```
src/plugins/beads/.agents/rules/beads.md
src/plugins/beads/.agents/rules/discovered-work.md     # extracted from delivery.md
src/plugins/beads/.agents/rules-readmes/beads-readme.md
src/plugins/graphify/.agents/rules/graphify.md
src/plugins/codex/.claude/rules/codex-routing.md
```

- **beads** — already in `ALL_PLUGINS` + auto-detected; the overlay pass picks up
  `src/plugins/beads/.agents/rules/` automatically when beads is active.
- **graphify / codex** — installer registration + detection predicates are bead
  `agents-config-r8wsz`. Until then they are staged in source but not deployed.

## 5. Skill-fold verification (done)

- **`testing-principles` → `writing-unit-tests`:** Both points already in the
  skill's "Tautology Filter" (same "What coded decision does this pin?" framing,
  language/compiler/uncalled-method/enum-literal cases, consumer-boundary
  guidance). **Covered → delete rule, no skill edit.**
- **`skill-model-pinning` → `writing-skills`:** No coverage of model pinning /
  parent-context / `ContextLimitExceeded` in the skill. **Add a tool-neutral note**
  to the Frontmatter section, then delete the rule. The rule is Claude-specific
  (`model:` frontmatter); phrased generally ("don't pin a small/cheap model — a
  skill inherits the parent's full context") it stays sound for the shared skill.

## 6. Token-efficiency rewrite principles

Applied to all KEEP survivors:

- **Rationale → readme.** War-stories, incident history, worked examples leave
  the rule; the rule states the constraint and nothing else.
- **Drop cross-ref noise.** `(checklist step N)` parentheticals and file-path
  citations (`see X.md`) — replace the latter with concept references per the
  no-file-path-citation constraint.
- **No meta sections.** Self-evident `## Rules for …` headers go.

*Example — `worktrees.md`:* keep the location rule + the "disregard the skill's
`.worktrees/` default" override (≈4 lines); move the post-merge cleanup bash
block and the `branch -d` vs `-D` narrative to `worktrees-readme.md`.

## 7. Follow-up beads (out of this PR)

- **`agents-config-8b833`** — installer: stop `rules/AGENTS.md` meta-docs leaking
  into assembled instructions (relocate meta-docs + exclude `AGENTS.md`/`README.md`
  from the rules glob).
- **`agents-config-r8wsz`** — installer: register + tune detection for the
  graphify and codex plugin namespaces (regression window noted in the bead).
- **`agents-config-kdh1h`** — installer: prune the 5 deleted always-on rules
  from user space (already-deployed copies persist in `~/.claude/rules/` until
  pruned; resolve whether `--prune` auto-handles or explicit `installer.toml`
  retired entries are needed).
