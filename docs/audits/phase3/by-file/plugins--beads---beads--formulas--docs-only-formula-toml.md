# Findings for src/plugins/beads/.beads/formulas/docs-only.formula.toml
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
