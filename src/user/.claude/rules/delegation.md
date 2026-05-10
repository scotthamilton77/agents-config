# Delegation

MANDATORY delegation for non-trivial work (skip for obvious one-liners, config changes, typos):

- Planning → `superpowers:brainstorming` skill
- Implementation (default) → `superpowers:test-driven-development` first, then any applicable domain skills
- NEVER invoke `ralf-implement` unless the user explicitly requests it with a target, Definition of Done, context, and optional max cycle count
- NEVER invoke `ralf-review` unless the user explicitly requests it with a target artifact, review criteria, context, and optional max cycle count
- Tests → `writing-unit-tests` + `superpowers:test-driven-development` skills

**Cross-tool delegation:** see `codex-routing.md` for picking a Codex model when delegating review or coding work to the Codex plugin.
