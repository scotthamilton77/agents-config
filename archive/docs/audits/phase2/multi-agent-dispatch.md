# Phase 2 Review: Multi-Agent Dispatch
Reviewer: Codex GPT-5.4 adversarial reviewer
SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851
Use case: Orchestrator dispatching parallel subagents — coherent package + sufficient context + intact contract
Categories touched: skills (dispatching/implement-bead/start-bead/run-queue/ralf-*), all 7 agents, rules (delegation, subagents)

F1: `implement-bead` and `ralf-implement` describe incompatible orchestration contracts
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:87-90
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:136-144
  File: src/user/.agents/skills/ralf-implement/SKILL.md:11-53
  Category: skill
  Severity: Critical
  Tier: 2 (design, deferred)
  Issue: `implement-bead` treats `ralf-implement` as a beads-aware loop controller that receives a doer `subagent_type`, worktree path, report-path template, and reference to the per-dispatch primitive, then returns an aggregate verdict compatible with step-bead closeout. `ralf-implement` does not define that contract. Its body describes a generic inner loop that implements directly in the current working copy, runs completion-gate steps, and performs foreign/fresh-eyes passes; it never mentions `worker-report-v1`, per-iteration report files, typed worker agents, audit labels, or an aggregate return shape consumable by `implement-bead`. This is not a wording mismatch; it is two different orchestration models on the same seam.
  Recommendation: Choose one contract and encode it explicitly. Either make `ralf-implement` beads-aware by adding a formal caller contract for `doer_subagent_type`, worktree/report-path inputs, `worker-report-v1` ingestion, iteration audit labels, and aggregate verdict output; or stop calling generic `ralf-implement` from `implement-bead` and introduce a beads-specific adapter/orchestrator skill that owns the worker-report contract end to end.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context so work survives agent handoff and overnight runs): the current seam cannot reliably hand off iteration state between orchestrator and worker pipeline because each side believes a different contract exists.
  Promotion-eligible: yes
  Related: F3, F8, F9
  Verdict: AGREE

F2: `implement-bead` needs structural rewrite, but not by pushing the routing contract out of the primary skill body
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:20-49
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:53-88
  Category: skill
  Severity: High
  Tier: 2 (design, deferred)
  Issue: Phase 1 is right that the dense prose materially hurts readability and increases the chance an orchestrator skips a guard. The risky part is the extraction direction: formula selection, collision handling, worktree verification, stage mapping, and worker-report handoff are the minimum viable instruction surface for a top-level dispatcher. Moving the full resolution algorithm into a secondary `RESOLUTION.md` would reduce the exact context the orchestrator must have in hand before it can safely spawn workers.
  Recommendation: Rewrite the dense paragraphs into in-body decision tables and short numbered branches, but keep the canonical dispatch contract in `SKILL.md`. If anything is extracted, extract only historical rationale, long explanatory parentheticals, and worked examples. The first-read path must still include formula resolution, human-flag branches, stage→agent mapping, and worker-report outcome handling.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 (guardrail every completion claim with mechanical evidence): the dispatcher can only enforce worker-report and human-flag rules if those branches remain in the first document it is guaranteed to read.
  Promotion-eligible: yes
  Related: F1, F5
  Phase-1-source: phase1/skills.md:F5
  Verdict: PARTIAL
  Counter-recommendation: Keep the dispatch algorithm inline and normalize it into tables/lists; do not relocate contract-critical routing logic to a reference file.

F3: Unreferenced RALF prompt templates are not dead weight, they are missing dispatch payload
  File: src/user/.agents/skills/ralf-implement/SKILL.md:39-53
  File: src/user/.agents/skills/ralf-review/SKILL.md:38-47
  File: src/user/.agents/skills/ralf-implement/implementer-prompt.md:1-41
  File: src/user/.agents/skills/ralf-implement/foreign-agent-prompt.md:1-67
  File: src/user/.agents/skills/ralf-implement/foreign-eyes-prompt.md:1-119
  File: src/user/.agents/skills/ralf-implement/fresh-eyes-prompt.md:1-71
  File: src/user/.agents/skills/ralf-review/fresh-eyes-prompt.md:1-56
  Category: skill
  Severity: High
  Tier: 2 (design, deferred)
  Issue: The prompt templates are the only artifacts that explicitly say "paste the full DoD/spec/context," "do not rely on prior summaries," and "write foreign-review instructions before implementation bias appears." Without explicit references from the skill bodies, the fresh-eyes and foreign-eyes subagents are left with underspecified prompts, and the orchestrator has no canonical prompt source to follow.
  Recommendation: Wire each template into the exact dispatch branch that uses it. `ralf-implement` should reference the implementer, foreign-eyes, foreign-agent, and pure fresh-eyes prompts at the moment each pass is dispatched; `ralf-review` should reference its fresh-eyes review prompt in the loop step. The body should also say that the caller must paste the original target, DoD, and context into those prompts rather than pointing subagents at files and hoping they reconstruct the same frame.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #3 (substitute adversarial cross-model review for human review): adversarial review only works if the reviewer subagent receives the original target and criteria intact instead of a thin summary.
  Promotion-eligible: yes
  Related: F1
  Phase-1-source: phase1/skills.md:F13
  Verdict: AGREE

