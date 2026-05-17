# Findings for src/plugins/beads/.beads/scripts/bd-record-decision.sh
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F1: bd-record-decision.sh — usage block is a one-liner, inconsistent with sibling scripts
  File: src/plugins/beads/.beads/scripts/bd-record-decision.sh:28
  Category: script
  Severity: Medium
  Tier: 1
  Issue: The `usage()` function emits a terse one-line echo while all four sibling bd-toolkit scripts emit a full `cat >&2 <<'EOF'` block documenting every option, output format, and exit contract. --help on this script gives less information than on any other script in the same directory.
  Recommendation: Replace the one-line echo in usage() with a `cat >&2 <<'EOF' ... EOF` block covering: each option with type hint (--bead-id <id>, --title <text>, --notes <text>), the mutually exclusive flags (--implemented | --needs-approval), stdout output on success, and the exit code contract. Match the style of bd-close-walk.sh's usage block.
  Vision-advancement-tier: A
  Vision-advancement: Commitment #4 (guardrail completion claims) requires that helper scripts surface their contracts clearly; inconsistent usage blocks make automated error diagnosis harder.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/scripts.md:F1

---

---

F2: bd-record-decision.sh — stdout contract should stay human-readable; add opt-in --json mode if needed
  File: src/plugins/beads/.beads/scripts/bd-record-decision.sh:79-83
  Category: script
  Severity: Medium
  Tier: 2
  Issue: Phase 1 recommends changing the default stdout contract from human-readable to machine-readable key=value. Phase 2 formula-step-execution reviewer DISAGREE (D2): the audited formula callsite does not capture or parse stdout — the human-readable sentence is immediate confirmation that the decision bead was created. Changing the default would optimize for a caller model not present on the actual runtime path.
  Recommendation: Leave the default stdout behavior alone. Add an opt-in `--json` or `--machine` mode only if a concrete structured caller is introduced. Priority: fix the usage block (F1) first.
  Vision-advancement-tier: C
  Vision-advancement: Avoids churn that does not improve the common execution path and preserves the immediately-readable confirmation the step currently benefits from.
  Promotion-eligible: no
  Resolution: DROPPED (per D2)
  Rationale: Phase 2 DISAGREE accepted — changing the default stdout is not warranted without a concrete structured caller.
  Sources: phase1/scripts.md:F2, phase2/formula-step-execution.md:F4

---
