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

Closed beads can carry a forwarding pointer to a derivative bead via a
`produced-bead-<Y-id>` label, stamped by upstream workflows when a bead
is closed and a new bead is produced from it. This preflight runs
before the molecule existence probe (Step 2) so closed beads with such
a pointer don't silently fall through to molecule resumption or
Routes A/B/C.

The logic lives in a sibling helper script that is pure-read (no `bd`
writes) and emits a single `decision=...` line on stdout. The agent
runs the helper alongside the skill and acts on the returned decision.

The helper exits non-zero on the `decision=halt reason=error` branch
(per its F6 contract). Under `set -e` this would abort the caller before
it could read the decision line, so capture stdout with a `|| true`
guard to preserve the line on every exit code:

```bash
# Safe capture: preserve stdout even when the helper exits non-zero on
# the error halt branch (set -e contexts).
decision_line=$(./closed-bead-preflight.sh <target-id> 2>/dev/null) \
  || true

# On a forward, the next call passes the original target and updated chain
# (same safe-capture pattern):
decision_line=$(./closed-bead-preflight.sh <Y-id> \
    --original=<original-id> --chain=<csv> 2>/dev/null) \
  || true
```

Interpret `decision_line`:

| Decision | Action |
|----------|--------|
| `decision=proceed` | Fall through to Step 2 unchanged. |
| `decision=forward target=<Y> chain=<csv>` | Re-enter Step 1 with `<target> = <Y>`; pass `--chain=<csv>` and the unchanged `--original=<id>` to the helper on the next invocation. The original target stays fixed across forwards. |
| `decision=friendly-exit current=<bead-id>` | Emit `Bead <bead-id> is closed. Did you mean a different bead?` to the user; stop. |
| `decision=halt reason=dangling original=<id> intermediate=<X> y=<Y>` | Emit reply text and add an audit comment on the **original target** (template below). |
| `decision=halt reason=multiple original=<id> intermediate=<X> labels=<csv>` | Emit reply text and add an audit comment on the **original target** (template below). |
| `decision=halt reason=cycle original=<id> chain=<csv>` | Emit reply text and add an audit comment on the **original target** (template below). |
| `decision=halt reason=error message=<terse>` | The probe failed (e.g. `bd show` returned non-zero). Surface the message; stop. |

Audit-comment templates — always target the **original** target, not
the intermediate chain bead:

```bash
# dangling
bd comments add <original-id> "Route Z halt (dangling label): produced-bead-<Y> on <intermediate> points to non-existent <Y>. Investigate label correctness or bead deletion."

# multiple
bd comments add <original-id> "Route Z halt (multiple labels): <intermediate> carries N produced-bead-* labels: <list>. Cannot determine which Y is canonical. Manual triage required."

# cycle
bd comments add <original-id> "Route Z halt (cycle): produced-bead-* chain visits a bead twice. Chain so far: <ordered-list>. Manual triage required."
```

The friendly-exit suffix `is closed. Did you mean a different bead?`
is the helper's exact deterministic output for the no-`produced-bead-*`
branch on a closed bead, and it is the canonical phrasing the agent
relays to the user. Do NOT add `human` to any bead in any branch — the
user is present to read audit comments and the reply directly.

### Step 2: Check for Existing Molecule

Once Step 1.5 has cleared (the bead is open, or Route Z has forwarded
to an open Y), **run the Step 2.5 / Route D trigger check before any
other action in this step**. Route D's detection probe (`HUMAN_SELF`
and `HUMAN_BLOCKER_COUNT` in §2.5) is non-destructive — a pair of
`bd label list` / `bd show --json` reads. If either trigger fires
(`HUMAN_SELF=yes` OR `HUMAN_BLOCKER_COUNT>0`), JUMP straight to Step 2.5
and dispatch to `resolve-human-bead`; do NOT execute the molecule-count
branching below. A paused (human-blocked) bead with one or more active
molecules must NOT be silently resumed via the length-1 path — Route D
gates ALL routing actions, including molecule resume.

