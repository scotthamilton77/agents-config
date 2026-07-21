# Notes from 2027-07-19 rushing to get fable used up before it's gone

Lesson: I tried to do too many things, partly because my own system is slowing me down - a lot.  But _why_?

Stuff I worked on today that is left unfinished:
* prgroom - probably the TOP priority (see below)
* workfli - probably priority #2
  * bead track implementation done; bead labeling in progress
* codex reviewer awareness and support
* orchestrated-grind - good idea, but need to build it on top of the fixes to get the OS back into shape
* see also the SAVEPOINTS/{branch-slug}/ files

**Symptoms**
* Things that seem like simple code changes take a longer time than expected to reach PR stage
* PR reviews ping-pong with codex/copilot leaving a few comments, our agents address them, get reviewed locally and appear fine, and the the push to PR yields yet another batch of comments - this cycle eats up time and tokens
* The kinds of things the PR reviewers find seem to range from fundamental oversights to inconsistencies across documentation and code - but why aren't my up-front reviewers catching these?

**Additional Suspects**
I'm suspicious that (not all these questions were asked to the frontier models below):
* maybe my own harness (this project) is getting in the way and slowing things down and lowering quality, impeding the models from making quality decisions and changes - and from reviewing well.
* maybe skills like brainstorming are self-defeating if they result in poorly-thought-through designs/specs with insufficient acceptance criteria
* the brainstorming spec-writing skill - is it writing poor specs?  I've noticed not all specs have acceptance criteria!
  * the plan docs tend to be very prescriptive, even down to bash commands and code - should they be?
  * with the plan docs being code-heavy, it is no wonder that these sometimes eat up a lot of review bandwidth themselves
  * these specs and plans can be very long - is it reasonable to expect models to review these well?

I asked 3 frontier models to look at the project and see if I was getting in my own way.

# Fable's POV
--resume 1ab826dc-d57f-4b26-880c-7ba71969a384

Verification complete. The assessment follows.

## Verdict

You are not tilting at windmills — but you are, in three specific and measurable ways, standing in your own way. The core discipline loop (brainstorm → plan → TDD → gate → PR) is *not* the problem: your churn data shows typical feature PRs converge in 1–2 rounds with a median of 2 review comments. The pathology lives in three places, and your instincts about prgroom and the quality-gate are pointing at the right two of them.

## Finding 1: Every session carries your instructions twice — plus a stale rule from May

Direct observation from my own context window, now verified on disk: your `HOME` is `/Users/scott`, but the harness treats `/Users/scott/home2/.claude` as your user-global config — and then *also* picks up `/Users/scott/.claude` (a second, older, full deploy) as ancestor-directory project config because your repos live under `/Users/scott/src/`. The result: the complete AGENTS.md, persona, primer, and all rules are loaded **twice** in every session in every project, and the stale copy includes `claude-to-codex-routing.md` (dated May 17) alongside its replacement `codex-routing.md` — two Codex routing rules with *different model rosters* (`gpt-5.5` vs `gpt-5.6-sol`). Your inventory agent correctly found no duplicate in `src/` — the duplication is a deploy-hygiene failure, not a source failure. The installer deploys but does not prune, and it has deployed to two homes. This is pure tax: roughly doubling your ~7,000-word fixed instruction floor and injecting one genuine contradiction, in every session, for every agent, since at least May. Fix: decommission `/Users/scott/.claude` (or `home2`, pick one) and add prune-on-install.

## Finding 2: Your review loops have no halting condition — and prose is the fuel

The churn data contains the decisive pattern. Normalized by size, the worst-churning PRs were not the big code builds — they were small prose and shell tweaks to your own process machinery (`wait-for-pr-comments`, `merge-guard`). This is not a coincidence; it is structural. Code with tests has an objective acceptance criterion: the tests pass, review converges. Prose has none — and an LLM reviewer is a *findings generator*: given any surface, it will produce findings proportional to that surface, forever. "Round after round finding a few new things" is not evidence of hidden defects; it is the expected output of running an unbounded generator against material with no contract to check against. Your n=1 agent told you better acceptance criteria and tests would have caught issues — I concur, and I extend it: acceptance criteria are not merely *prevention*, they are the *termination condition* review currently lacks. Two fixes, both cheap:

