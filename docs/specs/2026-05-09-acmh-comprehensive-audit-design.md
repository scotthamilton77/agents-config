# Comprehensive Audit of Agent-Facing Content — Design

**Bead**: `agents-config-acmh` (closed; this spec is the implementation guide consumed by `agents-config-il69`)
**Status**: Spec — finalized through 4 ralf-review cycles (cycles 1–2 inline, cycles 3–4 belt-and-suspenders post-close)
**Date**: 2026-05-09 (initial); 2026-05-10 (cycle 3+4 patch pass)
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

When a finding could plausibly claim either A or B, prefer **A** — the more specific tier wins.

Phase 3 acceptance rule: at most **30%** of *accepted* findings (after MERGED/DROPPED resolution) may be tier C. If the C share exceeds 30%, the aggregator demotes tier-C findings to DROPPED in **ascending severity order**, breaking ties by **descending document order** within the source file (deterministic). Demotion continues until the ratio drops to ≤ 30% OR all remaining tier-C findings are Critical/High AND no tier-A/B findings exist — in that terminal case the aggregator stops demoting and **surfaces the result to the user as a vision-alignment failure of the audit itself** (recorded in `decisions.md` and flagged in `REMEDIATION_PLAN.md`). Each demotion records a `decisions.md` entry with rationale.

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
| audit-templates | `src/user/.agents/INSTRUCTIONS.md.template`; `AGENTS.md.template` (all platforms); `settings.json.template`; the live root `AGENTS.md` (non-vision sections only — vision-section findings are recommendation-only per §16) |

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
│   6 × Codex (gpt-5.4 per §6), dispatched in parallel            │
│   Each: vision + all primers + all Phase 1 outputs              │
│   Reviewers operate on Phase 1 findings + primers + vision —    │
│   they do NOT re-audit source files. Source-omission gaps are   │
│   surfaced (if at all) by inter-reviewer disagreement on Phase 1│
│   coverage, resolved at Phase 3.                                │
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
[Vision & Mission section from AGENTS.md, extracted by H2 boundary.
 Extraction rule: from the line beginning `## Vision & Mission` through
 the last line before the next H2 header (regex: `^## ` at column 0).
 The H3 subsections inside it (`### Current state…`, `### Implications
 for agents working in *this* repo`) are part of the extracted block by
 construction. Injected verbatim by the orchestrator at dispatch time.
 Line numbers MUST NOT be hard-coded; the H2 boundary rule survives
 AGENTS.md edits. Step 0 verification prints the first and last
 extracted line for the user to eyeball before any phase dispatches.]

=== AUDIT INPUT SHA ===
[The full git SHA the orchestrator pinned at Step 0.5. All file paths
 in the brief resolve against this SHA.

 Drift check (scoped, NOT a HEAD-equality check): at dispatch time and
 at each verification step, the orchestrator runs
   `git diff --name-only AUDIT_INPUT_SHA HEAD -- <resolved-source-paths>`
 where `<resolved-source-paths>` is the union of file lists resolved at
 Step 0.5 (i.e., the §4 globs at the pinned SHA). Empty diff = invariant
 holds. Audit outputs under `docs/audits/**` are intentionally excluded
 from this check by construction — they are not in §4 source scope and
 must not be expected to match `AUDIT_INPUT_SHA`. The orchestrator's
 own `Commit Phase N outputs` operations move the worktree HEAD; that
 is expected and does NOT violate the invariant. Only changes to
 in-scope source files do. If the diff is non-empty for any in-scope
 path, the orchestrator MUST refuse to dispatch and surface.]

=== ROLE PRIMERS ===
[All subagents (Phase 1, 2, 3) read all 5 primers in docs/primers/
 (SKILLS, AGENTS, COMMANDS, RULES, FORMULAS). Phase 1 auditors need the
 full set because the §3 "right tool for the job" dimension requires
 evaluating skill↔rule↔command↔agent↔shell-script reclassification —
 which demands understanding all content-type charters, not just the
 auditor's primary category. Phase 2 also receives all 7 Phase 1 outputs.
 Phase 3 also receives all 7 Phase 1 + all 6 Phase 2 outputs.]

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
  observations outside scope go in an "Out of scope" section using the
  out-of-scope schema below. Phase 2 reviewers do NOT see each other's
  outputs — inter-reviewer conflicts are resolved by Phase 3.
