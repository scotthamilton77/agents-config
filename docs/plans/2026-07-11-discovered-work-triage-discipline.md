# Discovered-Work Triage Discipline Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking. This is a prose/config change: the "test" for each task is the grep assertion given in its verify step — run it exactly and compare against the expected output.

**Goal:** Make mid-task discoveries adjudicated (fix-in-session default), roadmap-anchored (triage block + parent edge), and visibly reported (structured manifest) instead of orphaned footnotes.

**Architecture:** Two thin gates per the spec (`docs/specs/2026-07-11-discovered-work-triage-discipline.md`): the beads-plugin rule owns filing-time discipline (always loaded, fires at the discovery moment); the verify-checklist skill owns report-time (manifest + audit). Two satellite touchpoints keep instructions non-competing: shared checklist step 9 and the wait-for-pr-comments DEFER-placement section.

**Tech Stack:** Markdown only — installed config content under `src/`. No build step; verification is grep assertions. Bead: agents-config-vaac.8.

---

### Task 1: Rewrite the discovered-work rule (filing-time contract)

**Files:**
- Rewrite: `src/plugins/beads/.agents/rules/discovered-work.md` (replace entire file)

- [ ] **Step 1: Replace the full file content with:**

````markdown
# Discovered-Work Discipline

When mid-task work surfaces a new issue, adjudicate scope FIRST, then file with a
roadmap anchor. Never file-and-forget: every discovery either gets fixed now or
gets a triaged, anchored bead plus a row in the completion report's
discovered-work manifest.

**Sibling test:** *would this have been on the current work item's original plan/spec?*

## In scope → fix it in this session (default)

In-scope discoveries are part of the work you were asked to do — do them now, in
the current session/PR. "Discovered work" is not a deferral service for missed
scope. Deferring in-scope work is permitted ONLY via three escape hatches:

- **externally-blocked** — needs credentials, an upstream fix, or another PR to land first
- **blast-radius** — the fix crosses into a subsystem or risk class the current change doesn't already touch
- **own-cycle** — big enough to deserve its own design/tests/review cycle (heuristic: would roughly double the current diff)

Every deferral requires ALL of:

1. File as a **sibling** of the in-flight bead: `bd create --parent
   <parent-of-in-flight-bead>` — keeps the in-flight bead closeable while the
   family holds the deferred work. (No in-flight bead, or it has no parent →
   anchor per the out-of-scope procedure below, recording session/PR provenance
   in the triage block.)
2. The triage block (below) with `Scope: in-scope — deferred: <hatch> — <why>`.
3. An escalation line in the completion report's **Remaining Work** section —
   not just the discovered-work manifest.
4. Do NOT close the filed bead this session.

## Out of scope → file it anchored

- **Parent = best-fit epic under the milestone the work maps to**; no fitting
  epic → the milestone itself: `bd create --parent <anchor-id>`. Apply the
  project's label conventions.
- **Provenance edge too**: `bd dep add <new-id> <current-work-id> --type
  discovered-from`. Provenance is not placement — both edges, always.
