# Comprehensive Audit of Agent-Facing Content — Design

**Bead**: `agents-config-acmh`
**Status**: Spec — pending adversarial review and finalize
**Date**: 2026-05-09
**Authors**: Scott Hamilton (architect) + Claude Opus 4.7 (1M context, brainstorm partner)

**Related beads**:
- Absorbed: `agents-config-xacz` (audit bd command sequences) — closed; scope folded into this audit
- Blocks: `agents-config-2gzy` (refactor skill helper scripts to named parameters) — depends on script-interface findings from this audit
- Adjacent: `agents-config-wmjy` (brainstorm-bead §3 inbound dep retargeting) — chosen script-extraction implementation; covers Tier 3 dep-migration extraction
- New follow-ups (filed at acmh close): one per category with Tier 2 findings + one Tier 3 bd-sequences bead (children-check + label-copy-filter)

---

## 1. Background and Motivation

This project is a versioned collection of agents, skills, commands, formulas, and rules for AI coding assistants (Claude Code, Codex, Gemini, OpenCode). Over time, content has accumulated organically. Three classes of drift have emerged:

1. **Quality drift**: skill descriptions that no longer enable correct selection; agent definitions missing examples; rules that have grown to embed methodology better suited to skills.
2. **Coherence drift**: cross-content-type boundaries blur — rules duplicate skill content; commands re-implement what skills already provide; agents reference skills they no longer use.
3. **Namespace drift**: bead-tracker concepts (bd commands, bead IDs, bead lifecycle terminology) have leaked into shared content under `src/user/.agents/` that should remain tool-agnostic. The plugin namespace `src/plugins/beads/` is the intended home for bead-specific content.

The brainstorm-bead formula 7bk.27 was a precursor: it extracted bd command sequences (claim-walk, close-walk, finalize-create-impl-bead) from inline LLM-prose into shell helpers. That work covered Tier 1+2 of the bd-sequence extraction; Tier 3 (children-check, dep-migration, label-copy-filter) was explicitly out of scope and is folded into this audit.

This bead conducts a comprehensive audit of all agent-facing content, produces structured findings with recommendations, applies low-risk mechanical fixes inline, and defers higher-risk rewrites to per-category follow-up beads.

## 2. Vision Alignment

This audit must serve the project vision documented in AGENTS.md:

> **Vision** — Make AI software development reliably autonomous. Concentrate human time *upstream* (brainstorming, design, judgment) and at thin verification gates; have agents execute implementation and machine-verifiable QA in the background.
>
> **Target operating ratio (aspirational)** — roughly **85% / 5% / 10%** of human time on brainstorming / troubleshooting escalations / validation testing.

Every finding produced by this audit must articulate, in one sentence, **how its recommendation advances** the 85/5/10 ratio or one of the five load-bearing commitments. Findings that cannot make this case are demoted or dropped at the Phase 3 aggregation step.

The implicit premise: a finding that is worth surfacing is, by definition, regressing the vision (even if only as drag/noise blocking the path). The auditor does not need to argue the regression. The auditor must argue the advance.

### Vision-advancement rubric (anti-filler discriminator)

To prevent vacuous "removes noise" filler, every finding's `Vision-advancement` field must declare its tier:

| Tier | Standard | Example |
|------|----------|---------|
| **A** | Names a specific load-bearing commitment from AGENTS.md and explains the mechanism by which the recommendation advances it | "Advances commitment #2 (good at saying 'no, not ready'): a brainstorm-readiness gate gains a probe in this skill that detects under-specified ACs before TDD red-tests, preventing implement loops on incomplete specs." |
| **B** | Ties to a vision gap labeled `vision-85-5-10` (named work-in-progress in AGENTS.md "Current state") | "Advances the brainstorm-readiness gate gap: this rule's normative phrasing makes the gate enforceable instead of advisory." |
| **C** | Generic "reduces noise / improves clarity" with no specific commitment or gap named | "Removes filler that distracts agents." |

Phase 3 acceptance rule: at most **30%** of *accepted* findings (after MERGED/DROPPED resolution) may be tier C. If the C share exceeds 30%, the aggregator must demote the lowest-severity tier-C findings to DROPPED until the threshold is met. This prevents the field from collapsing into a per-finding tax.

## 3. Audit Dimensions

Every file in scope is evaluated against these dimensions:

| Dimension | What to check |
|-----------|---------------|
| Frontmatter quality | Required fields present, values valid, no schema violations |
| Clarity | Direct, actionable, no fluff or filler preamble |
| Coherence | No conflicting guidance; consistent terminology |
| Separation of concerns | Each file has one job; no mixed concerns |
| Right tool for the job | Skill ↔ rule ↔ command ↔ agent ↔ shell script / helper code — is this content type the right vehicle for this guidance, or should it be reclassified? |
| Noise detection | Content that adds weight without serving execution or judgment |
| Progressive disclosure | Does the content respect the on-demand loading model? Should some content move to referenced files? |
| Bead-concept hygiene | Shared (`src/user/`) content must not leak bd commands, bead IDs, or bead-tracker terminology |
| Cross-reference hygiene | Cross-references only where a concrete dependency exists |
| Helper script candidacy | Inline deterministic shell sequences in prose → flag for extraction to helper script |

### Acid test by content type

The acid test is tiered to match how each content type is consumed:

| Content type | Acid test |
|--------------|-----------|
| Formulas | "Will the agent need this to execute its task reliably?" — formula step prose is copied into bead descriptions and read at execution time. **Strict**. |
| Commands | Same as formulas — commands are short, focused, lean. **Strict**. |
| Scripts | Interface quality (named params, help on misuse, exit codes); code reads from acceptance criteria. **Strict**. |
| Skills | "Does this serve the agent's judgment OR execution?" — skills are reference material. **Looser**, but apply progressive-disclosure: as-needed content moves to `references/` subdirs. |
| Agents | "Does this define the role boundary clearly?" — agents are persona + scope + tool contract. **Looser**, evaluate role coherence. |
| Rules | "Is this normative and always-applicable?" — rules are always-loaded constraints. Anything advisory belongs in skills. |
| Templates (AGENTS.md, INSTRUCTIONS.md) | Entry-point clarity; non-conflicting layered guidance. |

## 4. Audit Scope

The following content is in scope. Each row maps to one Phase 1 subagent.

| Subagent | Scope |
|----------|-------|
| audit-skills | `src/user/.agents/skills/*/SKILL.md` and supporting files; `src/plugins/beads/.agents/skills/*/SKILL.md` |
| audit-agents | `src/user/.agents/agents/*.md`; `src/plugins/beads/.agents/agents/*.md` |
| audit-commands | `src/user/.claude/commands/*.md` |
| audit-rules | `src/user/.claude/rules/*.md`; `src/plugins/beads/.claude/rules/*.md` |
| audit-formulas | `src/plugins/beads/.beads/formulas/*.formula.toml` — step prose noise audit |
| audit-scripts | `src/plugins/beads/.beads/scripts/*.sh` — interface quality (feeds 2gzy) |
| audit-templates | `src/user/.agents/INSTRUCTIONS.md.template`; `AGENTS.md.template` (all platforms); `settings.json.template` |

### Tier 3 bd-sequence absorption (from xacz)

