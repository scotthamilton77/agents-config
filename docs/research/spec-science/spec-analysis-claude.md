## Bottom line first

**No published work validates a *template*. The literature validates about five *properties*, and one of the best-controlled studies in the space found that the artifact most people are betting on — repository-level spec/context files — has no measurable effect on task success while costing ~20% more.** If you build templates, build them to carry the properties, and treat every structural element you add as a cost you must justify with your own measurement.

The strongest counterargument to the premise of your question: the framing "a corpus of specification that looks like X produces better outcomes" assumes the effect lives in the document. The evidence says the effect lives almost entirely in **the task-level packet handed to the implementing agent**, and barely at all in the surrounding corpus. Multi-level spec hierarchies are justified as *human coordination and compile-time inputs*, not as agent context. Getting this backwards is the dominant failure mode in current SDD tooling.

---

## What is actually substantiated

| Claim                                                                                                    | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | Confidence                                             |
| -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Ambiguity in the task description causally degrades correctness, and stronger models are not more robust | Orchid benchmark: ambiguity degrades all evaluated models, cutting Pass@1 by 7.22 points on average with the worst case at 31.10 points; GPT-4 dropped more than 28 points despite top-tier baseline performance, while Qwen-2.5-Coder degraded only ~8. Models also produce functionally divergent implementations from the same ambiguous requirement and cannot reliably detect the ambiguity themselves                                                                                                             | **High**                                               |
| Structured rewriting of the *task description* produces large gains                                      | Gloaguen et al. rewrote SWE-bench issues into a fixed 6-section schema (description, repro steps, expected behavior, observed behavior, specification, additional info) and saw roughly 15% higher accuracy with model rankings preserved — GPT-5.2 57.0%→70.8%, Qwen3-30B 30.3%→46.9%                                                                                                                                                                                                                                  | **Moderate** (see caveat below)                        |
| Repository-level context files (AGENTS.md/CLAUDE.md) do *not* improve task success and increase cost     | Across 4 agents/models on SWE-bench Lite and a new 138-instance CTXBench, context files showed no significant effect (p=0.87, 0.37, 0.21) while significantly increasing steps and cost by 20–23%. Critically, this is not an instruction-following failure: uv was invoked 1.6×/instance when mentioned versus under 0.01 when not, and repo-specific tools 2.5× versus under 0.05. Reasoning-token consumption rose 22% and 14% — the agents treated extra instructions as extra constraints, making each task harder | **High**                                               |
| Repository *overviews* specifically are dead weight — unless no other docs exist                         | Overviews did not reduce steps-to-first-relevant-file for any agent; when all documentation was stripped from the repo, LLM-generated context files improved performance 2.7% on average, indicating they are mostly redundant documentation                                                                                                                                                                                                                                                                            | **Moderate–High**                                      |
| Interface-level commitment (signatures/skeletons), not design models, is what makes agents conform       | DesBench ablation across 5 input conditions: adding a code skeleton produced the largest single improvement, moving Pass@k from ~0.30 to 0.76; adding method names or a UML design model alone gave minimal or no Pass@k gain. When method-name match fell below 0.95, Pass@k collapsed toward zero. The authors conclude the design model acted as interference rather than guidance because LLMs lack the implicit rules for translating a model into code                                                            | **Moderate** (see caveat)                              |
| Selective clarification before implementation recovers much of the ambiguity loss                        | ClarifyGPT (FSE 2024): GPT-4 Pass@1 rose from 70.96% to 80.80% on MBPP-sanitized, a 13.87% relative improvement, p=3.2e-05. The design detail matters: asking clarifying questions on every requirement causes needless interaction and *hurts* generation when questions go off-topic; the gain comes from detecting ambiguity first and asking only then                                                                                                                                                              | **Moderate–High**                                      |
| Agents will not ask on their own                                                                         | Empirical work found state-of-the-art code LLMs generate output in over 63% of ambiguous scenarios without seeking clarification                                                                                                                                                                                                                                                                                                                                                                                        | **High**                                               |
| LLM-generated acceptance tests reach human-comparable *coverage* but poor *design*                       | DesBench: acceptance tests generated from functional requirements matched human-written coverage, but models packed multiple cases into one test method, generated near-duplicate cases, and missed edge states (e.g., testing CONFIRMED and CANCELED but never PENDING). Supplying a test specification or I/O pairs consistently raised the rate at which correct code passed generated tests (95%→99% for the strongest model)                                                                                       | **Moderate**                                           |
| Tests alone cannot detect scope creep; ID-anchored traceability can                                      | traceSDD study: injected out-of-scope functions, unauthorized imports, and over-engineering all passed the functional test suites; an orphan-REQ-ID set-difference check caught 86.4–88.0% of them with 0% false positives, while all non-citing conditions caught 0%                                                                                                                                                                                                                                                   | **Low–Moderate** on numbers, **Moderate** on mechanism |
| End-to-end SDD pipelines, by themselves, buy very little                                                 | Spec Kit Agents: 128 runs across 32 features and 5 repositories yielded +0.15 on a 1–5 LLM-as-judge composite (+3.0% of scale, Wilcoxon p<0.05) with 99.7–100% test compatibility maintained. That is a small effect from a whole multi-agent pipeline, measured by an LLM judge                                                                                                                                                                                                                                        | **Moderate**                                           |

