# Delegation

MANDATORY delegation for non-trivial work (skip for obvious one-liners, config changes, typos):

- Planning → `superpowers:brainstorming` skill
- Implementation (default) → `superpowers:test-driven-development` first, then any applicable domain skills
- `ralf-implement` is opt-in only:
  - bead-driven: dispatch when `ralf:required` is present at formula-step dispatch time
  - standalone: explicit `/ralf-implement <target>` invocation
- `ralf-review` is for review-type formula steps (for example `brainstorm-bead` spec review) or explicit `/ralf-review <target>` invocation
- Non-trivial work alone is NOT a trigger for `ralf-implement`
- Labels are read at dispatch boundary; label changes mid-run do not alter the active run
- Tests → `writing-unit-tests` + `testing-anti-patterns` skills

**Cross-tool delegation:** see `codex-routing.md` for picking a Codex model when delegating review or coding work to the Codex plugin.