- Phase 1 isolation: auditors run in parallel and do NOT read each other's
  outputs; the orchestrator dispatches all 7 in a single message and only
  commits Phase 1 outputs after all 7 return (per §13 Step 2).
- Audit dimensions (§3 BOTH tables — dimension table AND "acid test by
  content type" table — must be inlined in the brief verbatim by the
  orchestrator; the orchestrator MUST NOT summarize or paraphrase. Step 2
  / Step 4 verification confirms both tables are literally present in
  the dispatch prompt.)
- Output file path
- Finding schema (§8 inlined verbatim)
- Constraints:
  * NO source-file modifications during audit (Phase 1, 2, 3 are read-only on source)
  * Every finding must include a non-empty Vision-advancement field with a
    declared tier (A, B, or C — see §2 rubric); tier-A is preferred when
    both A and B could apply
  * Output file must be valid markdown with the schema fields populated
  * Zero-findings result is a valid output: write a "Findings: none" block
    with one paragraph summarizing what was reviewed (the paragraph MUST
    name concrete files from the resolved file list — generic prose is
    not acceptable and will fail Step 2/Step 4 verification) and why
    nothing was flagged. Do NOT invent findings to fill the file.
- Reporting format expectations
```

### Phase 2 out-of-scope schema

Phase 2 observations that fall outside the reviewer's `categories-touched` list are recorded in an "Out of scope" section of the reviewer's output file using a constrained schema (NOT the §8 finding schema):

```
OOS<n>: <one-line title>
  File: <path>:<lines>
  Outside-scope: <reason — which category and why it's outside this reviewer's lens>
  Observation: <what was noticed>
  Suggested follow-up: <which Phase 2 reviewer or Phase 1 category should address>