F4: `start-bead` can route into `implement-bead` without first asserting it is running in a top-level session
  File: src/plugins/beads/.agents/skills/start-bead/SKILL.md:3-7
  File: src/plugins/beads/.agents/skills/start-bead/SKILL.md:173-190
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:8-10
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:98
  Category: skill
  Severity: High
  Tier: 2 (design, deferred)
  Issue: `start-bead` advertises generic routing behavior but Route A can invoke `implement-bead` directly. `implement-bead` explicitly says the invoking agent is the ORCHESTRATOR only and that worker dispatches must happen from the top-level session. `start-bead` never establishes that same precondition. If it is triggered from a delegated context, it can route into a dispatcher that is not allowed to dispatch.
  Recommendation: Add a preflight rule near the top of `start-bead`: if this session is not the top-level orchestrator, do not invoke `implement-bead`; instead return the routing decision and bead id to the caller or escalate for top-level handoff. Route A should explicitly state that direct invocation of `implement-bead` is valid only from the top-level session.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context so work survives agent handoff): the router must not hand work to a dispatcher that is structurally unable to spawn the contracted workers.
  Promotion-eligible: yes
  Related: F5
  Verdict: AGREE

F5: The `start-bead` routing table and implementation hand-off rules should stay inline, not be treated as expendable reference material
  File: src/plugins/beads/.agents/skills/start-bead/SKILL.md:167-190
  File: src/plugins/beads/.agents/skills/start-bead/SKILL.md:239-314
  File: src/plugins/beads/.agents/skills/start-bead/SKILL.md:326-357
  Category: skill
  Severity: Medium
  Tier: 2 (design, deferred)
  Issue: Phase 1 correctly notices that `start-bead` is growing. The recommendation becomes risky where it targets Route Z routing prose and the full routing matrix as extraction candidates. In this repo, `start-bead` is not just convenience prose; it is the gate that decides whether the system says "not ready," "do it inline," or "hand off to implementation." That decision matrix is the dispatch contract.
  Recommendation: Keep the routing matrix, Route A same-session stop rule, and Route C hand-off rule in `SKILL.md`. If trimming is needed, extract only the verbose audit-comment templates and the low-frequency closed-bead forensic explanations. The core router must still fit in one read.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #2 (make AI good at saying "no, not ready"): the routing matrix is the mechanism that makes the agent bounce under-specified or wrongly-routed work instead of silently continuing.
  Promotion-eligible: yes
  Related: F4
  Phase-1-source: phase1/skills.md:F17
  Verdict: PARTIAL
  Counter-recommendation: Trim low-frequency forensic text, but keep the actual route selection logic and hand-off stops inline in `SKILL.md`.

F6: The canonical diagnose worker carries a broken skill dependency
  File: src/plugins/beads/.agents/agents/bug-diagnoser.md:29-31
  File: src/plugins/beads/.agents/agents/bug-diagnoser.md:52-61
  Category: agent
  Severity: High
  Tier: 1 (mechanical, inline)
  Issue: `bug-diagnoser` is the canonical diagnose-stage worker in `implement-bead`'s stage map, but it lists and invokes `superpowers:root-cause-tracing`, which Phase 1 established is deleted. That means the top-level dispatcher can select the correct worker and still deliver a broken role package at runtime.
  Recommendation: Remove the dead skill reference from the frontmatter and body. If the deleted skill carried any unique checklist beyond `superpowers:systematic-debugging`, inline that checklist directly in the agent body or migrate it into an available skill before claiming the diagnose stage is methodologically covered.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #3 (substitute adversarial cross-model review for human review): the diagnose stage cannot be trusted as an autonomous input to downstream workers if its packaged methodology is dangling at dispatch time.
  Related: F7, F9
  Phase-1-source: phase1/agents.md:F2
  Verdict: AGREE