Once the Route D trigger check has cleared (no human label on the bead
itself, no open human-labeled blockers), check if an active molecule
already exists for this bead before evaluating any of Routes A/B/C. Use
the `for-bead-<bead-id>` label (stamped by Route C on wisp and by
`implement-bead` on pour) and query with `--json`:

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
  unlabeled in-progress work. Execute the **Human-Escalation Pattern
  (HEP)** — defined in `docs/specs/bead-pipeline-architecture.md` §5.6
  and summarized in the **HEP section** of
  `src/plugins/beads/.claude/rules/beads.md`. Do NOT bare-stamp `human`
  on the source bead; the single-bead-`human` invariant requires the
  escalation bead to be the sole carrier of `human`:
  ```bash
  bd comments add <bead-id> "Probe returned no labeled molecules, but I suspect an unlabeled molecule exists because: <reason>."
  # Container detection: containers get the human bead as a CHILD via
  # `--parent` (sidesteps bd's cross-type `blocks` epic wall);
  # non-containers get a sibling human bead with a `blocks` dep.
  SRC_TYPE=$(bd show <bead-id> --json | jq -r '.[0].issue_type // "task"')
  case "$SRC_TYPE" in
      epic|milestone) IS_CONTAINER=1 ;;
      feature)
          SRC_ACTIVE_CHILDREN=$(bd list --parent <bead-id> \
              --status open,in_progress --limit 0 --json \
              | jq '[.[] | select(((.labels // []) | (index("merge-gate") or index("human"))) | not)] | length')
          [ "$SRC_ACTIVE_CHILDREN" -gt 0 ] && IS_CONTAINER=1 || IS_CONTAINER=0 ;;
      *) IS_CONTAINER=0 ;;
  esac
  # dual-shape contract: bd create --json may emit either {id:...} or [{id:...}]
  if [ "$IS_CONTAINER" = "1" ]; then
    HUMAN_ID=$(bd create --parent <bead-id> --no-inherit-labels \
        --title "Human input needed: suspected unlabeled molecule on <bead-id>" \
        --type task \
        --priority "$(bd show <bead-id> --json | jq -r '.[0].priority')" \
        --description "<reason the unlabeled molecule is suspected; what evidence in the bead history points to it>" \
        --json | jq -r 'if type == "array" then .[0].id else .id end // empty')
  else
    HUMAN_ID=$(bd create \
        --title "Human input needed: suspected unlabeled molecule on <bead-id>" \
        --type task \
        --priority "$(bd show <bead-id> --json | jq -r '.[0].priority')" \
        --description "<reason the unlabeled molecule is suspected; what evidence in the bead history points to it>" \
        --json | jq -r 'if type == "array" then .[0].id else .id end // empty')
  fi
  [ -z "$HUMAN_ID" ] && { echo "HEP: failed to extract escalation bead id" >&2; exit 1; }
  bd label add "$HUMAN_ID" human
  bd update "$HUMAN_ID" --append-notes \
      "Source: <bead-id>
  Step-bead: N/A (pre-pour)
  Molecule: <unknown — probe returned 0 labeled molecules>
  Worktree: N/A
  Scenario hint: architectural-rework"
  # Non-containers: dep-block the source. Containers gate via parent-child
  # plus Rule C invariant (containers MUST NOT carry readiness labels).
  if [ "$IS_CONTAINER" = "0" ]; then
      bd dep add <bead-id> "$HUMAN_ID"
  fi
  ```
  Exit cleanly. Otherwise proceed to Step 3.

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

  If the molecules cannot be cleanly disambiguated, escalate via the
  **Human-Escalation Pattern (HEP)** — defined in
  `docs/specs/bead-pipeline-architecture.md` §5.6 and summarized in the
  **HEP section** of `src/plugins/beads/.claude/rules/beads.md`. Do NOT
  bare-stamp `human` on the source bead; the single-bead-`human`
  invariant requires the escalation bead to be the sole carrier of
  `human`. Carry your multi-molecule analysis into the escalation
  bead's notes so the human sees your read-out, not a blank flag:
  ```bash
  # Container detection: containers get the human bead as a CHILD via
  # `--parent`; non-containers get a sibling human bead + `blocks` dep.
  SRC_TYPE=$(bd show <bead-id> --json | jq -r '.[0].issue_type // "task"')
  case "$SRC_TYPE" in
      epic|milestone) IS_CONTAINER=1 ;;
      feature)
          SRC_ACTIVE_CHILDREN=$(bd list --parent <bead-id> \
              --status open,in_progress --limit 0 --json \
              | jq '[.[] | select(((.labels // []) | (index("merge-gate") or index("human"))) | not)] | length')
          [ "$SRC_ACTIVE_CHILDREN" -gt 0 ] && IS_CONTAINER=1 || IS_CONTAINER=0 ;;
      *) IS_CONTAINER=0 ;;
  esac
  # dual-shape contract: bd create --json may emit either {id:...} or [{id:...}]
  if [ "$IS_CONTAINER" = "1" ]; then
    HUMAN_ID=$(bd create --parent <bead-id> --no-inherit-labels \
        --title "Human input needed: multiple active molecules on <bead-id>" \
        --type task \
        --priority "$(bd show <bead-id> --json | jq -r '.[0].priority')" \
        --description "N active molecules for this bead; cannot cleanly disambiguate.
  - <mol-id-1> (<formula>, status=<s>, updated <ts>): <analysis>
  - <mol-id-2> (<formula>, status=<s>, updated <ts>): <analysis>
  Assessment: <duplicative | legacy | needs manual merge>
  Recommended action: <resume X / burn Y / user decides>" \
        --json | jq -r 'if type == "array" then .[0].id else .id end // empty')
  else
    HUMAN_ID=$(bd create \
        --title "Human input needed: multiple active molecules on <bead-id>" \
        --type task \
        --priority "$(bd show <bead-id> --json | jq -r '.[0].priority')" \
        --description "N active molecules for this bead; cannot cleanly disambiguate.
  - <mol-id-1> (<formula>, status=<s>, updated <ts>): <analysis>
  - <mol-id-2> (<formula>, status=<s>, updated <ts>): <analysis>
  Assessment: <duplicative | legacy | needs manual merge>
  Recommended action: <resume X / burn Y / user decides>" \
        --json | jq -r 'if type == "array" then .[0].id else .id end // empty')
  fi
  [ -z "$HUMAN_ID" ] && { echo "HEP: failed to extract escalation bead id" >&2; exit 1; }
  bd label add "$HUMAN_ID" human
  bd update "$HUMAN_ID" --append-notes \
      "Source: <bead-id>
  Step-bead: N/A (pre-pour)
  Molecule: <mol-id-1>, <mol-id-2>, ...
  Worktree: N/A
  Scenario hint: architectural-rework"
  # Non-containers: dep-block the source. Containers gate via parent-child
  # plus Rule C invariant (containers MUST NOT carry readiness labels).
  if [ "$IS_CONTAINER" = "0" ]; then
      bd dep add <bead-id> "$HUMAN_ID"
  fi
  ```
  Exit cleanly. Do NOT silently pick one.

