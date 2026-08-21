# Evidence-Based Specification Design for Agent-Driven Product Development

## Bottom line

The strongest conclusion from the research is somewhat inconvenient for the current “spec-driven development” enthusiasm:

> **There is not yet convincing experimental evidence for a particular end-to-end requirements methodology or document family—PRD → epic → story → design → task—that is proven to optimize agentic software development.**

I found no controlled study demonstrating that a recognizable commercial template such as a traditional PRD, SAFe epic, Jira story, IEEE-style SRS, GitHub Spec Kit structure, OpenSpec structure, or similar hierarchy produces superior end-to-end agent outcomes across a realistic PDLC.

There **is**, however, a rapidly emerging and surprisingly coherent experimental literature showing that several *properties* of specifications materially improve agent outcomes. The strongest studies are mostly from 2026 and therefore have limited independent replication, so I would rate the overall evidence as **moderate rather than high confidence**. Within-study effect sizes are often substantial. citeturn15search8turn15search3turn15academia28

My synthesis is:

> **Do not build your agentic PDLC around a collection of prose templates. Build it around a typed, traceable graph of engineering obligations, rendered into small task-specific context packages for agents.**

The evidence favors a corpus with these properties:

1. **Intent, required behavior, architecture, implementation planning, and verification are distinct artifacts**, connected by explicit traceability rather than mixed into one document. Recent CodeSpec and Repo0 experiments independently support separating requirement-side semantics from architecture/realization information. citeturn15academia28turn17view1
2. **Detailed requirements are structured, but lightly structured.** REAgent's fixed requirement attributes outperformed unstructured requirement generation; SpecFirst's six-heading Markdown structure slightly outperformed both free-form specifications and the more formal OpenSpec/RFC-2119/Given-When-Then format. citeturn18view3turn19view1
3. **Acceptance is executable wherever possible.** In REAgent, replacing execution-based requirement assessment with an LLM judge materially reduced resolution; CodeSpec found executable architecture and behavioral specifications particularly valuable on long-horizon work. citeturn5view2turn13view0
4. **“Correct new behavior” and “preserve existing behavior” are separate obligations.** FeatureBench explicitly evaluates fail-to-pass and pass-to-pass tests; TDAD found that supplying agents with dependency-informed regression context sharply reduced regressions. citeturn18view2turn20view0
5. **Architecture should be explicit and traceable, but not prematurely frozen.** CodeSpec's architecture-spec ablation hurt feature-development performance; Repo0's experiments suggest that a requirement graph and a separately evolving component graph outperform a unified/static realization model in greenfield repository generation. citeturn13view0turn18view0
6. **More context is not inherently better.** Controlled experiments on `AGENTS.md`-style repository files found little or negative benefit from automatically generated general-purpose context and more than 20% higher inference cost; the useful information tended to be the non-obvious, repository-specific constraints. citeturn21search0turn21search4
7. **Visual requirements need both visual and behavioral representations.** Current multimodal experiments show screenshots/Figma improve visual grounding, but visual information alone does not guarantee functional correctness; interaction semantics and executable workflows remain necessary. citeturn11view2turn11view3turn10view0
8. **Uncertainty and derived assumptions should be explicit.** SWE-RPG finds requirement clarification and planning failures to be a major fraction of unsuccessful agent runs; specification omissions and inaccuracies also account for substantial remaining failures in SpecFirst. citeturn21search1turn19view0

The architecture I would therefore recommend for your own PDLC looks roughly like this:

```text
                     PRODUCT INTENT
                          │
                    refines / allocates
                          ▼
                 CAPABILITY / EPIC
                  ╱       │       ╲
           journey     quality     scenarios
              │        budgets        │
              └──────────┼────────────┘
                         ▼
                DELIVERABLE REQUIREMENT
                / FEATURE / CHANGE SPEC
                    │            │
             verifies│            │realized-by
                    ▼            ▼
            ACCEPTANCE       ARCHITECTURE
            OBLIGATIONS       REALIZATION
          behavior | regression   │
          quality  | UX           │constrains
                    │             ▼
                    └──────► LOW-LEVEL DESIGN
                                  │
                                  ▼
                            IMPLEMENTATION
                                  │
                                  ▼
                         EXECUTED EVIDENCE
```

That looks superficially like conventional requirements engineering. The important difference is that **each box is intended to be machine-addressable, selectively retrievable, provenance-aware, and—with increasing detail—executable.** That distinction is where the emerging agent evidence gets interesting.

## What the experimental literature actually shows

I would separate the evidence into direct treatment experiments, benchmark diagnostics, and corroborating industrial work. That distinction matters because a lot of SDD literature quietly jumps from “this benchmark uses specifications” to “therefore this specification style works.” Those are not equivalent claims.

### The best direct evidence for structured requirements

**REAgent** is probably the closest study I found to the experiment you described. It takes repository-level issue-resolution tasks and creates an intermediate structured “issue-oriented requirement” before asking the coding agent to solve the problem. Its schema contains nine main areas: repository background, problem overview, reproduction, actual behavior, expected behavior, environment, root-cause analysis, solution information, and additional concerns such as security and compatibility. citeturn18view3

More important than its headline performance is the ablation study. Removing requirements modeling altogether reduced average resolved rate by about **9.5 percentage points**. Keeping requirements but removing the predefined attribute structure—i.e. letting the requirements remain unstructured—reduced resolved rate by about **3.3 points**. Replacing executable test-based requirements assessment with an LLM judge cost roughly **7.7 resolution points**, while removing targeted refinement also hurt performance; the reported comparisons were statistically significant. citeturn5view2

That gives us fairly direct evidence for:

> **A semantically structured intermediate requirement representation is better than simply telling an agent to make a richer description.**

**Confidence: moderate.** The experiment spans multiple SWE-bench variants and models and contains useful ablations, but it is still one recent preprint and primarily concerns issue resolution rather than an entire PDLC. citeturn15search8