```

Phase 3 reads OOS entries as advisory only. The aggregator MAY promote an OOS entry to a real finding only with an explicit `decisions.md` entry naming the rationale and constructing the missing schema fields (Severity, Tier, Vision-advancement, etc.) itself.

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

**File-slug algorithm**: For a source path `<full-path>`, the slug is computed deterministically by the orchestrator as follows. Auditors do not name `by-file/` files themselves.

1. **Normalize**: take `<full-path>` as the path relative to the repo root (no leading `./`).
2. **Strip prefix**: if the path starts with `src/`, strip that prefix. Paths outside `src/` (e.g., the live root `AGENTS.md`) are processed as-is from this step.
3. **Path-separator substitution**: replace each `/` with `--`.
4. **Dot substitution**: replace **every** `.` with `-`. There is no "in extensions" distinction — leading-dot directories (`.agents`, `.beads`, `.claude`), middle dots (`SKILL.md.template`), and final extension dots are all treated identically. This is a deliberate simplification; the rule is unambiguous and operator-implementable.
5. **Append `.md`** to produce the slug.
6. **Collision resolution**: if two distinct in-scope paths produce the same step-5 result, the orchestrator appends an 8-character hash before the `.md`: `<base>-<hash>.md`, where `<hash>` is the first 8 lowercase hex characters of `sha256(<full-path>)`. If two paths still collide after the 8-char hash (vanishingly rare; collision resistance ~10⁹), append a numeric tiebreak `-<n>` where `<n>` ≥ 2 in lexicographic path-sort order. Both the hash function (sha256) and encoding (lowercase hex, first 8 chars) are pinned by spec — alternative implementations are not permitted.

**Worked examples**:

| Source path | Slug |
|---|---|
| `src/user/.agents/skills/writing-unit-tests/SKILL.md` | `user---agents--skills--writing-unit-tests--SKILL-md.md` |
| `src/user/.agents/agents/quality-reviewer.md` | `user---agents--agents--quality-reviewer-md.md` |
| `src/user/.claude/rules/completion-gate.md` | `user---claude--rules--completion-gate-md.md` |
| `src/plugins/beads/.beads/scripts/finalize-create-impl-bead.sh` | `plugins--beads---beads--scripts--finalize-create-impl-bead-sh.md` |
| `AGENTS.md` (root, outside `src/`) | `AGENTS-md.md` |
| `src/user/.agents/INSTRUCTIONS.md.template` | `user---agents--INSTRUCTIONS-md-template.md` |

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
  Vision-advancement-tier: A | B | C    (per §2 rubric; A preferred when both A and B apply)
  Vision-advancement: <one sentence — MANDATORY non-empty.
                      Tier A names a load-bearing commitment + mechanism;
                      Tier B names a `vision-85-5-10`-labeled gap;
                      Tier C is generic "reduces noise / improves clarity".>
  Promotion-eligible: yes | no    (Tier 2 findings only — "yes" means the
                      Issue/Recommendation are concrete enough that the
                      Phase 3 aggregator could construct a before/after
                      snippet and promote to Tier 1 if appropriate. "no"
                      means the finding genuinely requires design judgment.
                      Tier 1 findings omit this field.)
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

### `decisions.md` entry schema

`decisions.md` is the conflict-resolution and audit-trail log. Every entry uses this structure (Step 5 verification depends on this schema being literal — alternative shapes fail the verifiable checks):

```
D<n>: <one-line summary>
  Type: conflict-resolution | tier1-promotion | tierC-demotion | oos-promotion |
        sha-drift | tier1-revert | user-gate-demotion | user-gate-drop |
        vision-alignment-failure | manual-fix-up
  Sources: phase1/<file>:F<n>, phase2/<file>:F<n>     (as applicable; "none" for oos-promotion or sha-drift)
  Resolution: <accepted | merged | dropped | deferred | promoted-to-tier1 |
              demoted-to-tier2 | reverted | flagged-for-human>
  Rationale: <one paragraph — why this disposition>
  Snippet: (REQUIRED for tier1-promotion only; omit otherwise)
    Before: <verbatim source-text excerpt at AUDIT_INPUT_SHA>
    After:  <verbatim replacement text>