See `rules/beads-labels.md` ("Molecule → bead linkage convention") for the full
rationale and the stamp procedure.

### Step 2.5: Route D — bead carries `human` or is blocked by `human`

Route D **AUTO-INVOKES** the `resolve-human-bead` skill in the current
session via the Skill tool before any of Routes A/B/C are considered. The
user sees one continuous flow — no second `/resolve-human-bead` invocation
is required.

Authority: this route implements the **Human-Escalation Pattern (HEP)**
defined in `docs/specs/bead-pipeline-architecture.md` §5.6 and summarized
in the HEP section of `src/plugins/beads/.claude/rules/beads.md`. Cite
arch §5.6 and the beads.md HEP section as authoritative.

**Trigger** — fire Route D when EITHER:

- **bead-itself-human** — the target bead has `human` label (i.e. the
  bead itself carries the human-attention tag), OR
- **bead-blocked-by-human** — the target bead has at least one open
  `bd dep` blocker that carries `human` (a human-labeled blocker
  paused this bead).

Detection (run as the **first action of Step 2** before any
molecule-count branching, per the Route D gate referenced at the top of
Step 2; non-destructive `--json` reads only):

```bash
# Bead itself carries human?
HUMAN_SELF=$(bd label list <bead-id> --json | jq -e 'index("human")' >/dev/null && echo yes || echo no)

# How many open human-labeled blockers does this bead have?
# Route D fires when HUMAN_BLOCKER_COUNT > 0; the count is also used in
# the surface message so the user sees up front whether the skill will
# pivot directly (count=1) or list-and-prompt (count>1).
HUMAN_BLOCKER_COUNT=$(bd show <bead-id> --json \
  | jq -r '.[0].dependencies[]? | select(.dependency_type=="blocks") | .id' \
  | while read blocker; do
      BSTATE=$(bd show "$blocker" --json | jq -r '.[0].status')
      [ "$BSTATE" = "closed" ] && continue
      bd label list "$blocker" --json | jq -e 'index("human")' >/dev/null && echo "$blocker"
    done | wc -l | tr -d ' ')
```