One qualification is important. REAgent mixes true requirements with analysis and proposed solution details—root cause, likely code paths, modification location, and modification content. citeturn18view3 I would **not** copy that aspect into a canonical requirements template. Instead, I would interpret its result as evidence that an implementation agent benefits from receiving all of those semantic dimensions, while storing them in separate artifact types so that stakeholder intent is not confused with agent-derived solution hypotheses.

### The best direct evidence for a specification phase

**SpecFirst** gives a cleaner experiment on whether an explicit specification phase is worthwhile. It separates behavioral discovery from implementation: one agent explores the target system and produces `SPEC.md`; a second agent implements from that specification. Across all 200 ProgramBench tasks and four model configurations, SpecFirst improved test pass rates by **6.9–21.3%** and behavioral-exploration coverage by **9.4–18.5%**, with the reported improvements statistically significant. citeturn18view1turn19view2

The particularly useful part for your question is that the authors separately experimented with the *format* of `SPEC.md` on 50 tasks using GPT-5.4-mini:

| Specification treatment | Test pass rate |
|---|---:|
| No specification | 55.9% |
| Free-form specification | 60.7% |
| OpenSpec-style requirements + RFC 2119 + Given/When/Then | 61.7% |
| Lightweight named sections | **62.6%** |

The lightweight structure used six categories: **Overview, Flags, Input & stdin, Output format, Error patterns, Edge cases**. citeturn19view1turn19view4

That is an unusually useful result because it challenges two easy assumptions simultaneously:

* specification **does** appear to help;
* greater syntactic ceremony **does not appear to be the main reason** it helps.

The difference between free-form, OpenSpec, and sections is small compared with the difference between having and not having an elicited behavioral specification. The sample for the format comparison is only 50 tasks, so I would not declare six Markdown headings the One True Template. citeturn19view1

**My interpretation:** optimize the template for **semantic coverage and retrieval**, not requirements-language aesthetics.

SpecFirst's failure analysis reinforces that point. Among 50 sampled failures, 10% involved an omitted behavior, 4% an incorrect specification, and 26% a specification that mentioned the feature but lacked sufficient precision; 52% instead occurred because the implementation failed to follow a sufficiently good specification. citeturn19view0 In other words, better specs help but do not abolish the need for executable verification.

### The strongest evidence for executable specifications

**CodeSpec** is particularly relevant to architecture and long-running feature work. It decomposes a high-level feature into subrequirements, grounds each against repository evidence, derives a “functional chain,” and compiles that information into two different executable specifications:

* a **behavior specification**, checking observable outputs, boundary conditions, and state transitions;
* an **architecture specification**, checking expected functional units, relationships, and data flows. citeturn15academia28turn12view0turn12view1

Its controlled FeatureBench experiment reported:

| Treatment | FeatureBench pass rate |
|---|---:|
| Full CodeSpec | **70.7%** |
| No specifications | 62.6% |
| Without behavior spec | 64.0% |
| Without architecture spec | 66.6% |
| Without evidence grounding | 64.8% |

The same agent/model/environment budgets were used for the controlled comparison. citeturn13view0

More interestingly, the difference between **executable and textual** specifications grew with task length. For tasks whose instructions were approximately 3,000–5,000 words, executable CodeSpec achieved **71.8%** versus **43.8%** for its textual counterpart. For simpler/shorter tasks the difference was substantially smaller. Long agent trajectories showed a similar advantage. citeturn13view0

That suggests an important PDLC design principle:

> **Specification rigor should scale with coordination complexity.**

Making every trivial edit walk through a full specification/architecture/verification pipeline is not supported by this evidence. The return appears greatest when the agent must preserve constraints across many interactions, components, or files. citeturn13view0

### Architecture is not merely “extra context”

Repo0, released August 20, 2026, provides extremely fresh and therefore especially replication-poor corroborating evidence. It deliberately maintains **two graphs**: a requirement-level graph expressing functional relationships and a component-level graph expressing realization/dependencies, plus a many-to-many alignment relation from requirements to components. The requirement graph generally stabilizes earlier, while the component graph can evolve during design. citeturn17view1

Across six repository-generation targets and two model families, Repo0 reported higher functionality coverage and pass rates than the strongest static repository-planning baseline, with gains of up to **20.08 percentage points in functionality coverage** and **29.74 points in pass rate**. Critically, all systems used the same downstream code-generation/validation scaffold after producing their architecture, which makes the architecture treatment relatively well isolated. citeturn17view1turn18view0

The ablations are more informative than the headline. Removing structural evolution caused the largest broad degradation; replacing the dual requirement/component graph with a unified graph also hurt results, and omitting related requirement context reduced correctness on interacting functionality. citeturn18view0

**Confidence: low-to-moderate**, because the paper is literally one day old as of August 21, 2026 and has no independent replication. But its conclusion is strikingly consistent with CodeSpec:

> **Keep “what behaviors belong together” distinct from “what components implement them,” and maintain an explicit mapping between the two.**

That is almost exactly the architecture/requirements boundary I would use in an agent-native corpus.

### Context stuffing is actively suspect

A particularly useful negative result comes from the ETH Zürich study of `AGENTS.md`-style repository context. It tested coding agents both on SWE-bench tasks and on a new set of repositories with developer-authored agent context files. Automatically generated context did not reliably improve performance and often reduced it, while context files increased inference cost by more than 20%. Human-written files were better than generated ones, but the study's overall conclusion was that only non-obvious, necessary repository constraints should be included. citeturn21search0turn21search4

Agents were not simply ignoring the extra content: they followed its instructions and performed more exploration, testing, and navigation. The problem was that unnecessary instructions consumed effort without yielding corresponding task success. citeturn21search4

TDAD finds a conceptually similar result from another direction. On its small-model experiments, a verbose 107-line TDD procedure was substantially less effective than a concise 20-line instruction coupled with concrete information about **which tests are impacted**; graph-informed test context reduced test-level regression from 6.08% to 1.82% in its 100-task experiment. The authors explicitly caution that the study uses two smaller models, limited samples, Python only, and lacks formal significance testing. citeturn20view0

These are strong warnings against an attractive but wrong architecture:

```text
VISION.md
PRD.md
EPICS.md
ARCHITECTURE.md
SECURITY.md
UX.md
STYLE.md
TESTING.md
DESIGN_SYSTEM.md
OBSERVABILITY.md
...
        │
        └──► shove all of it into every coding-agent context
```

I would instead make the corpus large and the **compiled task context small**.

### Real developer requests are often insufficient specifications

A Microsoft study mutated formal GitHub issues into shorter, telemetry-informed user-style queries while holding the codebase and test harness constant. OpenHands success on SWE-bench Verified fell from 35.6% to 22.6% with GPT-4.1, from 54.2% to 39.2% with Sonnet 3.7, and from 65.4% to 50.2% with Sonnet 4; effects were smaller on a private C# benchmark but remained negative. citeturn14view0

The authors reasonably note that public benchmark contamination and other differences prevent attributing the entire drop solely to specification completeness. Their mutations can also remove information sufficiently important to make some tasks genuinely underspecified. citeturn14view0

But that caveat actually strengthens the PDLC conclusion: **raw conversational intent and an implementation-ready specification are different artifacts**.

SWE-RPG reaches the same issue from a diagnostic angle. Across 163 Python/Java repository tasks, three coding frameworks, and six model backends, agents averaged only 31.5% resolution, while **46.7% of runs failed primarily during requirement clarification or implementation planning** rather than final coding. citeturn21search1

I would therefore make the transition

```text
RAW REQUEST  →  CLARIFIED REQUIREMENT
```

a first-class transformation with provenance rather than silently letting the coding agent fill in missing intent.

## Design principles for an agent-native specification corpus

Based on the experiments above, I would impose several architectural properties on the corpus itself.

### The source of truth should be a graph, not a document hierarchy

Conventional requirements tooling encourages:

```text
Vision
 └── Epic
      └── Feature
           └── Story
                └── Task
```

That tree is useful for project management. It is not rich enough for engineering semantics.

The empirical work increasingly uses graph relationships: Repo0 has requirement coordination, component dependency, and requirement-to-component alignment; CodeSpec traces subrequirements through functional chains into architecture and behavior checks; Bosch's industrial test-specification workflow has intermediate structures because requirements and tests exhibit many-to-many relationships. citeturn17view1turn15academia28turn21search3

I would use typed edges such as:

```text
REFINES
DEPENDS_ON
DERIVED_FROM
REALIZED_BY
CONSTRAINS
VERIFIED_BY
PRESERVED_BY
AFFECTS
SUPERSEDES
EVIDENCED_BY
```

Then:

```text
OUTCOME-12
   │ REFINES
   ▼
CAP-37 ────────────── CONSTRAINS ─────────────► QUALITY-SEC-4
   │
   ├─ REFINES ─► REQ-371
   │               │
   │               ├─ VERIFIED_BY ─► AT-371-A
   │               ├─ PRESERVED_BY ─► RT-371-B
   │               ├─ REALIZED_BY ─► ARCH-COMP-18
   │               └─ EVIDENCED_BY ─► UX-FIGMA-29
   │
   └─ REFINES ─► REQ-372 ...
```

I would allow many-to-many realization and verification. A requirement often spans multiple components, and one architectural component commonly realizes several requirements; Repo0 explicitly models this as a many-to-many alignment rather than forcing ownership into a tree. citeturn17view1

### Provenance should be mandatory

Every normative or descriptive statement should indicate something like:

```yaml
provenance:
  class: stakeholder | observed | inferred | derived | implementation-choice
  source: ...
  confidence: validated | provisional | disputed
```

This is a synthesis rather than a directly tested field format, but the motivation is strong. SWE-RPG shows that implicit-requirement recovery is a substantial failure source; REAgent improves requirements through repository exploration and targeted refinement; SpecFirst explicitly distinguishes discovered behavior from incomplete documentation. citeturn21search1turn18view3turn19view0

This solves a problem that current spec-driven tools tend to blur:

> “The user said the API must be asynchronous”  
> is very different from  
> “The architecture agent inferred async would be preferable.”

Both are useful. Only the first is a requirement unless the inference is deliberately promoted and validated.

I would especially label:

```text
STATED        explicitly provided by authoritative stakeholder/source
OBSERVED      empirically observed in existing behavior
INFERRED      agent conclusion required to complete ambiguity
DERIVED       logically imposed by another accepted constraint
DESIGN        architecture decision
PLAN          current implementation tactic
```

That makes agent-created specification enrichment safe enough to be useful without quietly turning model guesses into organizational truth.

### Explicit examples should receive disproportionate attention

REAgent's successful schema explicitly contains reproduction commands, conditions, correct/incorrect behavior, and success criteria. SpecFirst's elicitation concentrates on actual observable inputs, outputs, error behavior, and edge cases. citeturn18view3turn19view4

The Bosch ACL 2025 industrial study provides an additional clue. In its system-level test-specification generation experiment, retrieval of similar historical requirements/test-purpose examples improved ROUGE-L considerably more than generic standards-oriented prompting; its multi-step process decomposed requirement → test design → scenarios → test purpose → final test specification. citeturn21search3turn3view0 Ten experienced test developers participating in its user study estimated roughly 30–40% time savings, although that is self-reported and domain-specific rather than an execution-based software-agent result. citeturn3view1

So I would spend template space on:

```text
canonical example
boundary example
negative example
error example
state-transition example
```

before spending it on three paragraphs of explanatory prose.

### Open questions should be data, not prose comments

A specification should be able to say:

```yaml
open_questions:
  - id: Q-371-2
    question: "Does cancellation refund an already-captured payment?"
    blocks:
      - AT-371-C
      - ARCH-42
    resolution_required_before: implementation
```

rather than hoping the agent notices a sentence containing “TBD.”

This exact schema is my recommendation rather than a proven format, but explicitly surfacing unresolved ambiguity follows directly from the requirement-clarification failures in SWE-RPG and the omission/inaccuracy failures in SpecFirst. citeturn21search1turn19view0