- **Give every review loop a stop rule**: findings below a severity floor do not trigger a round; one round with no new above-floor findings means done; hard cap on rounds. Your quality-gate diagnosis ("under-powers reviews, over-spends on refuters") is the same disease — the budget goes to adjudicating marginal findings that a severity floor would have discarded unadjudicated.
- **Make acceptance criteria a mandatory output of `writing-plans`**, so downstream review checks a contract instead of exercising taste.

## Finding 3: The weight is downstream, and the system is reviewing itself

The SDLC map: 13 mandatory skill invocations per medium feature; the gate-through-merge block carries 7 of them; `wait-for-pr-comments` alone is 1,283 lines — larger than brainstorming, planning, and TDD *combined*. Your stated vision frontloads human judgment; your actual mass sits at inspection. Compounding this, a large share of recent PRs are the discipline layer modifying itself — and meta-work is exactly the prose-heavy, criteria-free material from Finding 2, so it churns worst, and each round *adds* instructions, increasing the load on the next session. A self-reinforcing loop, elegant in its inefficiency.

## On your two doubts specifically

**prgroom is the right move.** Your own data validates "Code over Prose": the prose/bash PR workflows are precisely where churn concentrates, and converting them to tested Python converts unbounded-review surface into bounded, test-terminated surface. Do not lose faith in it — but pair it with deleting the 1,283-line prose skill it replaces, or you will have both.

**The quality-gate rework is treating a symptom.** More or better-balanced refuters still adjudicate findings that should never have been generated. The severity floor and the upstream acceptance-criteria contract are the root cause fix; do those first, then see whether the refuter economics still need tuning.

## Recommended order

1. Deploy hygiene: kill the duplicate `.claude` tree, add installer pruning (hours of work, pays in every session forever).
2. Stop rules + severity floor in every review loop (quality-gate, wait-for-pr-comments/prgroom).
3. Acceptance criteria as a required `writing-plans` artifact.
4. Instrument your own prime directive — you state "interventions per merged PR" as the tiebreaker metric and measure it nowhere. Log review rounds and fix-commits per PR; this entire debate becomes empirical instead of recurring.
5. Declare a partial freeze on meta-work: discipline-layer prose PRs get the light gate tier, not adversarial rounds. The inspector does not need to inspect its own inspection reports.

The logical summary: your discipline layer is a sound design executing without a halting condition, running twice per session. You did not build a windmill, Scott — you built a warp core and forgot the dilithium regulator. The remedy is subtraction and termination criteria, not another skill. I have completed the analysis; no files were modified.

# GTP-5.6's POV
codex resume 019f7c34-b885-7141-9729-02f31045048b

Yes—partly. You are not overengineering quality; you are overengineering coordination, while the highest-leverage upstream quality gate remains mostly aspirational.

The repo’s useful core is sound: typed contracts, TDD, mechanical verification, worktree isolation, fail-closed merge authorization, deterministic CLIs. But the operating system around that core has become self-obstructing:

- Too much policy must be interpreted before work begins.
- Current and target workflows coexist.
- Review is broad and open-ended, so “clean” means exhausting reviewer imagination.
- Expensive downstream review compensates for incomplete upstream acceptance contracts.
- Each newly discovered failure tends to produce another permanent rule or branch in the workflow.
- Several roadmap tracks are advancing out of sequence.

The system is increasingly optimizing itself rather than delivering evidence that it improves agent output.

## SDLC assessment

