---
name: handoff
description: Compact the current conversation into a handoff document so a fresh agent can resume the work in a new session. Use when ending a session or when the user types /handoff [focus].
argument-hint: [focus of next session]
disable-model-invocation: true
allowed-tools: Write Bash(git status *) Bash(git log *) Bash(date *) Bash(pwd)
---

<!--
Source: oss-snapshots/pocock/handoff/ (pristine upstream); promoted project-extended fork
Upstream: https://github.com/mattpocock/skills @ e74f0061bb67222181640effa98c675bdb2fdaa7
Local extensions: Claude-specific frontmatter (disable-model-invocation, allowed-tools), !-command working-tree snapshot prelude, 8-section required document structure, redaction constraints
Last sync: 2026-05-23
Drift policy: rewrite-and-divorce (project-extended, Claude-specific; do not re-sync from upstream)
Why Claude-only (lives in src/user/.claude/skills/, not src/user/.agents/skills/): !-command syntax and disable-model-invocation/allowed-tools frontmatter keys are Claude Code conventions; staging into other tools (Codex/Gemini/OpenCode) would yield broken or degraded behavior.
-->

## Working-tree snapshot

- Project root: !`pwd`
- Branch + status: !`git status -sb`
- Recent commits: !`git log --oneline -10`
- UTC timestamp: !`date -u +%Y%m%dT%H%M%SZ`

## Task

Write a handoff document so a fresh agent can resume this work in a new session.

**Next-session focus:** $ARGUMENTS

If the focus above is empty, infer it from the conversation and state your inference at the top of the document.

## Output location

Write the file to `${TMPDIR:-/tmp}/handoff-<UTC-timestamp>-<short-slug>.md` where:

- `<UTC-timestamp>` is the value captured in the snapshot above (compact form, e.g. `20260523T143052Z`)
- `<short-slug>` is a 3–5 word kebab-case summary of the next-session focus

After writing, print the absolute file path on its own line so the user can pass it to the next session.

## Required document structure

1. **Next-session goal** — one sentence
2. **Current state** — what is in flight, branch, what compiles/passes, what does not
3. **Decisions made and rationale** — non-obvious choices only; skip the obvious
4. **Lessons learned** — anything the next agent should know to avoid pitfalls or dead ends that isn't already in the agent memory or easily discoverable in the artifacts
5. **Open questions and blockers** — anything the next agent needs to resolve before progress
6. **Next concrete steps** — ordered, actionable
7. **References** — paths and URLs only; do NOT duplicate content from PRDs, plans, ADRs, issues/beads, commits, or diffs
8. **Suggested skills** — skills the next agent should invoke (e.g. `superpowers:brainstorming`, `implement-bead`, `bugfix`)

## Constraints

- Redact API keys, passwords, tokens, and PII.
- No duplication of artifacts already on disk or in trackers. Link, do not copy.
- The document must be readable cold by an agent with zero prior context.