```

**Step 5 verifiable checks reference this schema literally**:
- "Every Phase 2 finding with `Verdict: DISAGREE` or `PARTIAL` has a `decisions.md` entry whose `Sources:` field includes the corresponding `phase2/<file>:F<n>`" (mechanical grep against entry `Sources:` lines).
- "Every promoted Tier 2 → Tier 1 has `Type: tier1-promotion` AND a non-empty `Snippet:` block" (mechanical parse).
- "Every Tier-C demotion to DROPPED has `Type: tierC-demotion` with a `Rationale:` line" (mechanical parse).
- "For each `Snippet: Before:` block, `git grep -F "<Before>"` against `AUDIT_INPUT_SHA` returns ≥1 match" (defends against hallucinated promotion snippets; if zero matches, the aggregator demotes the promotion back to Tier 2 with a follow-on `Type: tier1-revert` entry).

User-authored entries (the manual fix-up path in §13 Step 5) MUST follow the same schema with `Type: manual-fix-up`. The orchestrator parses the manual entries identically to aggregator entries. Free-form prose insertions are ignored by Step 5 verification.

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

**Default-to-Tier-2 rule**: If a Phase 1 auditor is uncertain whether a finding qualifies for Tier 1, classify as Tier 2 with `Promotion-eligible: yes` (per §8) when the Issue/Recommendation are concrete enough that an aggregator could mechanically synthesize a before/after snippet. The Phase 3 aggregator may **promote** a Tier 2 finding to Tier 1 by:
- Constructing the before/after snippet itself when `Promotion-eligible: yes`, OR
- Using a pre-existing snippet supplied by the auditor.

Promotion is recorded in `decisions.md` with the constructed snippet attached. The aggregator may **never demote** a Tier 1 to Tier 2 silently — demotion requires a `decisions.md` entry with rationale. This asymmetry biases the system toward fewer false Tier 1s while preserving an aggregator path to fix obvious Tier 2 misclassifications.

If a Tier 1 fix turns out to break `install.sh --dry-run`, the orchestrator reverts and demotes to Tier 2 (recorded in `decisions.md`).

## 11. Cross-Cutting Use Cases (Phase 2)

The six use cases are deliberately uneven — each touches the categories it actually exercises in real agent workflows. None is required to touch all categories. Use case 5 explicitly bundles three sub-questions and is therefore expected to produce a deeper output than the others; this asymmetry is accepted by design rather than split.

Each Phase 2 reviewer sees: vision + all 5 primers + all 7 Phase 1 outputs + their own use-case brief. They do **NOT** see other Phase 2 reviewers' outputs. Inter-reviewer disagreements are surfaced and resolved by Phase 3 against `decisions.md`. Each reviewer's brief includes the categories-touched list from the table below; counter-findings outside that list go into an "Out of scope" advisory section using the OOS schema in §6, not into the main findings.

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
| 5 | User has reviewed `REMEDIATION_PLAN.md` and approved the Tier 1 fix list — evidenced by an explicit `APPROVED <SHA>` marker line at the top of `REMEDIATION_PLAN.md` (canonical, lookup first), OR a comment on `agents-config-acmh` recording the approval and the worktree HEAD SHA (fallback). If both are present and the SHAs disagree, the orchestrator MUST surface to the user rather than guess. |
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
- Extract AGENTS.md vision section by H2 boundary: from the line beginning `## Vision & Mission` through the last line before the next H2 header (`^## ` at column 0). The H3 subsections inside (`### Current state…`, `### Implications for agents working in *this* repo`) are part of the extracted block. Line numbers MUST NOT be hard-coded.
- Print the first and last extracted line for the user to eyeball before continuing — confirms the H2 boundary detection landed on the right section
- Verify `docs/audits/` is absent (or, if present, that the user has explicitly authorized overwrite — the orchestrator surfaces and pauses on first-run conflict)
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
- **Schema check**: every finding parses against the §8 schema — every required field non-empty, `Severity ∈ {Critical, High, Medium, Low}`, `Tier ∈ {1, 2}`, `Vision-advancement-tier ∈ {A, B, C}`, `Vision-advancement` non-empty. Reject any output failing this and re-dispatch (subject to Step 1 retry cap). "Findings: none" outputs are exempt from per-finding checks but their summary paragraph MUST contain ≥3 distinct exact-substring matches from the category's resolved file list.
- **Source-drift check (scoped, NOT HEAD-equality)**: run `git diff --name-only AUDIT_INPUT_SHA HEAD -- <resolved-source-paths>`. Empty diff = invariant holds; the orchestrator's own commits of audit outputs do NOT trigger this (they are outside §4 source scope). If non-empty, surface and pause per the §6 AUDIT INPUT SHA contract.
- If any subagent failed: re-dispatch up to the Step 1 retry cap (idempotent — outputs go to same path)
- Commit Phase 1 outputs

### Step 3 — Phase 2 dispatch (parallel)
- Dispatch 6 Codex subagents via the Claude Code Codex plugin (`codex-companion.mjs`, never the raw `codex` binary).
- **Model resolution**: the orchestrator reads `codex-routing.md` at dispatch time and selects the model it currently lists for adversarial / cross-subsystem review (today, 2026-05: `gpt-5.4`). The spec does NOT hard-pin a literal version string — `codex-routing.md` is the authority. The resolved model name appears in the dispatch log and is recorded once in `REMEDIATION_PLAN.md` header metadata for audit-trail purposes.
- **Fallback on plugin rejection**: if the resolved model is rejected by the Codex plugin at dispatch time (returned error), the orchestrator MUST surface to the user and pause. The orchestrator MUST NOT silently substitute another model — quality of adversarial review depends on the model class. The user explicitly authorizes a fallback model (or aborts) before dispatch resumes.
- Each gets: `AUDIT_INPUT_SHA` + vision + all 5 primers + all 7 Phase 1 outputs + use-case brief + the categories-touched list from §11 + output path
- Each writes to its assigned `phase2/<use-case>.md`. Reviewers do not see each other's outputs by design.
- **Pre-dispatch source-drift check**: run the same scoped diff as Step 2's source-drift check; refuse to dispatch on non-empty diff.
- Per-phase max retry: 3 per subagent (same policy as Phase 1).

