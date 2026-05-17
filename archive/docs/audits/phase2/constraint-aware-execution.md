# Phase 2 Review: Constraint-Aware Execution
Reviewer: Codex GPT-5.4 adversarial reviewer
SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851
Use case: Always-loaded rules and INSTRUCTIONS.md template constraining agent behavior
Categories touched: rules, INSTRUCTIONS.md.template

F1: Codex and Gemini still lack always-loaded rule implementations for the shared verification workflow
  File: src/user/.agents/INSTRUCTIONS.md.template:47-68; src/user/.codex/AGENTS.md.template:5-8; src/user/.gemini/GEMINI.md.template:5-8
  Category: template
  Severity: High
  Tier: 2
  Issue: The shared template says checklist steps 1-10 are mandatory and that tool-specific extensions define how to execute them, but the Codex and Gemini entry templates inject no equivalent rule layer at all. That leaves those tools with obligations but no always-loaded implementation for completion-gate, delivery sequencing, subagent hygiene, or worktree policy.
  Recommendation: Land an always-loaded Codex/Gemini equivalent for the core rule set before trimming shared instruction text. If the exact Claude rules cannot be reused verbatim, add tool-neutral sections that preserve the same constraints and sequencing.
  Vision-advancement-tier: A
  Vision-advancement: This directly supports commitment 4 by preserving a mechanical path from the shared verification checklist to executable behavior instead of leaving Codex and Gemini with unenforced aspirations.
  Promotion-eligible: yes
  Related: F2, F3, F6
  Phase-1-source: phase1/templates.md:F1
  Verdict: AGREE

F2: Genericizing away `self-improving-agent` and `verify-checklist` would delete real always-loaded triggers, not noise
  File: src/user/.agents/INSTRUCTIONS.md.template:37-41
  Category: template
  Severity: High
  Tier: 2
  Issue: Phase 1 treated `self-improving-agent` and `verify-checklist` as Claude-only skill names, but in this repo they are shared skills under `src/user/.agents/skills/`. Replacing them with abstract prose would weaken two concrete, always-loaded triggers that already map to portable implementation. The portability concern is real for the phrase `Plan mode`, but the skill-name cleanup recommendation overreaches.
  Recommendation: Keep the named skill triggers in shared instructions. If desired, soften the surrounding wording to be tool-neutral: "enter a planning phase" instead of "Plan mode," and "use `verify-checklist` when available; otherwise perform the same audit explicitly."
  Vision-advancement-tier: A
  Vision-advancement: This preserves commitment 5 by keeping correction capture and completion audit attached to concrete mechanisms that survive handoff and compaction instead of degrading into vague intent.
  Promotion-eligible: yes
  Related: F1
  Phase-1-source: phase1/templates.md:F5
  Verdict: PARTIAL
  Counter-recommendation: Genericize only the Claude-specific phrasing around planning; do not remove the shared skill names from the always-loaded template.

F3: Moving the Dolt example out of shared instructions would create a cross-tool database-safety blind spot
  File: src/user/.agents/INSTRUCTIONS.md.template:24
  Category: template
  Severity: High
  Tier: 2
  Issue: The portability concern in Phase 1 is valid, but relocating the Dolt-specific warning into beads-only rules assumes those rules are present wherever the hazard exists. They are not present for Codex or Gemini today. The current shared line is the only always-loaded place those tools are warned about worktree-relative DB corruption, and the concrete "Dolt or SQLite" examples make the abstract rule legible.
  Recommendation: Keep database safety in shared instructions and rewrite it as a generic constraint with concrete examples: "Never copy live databases (for example Dolt or SQLite with WAL)..." Add beads-specific reinforcement later as an additive rule, not a substitute.
  Vision-advancement-tier: A
  Vision-advancement: This protects commitment 5 by keeping a corruption-prevention constraint in the one layer that all tools currently load, which is exactly where overnight autonomous runs need it.
  Promotion-eligible: yes
  Related: F1
  Phase-1-source: phase1/templates.md:F13
  Verdict: PARTIAL
  Counter-recommendation: Improve the wording for portability, but do not move the only explicit DB-safety warning out of the shared always-loaded surface until rule parity exists across tools.