### Caveats you should weight

- **The 15% rewrite gain is an upper bound.** The rewritten descriptions were produced by an agent that had access to the gold patch. The authors instructed it not to leak the solution and manually inspected, finding no leakage and calling the result a slightly easier but fairer evaluation — but "not leaking the solution" and "not implicitly encoding the shape of the solution" are different bars. Treat the direction as solid, the magnitude as optimistic.
- **The DesBench skeleton result is partly measuring name conformance.** Its oracle tests bind to exact class/method names, so any renaming zeroes the score. That inflates the skeleton's apparent value *as correctness*. It does not invalidate the operational conclusion, though: whenever an agent's output must plug into pre-existing tests, callers, or contracts, unpinned interfaces are a dominant failure mode. Also note the model generation is dated (GPT-4o-mini era) — I'd expect frontier 2026 models to do better on design-model adherence than this table shows.
- **The traceSDD paper is weak evidence for its own numbers.** Single-author preprint, evaluating the author's own framework, hallucinations injected as *fake REQ IDs* — which is precisely what the orphan-ID check is built to find. Circular. The paper itself notes ~12% of injected hallucinations bypassed detection by simply omitting the citation, and all four conditions achieved 100% functional correctness, which tells you the task suite was too easy to discriminate. What survives is the mechanism, not the effect size.
- **SWE-bench Verified is a natural experiment, not a controlled one.** 38.3% of samples were flagged for underspecified problem statements and 61.1% for unfair unit tests — spec quality is confounded with test-suite and environment fixes, so you cannot attribute the resolution-rate jump to specification alone.

### What is not substantiated (and is mostly marketing)

The vendor and blog numbers — "3–10× first-pass success," 18-month/30-engineer projects in 76 days, order-of-magnitude fewer regeneration cycles — are uncontrolled field reports with no baseline. The most useful practitioner counterweight is Böckeler's Thoughtworks evaluation: Kiro expanded a small bug fix into 4 user stories with 16 acceptance criteria; spec-kit generated so many markdown files for a mid-sized feature that the implementation was never finished, with the estimate that plain AI-assisted coding would have been faster; review burden shifts from code to verbose artifacts rather than decreasing; and agents still ignored instructions despite constitution files, producing a false sense of control.

EARS deserves a specific note: it has decades of RE practice behind it and is genuinely good at reducing ambiguity *for humans*, which matters because ambiguity is the thing that measurably hurts agents. But I found **no controlled experiment showing EARS-formatted requirements outperform equally-precise prose for LLM code generation.** Use it as a forcing function for the author, not as a claimed model-side optimization. Confidence: **low** that the notation itself carries any effect beyond the precision it induces.

---

## The design principles that fall out

1. **Optimize the L4 packet, not the corpus.** Effect sizes at the task level are 10–50× those at the ambient-context level.
2. **Every level above the work unit is a compile-time input.** Vision and epic documents should almost never enter an implementation agent's context window. They exist to produce, review, and validate the packet.
3. **Precision beats volume; volume has a measured cost.** More instructions → more constraints to satisfy → more reasoning tokens → more steps → no accuracy gain.
4. **Convert prose constraints into executable constraints wherever possible.** Architecture → dependency rules a linter enforces. NFRs → numeric CI budgets. UI → rendered-state assertions. Prose that could have been a gate is prose that will be selectively ignored.
5. **Pin interfaces, don't describe them.** The single highest-leverage artifact is the type/signature surface, not the diagram.
6. **Gate on ambiguity before implementation, selectively.** Universal clarification is net-negative.
7. **Give every requirement a stable ID.** Not for the ceremony — for the cheap grep-based coverage and orphan checks that tests structurally cannot perform.

---

## Proposed structure

Five layers. The vertical axis is *stability*, not *detail* — that's what makes the traceability tractable.

### L0 — Constitution (repo-scoped, ~50–150 lines, hard cap)

