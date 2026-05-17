# Findings for AGENTS.md
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F4: AGENTS.md vision section contains a bd command — beads hygiene violation (recommendation-only)
  File: AGENTS.md:27
  Category: template
  Severity: Critical
  Tier: 2
  Issue: Line 27 reads: `Search current work with: \`bd list --label vision-85-5-10\`.` This is inside the Vision & Mission section (out of scope for Tier 1/2 enforcement per audit constraints) but AGENTS.md is read by ALL agents in this repo including agents without the beads plugin. `bd` command will fail silently or produce a confusing error for non-beads agents. The Implications subsection also reads "File beads for harness friction you discover" — beads terminology in shared project-level instructions.
  Recommendation: Vision section — recommendation only per audit constraints. If the vision section is revised in a future cycle, replace the `bd list` example with a label reference (`label: vision-85-5-10`) and make "File beads for harness friction" conditional on plugin availability, or move it to the beads plugin's rules.
  Vision-advancement-tier: A
  Vision-advancement: Keeping beads commands out of shared project-level instructions directly supports commitment #5 (persist context) — all agents can read the project AGENTS.md without encountering commands that fail silently.
  Promotion-eligible: yes
  Resolution: ACCEPTED (recommendation-only per audit constraints)
  Rationale: Phase 2 escalation reviewer reinforces via OOS1; Phase 1 finding stands as Tier 2 recommendation-only.
  Sources: phase1/templates.md:F4

---

---

F9: AGENTS.md agent frontmatter schema incomplete — missing fields documented in AGENTS_PRIMER
  File: AGENTS.md:86-93
  Category: template
  Severity: Medium
  Tier: 1
  Issue: "File Formats" section documents agent frontmatter as having only `name`, `description`, `model`, and `color`. AGENTS_PRIMER.md documents additional valid fields: `tools`, `disallowedTools`, `skills`, `effort`, `memory`. Developer reading AGENTS.md to author a new agent would not know these fields exist.
  Recommendation: Expand the agent frontmatter example to include at minimum `tools`/`disallowedTools`, `skills`, `effort`, `memory` with brief comments. Match the format of AGENTS_PRIMER.md's schema table.
  Vision-advancement-tier: C
  Vision-advancement: Accurate frontmatter documentation reduces the likelihood of agents being authored with missing capability declarations.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/templates.md:F9

---

---

F10: AGENTS.md skill frontmatter schema incomplete — missing allowed-tools and model fields
  File: AGENTS.md:98-101
  Category: template
  Severity: Low
  Tier: 1
  Issue: Skill frontmatter schema in AGENTS.md shows only `name` and `description`. SKILLS_PRIMER.md documents additional valid fields: `license`, `allowed-tools`, `compatibility`, `metadata`, `model`, `effort`.
  Recommendation: Expand the skill frontmatter example to note that additional optional fields exist (model, effort, allowed-tools) and point to docs/primers/SKILLS_PRIMER.md for the full schema.
  Vision-advancement-tier: C
  Vision-advancement: Accurate schema documentation prevents authors from omitting model/effort directives that affect dispatch quality.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/templates.md:F10

---

---

F11: AGENTS.md graphify section — `graphify update .` unsafe for subagents
  File: AGENTS.md:173-177
  Category: template
  Severity: Medium
  Tier: 2
  Issue: Instruction "After modifying code files in this session, run `graphify update .`" is appropriate for the main orchestrating agent but dangerous for subagents — running from a worktree context could update the graph with partial changes or corrupt graph state. Phase 2 multi-agent reviewer OOS1 reinforces this concern for multi-agent runs.
  Recommendation: Add qualifier: "After modifying code files in this session (orchestrator only — subagents must not run this), run `graphify update .`..." Alternatively, add a condition that checks whether the session is the primary orchestrator.
  Vision-advancement-tier: A
  Vision-advancement: Subagent coordination correctness is load-bearing for overnight autonomous execution (commitment #5); a subagent corrupting the knowledge graph mid-run would break the next orchestrator session's architectural queries.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 OOS1 (multi-agent-dispatch) reinforces Phase 1 finding; aggregator strengthens via D27.
  Sources: phase1/templates.md:F11, phase2/multi-agent-dispatch.md:OOS1

---

---

F15: AGENTS.md Session Completion section — bd dolt push unguarded in mandatory workflow
  File: AGENTS.md:154
  Category: template
  Severity: Critical
  Tier: 2
  Issue: The Session Completion section contains `bd dolt push` as a mandatory step. The entire block is inside `<!-- BEGIN BEADS INTEGRATION -->` markers, but a non-beads agent following the "MANDATORY WORKFLOW" will fail at step 4 when it hits `bd dolt push` with no conditional guard. Phase 2 constraint-aware reviewer OOS1 reinforces this concern.
  Recommendation: Add a conditional note inside the Session Completion block: "(beads only — skip if beads not installed)" next to the `bd dolt push` line. This is a minimal change that preserves the block's structure while preventing agent confusion.
  Vision-advancement-tier: A
  Vision-advancement: Session completion integrity is a prerequisite for reliable overnight autonomous runs (commitment #5); a non-beads agent failing silently at `bd dolt push` will not push code, stranding work locally.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 OOS1 (constraint-aware) reinforces Phase 1 finding; aggregator strengthens via D28.
  Sources: phase1/templates.md:F15, phase2/constraint-aware-execution.md:OOS1
