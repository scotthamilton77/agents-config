# Phase 3 By-Category: Formulas
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

This file consolidates all Phase 1 and Phase 2 findings targeting the formulas category.
Cross-category findings (skills/formulas/rules interactions) noted where applicable.

---

F1: brainstorm-bead finalize step — extract helper scripts for deterministic shell sequences
  File: src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml:228-651
  Category: formula
  Severity: High
  Tier: 2
  Issue: The `finalize` step description is ~420 lines of interleaved prose and bash. Steps 1-3 and 5 contain deterministic shell sequences (idempotency probe, children pre-flight check, label-copy filtering, child migration loop, merge-gate creation) that are script candidates. Steps 3c (RALF triage), 3d (formula selection), and 9 (burn + hand-off report) are agent decision points that should remain in prose.
  Recommendation: Extract Steps 1 (idempotency probe), 2 (children pre-flight check), 3f (label-copy filtering), 5a (child migration loop), and 5b (merge-gate + [h]-child creation) into named helper scripts under `~/.beads/scripts/`. Keep agent decision points and step 3h (label assembly, purely declarative) inline. Target: reduce finalize from ~420 lines to under 100.
  Vision-advancement-tier: A
  Vision-advancement: Extracting deterministic orchestration logic from formula prose directly advances commitment #5 (persist context) — shorter, script-backed steps are more compaction-resistant and survive agent handoff with less context-window cost.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not dispute the script extraction direction; Phase 1 finding stands.
  Sources: phase1/formulas.md:F1

---

F2: brainstorm-bead — motivational rationale embedded in claim step prose
  File: src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml:41-51
  Category: formula
  Severity: Medium
  Tier: 1
  Issue: The `claim` step description contains explanatory motivation about why claim-walks are required ("Brainstorming IS work — the bead's status must reflect that…"). This is background rationale, not execution instruction. The action and its DoD are stated without this sentence.
  Recommendation: Remove the motivational sentence. Keep "The claim walk marks this bead and all ancestor epics in_progress. Read the `walked=N` output to confirm the chain depth."
  Vision-advancement-tier: C
  Vision-advancement: Removing background rationale reduces per-step context weight, reducing agent judgment cycles wasted on non-executable content.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/formulas.md:F2

---

F3: brainstorm-bead — QUESTION FILTER should stay self-contained in discuss step
  File: src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml:74-84,104-108
  Category: formula
  Severity: Medium
  Tier: 2
  Issue: Phase 1 recommends replacing the QUESTION FILTER in the discuss step with a back-reference to assess. Phase 2 formula-step-execution reviewer DISAGREE: on the actual runtime path, the discuss step-bead is its own execution prompt. A resumed or compacted session may have the discuss bead in hand without the assess text in active context. Replacing the filter with a back-reference strips the live guardrail the agent needs.
  Recommendation: Keep the QUESTION FILTER fully self-contained in the discuss step per D1/Phase 2. If noise reduction is desired, tighten the wording inside the step itself (e.g., reduce to 3-4 tight lines) rather than pointing back to assess.
  Vision-advancement-tier: A
  Vision-advancement: Supports commitments #1 and #2 (frontload judgment; make AI good at saying "no, not ready") — the executing agent needs the filter in the live step prompt to avoid over-escalating or silently guessing.
  Promotion-eligible: no
  Resolution: ACCEPTED (modified — keep self-contained, tighten wording)
  Rationale: Phase 2 DISAGREE accepted (D1); recommendation becomes "tighten, not cross-reference."
  Sources: phase1/formulas.md:F3, phase2/formula-step-execution.md:F1

---

F4: worktree-path encoding/decoding — extract to two helper scripts
  File: src/plugins/beads/.beads/formulas/docs-only.formula.toml:116-122, src/plugins/beads/.beads/formulas/fix-bug.formula.toml:100-102,139-142, src/plugins/beads/.beads/formulas/implement-feature.formula.toml:100-106,139-141
  Category: formula
  Severity: High
  Tier: 2
  Issue: The worktree-path label encoding/decoding procedure (`_ → _u`, `/ → __`) appears in prose form in at least five locations across three formula files. If the bijection changes, five prose locations must be updated in sync.
  Recommendation: Extract encoding and decoding into two helper scripts: `bd-worktree-path-encode.sh <path>` and `bd-worktree-path-decode.sh <encoded>`. Each preflight step reduces to a single script call; each consuming step reduces to `<path>=$(bd-worktree-path-decode.sh <label>)`. Flag for the scripts audit scope.
  Vision-advancement-tier: A
  Vision-advancement: Consolidating five copies of a fragile bijection into one canonical helper advances commitment #4 (guardrail completion claims) — a shared script can be tested once, whereas five prose copies cannot.
  Promotion-eligible: no
  Resolution: ACCEPTED
  Rationale: Phase 2 did not dispute extraction; Phase 1 finding stands.
  Sources: phase1/formulas.md:F4

