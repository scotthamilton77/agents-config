---
description: Analyze the current session for what made it slower, more error-prone, or less correct, and propose weighted corrective actions to improve future sessions. Makes no changes until explicitly approved. Use at session end or when the user types /retrospect.
argument-hint: [--focus <area> | --since <marker>]
disable-model-invocation: true
---

Analyze the current session, identify what made it slower, more error-prone, or
less correct than it should have been, and propose weighted corrective actions
that would improve **future** sessions. Present recommendations for approval.
Make **no changes** until the user explicitly authorizes.

## Argument

Optional scope filter for this retrospective: $ARGUMENTS

Recognized forms:

- **Empty** — full-session retrospective covering all categories below.
- **`--focus <area>`** — restrict analysis to one area (e.g. `--focus tooling`,
  `--focus user-communication`, `--focus tests`, `--focus rules`).
- **`--since <marker>`** — retrospect only from a point in the session
  (e.g. `--since "first PR push"`, `--since "after compaction"`). The agent
  picks the closest matching anchor in conversation history.

## Core principle: recurring over bespoke

A finding is **worth reporting** only if it is likely to recur in other
sessions, on other projects, or with other agents. Reject anything that
is purely session-local trivia ("the file path I guessed was wrong on
turn 14"). Report patterns ("the agent guessed file paths twice without
running a search first — recurring habit, not a one-off slip").

A useful screening test for each candidate finding:

- **Recurrence test**: Could this same problem happen in a different session
  on different work? If no, drop it.
- **Surprise test**: Was the friction caused by something a future agent
  would *also* not know or *also* get wrong? If no, drop it.
- **Transferability test**: Is the corrective action portable beyond this
  session's specific task? If no, downgrade or drop.

If everything fails the screen, say so. An empty retrospective is a valid
outcome and far better than padded recommendations.

## Phase 1 — Evidence gathering

Walk the session and collect concrete evidence in each of the following
buckets. Quote or cite turns where possible (paraphrase is fine — the goal is
traceability, not transcription).

1. **User redirects and corrections** — explicit "no", "stop", "wrong",
   "instead", "actually", "you missed", "you should have", as well as quieter
   signals (user re-asks the same question, user accepts grudgingly, user
   rewrites the agent's output before using it).
2. **Dead-end tool sequences** — reads of files that turned out irrelevant,
   repeated searches that returned the same nothing, retries against the same
   failing approach, exploratory passes that produced no decision.
3. **Token-waste patterns** — overlong outputs, redundant context-gathering
   (re-reading a file already in context), verification theater (running a
   check the agent already knew would pass), narration of internal
   deliberation, repeated background.
4. **Skipped or missed discipline** — skills, rules, agents, or workflows
   that should have been invoked and were not; completion-gate steps glossed
   over; verification claims made without evidence; the canonical decision
   matrix bypassed.
5. **Architectural friction surfaced during the work** — code or
   configuration that resisted the change, abstractions that leaked, tests
   that were hard to write because the code was hard to test, documentation
   that was missing or wrong when consulted.
6. **Stale or wrong project/user assets** — rules that no longer match
   reality, memories that the session disproved, AGENTS.md / CLAUDE.md
   sections that misled the agent, command or skill descriptions that
   triggered (or failed to trigger) inappropriately.
7. **User-side communication patterns worth flagging** — ambiguous phrasing,
   missing context, assumed-shared vocabulary, instructions that produced a
   predictably wrong first pass. Frame as observations to discuss, never as
   blame.
8. **Dependency or tooling gaps** — versions out of date, missing CLI tools,
   environment quirks that ate cycles, MCP servers that timed out or were
   misconfigured.

Apply the **recurrence / surprise / transferability** screen to every item
collected. Discard the bespoke; keep the recurring.

## Phase 2 — Categorize each surviving finding

For each surviving finding, classify it by **corrective-action category**:

- **A. Project asset edit** — change to a checked-in file in this repo
  (AGENTS.md, CLAUDE.md, README.md, docs/, specs, source code).
- **B. User asset edit** — change to `~/.claude/`, `~/.codex/`, `~/.gemini/`,
  or this project's `src/user/.*` (which deploys to those locations).
- **C. New skill / agent / command / rule** — recurring pattern strong
  enough to deserve its own artifact.
- **D. Spec or design update** — bead description, design doc, ADR,
  acceptance criteria revision.
- **E. Code or architecture debt** — refactor, simplification, deletion of
  obsolete code, dependency bump.
- **F. Agent education via memory** — write to auto-memory under
  `~/.claude/projects/-Users-scott-src-projects-agents-config/memory/`
  (the file-based system documented in the user's AGENTS.md). Project-scoped
  lessons go here, indexed via that folder's `MEMORY.md`. Pick the right
  memory type (user / feedback / project / reference) per the rules in the
  global AGENTS.md.
- **G. User education / communication suggestion** — observation about how
  a future request could be phrased or scoped to land better. Suggest, do
  not prescribe. The user is in charge of their own communication style.
- **H. Tooling / dependency change** — install, upgrade, configure, or
  remove a CLI tool, MCP server, or environment piece.

A finding may carry more than one category if the corrective action spans
artifacts (e.g. a rule edit *and* a memory write).

## Phase 3 — Weight each finding

Score every surviving finding on four axes, then compute a composite
**impact rating** (High / Medium / Low) using the agent's judgment, not
arithmetic.

- **Recurrence likelihood** — how often will this pattern resurface?
- **Cost when it recurs** — minutes lost, tokens burned, errors shipped.
- **Cost to fix now** — small edit, medium refactor, or larger initiative.
- **Confidence** — strength of evidence; speculative findings get
  downgraded.

State the composite rating per finding and one short sentence explaining
the weighting.

## Phase 4 — Specify the execution mode per finding

Each recommendation **must** specify *how* the fix would be carried out if
approved. Pick one (or describe a small sequence) from:

- **Inline (this session)** — small file edits, single-target memory writes,
  one-line rule additions. Do it now after approval; bounded scope.
- **Subagent delegation (this session)** — medium-scope change with
  self-contained context (e.g. rewriting one skill, refactoring one module).
  Spawn a fresh subagent with the full corrective-action spec.
- **Future bead** — multi-step, design-needed, or cross-cutting work.
  Specify the proposed bead type (task / chore / feature / bug / spike /
  decision) and parent if it belongs under an existing milestone or epic.
  Quote the proposed title and one-line description.
- **Memory write** — for category F findings, name the proposed memory file
  (`feedback_*.md`, `project_*.md`, etc.) and give the proposed one-line
  MEMORY.md index entry.
- **User action** — for category G findings, frame as a suggestion the user
  can take or leave; the agent does nothing automatically.

If a single finding requires more than one mechanism (e.g. inline rule edit
*plus* a memory write recording why), enumerate the sequence in order.

## Phase 5 — Present recommendations for approval

Output a structured report with this shape:

```
## Retrospective summary

<one short paragraph: what this session did, where it spent its time,
whether it was efficient or not. Two or three sentences max.>

## Findings worth acting on

### Finding 1 — <short title>
- **Category**: <A–H, plus subtype if relevant>
- **Impact**: High | Medium | Low — <one-sentence justification>
- **Evidence**: <one or two specific session moments>
- **Proposed corrective action**: <what to change>
- **Execution mode**: <inline | subagent | future bead | memory write | user action>
- **Estimated cost**: <small | medium | large; rough wall-clock or token sense>

### Finding 2 — ...

(continue for each finding)

## Findings considered and dropped (transparency)

- <short line per dropped candidate and which test it failed>

## Approval requested

I will make no changes until you tell me which findings to act on. Reply with:
- "approve all"
- "approve <numbers>"   (e.g. "approve 1, 3, 5")
- "approve <numbers> with changes: ..." (modify before applying)
- "skip"
```

Sort findings **by impact descending**, then by execution-mode cost ascending
(cheaper fixes first within the same impact band).

## Phase 6 — Execute (only after approval)

If and only if the user approves specific findings, execute each approved
recommendation according to its declared execution mode. Respect normal
project workflow:

- Worktree isolation for non-trivial code changes (per the worktrees rule).
- Completion-gate discipline if any approved finding lands in code.
- For category F memory writes, use the file-based auto-memory system under
  `~/.claude/projects/-Users-scott-src-projects-agents-config/memory/` —
  create the memory file with the correct frontmatter and add the one-line
  pointer to `MEMORY.md`.
- For future-bead findings, run `bd create` with the type, priority,
  description, and any parent the recommendation specified. Do **not** start
  work on the new beads in the same turn; capture only.

After execution, emit a short closing report listing what changed, what
beads were filed, what memories were written, and what (if anything) the
user asked you to defer.

## Hard constraints

- **No changes before approval.** Phases 1–5 are read-only.
- **No padded recommendations.** Empty retrospective is a valid outcome.
- **No blame-framed user-education items.** Category G findings are framed
  as collaborative observations, never as corrections of the user.
- **No session-bespoke findings.** Apply the recurrence / surprise /
  transferability screen ruthlessly.
- **Cite evidence.** Every reported finding names the session moment(s)
  that surfaced it.
