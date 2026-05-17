# Findings for src/plugins/beads/.beads/formulas/merge-and-cleanup.formula.toml
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F8: merge-and-cleanup file header — replace historical motivation with purpose statement
  File: src/plugins/beads/.beads/formulas/merge-and-cleanup.formula.toml:1-19
  Category: formula
  Severity: Medium
  Tier: 2
  Issue: File-level comment opens with historical motivation explaining why the formula was created ("agents frequently skip completion gates... merges have been authorized prematurely"). This is incident retrospective language, not execution context.
  Recommendation: Replace the "why it exists" paragraph with a one-line purpose statement: "Trust-but-verify merge workflow: checks completion gate evidence, triages all PR comments, requires explicit merge authorization, then cleans up artifacts." Move design rationale to docs/specs/.
  Vision-advancement-tier: C
  Vision-advancement: Removing historical motivation from formula headers keeps the runtime-readable content strictly execution-serving.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/formulas.md:F8

---

---

F9: merge-and-cleanup merge-authorization step — remove historical incident rationale
  File: src/plugins/beads/.beads/formulas/merge-and-cleanup.formula.toml:184-219
  Category: formula
  Severity: Medium
  Tier: 2
  Issue: Step ends with "This gate exists because merges have been performed without explicit authorization, causing irreversible state changes." This is a historical incident explanation — execution guidance but the preceding historical sentence is pure motivation.
  Recommendation: Remove the final historical sentence ("This gate exists because..."). Keep "When in doubt: they have not authorized it. Ask again." and the authorization examples.
  Vision-advancement-tier: C
  Vision-advancement: Removing incident-retrospective language from step prose reduces execution noise without losing any enforcement value.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/formulas.md:F9

---

---

F10: merge-and-cleanup cleanup step — extract inline merge-gate detection shell to helper script
  File: src/plugins/beads/.beads/formulas/merge-and-cleanup.formula.toml:271-299
  Category: formula
  Severity: High
  Tier: 2
  Issue: Step 4 of the cleanup step contains ~15 lines of deterministic bash for detecting the merge-gate child (iterate children, call `bd label list` per child, check for `merge-gate` label, detect duplicates, build `MERGE_GATE` variable). Per the acid test, the agent does not need to read this shell to make any decision — it needs to invoke a helper.
  Recommendation: Extract into `bd-find-merge-gate-child.sh --bead-id <id>` that outputs the merge-gate child ID on success (exit 0) or exits non-zero with a diagnostic. The cleanup step references: `MERGE_GATE=$(bd-find-merge-gate-child.sh --bead-id {{bead-id}}) || { flag-human; exit 1; }`.
  Vision-advancement-tier: A
  Vision-advancement: Extracting the merge-gate detection loop into a tested helper advances commitment #4 (guardrail completion claims) — the helper can be run deterministically in CI while inline prose cannot.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/formulas.md:F10

---

---

F15: merge-and-cleanup check-pr-comments — delegate cleanly to wait-for-pr-comments skill
  File: src/plugins/beads/.beads/formulas/merge-and-cleanup.formula.toml:90-119
  Category: formula
  Severity: High
  Tier: 2
  Issue: The check-pr-comments step names `superpowers:wait-for-pr-comments` but then tells the agent to run raw `gh pr view` and `gh api` commands and manually triage comments itself. Two competing execution models in the step-bead. An agent can reasonably bypass the stronger skill. Phase 2 formula-step-execution reviewer AGREE.
  Recommendation: Make the step delegate cleanly to `wait-for-pr-comments --mode autonomous --bead-id {{bead-id}}` with clear postconditions: all comments classified, FIX items addressed and pushed, reply/resolve bookkeeping completed. Keep raw `gh` commands only as explicit fallback/debug outside the main happy path.
  Vision-advancement-tier: A
  Vision-advancement: Directly advances commitment #3 (substitute adversarial cross-model review) by ensuring the step uses the existing end-to-end review workflow instead of a weaker manual substitute.
  Promotion-eligible: yes
  Resolution: ACCEPTED (promoted from phase2/formula-step-execution.md:F5)
  Rationale: Phase 2 AGREE — new finding not in Phase 1, promoted to this phase.
  Sources: phase2/formula-step-execution.md:F5

---