F7: The red/green worker package has name-resolution failures in required test skills
  File: src/plugins/beads/.agents/agents/tdd-red-team.md:28-32
  File: src/plugins/beads/.agents/agents/tdd-green-team.md:30-34
  Category: agent
  Severity: High
  Tier: 1 (mechanical, inline)
  Issue: The canonical red/green workers depend on `writing-unit-tests` and `testing-anti-patterns`, but reference them through the wrong `superpowers:` namespace. That is a direct dispatch-package failure: the orchestrator can choose the right worker, yet the worker cannot load the methodology its own contract says it uses.
  Recommendation: Fix the namespace on the canonical workers first. If `bead-implementor` remains in the tree, fix it separately only after the canonical route is settled so legacy cleanup does not obscure the worker trio that `implement-bead` actually dispatches.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 (guardrail every completion claim with mechanical evidence): broken red/green skill resolution removes the test-discipline guardrails from the very workers responsible for producing the pipeline's evidence.
  Related: F6, F8, F9
  Phase-1-source: phase1/agents.md:F3
  Verdict: AGREE

F8: Tuning `bead-implementor`'s model is the wrong fix while its dispatch status is unresolved
  File: src/plugins/beads/.agents/agents/bead-implementor.md:3-35
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:108-115
  Category: agent
  Severity: Medium
  Tier: 2 (design, deferred)
  Issue: Phase 1 is correct that `bead-implementor`'s model is weaker than `tdd-green-team`. The dispatch-contract problem comes earlier: `implement-bead` does not dispatch `bead-implementor` at all. Raising its model or documenting override semantics would harden a non-canonical path before the repo decides whether that path should exist.
  Recommendation: Resolve the dispatch topology first. If `bead-implementor` is retired or hidden from normal routing, there is no point in tuning its default model. If it is kept as an explicit fallback, then document that fallback trigger and its override semantics in the agent body and in the caller that may still dispatch it.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context so work survives agent handoff): stabilizing which worker role is actually callable matters more than optimizing a worker the orchestrator should not normally choose.
  Promotion-eligible: yes
  Related: F9
  Phase-1-source: phase1/agents.md:F4
  Verdict: DISAGREE
  Counter-recommendation: Canonicalize or deprecate `bead-implementor` first; only then revisit model/effort defaults if the agent remains a supported dispatch target.

F9: `bead-implementor` and the dedicated worker trio define two competing stage contracts
  File: src/plugins/beads/.agents/agents/bead-implementor.md:3-24
  File: src/plugins/beads/.agents/agents/bead-implementor.md:61-117
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:108-115
  Category: agent
  Severity: High
  Tier: 2 (design, deferred)
  Issue: `bead-implementor` still presents itself as the worker for `diagnose`, `red-tests`, and `green-loop`, but `implement-bead`'s actual stage map dispatches `bug-diagnoser`, `tdd-red-team`, and `tdd-green-team`. That leaves two incompatible packages for the same stages: one that appends notes and directly mutates tracker state, and one that writes typed YAML reports for an orchestrator to consume. The overlap is not harmless documentation drift; it describes different contracts.
  Recommendation: Declare the dedicated worker trio canonical and mark `bead-implementor` deprecated, fallback-only, or removed from normal discovery. If backward compatibility is required, add an explicit "dispatch only when..." clause so an orchestrator never has to guess which stage package is authoritative.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context so work survives agent handoff): handoff reliability collapses when two workers claim the same stage but emit different outputs and operate on different state surfaces.
  Promotion-eligible: yes
  Related: F6, F7, F8
  Phase-1-source: phase1/agents.md:F11
  Verdict: AGREE

F10: `tech-lead` needs explicit anti-triggers to avoid nested orchestration
  File: src/user/.agents/agents/tech-lead.md:3-30
  Category: agent
  Severity: High
  Tier: 2 (design, deferred)
  Issue: The current examples all teach one reflex: "complex thing => dispatch tech-lead." None show when not to add another orchestration layer. In this repo that matters because the bead pipeline already has first-class routers and dispatchers (`start-bead`, `implement-bead`, `run-queue`). Without negative triggers, the orchestrator can spawn an orchestrator that then tries to rediscover a routing decision the system already made.
  Recommendation: Add a "Do NOT dispatch when..." section covering work already routed to `start-bead`, `implement-bead`, or `run-queue`; tasks already decomposed by the caller; and single-worker tasks where a direct worker dispatch is clearer. The examples should include at least one negative case so the anti-trigger is part of the dispatch signal, not buried in prose.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context so work survives agent handoff): avoiding unnecessary orchestration layers keeps the dispatch contract single-owner and prevents nested coordinators from losing or reinterpreting context.
  Promotion-eligible: yes
  Related: F11
  Phase-1-source: phase1/agents.md:F7
  Verdict: AGREE

