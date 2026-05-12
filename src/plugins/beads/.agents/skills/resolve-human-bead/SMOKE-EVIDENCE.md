# resolve-human-bead — Smoke Evidence

Two procedural smoke tests, run by hand against scratch fixtures, per
the bead spec (AC15, AC16). Authority: `docs/specs/bead-pipeline-architecture.md`
§5.6 and the HEP section of `src/plugins/beads/.claude/rules/beads.md`.

## Smoke 1 — HEP escalation, scenario C round-trip (executed)

### Fixture

```bash
SMOKE1=/tmp/nhep-smoke-1-cycle2-1778603362
mkdir -p "$SMOKE1" && cd "$SMOKE1"
bd init
# Issue prefix: nhep-smoke-1-cycle2-1778603362
B1=$(bd create --title "Test source" --type task --json | jq -r .id)
# B1=nhep-smoke-1-cycle2-1778603362-i2o
```

### Step 2 — Run the HEP escalation block

(Inlined per the bead's "Open questions / minor risks" note #1 — the
implementer re-verified arch §5.6 contains a runnable bash block before
executing.)

```bash
H1=$(bd create \
    --title "Human input needed: tooling-credentials test" \
    --type task \
    --priority "$(bd show "$B1" --json | jq -r '.[0].priority')" \
    --description "Smoke 1 cycle2 fixture: blocked on tooling-credentials" \
    --json | jq -r .id)
# H1=nhep-smoke-1-cycle2-1778603362-3r7
bd label add "$H1" human
bd update "$H1" --append-notes "Source: $B1
Step-bead: N/A (smoke fixture)
Molecule: N/A
Worktree: $SMOKE1
Scenario hint: tooling-credentials"
bd dep add "$B1" "$H1"
bd update "$B1" --status open
```

### Step 3 — Verifications (actual output)

```
[bd show $B1] status+deps (post-escalation)
{
  "id": "nhep-smoke-1-cycle2-1778603362-i2o",
  "status": "open",
  "dependencies": [
    {
      "id": "nhep-smoke-1-cycle2-1778603362-3r7",
      "title": "Human input needed: tooling-credentials test",
      "status": "open",
      "labels": ["human"],
      "dependency_type": "blocks"
    }
  ]
}

[bd ready filter for $B1] (should be 0 — source is dep-blocked)
0

[bd label list $B1] (should NOT contain "human")
[]
```

All three step-3 invariants hold:

- Source `$B1` is `open` with a `dependencies[]` entry pointing at `$H1`
  (`dependency_type: "blocks"`).
- `bd ready --json | jq '[.[] | select(.id==$B1)] | length'` returns `0`
  — the source is correctly filtered out of the ready queue.
- `bd label list $B1` returns `[]` — the source bead does NOT carry
  `human`. The single-bead-`human` invariant holds.

### Step 4 — Canonical detection probe verified live (cycle-2 correction)

Cycle 1's SKILL.md and start-bead Route D used
`select(.type=="blocks") | .issue_id` — that shape is from
`bd ready --json`'s dependency-record wire, NOT `bd show --json`'s. On
`bd show --json` each dep object exposes `dependency_type` and `.id`.
Cycle 2 corrects both files and verifies the corrected probe live on
the same fixture:

```bash
# Broken probe (cycle-1 text) — returns empty on bd show --json:
$ bd show "$B1" --json | jq -r '.[0].dependencies[]? | select(.type=="blocks") | .issue_id'

# Corrected probe (cycle-2 text) — returns the blocker id:
$ bd show "$B1" --json | jq -r '.[0].dependencies[]? | select(.dependency_type=="blocks") | .id'
nhep-smoke-1-cycle2-1778603362-3r7

# Full canonical probe (corrected) with human-label filter:
$ bd show "$B1" --json \
    | jq -r '.[0].dependencies[]? | select(.dependency_type=="blocks") | .id' \
    | while read blocker; do
        BSTATE=$(bd show "$blocker" --json | jq -r '.[0].status')
        [ "$BSTATE" = "closed" ] && continue
        bd label list "$blocker" --json | jq -e 'index("human")' >/dev/null && echo "$blocker"
      done
nhep-smoke-1-cycle2-1778603362-3r7
```

The corrected probe fires exactly once for the one open human-labeled
blocker. Route D's `bead-blocked-by-human` trigger and
`resolve-human-bead`'s Probe 6 (source-bead pivot) detection both rely
on this probe shape; the cycle-1 text would have caused both to miss.

### Step 5 — Scenario C resolution (`bd human respond`)

```bash
bd human respond "$H1" --response "Tooling credential resolved; source bead unblocked"
# Output: ✔ Bead nhep-smoke-1-cycle2-1778603362-3r7 closed with response.
```

