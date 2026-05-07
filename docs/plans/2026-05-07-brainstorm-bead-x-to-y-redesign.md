# Brainstorm-bead formula redesign: produce net-new implementation bead, close source

**Bead:** agents-config-12q7
**Status:** Design (in brainstorming)
**Date:** 2026-05-07
**Revision:** 2 (post ralf-spec-review cycle 1)

## Problem

The brainstorm-bead formula currently mutates the source bead X in place: it
writes spec content to X's notes/AC, marks X `implementation-ready`, and leaves
X in `in_progress`. This strands X — `bd ready` filters by `status=open`, so a
stranded `in_progress` bead is invisible until run-queue or a human re-claims it.
Worse, X conflates two distinct activities: the *exploration* (problem framing,
discussion) and the *implementation work* (spec → code → PR → merge).

## Goal

The formula produces a net-new implementation bead Y at finalize time, then
closes X. X becomes the historical seed; Y becomes the active implementation
bead carrying the spec, formula choice, ralf labels, readiness markers, and
follow-up children.

## Conventions

- `<X-id>` and `<Y-id>` always refer to fully-qualified bead IDs (e.g.,
  `agents-config-12q7`), never short suffixes.
- All bd commands documented here have been verified against the current
  bd CLI; deviations from documented behavior are bugs to be filed.
- `discovered-from` is a valid dep type across all bead types; `bd dep add A B
  --type discovered-from` works regardless of A's or B's `type` field
  (verified empirically against bd in this repo, 2026-05-07).

## Pre-approved design decisions (from bead 12q7)

- Use the existing `discovered-from` dep type to link Y → X. No new dep types.
- Bidirectional traceability via labels: `produced-from-<X-id>` on Y;
  `produced-bead-<Y-id>` on X.
- No new bead fields required.
- Y inherits X's epic hierarchy (Y.parent = X.parent).
- merge-gate and `[Human verify]` follow-up children are created under Y, not X.
- The formula's finalize step performs: create Y, close X, establish deps,
  burn the wisp.

## Detailed design

### 1. Lifecycle transformation

- **X (seed bead)**: enters formula `open`, exits `closed` with reason
  `"brainstormed; produced <Y-id>"`. Carries the brainstorming history (notes,
  comments, decisions, ralf-spec-review output) as a frozen historical record.
- **Y (implementation bead)**: created at finalize time, exits `open` +
  `implementation-ready`. Carries the spec, formula choice, ralf labels,
  readiness markers, and the merge-gate / `[h]` children.

### 2. Y's identity

| Field | Value |
|---|---|
| `title` | `"[Impl] " + X.title` — see §2.1 for the exact computation and idempotency guard |
| `type` | derived from chosen formula: `implement-feature` → `feature`, `fix-bug` → `bug`, `docs-only` → `task` |
| `priority` | inherits from X |
| `parent` | inherits from X (epic hierarchy carries) |
| `description` | the spec written during write-spec phase |
| `acceptance_criteria` | the AC produced during write-spec |
| `notes` | empty by default — the X↔Y relationship is captured structurally via the `Y discovered-from X` dep edge plus the `produced-from-<X-id>` label, not via prose in notes |

#### 2.1. Title computation

The title is computed in shell at finalize time. The TOML formula's mustache
templating (`{{bead-id}}`) does NOT apply to X.title; the formula step shells
out:

```bash
TITLE=$(bd show <X-id> --json | jq -r '.[0].title')
# Defensive trim: a leading-whitespace title like "  [Impl] Foo" would
# otherwise fall through and double-prefix.
TITLE="$(printf %s "$TITLE" | awk '{$1=$1; print}')"
case "$TITLE" in
  '[Impl] '*) Y_TITLE="$TITLE" ;;     # idempotent: do not double-prefix on replay
  *)          Y_TITLE="[Impl] $TITLE" ;;
esac
```

Title rationale: the `[Impl]` prefix exists specifically to defeat
bead-database duplicate-detection scanners that flag same-titled beads as
duplicates. X and Y share a logical subject but represent distinct lifecycle
stages (seed vs. implementation), so the prefix avoids spurious dedup hits
without forcing humans to invent two different titles for the same thing.