Note: Route D does NOT pick a specific blocker id from this list — the
source bead id is what gets passed to `resolve-human-bead`, and the
skill's Probe 6 (source-bead pivot) re-runs the same detection and
handles both the single-blocker (auto-pivot) and multi-blocker
(list-and-prompt) cases.

`select(.dependency_type=="blocks")` is the verified jq path on `bd show
--json`'s `dependencies[]` field; `.id` is the verified id field on each
dep object. (Do NOT use `select(.type=="blocks") | .issue_id` here —
that is `bd ready --json`'s dependency-record shape, NOT `bd show
--json`'s, and returns empty silently.) The canonical detection probe
is documented in the `resolve-human-bead` skill — Route D's detection
MUST stay in sync with it.

**Action** — Route D auto-invokes the `resolve-human-bead` skill via the
Skill tool, passing the **source bead id** (i.e. the `<bead-id>` that
`start-bead` was invoked with) unconditionally — regardless of trigger
or blocker count:

- **bead-itself-human** — the skill sees a `human`-labeled target and
  proceeds with its normal class-detection path (Probes 1–5).
- **bead-blocked-by-human** — the skill's source-bead-pivot (Probe 6)
  re-runs the canonical detection probe on the source's blockers; if
  exactly one open `human`-labeled blocker exists it pivots
  automatically, and if more than one exists it lists all blockers
  with one-line context and prompts the user to pick one per
  invocation.

Passing the source bead unconditionally keeps Route D branch-free and
preserves the multi-blocker list-and-prompt UX — passing only the
first blocker would bypass that prompt and silently pick one for the
user.

Merge-gate hand-off sub-class beads (also `human`-labeled) flow through
Route D naturally — Route D dispatches to the skill, which then routes
to Scenario G per the class-detection priority.

**Surface message** — print exactly one line before invoking the skill.
For the `bead-blocked-by-human` trigger, include the count of open
`human`-labeled blockers detected so the user sees up front whether a
multi-blocker prompt is about to appear:

```
Route D: <id> is human-labeled. Invoking resolve-human-bead on source...
Route D: <id> is blocked by <N> human-labeled bead(s). Invoking resolve-human-bead on source...
```

Then invoke the `resolve-human-bead` skill via the Skill tool. Do NOT
fall through to Routes A/B/C; Route D's dispatch is the terminal action
for this `start-bead` invocation.

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

Do NOT commit or push unless explicitly instructed by the user.  Definitely do not violate branch protection rules unless given explicit permission for this specific change.

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
lookup label (see `rules/beads-labels.md` "Molecule → bead linkage convention"):
```bash
bd mol wisp create brainstorm-bead --var bead-id=<bead-id> --var title-slug=<slug>
# Capture the wisp-id from the command output, then:
bd label add <wisp-id> for-bead-<bead-id>
```

The `<slug>` is generated from the source bead's title using the canonical
slug generation algorithm:
1. Lowercase the source bead's title
2. Replace spaces with hyphens
3. Strip all characters except a-z, 0-9, and hyphens
4. Collapse consecutive hyphens to a single hyphen
5. Truncate to a maximum of 30 characters
6. Strip leading and trailing hyphens
7. Fallback: if the result is empty (e.g., the title contained only non-ASCII characters or symbols), apply steps 1–6 to the bead-id instead. (Dots and other non-[a-z0-9-] characters in the bead-id are stripped by step 3, so `agents-config-abn9.7` → `agents-config-abn97`.)

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

*"A closed bead with ≥2 `produced-bead-*` labels does NOT route — it halts."*

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
| The bead is closed, just give up | Run Step 1.5. If the helper says forward, route to the new target. Otherwise, friendly exit. Never silently fall through. |

### Recovery: if you land in `superpowers:writing-plans`

If you hit `superpowers:writing-plans` and see its execute-plan vs
`superpowers:subagent-driven-development` menu while on a bead, STOP. The
bead is the plan. Ensure `brainstormed` + `implementation-ready` labels
exist, then invoke `implement-bead`. Pick neither menu option.
