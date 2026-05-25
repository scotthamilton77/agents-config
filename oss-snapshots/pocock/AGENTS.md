# pocock/ — Skills from mattpocock/skills

## What this is

Unmodified-upstream snapshot of the in-scope skills from Matt Pocock's public skills repo. Snapshot layout is flat (one folder per skill, no upstream category folders); the upstream category is recorded in the inventory table below.

Scope was set in cx6.7.5: all non-Skip skills from the 4vn5.2 audit **except** the `deprecated/` subtree, which was excluded as out of scope.

## Source

- **Repo**: https://github.com/mattpocock/skills
- **Commit**: `e74f0061bb67222181640effa98c675bdb2fdaa7`
- **Last refreshed**: 2026-05-23
- **Source paths**: `skills/engineering/`, `skills/in-progress/`, `skills/misc/`, `skills/productivity/`

## Skills

Per-skill notes record the upstream source path, the 4vn5.2 audit verdict, the cx6.7.5 disposition (promote / amalgamate / defer / out-of-scope), and the landing target where applicable.

| Skill | Upstream path | Audit | cx6.7.5 verdict | Landing target / notes |
|-------|---------------|-------|-----------------|------------------------|
| `caveman/` | `productivity/caveman` | Gap-fill | **promoted (project-extended fork)** | `src/user/.agents/skills/caveman/` — local fork from `.claude/skills/caveman/` (intensity levels + boundaries). Drift policy: rewrite-and-divorce. |
| `diagnose/` | `engineering/diagnose` | Compare-and-improve | **deferred — verdict open** | `bugfix` received a sibling lift from `oss-snapshots/superpowers/systematic-debugging/`; diagnose-specific patterns (loop-construction toolkit for Thread 2, "iterate on the loop itself" rules, ranked-hypothesis cadence in Synthesis Gate, and `scripts/hitl-loop.template.sh`) remain upstream-only. A follow-up tracks whether to lift, drop, or close with rationale. |
| `git-guardrails-claude-code/` | `misc/git-guardrails-claude-code` | Compare-and-improve | **deferred** | Existing `claude-sandbox.md` policy covers the same surface via documentation; hook-based mechanical enforcement is a separate decision. Revisit if/when policy-only enforcement proves insufficient. |
| `grill-me/` | `productivity/grill-me` | Compare-and-improve | **deferred** | Stripped-down variant of `grill-with-docs`, which is being promoted. Re-evaluate only if a lighter grilling cadence is wanted separately. |
| `grill-with-docs/` | `engineering/grill-with-docs` | Compare-and-improve | **promoted (pristine)** | `src/user/.agents/skills/grill-with-docs/` — byte-identical to upstream (verified `diff -rq` clean). Drift policy: accept-periodic-resync. |
| `handoff/` | `productivity/handoff` | Compare-and-improve | **promoted (project-extended fork, Claude-only)** | `src/user/.claude/skills/handoff/` — local fork uses `!`-command syntax and Claude-specific frontmatter that does not portably stage into Codex/Gemini/OpenCode. Drift policy: rewrite-and-divorce. |
| `improve-codebase-architecture/` | `engineering/improve-codebase-architecture` | Gap-fill | **promoted (pristine)** | `src/user/.agents/skills/improve-codebase-architecture/`. Drift policy: accept-periodic-resync. References `../grill-with-docs/CONTEXT-FORMAT.md` and `../grill-with-docs/ADR-FORMAT.md` — resolved by sibling `grill-with-docs/` promotion above. |
| `prototype/` | `engineering/prototype` | Gap-fill | **promoted (pristine)** | `src/user/.agents/skills/prototype/` — includes `LOGIC.md` and `UI.md` companions. Drift policy: accept-periodic-resync. |
| `review/` | `in-progress/review` | Spark | **deferred** | Two-axis Standards-vs-Spec sub-agent pattern; defer until a clear amalgamation target exists in `ralf-review` / `test-review`. |
| `setup-matt-pocock-skills/` | `engineering/setup-matt-pocock-skills` | Skip | **out of scope** | Convention scaffold for `to-issues`/`to-prd`/`triage`. Deferred to `agents-config-wgclw.7` (revisit under M0 work-tracker abstraction). |
| `setup-pre-commit/` | `misc/setup-pre-commit` | Spark | **deferred** | Husky + lint-staged is Node.js-specific; agents-config is documentation. Pattern-only reference; no immediate landing target. |
| `tdd/` | `engineering/tdd` | Compare-and-improve | **amalgamated → `writing-unit-tests`** (cx6.7.10) | Anti-horizontal-slicing rule + diagram and proactive interface-design pre-phase pulled into native `writing-unit-tests`. Companion files (`deep-modules.md`, `interface-design.md`, `mocking.md`, `refactoring.md`, `tests.md`) intentionally not amalgamated — load-bearing content is inline in `writing-unit-tests/SKILL.md`. `superpowers:test-driven-development` left untouched (plugin-sourced). |
| `to-issues/` | `engineering/to-issues` | Compare-and-improve | **out of scope** | Deferred to `agents-config-wgclw.7`. |
| `to-prd/` | `engineering/to-prd` | Compare-and-improve | **out of scope** | Deferred to `agents-config-wgclw.7`. |
| `triage/` | `engineering/triage` | Gap-fill | **out of scope** | Deferred to `agents-config-wgclw.7`. |
| `write-a-skill/` | `productivity/write-a-skill` | Compare-and-improve | **deferred — verdict open** | Compare against the in-tree `writing-skills` amalgam (superpowers + anthropics). A follow-up tracks the comparison and verdict (lift deltas, close with rationale). |
| `zoom-out/` | `engineering/zoom-out` | Gap-fill | **promoted (pristine)** | `src/user/.agents/skills/zoom-out/`. Drift policy: accept-periodic-resync. Kept separate from `where-does-this-fit` (renamed from `big-picture`) — different triggers, complementary skills. |

## Out of scope — `deprecated/` subtree

Excluded from this snapshot per cx6.7.5 direction:

| Skill | Upstream path | Audit | Reason |
|-------|---------------|-------|--------|
| `design-an-interface` | `deprecated/design-an-interface` | Spark | `deprecated/` subtree excluded |
| `qa` | `deprecated/qa` | Gap-fill | `deprecated/` subtree excluded |
| `request-refactor-plan` | `deprecated/request-refactor-plan` | Compare-and-improve | `deprecated/` subtree excluded |
| `ubiquitous-language` | `deprecated/ubiquitous-language` | Gap-fill | `deprecated/` subtree excluded |

The full audit lives at `docs/beads/4vn5.2-mattpocock-skills-audit.md`.

## Related beads

- `agents-config-cx6.7.5` — this verdict pass
- `agents-config-cx6.7.9` — update AGENTS.md template to note CONTEXT.md at project root as soft convention
- `agents-config-wgclw.7` — revisit `setup-matt-pocock-skills`/`to-issues`/`to-prd`/`triage` under M0 work-tracker abstraction

## Notes

- `README-engineering.md` is the upstream `skills/engineering/README.md` preserved verbatim. It covers only the engineering subset of the in-scope inventory above — see this `AGENTS.md` for the full picture and per-skill verdicts.