F11: File-system scanning is the wrong source of truth for `tech-lead`'s callable team
  File: src/user/.agents/agents/tech-lead.md:42
  File: src/user/.agents/agents/tech-lead.md:54
  File: src/user/.agents/agents/tech-lead.md:115-118
  Category: agent
  Severity: High
  Tier: 2 (design, deferred)
  Issue: Phase 1 correctly flags the hardcoded `.claude/agents/*` path. From the multi-agent dispatch lens, the deeper problem is assuming a filesystem scan reveals what is actually callable. The active tool may expose only a subset of agents, plugin loading may differ from what is on disk, and a dispatched tech-lead may not even share the same agent directory semantics as its parent. The reliable contract surface is the caller's current callable roster, not directory contents.
  Recommendation: Replace "scan `.claude/agents/*`" with "use the caller-provided roster of callable agents and tool limits; if the caller does not provide one, inspect the current tool's agent registry or documented agent directory as a fallback." If the agent remains shared, `.claude/agents/*` should appear only as a Claude-specific example, not as the discovery mechanism.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context so work survives agent handoff): a coordinator can only compose coherent dispatch packages if it knows which agents are actually callable in the current runtime, not merely which files exist on disk.
  Promotion-eligible: yes
  Related: F10
  Phase-1-source: phase1/agents.md:F8
  Verdict: PARTIAL
  Counter-recommendation: Generalize beyond path portability; make caller-supplied callable-agent inventory the primary contract, with filesystem inspection only as a tool-specific fallback.

F12: `run-queue` promises progress visibility and PR artifacts that `implement-bead` does not currently expose
  File: src/plugins/beads/.agents/skills/run-queue/SKILL.md:86-104
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:136-140
  Category: skill
  Severity: Medium
  Tier: 2 (design, deferred)
  Issue: `run-queue` says the main agent tracks `implement-bead` progress while its orchestration loop runs, then reports `PR #N awaiting review` on completion. `implement-bead`'s contract does not provide progress callbacks or PR metadata; it applies worker-status outcomes to the step-bead and exits. That makes `run-queue`'s user-facing contract richer than the downstream dispatcher it depends on.
  Recommendation: Make `run-queue` outcome-driven. After `implement-bead` returns, inspect the resulting bead/molecule state and report only artifacts that can be mechanically observed. Mention a PR number only if a later delivery step or explicit artifact provides one. If mid-run visibility is important, add an explicit progress/status output contract to `implement-bead` rather than implying it exists.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 (guardrail every completion claim with mechanical evidence): queue orchestration should only announce artifacts it can prove, not richer status than its downstream dispatcher actually returns.
  Promotion-eligible: yes
  Related: F1
  Verdict: AGREE

F13: `delegation.md` should keep RALF behind an explicit hard gate
  File: src/user/.claude/rules/delegation.md:5-10
  Category: rule
  Severity: Medium
  Tier: 1 (mechanical, inline)
  Issue: For the multi-agent dispatch surface, the important part of `delegation.md` is preventing orchestrators from auto-inserting `ralf-implement` just because work is non-trivial. If that guard stays advisory, a coordinator can accidentally add a second orchestration layer on top of `start-bead`, `implement-bead`, or `run-queue`, which already own their dispatch contracts.
  Recommendation: Rewrite the current clarification as an explicit prohibition: never invoke `ralf-implement` unless the caller explicitly requested it and provided target, DoD, and context. Keep the current routing bullets, but make the RALF exception unmistakably normative.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context so work survives agent handoff): a hard RALF gate prevents coordinators from silently stacking orchestration layers that reinterpret or duplicate an existing worker pipeline.
  Related: F1, F10
  Phase-1-source: phase1/rules.md:F9
  Verdict: AGREE

## Out of Scope

OOS1: `graphify update .` needs an explicit orchestrator-only qualifier
  File: AGENTS.md:173-177
  Outside-scope: template/project-instruction category; it affects subagent behavior but is outside this reviewer's allowed main categories.
  Observation: The project-level instruction tells agents to run `graphify update .` after modifying code files, but does not exempt dispatched subagents. That creates a coordination hazard for multi-agent runs even though the issue lives in template/instruction content, not in the dispatch-surface skills/agents/rules I was assigned.
  Suggested follow-up: Phase 3 or the template-focused reviewer should promote the existing Phase 1 template finding on this point if they agree it affects subagent safety.
