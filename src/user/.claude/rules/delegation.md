# Delegation

MANDATORY delegation for non-trivial work (skip for obvious one-liners, config changes, typos):

- Planning → `superpowers:brainstorming` skill
- Implementation (default) → `superpowers:test-driven-development` first, then any applicable domain skills
- `ralf-implement` is opt-in only via explicit invocation with a target, Definition of Done, context, and optional max cycle count
- `ralf-review` is opt-in only via explicit invocation with a target artifact, review criteria, context, and optional max cycle count
- Non-trivial work alone is NOT a trigger for `ralf-implement`
- Tests → `writing-unit-tests` + `superpowers:test-driven-development` skills

**Cross-tool delegation:** see `codex-routing.md` for picking a Codex model when delegating review or coding work to the Codex plugin.
