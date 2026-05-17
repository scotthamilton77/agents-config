# Findings for src/plugins/beads/.agents/agents/bead-implementor.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F1: bead-implementor — superpowers:root-cause-tracing is a deleted skill (broken reference)
  File: src/plugins/beads/.agents/agents/bead-implementor.md:31,65
  Category: agent
  Severity: High
  Tier: 1
  Issue: `skills:` frontmatter lists `superpowers:root-cause-tracing`. This skill was backed up and removed from install on 2026-05-03. It does not exist in superpowers 5.1.0 or locally. The body also invokes it by name (line 65). When dispatched, the skill cannot load — the body instruction becomes dead guidance.
  Recommendation: Remove `superpowers:root-cause-tracing` from `skills:` list. In the body, remove the reference or replace with `superpowers:systematic-debugging` alone (which exists and covers root cause work).
  Vision-advancement-tier: A
  Vision-advancement: Broken skill references silently degrade commitment #4 (guardrail every completion claim with mechanical evidence) — the systematic-debugging stage runs without its contracted methodology.
  Resolution: ACCEPTED
  Rationale: Phase 2 multi-agent reviewer AGREE (F6) and escalation reviewer (F7); Phase 1 finding stands as Tier 1.
  Sources: phase1/agents.md:F1, phase2/multi-agent-dispatch.md:F6

---

---

F3: Wrong namespace for writing-unit-tests and testing-anti-patterns in bead-pipeline agents
  File: src/plugins/beads/.agents/agents/bead-implementor.md:28-29, src/plugins/beads/.agents/agents/tdd-red-team.md:30-32, src/plugins/beads/.agents/agents/tdd-green-team.md:33-34
  Category: agent
  Severity: High
  Tier: 1
  Issue: Three agents list `superpowers:writing-unit-tests` and `superpowers:testing-anti-patterns` in `skills:` frontmatter. These skills are NOT in the superpowers plugin (confirmed: superpowers 5.1.0 has no writing-unit-tests or testing-anti-patterns directory). They are plain skills from this repo installed at `~/.claude/skills/`. The `superpowers:` namespace prefix is incorrect and will cause skill resolution failure.
  Recommendation: Replace `superpowers:writing-unit-tests` → `writing-unit-tests` and `superpowers:testing-anti-patterns` → `testing-anti-patterns` in all three files. Also fix body text references that use the wrong namespace prefix.
  Vision-advancement-tier: A
  Vision-advancement: Correct skill resolution is a prerequisite for the TDD pipeline to enforce commitment #4 (guardrail every completion claim with mechanical evidence) — misnaming skills means TDD methodology fails to load.
  Resolution: ACCEPTED
  Rationale: Phase 2 multi-agent reviewer AGREE (F7); Phase 1 finding stands as Tier 1.
  Sources: phase1/agents.md:F3, phase2/multi-agent-dispatch.md:F7

---

---

F4: bead-implementor model tier — defer until dispatch topology resolved
  File: src/plugins/beads/.agents/agents/bead-implementor.md:34
  Category: agent
  Severity: Medium
  Tier: 2
  Issue: bead-implementor assigned `model: sonnet` / `effort: medium` while companion tdd-green-team is `model: opus` / `effort: high`. However implement-bead's stage map does not dispatch bead-implementor at all — the canonical dispatches go to bug-diagnoser, tdd-red-team, tdd-green-team. Tuning bead-implementor's model before the topology question is settled hardens a non-canonical path.
  Recommendation: Resolve dispatch topology (F11/F9 — bead-implementor vs dedicated trio) first. Only then revisit model/effort defaults if the agent remains a supported dispatch target.
  Vision-advancement-tier: C
  Vision-advancement: Stabilizing which worker role is actually callable matters more than optimizing a worker the orchestrator should not normally choose.
  Promotion-eligible: yes
  Resolution: DEFERRED (per D5)
  Rationale: Phase 2 DISAGREE — tuning the wrong path is premature. Deferred until F9/F11 (dispatch topology) is resolved.
  Sources: phase1/agents.md:F4, phase2/multi-agent-dispatch.md:F8

---

---

F11: bead-implementor vs dedicated worker trio — ambiguous parallel dispatch paths
  File: src/plugins/beads/.agents/agents/bead-implementor.md:25-36
  Category: agent
  Severity: High
  Tier: 2
  Issue: bead-implementor still presents itself as the worker for diagnose, red-tests, and green-loop, but implement-bead's actual stage map dispatches bug-diagnoser, tdd-red-team, tdd-green-team. Two incompatible packages for the same stages: one appends notes and mutates tracker state, the other writes typed YAML reports. Phase 2 multi-agent reviewer AGREE: this is not documentation drift — it's two different contracts.
  Recommendation: Declare the dedicated worker trio canonical and mark bead-implementor deprecated, fallback-only, or removed from normal discovery. If backward compatibility required, add explicit "dispatch only when..." clause so orchestrator never has to guess.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context): handoff reliability collapses when two workers claim the same stage but emit different outputs and operate on different state surfaces.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 AGREE (multi-agent:F9).
  Sources: phase1/agents.md:F11, phase2/multi-agent-dispatch.md:F9

---