**Contents:** only rules an agent cannot infer from the codebase. Non-standard conventions, forbidden patterns, the build/test invocation, deviations from ecosystem defaults.
**Explicitly excluded:** repository overviews, directory listings, restatements of README content, generic best practices, anything a linter already enforces.
**Acceptance test:** none — but every line must be deletable-and-testable. If you can't name what would break, delete it.
**Rationale:** this is the layer the ETH study measured as null-to-negative. Keep it thin and adversarial.

### L1 — Product Direction (vision)

**Artifacts:** problem statement, target users, success metrics with numeric targets and measurement method, explicit non-goals, and a *constraint register* (regulatory, platform, budget, org).
**Acceptance test:** outcome metrics — measurable in production, not by an agent.
**Traceability:** owns `OBJ-*` IDs. Every capability must cite one.
**Agent exposure:** planning/decomposition agents only. Never implementation.
**The non-goals section is the load-bearing part.** Scope creep is the failure mode tests cannot catch, and negative space is what constrains it.

### L2 — Capability / Epic

**Artifacts:**
- Capability statement + the `OBJ-*` it serves
- **User-observable outcome scenarios** (5–15, prose, no implementation detail) → become the e2e/integration suite
- **NFR budget table** — numeric only: p99 latency, error budget, bundle size, memory ceiling, cost per request, availability. Each row names its enforcement gate.
- **Architecture decision set** (see below)
- **Decomposition into features** with declared interface boundaries between them
- **Open questions register** with owner and blocking status

**Acceptance test:** the outcome scenarios, executed end-to-end, plus the NFR budgets as CI gates.
**Traceability:** `CAP-nnn`, requiring `OBJ-*` parents and enumerating `FEAT-*` children.

**Where architecture sits:** between L2 and L3, and it is *the* decomposition constraint. Its human-facing form is whatever you like — C4, ADRs, diagrams. Its **agent-facing form must be three executable artifacts**:

1. **Module/ownership map** — directory boundaries, who owns what
2. **Allowed-dependency rules** — as an import-linter / ArchUnit / eslint-boundaries config, not prose
3. **Interface contracts** — OpenAPI, protobuf, or checked-in type definitions

The DesBench result is the justification: a class diagram in the context window measurably failed to constrain generation, while code-shaped artifacts did. Do not hand agents PlantUML and expect conformance.

### L3 — Feature Specification (the review unit)

This is where FR and AC discipline lives, and where a human reviewer should be spending their attention.

```
FEAT-042: <name>                      parent: CAP-012
─────────────────────────────────────────────────────
Intent            1–3 sentences. What changes for the user.
In scope          Bulleted, concrete.
Out of scope      Bulleted, concrete. ← enforced later
Current behavior  What exists today (brownfield) or "n/a"

Requirements      REQ-042.1 … REQ-042.n
                  EARS-shaped. One testable assertion each.
                  Explicit types, formats, boundary inclusivity,
                  null/empty/error behavior.

Acceptance        AC-042.1.1 … Given/When/Then, executable.
criteria          Every REQ has ≥1. Every AC names its test.

Interface         The contract this feature exposes and consumes.
contract          Signatures/types/schema — checked in, not prose.

NFR bindings      Only the L2 budget rows this feature can violate.
                  Cite the row; do not restate it.

Data & migration  Schema deltas, backfill, rollback.

Failure modes     What must degrade gracefully, and how.

Assumptions       Explicit. Each one is a clarification candidate.
```

Two things worth defending:

- **"Out of scope" is not decoration.** It is the only input to the orphan/scope-creep check that tests cannot perform. The traceSDD result — injected out-of-scope code passing 100% of tests — is the argument.
- **Boundary and format precision is where the ambiguity gain lives.** DesBench's construction is instructive here: they explicitly defined formats for complex values and stated whether boundary values were inclusive, because terms like "within" and "between" cause misunderstandings. That's the concrete, non-ceremonial content of an EARS discipline.

**On functional vs non-functional:** split NFRs into two classes and route them differently.
- **Budgeted** (latency, size, memory, cost, coverage): live at L2 as numbers, enforced as CI gates, injected into L4 *only* when that work unit can plausibly violate the budget. Injecting all of them into every packet is exactly the constraint-inflation the ETH study penalized.
- **Invariant** (authz, PII handling, input validation, audit logging): belong in L0 *and* as policy tests / static analysis. Prose is the weakest possible carrier. Note that the context-file corpus study specifically flagged security and performance instructions as scarce in practice — encoding them as gates is both more reliable and cheaper.