### Step 4 — Phase 2 verification
- Confirm all 6 output files exist; schema spot-check
- Commit Phase 2 outputs

### Step 5 — Phase 3 aggregation (serial)
- Dispatch 1 Sonnet 1M subagent
- Inputs: `AUDIT_INPUT_SHA` + vision + all 5 primers + all 7 Phase 1 + all 6 Phase 2 outputs
- Outputs: `by-category/`, `by-file/` (using the file-slug algorithm in §7), `decisions.md`, `REMEDIATION_PLAN.md`
- Conflict-resolution rule: aggregator decides AND states why; never "reviewer wins" silently
- Aggregator MUST enforce the Vision-advancement rubric (§2): if more than 30% of accepted findings carry tier C, demote per the §2 ascending-severity / descending-document-order algorithm, including the terminal "vision-alignment failure of the audit itself" surface case
- Aggregator handles cross-category reclassification findings (e.g. "this skill should be a script") — both the source-category `by-category/` output and the target-category `by-category/` output reference the finding via cross-link; the canonical entry lives in the source category
- Aggregator MAY promote OOS entries from Phase 2 reviewers to real findings only via an explicit `decisions.md` entry that constructs the missing schema fields itself
- Verifiable checks (after Phase 3 returns; all parse against the §8.5 `decisions.md` schema):
  * Every Phase 2 finding with `Verdict: DISAGREE` or `PARTIAL` has a `decisions.md` entry whose `Sources:` line includes the corresponding `phase2/<file>:F<n>` (mechanical grep)
  * Tier-C share of accepted findings ≤ 30% OR terminal vision-alignment-failure surface is present (mechanical count over `Vision-advancement-tier:` declarations of accepted findings; tier C cap enforced per §2)
  * Every promoted Tier 2 → Tier 1 has a `decisions.md` entry with `Type: tier1-promotion` and a non-empty `Snippet:` block whose `Before:` block matches at least one `git grep -F` occurrence in the source tree at `AUDIT_INPUT_SHA` (defends against hallucinated snippets; zero matches → automatic demotion back to Tier 2 with a follow-on `Type: tier1-revert` entry)
- **Phase 3 retry cap**: 2 attempts. On second verification failure, the orchestrator surfaces the missing-entry list to the user as a manual fix-up task. The user edits `decisions.md` directly using the §8.5 schema with `Type: manual-fix-up`. The orchestrator confirms via `git diff` that ONLY `docs/audits/phase3/decisions.md` was modified (no source files touched). It then re-runs Step 5 verification ONCE. If verification still fails, the orchestrator surfaces the still-missing list and halts the bead in `in_progress`; the user must re-invoke the orchestrator with corrected entries (no auto-loop, no third Phase 3 dispatch).
- Commit Phase 3 outputs

### Step 6 — USER REVIEW GATE
- Orchestrator presents `REMEDIATION_PLAN.md`
- **Marker format (operationally meaningful only)**: markers MUST appear at column 0 in `REMEDIATION_PLAN.md`. The `<SHA>` in the `APPROVED` marker MUST be a 40-character lowercase hex git SHA equal to `AUDIT_INPUT_SHA`. The orchestrator validates each `F<n>` referenced in `DEMOTE`/`DROP` against the live REMEDIATION_PLAN finding list; unknown F-ids surface to the user before any Tier 1 application begins.
- User actions:
  * **Approve**: add `APPROVED <SHA>` marker line as the first non-blank line of `REMEDIATION_PLAN.md` (canonical, lookup first), OR post a bd comment on `agents-config-acmh` whose body matches `^APPROVED <40-hex-SHA>$` (fallback) per AC #5. If both are present and the SHAs disagree, the orchestrator surfaces.
  * **Demote a Tier 1 to Tier 2**: add a marker line in `REMEDIATION_PLAN.md` of the form `DEMOTE F<n>: tier=2 reason=<text>` — the orchestrator parses these post-approval and reflects each in `decisions.md` as `Type: user-gate-demotion`. Editing diffs directly without a `DEMOTE` marker is NOT a supported demotion mechanism (the orchestrator will not reverse-engineer free-form edits).
  * **Drop a finding**: marker line `DROP F<n>: reason=<text>` (recorded as `Type: user-gate-drop`)
  * **Request schema fixes**: surface as a comment on the bead; orchestrator returns to Step 5 with the request
  * **Direct edit of `REMEDIATION_PLAN.md`**: only the `APPROVED`, `DEMOTE`, and `DROP` markers are operationally meaningful; prose edits are advisory and do not alter the orchestrator's behavior
