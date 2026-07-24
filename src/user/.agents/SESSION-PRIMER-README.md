<!--
Source: oss-snapshots/superpowers/using-superpowers/SKILL.md @ obra/superpowers commit f2cbfbe (v5.1.0)
Last lifted: 2026-05-25
Drift policy: selective-amalgamation — content was rewritten for project-owned voice and the four-tool surface (Claude Code, Codex CLI, Gemini CLI, OpenCode). Do not auto-resync from upstream.
Material edits vs. upstream:
  - Dropped upstream's <SUBAGENT-STOP> gate: subagents inherit the host's AGENTS.md context including this primer, so they cannot act on a "skip" instruction they've already read.
  - Dropped upstream's "Instruction Priority" section: agents already follow user > skills > defaults as part of their baseline instruction-following protocol; restating it here is noise. (Not redundant with the shared AGENTS.md's <laws> — those define the L0–L3 quality/safety stack, a different concern.)
  - Dropped upstream's "How to Access Skills" per-runtime listing: each runtime's own system prompt already documents its skill mechanism.
  - Dropped upstream's "Platform Adaptation" pointer to references/copilot-tools.md / references/codex-tools.md (those reference files are not in-tree).
  - Dropped upstream's DOT skill_flow digraph (none of the four tools render DOT); replaced with prose workflow steps.
  - Generalized the upstream's runtime-specific checklist-tracker invocation to runtime-agnostic phrasing (no tool name).
  - Body wrapped in <skill-usage-instructions> for context-boundary clarity.
-->