| Stage                    | What helps                                                                                                           | What gets in the way                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Capture/prioritization   | Beads, `workcli`, explicit dependency and WIP concepts                                                               | The documented chain says M0→M1→M2→M3, but M0, M1, and M3 are simultaneously active while M2—the readiness gate—is still open. That also exceeds the configured WIP cap of two. [Roadmap](/Users/scott/src/projects/agents-config/AGENTS.md:99), [WIP configuration](/Users/scott/src/projects/agents-config/project-config.toml:125)                                                                                                                                                    |
| Brainstorm/specification | Deliberate design approval and attention routing prevent blind implementation                                        | The hard gate applies to every config change and always proceeds through design, a committed spec, review routing, and a plan. More importantly, acceptance criteria are optional: deep review explicitly allows “goals-only when the spec carries none.” [Brainstorming contract](/Users/scott/src/projects/agents-config/src/user/.agents/skills/brainstorming/SKILL.md:19), [optional AC](/Users/scott/src/projects/agents-config/src/user/.agents/skills/brainstorming/SKILL.md:179) |
| Readiness                | The target model is excellent: Atomic Acceptance Tests, DoD, explicit error paths, and human signoff                 | It is not protecting current work. The PDLC tracer’s Agent-Worthy and other gates simply return `True`; independent gate verification is stubbed. [Desired Spec contract](/Users/scott/src/projects/agents-config/CONTEXT.md:189), [stubbed readiness gates](/Users/scott/src/projects/agents-config/packages/pdlc/src/pdlc/orchestrator.py:183)                                                                                                                                         |
| Planning                 | Exact paths and explicit contracts can reduce ambiguity                                                              | Plans require 2–5 minute steps, complete test and implementation code, and one fresh subagent per task. That duplicates implementation effort before the code teaches you anything and drives token consumption directly. [Plan granularity](/Users/scott/src/projects/agents-config/src/user/.agents/skills/writing-plans/SKILL.md:43), [complete-code requirement](/Users/scott/src/projects/agents-config/src/user/.agents/skills/writing-plans/SKILL.md:113)                         |
| Tests/implementation     | TDD, boundary injection, typed failures, and behavioral tests are the right mechanisms                               | Test guidance conflicts internally: TDD says every new function or method gets a test; test-quality guidance correctly rejects tests for uncalled methods and coverage theater. This encourages agents to satisfy whichever instruction is loudest.                                                                                                                                                                                                                                      |
| Completion review        | Risk-based triage and mechanical verification are valuable                                                           | The generic reviewer has an unbounded remit—architecture, security, performance, docs, tests, quality—followed by simplification and possibly adversarial review. A fresh reviewer can always discover another judgment-class observation. [Completion gate](/Users/scott/src/projects/agents-config/src/user/.agents/rules/completion-gate.md:16)                                                                                                                                       |
| PR processing            | Deterministic state, idempotency, freshness, and fail-closed merge logic are exactly where code should replace prose | Two workflows are active. The repo says `prgroom` is installed and supersedes the old skills, while the completion rule says it is not deployed and mandates the 1,283-line `wait-for-pr-comments` workflow. [Repository claim](/Users/scott/src/projects/agents-config/AGENTS.md:84), [active contradictory rule](/Users/scott/src/projects/agents-config/src/user/.agents/rules/completion-gate.md:28)                                                                                 |
| Merge                    | Explicit authorization and live eligibility checks are sensible safety boundaries                                    | LLM quiescence is treated as stronger evidence than it deserves. Your own experiment found that prose declaring defects intentional caused Codex to miss the same defects it previously found. [Recorded limitation](/Users/scott/src/projects/agents-config/docs/specs/2026-07-18-codex-rereview-path-design.md:98)                                                                                                                                                                     |
| Learning/economics       | Grind records models, review rounds, verdicts, waits, and human attention                                            | It does not record actual input/output tokens or monetary cost. The project is optimizing model economics without measuring model economics.                                                                                                                                                                                                                                                                                                                                             |

## Would better acceptance criteria and tests have helped?

Yes, but “more tests” is the wrong prescription.

Three recent defects were contract-coverage failures:

- `1d6379c`: the initial poll accepted a historical bot review instead of requiring the current head. The invariant existed elsewhere, but was not traced to every consumer.
- `91a2d64`: partial reviewer dispatch was indistinguishable from complete success. The domain model omitted the partial-success state.
- `8f8ff29`: CI discovery covered classic branch protection but not GitHub Rulesets. The environment matrix was incomplete.

