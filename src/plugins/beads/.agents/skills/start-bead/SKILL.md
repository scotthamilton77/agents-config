---
name: start-bead
description: >
  Use when the user points at a specific bead and wants to start work on it,
  or when routing a bead from create to the right workflow. Evaluates the bead
  and routes to: brainstorm formula (if spec incomplete), implement-bead skill
  (if implementation-ready), or inline execution (if trivial).
model: opus[1m]
effort: xhigh
---

# start-bead

Evaluate a bead and route it to the right workflow. The traffic cop of the pipeline.

## When to Use

- User says "start on xyz", "let's work on proj-42", "pick up that bug"
- After `bd ready` when the user selects a specific bead to begin
- Programmatically from `run-queue` for implementation-ready beads

## The Process

### Step 1: Read the Bead

```bash
bd show <bead-id>
bd label list <bead-id>
```

Note: type, status, labels, AC, description, dependencies.

### Step 1.5: Closed-bead preflight

Before the molecule existence probe (Step 2), short-circuit on closed
beads. All current routes assume an open bead; Step 2 in particular
would mis-handle stale `for-bead-<X-id>` molecules on a closed X (e.g.,
a brainstorm-bead wisp left over after the source bead closed). The
preflight runs BEFORE Step 2 so closed-bead handling cannot fall
through to molecule resumption or Routes A/B/C.

This section also documents **Route Z**: the forward path when a closed
source bead carries `produced-bead-<Y-id>` (stamped by the
brainstorm-bead redesign in `agents-config-12q7` when finalize closes X
and creates a new implementation bead Y). Route Z forwards routing to Y
so the user lands on the active bead instead of dead-ending on the
closed source.

#### Original-target convention

Across Route Z re-entries, the agent maintains a reference to the bead
ID the user **originally** invoked `start-bead` against. The R5/R7/R8
audit comments (dangling label, multiple labels, cycle) target the
**original** target — not the intermediate chain bead where the halt
was detected. The friendly-exit message (R6), in contrast, uses the
**current** target (relevant at the tail of a chain X → Y → Z when Z
is closed without `produced-bead-*`).

#### R2: Status check (gate)

If `status != "closed"`, proceed to Step 2 unchanged. Open beads pass
through Step 1.5 with no side effects. Otherwise (`status == "closed"`),
evaluate `produced-bead-*` labels (R3–R8 below).

#### R3: Produced-bead-* extraction probe (closed bead only)

Use the JSON contract — NOT the text-formatted `bd label list` output,
which has no documented stability contract:

```bash
PRODUCED=$(bd show "<X-id>" --json \
  | jq -r '.[0].labels[]? | select(startswith("produced-bead-")) | sub("^produced-bead-"; "")')
COUNT=$(printf '%s\n' "$PRODUCED" | grep -c .)
```

Branch on `COUNT`:

- `COUNT == 0` → R6 friendly-exit path.
- `COUNT == 1` → R4 forward path with the single Y-id in `$PRODUCED`.
- `COUNT >= 2` → R7 multiple-labels halt.

#### R4: Forward path (Route Z) — re-enter Step 1 with Y as new target

When `COUNT == 1`, take `<Y-id>` (the single value in `$PRODUCED`) and
verify Y exists with the exact probe:

```bash
bd show "<Y-id>" --json 2>/dev/null \
  | jq -e --arg yid "<Y-id>" '.[0].id == $yid' >/dev/null
```

- **Probe succeeds** → forward: set `target = <Y-id>` and **re-enter
  Step 1** with `<Y-id>` as the new target. Re-entry at Step 1 (NOT
  Step 3) ensures Y also passes through the closed-bead preflight
  (chain handling), the molecule existence probe (Y might have an
  active `implement-feature` pour), and full route evaluation.
- **Probe fails** → R5 dangling-label halt.

Forwarding is agent prose, NOT a Skill-tool re-invocation and NOT a
child-process recursion — the agent simply continues with the new
target.

#### R5: Dangling-label halt

When the `produced-bead-<Y-id>` label points to a non-existent Y,
add an audit comment on the **original target** (not the intermediate
chain bead where the halt was detected):

```bash
bd comments add <original-target-id> "Route Z halt (dangling label): produced-bead-<Y-id> on <intermediate-X-id> points to non-existent <Y-id>. Investigate label correctness or bead deletion."
```

Emit agent reply text:

> `start-bead halted: bead <intermediate-X-id> carries produced-bead-<Y-id> but <Y-id> does not exist. Investigate the label and re-invoke start-bead when fixed.`

