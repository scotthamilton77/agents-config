# superpowers/ — Skills from obra/superpowers

## What this is

Skills brought in from Jesse Vincent's (obra) superpowers repo. These are the upstream source for the project's existing `superpowers:*` skill set. Copied here to serve as a reference baseline for analysis, drift detection, and future re-sync decisions.

## Source

- **Repo**: https://github.com/obra/superpowers
- **Commit**: `f2cbfbefebbfef77321e4c9abc9e949826bea9d7` (v5.1.0)
- **License**: MIT (see `LICENSE` in this directory, copied from upstream at the pinned commit)
- **Last refreshed**: 2026-05-17
- **Source path**: `skills/`

## Skill verdicts

Verdict pass completed under `cx6.7.6` (2026-05-23). The `superpowers` plugin is being removed once this verdict pass and its follow-up beads land — see `cx6.7.17`. Verdict legend:

- **promote** — copied into `src/user/.agents/skills/<skill>/` with provenance header; survives plugin removal as a standalone in-tree skill
- **amalgamate** — salvageable content lifted into an existing in-tree skill; capability survives via the host skill
- **drop** — capability is either already covered by an in-tree alternative or no longer needed; no successor in-tree
- **defer** — verdict postponed pending a downstream decision; capability is temporarily gone after plugin removal

| Skill | Verdict | In-tree successor / host | Follow-up bead |
|-------|---------|--------------------------|----------------|
| `brainstorming/` | promote | `src/user/.agents/skills/brainstorming/` | `cx6.7.6` (this bead) |
| `dispatching-parallel-agents/` | defer | none (revisit after Orchestrator design) | `cx6.7.15` |
| `executing-plans/` | drop | none — rare-fallback skill; brainstorming → writing-plans flow now lives in-tree | — |
| `finishing-a-development-branch/` | promote | `src/user/.agents/skills/finishing-a-development-branch/` | `cx6.7.6` (this bead) |
| `receiving-code-review/` | amalgamate | `wait-for-pr-comments` / `reply-and-resolve-pr-threads` references | `cx6.7.11` |
| `requesting-code-review/` | drop | `quality-reviewer` agent + `completion-gate.md` step 1 already own this | — |
| `subagent-driven-development/` | defer | none — pattern captured as Orchestrator design input | `cx6.7.16` |
| `systematic-debugging/` | amalgamate | `bugfix` (lift missing patterns: Iron Law, 3-strike, multi-component evidence) | `cx6.7.12` |
| `test-driven-development/` | promote | `src/user/.agents/skills/test-driven-development/` | `cx6.7.6` (this bead) |
| `using-git-worktrees/` | promote | `src/user/.agents/skills/using-git-worktrees/` | `cx6.7.6` (this bead) |
| `using-superpowers/` | amalgamate | project-owned session primer (host TBD: rules file, INSTRUCTIONS template, or new SESSION-PRIMER template) | `cx6.7.14` |
| `verification-before-completion/` | amalgamate | `verify-checklist` (lift Iron Law opener + evidence-before-assertions framing) | `cx6.7.13` |
| `writing-plans/` | promote | `src/user/.agents/skills/writing-plans/` | `cx6.7.6` (this bead) |
| `writing-skills/` | amalgamate (done) | `src/user/.agents/skills/writing-skills/` (merged with `anthropics/skill-creator`) | `cx6.7.2` (closed) |

Tally: 5 promote, 5 amalgamate (1 already done), 2 drop, 2 defer.

## Plugin removal

The `superpowers` plugin will be removed once `cx6.7.6` and follow-up beads `cx6.7.11`–`cx6.7.16` resolve. The close-out bead is `cx6.7.17`. After removal, no `superpowers:*` namespaced references should remain in `src/`.

## Notes

- All 14 skills correspond to skills currently deployed under `superpowers:*` via plugin install. The 5 promoted copies live under `src/user/.agents/skills/` and are byte-identical to the snapshots at initial import; drift begins when those copies are edited in-tree.
- This snapshot folder is retained as the reference baseline. Do not delete it after plugin removal — the amalgamation beads cite it as the lift source, and future re-sync decisions need it.
