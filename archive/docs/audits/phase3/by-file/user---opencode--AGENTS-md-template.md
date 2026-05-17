# Findings for src/user/.opencode/AGENTS.md.template
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F6: OpenCode AGENTS.md.template missing subtitle
  File: src/user/.opencode/AGENTS.md.template:1-8
  Category: template
  Severity: Low
  Tier: 1
  Issue: Claude and Codex AGENTS.md.template files begin with `# AGENTS.md` followed by `User-scoped instructions for all projects.` as a subtitle. OpenCode template begins with only `# AGENTS.md` and immediately proceeds to DYNAMIC-INCLUDE markers. Minor structural inconsistency.
  Recommendation: Add the subtitle line `User-scoped instructions for all projects.` between the heading and the first DYNAMIC-INCLUDE marker.
  Vision-advancement-tier: C
  Vision-advancement: Minor cross-tool template consistency improvement.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/templates.md:F6

---
