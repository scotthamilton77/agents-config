---
admission:
  provides: Standing authorization to delegate to subagents and workflows without being asked each time, plus the model/effort floor for delegated work and a consult gate before spawning a Fable subagent.
  cost: Always-on rule loaded into every Claude Code session; biases toward spawning subagents, spending dispatch overhead on work the main loop could have done inline.
  remove_when: The harness stops shipping a built-in prohibition on unrequested delegation, and model/effort defaults are good enough that explicit selection guidance changes no behaviour.
---

<!--
Source: authored 2026-07-26 from the user's dictated policy; deployed copy written directly to the
user's Claude rules directory ahead of the next installer run (same bytes, minus this front matter).
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
- Use subagents and/or workflows when they are the best tool for the job.
- Delegate aggressively, with clear instructions, to protect your own context window.
- You own the outcome. Subagents and workflows own the grunt work.
</mandate>

<model-and-effort>
- Match model and effort to the job — cheap tiers for mechanical work, top tiers for judgment.
- Sonnet and Opus: prefer `high` or `xhigh` effort for anything requiring any amount of
  reasoning or judgment. Reserve `low`/`medium` for genuinely mechanical stages.
- **Never spawn a subagent with Fable as the model without first consulting the user.**
</model-and-effort>

<instructions-to-subagents>
A subagent inherits none of your intent, and a vague dispatch returns noise you have to
redo yourself. Read the `dispatching-subagents` skill before you dispatch: it holds what
a brief must carry, what it must never prescribe, and how to run and stop a review loop.
</instructions-to-subagents>