- **No-action / silence behavior**: the gate does NOT auto-timeout. If no approval marker appears, the orchestrator parks indefinitely with the bead `agents-config-acmh` in `in_progress` and the worktree retained. Resumption requires the user to re-invoke the orchestrator with one of the marker actions above present in `REMEDIATION_PLAN.md` or as a bd comment. The orchestrator surfaces the parked state once on initial post-Phase-3 hand-off and remains silent thereafter; no Tier 1 application proceeds without an explicit `APPROVED` marker. (Rationale: the project's vision explicitly accepts overnight / multi-day cadences; an auto-timeout would conflict with that. Aborting cleanly is the user's job — `bd close --reason ...` if abandoning.)
- **Worktree source-drift invariant** (per §6 AUDIT INPUT SHA contract): at approval-marker parse time, the orchestrator runs `git diff --name-only AUDIT_INPUT_SHA HEAD -- <resolved-source-paths>`. Empty diff = invariant holds; audit-output commits do NOT violate it. If non-empty (in-scope source files modified during the gate), resolution paths:
  * **"proceed against new tree"** — orchestrator pins `AUDIT_INPUT_SHA_v2 = <new HEAD>` in `decisions.md` (`Type: sha-drift`), re-runs Phase 1 categories whose §4 globs intersect the changed paths against `AUDIT_INPUT_SHA_v2`, re-runs all 6 Phase 2 reviewers (their inputs include all Phase 1 outputs), and re-runs Phase 3 in full. Subsequent SHA-drift detection during the re-audit pins as v3, etc. Stale v1 outputs from re-run categories are deleted, NOT merged.
  * **"re-audit"** — full re-dispatch from Step 0.5 with a new `AUDIT_INPUT_SHA`
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
- All follow-up beads are filed as children of `agents-config-acmh` (`bd create --parent agents-config-acmh`) per beads invariant I3 — they are scoped reductions of acmh's original audit work, not orphan siblings. After `bd create --parent`, audit and strip inherited lifecycle labels (per the documented `bd-create-parent-inherits-labels` quirk).
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
| Phase 1 or Phase 2 subagent legitimately finds nothing | Subagent writes a "Findings: none" file with one paragraph summarizing what was reviewed (paragraph MUST name concrete files from the resolved file list) and why nothing was flagged. Phase 3 accepts this and notes it in `decisions.md`. Empty files are a valid output, NOT a re-dispatch trigger. Step 2/Step 4 verification spot-checks the paragraph for concrete file references; generic prose fails verification. |
| Phase 3 aggregator can't resolve a conflict from evidence | Flag in `decisions.md` as "needs human"; surface in REMEDIATION_PLAN for user review |
| Phase 3 verification fails (missing decisions.md entries, tier-C share violation, missing promotion snippet) | Re-dispatch Phase 3. Cap: 2 attempts. On second failure, surface the missing-entry list to user as manual fix-up; user edits `decisions.md` directly; orchestrator re-runs Step 5 verification only (no third dispatch). |
| Phase 3 tier-C demotion algorithm reaches the terminal "all Critical/High tier-C and no tier-A/B" state | Stop demoting; surface to user as a vision-alignment failure of the audit itself; flag prominently in `REMEDIATION_PLAN.md` |
| Phase 3 finds tier-C share > 30% after first pass | Aggregator demotes lowest-severity tier-C findings to DROPPED until threshold is met (per §2 rubric). Each demotion recorded in `decisions.md`. |
| Tier 1 fix breaks `install.sh --dry-run` | Revert that category's commit; demote affected findings to Tier 2 with rationale in `decisions.md` |
| Source file modified by another agent during Phase 1/2 | Detected via the §6 scoped source-drift check (`git diff --name-only AUDIT_INPUT_SHA HEAD -- <source-paths>` is non-empty). Orchestrator surfaces and pauses. User must explicitly authorize re-running affected categories' Phase 1+2 against the new state, or restoring the source files. |
| Source file modified during user-review gate | Same scoped source-drift check at approval-marker parse time; orchestrator surfaces. User chooses "proceed against new tree" (re-runs categories whose globs intersect the changed paths + all 6 Phase 2 + Phase 3) or "re-audit" (full re-dispatch from Step 0.5). |
| User does not respond at the review gate | Orchestrator parks indefinitely with bead `in_progress`. No auto-timeout. Resumption requires the user re-invoking the orchestrator with an `APPROVED` marker present (or `bd close` to abort). Orchestrator surfaces the parked state once on initial post-Phase-3 hand-off and remains silent thereafter. |
| User-supplied marker references unknown F-id | Orchestrator surfaces unrecognized F-ids before any Tier 1 application begins; waits for the user to correct the marker or remove it. |
| User demotes Tier 1 finding to Tier 2 at review gate | Orchestrator records demotion in `decisions.md` as `Type: user-gate-demotion`, updates REMEDIATION_PLAN, files affected category's follow-up bead |
| User-authored manual fix-up to `decisions.md` (Step 5 retry exhaustion) | Orchestrator confirms via `git diff` that ONLY `decisions.md` was touched (no source files); user-authored entries MUST follow the §8.5 schema with `Type: manual-fix-up`. Re-runs Step 5 verification once after the user signals fix-up complete. If verification still fails, surface the still-missing list and halt; user re-invokes when ready (no auto-loop). |
| Codex plugin unavailable for Phase 2 | Pause; surface to user; do not silently substitute another model |
| Codex plugin rejects the resolved model name | Pause; surface to user with the rejection error; do not silently substitute. User explicitly authorizes a fallback model name (recorded in `decisions.md`) or aborts. |
| `docs/audits/` already exists at Step 0 | Surface and pause. User explicitly authorizes overwrite (e.g., a re-run after manual cleanup) before Step 0 proceeds. |
| Soft-budget tripwire | If any phase exceeds 2× the Phase token estimate in §15, surface to user with current spend + projection before continuing |