F4: `beads.md` parent-chain invariants must remain in the rule even if the shell loops move to helper scripts
  File: src/plugins/beads/.claude/rules/beads.md:20-46
  Category: rule
  Severity: High
  Tier: 2
  Issue: Phase 1 correctly identified the inline shell as script-worthy, but it went too far by proposing that I1 and I2 leave the always-loaded rule entirely. Claim-walk and close-walk are not optional methodology; they are tracker integrity invariants. If an agent sees the beads rule but not a separate reference or skill, it still needs the explicit requirement that status must walk up the parent chain on start and close.
  Recommendation: Keep I1 and I2 in `beads.md` as normative rule text. Once helper scripts exist, replace the code blocks with named script invocations, but leave the invariants themselves in the always-loaded rule.
  Vision-advancement-tier: A
  Vision-advancement: This advances commitment 5 because truthful parent/child state is the persistence mechanism that lets work survive handoff and resume correctly after compaction or overnight pauses.
  Promotion-eligible: yes
  Related: F5
  Phase-1-source: phase1/rules.md:F3
  Verdict: PARTIAL
  Counter-recommendation: Trim reference clutter if desired, but preserve parent-chain invariants as first-class always-loaded constraints.

F5: `beads-labels.md` is carrying behavioral semantics, not just a glossary
  File: src/plugins/beads/.claude/rules/beads-labels.md:5-35
  Category: rule
  Severity: High
  Tier: 2
  Issue: Phase 1 underestimates how much behavior depends on these label meanings. `implementation-readied-session-<sid>` drives same-session gating, `human` defines escalation visibility without affecting readiness, `for-bead-<bead-id>` defines bead↔molecule lookup, and `ralf:*` labels steer dispatch. If this file is collapsed to only the stamp command plus a probe warning, agents lose the always-loaded semantics needed to interpret other rules and workflows correctly.
  Recommendation: Keep a compact semantic table for the behavior-driving labels in the rule. Move only the repetitive command examples and inline jq probe to a helper or reference if you want the file shorter.
  Vision-advancement-tier: A
  Vision-advancement: This supports commitment 5 because label semantics are part of the persisted control plane that lets later agents interpret molecule state and escalation state correctly.
  Promotion-eligible: yes
  Related: F4
  Phase-1-source: phase1/rules.md:F4
  Verdict: PARTIAL
  Counter-recommendation: Compress the operational examples, but retain the label-meaning surface in always-loaded rule text.

F6: The completion gate still needs an explicit handoff bridge into delivery
  File: src/user/.claude/rules/completion-gate.md:19-22; src/user/.claude/rules/delivery.md:5-9,31-33
  Category: rule
  Severity: High
  Tier: 2
  Issue: Phase 1 is right that completion-gate and delivery overlap, but removing the `HARD STOP` bridge entirely would recreate the classic "ready when you are" gap between verification and PR creation. The bridge is load-bearing precisely because it fires at the end of step 5: finish the gate, continue immediately, pause only at merge. Since both files are always loaded, a small amount of deliberate redundancy is safer than a clean split that leaves the transition implicit.
  Recommendation: Keep a short bridge in `completion-gate.md`: after step 5 passes, execute `delivery.md` immediately and do not pause before PR creation; pause only at merge. The detailed skill list can be trimmed if desired, but the transition rule should stay.
  Vision-advancement-tier: A
  Vision-advancement: This directly supports commitment 4 by preventing false completion claims after verification but before the required delivery workflow has actually run.
  Promotion-eligible: yes
  Related: F1
  Phase-1-source: phase1/rules.md:F7
  Verdict: PARTIAL
  Counter-recommendation: De-duplicate the detailed mechanics, not the explicit no-pause transition from completion gate to delivery.

## Out of scope

OOS1: Beads session-completion block still mixes project-level delivery rules with beads-only transport
  File: AGENTS.md:141-165
  Outside-scope: Project AGENTS.md beads integration block; relevant to delivery constraints, but outside this reviewer's main files (`rules` and `INSTRUCTIONS.md.template`)
  Observation: `bd dolt push` remains embedded in a mandatory session-completion workflow visible to every agent reading the project AGENTS.md, which is the same transport-specific hazard Phase 1 flagged.
  Suggested follow-up: Phase 3 decisions or the template/AGENTS reviewer should decide whether this block becomes conditional, beads-scoped, or otherwise guarded.