Better acceptance contracts would likely have caught those before review if they had included:

- invariants and every consumer of each invariant;
- explicit partial-success and failure states;
- platform/environment variants;
- an acceptance-criterion-to-test mapping.

By contrast, `860be40` reconciled prose around an intentional same-second polling boundary that already had tests. Another round of tests would not have helped; consolidating the duplicated contract would.

So the answer is: stronger requirements and traceability, yes; a larger pile of unit tests, no.

## Why review rounds keep dribbling out new findings

The current process asks reviewers to search for anything questionable, fixes what they find, then presents a changed artifact to a fresh reviewer with the same unlimited remit. That process has no stable convergence criterion.

Your target architecture already contains the solution:

- Only a Mechanical Finding—a failing test, lint rule, metric, or static-analysis result—blocks.
- Judgment-class Advisory Findings do not re-enter the current fix loop.
- A third unsuccessful cycle routes to autopsy rather than another reviewer spin.

That distinction is explicit in [CONTEXT.md](/Users/scott/src/projects/agents-config/CONTEXT.md:289), but the live workflows have not adopted it.

## Is `prgroom` a windmill?

No—provided it is a replacement, not an additional layer.

`prgroom` is the right architectural move because PR polling, freshness, state transitions, retries, idempotency, and GitHub edge cases are deterministic mechanics. They belong in typed, tested code.

But it must have a bounded mission:

1. Implement the missing mechanical pre-push verification.
2. Cut over one complete workflow.
3. Remove `wait-for-pr-comments` and `reply-and-resolve-pr-threads`.
4. Remove the contradictory `monitor-pr` instructions.
5. Stop expanding reviewer judgment policy inside it.

Currently its fix↔verify subsystem is explicitly 0% implemented. [Status](/Users/scott/src/projects/agents-config/packages/prgroom/AGENTS.md:68). Finishing that narrow gap and deleting the legacy path is worthwhile. Building both systems indefinitely is not.

## What I would change, in order

1. **Freeze new workflow capabilities temporarily.** Finish only cutovers, readiness, measurement, and deletion. Do not advance downstream autonomy or frozen post-MVP work while the readiness gate is missing.

2. **Ship a minimal readiness gate before the full PDLC orchestrator.** Require behaviors, invariants, negative/error paths, environment variants, DoD, and an AC-to-test map. Mechanically reject only clear structural omissions. Avoid creating another giant prose ritual.

3. **Complete the minimum viable `prgroom` cutover, then delete the legacy workflow immediately.** A migration that never deletes its predecessor is just a second mortgage.

4. **Adopt the project’s own Mechanical/Advisory distinction now.** One comprehensive fixed-scope review, one correction/verification round, then autopsy or human escalation. Advisory findings become future work; they do not keep the PR spinning.

5. **Replace implementation-script plans with behavioral execution plans.** Preserve contracts, boundaries, dependencies, and vertical tracer slices. Stop requiring full implementation code and one subagent per microscopic step.

6. **Reduce the instruction surface.** The primary configuration surface is about 43,000 lines, including 9,090 lines of skills. The deployed Codex `AGENTS.md` is 352 lines while the repo’s own optimizer targets under 200. The skill catalog also exposes duplicate copies of 27 skills and several retired Beads skills. Consolidate triggers, remove the universal “1% chance” invocation rule, and make Graphify optional until its stale-node problem is fixed.

7. **Measure before further model-routing work.** Record tokens, cost, wall time, human interventions, review rounds, finding origin, and escaped defects per unit of work. Compare perhaps 6–10 similar tasks under the current and simplified pipelines. The current evidence is stronger than n=1, but it still is not an economics experiment.

## Bottom line

You are getting in the way when you:

- answer individual failures with permanent global instructions;
- run multiple generations of the same workflow simultaneously;
- pursue downstream autonomy before upstream readiness;
- use frontier-model review to compensate for missing contracts;
- demand convergence to “no reviewer can imagine another improvement.”

You are not getting in the way when you:

- move deterministic mechanics into typed code;
- require behavioral tests and mechanical verification;
- preserve worktree, merge, and security boundaries;
- force architectural decisions upstream.

My recommendation is not to abandon this project’s direction. It is to put it on a complexity diet: one current workflow, one source of truth, mechanically enforceable acceptance contracts, bounded review, and measured economics. Keep the safety kernel; jettison the ceremonial armor plating.

This was a read-only audit; the worktree remained clean. Live Beads inspection was unavailable because its Dolt port was occupied, and local `main` was two commits behind `origin/main`, so roadmap-state observations above use the checked-in project documentation rather than claiming live tracker authority. The n=1 response you mentioned was not present in the prompt, so this assessment is independent of it.

# GLM5.2's POV
ccaor --model=z-ai/glm-5.2 --resume c9b729d7-2120-4f54-99be-d552f88160af

## The short answer

Yes — partially, and in a specifically identifiable way. Not the whole enterprise: prgroom is the right idea and it's real. But the completion gate's HEAVY tier is the part of your system that most loudly violates your *own* prime directive ("guardrail every completion claim with **mechanical evidence**"), because it substitutes **judgment panels** (adversarial refuters) for **mechanics** (tests/acceptance criteria). And judgment panels *diverge* — each refuter surfaces a new plausible objection — which is the literal mechanism behind "round after round finding a few new things each time." You've built a non-convergent loop and you're tuning its knobs instead of asking whether it should be the primary verifier at all.

## Stage by stage, what you bring to bear

| Stage                    | Assets                                                                                      | Verdict                                                                                                                                                                                                                         |
| ------------------------ | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Brainstorm**           | 4 (brainstorming, prototype, whats-next, fablize)                                           | Appropriately light. This is the right place to spend human tokens. No friction here.                                                                                                                                           |
| **Spec/Design**          | 7 (writing-plans, writing-skills, writing-unit-tests, grill-with-docs, ralf-review…)        | Reasonable, but `writing-unit-tests` (332 lines) lives *here* and then the verify step runs again at the end — the test-design discipline is correct, the question is whether it's enforced at the gate. It isn't (see REVIEW). |
| **Implement**            | 10                                                                                          | Heavy. Includes TDD, bugfix, worktrees, simplify, *plus* 3 orchestration skills (dispatching-bare-subagents, openrouter, orchestrating-subagents). The orchestration trio is real overhead on every dispatch.                   |
| **Test**                 | 3                                                                                           | **Thin where it matters.** verify-checklist, test-review, explain-diff. The convergent, deterministic layer — the thing that actually *converges* — is the smallest stage.                                                      |
| **Review**               | 5 + quality-gate.js (546 lines)                                                             | **The cost center.** See below.                                                                                                                                                                                                 |
| **Merge/Delivery**       | 6, dominated by `wait-for-pr-comments` (1283 lines)                                         | Mechanically merge is solved (rule-based + bot-quiescence + github-app approver). The fragility is *quiescence detection*, not authorization.                                                                                   |
| **Cross-cutting + META** | 12 rules + 5 meta skills (optimize-my-skill/agent/agents-md, refresh-agents-md, retrospect) | A lot of "optimize the optimizer." That many pruning tools for a 52-asset garden is itself a signal you're over-planting.                                                                                                       |

## The three things that are actually in your way

**1. You're using a divergent tool where a convergent one belongs.** The HEAVY gate runs up to 3 rounds of finder → refuter → fixer, generating dozens of opus/sonnet calls per diff. The file *says* it's "interim" and admits hitting the round cap is common and "NOT a clean bill of health." That's a self-documented non-convergence problem. Refuter panels can't converge by construction — each refuter is incentivized to find a *new* objection. Tests converge — a test passes or fails deterministically. The fix isn't to tune refuter counts (3→2); it's to **convert refuter findings into red regression tests** before they count. Right now survivors get a "fixer call" that patches code, not a failing test that locks the behavior in. That conversion is the missing step between "adversarial review" and "mechanical evidence."