A very new August 19 preprint goes further, representing specifications as semantic blocks with dependencies, owned rules, decision points, and explicitly open questions. Its single Oracle-to-PostgreSQL case reported roughly 71% lower per-task context when agents were supplied only dependency closures, but given its age and narrow case I would treat it as an interesting research direction rather than validation of that particular formalism. citeturn16academia7

### Compile task context; do not retrieve “the docs”

The persistent corpus and the prompt/context given to an execution agent should be different things.

For a deliverable `REQ-371`, I would compile approximately:

```text
TARGET
  REQ-371

WHY
  concise projection of ancestor OUTCOME + CAPABILITY

BEHAVIOR
  REQ-371's states, inputs, outputs, examples, boundaries

APPLICABLE CONSTRAINTS
  only NFR/policies whose scope includes REQ-371

UX
  relevant journey/screens/component states only

ARCHITECTURE
  affected components/interfaces/invariants only

ACCEPTANCE
  new-behavior obligations
  preservation/regression obligations
  quality obligations
  UX obligations

IMPACT CONTEXT
  relevant code paths / existing tests / dependencies

OPEN QUESTIONS
  only unresolved questions that affect this work
```

That selective compilation is a synthesis supported by the AGENTS.md negative-context result, TDAD's impact-context result, CodeSpec's evidence-grounded requirement slices, and Repo0's use of aligned and neighboring requirement context rather than undifferentiated global context. citeturn21search4turn20view0turn15academia28turn18view0

This is one place I would strongly depart from today's “put everything in `CLAUDE.md`” pattern.

## Proposed artifact model from vision through delivery

I would use roughly **five primary engineering artifact types**, plus UX and acceptance artifacts that attach across them. These are logical types, not necessarily separate files.

| Layer | Primary question | Stability | Agent receives | Acceptance concept |
|---|---|---|---|---|
| **Outcome / Direction** | Why are we changing the system? | High | summarized | outcome evidence |
| **Capability / Epic** | What coherent capability must exist? | High-medium | relevant slice | scenario acceptance |
| **Deliverable Requirement** | Exactly what externally meaningful behavior must this increment provide? | Medium-high | full | executable behavior + preservation |
| **Architecture Realization** | How will requirements be partitioned and constrained structurally? | Medium | affected slice | conformance / fitness checks |
| **Low-Level Design / Change Plan** | What concrete changes will this run perform? | Low / disposable | full | implementation checks |

The distinction between requirement-side and realization-side representations follows the architecture experiments in CodeSpec and Repo0; the exact five-layer taxonomy is my synthesis rather than something validated verbatim in a study. citeturn15academia28turn17view1

### Outcome or direction artifact

This is the “why” layer. I would keep it deliberately small:

```yaml
id: OUTCOME-12
type: outcome

problem:
desired_outcome:
target_users_or_actors:

success_measures:
guardrail_measures:

in_scope:
out_of_scope:

strategic_constraints:
quality_priorities:

assumptions:
open_questions:

children:
```

Do **not** try to turn business metrics into fake Given/When/Then software tests.

The acceptance object here is an **evidence plan**:

```text
What observation would convince us that the outcome occurred?
What observation would tell us we harmed an important guardrail?
```

For example:

```text
Outcome:
  Reduce checkout abandonment attributable to payment failures.

Success evidence:
  payment-related checkout abandonment ↓ X%
  over evaluation interval Y

Guardrails:
  chargebacks do not increase
  p95 checkout latency stays under Z
```

That is product validation, not code acceptance.

**Evidence strength for this layer: low.** The agentic experiments largely start below product strategy. This is classical engineering synthesis. I would resist anyone claiming their exact “vision template” is empirically agent-optimized; I found no such evidence.

### Capability or epic artifact

An epic should describe a **coherent observable capability**, not a bag of implementation tasks.

```yaml
id: CAP-37
type: capability
parent: OUTCOME-12

capability:
actors:
user_or_system_journeys:

scope:
  included:
  excluded:

major_scenarios:
dependencies:

allocated_quality_constraints:
architecture_significant_scenarios:

ux_refs:

acceptance_contract:
children:

assumptions:
open_questions:
```

The acceptance contract at this level is scenario-oriented:

```text
Customer can:
  create a payment authorization
  recover from a recoverable decline
  cancel before capture
  receive a deterministic terminal status

System must:
  preserve idempotency
  meet the allocated latency budget
  maintain auditability
```

Those can eventually compile into multiple feature tests, integration tests, quality tests, and journeys. The capability-level acceptance clause is therefore a **coverage contract**, not necessarily one executable test.

FeatureBench reinforces that realistic features routinely encompass a high-level goal plus functional interfaces and require behavior across multiple parts of a repository, while CodeSpec decomposes such goals into linked subrequirements before implementation. citeturn18view2turn15academia28

### Deliverable requirement or change specification

This is where the empirical evidence is strongest and where I would impose the most consistent template.

A generalized version of the useful parts of REAgent and SpecFirst would look like:

```yaml
id: REQ-371
type: deliverable_requirement
parent: CAP-37

intent:
  purpose:
  observable_outcome:

scope:
  included:
  excluded:
  affected_behavior:

actors_and_preconditions:

behavior:
  trigger_or_input:
  normal_flow:
  outputs:
  state_transitions:
  error_behavior:
  boundary_conditions:

examples:
  canonical:
  negative:
  edge:

interfaces_and_data:
  contracts:
  compatibility:

constraints:
  applicable_nfr_ids:
  policy_ids:

ux_refs:

preservation_requirements:
  behavior_that_must_not_change:

acceptance:
  new_behavior:
  regression:
  quality:
  ux:

dependencies:
architecture_drivers:

assumptions:
open_questions:

provenance:
```

This incorporates the dimensions that REAgent found useful—preconditions, conditions, reproduction, actual versus expected behavior, success criteria, environment, impact, compatibility/security—without embedding root-cause or modification instructions inside the authoritative requirement itself. citeturn18view3

It also reflects SpecFirst's finding that edge cases, precise outputs, errors, and input behavior are frequent sources of specification gaps. citeturn19view4turn19view0