---

F5: fix-bug and implement-feature reroute protocol — extract mechanics, keep postcondition checklist
  File: src/plugins/beads/.beads/formulas/fix-bug.formula.toml:237-318, src/plugins/beads/.beads/formulas/implement-feature.formula.toml:188-284
  Category: formula
  Severity: High
  Tier: 2
  Issue: Both red-tests steps contain a near-identical Reroute Protocol (steps 1-11). Phase 2 formula-step-execution reviewer gives PARTIAL: reroute is irreversible; the step-bead must retain a postcondition checklist so the agent can verify what the helper preserved.
  Recommendation: Extract the mechanical steps 2-11 into `bd-reroute-to-docs-only.sh`. Keep in each red-tests step: (a) trigger evaluation logic (A, B, A+B as applicable per formula), (b) an inline postcondition checklist specifying the required surviving invariants and what must be verified before considering reroute complete per D18.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (context persists through compaction and handoff) — a single tested script is more reliable than two prose copies that can silently diverge.
  Promotion-eligible: no
  Resolution: ACCEPTED (modified per D18)
  Rationale: Phase 2 PARTIAL — extract mechanics but keep postcondition checklist inline.
  Sources: phase1/formulas.md:F5, phase2/formula-step-execution.md:F3

---

F6: fix-bug file header contains pure motivational prose
  File: src/plugins/beads/.beads/formulas/fix-bug.formula.toml:1-19
  Category: formula
  Severity: Medium
  Tier: 1
  Issue: File-level comment includes "The cardinal sin of bug fixing is patching the symptom." This is motivational framing that belongs in a README or spec document, not in a formula file. The `diagnose` step description already enforces the hard gate.
  Recommendation: Remove the "cardinal sin" motivational sentence. Keep the factual stage-sequence description and the "See:" and "Usage:" comments, which are actionable references.
  Vision-advancement-tier: C
  Vision-advancement: Removing non-actionable motivational prose from formula headers reduces maintenance cognitive load.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/formulas.md:F6

---

F7: implement-feature — stale bead reference in file-level comment
  File: src/plugins/beads/.beads/formulas/implement-feature.formula.toml:12-14
  Category: formula
  Severity: Low
  Tier: 1
  Issue: File-level comment reads: "Note: per-step model/effort flag passthrough from the shell driver is planned for bead 7bk.14." Embedding a bead ID in a formula comment is a staleness risk.
  Recommendation: Remove the bead ID reference. Either state the limitation plainly ("Note: per-step model/effort flags in this file are informational only — the shell driver does not currently pass them to `claude -p`") or remove the note entirely.
  Vision-advancement-tier: C
  Vision-advancement: Removing volatile bead ID references from formula comments prevents silent documentation rot.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/formulas.md:F7

---

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

F11: name field mirrors id throughout implement-feature and fix-bug — undocumented step field
  File: src/plugins/beads/.beads/formulas/implement-feature.formula.toml:47-48, src/plugins/beads/.beads/formulas/fix-bug.formula.toml:46-47
  Category: formula
  Severity: Medium
  Tier: 1
  Issue: Both formulas set `name = "..."` on every step, mirroring `id` exactly. The FORMULAS_PRIMER does not list `name` as a valid step field. In-file comment says it "is accepted by bd... and serves as the stage-role identifier used by the shell driver." If load-bearing for the shell driver, this should be documented once at file top; if not load-bearing, it is noise. Also affects docs-only.formula.toml.
  Recommendation: Confirm whether `name` is required by the shell driver. If required, add one top-level file comment explaining the convention and remove the per-step comment from every step. If not required, remove all `name` fields.
  Vision-advancement-tier: C
  Vision-advancement: Removing redundant undocumented fields reduces per-step noise and makes formulas easier to audit and maintain.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/formulas.md:F11

---

