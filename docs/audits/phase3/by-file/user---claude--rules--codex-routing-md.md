# Findings for src/user/.claude/rules/codex-routing.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F11: codex-routing.md — hardcoded plugin install path will drift
  File: src/user/.claude/rules/codex-routing.md:7-8
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: Invocation block hardcodes `$HOME/.claude/plugins/marketplaces/openai-codex/plugins/codex` — a Claude Code marketplace path subject to change without notice. If the marketplace reorganizes, all agents following this rule silently break.
  Recommendation: Move the resolved path into a settings.json env var (e.g., `CODEX_PLUGIN_HOME`) so agents reference `$CODEX_PLUGIN_HOME` and the path is configured at install time. Alternatively, extract path resolution to a helper script `scripts/codex-invoke.sh` that handles fallback logic.
  Vision-advancement-tier: A
  Vision-advancement: Directly advances commitment #5 (persist context across agent handoff and overnight runs) — hardcoded plugin paths that drift cause silent delegation failures in autonomous overnight runs.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/rules.md:F11

---

---

F12: codex-routing.md — model names are time-sensitive and will rot
  File: src/user/.claude/rules/codex-routing.md:13-15
  Category: rule
  Severity: Medium
  Tier: 2
  Issue: Model selection table hardcodes `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.3-codex-spark`. Rules are always-loaded; when model names change, this rule will silently route to deprecated models. Cost ratios are also time-sensitive.
  Recommendation: Abstract model names behind aliases defined in a companion config or settings.json (`CODEX_MODEL_FULL`, `CODEX_MODEL_MINI`, `CODEX_MODEL_SPARK`). At minimum, add a note: "Model names current as of 2026-05; verify against `codex:status` or plugin changelog if encountering 'model not found' errors."
  Vision-advancement-tier: A
  Vision-advancement: Prevents silent routing failures in autonomous overnight runs caused by deprecated model names in always-loaded rules.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/rules.md:F12

---
