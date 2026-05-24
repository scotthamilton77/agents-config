# Delegation

MANDATORY delegation for non-trivial work (skip for obvious one-liners, config changes, typos):

- Planning → `brainstorming` skill
- Implementation (default) → `test-driven-development` first, then any applicable domain skills
- NEVER invoke `ralf-implement` unless defined as part of the scope of work to be done, or the user explicitly requests it with a target, Definition of Done, context, and optional max cycle count
- NEVER invoke `ralf-review` unless defined as part of the scope of work to be done, or the user explicitly requests it with a target artifact, review criteria, context, and optional max cycle count
- Tests (writing OR designing/spec'ing — including a test plan in a brainstorm or design doc) → `writing-unit-tests` skill BEFORE drafting test names or assertions; + `test-driven-development` skill for the red-green-refactor cycle

**Cross-tool delegation:** see `claude-to-codex-routing.md` for picking a Codex model when delegating review or coding work to the Codex plugin.