I would make a deliverable requirement pass an automated lint gate roughly equivalent to:

```text
Does it say what success looks like?
Are inputs/preconditions defined?
Are outputs/effects defined?
Are important state transitions defined?
Are known errors/boundaries defined?
Are examples concrete?
Is preservation scope stated?
Are applicable quality constraints linked?
Are unresolved decisions explicit?
Can every acceptance assertion be traced to something stated here
  or in an inherited requirement?
```

The last check is critical.

### Architecture realization artifact

I would **not** put architecture under the requirement as “technical acceptance criteria.” Keep it as a sibling realization model.

```yaml
id: ARCH-42
type: architecture_realization

driven_by:
  - REQ-371
  - QUALITY-7
  - QUALITY-12

context:
affected_components:

functional_chain:
  - responsibility:
    realized_requirements:
    inputs:
    outputs:
    downstream:

interfaces:
data_flows:
state_ownership:

architecture_invariants:
dependencies:

decisions:
  - adr_ref:
    rationale:
    derived_constraints:

conformance_checks:

risks:
open_design_questions:
```

CodeSpec directly supports treating architecture and behavior as complementary specifications: removing either executable specification lowered task success. citeturn13view0

Repo0 adds two insights I think are particularly important for an agentic PDLC:

First, **do not collapse functional decomposition and component decomposition**. Its requirement graph represents functional coordination, while its component graph represents implementation dependencies, with explicit links between them. citeturn17view1

Second, **architecture should be revisable**. Repo0's largest ablation degradation came from removing structural evolution, and its metric-guided architecture changes outperformed treating the first plan as final. citeturn18view0

So I would treat:

```text
requirements scope      relatively stable during implementation
architecture realization   controlled but revisable
low-level plan              highly revisable
```

rather than turning an agent's first architecture proposal into scripture.

### Low-level design or change plan

This artifact should be aggressively task-local:

```yaml
id: PLAN-371-04
type: implementation_plan

implements:
  - REQ-371

conforms_to:
  - ARCH-42

change_surface:
  files:
  components:
  symbols:

interface_changes:
schema_changes:
migration_changes:

execution_sequence:

failure_handling:

rollout:
  feature_flags:
  migration_order:
  compatibility:

observability:
  logs:
  metrics:
  traces:

test_impact:
  existing_tests:
  new_tests:

risks:
validation_commands:
```

I would not make this long-lived authoritative requirements content.

It is an **execution hypothesis**.

This distinction matters because the repository itself supplies evidence that frequently invalidates the first plan. CodeSpec grounds functional chains in code evidence, while Repo0 explicitly revises component boundaries when implementation evidence contradicts the initial structure. citeturn15academia28turn18view0

A useful lifecycle is therefore:

```text
Requirement: authoritative until deliberately changed.
Architecture: authoritative constraint, but change-controlled.
Plan: disposable and regenerable.
Code: candidate realization.
Tests/evidence: proof attempt.
```

That prevents the corpus from accumulating thousands of obsolete implementation plans that future agents mistake for requirements.

## Acceptance, traceability, and quality requirements

Acceptance is the part of current agentic-development practice where I think the empirical signal is clearest.

### Acceptance should be multi-dimensional

For detailed work, I would require at least three distinct acceptance classes:

```text
CONFORMANCE
Does the new intended behavior work?

PRESERVATION
Did behaviors outside the intended change remain valid?

QUALITY / CONSTRAINT
Does the result satisfy performance, security, compatibility,
architecture, accessibility, etc.?
```

This corresponds closely to FeatureBench's fail-to-pass versus pass-to-pass methodology and REAgent's separately generated reproduction and regression tests. citeturn18view2turn18view3

TDAD provides evidence that preservation cannot simply be “run whatever tests the agent happens to think of.” Graph-derived impact information reduced regressions substantially compared with both vanilla operation and procedural TDD prompting in its experiments. citeturn20view0

So each lower-level specification should have explicit links such as:

```yaml
acceptance:
  conformance:
    - AT-371-001
    - AT-371-002

  preservation:
    - RT-payment-existing-*
    - RT-checkout-*

  quality:
    - PERF-371
    - SEC-371
```

### Tests should verify the specification, not secretly extend it

This sounds banal, but it is currently an important agent-evaluation failure mode.

SWE-Bench ProMax's curation process explicitly removes tests that are too narrow and reject valid solutions, as well as tests that are too broad because they enforce **unstated requirements**. Its issue descriptions are rewritten to be precise enough that the evaluation suite can legitimately judge implementations against them. citeturn21search6

That leads to a rule I would enforce mechanically:

> **Every normative assertion in an acceptance test must trace to a requirement or declared inherited constraint.**

For example, this is bad:

```text
REQ:
  Return all matching records.

TEST:
  Assert matches are sorted lexicographically.
```

Unless ordering is specified elsewhere, the test has invented a requirement.

Conversely:

```text
REQ-371.7:
  Results MUST be ordered by creation timestamp ascending.

AT-371-04:
  verifies: REQ-371.7
```

is legitimate.

This is particularly valuable when agents generate the tests themselves: the trace link gives a separate review surface for “did the test hallucinate a constraint?”

### But tests must not become the sole specification

The contrarian version of the previous recommendation is equally important.

Executable checks are exceptionally useful, but a test suite is usually only a **sample of the behavioral space**. ProMax's need to curate over-constraining and under-constraining tests illustrates the problem, while SpecFirst still found meaningful specification omissions and inaccuracies despite downstream execution. citeturn21search6turn19view0

So I would treat:

```text
natural/structured requirement = semantic contract
test                           = executable proof obligation
test result                    = evidence
```

rather than:

```text
tests = requirements
```

CodeSpec's dual representation is conceptually attractive for exactly this reason: semantic intent produces executable checks, while the textual/structured representation remains available to the agent. citeturn15academia28

### Acceptance changes by abstraction level

I would use the following model:

| Artifact | Acceptance should mean |
|---|---|
| **Outcome** | Product/business evidence and guardrails |
| **Capability** | End-to-end scenarios and quality-budget coverage |
| **Deliverable requirement** | Executable functional, boundary, error, state, regression tests |
| **Architecture** | Conformance checks, allowed dependencies, interfaces, data-flow and structural invariants |
| **Low-level design** | Unit/component/interface/schema/migration/static checks |
| **UX** | Workflow execution + semantic interaction + accessibility + visual fidelity |

The lower half is strongly aligned with the execution-oriented findings from REAgent, FeatureBench, CodeSpec, and multimodal web-development work; the outcome/capability portion is a lifecycle synthesis because agent research has not experimentally validated a preferred strategy-level acceptance format. citeturn5view2turn18view2turn13view0turn11view2

### Non-functional requirements should not be a separate bottomless document

I would avoid a global `NFR.md` containing hundreds of generic statements that gets loaded for every task. The context-file experiments give good reason to suspect that irrelevant standing instructions can consume agent attention and cost. citeturn21search4

Instead, model quality requirements exactly like functional ones, but with scope and measurable obligations:

```yaml
id: QUALITY-LAT-7
type: quality_requirement
quality: performance

scope:
  applies_to:
    - CAP-37
    - REQ-371

measure:
  metric: checkout_request_latency
  statistic: p95
  workload: 500 requests/sec
  environment: production-equivalent

target:
  maximum: 400ms

acceptance:
  - PERF-371-01
```

For reliability:

```yaml
measure:
  metric: successful_request_ratio
  window: rolling_30d
target:
  minimum: 99.95%
```

For compatibility:

```yaml
supported_versions:
  browser:
    - ...
  API:
    - ...
```

This matters because terms such as “fast,” “secure,” “scalable,” and “robust” give an agent very little executable information. ProjDevBench's project-level evaluation explicitly combines execution testing with checking declared constraints because functional tests alone do not cover all requirements, including resource and specification constraints. citeturn1view1

I would divide NFRs into:

**Global policy/invariant requirements**, such as organizational security rules or compatibility policy, stored once and inherited by scope.

**Allocated quality requirements**, such as the actual latency, capacity, reliability, safety, accessibility, or resource budget applicable to a capability or deliverable.

Only the applicable closure gets put into a task context.

### Traceability should survive all the way to evidence

I would want the system to answer queries like these without using an LLM to guess:

```text
Why does this line/component exist?
Which requirements would be endangered if this API changes?
Which tests prove REQ-371?
Which requirement justifies AT-371-7's assertion?
Which architecture decisions are driven by QUALITY-SEC-4?
Which deliverables consume CAP-37?
Which accepted requirements have no tests?
Which tests no longer trace to an active requirement?
Which architecture components realize no active requirement?
```

Repo0 directly maintains requirement-to-component alignment, while CodeSpec maintains requirement-to-functional-chain evidence; Bosch explicitly builds intermediate artifacts to preserve the relationship from system-level requirement through test purpose into test specification. citeturn17view1turn15academia28turn21search3

That means I would put trace identifiers **inside executable artifacts**, not merely in Jira links:

```python
def test_cancel_before_capture():
    """
    verifies: REQ-371.4
    scenario: SCENARIO-371-CANCEL
    """
```

and, where practical:

```text
component: PaymentCancellationHandler
realizes:
  - REQ-371.4
  - REQ-371.5
conforms-to:
  - ARCH-42.INVARIANT-3
```

The exact syntax does not matter nearly as much as having a mechanically queryable relation.

## Architecture, low-level design, and UI/UX

### Architecture belongs after requirement semantics but before irreversible implementation choices

I would resist both common extremes:

```text
Extreme A:
"The agent has the requirements; let it discover the architecture."

Extreme B:
"Finalize the entire architecture before an agent writes anything."
```

Current evidence favors an intermediate position.

CodeSpec shows benefit from an explicit architecture specification during feature implementation in existing systems. citeturn13view0 Repo0 shows benefit from explicit architecture during greenfield generation, but also shows that allowing that architecture to evolve is better than treating the first design as fixed. citeturn18view0

So the sequence I would encode is:

```text
validated behavior
       │
       ▼
architecture drivers
       │
       ▼
candidate realization
       │
       ▼
architecture checks
       │
       ▼
implementation evidence
       │
       ├──── architecture still sound ───► continue
       │
       └──── architectural contradiction ► revise architecture
```

That is closer to continuous design than to Big Design Up Front.

### Architecture should describe invariants, not merely diagrams

An architecture artifact intended for agents should contain things the implementation can violate.

For example:

```yaml
invariants:
  - id: INV-42-1
    statement: Domain layer must not import payment-provider adapters.
    check: architecture_test/domain_dependencies

  - id: INV-42-2
    statement: Payment transitions are persisted before outbound event emission.
    check: integration/payment_transition_order

  - id: INV-42-3
    statement: All provider integrations implement PaymentProviderPort.
    check: static/interface_conformance
```

This is closely aligned with CodeSpec's architecture specification, which evaluates functional units, architectural relationships, and data flows rather than simply giving the model prose describing the repository. citeturn12view0turn15academia28

Architecture Decision Records remain useful, but I would distinguish:

```text
ADR = why a choice was made
architecture spec = what must remain true
architecture checks = executable evidence that it remains true
```

The latter two are more directly actionable for an agent.

### Low-level design should be generated late

Low-level design is where I would intentionally favor agent generation over manually curated permanent specifications, except in high-risk domains.

The plan should be derived from:

```text
target requirements
+ applicable architecture
+ repository evidence
+ test impact
```

and should contain concrete files, interfaces, data migrations, operational rollout, feature flags, observability, and validation commands.

SWE-Bench Mobile is instructive here. Its 50 industrial iOS tasks provide agents with production PRDs, Figma assets, existing code, and hundreds of human-verified tests, yet the best reported task-level result is only 12%; observed failures include omitted feature-flag handling, missing data models, and incomplete coverage of affected files. citeturn10view0

That benchmark does **not** isolate the causal effect of PRDs or Figma. What it does show is that realistic delivery intent contains operational and structural information beyond happy-path functional behavior.

Consequently, rollout is part of detailed design:

```text
feature flag
configuration
migration
backward compatibility
telemetry
rollback
```

not post-coding administrivia.

### UI/UX deserves a separate semantic artifact

I would not encode UX exclusively in either prose requirements or Figma.

VISTA performed controlled experiments with combinations of textual instruction, screenshots, Figma structure, fixed versus flexible implementation stacks. Screenshots substantially improved localization of the relevant visual regions, and Figma structure further improved grounding in several conditions, but neither automatically translated into equivalent end-to-end functional gains; constraining the implementation stack could also offset some benefit. citeturn11view2turn11view3turn11view4

That tells me a UI feature should have at least three representations:

```text
SEMANTIC INTENT
What interaction/state is required?

VISUAL REFERENCE
What should it look like?

EXECUTABLE WORKFLOW
What can a user actually do?
```

I would therefore use an artifact like:

```yaml
id: UX-371
type: ux_spec

supports:
  - REQ-371

journey:
states:
  - id: normal
  - id: loading
  - id: validation_error
  - id: provider_error
  - id: success

screens:
  - design_ref: Figma/...
    semantic_components:
      - payment_method_selector
      - submit_button
      - inline_error

interactions:
  - trigger:
    state_before:
    expected_state_after:
    side_effect:

content_requirements:
responsive_requirements:
accessibility_requirements:

visual_references:
  - screenshot:
  - figma:

acceptance:
  workflow_tests:
  accessibility_tests:
  visual_regression:
```

Current multimodal benchmarks support keeping these dimensions separate. Vision2Web evaluates increasingly complex tasks using visual prototypes, GUI workflows, and visual-fidelity measures, while SWE-bench Multimodal contains real software issues where images/screenshots carry requirement information and some tasks use pixel-level visual checks. citeturn10view1turn10view3

The practical consequence is:

> **A screenshot is evidence of desired appearance; it is not a sufficient UI requirement.**

Likewise:

> **A DOM/workflow test is evidence of interaction correctness; it is not a sufficient visual requirement.**

You want both.

## Practical template skeletons and adoption strategy

If I were constructing your corpus today, I would not start by designing six perfect Markdown templates. I would first define a small canonical semantic model and then let Markdown, YAML, a requirements database, Jira, GitHub, and agent prompts become different *views* over that model.

### A common envelope

Every artifact should share roughly this metadata:

```yaml
id:
type:
title:

status:
  # proposed | clarified | validated | implemented | verified | superseded

parents:
depends_on:

provenance:
  class:
  sources:
  confidence:

scope:

assumptions:
open_questions:

links:
  refines:
  realized_by:
  verifies:
  evidenced_by:
  supersedes:

revision:
```

The exact serialization is not empirically demonstrated to matter. In fact, SpecFirst provides modest evidence that semantic structure matters more than elaborate notation: its simple sectioned format did slightly better than a more formal OpenSpec treatment. citeturn19view1

So YAML front matter plus Markdown is perfectly reasonable as an authoring surface, provided IDs and relationships are actually machine-readable.

### The semantic template family I would pilot

I would begin with this corpus:

| Artifact | Mandatory semantic core | Typical producer |
|---|---|---|
| `OUTCOME` | problem, actors, desired outcome, success/guardrail evidence, scope | human + product agent |
| `CAPABILITY` | coherent capability, journeys/scenarios, scope, allocated qualities, children | human + requirements agent |
| `REQUIREMENT` | behavior, preconditions, inputs/outputs, states/errors/boundaries, examples, preservation, acceptance links | requirements/spec agent + human |
| `QUALITY` | scoped measurable constraint + verification method | human/domain agent |
| `UX_SPEC` | journey/states/interactions + visual refs + UX acceptance | designer + UX agent |
| `ARCHITECTURE` | drivers, components/responsibilities, interfaces/data flow, invariants, realization links, conformance | architecture agent + architect |
| `PLAN` | concrete changes, sequence, rollout, observability, impact/test map | implementation agent |
| `ACCEPTANCE` | assertion, requirement source, executable mechanism, result | spec/test agent |
| `EVIDENCE` | test/run/check result with version and environment | pipeline |

This taxonomy is my synthesis. Its separation of requirements from architecture and executable behavior is supported by CodeSpec and Repo0; the detailed behavioral content follows REAgent and SpecFirst; preservation follows FeatureBench/TDAD; UI separation follows multimodal benchmark evidence. citeturn18view3turn19view4turn13view0turn18view0turn18view2turn20view0turn11view2

### The actual agent input should be a compiled “work contract”

For a coding run, I would compile those artifacts into something considerably smaller:

```yaml
work_contract:
  target:
    requirement_ids:
      - REQ-371

  intent:
    outcome_summary:
    capability_summary:

  required_behavior:
    ...

  examples:
    ...

  preservation:
    ...

  constraints:
    applicable_quality:
    applicable_policy:

  ux:
    relevant_states:
    relevant_design_refs:

  architecture:
    components:
    interfaces:
    invariants:

  acceptance:
    functional:
    regression:
    quality:
    ux:
    architecture:

  repository_evidence:
    likely_affected_surface:
    relevant_existing_tests:

  unresolved:
    blocking_questions:
```

I would call this an **execution contract**, not a specification. It is a projection of the authoritative corpus for one run.

The selective-context rationale is among the more robust cross-study themes: generated general repository context can impose measurable overhead without improving results, graph-derived relevant context can reduce regressions, and evidence-grounded requirement/architecture context materially affects CodeSpec and Repo0 results. citeturn21search4turn20view0turn13view0turn18view0

### I would make specification depth risk-adaptive

A five-minute local refactor should not require the same ceremony as a payment subsystem.

I would establish three modes:

| Work characteristic | Required corpus |
|---|---|
| **Local/simple** | requirement + examples + acceptance + preservation |
| **Cross-component** | above + architecture slice + quality allocation + impact analysis |
| **Long-horizon / architecture-significant** | full capability trace + explicit architecture realization + executable architecture/behavior specs + rollout/evidence |

