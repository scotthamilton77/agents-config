# Phase 2 Review: Formula → Step Bead Execution
Reviewer: Codex GPT-5.4 adversarial reviewer
SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851
Use case: Agent executing a step bead copied from a formula
Categories touched: formulas, rules, scripts

F1: `discuss` step needs a self-contained QUESTION FILTER
  File: src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml:95-107
  Category: formula
  Severity: High
  Tier: 2
  Issue: Phase 1 treats the repeated QUESTION FILTER as compressible duplication, but on the actual runtime path the `discuss` step-bead is its own execution prompt. A resumed or compacted session may have the `discuss` bead in hand without the `assess` text in active context. Replacing the filter with a back-reference would strip the live guardrail that tells the agent which questions belong to the user and which decisions it must make itself.
  Recommendation: Keep the QUESTION FILTER fully self-contained in the `discuss` step. Noise reduction is still possible, but only by tightening the wording inside the step itself, not by pointing back to `assess`.
  Vision-advancement-tier: A
  Vision-advancement: This directly supports commitment #1 (frontload human creativity and judgment) and commitment #2 (make AI good at saying "no, not ready") because the executing agent needs the filter in the live step prompt to avoid either over-escalating or silently guessing on requirements questions.
  Promotion-eligible: no
  Phase-1-source: phase1/formulas.md:F3
  Verdict: DISAGREE
  Counter-recommendation: Reduce the block to 3-4 tight lines if desired, but keep the actual decision rule inline in `discuss` rather than replacing it with a cross-step reference.

F2: beads runtime semantics cannot be demoted wholesale into opt-in reference material
  File: src/plugins/beads/.claude/rules/beads.md:10-18,48-87; src/plugins/beads/.claude/rules/beads-labels.md:5-35
  Category: rule
  Severity: High
  Tier: 2
  Issue: Phase 1 is right that these rule files contain reference-heavy material, but it over-corrects by treating most of that material as non-runtime. The common execution path dereferences these rules as authority for `for-bead-*` molecule lookup, `implementation-readied-session-*` session gating, `human` label semantics, the I3 sibling test for discovered work, and the `--notes` overwrite footgun. `implement-bead` explicitly cites both rules. If the substance moves behind an optional skill/reference hop, the executing agent may not have the semantics loaded when it is deciding how to route, resume, or file follow-up work.
  Recommendation: Keep a concise always-loaded runtime contract in the beads rules, and move only examples, CLI glossaries, and inline command blocks out. The rules should still define label semantics, molecule-linkage semantics, I3 placement policy, session-separation semantics, and destructive-write warnings.
  Vision-advancement-tier: A
  Vision-advancement: This supports commitment #5 (persist context so work survives compaction and handoff) because step execution depends on stable shared semantics for labels and molecule linkage even when the agent does not explicitly load a separate beads reference skill.
  Promotion-eligible: yes
  Related: F3
  Phase-1-source: phase1/rules.md:F3, F4
  Verdict: PARTIAL
  Counter-recommendation: Trim aggressively, but preserve the runtime contract in always-loaded rules and move only non-normative tables/examples to reference files.

F3: reroute helper extraction must leave the step-bead with a postcondition checklist
  File: src/plugins/beads/.beads/formulas/fix-bug.formula.toml:230-318; src/plugins/beads/.beads/formulas/implement-feature.formula.toml:182-284
  Category: formula
  Severity: High
  Tier: 2
  Issue: Phase 1 correctly identifies duplicated reroute mechanics, but its proposed end state collapses the step to "evaluate triggers, call script, exit." On the runtime path that is too thin. Reroute is an irreversible branch: it clones a new bead, restamps labels, creates a new merge-gate child, reparents open `[h]` children, closes the original gate, closes the original bead, and burns the molecule. The executing agent needs those invariants in the step-bead so it can verify what the helper was supposed to preserve instead of blindly trusting a side-effect-heavy script.
  Recommendation: Extract the mechanics into a helper script, but keep an inline postcondition checklist in both `red-tests` steps describing the required surviving invariants and what must be verified before considering reroute complete.
  Vision-advancement-tier: A
  Vision-advancement: This strengthens commitment #4 (guardrail every completion claim with mechanical evidence) because the step-bead still tells the executing agent what success must look like after the helper runs.
  Promotion-eligible: yes
  Related: F2
  Phase-1-source: phase1/formulas.md:F5
  Verdict: PARTIAL
  Counter-recommendation: Reduce the 11-step prose to trigger logic plus a short invariant checklist, not to a bare helper invocation with no runtime verification contract.