**2. Three independent copies of "what to review."** The review checklist (security/quality/reuse/efficiency/architecture) is authored three times: in `quality-reviewer.md`, in `simplify/SKILL.md`, and again as finder-lens briefs inside `quality-gate.js`. SERIAL and HEAVY take different paths through them, so they surface *different* findings each time — and that drift is itself a non-convergence source. One source of truth, read by both tiers, kills this.

**3. Process sized to the worst case, applied to every case.** The gate tiers SKIP/SERIAL/HEAVY cleanly (gate-triage is your best-engineered asset). But the *delivery chain* it unconditionally mandates below the gate is unsized — a one-line SKIP change still owes the full `wait-for-pr-comments` polling loop. The tiering stops at the wrong boundary.

## Verdict on your three specific doubts

- **"quality-gate under-powers reviews and over-spends on refuters"** — Correct, but the framing is too small. It's not an under/overspend tuning problem; it's a *role* problem. Refuters shouldn't be the primary verifier at all. Demote them to one bounded pass whose output is red tests, run *after* the mechanical verify (acceptance criteria + test suite) has already converged.

- **"codex-taking-copilot's-place revealed gaps in PR processing"** — Real, and the gap is concrete: there's a *known, self-documented correctness mismatch* in the current bash chain (poll-copilot-review.sh's completion detection is narrower than check-merge-eligibility.sh's acceptance criteria). No amount of prompt discipline fixes a script bug. This is the strongest argument *for* prgroom, not against it.

- **"PR workflows are prose+bash; prgroom intends to make it deterministic — losing faith it's the right thing"** — Your doubt is half-right and half-wrong. prgroom is **not vaporware**: 1026 passing tests, 99.5% coverage, strict mypy, real Protocol-seamed architecture. It genuinely *removes* the fragility for the mechanical state-machine parts (idempotency, schema, locking) by making them type-checked code instead of an LLM's reading of a 1283-line spec. **But** it has two real holes: `sweep` is a stub, and the `verify` subsystem (the fix-quality gate — the highest-fragility piece) is 0% implemented. So the part that would replace the noisy adversarial gate doesn't exist yet in prgroom either. The instinct to doubt isn't crazy; the conclusion to abandon is.

## What I'd actually do

1. **Finish prgroom's `verify` subsystem and switch the delivery chain onto it.** This is the exit ramp from the windmill — it replaces a 1283-line prose state machine + a non-convergent refuter panel with deterministic, tested code. This is the single highest-leverage thing on your roadmap.
2. **Collapse the three "what to review" lists into one source of truth** that both SERIAL and HEAVY read. This kills the drift-driven non-convergence.
3. **Change the refuter contract:** a refuter finding that can't be expressed as a failing test gets dropped, not prose-argued. One bounded adversarial pass, not a 3-round cap.
4. **Size the delivery chain the way the gate is sized,** or make `wait-for-pr-comments` cheap — which prgroom already does. Don't make SKIP owe HEAVY's obligation.
5. **Prune the META layer and the instruction surface.** 5 optimize-the-optimizer skills for a 52-asset system is the smell of over-building. The cheapest win for your M3 cheap-model fleet is *less context per task* — and every rule file is context every worker loads. Your own mission ("get the human out of babysitting") is best served by a thinner instruction surface, not more orchestration on top of a thick one.

## The one-line verdict

You're not tilting at windmills with prgroom — that's the right exit ramp and it's real. You *are* tilting with the HEAVY refuter panel: it's a convergent-evidence job being done with a divergent-judgment tool, and no amount of fleet-sizing will make it stop finding "a few new things each time." Finish the verify subsystem, demote the refuters, and the rounds problem goes away by construction rather than by cap.

One caveat on my own objectivity: I'm running under your loaded instruction set, and my recommendations happen to align with your *stated* mission (mechanical evidence, code-over-prose, consolidate-over-conflict). That's reassuring — it means I'm pointing at where the implementation drifted from the mission, not rebelling against the mission itself — but it also means I'm the model most primed to agree with the mission. If you want a genuinely adversarial check on this verdict, route it through `/codex:adversarial-review` or a bare-context subagent (which you have a skill for) so it's not shaped by these same rules.
