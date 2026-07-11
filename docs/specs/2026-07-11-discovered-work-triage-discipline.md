# Discovered-Work Triage Discipline

**Date:** 2026-07-11
**Status:** Draft (pending review)
**Bead:** agents-config-vaac.8
**Decision:** In-scope discoveries are fixed in-session by default (deferral is a justified, escalated exception); out-of-scope discoveries are filed *anchored* to the roadmap with a required triage-rationale block; the completion report renders every discovery in a structured manifest whose "Lands in" value must name an anchor. Prose enforcement now (rule + skill), mechanical enforcement later via a workcli `work discover` verb.

## 1. Problem

Agents discover work mid-task, file beads for it (good), then claim victory with
the discovered work as an untriaged footnote. The human is left not knowing:

1. **Where the work sits relative to the roadmap** — beads are orphaned.
2. **How severe/urgent it is** — priority is self-assigned silently, with no rationale.
3. **Whether it should have been done in-session** — the agent may have misjudged
   in-scope work as "discovered work I can do later," and nothing surfaces that call.
4. **That it exists at all** — the completion report renders discoveries as a bare
   two-column table (`Item | Recorded In`), positioned last.

The orphaning is *by design*: the current discovered-work rule solves exactly one
problem (close-walk safety) and its out-of-scope branch prescribes "orphan +
`discovered-from` breadcrumb," full stop. The repo convention "work that maps to a
milestone is a child of that milestone bead" is never invoked on the discovery path.

Measured at design time: of 93 open non-epic/non-milestone beads, 15 had no parent
anchor; 14 of those carried only a `discovered-from`/`related-to` breadcrumb — the
exact pattern the rule prescribes.

