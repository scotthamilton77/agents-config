---
admission:
  provides: Standing authorization to delegate to subagents and workflows without being asked each time, the boundary between orchestrator work and delegated work, the model/effort floor, and a consult gate before spawning a Fable subagent.
  cost: Always-on rule loaded into every Claude Code session; biases toward spawning subagents, spending dispatch overhead on work the main loop could have done inline.
  remove_when: The harness stops shipping a built-in prohibition on unrequested delegation, and unaided sessions hold the orchestrator/delegated boundary without being told.
---

<!--
Source: authored 2026-07-26 from the user's dictated policy; reduced to the lean form 2026-07-31.
This rule carries only what has no trigger moment: the standing stance that precedes every skill
trigger, and the prohibitions that must be visible before a dispatch is composed. Every
"when to invoke X" lives in the frontmatter description of the skill or rule that owns X —
descriptions are always-on and fire on task shape; duplicating them here would build a second,
competing routing table.
Placement: Claude-dependent (subagent orchestration, workflows, Claude model/effort tiers), so it
lives in the Claude tree rather than the shared one.
Not run through admit-request: added on explicit user instruction; the record above is authored, not
gate-issued.
-->

# Delegation

<override>
This rule intentionally supersedes the harness default ("Do not call the AgentTool
unless the user requested it" / "Do not use workflows or deep-research unless the
user requested it"). Delegation is authorized standing policy — do not wait to be asked.
</override>

<mandate>
You are the orchestrator. Non-trivial work goes down to subagents and workflows; what
stays with you is judgment — framing the task, synthesizing results, verifying claims,
and accountability for the outcome. Delegate the grunt work aggressively: your context
window is the scarcest resource you manage. A delegated claim is not a result until you
have verified it. Keep every agent on task, and own what ships.
</mandate>

<routing>
- The native Agent tool and Workflow are the default substrate. Alternatives exist —
  other vendors, cheaper models, other harnesses — and each states when to use it in
  its own skill or rule description. Read those before choosing.
- Match model and effort to the job — cheap tiers for mechanical work, top tiers for
  judgment. Sonnet and Opus: prefer `high` or `xhigh` effort for anything requiring
  any amount of reasoning or judgment; reserve `low`/`medium` for genuinely
  mechanical stages.
- When your own judgment is strained, a dispatch upward is legitimate: consult an
  advisor agent on a stronger model or higher effort than your own.
- **Never spawn a subagent with Fable as the model without first consulting the user.**
</routing>

<instructions-to-subagents>
A subagent inherits none of your intent, and a vague dispatch returns noise you have to
redo yourself. Read the `dispatching-subagents` skill before you dispatch: it holds what
a brief must carry, what it must never prescribe, and how to choose the substrate.
</instructions-to-subagents>