## 15. Resource Budget

This is an expensive audit by design. The user accepted this cost in choosing the multi-dimensional architecture.

| Phase | Workers × Model | Rough token estimate (per worker) | Order-of-magnitude total |
|-------|----------------|-----------------------------------|--------------------------|
| Phase 1 | 7 × Opus 1M @ xhigh effort | ~150k–350k input + ~30k–60k output (reads ~10–30 source files + all 5 primers + vision) | ~3M tokens |
| Phase 2 | 6 × Codex (`gpt-5.4`) | ~80k–150k input + ~15k–30k output (reads all 5 primers + all 7 Phase 1 outputs) | ~1M tokens |
| Phase 3 | 1 × Sonnet 1M | ~300k–500k input + ~50k–100k output (must hold all 13 prior outputs) | ~600k tokens |
| Tier 1 fixes | up to 7 × Sonnet (serial by default, parallel only when scope-disjoint) | ~20k–50k input + ~10k–20k output per category | ~300k tokens |

These are ±50% estimates, intended only for runaway detection (per the §14 soft-budget tripwire at 2× per-phase). They are NOT a precision budget — the user accepted this cost class. Tier 1 fix tokens are spent only after the §13 Step 6 user-approval gate; users who shrink the Tier 1 list at the gate proportionally reduce that row.

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
