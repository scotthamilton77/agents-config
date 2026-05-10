# Findings for src/plugins/beads/.agents/skills/implement-bead/SKILL.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F5: implement-bead dense prose — rewrite as decision tables inline, not extraction
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:24,48,56,87
  Category: skill
  Severity: High
  Tier: 2
  Issue: Multiple lines exceed 400-1100 characters of inline prose. Line 48 (1100 chars) encodes type-to-formula routing logic, formula variable shapes, bead linkage stamping, and molecule disambiguation in one paragraph. Dense prose is fragile under agent attention compression.
  Recommendation: Rewrite §1 and §2 dense paragraphs as decision tables and numbered branches. Keep dispatch contract inline in SKILL.md (do NOT move routing algorithm to RESOLUTION.md per D14). Extract only historical rationale and long explanatory parentheticals.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4: the orchestrator cannot reliably follow 1100-character prose encoding 4 interleaved decision branches.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D14)
  Rationale: Phase 2 multi-agent reviewer gives PARTIAL; aggregator accepts inline-table synthesis.
  Sources: phase1/skills.md:F5, phase2/multi-agent-dispatch.md:F2

---

---

F6: implement-bead formula-label parsing — share expression, keep state-specific branches
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:26-46,58-79
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: 20-line shell snippet for parsing `formula-*` labels appears twice (§1 and §2). However the two blocks guard different recovery states: pre-pour (label source bead only) vs post-pour (label both source bead and step-bead, reopen step).
  Recommendation: Extract the low-level label-parsing shell expression to a single named block. Keep the pre-pour and post-pour escalation branches explicit at their call sites per D15.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context): the dispatcher's recovery behavior depends on knowing whether execution failed before or after step materialization.
  Promotion-eligible: yes
  Resolution: ACCEPTED (modified per D15)
  Rationale: Phase 2 escalation reviewer gives PARTIAL; aggregator preserves two explicit flag-human branches.
  Sources: phase1/skills.md:F6, phase2/escalation-edge-recovery.md:F2

---

---

F20: implement-bead and ralf-implement describe incompatible orchestration contracts
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:87-90,136-144, src/user/.agents/skills/ralf-implement/SKILL.md:11-53
  Category: skill
  Severity: Critical
  Tier: 2
  Issue: implement-bead treats ralf-implement as a beads-aware loop controller that receives typed worker inputs and returns an aggregate verdict compatible with step-bead closeout. ralf-implement defines no such contract — it implements directly in the working copy, runs completion-gate steps, and never mentions worker-report-v1, iteration audit labels, or aggregate return shapes. Two different orchestration models on the same seam.
  Recommendation: Choose one contract and encode it explicitly. Either make ralf-implement beads-aware by adding a formal caller contract for doer_subagent_type, worktree/report-path inputs, worker-report-v1 ingestion, and aggregate verdict output; or introduce a beads-specific adapter skill that owns the worker-report contract end to end.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context across agent handoff): the current seam cannot reliably hand off iteration state because each side believes a different contract exists.
  Promotion-eligible: yes
  Resolution: ACCEPTED (promoted from phase2/multi-agent-dispatch.md:F1)
  Rationale: Phase 2 multi-agent reviewer finds this a Critical gap not covered by Phase 1.
  Sources: phase2/multi-agent-dispatch.md:F1

---

---

F21: start-bead can route into implement-bead from a non-orchestrator context
  File: src/plugins/beads/.agents/skills/start-bead/SKILL.md:3-7,173-190, src/plugins/beads/.agents/skills/implement-bead/SKILL.md:8-10,98
  Category: skill
  Severity: High
  Tier: 2
  Issue: start-bead Route A can invoke implement-bead directly. implement-bead explicitly requires the invoking agent to be the top-level ORCHESTRATOR. start-bead never establishes this precondition. If triggered from a delegated context, it routes into a dispatcher that cannot dispatch.
  Recommendation: Add a preflight rule near the top of start-bead: if this session is not the top-level orchestrator, return the routing decision to the caller rather than invoking implement-bead directly.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5: the router must not hand work to a dispatcher that is structurally unable to spawn contracted workers.
  Promotion-eligible: yes
  Resolution: ACCEPTED (promoted from phase2/multi-agent-dispatch.md:F4)
  Rationale: Phase 2 AGREE verdict on a genuine gap not in Phase 1.
  Sources: phase2/multi-agent-dispatch.md:F4

---

---

F22: run-queue announces PR artifacts not exposed by implement-bead's contract
  File: src/plugins/beads/.agents/skills/run-queue/SKILL.md:86-104, src/plugins/beads/.agents/skills/implement-bead/SKILL.md:136-140
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: run-queue promises PR number on completion, but implement-bead does not provide progress callbacks or PR metadata. Queue orchestration announces richer status than its downstream dispatcher returns.
  Recommendation: Make run-queue outcome-driven. After implement-bead returns, inspect bead/molecule state and report only mechanically observable artifacts. Mention PR number only if a delivery step explicitly provides one.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4: queue orchestration should only announce artifacts it can prove.
  Promotion-eligible: yes
  Resolution: ACCEPTED (promoted from phase2/multi-agent-dispatch.md:F12)
  Rationale: Phase 2 AGREE verdict on a genuine gap not in Phase 1.
  Sources: phase2/multi-agent-dispatch.md:F12

---

---

F25: run-queue resolves implement-bead escalations too loosely — misses dual-bead human-flag contract
  File: src/plugins/beads/.agents/skills/run-queue/SKILL.md:117-133, src/plugins/beads/.agents/skills/implement-bead/SKILL.md:55-79,124-140
  Category: skill
  Severity: High
  Tier: 2
  Issue: run-queue resolves escalations by appending guidance and removing `human` from one bead ID. implement-bead stamps both source bead and step-bead on most recovery paths; some pauses require step reopen. Clearing one label ad hoc can requeue half-recovered work or leave a parked molecule in inconsistent state.
  Recommendation: Add a paired-resolution procedure to run-queue: identify whether escalation belongs to source bead, step-bead, or both; clear labels symmetrically only after underlying block is fixed; then re-check `bd mol current <mol-id>` and step notes before resuming queue.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context): resume behavior must be deterministic after parked molecule is handed back from human review.
  Promotion-eligible: yes
  Resolution: ACCEPTED (promoted from phase2/escalation-edge-recovery.md:F9 via D26)
  Rationale: Genuine gap not in Phase 1; Phase 2 AGREE.
  Sources: phase2/escalation-edge-recovery.md:F9

---