The strongest justification is CodeSpec's observation that executable specifications distinguish themselves most clearly on longer, more coordination-heavy tasks rather than very simple ones. citeturn13view0

SpecFirst also reveals a real economic tradeoff: introducing the specification stage increased total inference cost by roughly **48–130%** across its tested models, despite improving correctness; one model saw lower implementation-stage cost, but the separate elicitation stage still added overall expense. citeturn19view1

So “specify everything maximally” is not supported.

### The pipeline I would actually build

At a high level:

```text
Human / Product Intent
        │
        ▼
┌─────────────────────┐
│ Intake Artifact     │  Preserve original wording/source
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Clarification       │  Identify missing/ambiguous behavior;
│ / Elicitation Agent │  record inferred vs stated information
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Requirement Graph   │  Outcome → Capability → Deliverable;
│                     │  functions + allocated qualities
└─────────┬───────────┘
          │
          ├──────────────► UX Spec / Prototype
          │
          ▼
┌─────────────────────┐
│ Acceptance Compiler │  behavior + preservation + quality
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Architecture Agent  │  requirement→component alignment,
│                     │  interfaces, flows, invariants
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Work-Contract       │  compile only relevant dependency
│ Compiler            │  closure into agent context
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Planning Agent      │  concrete change plan
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Implementation Agent│
└─────────┬───────────┘
          ▼
┌─────────────────────────────────────────┐
│ Verification                            │
│ behavior | regression | quality | UX   │
│ architecture | rollout                 │
└─────────┬───────────────────────────────┘
          │
          ├── implementation defect ──► repair
          │
          ├── plan defect ────────────► re-plan
          │
          ├── architecture defect ────► revise realization
          │
          └── requirement ambiguity ──► clarification
```

Separating elicitation from implementation is directly supported by SpecFirst; using executable feedback for requirements quality is supported by REAgent; maintaining separate behavior and architecture constraints is supported by CodeSpec; permitting realization to evolve while retaining requirement traceability is supported by Repo0. citeturn19view2turn5view2turn15academia28turn18view0

### What I would explicitly *not* adopt yet

I would **not** standardize your organization around a particular trendy Markdown SDD format on the theory that syntax itself improves agents. SpecFirst's small format experiment provides no evidence of a dramatic advantage for a formal OpenSpec-style structure over ordinary structured sections. citeturn19view1

I would **not** put generated repository summaries, architecture descriptions, style guides, testing procedures, and generic development philosophy into every agent's permanent context. Controlled context-file studies make that assumption questionable. citeturn21search0turn21search4

I would **not** use acceptance tests as hidden requirements. Expert curation work is explicitly having to remove tests that enforce unstated behavior. citeturn21search6

I would **not** embed proposed files/classes/solutions in authoritative product requirements. REAgent finds that such information is useful to the implementing agent, but CodeSpec and Repo0 give good reasons to preserve a distinction between requirement semantics and realization. citeturn18view3turn15academia28turn17view1

I would **not** freeze a low-level architecture solely because an architecture agent generated a persuasive diagram. Repo0's current evidence points in the opposite direction for greenfield work. citeturn18view0

And I would **not** interpret today's published effect sizes as settled engineering science. Most of the most relevant controlled results—REAgent, CodeSpec, SpecFirst, Repo0, SWE-RPG, and the `AGENTS.md` experiments—are 2026 publications or preprints, several only weeks old and Repo0 only one day old as of August 21, 2026. citeturn15search8turn15academia28turn15search3turn17view1turn21search1turn21search0

### My confidence-weighted recommendation

| Recommendation | Confidence | Why |
|---|---|---|
| Have a distinct clarification/specification phase for ambiguous or substantial work | **Moderate-high** | SpecFirst direct experiment; REAgent corroboration. citeturn19view2turn5view2 |
| Use structured semantic fields rather than unstructured prose | **Moderate** | REAgent direct ablation; SpecFirst format experiment. citeturn5view2turn19view1 |
| Prefer light semantic structure over elaborate requirements syntax | **Moderate-low** | SpecFirst's 50-task format experiment only. citeturn19view1 |
| Make acceptance executable wherever practical | **Moderate-high** | REAgent and CodeSpec controlled ablations. citeturn5view2turn13view0 |
| Explicitly separate new behavior from regression/preservation | **Moderate** | FeatureBench evaluation design plus TDAD intervention. citeturn18view2turn20view0 |
| Separate requirements from architecture while maintaining trace links | **Moderate** | CodeSpec direct ablation; Repo0 fresh corroboration. citeturn13view0turn18view0 |
| Let architecture evolve rather than treating initial design as final | **Low-moderate** | Strong Repo0 result, but one extremely recent study. citeturn18view0 |
| Retrieve only relevant corpus slices for a coding run | **Moderate** | AGENTS.md negative result, TDAD contextual intervention, CodeSpec evidence grounding. citeturn21search4turn20view0turn13view0 |
| Track provenance of inferred/derived requirements | **Moderate as design recommendation** | Strong diagnostic motivation, but exact metadata design untested. citeturn21search1turn19view0 |
| Represent UI as semantic behavior + visual reference + executable workflow | **Moderate** | Controlled VISTA results plus multiple multimodal benchmarks. citeturn11view2turn11view3turn10view1 |
| Use a particular vision/epic Markdown template | **Unknown** | I found essentially no direct agent-outcome experiment at this abstraction level. |

The key distinction, **Chief Bureaucracy Compiler**, is therefore between a *specification document* and a *specification system*. The evidence is increasingly favorable to the latter.

The most defensible design today is a corpus in which **intent is stable, behavior is explicit, ambiguity is visible, requirements and realization are separated, examples are concrete, acceptance obligations are executable, architecture constraints are checkable, traceability is mechanical, and agents receive only the relevant closure of that graph for the job at hand**. That synthesis is supported independently by the requirement, specification-elicitation, executable-specification, architecture, regression-testing, context-management, and multimodal studies above, even though no single experiment has yet tested the entire proposed PDLC architecture end to end. citeturn5view2turn19view2turn13view0turn18view0turn20view0turn21search4turn11view2