F12: brainstorm-bead — vapor + pour are intentionally orthogonal; add clarifying comment
  File: src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml:25-26
  Category: formula
  Severity: Medium
  Tier: 2
  Issue: Phase 1 reads `phase = "vapor"` and `pour = true` as contradictory and recommends changing to `phase = "liquid"`. Three Phase 2 reviewers DISAGREE (D1, D23): these fields are orthogonal — `phase = "vapor"` signals wisp-mode interactive use; `pour = true` causes step materialization within that wisp. Changing to `liquid` would break `start-bead` Route C contract.
  Recommendation: Keep `phase = "vapor"` with `pour = true`. Add a comment in the formula header explaining the intentional semantics: "`phase = vapor` → use `bd mol wisp create` (ephemeral lifecycle); `pour = true` → still materializes executable step beads within the wisp." Update FORMULAS_PRIMER to document this valid vapor-plus-poured-wisp configuration.
  Vision-advancement-tier: A
  Vision-advancement: Supports commitments #1 and #5 — preserves brainstorming as an explicit interactive workflow while still materializing state that survives step-to-step handoff.
  Promotion-eligible: no
  Resolution: ACCEPTED (modified — no formula change; add documentation)
  Rationale: Phase 2 DISAGREE × 3 accepted (D1); finding converts to documentation task.
  Sources: phase1/formulas.md:F12, phase2/formula-step-execution.md:F6, phase2/full-bead-lifecycle.md:F5, phase2/escalation-edge-recovery.md:F4

---

F13: fix-bug diagnose step — remove superpowers:root-cause-tracing dead skill reference
  File: src/plugins/beads/.beads/formulas/fix-bug.formula.toml:134-135
  Category: formula
  Severity: Low
  Tier: 1
  Issue: diagnose step lists `superpowers:root-cause-tracing` as a preloaded skill. This skill does not exist in the known skill inventory (confirmed deleted). The step promises a root-cause workflow the agent cannot actually load.
  Recommendation: Remove `superpowers:root-cause-tracing` from the preloaded skills list and from the invocation instruction. Reference `superpowers:systematic-debugging` only (which covers root-cause work).
  Vision-advancement-tier: C
  Vision-advancement: Removing references to non-existent skills prevents silent degradation in skill invocation.
  Resolution: ACCEPTED
  Rationale: Phase 2 formula-step-execution reviewer AGREE (F7); phase2/multi-agent-dispatch.md AGREE (F6).
  Sources: phase1/formulas.md:F13, phase2/formula-step-execution.md:F7

---

F14: preflight spec validation logic duplicated across docs-only, fix-bug, implement-feature — extract mechanics only
  File: src/plugins/beads/.beads/formulas/docs-only.formula.toml:50-93, src/plugins/beads/.beads/formulas/fix-bug.formula.toml:50-114, src/plugins/beads/.beads/formulas/implement-feature.formula.toml:51-116
  Category: formula
  Severity: High
  Tier: 2
  Issue: The preflight step shares large blocks of near-identical logic. However Phase 2 escalation reviewer gives PARTIAL (D17): docs-only is the reroute target and deliberately skips coverage gates; fix-bug and implement-feature inspect coverage and park with a human flag on missing report-location. A single shared helper would collapse these divergent escalation rules.
  Recommendation: Extract only mechanically identical parts: `for-bead-<mol-id>` label stamp, worktree creation + path encoding, `worktree-path-*` label stamp, claim-walk. Keep coverage/gates policy and corresponding human-flag-vs-skip behavior inside each formula. This is a narrower extraction than Phase 1 proposed per D17.
  Vision-advancement-tier: A
  Vision-advancement: Consolidating shared mechanics into one tested helper advances commitment #4 (guardrail completion claims) while preserving formula-specific "not ready, stop here" behavior.
  Promotion-eligible: no
  Resolution: ACCEPTED (modified per D17)
  Rationale: Phase 2 PARTIAL — share mechanics, keep policy inline per formula.
  Sources: phase1/formulas.md:F14, phase2/escalation-edge-recovery.md:F5

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

## Cross-Category References

- F24 (human-label semantics contradiction between formulas and rules): canonical entry in skills.md by-category. Affects docs-only.formula.toml:367-372 and implement-feature.formula.toml:660-666
- F4 (worktree-path encoding): flagged for scripts audit subagent (`agents-config-2gzy` scope)
- F5 (reroute protocol): flagged for scripts audit subagent
- F10 (merge-gate detection): flagged for scripts audit subagent
- F14 (preflight): flagged for scripts audit subagent