### 3. Edge migration policy

The formula iterates X's existing dep edges (excluding the parent-child edge,
which is already preserved via `Y.parent = X.parent`) and applies a mechanical
rubric:

| Dep type | Linked bead status | Action |
|---|---|---|
| `blocks`, `blocked-by` | any | migrate to Y |
| `tracks`, `until`, `caused-by`, `validates`, `relates-to`, `supersedes` | any | migrate to Y |
| `discovered-from`, `related` | linked bead is `closed` | keep on X (historical seed context) |
| `discovered-from`, `related` | linked bead is `open` or `in_progress` | migrate to Y |

The new `Y discovered-from X` edge is added unconditionally as part of step 4
(`bd create --deps discovered-from:<X-id>`).

**Cost bound**: the formula does at most N `bd show` calls on linked beads,
where N = `len(X.dependencies) - 1` (excluding the parent edge). In typical
use N < 10. If any `bd show` fails mid-loop, the formula errors and stops
with a clear message; replay handles this via the atomicity contract in §7.

### 4. Children placement

- New finalize creates `merge-<Y-id>` (label: `merge-gate`) **under Y**.
- New finalize creates `[h]` / `[Human verify]` follow-up beads **under Y**.
- **Pre-existing children of X**: classified by allowlist:
  - Children carrying label `merge-gate`: tolerated; migrated via
    `bd update <child-id> --parent <Y-id>`. If the title encodes the old X-id
    (`merge-<X-id>`), additionally rename via
    `bd update <child-id> --title "merge-<Y-id>"`.
  - Children carrying label `human` linked to an `[h]` AC: tolerated;
    migrated via `bd update <child-id> --parent <Y-id>`.
  - Any other child: finalize errors out with
    *"X has unexpected children C1, C2; brainstorming a bead with non-formula
    children is not supported. Triage manually."*

The allowlist exists for robustness against pre-redesign finalize runs and
mid-replay fault recovery; new finalize runs against fresh seed beads will
typically find no pre-existing children and pass through trivially.

### 5. Bidirectional traceability

- `Y discovered-from X` (the dep edge, per pre-approved decisions; added
  atomically via `bd create --deps`).
- `produced-from-<X-id>` label on Y (added atomically via `bd create --labels`).
- `produced-bead-<Y-id>` label on X (stamped *before* X closes).
- A `bd comments add` breadcrumb on X: `"Brainstormed; produced <Y-id> on
  <date>"` (best-effort; not a replay marker).

### 6. Lifecycle labels

