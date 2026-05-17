# Findings for src/plugins/beads/.beads/formulas/implement-feature.formula.toml
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

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

---

F24: human-label semantics contradict between formulas and rules
  File: src/plugins/beads/.beads/formulas/docs-only.formula.toml:367-372, src/plugins/beads/.beads/formulas/implement-feature.formula.toml:660-666, src/plugins/beads/.claude/rules/beads-labels.md:10-13
  Category: skill (cross-category: formula + rule)
  Severity: High
  Tier: 1
  Issue: Two formulas say adding `human` label excludes a bead from `bd ready`. The beads-labels.md rule says `human` is only a visibility tag and does NOT gate readiness. An agent following the hand-off path can believe work is safely parked when it may still surface as ready.
  Recommendation: Pick one contract and make every touched file match. If `human` alone is not a readiness gate, the hand-off path must add a real blocking dependency and state this explicitly.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context): a contradictory parking contract causes resumed work to re-enter the queue before a human resolves it.
  Promotion-eligible: no
  Resolution: ACCEPTED (promoted from phase2/escalation-edge-recovery.md:F8 via D25)
  Rationale: Active contradiction between rules and formulas; Tier 1 mechanical fix (pick one contract, update all files).
  Sources: phase2/escalation-edge-recovery.md:F8

---
