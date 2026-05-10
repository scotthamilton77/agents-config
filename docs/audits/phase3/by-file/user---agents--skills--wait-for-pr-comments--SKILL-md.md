# Findings for src/user/.agents/skills/wait-for-pr-comments/SKILL.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F1: wait-for-pr-comments exceeds 500-line body budget — extract to reference files
  File: src/user/.agents/skills/wait-for-pr-comments/SKILL.md:1-828
  Category: skill
  Severity: High
  Tier: 2
  Issue: SKILL.md is 828 lines — 66% over the 500-line progressive-disclosure budget. Schema validation guards, subagent contract, concurrency recovery branch table, and reply templates all inflate the body. Phase 2 quality-gate reviewer agrees on extraction but specifies what must remain: the phase map, Phase 8 default-on chain, inventory ownership statement, and recovery entrypoints.
  Recommendation: Extract to SCHEMA.md (hand-off contract + guard definitions), RECOVERY.md (concurrency recovery branch table), and SUBAGENT-CONTRACT.md (per-comment subagent contract + SHA-discovery procedure). Keep phase map, Phase 8 default-on chain, inventory ownership, and recovery entrypoints in SKILL.md. Add TOC to extracted files >100 lines.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 (guardrail every completion claim with mechanical evidence): a 828-line SKILL.md risks partial reads that cause the orchestrator to mis-apply phase contracts mid-run.
  Promotion-eligible: yes
  Resolution: ACCEPTED (synthesis per D10)
  Rationale: Phase 2 AGREE on extraction principle; aggregator synthesizes what stays vs. what moves.
  Sources: phase1/skills.md:F1, phase2/quality-gate-and-delivery.md:F1

---

---

F2: Schema validation guards duplicated between wait-for-pr-comments and reply-and-resolve-pr-threads
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:200-214, src/user/.agents/skills/wait-for-pr-comments/SKILL.md:683-713
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: Nine schema validation guards are reproduced verbatim in both skills. Two copies means any change must be kept in sync manually; guard numbering is already slightly inconsistent.
  Recommendation: Define guards once in a shared SCHEMA.md (per F1) referenced by both SKILL.md files. Each file keeps only the guards that are implementation-specific to its own write/read side.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 (guardrail completion claims): divergent guard descriptions will eventually cause a mismatch between what the writer enforces and what the reader expects.
  Promotion-eligible: yes
  Resolution: ACCEPTED (merged into D9/D10 synthesis)
  Rationale: Phase 2 F3 (quality-gate) agrees that shared SCHEMA.md is correct; the move-to-shared-path decision (D9) applies.
  Sources: phase1/skills.md:F2, phase2/quality-gate-and-delivery.md:F3

---

---

F3: wait-for-pr-comments — beads leakage; split shared core from beads-only autonomous mode
  File: src/user/.agents/skills/wait-for-pr-comments/SKILL.md:191,548,557-561
  Category: skill
  Severity: Critical
  Tier: 2
  Issue: Shared skill contains direct `bd` command invocations in the normative execution path (ESCALATE section, DEFER placement logic). Non-beads tools loading this skill will encounter commands they cannot execute, with no fallback defined.
  Recommendation: Keep shared PR-review core (detection, Copilot polling, classification, FIX execution, inventory handoff, interactive mode) in shared namespace. Create beads-plugin addendum or wrapper that owns autonomous mode, `--bead-id`, `bd` escalation filing, and I3-based DEFER placement. Do NOT move the whole skill to `src/plugins/beads/` per D7.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context across agent handoff and overnight runs): autonomous mode failing silently on non-Claude tools breaks overnight PR cycles without any error signal.
  Promotion-eligible: yes
  Resolution: ACCEPTED (split-not-move per D7)
  Rationale: Three Phase 2 reviewers agree on split vs. wholesale move; aggregator accepts synthesis.
  Sources: phase1/skills.md:F3, phase2/full-bead-lifecycle.md:F1, phase2/quality-gate-and-delivery.md:F2

---

---

F10: wait-for-pr-comments hardcoded ~/.claude/skills/ install path
  File: src/user/.agents/skills/wait-for-pr-comments/SKILL.md:227,244,261,326,354,410,655,672
  Category: skill
  Severity: High
  Tier: 1
  Issue: Helper script invocations use hardcoded path `~/.claude/skills/wait-for-pr-comments/` at 8+ locations. Project convention is `${CLAUDE_SKILL_DIR}` (as used correctly in merge-guard and run-queue). Hardcoded path breaks if installed to non-standard location.
  Recommendation: Replace all `~/.claude/skills/wait-for-pr-comments/` prefixes with `${CLAUDE_SKILL_DIR}/`. Mechanical substitution at 8+ locations.
  Vision-advancement-tier: C
  Vision-advancement: Removes hardcoded install path that breaks portability — a mechanical correctness fix.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not specifically address; Phase 1 finding stands as Tier 1.
  Sources: phase1/skills.md:F10

---