The subtlest defect: the sibling test ("would this have been on the original
plan?") routes a **yes** answer to *filing a child bead*, not to *doing the work*.
"Yes, this was in scope" is precisely the case where the agent should fix it now or
escalate loudly. The current rule lets agents launder in-scope work into deferrable
discoveries.

## 2. Decisions

| # | Decision | Rejected alternatives |
|---|----------|----------------------|
| 1 | **Fix-in-session default** — in-scope discoveries get done in the current session/PR; deferral only through three named escape hatches, each requiring a report escalation | Defer-but-justify (keeps the leak); ask-per-item (returns the human to the babysitting loop) |
| 2 | **Agent anchors + audit trail** — the agent finds the best-fit epic/milestone and files the bead as its child with a one-line placement rationale; the human audits via the report | Triage inbox (placement work stays on the human); hybrid confidence routing (adds a judgment call agents get wrong both ways) |
| 3 | **Prose now, workcli verb later** — rule + skill changes ship immediately; a `work discover` verb (mechanical refusal of unanchored/untriaged filings) is filed as a continuation | Helper script now (workcli supersedes it — throwaway); prose only (honor system forever) |
| 4 | **Rule + skill split** — the beads-plugin rule owns filing-time discipline (always loaded, fires at the discovery moment); verify-checklist owns report-time (manifest + audit that catches what filing missed) | Fat rule (no report-time teeth); dedicated skill (relies on mid-flow invocation discipline — the thing that's failing) |

## 3. Design

### 3.1 Filing-time contract — rewrite `src/plugins/beads/.agents/rules/discovered-work.md`

The rule keeps the sibling test and close-walk safety, and gains the adjudication
step. New decision procedure when mid-task work surfaces:

**Step 1 — Sibling test (kept):** *would this have been on the original plan/spec?*

**Step 2 — In-scope → fix it now (default).** It is part of the work the agent was
asked to do. Deferral is permitted only through three escape hatches:

- **(a) Externally blocked** — needs credentials, an upstream fix, or another PR to land first.
- **(b) Blast-radius expansion** — the fix crosses into a subsystem or risk class the current change doesn't already touch.
- **(c) Deserves its own cycle** — big enough to need its own design/tests/review (heuristic: would roughly double the current diff).

Every deferral requires **all** of:
- Filing as a **sibling** of the in-flight bead: `bd create --parent
  <parent-of-in-flight-bead>` (keeps the in-flight bead closeable; the family holds
  the deferred work). No in-flight bead, or in-flight bead has no parent → anchor
  per the out-of-scope procedure below, recording session/PR provenance in the
  triage block.
- The triage block (below) with `Scope: in-scope — deferred: <hatch> — <why>`.
- An escalation line in the completion report's **Remaining Work** section — not
  only the discovered-work manifest.
- Not closing the filed bead this session.

**Step 3 — Out-of-scope → anchored filing.** Orphan-plus-breadcrumb is no longer
the default shape. Required:

- **Parent = best-fit epic under the milestone the work maps to**; no fitting epic
  → the milestone itself (`bd create --parent <anchor-id>`). Existing label
  conventions apply (e.g. the install label → milestone's install epic).
- **Keep the provenance edge**: `bd dep add <new-id> <current-work-id> --type
  discovered-from`. It is provenance, not placement. Both edges, always.
- **Triage block** appended to the bead description:

  ```markdown
  ## Triage
  - Scope: out-of-scope — <one line why>          (or: in-scope — deferred: <hatch> — <why>)
  - Priority: P<N> — <one line why>
  - Anchor: <epic-or-milestone-id> — <one line why>
  ```

- **Orphan is the loud exception**: permitted only when genuinely no milestone
  fits, and that fact must surface in the completion report as an escalation
  ("fits no milestone — may be out of project scope, needs a human call").

**Close-walk safety (kept, reframed):** never file a discovery as a child of the
in-flight bead itself, and never close an out-of-scope discovery's new parent
chain mid-session. The original trap text (parent auto-closes when all structural
children close) is retained.

### 3.2 Report-time contract — upgrade `src/user/.agents/skills/verify-checklist/SKILL.md`

Second gate; catches what filing missed. Wording stays tracker-neutral (the skill
ships to all four tools; bd mechanics stay in the beads-plugin rule).

**Audit step (added to "Gather Context"):** for each work item filed this session —
anchor present? Priority rationale present? Provenance link present? Missing → fix
now, with the same teeth as the existing "unrecorded work is lost work" clause: an
unanchored item is an orphan; anchor it now.

**Manifest replaces the footnote table.** Every discovery gets a row — including
those fixed in-session, so the adjudication is visible, not just the leftovers:

```markdown
### Discovered Work
| Item | Scope | Lands in | Bead | Priority — why |
|------|-------|----------|------|----------------|
| null-check in poller | in-scope | this PR | — | — |
| retry config drift | in-scope | parent epic (<id>) | <id> | P1 — deferred: blast radius; breaks overnight runs |
| stale docs in guide | out-of-scope | <epic-id> (M4 review epic) | <id> | P3 — cosmetic |
```

**"Lands in" value vocabulary** — the value must *be* an anchor; vague temporal
buckets ("future work") are structurally disallowed:

- `this PR` — fixed in-session; no tracking item needed.
- `parent epic (<id>)` — in-scope work deferred into the in-flight family.
- `<epic-or-milestone-id>` — out-of-scope, anchored to the roadmap.
- `unanchored — needs your call` — the rare no-milestone-fits escalation.

A bare `—` cell is legitimate only on `this PR` rows (nothing was filed, so
there is no tracked item or priority); every row that files a tracked item must
fill all five cells.

**Double-reporting rule:** any in-scope row whose "Lands in" is not `this PR` also
appears in **Remaining Work** as an escalation line.

**Red-flags table addition:** "I'll mention the filed items casually at the end" →
every discovery gets a manifest row with full triage.

### 3.3 Shared checklist step 9 — `src/user/.agents/INSTRUCTIONS.md.template`

> 9. Discovered work recorded **and triaged** — issues found during work are
> tracked, severity-rated with rationale, and anchored to the roadmap per the
> discovered-work placement discipline.

Concept reference, no file paths — survives DYNAMIC-INCLUDE flattening.

### 3.4 Align `src/user/.agents/skills/wait-for-pr-comments/SKILL.md`

Its filing fallback ("Fail or no parent → orphan + `discovered-from`") is replaced
with a pointer to the discovered-work rule's anchored-filing procedure. No
competing instructions left standing.

## 4. Non-goals

- No new skill, agent, or helper script (mechanical enforcement arrives with the
  workcli verb — see Continuations).
- No auto-remediation of the 14 existing breadcrumb-only beads in this change
  (separate sweep — see Continuations).
- No change to close-walk semantics or bd itself.
- No implementation-readiness labeling policy for discovered beads — that is
  agents-config-abn9.15 (deferred under the formula freeze), related but distinct.

## 5. Verification

All four touchpoints are prose/config; there is no build step. Verification is:

1. **Consistency** — the four changed files agree on the procedure, the triage
   block format, and the manifest vocabulary; a grep for the retired
   orphan-default pattern across `src/` returns no instruction that still
   prescribes it.
2. **Install-layout neutrality** — no files added/removed/renamed, so the
   installer's merge behavior is unchanged.
3. **Effectivity note** — changes take effect only after the user runs the
   installer; deployed copies under `~/.claude/` etc. are stale until then.

## 6. Continuations

- **workcli `work discover` verb** — mechanical filing contract: refuses to file a
  discovery without an anchor parent and a complete triage block; emits the
  manifest row as structured JSON. Acceptance: filing without anchor or rationale
  fails with a non-zero exit and a message naming the missing field; filing with
  them creates the item with both edges (parent + provenance) in one call.
  Anchor at minting time per this spec's own procedure.
- **One-time remediation sweep** — triage and anchor the 14 breadcrumb-only open
  beads identified at design time (re-enumerate at execution: open non-epic beads
  whose only downward edges are `discovered-from`/`related-to`). Acceptance: zero
  open non-epic beads without a parent anchor, or each survivor carries an
  explicit human-approved orphan rationale.