Do NOT add `human` to any bead (HEP non-applicability — Route Z's
failure modes don't fit the HEP escalation pattern: the source bead is
closed, `start-bead` is interactive routing, the user is present to
read the audit comment + reply directly). Do NOT modify any other bead
state.

#### R6: Closed-without-produced-bead friendly exit

When the bead is closed and has NO `produced-bead-*` label, emit agent
reply text using the **current** target's id (NOT the original — this
matters when arriving here at the tail of a chain):

> `Bead <current-target-id> is closed. Did you mean a different bead?`

The exact suffix `is closed. Did you mean a different bead?` is
canonical and verifiable; the `<current-target-id>` prefix is templated
with the actual id at runtime.

A bead closed normally (work completed, superseded, abandoned) is not
an error condition — the user has just pointed at a finished bead. Do
NOT modify any bead state. Do NOT add `human`. Do NOT add an audit
comment. `start-bead` exits cleanly (no Step 2, no Step 3).

Stale unlabeled molecules on a closed bead are NOT investigated by
Route Z — closed beads are terminal from start-bead's perspective. Use
`bd mol list` if cleanup is needed.

#### R7: Multiple-labels halt

When X carries `>= 2` `produced-bead-*` labels, add an audit comment on
the **original target**:

```bash
bd comments add <original-target-id> "Route Z halt (multiple labels): <intermediate-X-id> carries N produced-bead-* labels: <list>. Cannot determine which Y is canonical. Manual triage required."
```

Emit agent reply text naming the conflicting labels. Do NOT modify any
other bead state.

#### R8: Cycle detection via visited-set

The agent maintains a **visited-set** of bead IDs across the whole
`start-bead` invocation. NOT a depth/hop counter — a visited-set
strictly dominates: it detects cycles AND naturally bounds depth (chain
length cannot exceed the number of distinct beads in the
`produced-bead-*` graph).

The visited-set is agent-local per-invocation state; it is not
persisted to bead state.

**Three loop invariants (all MUST hold):**

1. On the very first entry to Step 1.5 for a given `start-bead`
   invocation, the visited-set is initialized with the **original
   target's id** BEFORE R3 evaluates.
2. At the **top of every Step 1.5 R3 evaluation** (i.e., on initial
   entry AND on every re-entry triggered by R4 forwarding), the agent
   checks whether the current target is already in the visited-set.
3. R4 forwarding adds `<Y-id>` to the visited-set BEFORE re-entering
   Step 1, so the next Step 1.5 evaluation sees Y as visited.

When the current target is already in the visited-set, halt with an
audit comment on the **original target**:

```bash
bd comments add <original-target-id> "Route Z halt (cycle): produced-bead-* chain visits <current-target-id> twice. Chain so far: <ordered-list>. Manual triage required."
```

Emit agent reply text naming the cycle path (the ordered list of
visited bead IDs). Do NOT modify any other bead state.

### Step 2: Check for Existing Molecule

Before doing anything else, check if an active molecule already exists for
this bead. Use the `for-bead-<bead-id>` label (stamped by Route C on wisp
and by `implement-bead` on pour) and query with `--json`:

```bash
bd list --label for-bead-<bead-id> --type molecule --json \
  | jq '[.[] | select(.status != "closed")]'
```

Why this shape — two bugs motivate every character:
- `--json` bypasses the tree-text path, which silently drops `--type` and
  seeds the queried id into results (beads `2dx`).
- The label is the only reliable bead→molecule edge; `bd mol pour` does
  not set `parent = <bead-id>`, so `bd list --parent <bead-id>` returns
  `[]` even when a molecule exists (beads `lp3`).

Decide from the result array:

- **length 0** → no active molecule. BUT if you suspect a pre-convention
  or otherwise unlabeled molecule exists (prior activity visible in the
  bead's history, user references one), STOP — do NOT pour/wisp over
  unlabeled in-progress work. Escalate:
  ```bash
  bd comments add <bead-id> "Probe returned no labeled molecules, but I suspect an unlabeled molecule exists because: <reason>."
  bd label add <bead-id> human
  ```
  Otherwise proceed to Step 3.

- **length 1** → extract and resume:
  ```bash
  MOL_ID=$(bd list --label for-bead-<bead-id> --type molecule --json \
    | jq -r '[.[] | select(.status != "closed")] | .[0].id')
  bd mol current "$MOL_ID"
  ```
  Then execute the current step. Do NOT create a new molecule.

- **length 2+** → analyze first; don't escalate blindly. Multiple
  non-closed molecules for one bead is legitimate when distinct formulas
  coexist (a lingering brainstorm-bead wisp alongside an
  implement-feature pour) or when parallel agents share the same Dolt
  server. Inspect each:
  ```bash
  bd list --label for-bead-<bead-id> --type molecule --json \
    | jq '[.[] | select(.status != "closed")
               | {id, title, status, updated_at, created_at}]'
  ```
  Resolve if one clearly supersedes the others — an open
  implement-feature/fix-bug pour supersedes a stale brainstorm-bead
  wisp; a more recent pour supersedes an abandoned earlier one. Resume
  the winner and tell the user your reasoning in the routing message;
  the user can burn the loser later.

  If the molecules cannot be cleanly disambiguated, escalate WITH your
  analysis — the human should see your read-out, not a blank flag:
  ```bash
  bd comments add <bead-id> "N active molecules for this bead:
    - <mol-id-1> (<formula>, status=<s>, updated <ts>): <analysis>
    - <mol-id-2> (<formula>, status=<s>, updated <ts>): <analysis>
    Assessment: <duplicative | legacy | needs manual merge>
    Recommended action: <resume X / burn Y / user decides>"
  bd label add <bead-id> human
  ```
  Do NOT silently pick one.

See `rules/beads.md` ("Molecule → bead linkage convention") for the full
rationale and the stamp procedure.

### Step 3: Route the Bead

Evaluate the bead against these criteria in order:

---

**ROUTE A: Already implementation-ready**

Condition: has label `implementation-ready`

Action: check for a same-session readier label.

1. Get your current session ID from the `<session-info>` system tag and
   take its first 8 hex characters (e.g. `62d06423`).
2. Run `bd label list <bead-id>` and look for a label of the form
   `implementation-readied-session-<your-sid-prefix>`.
3. Decide:
   - **Label present** (you are the session that readied this bead):
     STOP. The default is hand-off to run-queue. Invoke `implement-bead`
     only on explicit user authorization; silent continuation is not
     permitted.
   - **Label absent** (another session readied it, or it was readied via
     a path that doesn't stamp the session label — e.g. manual
     `bd label add` or import): invoke `implement-bead` directly.

---

**ROUTE B: Trivial — no formula needed**

Condition: ALL of the following are true:
- Change touches ≤ 3 files
- No new tests required
- No worktree needed (too small to warrant isolation)
- No architectural implications
- Completable in a single focused turn

Action: do it inline. No formula, no molecule. The inline route still
owes the bead's lifecycle the same claim/close invariants the formulas
enforce — do NOT skip them just because the work is small.

Before starting:

```bash
bd update <id> --status in_progress

# Walk parent chain; mark each ancestor epic in_progress
PARENT=$(bd show <id> --json | jq -r '.[0].parent // empty')
while [ -n "$PARENT" ]; do
  bd update "$PARENT" --status in_progress
  PARENT=$(bd show "$PARENT" --json | jq -r '.[0].parent // empty')
done
```

After finishing:

```bash
bd close <id> --reason "<one-line summary>"

# Walk parent chain; close each ancestor whose remaining children are all closed
PARENT=$(bd show <id> --json | jq -r '.[0].parent // empty')
while [ -n "$PARENT" ]; do
  NON_CLOSED=$(bd list --parent="$PARENT" --json | jq '[.[] | select(.status != "closed")] | length')
  [ "$NON_CLOSED" = "0" ] || break
  bd close "$PARENT" --reason "All children closed"
  PARENT=$(bd show "$PARENT" --json | jq -r '.[0].parent // empty')
done
```

If in doubt, it is NOT trivial. Use Route C.

---

**ROUTE C: Needs brainstorming**

Condition: anything that does not meet Route A or B criteria.
This is the default route for feature, task, and chore beads without full specs.

The bead's claim walk (I1 in `rules/beads.md`) is handled by the
brainstorm-bead formula's first step (`claim`) — you do not need to
claim the bead manually here; driving the molecule will run the claim
step and mark the bead (and parent chain) `in_progress` before `assess`.

Action: wisp the brainstorm-bead formula, then stamp the bead→molecule
lookup label (see `rules/beads.md` "Molecule → bead linkage convention"):
```bash
bd mol wisp create brainstorm-bead --var bead-id=<bead-id>
# Capture the wisp-id from the command output, then:
bd label add <wisp-id> for-bead-<bead-id>
```

Then drive the molecule as the MAIN AGENT (brainstorming requires
interactive conversation with the user — do NOT dispatch a subagent):

1. `bd mol current <wisp-id>` — shows all steps with status markers
2. For the first `[ready]` step:
   - `bd update <step-id> --claim` — lock as in_progress
   - `bd show <step-id>` — read the step's instructions
   - Execute the step (interactive conversation for the discuss step)
   - `bd close <step-id> --continue` — closes and auto-claims the next step
3. Repeat until all steps show `[done]`.

Use the step IDs reported by `bd mol current` — do NOT synthesize
`<root>.<step>` patterns. Step IDs are independent hash-based identifiers.

After the formula completes, the bead will have the `implementation-ready`
label and will be picked up by `run-queue`, or the user can invoke
`implement-bead` directly.

### Failure mode: 0/0 steps after wisp creation

If `bd mol current <wisp-id>` shows "0/0 steps complete" with no step
list, the formula is missing `pour = true`. Recover with:

```bash
bd mol burn <wisp-id>
```

Tell the user it is a formula bug (child step beads were not materialized).
Do NOT fall back to invoking the brainstorming skill inline — that bypasses
the state tracking the molecule exists to provide.

For mid-run abandonment of a **poured** molecule (real progress was made,
but the molecule needs to stop), prefer:

```bash
bd mol squash <mol-id> --summary "Aborted: <reason>"
```

to preserve history for debugging. Squash is only for poured molecules —
wisps (including `brainstorm-bead`) have ephemeral state, so `bd mol burn`
is the right recovery for any wisp abandonment.

### Hand-off: stop at implementation-ready

When the brainstorm formula completes and the bead has `implementation-ready`
and `brainstormed` labels, STOP. The default path is: another agent
(run-queue, in a dedicated session) picks up the implementation.

Do NOT invoke `implement-bead` in this session unless the user:
- Explicitly directs you to ("implement it now", "do X next"), OR
- Explicitly agrees when you ask.

Do NOT re-invoke `start-bead` on this bead in this session — that can send
you back through Route A and blur this hand-off, especially if session
context is lost.

Asking is acceptable when the user's intent is unclear. Silent assumption
that brainstorming means "also implement" is not.

---

### Step 4: Report routing decision

Before acting, briefly tell the user what you're doing and why:
> "This bead looks [fully specified / trivial / needs clarification].
>  Routing to [implement-bead / inline / brainstorm formula]."

Exception: if it's obviously trivial, just do it without announcing.

## Routing Decision Table

| Status | Has `produced-bead-*` | Has `implementation-ready` | Trivial | Route |
|--------|-----------------------|----------------------------|---------|-------|
| closed | yes (exactly 1)       | —                          | —       | **Z** (forward to Y) |
| closed | no                    | —                          | —       | exit (friendly message) |
| open   | —                     | yes                        | —       | A |
| open   | —                     | no                         | yes     | B |
| open   | —                     | no                         | no      | C |

*"A closed bead with ≥2 `produced-bead-*` labels does NOT route — it halts per R7 (multiple-labels manual triage)."*

## Red Flags

| Thought | Reality |
|---------|---------|
| "I'll just start implementing, it seems clear enough" | Run the router. Don't shortcut. |
| "The bead has some AC, close enough" | Has `implementation-ready` label? No? Then Route C. |
| "I'll do a quick brainstorm in-line without the formula" | No. The formula provides state tracking and spec review. |
| "This molecule looks incomplete, I'll create a new one" | Resume the existing molecule first. |
| "The molecule looks empty, I'll just do the work inline" | STOP. 0/0 = formula bug. Burn (`bd mol burn <wisp-id>`) + report, do not bypass. |
| "I'll make up step IDs — they look like `<root>.<step>`" | No. Use IDs from `bd mol current` output. |
| "After brainstorming, I should invoke `writing-plans` next" | No. The bead is the plan. Default is hand-off to run-queue; only invoke `implement-bead` with explicit user authorization or in a separate run-queue session. |
| "Brainstorming is done, I'll implement next as a natural continuation" | No. Default is hand-off to run-queue. Stop unless explicitly authorized. |
| The bead is closed, just give up | Run Step 1.5. If produced-bead-<Y> exists, Route Z forwards to Y. Otherwise, friendly exit referencing the current target. Never silently fall through. |

### Recovery: if you land in `superpowers:writing-plans`

If you hit `superpowers:writing-plans` and see its execute-plan vs
`superpowers:subagent-driven-development` menu while on a bead, STOP. The
bead is the plan. Ensure `brainstormed` + `implementation-ready` labels
exist, then invoke `implement-bead`. Pick neither menu option.