- **Orphan is a loud exception**: permitted only when genuinely no milestone
  fits, and the completion report must escalate it ("fits no milestone — may be
  out of project scope, needs a human call").

## Triage block (required on every discovered-work bead)

Append to the bead description:

```
## Triage
- Scope: out-of-scope — <one line why>   (or: in-scope — deferred: <hatch> — <why>)
- Priority: P<N> — <one line why>
- Anchor: <epic-or-milestone-id> — <one line why>
```

## Close-walk safety

Never file a discovery as a child of the in-flight bead itself, and never close a
newly filed discovery mid-session. Close-walk closes a parent the moment all its
structural children are closed — filing under the in-flight bead and closing the
child can auto-close in-flight work while it is still pending. Recovery needs
`bd reopen <parent>` plus an audit of beads the close-walk propagated through.
Classify with the sibling test BEFORE filing, not after.
````

- [ ] **Step 2: Verify**

Run: `grep -c "fix it in this session\|Triage block\|Close-walk safety" src/plugins/beads/.agents/rules/discovered-work.md`
Expected: `3` (one hit per section heading line; confirms all three new sections present)

Run: `grep -n "orphan + provenance\|Orphan + provenance" src/plugins/beads/.agents/rules/discovered-work.md`
Expected: no output, exit 1 (old orphan-default table retired)

- [ ] **Step 3: Commit**

```bash
git add src/plugins/beads/.agents/rules/discovered-work.md
git commit -m "feat(rules): discovered-work rule — fix-in-session default + anchored filing"
```

### Task 2: Upgrade verify-checklist (report-time contract)

**Files:**
- Modify: `src/user/.agents/skills/verify-checklist/SKILL.md` (three edits: Gather Context, report template, red-flags table)

- [ ] **Step 1: Edit "3. Gather Context"** — replace this text:

```markdown
- **Task objective** — What were you asked to do? One sentence.
- **PRs** — Branch names, PR URLs/numbers, current status
- **Remaining work** — Anything incomplete if this was a partial delivery
- **Discovered work** — Issues found but not addressed during implementation
- **Where recorded** — IDs in the project's tracking system, issue numbers, memory entries for each discovered item

If discovered work is unrecorded, **record it now** in the project's tracking system (issues, backlog, memory entries — whatever the project uses). Unrecorded work is lost work.
```

with:

```markdown
- **Task objective** — What were you asked to do? One sentence.
- **PRs** — Branch names, PR URLs/numbers, current status
- **Remaining work** — Anything incomplete if this was a partial delivery, plus every in-scope discovery deferred to a tracked item (each is an escalation line here, not just a manifest row)
- **Discovered work** — Every issue found during implementation: fixed in-session, deferred in-scope, or filed out-of-scope
- **Triage audit** — For each item filed this session: anchor parent present? Severity rationale present? Provenance link present?

If discovered work is unrecorded, **record it now** in the project's tracking system (issues, backlog, memory entries — whatever the project uses). Unrecorded work is lost work. If a filed item is unanchored or untriaged, **fix it now** per the project's discovered-work placement discipline — an unanchored item is an orphan; anchor it, rate it, and say why.
```

- [ ] **Step 2: Edit the report template** — replace this text:

```markdown
### Discovered Work
| Item | Recorded In |
|------|-------------|
| [description] | id in the project's tracking system / issue:#N / memory / backlog |
```

with:

```markdown
### Discovered Work
| Item | Scope | Lands in | Bead/Issue | Priority — why |
|------|-------|----------|------------|----------------|
| [description] | in-scope | this PR | — | — |
| [description] | in-scope | parent epic (<id>) | <id> | P1 — deferred: <hatch>; <severity rationale> |
| [description] | out-of-scope | <anchor epic/milestone id> | <id> | P2 — <severity rationale> |
```

"Lands in" must name an anchor: `this PR`, `parent epic (<id>)`, an
epic/milestone id, or `unanchored — needs your call` (rare escalation) — never
a vague bucket like "future work". Any in-scope row not landing in `this PR`
must also appear under **Remaining Work** as an escalation line.

- [ ] **Step 3: Add a red-flags row** — in the "Red Flags — STOP" table, insert after the row `| "I'll skip the discovered work section" | Unrecorded work is lost work. Record it now. |`:

```markdown
| "I'll mention the filed items casually at the end" | Every discovery gets a manifest row with full triage — scope, landing anchor, priority rationale. |
```

- [ ] **Step 4: Verify**

Run: `grep -n "Recorded In" src/user/.agents/skills/verify-checklist/SKILL.md`
Expected: no output, exit 1 (old two-column manifest retired)

Run: `grep -c "Lands in\|Triage audit\|casually at the end" src/user/.agents/skills/verify-checklist/SKILL.md`
Expected: `4` or more (new manifest header + vocabulary paragraph + audit bullet + red-flag row present)

Check wording stays tracker-neutral: `grep -n "bd \|bd create\|beads" src/user/.agents/skills/verify-checklist/SKILL.md`
Expected: no output, exit 1 (skill ships to all four tools; bd mechanics live only in the beads-plugin rule)

- [ ] **Step 5: Commit**

```bash
git add src/user/.agents/skills/verify-checklist/SKILL.md
git commit -m "feat(skills): verify-checklist — discovered-work manifest + triage audit"
```

### Task 3: Amend shared checklist step 9

**Files:**
- Modify: `src/user/.agents/INSTRUCTIONS.md.template` (one line, currently line 148)

- [ ] **Step 1: Replace**

```markdown
9. Discovered work recorded — issues found during work tracked in the project's system
```

with:

```markdown
9. Discovered work recorded and triaged — issues found during work are tracked, severity-rated with rationale, and anchored to the roadmap per the discovered-work placement discipline
```

- [ ] **Step 2: Verify**

Run: `grep -n "recorded and triaged" src/user/.agents/INSTRUCTIONS.md.template`
Expected: one hit on the step-9 line

- [ ] **Step 3: Commit**

```bash
git add src/user/.agents/INSTRUCTIONS.md.template
git commit -m "feat(instructions): checklist step 9 — discovered work triaged and anchored"
```

### Task 4: Align wait-for-pr-comments DEFER placement

**Files:**
- Modify: `src/user/.agents/skills/wait-for-pr-comments/SKILL.md` (the "DEFER placement (interactive only)" section, currently ~line 780; also fixes the stale `beads.md` I3 citation — the sibling test lives in the discovered-work rule)

- [ ] **Step 1: Replace this text:**

```markdown
### DEFER placement (interactive only)

Apply `beads.md` I3 sibling test:

- **Pass** (would have been on the parent epic's original plan) →
  `bd create --parent <parent-of-current-bead>`.
- **Fail or no parent** → orphan + `bd dep add <new-id> <bead-id>
  --type discovered-from`.
```

with:

```markdown
### DEFER placement (interactive only)

Apply the discovered-work rule (sibling test → anchored filing):

- **In scope** (would have been on the parent epic's original plan) →
  sibling: `bd create --parent <parent-of-current-bead>`, plus the rule's
  triage block and a Remaining-Work escalation in the completion report.
- **Out of scope** → anchor under the best-fit epic/milestone
  (`bd create --parent <anchor-id>`), plus `bd dep add <new-id> <bead-id>
  --type discovered-from` and the triage block. Orphan only when no
  milestone fits — escalate that in the report.
```

- [ ] **Step 2: Verify**

Run: `grep -n 'beads.md. I3\|Fail or no parent' src/user/.agents/skills/wait-for-pr-comments/SKILL.md`
Expected: no output, exit 1 (stale citation and orphan-default branch retired; the `.` in the pattern stands in for the backtick to avoid shell quoting issues)

- [ ] **Step 3: Commit**

```bash
git add src/user/.agents/skills/wait-for-pr-comments/SKILL.md
git commit -m "fix(skills): wait-for-pr-comments DEFER placement — anchored filing, drop stale beads.md I3 citation"
```

### Task 5: Consistency sweep (spec §5 verification)

**Files:** none (read-only assertions across `src/`)

- [ ] **Step 1: No instruction still prescribes orphan-as-default**

Run: `grep -rn "orphan + " src/ --include="*.md" --include="*.template"`
Expected: no output, exit 1

- [ ] **Step 2: The retired manifest shape is gone**

Run: `grep -rn "Recorded In" src/ --include="*.md" --include="*.template"`
Expected: no output, exit 1

- [ ] **Step 3: Vocabulary agreement across the four files**

Run: `grep -rlni "triage" src/plugins/beads/.agents/rules/discovered-work.md src/user/.agents/skills/verify-checklist/SKILL.md src/user/.agents/skills/wait-for-pr-comments/SKILL.md src/user/.agents/INSTRUCTIONS.md.template`
Expected: all four paths listed (each file speaks the same triage vocabulary; case-insensitive — two files use it only lowercase)

- [ ] **Step 4: Spec agreement** — re-read spec §3.1–§3.4 against the diff (`git diff main...HEAD -- src/`); each spec requirement maps to a hunk; no hunk contradicts the spec. Record any mismatch instead of papering over it.

- [ ] **Step 5: Commit any fixes surfaced by the sweep** (if none, no commit)