F4: `bd-record-decision.sh` does not need a new default stdout contract for the current step-execution path
  File: src/plugins/beads/.beads/scripts/bd-record-decision.sh:76-83
  Category: script
  Severity: Medium
  Tier: 2
  Issue: Phase 1 assumes callers need machine-readable stdout, but the audited formula callsite in `brainstorm-bead` simply tells the agent to run the script and does not capture or parse the output. On the common write-spec path, the human-readable success line is immediate confirmation that the decision bead was created and whether it was closed or flagged. Replacing the default contract now would optimize for a caller model that is not present in the runtime path under review.
  Recommendation: Leave the default stdout behavior alone unless a concrete structured caller is introduced. Prioritize the help/usage improvement first. If structured consumption becomes necessary later, add an explicit `--json` or `--machine` mode instead of replacing the current default.
  Vision-advancement-tier: C
  Vision-advancement: This avoids churn that does not improve the common execution path and preserves the immediately-readable confirmation the step currently benefits from.
  Promotion-eligible: no
  Phase-1-source: phase1/scripts.md:F2
  Verdict: DISAGREE
  Counter-recommendation: Add an opt-in machine-readable mode only when a real caller needs it; do not treat the current human-readable stdout as a runtime defect.

F5: `merge-and-cleanup` mixes skill delegation with a weaker manual PR-comment workflow
  File: src/plugins/beads/.beads/formulas/merge-and-cleanup.formula.toml:90-119
  Category: formula
  Severity: High
  Tier: 2
  Issue: The `check-pr-comments` step names `superpowers:wait-for-pr-comments`, but then tells the agent to run raw `gh pr view` and `gh api` commands and manually triage comments itself. That creates two competing execution models in the step-bead. An agent can reasonably bypass the stronger skill and perform a weaker manual pass, or double-run both. On this runtime path, that ambiguity is active harm because the repo already has a load-bearing review responder skill with its own autonomous arg contract and thread-resolution chain.
  Recommendation: Make the step delegate cleanly to `wait-for-pr-comments --mode autonomous --bead-id {{bead-id}}` and define expected postconditions only: all comments classified, FIX items addressed and pushed, and reply/resolve bookkeeping completed. Keep raw `gh` commands only as explicit fallback/debug instructions outside the main happy path.
  Vision-advancement-tier: A
  Vision-advancement: This directly advances commitment #3 (substitute adversarial cross-model review for human review wherever quality permits) by ensuring the step actually uses the existing end-to-end review workflow instead of a weaker manual substitute.
  Promotion-eligible: yes
  Verdict: AGREE

F6: `brainstorm-bead` persistence mode must match its cross-session execution role
  File: src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml:18-26
  Category: formula
  Severity: High
  Tier: 1
  Issue: The common runtime path here is explicitly cross-session and stateful: brainstorm, spec write-back, RALF review, finalize, produce downstream implementation bead. Marking the formula `phase = "vapor"` while also setting `pour = true` leaves the execution model ambiguous exactly where the system needs durable state. That is not cosmetic drift; it muddies whether this workflow is supposed to survive handoff and resumption.
  Recommendation: Align the formula to the durable path: `phase = "liquid"` with `bd mol pour` usage, unless the project intentionally wants brainstorming runs to be ephemeral and disposable.
  Vision-advancement-tier: A
  Vision-advancement: This supports commitment #5 (persist context so work survives compaction, handoff, and overnight runs) because brainstorm-bead is upstream of implementation and cannot safely behave like a throwaway wisp.
  Related: F1
  Phase-1-source: phase1/formulas.md:F12
  Verdict: AGREE

F7: the `diagnose` step cannot depend on a deleted skill name
  File: src/plugins/beads/.beads/formulas/fix-bug.formula.toml:129-156
  Category: formula
  Severity: High
  Tier: 1
  Issue: On the bug path, `diagnose` is the hard gate before red tests and code changes. Referencing `superpowers:root-cause-tracing` when that skill is not installed turns a required execution aid into a phantom dependency. The step then promises a root-cause workflow the agent cannot actually load, weakening the root-cause gate that is supposed to stop symptom-patching.
  Recommendation: Remove the dead skill reference or replace it with an installed equivalent, and keep the step's explicit root-cause requirements as the load-bearing runtime contract.
  Vision-advancement-tier: A
  Vision-advancement: This supports commitment #4 (guardrail every completion claim with mechanical evidence) because the bug pipeline's first execution gate only works if the promised diagnostic methodology is actually available.
  Phase-1-source: phase1/formulas.md:F13
  Verdict: AGREE
