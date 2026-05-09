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
[Vision & Mission section from AGENTS.md, lines 9-41, injected verbatim
 by the orchestrator at dispatch time]

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
- Files in scope (exact paths)
- Audit dimensions (from §3)
- Output file path
- Finding schema (from §8)
- Constraints:
  * NO source-file modifications during audit (Phase 1, 2, 3 are read-only on source)
  * Every finding must include a non-empty Vision-advancement field
  * Output file must be valid markdown with the schema fields populated
- Reporting format expectations
```

Vision content is injected fresh from the live AGENTS.md at dispatch time — there is no static copy in the primers directory. If AGENTS.md updates between phases, later phases see the newer content.

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
  Vision-advancement: <how this recommendation advances the 85/5/10 ratio
                      or a load-bearing commitment — one sentence,
                      MANDATORY non-empty>
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

- Frontmatter corrections (typos, missing required fields, name-validation violations per Anthropic schema)
- Bead-ID and bd-command removal from shared (`src/user/`) content — find-and-replace
- Dead reference removal (cross-refs to nonexistent files)
- Forward-slash conversion for Windows-style paths
- Adding TOC headers to >100-line reference files (mechanical scaffolding)
- Typo fixes
- Removing recurring noise patterns (e.g., the same "Rules in This Repository" / "Instruction Hierarchy" patterns we cut from RULES_PRIMER)

### Tier 2 — Design required, deferred to follow-up beads

- Skill body restructuring (which content moves to `references/`, what stays)
- Formula step prose rewrites (requires understanding the step's role)
- Agent body simplification (requires reading role boundaries)
- Rule splitting (policy boundary judgment)
- Right-tool reclassification (skill↔rule↔command↔agent↔shell script)
- Terminology unification across files (requires choosing the canonical term)
- Helper-script extraction from prose-prescribed deterministic logic (parameter design)
- Tier 3 bd-sequence extractions (children-check, label-copy-filter)
- Anything where two reasonable engineers would land on different fixes

**The line**: Tier 1 = a regex or unambiguous edit. Tier 2 = anything requiring judgment.

If a Tier 1 fix turns out to break `install.sh --dry-run`, the orchestrator reverts and demotes to Tier 2.

## 11. Cross-Cutting Use Cases (Phase 2)

The six use cases are deliberately uneven — each touches the categories it actually exercises in real agent workflows. None is required to touch all categories.

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
| 5 | User has reviewed `REMEDIATION_PLAN.md` and approved the Tier 1 fix list |
| 6 | All approved Tier 1 fixes applied to source files |
| 7 | `scripts/install.sh --dry-run` passes after Tier 1 fixes |
| 8 | One follow-up bead filed per category with ≥1 Tier 2 finding |
| 9 | Tier 3 bd-sequences follow-up bead filed (children-check + label-copy-filter) |
| 10 | Comments posted on `agents-config-2gzy` (script-interface findings) and `agents-config-wmjy` (dep-migration extraction confirmation) |
| 11 | AGENTS.md updated if audit surfaces findings against it |
| 12 | Completion gate passed: quality-reviewer → simplify → verify-checklist (all pass with evidence) |
| 13 | PR created via `finishing-a-development-branch` skill; summary links to `REMEDIATION_PLAN.md` |

## 13. Execution Sequence

### Step 0 — Preflight
- Verify all 5 primers exist at `docs/primers/` (SKILLS, AGENTS, COMMANDS, RULES, FORMULAS)
- Read AGENTS.md vision section into orchestrator context
- Confirm bead `agents-config-acmh` is `in_progress` with no active molecule conflict
- Create worktree at `.claude/worktrees/acmh-comprehensive-audit`

### Step 1 — Phase 1 dispatch (parallel)
- Dispatch 7 Opus 1M / xhigh effort subagents in a single message
- Each gets: vision context + relevant primer(s) + file scope + output path + finding schema
- Subagents make NO source-file modifications; output only

### Step 2 — Phase 1 verification
- Confirm all 7 output files exist
- Spot-check schema compliance (every finding has all fields, including non-empty Vision-advancement)
- If any subagent failed: re-dispatch (idempotent — outputs go to same path)
- Commit Phase 1 outputs

### Step 3 — Phase 2 dispatch (parallel)
- Dispatch 6 Codex GPT-5.5 subagents via the Claude Code Codex plugin (`codex-companion.mjs`, never the raw `codex` binary)
- Each gets: vision + all 5 primers + all 7 Phase 1 outputs + use-case brief + output path
- Each writes to its assigned `phase2/<use-case>.md`

### Step 4 — Phase 2 verification
- Confirm all 6 output files exist; schema spot-check
- Commit Phase 2 outputs

### Step 5 — Phase 3 aggregation (serial)
- Dispatch 1 Sonnet 1M subagent
- Inputs: vision + all 5 primers + all 7 Phase 1 + all 6 Phase 2 outputs
- Outputs: `by-category/`, `by-file/`, `decisions.md`, `REMEDIATION_PLAN.md`
- Conflict-resolution rule: aggregator decides AND states why; never "reviewer wins" silently
- Commit Phase 3 outputs

### Step 6 — USER REVIEW GATE
- Orchestrator presents `REMEDIATION_PLAN.md`
- User can: approve, demote any Tier 1 finding to Tier 2, drop findings, request schema fixes
- **No source files touched until user approves**

### Step 7 — Tier 1 application (parallel by category)
- One Sonnet subagent per category with Tier 1 findings
- Each applies its category's mechanical fixes
- Orchestrator commits in batches (one commit per category)

### Step 8 — Tier 1 verification
- Run `scripts/install.sh --dry-run`
- If failure: revert offending category's commit, demote findings to Tier 2, update REMEDIATION_PLAN

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
| Phase 1 subagent crashes or returns malformed output | Re-dispatch with same prompt (idempotent — overwrites the file) |
| Phase 2 subagent disagrees with Phase 1 entirely | That's the design — Phase 3 aggregator resolves with `decisions.md` entry |
| Phase 3 aggregator can't resolve a conflict from evidence | Flag in `decisions.md` as "needs human"; surface in REMEDIATION_PLAN for user review |
| Tier 1 fix breaks `install.sh --dry-run` | Revert that category's commit; demote affected findings to Tier 2 |
| Source file modified by another agent during audit | Re-run that category's Phase 1 + Phase 2 against the new state |
| User demotes Tier 1 finding to Tier 2 at review gate | Orchestrator updates REMEDIATION_PLAN, files affected category's follow-up bead |
| Codex plugin unavailable for Phase 2 | Pause; surface to user; do not silently substitute another model |

## 15. Resource Budget

This is an expensive audit by design. The user accepted this cost in choosing the multi-dimensional architecture.

| Phase | Workers × Model | Token expectation |
|-------|----------------|-------------------|
| Phase 1 | 7 × Opus 1M @ xhigh effort | High — each agent reads ~10-30 source files + 5 primers + vision injection |
| Phase 2 | 6 × Codex GPT-5.5 | Moderate — each reads all 7 Phase 1 outputs (smaller than source files) |
| Phase 3 | 1 × Sonnet 1M | High — must hold all 13 prior outputs in context |
| Tier 1 fixes | ~7 × Sonnet (parallel, one per category with Tier 1) | Low — focused mechanical edits |

## 16. Out of Scope

- **Implementation of Tier 2 fixes** — those are the job of the per-category follow-up beads filed at acmh close.
- **Tier 3 dep-migration script extraction** — owned by `wmjy`, which is choosing script-extraction as its implementation.
- **Restructuring AGENTS.md vision section** — the audit may flag clarity issues but the vision text itself is the user's authorship; recommendations only.
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