In addition to the dimensions above, the audit identifies remaining inline bd command sequences not extracted by 7bk.27: `children-check`, `label-copy-filter`. (Dep-migration extraction is on `wmjy`'s plate.) These surface as findings flagged for the Tier 3 follow-up bead.

## 5. Architecture

A three-phase pipeline. Multi-dimensional review by design — each phase compensates for the limitations of the prior phase.

```
┌─────────────────────────────────────────────────────────────────┐
│ Phase 1 — Parallel category audits                              │
│   7 × Opus 1M / xhigh effort, dispatched in parallel            │
│   Each: vision + relevant primer + file scope → findings file   │
│   Output: docs/audits/phase1/<category>.md                      │
└────────────────────────────┬────────────────────────────────────┘
                             ▼ (Phase 1 outputs verified)
┌─────────────────────────────────────────────────────────────────┐
│ Phase 2 — Adversarial use-case reviews                          │
│   6 × Codex GPT-5.5, dispatched in parallel                     │
│   Each: vision + all primers + all Phase 1 outputs              │
│   Each reviews findings through one cross-cutting use case      │
│   Output: docs/audits/phase2/<use-case>.md                      │
└────────────────────────────┬────────────────────────────────────┘
                             ▼ (Phase 2 outputs verified)
┌─────────────────────────────────────────────────────────────────┐
│ Phase 3 — Aggregation and conflict resolution                   │
│   1 × Sonnet 1M (serial; needs full context)                    │
│   Inputs: vision + all primers + Phase 1 + Phase 2              │
│   Resolves conflicts with explicit decision rationale           │
│   Output: by-category/, by-file/, decisions.md, REMEDIATION_PLAN│
└────────────────────────────┬────────────────────────────────────┘
                             ▼
                    USER REVIEW GATE
                             ▼
                    Tier 1 inline fixes
                             ▼
                    Follow-up beads filed
                             ▼
                    Completion gate + delivery
```

### Why three dimensions

- **By content type** (Phase 1): each category specialist applies the right acid test for that content type
- **By use case** (Phase 2): cross-cutting adversarial perspective catches inconsistencies category specialists miss
- **By aggregator** (Phase 3): when category and use-case views disagree, an aggregator with the full picture decides

The cost is more tokens. The gain is fewer false-positive findings, fewer missed cross-category patterns, and explicit conflict-resolution rationale that the implementer of the remediation can refer back to.

## 6. Subagent Dispatch Contract

Every subagent in Phases 1, 2, and 3 receives a dispatch prompt structured as:

```
=== PROJECT CONTEXT ===
[Vision & Mission section from AGENTS.md, extracted by section header
 (from "## Vision & Mission" through the end of "## Implications for
 agents working in *this* repo"), injected verbatim by the orchestrator
 at dispatch time. Line numbers MUST NOT be hard-coded; the orchestrator
 extracts by header so the boundaries survive AGENTS.md edits.]

=== AUDIT INPUT SHA ===
[The full git SHA the orchestrator pinned at Step 0.5. All file paths
 in the brief resolve against this SHA. If the worktree HEAD has moved
 by dispatch time, the orchestrator MUST refuse to dispatch and surface.]

=== ROLE PRIMERS ===
[Read these files before beginning:
  Phase 1 category auditors:
    - docs/primers/<CATEGORY>_PRIMER.md (their primary category)
    - Adjacent primers where the category boundary matters
      (e.g. audit-rules also reads SKILLS_PRIMER.md for the rules-vs-skills line;
       audit-agents also reads SKILLS_PRIMER.md for skills-listed-in-frontmatter)
  Phase 2 use-case reviewers: all 5 primers + all 7 Phase 1 outputs
  Phase 3 aggregator: all 5 primers + all 7 Phase 1 + all 6 Phase 2 outputs]

=== TASK BRIEF ===
- Files in scope (RESOLVED exact paths — the orchestrator enumerates the
  glob patterns from §4 against the pinned SHA before dispatch and injects
  the concrete file list here; auditors do NOT re-resolve globs)
- For audit-skills specifically: the resolved list distinguishes
  primary files (SKILL.md) from supporting files (sibling .md references,
  scripts/). Audit dimensions in §3 apply to primary files; supporting
  files are catalogued (path + purpose) only — internal code is audited
  by audit-scripts.
- For Phase 2 reviewers: the categories-touched list from §11 column 3.
  The reviewer MUST restrict counter-findings to those categories;
  observations outside scope go in an "Out of scope" section, advisory
  only. Phase 2 reviewers do NOT see each other's outputs — inter-reviewer
  conflicts are resolved by Phase 3.
- Audit dimensions (from §3)
- Output file path
- Finding schema (from §8)
- Constraints:
  * NO source-file modifications during audit (Phase 1, 2, 3 are read-only on source)
  * Every finding must include a non-empty Vision-advancement field with a
    declared tier (A, B, or C — see §2 rubric)
  * Output file must be valid markdown with the schema fields populated
  * Zero-findings result is a valid output: write a "Findings: none" block
    with one paragraph summarizing what was reviewed and why nothing was
    flagged. Do NOT invent findings to fill the file.
- Reporting format expectations
```

Vision content is injected fresh from the live AGENTS.md at dispatch time — there is no static copy in the primers directory. If AGENTS.md updates between phases, later phases see the newer content. Section-header extraction (not line numbers) is the canonical anchor.

## 7. Outputs Structure

```
docs/audits/
├── phase1/
│   ├── skills.md
│   ├── agents.md
│   ├── commands.md
│   ├── rules.md
│   ├── formulas.md
│   ├── scripts.md
│   └── templates.md
├── phase2/
│   ├── formula-step-execution.md
│   ├── constraint-aware-execution.md
│   ├── full-bead-lifecycle.md
│   ├── quality-gate-and-delivery.md
│   ├── multi-agent-dispatch.md
│   └── escalation-edge-recovery.md
└── phase3/
    ├── by-category/
    │   ├── skills.md
    │   ├── agents.md
    │   └── ...
    ├── by-file/
    │   └── <file-slug>.md          # one per source file with ≥1 finding
    ├── decisions.md                 # conflict-resolution log
    └── REMEDIATION_PLAN.md          # the actionable handoff: Tier 1 inline + Tier 2 deferred
```

## 8. Finding Schema

Every finding in every output file uses this structure:

```
F<n>: <one-line title>
  File: <path>:<lines>
  Category: skill | agent | command | rule | formula | script | template
  Severity: Critical | High | Medium | Low
  Tier: 1 (mechanical, inline) | 2 (design, deferred)
  Issue: <what's wrong>
  Recommendation: <what to do>
  Vision-advancement-tier: A | B | C    (per §2 rubric)
  Vision-advancement: <one sentence — MANDATORY non-empty.
                      Tier A names a load-bearing commitment + mechanism;
                      Tier B names a `vision-85-5-10`-labeled gap;
                      Tier C is generic "reduces noise / improves clarity".>
  Related: F<n>, F<n>
```

Phase 2 findings additionally include:

```
  Phase-1-source: F<n>           (which Phase 1 finding this challenges, if any)
  Verdict: AGREE | DISAGREE | PARTIAL
  Counter-recommendation: ...    (when DISAGREE or PARTIAL)
```

Phase 3 findings additionally include:

```
  Resolution: ACCEPTED | MERGED | DROPPED | DEFERRED
  Rationale: <one sentence: why the aggregator chose this disposition>
  Sources: phase1/<file>:F<n>, phase2/<file>:F<n>
```

## 9. Severity Tiers

| Severity | Definition | Examples |
|----------|------------|----------|
| **Critical** | Active hazard | Conflicting rules; security leak; broken cross-references blocking agent execution; bd commands in `src/user/` shared content (regresses multi-tool portability) |
| **High** | Materially degrades agent behavior or breaks a load-bearing commitment | Missing skill trigger boundary; wrong content type (rule that should be skill); orchestrator→subagent contract gap |
| **Medium** | Adds weight without active harm; agent has to spend judgment cycles deciding what to ignore | Terminology drift; missing best-practice elements (no examples in agent description); style inconsistency |
| **Low** | Polish | Typos, minor wording, optional metadata |

## 10. Tier 1 (Inline) vs Tier 2 (Deferred)

The remediation tier determines what acmh fixes inline versus what defers to a follow-up bead.

### Tier 1 — Mechanical, inline in acmh's PR

Tier 1 is restricted to edits that a regex or trivial AST transform could perform without semantic judgment:

- Frontmatter field corrections (typos in field names, missing required fields where the value is unambiguous, name-validation violations per Anthropic schema)
- Pure typo fixes (single-word misspellings, with no surrounding-sentence rewrite needed)
- Forward-slash conversion for Windows-style paths
- Dead-reference deletion: cross-references to files/skills/agents that demonstrably do not exist (no judgment about whether the reference *should* exist)
- Explicit-pattern-match removals where the Phase 3 finding provides the exact regex or literal string AND the surrounding sentence still parses after removal (the finding must include a verified before/after snippet)

### Tier 2 — Design required, deferred to follow-up beads

- Skill body restructuring (which content moves to `references/`, what stays)
- Formula step prose rewrites (requires understanding the step's role)
- Agent body simplification (requires reading role boundaries)
- Rule splitting (policy boundary judgment)
- Right-tool reclassification (skill↔rule↔command↔agent↔shell script)
- Terminology unification across files (requires choosing the canonical term)
- Helper-script extraction from prose-prescribed deterministic logic (parameter design)
- Tier 3 bd-sequence extractions (children-check, label-copy-filter)
- Bead-ID and bd-command removal from shared content (often requires deleting the surrounding sentence, not a token — judgment call)
- TOC additions to >100-line reference files (requires choosing section boundaries)
- Recurring-noise-pattern removal where the pattern requires interpretation
- Anything where two reasonable engineers would land on different fixes

**The line**: Tier 1 = a regex or unambiguous edit with a verified before/after snippet on file. Tier 2 = anything requiring judgment.

**Default-to-Tier-2 rule**: If a Phase 1 auditor is uncertain whether a finding qualifies for Tier 1, classify as Tier 2. Phase 3 aggregator may **promote** a Tier 2 finding to Tier 1 only when the finding includes an explicit pattern match + before/after snippet; the aggregator may **never demote** a Tier 1 to Tier 2 silently — demotion requires a `decisions.md` entry with rationale. This asymmetry biases the system toward fewer false Tier 1s.

If a Tier 1 fix turns out to break `install.sh --dry-run`, the orchestrator reverts and demotes to Tier 2 (recorded in `decisions.md`).

## 11. Cross-Cutting Use Cases (Phase 2)

The six use cases are deliberately uneven — each touches the categories it actually exercises in real agent workflows. None is required to touch all categories. Use case 5 explicitly bundles three sub-questions and is therefore expected to produce a deeper output than the others; this asymmetry is accepted by design rather than split.

Phase 2 reviewers run in parallel and do **not** see each other's outputs — inter-reviewer disagreements are surfaced and resolved by Phase 3 against `decisions.md`. Each reviewer's brief includes the categories-touched list from the table below; counter-findings outside that list go into an "Out of scope" advisory section, not into the main findings.

| # | Use Case | Categories touched | Adversarial lens |
|---|----------|-------------------|------------------|
| 1 | Formula → step bead execution: agent receives a step bead copied from a formula, reads it, acts | Formulas, rules/beads, scripts | Do noise-removal recommendations correctly identify what's needed at execution time? |
| 2 | Constraint-aware execution: always-loaded rules and instructions actively constraining behavior | Rules, INSTRUCTIONS.md template | Do recommendations reduce clarity, introduce gaps, or create contradictions? |
| 3 | Full bead lifecycle: create → brainstorm → implement → deliver → merge | Skills (lifecycle), all 4 formulas, scripts, rules | Do bead-concept hygiene recommendations create gaps in cross-cutting guidance? |
| 4 | Quality gate + delivery pipeline: completion gate through PR merge, including review-feedback loop | Skills (verify, simplify, wait-for-pr), agents (quality-reviewer, bead-verifier), rules (completion-gate, delivery) | Do cross-reference hygiene findings preserve genuine skill-to-skill dependencies? |
| 5 | Multi-agent dispatch: orchestrator dispatching parallel subagents — agent role + tools + skills + dispatch prompt + environment access coherence | Skills (dispatching, implement-bead), agents, rules (delegation, subagents) | (a) Does the agent's role + tools + skills + prompt form a coherent package? (b) Sufficient context, env access, and tools to execute reliably? (c) Do audit findings create mismatches in the orchestrator→subagent contract? |
| 6 | Escalation + edge-case recovery: agent hits unexpected state (ambiguous molecule, blocked bead, failed build) | Skills (start-bead, implement-bead, bugfix), formulas, rules | Do noise-removal recommendations strip escalation paths agents need? |

## 12. Acceptance Criteria

| # | Criterion |
|---|-----------|
| 1 | All 7 Phase 1 category audit files exist at `docs/audits/phase1/<category>.md` |
| 2 | All 6 Phase 2 use-case adversarial files exist at `docs/audits/phase2/<use-case-slug>.md` |
| 3 | Phase 3 outputs complete: `by-category/<category>.md` per category, `by-file/<file-slug>.md` per source file with ≥1 finding, `decisions.md`, `REMEDIATION_PLAN.md` |
| 4 | Every finding has all schema fields populated, including non-empty `Vision-advancement` |
| 5 | User has reviewed `REMEDIATION_PLAN.md` and approved the Tier 1 fix list — evidenced by a comment on `agents-config-acmh` recording the approval and the worktree HEAD SHA at approval time, OR an explicit "APPROVED <SHA>" marker line at the top of `REMEDIATION_PLAN.md` |
| 6 | All approved Tier 1 fixes applied to source files |
| 7 | `scripts/install.sh --dry-run` passes after Tier 1 fixes |
| 8 | One follow-up bead filed per category that has ≥1 Tier 2 finding (categories with zero Tier 2 findings produce no bead — this is acceptable; the absence is recorded in `REMEDIATION_PLAN.md`) |
| 9 | Tier 3 bd-sequences follow-up bead filed (children-check + label-copy-filter) |
| 10 | Comments posted on `agents-config-2gzy` (script-interface findings) and `agents-config-wmjy` (dep-migration extraction confirmation) |
| 11 | AGENTS.md updated only in non-vision sections if audit surfaces findings against them; vision-section findings produce recommendations only and are routed to a follow-up bead (per §16) |
| 12 | Completion gate passed: quality-reviewer → simplify → verify-checklist (all pass with evidence) |
| 13 | PR created via `finishing-a-development-branch` skill; summary links to `REMEDIATION_PLAN.md` |

## 13. Execution Sequence

### Step 0 — Preflight
- Verify all 5 primers exist at `docs/primers/` (SKILLS, AGENTS, COMMANDS, RULES, FORMULAS)
- Extract AGENTS.md vision section by header (`## Vision & Mission` through end of `## Implications for agents working in *this* repo`) into orchestrator context — line numbers MUST NOT be hard-coded
- Confirm bead `agents-config-acmh` is `in_progress` with no active molecule conflict
- Create worktree at `.claude/worktrees/acmh-comprehensive-audit`

### Step 0.5 — Pin audit-input SHA and resolve file scope
- Record the worktree HEAD SHA as `AUDIT_INPUT_SHA` (this anchors all Phase 1/2/3 dispatches; if the worktree HEAD moves before a phase dispatches, the orchestrator MUST refuse and surface)
- For each Phase 1 category, resolve the §4 glob patterns against `AUDIT_INPUT_SHA` to a concrete file list
- For audit-skills, partition the resolved list into primary files (`SKILL.md`) and supporting files (sibling `.md` references, `scripts/`)
- Persist the resolved file lists for each category (e.g. inline in the dispatch prompt; do NOT have subagents re-resolve)

### Step 1 — Phase 1 dispatch (parallel)
- Dispatch 7 Opus 1M / xhigh effort subagents in a single message
- Each gets: `AUDIT_INPUT_SHA` + vision context + relevant primer(s) + the RESOLVED file list from Step 0.5 + output path + finding schema + Vision-advancement rubric reference
- Subagents make NO source-file modifications; output only
- Per-phase max retry: 3 per subagent. After 3 failed attempts (crashed or unparseable output), the orchestrator surfaces to user with the failing brief; no further auto-redispatch.

### Step 2 — Phase 1 verification
- Confirm all 7 output files exist (a "Findings: none" file is a valid output and counts as exists)
- Spot-check schema compliance (every finding has all fields, including non-empty Vision-advancement and a declared tier A/B/C)
- Verify `AUDIT_INPUT_SHA` is still the worktree HEAD; if not, surface and pause
- If any subagent failed: re-dispatch up to the Step 1 retry cap (idempotent — outputs go to same path)
- Commit Phase 1 outputs

### Step 3 — Phase 2 dispatch (parallel)
- Dispatch 6 Codex subagents via the Claude Code Codex plugin (`codex-companion.mjs`, never the raw `codex` binary). Default model: `gpt-5.4` (per `codex-routing.md`: best fit for adversarial / cross-subsystem review). If a newer model becomes available and `codex-routing.md` is updated to list it, that becomes the default; the spec does not pin a future-tense version number.
- Each gets: `AUDIT_INPUT_SHA` + vision + all 5 primers + all 7 Phase 1 outputs + use-case brief + the categories-touched list from §11 + output path
- Each writes to its assigned `phase2/<use-case>.md`. Reviewers do not see each other's outputs by design.
- Per-phase max retry: 3 per subagent (same policy as Phase 1).

### Step 4 — Phase 2 verification
- Confirm all 6 output files exist; schema spot-check
- Commit Phase 2 outputs

### Step 5 — Phase 3 aggregation (serial)
- Dispatch 1 Sonnet 1M subagent
- Inputs: `AUDIT_INPUT_SHA` + vision + all 5 primers + all 7 Phase 1 + all 6 Phase 2 outputs
- Outputs: `by-category/`, `by-file/`, `decisions.md`, `REMEDIATION_PLAN.md`
- Conflict-resolution rule: aggregator decides AND states why; never "reviewer wins" silently
- Aggregator MUST enforce the Vision-advancement rubric (§2): if more than 30% of accepted findings carry tier C, demote the lowest-severity tier-C findings to DROPPED until the threshold is met (record each demotion in `decisions.md`)
- Verifiable check: every Phase 2 finding with `Verdict: DISAGREE` or `PARTIAL` must have a corresponding `decisions.md` entry with explicit Resolution + Rationale; missing entries are a verification failure that returns to Step 5 dispatch
- Commit Phase 3 outputs

### Step 6 — USER REVIEW GATE
- Orchestrator presents `REMEDIATION_PLAN.md`
- User can: approve, demote any Tier 1 finding to Tier 2 (recorded in `decisions.md`), drop findings, request schema fixes, or edit `REMEDIATION_PLAN.md` directly (post-approval, the edited file is canonical)
- Approval is evidenced per AC #5: comment on `agents-config-acmh` recording the approval and the worktree HEAD SHA, OR an "APPROVED <SHA>" marker line at the top of `REMEDIATION_PLAN.md`
- **Worktree-HEAD invariant**: the worktree HEAD SHA at approval MUST equal `AUDIT_INPUT_SHA`. If the user (or another agent) modified source files during the gate, the orchestrator detects the SHA drift and surfaces; user must explicitly say "proceed against new tree" (orchestrator records the drift in `decisions.md` and re-runs Phase 1+2 on the affected categories) or "re-audit" (full re-dispatch from Step 0.5)
- **No source files touched until user approves**

### Step 7 — Tier 1 application (serial by category)
- One Sonnet subagent per category with Tier 1 findings
- Each applies its category's mechanical fixes against the post-approval HEAD
- **Default policy**: serialize — orchestrator dispatches one category at a time and commits before the next is dispatched. Run `scripts/install.sh --dry-run` after each category's commit (per Step 8 verification cadence). This eliminates cross-category write races at the cost of wall-clock time.
- **Optional parallelization**: only when the orchestrator can prove the categories' file scopes are provably disjoint at this SHA (e.g. audit-skills touches only `src/user/.agents/skills/**` and audit-rules touches only `src/user/.claude/rules/**`); the proof must be recorded in the commit message.

### Step 8 — Tier 1 verification
- Run `scripts/install.sh --dry-run` after each category's commit (or once at the end if Step 7 was parallelized under provable disjointness)
- If failure: revert offending category's commit, demote affected findings to Tier 2 with rationale in `decisions.md`, update REMEDIATION_PLAN

### Step 9 — Follow-up bead filing
- One per category with ≥1 Tier 2 finding (skip empties)
- One Tier 3 bd-sequences bead (children-check + label-copy-filter)
- Each bead's description references its Phase 3 by-category file as the spec

### Step 10 — Adjacency notifications
- Comment on `agents-config-2gzy`: link to `phase3/by-category/scripts.md`
- Comment on `agents-config-wmjy`: confirm dep-migration extraction is its responsibility

### Step 11 — Completion gate (per `completion-gate.md` rule)
- `quality-reviewer` agent
- `simplify` skill
- `verify-checklist` skill
- Address all findings before proceeding

### Step 12 — Delivery (per `delivery.md` rule)
- `using-git-worktrees` (already done at Step 0)
- `finishing-a-development-branch` skill (PR created)
- `wait-for-pr-comments` skill (Copilot review handling)
- Pause at merge for explicit user authorization

## 14. Failure Modes and Contingencies

| Failure | Response |
|---------|----------|
| Phase 1 subagent crashes or returns malformed output | Re-dispatch with same prompt (idempotent — overwrites the file). Cap: 3 attempts per subagent; on cap, surface to user. |
| Phase 2 subagent disagrees with Phase 1 entirely | That's the design — Phase 3 aggregator resolves with `decisions.md` entry |
| Phase 1 or Phase 2 subagent legitimately finds nothing | Subagent writes a "Findings: none" file with one paragraph summarizing what was reviewed and why nothing was flagged. Phase 3 accepts this and notes it in `decisions.md`. Empty files are a valid output, NOT a re-dispatch trigger. |
| Phase 3 aggregator can't resolve a conflict from evidence | Flag in `decisions.md` as "needs human"; surface in REMEDIATION_PLAN for user review |
| Phase 3 finds tier-C share > 30% after first pass | Aggregator demotes lowest-severity tier-C findings to DROPPED until threshold is met (per §2 rubric). Each demotion recorded in `decisions.md`. |
| Tier 1 fix breaks `install.sh --dry-run` | Revert that category's commit; demote affected findings to Tier 2 with rationale in `decisions.md` |
| Source file modified by another agent during Phase 1/2 | Detected via `AUDIT_INPUT_SHA` mismatch; orchestrator surfaces and pauses. User must explicitly authorize re-running affected categories' Phase 1+2 against the new state, or restoring the SHA. |
| Source file modified during user-review gate | Same SHA-mismatch detection as above; orchestrator surfaces at approval time. User chooses "proceed against new tree" (re-runs affected categories) or "re-audit" (full re-dispatch from Step 0.5). |
| User demotes Tier 1 finding to Tier 2 at review gate | Orchestrator records demotion in `decisions.md`, updates REMEDIATION_PLAN, files affected category's follow-up bead |
| Codex plugin unavailable for Phase 2 | Pause; surface to user; do not silently substitute another model |
| Soft-budget tripwire | If any phase exceeds 2× the Phase token estimate in §15, surface to user with current spend + projection before continuing |

## 15. Resource Budget

This is an expensive audit by design. The user accepted this cost in choosing the multi-dimensional architecture.

| Phase | Workers × Model | Rough token estimate (per worker) | Order-of-magnitude total |
|-------|----------------|-----------------------------------|--------------------------|
| Phase 1 | 7 × Opus 1M @ xhigh effort | ~100k–250k input + ~30k–60k output (reads ~10–30 source files + 1–3 primers + vision) | ~2M tokens |
| Phase 2 | 6 × Codex (`gpt-5.4`) | ~80k–150k input + ~15k–30k output (reads all 5 primers + all 7 Phase 1 outputs) | ~1M tokens |
| Phase 3 | 1 × Sonnet 1M | ~300k–500k input + ~50k–100k output (must hold all 13 prior outputs) | ~600k tokens |
| Tier 1 fixes | up to 7 × Sonnet (serial by default, parallel only when scope-disjoint) | ~20k–50k input + ~10k–20k output per category | ~300k tokens |

These are ±50% estimates, intended only for runaway detection (per the §14 soft-budget tripwire at 2× per-phase). They are NOT a precision budget — the user accepted this cost class.

## 16. Out of Scope

- **Implementation of Tier 2 fixes** — those are the job of the per-category follow-up beads filed at acmh close.
- **Tier 3 dep-migration script extraction** — owned by `wmjy`, which is choosing script-extraction as its implementation.
- **Restructuring AGENTS.md vision section** — the audit may flag clarity issues but the vision text itself is the user's authorship; vision-section findings produce recommendations only and are routed to a follow-up bead. Non-vision sections of AGENTS.md (e.g. plugin docs, primer references, prerequisites) are in scope for Tier 1/2 fixes per AC #11.
- **External plugins beyond `src/plugins/beads/`** — only the in-tree plugin is in scope.
- **Skill or agent body rewrites** — Tier 2; deferred to follow-up.
- **Adding new skills, agents, commands, or rules** — audit produces recommendations; new content creation is separate work.
- **Testing the install.sh against all four target tools (Claude/Codex/Gemini/OpenCode)** — only `--dry-run` validation is in scope; full multi-tool install testing is out of scope.

## 17. Notes on Future Work Surfaced by This Audit

The audit will likely surface findings that imply broader project work:

- **Vision/AGENTS.md gap items** — if findings recur against gaps already enumerated in AGENTS.md "Current state — work in progress", recommendations should reference the existing tracker label `vision-85-5-10` rather than file new beads.
- **Cross-tool rule embedding** — RULES_PRIMER notes the future intent that rule content embeds into Codex/Gemini AGENTS.md. The audit may produce a recommendation for that install pipeline change; if so, file as a separate bead, not as part of remediation.
- **Helper-script library** — Tier 1+2+3 extractions accumulate scripts in `.beads/scripts/`. The audit may surface a need for a discoverability mechanism (index, conventions doc) — file as a separate bead if so.

---

## Appendix A — Primer Set

The five primers in `docs/primers/` are the shared knowledge base for all audit subagents:

| Primer | Owner content type |
|--------|---------------------|
| SKILLS_PRIMER.md | Skills (frontmatter, progressive disclosure, naming, degrees of freedom, MCP tool refs) |
| AGENTS_PRIMER.md | Agent definitions (frontmatter, memory scope, dispatch contract, key constraints) |
| COMMANDS_PRIMER.md | Slash commands (lean delegation, $ARGUMENTS, command-vs-skill-vs-agent) |
| RULES_PRIMER.md | Rules files (path scoping, append/collision model, rules-vs-skills, cross-tool embedding intent) |
| FORMULAS_PRIMER.md | Formulas and molecules (TOML structure, lifecycle, parent-chain invariants, composition) |

The vision context comes from AGENTS.md at dispatch time, not a primer file — this avoids drift.

## Appendix B — Bead Dependencies

```
agents-config-acmh (this bead)
  ├── absorbed: agents-config-xacz (closed)
  ├── blocks: agents-config-2gzy (audit findings inform 2gzy's scope)
  └── adjacent: agents-config-wmjy (script-extraction implementation chosen;
                                     covers Tier 3 dep-migration)

Filed at acmh close (deferred Tier 2 work):
  ├── Remediate: skills audit findings        (if any Tier 2)
  ├── Remediate: agents audit findings        (if any Tier 2)
  ├── Remediate: commands audit findings      (if any Tier 2)
  ├── Remediate: rules audit findings         (if any Tier 2)
  ├── Remediate: formulas audit findings      (if any Tier 2)
  ├── Remediate: scripts audit findings       (if any Tier 2)
  ├── Remediate: templates audit findings     (if any Tier 2)
  └── Tier 3 bd-sequence extraction           (children-check + label-copy-filter)
```
