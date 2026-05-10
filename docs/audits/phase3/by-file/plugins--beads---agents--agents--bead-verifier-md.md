# Findings for src/plugins/beads/.agents/agents/bead-verifier.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F12: bead-verifier description — imperative phrasing instead of third-person trigger contract
  File: src/plugins/beads/.agents/agents/bead-verifier.md:3-27
  Category: agent
  Severity: Low
  Tier: 1
  Issue: Description begins "PROACTIVELY collect mechanical verification evidence…" — imperative/second-person framing of a dispatch trigger, not third-person description of what the agent does.
  Recommendation: Rewrite opening to third-person: "Mechanical verification agent that collects quality-gate evidence at completion gates — runs the project's quality-gate commands (tests, build, lint, typecheck, etc.) and reports raw exit codes plus terse error excerpts."
  Vision-advancement-tier: C
  Vision-advancement: Correct description framing ensures reliable dispatch-trigger matching, preventing the orchestrator from bypassing the verification step.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/agents.md:F12