### Step 5 — Verifications (actual output)

```
[bd show $H1] (closed with close_reason "Responded")
{
  "id": "nhep-smoke-1-cycle2-1778603362-3r7",
  "status": "closed",
  "close_reason": "Responded",
  "labels": ["human"]
}

[bd show $B1 post-resolve] (dep edge persists; H1 is closed, so B1 ready)
{
  "id": "nhep-smoke-1-cycle2-1778603362-i2o",
  "status": "open",
  "dependencies": [
    { "id": "nhep-smoke-1-cycle2-1778603362-3r7",
      "status": "closed",
      "close_reason": "Responded",
      "dependency_type": "blocks" }
  ]
}
```

Round-trip succeeded: the escalation closed via `bd human respond` (which
adds the response comment AND closes with `close_reason: "Responded"`),
and the source bead is unblocked because its only dep is closed.

**Expected outcome verified:** zero `human` labels on the source bead at
any point; round-trip succeeds with no other state changes (scenario C
applied ONLY `bd human respond`); the corrected canonical detection
probe fires live as documented in SKILL.md and start-bead Route D.

## Smoke 2 — `[h]` follow-up scenario F, synthetic fixture (executed)

### Limitation noted

`[h]` follow-up beads are created exclusively by
`brainstorm-bead.finalize` (arch §4.3), owned by bead `7bk.12` (still
open / not implemented at this bead's ship time). Until `7bk.12` lands,
Smoke 2 verifies **only** the SKILL'S CLASS DETECTION + SCENARIO F
PRIMITIVE CHOICE — it does NOT verify integration with real finalize-step
output (e.g., the `merge-{source-id}` sibling bead behavior,
multi-follow-up close-walk gating). Real-finalize integration testing is
tracked as discovered-work bead, to be filed at `7bk.12` implementation
time.

### Synthetic / hand-crafted fixture commands

```bash
SMOKE2=/tmp/nhep-smoke-2-1778601965
mkdir -p "$SMOKE2" && cd "$SMOKE2"
bd init
S=$(bd create --title "Test source" --type task --json | jq -r .id)
# S=nhep-smoke-2-1778601965-k51
FU=$(bd create \
    --type task \
    --title "[Human verify] Test verification AC" \
    --parent "$S" --json | jq -r .id)
# FU=nhep-smoke-2-1778601965-k51.1
bd label add "$FU" human
```

This mimics the §4.3 shape: `parent` set + `[Human verify]` title prefix
+ `human` label.

### Class detection — verifications

The skill's `[h]` follow-up class probe inspects: `has human label` AND
`parent` set AND `title starts with [Human verify]`.

```
has human label: true
parent: nhep-smoke-2-1778601965-k51
title starts with [Human verify]: yes
```

All three probe predicates fire → class is `[h]` follow-up → resolution
routes to Scenario F (`verified-by-human` + plain `bd close`). Probe
ordering is correct: no `merge-ready` label, so the merge-gate sub-class
probe (priority 1) does not fire and the `[h]` probe (priority 2) takes
precedence over the generic HEP escalation probe (priority 3).

### Scenario F primitive application

```bash
bd label add "$FU" verified-by-human
# ✓ Added label 'verified-by-human' to nhep-smoke-2-1778601965-k51.1
bd close "$FU" --reason "Smoke 2: scenario F verification primitive simulated"
# ✓ Closed nhep-smoke-2-1778601965-k51.1 — [Human verify] Test verification AC: Smoke 2: scenario F verification primitive simulated
```

The skill did NOT invoke `bd human respond`. The skill did NOT invoke
`bd human dismiss`. Both forbidden primitives stayed absent; the correct
Scenario F primitive (label + plain `bd close`) was applied.

### Final-state verifications

```
[bd label list $FU]
["human", "verified-by-human"]

[bd show $FU]
{
  "id": "nhep-smoke-2-1778601965-k51.1",
  "status": "closed",
  "close_reason": "Smoke 2: scenario F verification primitive simulated",
  "labels": ["human", "verified-by-human"]
}

[bd show $S — parent, unaffected]
{
  "id": "nhep-smoke-2-1778601965-k51",
  "status": "open"
}
```

The follow-up `$FU` is `closed` with both labels (`human` retained for
audit; `verified-by-human` stamped by Scenario F). The parent source
`$S` is unaffected — no I2 close-walk cascade triggered because no
other simulated children gate the parent.

**Expected outcome verified:** correct class detection (`[h]` follow-up,
not HEP escalation); correct primitive choice (`verified-by-human` +
plain `bd close`); no use of `bd human respond` or `bd human dismiss`.
