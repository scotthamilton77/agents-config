# Findings for src/user/.agents/INSTRUCTIONS.md.template
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F5: INSTRUCTIONS.md.template — skill names are shared, not Claude-only; genericize phrasing only
  File: src/user/.agents/INSTRUCTIONS.md.template:41,42
  Category: template
  Severity: High
  Tier: 2
  Issue: Phase 1 recommends replacing `self-improving-agent` and `verify-checklist` skill names with generic prose. Phase 2 constraint-aware reviewer gives PARTIAL (D6): these ARE shared skills in `src/user/.agents/skills/` — not Claude-only. Removing their names would weaken always-loaded triggers that have portable implementations. However "Plan mode" IS Claude-specific.
  Recommendation: Keep the named skill triggers `self-improving-agent` and `verify-checklist`. Replace "Plan mode" (Claude-specific feature name) with "planning phase" or "structured planning". Add "when available" softener to skills that genuinely depend on tool support. This is the D6 synthesis.
  Vision-advancement-tier: A
  Vision-advancement: Making the shared template truly tool-agnostic advances the mission to make the 85/5/10 ratio achievable on any major AI coding assistant; keeping named shared-skill triggers preserves portable implementation of correction capture and completion audit.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D6)
  Rationale: Phase 2 PARTIAL — genericize Claude-specific phrasing only; keep shared skill names.
  Sources: phase1/templates.md:F5, phase2/constraint-aware-execution.md:F2

---

---

F13: INSTRUCTIONS.md.template database constraint — genericize wording, keep in shared template
  File: src/user/.agents/INSTRUCTIONS.md.template:24
  Category: template
  Severity: Critical
  Tier: 2
  Issue: "Never copy Dolt or SQLite databases while WAL is locked" is beads-plugin-specific terminology in a shared template. Phase 1 recommends moving it to beads-only rules. Phase 2 constraint-aware reviewer gives PARTIAL (D4): Codex and Gemini have no beads rules today — moving the warning would create a database-safety blind spot for those tools.
  Recommendation: Keep the database-safety constraint in INSTRUCTIONS.md.template but reword to lead with the generic principle: "Never copy live databases (such as Dolt or SQLite with WAL enabled) from worktree directories if the database lives in the main tree." The concrete examples (`Dolt or SQLite`) make the abstract rule legible and remain as illustration, not as the primary framing. The beads plugin then adds its Dolt-specific reinforcement as an additive rule per D4.
  Vision-advancement-tier: A
  Vision-advancement: Removes beads-specific database terminology as the framing while preserving the database-safety constraint in the one layer all tools currently load — exactly where overnight autonomous runs need it.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D4)
  Rationale: Phase 2 PARTIAL — reword for portability but don't remove; aggregator accepts synthesis.
  Sources: phase1/templates.md:F13, phase2/constraint-aware-execution.md:F3

---

---

F14: INSTRUCTIONS.md.template — references context7 by name in shared template
  File: src/user/.agents/INSTRUCTIONS.md.template:18
  Category: template
  Severity: Critical
  Tier: 1
  Issue: "look up docs via context7 before using it" — `context7` is a specific MCP plugin available in Claude Code but not necessarily in Codex/Gemini/OpenCode. Non-Claude agents following this instruction will attempt to use a tool that doesn't exist.
  Recommendation: Replace "look up docs via context7 before using it" with "look up current docs via available documentation tools (e.g., context7 MCP if available, or web search) before using it." (Promoted to Tier 1 per D22.)
  Vision-advancement-tier: A
  Vision-advancement: Removing Claude-specific tool references from the shared constraint template directly advances the mission of making the discipline layer portable to any major AI coding assistant.
  Resolution: ACCEPTED (promoted to Tier 1 per D22)
  Rationale: Phase 2 did not specifically address; D22 tier1-promotion confirmed with Before/After snippet.
  Sources: phase1/templates.md:F14

---