| Label | X (after finalize) | Y (after finalize) |
|---|---|---|
| `brainstormed` | — (X is closed) | applied |
| `implementation-ready` | — | applied |
| `implementation-readied-session-<sid>` | — | applied (current session's `<sid>`) |
| `formula-<chosen>` | — | applied |
| `ralf:required`, `ralf:cycles=N` | — | recomputed and applied if heuristic warrants (X's stale values are NOT carried) |
| `produced-bead-<Y-id>` | applied | — |
| `produced-from-<X-id>` | — | applied |
| Custom / org labels on X | retained (frozen state) | copied per deny-list (§6.1) |

#### 6.1. Label deny-list (NOT copied X → Y)

When copying X's labels to Y, the formula skips any label matching this
extended-regex deny-list:

```
^(brainstormed|implementation-ready|implementation-readied-session-.*|formula-.*|produced-(from|bead)-.*|for-bead-.*|ralf:.*|merge-gate|human)$
```

Rationale:
- `brainstormed`, `implementation-ready`, `implementation-readied-session-*`,
  `formula-*` are session/lifecycle markers; Y gets fresh ones for the
  current session, X's are stale.
- `produced-bead-<X-id>` lives on X only (it points TO Y). `produced-from-*`
  is set fresh on Y by step 4.
- `for-bead-*` is a molecule→bead lookup label; it lives on the wisp/molecule,
  not on X, but is denylisted defensively in case it leaks onto a bead.
- `ralf:required` / `ralf:cycles=*` are recomputed on Y by Phase 5's RALF
  triage step (retargeted to Y per §8); copying X's stale values would corrupt
  the heuristic's output.
- `merge-gate` / `human` are child-state markers, not bead-state; copying them
  onto Y would mis-classify Y itself.

### 7. Order of operations (atomicity / replay)

The finalize step is multi-write. The order is chosen so any failure leaves a
recoverable state:

1. **Pre-flight idempotency**:
   ```
   bd label list <X-id> | grep -E '^produced-bead-' || echo "no marker"
   ```
   If `produced-bead-<Y-id>` already exists on X (from a prior partial run),
   skip ahead to step 8 and resume. Find Y via:
   ```
   bd list --label produced-from-<X-id> --json | jq '[.[] | select(.status != "closed")]'
   ```
   (Do NOT pass `--type *` — `*` is not a valid issue type and bd will error
   with `invalid issue type "*"`. Omitting `--type` matches all types, which
   is the intended behavior.)
   
   If no `produced-bead-*` marker exists on X, also probe for an orphan Y from
   a prior run that crashed before step 7:
   ```
   bd list --label produced-from-<X-id> --json | jq '[.[] | select(.status != "closed")]'
   ```
   - 0 results → fresh run, proceed to step 2.
   - 1 result → resume from step 5 with the existing Y.
   - ≥2 results → escalate (`bd label add <X-id> human` + comment); finalize halts.

2. **Pre-flight children check**: classify X's children per §4 allowlist.
   Reject if any child fails the allowlist.

3. **Compute** Y's fields: title (per §2.1), type from formula choice,
   priority, parent, copied labels (filtered through §6.1 deny-list), ralf
   triage outcome.

4. **Create Y atomically** in a single `bd create` call so identity, labels,
   and the `discovered-from` edge are established together (no partial state
   where Y exists but is unfindable):
   ```
   bd create \
     --type "<derived>" \
     --priority "<X.priority>" \
     --parent "<X.parent>" \
     --title "$Y_TITLE" \
     --description "$(cat /tmp/y-spec.md)" \
     --acceptance "$(cat /tmp/y-ac.md)" \
     --labels "produced-from-<X-id>,formula-<chosen>,brainstormed,implementation-ready,implementation-readied-session-<sid>,<copied-custom-labels>,<ralf-labels-if-any>" \
     --deps "discovered-from:<X-id>" \
     --no-inherit-labels
   ```
   Capture Y's id from the JSON output. The `produced-from-<X-id>` label is
   the canonical identity marker; step 1's probe always finds Y from this
   point on.

   **I1 claim-walk note (per beads.md):** Y is created `open` here; it is not
   yet "starting work," so I1 does not require a fresh claim-walk against Y.
   `Y.parent = X.parent`, which X's Phase 0 claim already marked
   `in_progress` and walked. The next agent (run-queue/implement-bead) that
   claims Y will run its own claim-walk per I1.

   **`--no-inherit-labels` rationale:** prevents X.parent's labels from
   leaking onto Y; Y's labels are exactly what `--labels` lists, nothing else.

   **Field-vs-flag mapping:** the `acceptance_criteria` bead field is set via
   `bd create --acceptance "..."` (the flag is `--acceptance`, NOT
   `--acceptance-criteria`).

   **`for-bead-<X-id>` molecule label note:** the running wisp still bears
   `for-bead-<X-id>` after Y is created. Step 9 burns the wisp immediately
   after step 8, so the staleness window is bounded to the remainder of
   finalize (a single agent turn). No external `start-bead` /
   `implement-bead` call can race with finalize, so no `for-bead-<Y-id>`
   stamp is needed on the doomed wisp.

5. **Create children under Y** — explicit ordering to avoid duplicates:
   - **5a. Migrate first.** For each allowlisted pre-existing child of X
     (per §4), re-parent to Y:
     ```
     bd update <child-id> --parent <Y-id>
     ```
     If the child has label `merge-gate` and a title `merge-<X-id>`,
     additionally rename:
     ```
     bd update <child-id> --title "merge-<Y-id>"
     ```
   - **5b. Fresh-create what's missing.** Probe for `merge-<Y-id>` under Y
     (`bd list --parent <Y-id> --label merge-gate --json`); if empty, create
     it. For each `[h]` AC line, ensure exactly one child with label `human`
     linked to that AC exists under Y; create only if missing. This guard
     prevents duplicate `merge-<Y-id>` children when step 5a already
     migrated one from X.

6. **Migrate edges** from X to Y per §3 rubric.

7. **Stamp `produced-bead-<Y-id>` on X** (canonical replay-safe boundary
   marker), THEN add the breadcrumb comment (best-effort; comment failure
   does NOT prevent advance to step 8).

8. **Close X** with reason `"brainstormed; produced <Y-id>"`. **Run I2 close-walk** per beads.md: walk X's parent chain and close each ancestor whose remaining children are all closed; stop at the first ancestor with any non-closed children. Y is now an `open` child of X.parent (since Y.parent = X.parent), so the walk naturally halts at X.parent — which is the correct outcome (the epic still has active work via Y). The walk is idempotent on replay.

9. **Burn the wisp.**

If finalize fails between steps 4 and 7, replay finds Y via the
`produced-from-<X-id>` label probe (§7 step 1) and resumes from step 5. If it
fails after step 7 (produced-bead label set) but before step 8, replay sees
the idempotency marker and only does step 8 + step 9.

### 8. What stays the same — and what changes inside Phase 5

Phases 0–4 (claim, assess, discuss, write-spec, ralf-spec-review) are
unchanged in intent. The write-spec phase still writes the spec to X's
notes/AC during the formula run; that's the source of truth that step 4 reads
from.

**Phase 5 (finalize) changes:** the current formula's Phase 5 has 7
sub-steps. The redesign retargets every X-pointed sub-step at Y:

| Current Phase 5 sub-step (target = X) | Redesign target | Where it lives now |
|---|---|---|
| 1. Update notes + AC | Y | Step 4's `--description` / `--acceptance` (atomic with create) |
| 2. RALF triage | Y | Step 4's `--labels` (recomputed; X's stale values discarded) |
| 3. Formula selection + label | Y | Step 4's `--labels` (`formula-<chosen>`) |
| 4. Reconcile follow-up children | Y | Step 5 (create under Y; migrate any allowlisted children of X) |
| 5. Add readiness labels | Y | Step 4's `--labels` |
| 6. Report and stop | (unchanged) | Step 9 (after wisp burn) |
| 7. Burn the wisp | (unchanged) | Step 9 |

The interactive parts (formula selection prompt, RALF heuristic) still run
inline in the main agent during finalize; they only differ in which bead
receives the resulting label.

## Out of scope (follow-up beads)

Each follow-up bead below MUST be created with a `discovered-from
agents-config-12q7` dep (`bd dep add <new-id> agents-config-12q7 --type
discovered-from`) so the relationship to this redesign is captured in the
bead graph.

- **start-bead behavior on closed-X (MERGE PREREQUISITE — must close before
  this redesign ships):** if a user runs `start-bead X` after Y is produced,
  current Route C will try to wisp brainstorm-bead on a closed bead. Need a
  new Route Z that detects `produced-bead-<Y-id>` on closed X and forwards
  to `start-bead Y`. Without this, every closed X with `produced-bead-*`
  becomes a trap for `start-bead`. → file as follow-up bead,
  `discovered-from agents-config-12q7`. Block merge of this bead's PR until
  Route Z's PR is merged.
- **Documentation propagation:** `rules/beads.md` lifecycle table, the
  `bead-pipeline-architecture.md` doc (if present), and skill instructions
  referencing "the bead becomes implementation-ready" need to know about
  X→Y. → file as follow-up bead, `discovered-from agents-config-12q7`.
- **In-flight migration audit:** scan for in-flight beads at deploy time
  that already carry `implementation-ready` (these stay on the old behavior
  — they go straight to run-queue/implement-bead, never re-enter
  brainstorm). Confirm none are stranded. → file as follow-up bead,
  `discovered-from agents-config-12q7`.
- **`merge-and-cleanup` compatibility check:** the `merge-and-cleanup`
  formula references `merge-<bead-id>` under the source bead. Verify it
  still works when the gate child lives under Y, not X. → file as follow-up
  bead, `discovered-from agents-config-12q7`.

## Acceptance criteria

(See bead's `acceptance_criteria` field — kept in sync with the bead, not
duplicated here.)