**Where UI/UX sits:** at L3, as a peer to the interface contract, in three parts —
1. **Design system as code** (tokens, component library). This is the real constraint; a prose style description is not.
2. **Visual reference** — screenshot, Figma export, or existing component to match. This is the oracle.
3. **Behavioral acceptance criteria as rendered-state assertions** (Playwright/Testing Library), not prose descriptions of appearance.

The front-end benchmark literature is consistent that iterative visual feedback loops, not richer textual UI specs, drive quality — and that the interesting evaluation signal comes from rendered behavior rather than source. Design your UI ACs so an agent can self-check by rendering. Confidence: **moderate**; this area is benchmark-rich but ablation-poor.

### L4 — Work Unit Packet (what the agent actually receives)

This is a **compiled artifact**, generated from L0–L3, not authored. Target: self-contained, one context window, no upward navigation required.

```
WU-042.3                              implements: REQ-042.3, REQ-042.4
──────────────────────────────────────────────────────────────────────
1. Task              What to build, in the 6-section shape that
                     measurably worked: description / repro or trigger /
                     expected behavior / observed behavior /
                     specification / additional info
2. Requirements      The verbatim REQ + AC subset. Nothing else.
3. Surface           Files this may touch. Files it may NOT touch.
4. Interface         Skeleton: signatures, types, stubs, TODOs.
   commitment        ← highest-leverage element in the packet
5. Tests             Existing tests that must stay green.
                     New test names it must make green.
6. Relevant NFRs     Only budgets this unit can violate.
7. Local context     The 3–8 files/snippets that matter. Concrete,
                     not "explore the repo."
8. Done              Commands to run. Expected states.
```

Item 4 is the one I'd fight for hardest given the evidence, and it's also the one most SDD tooling omits — Kiro and Spec Kit both produce prose design docs rather than checked-in skeletons.

---

## Traceability model

Keep it string-greppable. Do not build a graph database.

```
OBJ-003  →  CAP-012  →  FEAT-042  →  REQ-042.3  →  AC-042.3.1  →  test_name
                                                                 →  code (optional citation)
```

**CI checks, all cheap:**

| Check                                              | Direction | Catches                 |
| -------------------------------------------------- | --------- | ----------------------- |
| Every REQ has ≥1 AC                                | down      | untestable requirements |
| Every AC has ≥1 named test that exists             | down      | spec/test drift         |
| Every REQ ID cited in code exists in a spec        | up        | fabricated requirements |
| Every changed file is inside a declared surface    | up        | scope creep             |
| Every FEAT cites a live CAP; every CAP a live OBJ  | up        | orphaned work           |
| Spec touched without test touched (and vice versa) | lateral   | silent divergence       |

**On inline per-line REQ citations in source:** I'd skip them by default. The measured benefit is real but narrow, the measured cost is real, and the study's construct validity is weak. Test-level and file-level annotations get you most of the coverage checking at a fraction of the noise. Reconsider for regulated/safety-critical work where the traceability matrix is a deliverable anyway.

---

## Validate this against your own corpus

Given your eval background, this is where I'd put the effort, because none of the above transfers cleanly to your repos.

**Harness:** 25–40 historical work items from your codebases where you have the merged PR as ground truth. Bias toward brownfield feature work, not bug fixes — that's where spec structure should matter most and where the public benchmarks are weakest.

**Conditions** (3 runs each, temperature fixed, paired on task ID):
- A: original ticket text (baseline)
- B: full L4 packet
- C: B minus interface commitment (§4)
- D: B minus acceptance criteria (§5)
- E: B minus surface declaration (§3)
- F: B plus full L1–L3 documents dumped in (the "more context" straw man — include it, you may be surprised)

**Metrics — and measure cost, not just success:**
- First-pass CI-green rate (primary)
- Human review iterations to merge
- Files touched outside declared surface (scope-creep proxy)
- Diff distance from gold patch
- Steps and USD per task
- Reasoning-token delta between conditions

**Falsifiable predictions from the evidence above.** If these don't hold on your corpus, the templates are wrong for your domain, not the other way around:
- B > A by ≥10pp on first-pass green
- C ≈ A (interface commitment carries most of B's gain)
- F ≤ B and F costs ≥20% more
- E shows no accuracy change but measurably more scope creep

Sample size: with n=30 and 3 runs, you can detect roughly a 15pp difference with paired tests. Anything smaller is noise at this scale — which also means: if a template element only buys 3pp, it isn't worth the authoring cost.

**Sequencing:** build L4 first and prove it. Only then build the levels above it, and build them because humans need them for coordination and review — that justification stands on its own and doesn't require an agent-performance claim.
