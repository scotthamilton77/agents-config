# Epic Hygiene: Container Bead Rules, Enforcement, and whats-next Redesign

**Bead:** agents-config-pqa5  
**Date:** 2026-05-13  
**Status:** Spec rev 7 — post Cycles 6–7 cross-model review (Codex gpt-5.5 + Gemini gemini-3-flash-preview; 10 real findings fixed)

---

## Summary

Define and enforce three rules governing "container beads" (milestones, epics, and features-with-children) to eliminate noise in readiness determination, whats-next output, and ancestor-walk closure. Enforce at three surfaces (collect.py, brainstorm-bead finalize, implement-bead) and migrate three known violations.

---

## Background / Motivation

On 2026-05-13, epic `abn9.8` appeared in the implementation-ready whats-next list despite being a pure grouping parent. A full audit of 8 open/in-progress epics found 3 violations and surfaced a systemic gap: no enforced rules govern what labels container beads carry, whether they hold executable work, or whether they appear in any readiness list.

Goal: users and agents never encounter container-bead noise in whats-next, ancestor-walk close logic, or formula dispatch.

---

## Definitions

### Container Bead

A bead is a **container** when any of the following applies:
- Type is `milestone` or `epic` — always containers, regardless of children
- Type is `feature` AND has ≥1 non-closed children — feature becomes a container the moment its first child is created

`feature` is a container-design type: its purpose is to group related epics/tasks. When childless with no `implementation-ready` label it is a planning-ready placeholder; when childless with `implementation-ready` it is a leaf impl bead produced by brainstorm-bead finalize. Either way it is never brainstorm-ready.

`decision` type is informational — excluded from all ready lists regardless of children.

`milestone`, `epic`, and `feature` types are NEVER brainstorm-ready. Use `task`, `story`, or `spike` when you want a leaf bead subject to brainstorm-ready routing.

### State Transitions

- A `feature` becomes a container the moment its first non-closed child is created.
- A `feature` with all children closed re-enters the planning-ready or impl-ready path depending on its labels.
- `milestone` and `epic` never transition to leaf status.

---

## The Three Rules

### Rule A — No executable work (convention, not enforced gate)

A container bead's AC should be expressible purely as "all children/named-children closed." Verification work not automatic from child closure should live in a leaf child. **Convention only; no automated enforcement.** Migration trims known violating AC text.

### Rule B — Never surfaces in brainstorm or implementation ready lists

Container beads are excluded from the **brainstorm-ready** and **implementation-ready** lists by structural probe, not by label hygiene. Enforced in `collect.py` regardless of labels.

**Not in scope for Rule B:** The planning-ready list intentionally surfaces childless container beads — that is its purpose. Rule B's prohibition applies only to brainstorm and implementation routing.

### Rule C — No readiness labels (convention, not actively stripped)

Container beads must not carry `implementation-ready`, `implementation-readied-session-*`, `brainstormed`, or `human`. **Convention only; collect.py's structural filter prevents surfacing even when labels exist.** The migration strips labels from the 3 known violators. The finalize gate prevents future stamping.

---

## Filter Matrix

| Type | Non-closed children | Has `implementation-ready` | Has `human` | Routing |
|------|---------------------|---------------------------|-------------|---------|
| `milestone` | 0 | no | no | **planning-ready** |
| `milestone` | 0 | yes/any | any | planning-ready (Rule C noise; filter by structure) |
| `milestone` | ≥1 | any | any | hidden |
| `epic` | 0 | no | no | **planning-ready** |
| `epic` | 0 | yes/any | any | planning-ready (Rule C noise) |
| `epic` | ≥1 | any | any | hidden |
| `feature` | 0 | no | no | **planning-ready** |
| `feature` | 0 | yes | no | **impl-ready** (leaf impl bead from brainstorm-bead) |
| `feature` | ≥1 | any | any | hidden (active container) |
| `decision` | any | any | any | nowhere |
| any type | any | any | yes | **human-attention only** (excluded from all other lists) — **this row takes priority over ALL other rows, including `decision` above** |
| `task`/`bug`/`chore`/`story`/`spike` | any | no | no | **brainstorm-ready** |
| `task`/`bug`/`chore`/`story`/`spike` | any | yes | no | **impl-ready** |

---

## whats-next Output Redesign

### Four Lists (all shown by default; empty sections suppressed)

| Section | Contents | Default? |
|---------|----------|----------|
| **Needs your attention** | `human`-labeled beads, dep-unblocked | yes |
| **Planning-ready** | container-type beads per filter matrix, dep-unblocked | yes |
| **Ready to brainstorm** | leaf-type beads, no `human`, no `implementation-ready`, dep-unblocked | yes |
| **Ready to implement** | leaf-type beads, `implementation-ready`, no `human`, dep-unblocked | on explicit request only |

`human`-labeled beads appear in "Needs your attention" only — explicitly excluded from brainstorm-ready and impl-ready. `is_brainstorm_candidate` already implements this; spec formalises it.

### Column Layout (all four lists)

```
| P | Milestone | Feature | Parent Epic | Bead ID | Type | Title |
```

- **P** — priority digit
- **Milestone** — nearest `milestone`-type ancestor short_id (nullable)
- **Feature** — nearest `feature`-type ancestor short_id (nullable)
- **Parent Epic** — immediate parent short_id (nullable, regardless of type)
- **Bead ID** — the bead's short_id
- **Type** — bead type
- **Title** — full title, untruncated

### collect.py `--mode` Contract

collect.py gains a `--mode` flag. Intent parsing lives in `whats-next` SKILL.md; it passes the appropriate flag based on user intent. When a mode does not include a section, **that key is absent from the output JSON entirely** (not an empty array). SKILL.md must not render absent keys.

| `--mode` value | Keys emitted in output JSON |
|----------------|----------------------------|
| `default` (or omitted) | `human`, `planning_ready`, `brainstorm` |
| `brainstorm` | `brainstorm` only |
| `implementation` | `implementation` only |
| `planning` | `planning_ready` only |
| `human` | `human` only |

---

## Enforcement Surfaces

### Surface 1: collect.py

**Change 1 — Pre-built active-children index (replaces per-bead subprocess calls)**

Fetch all non-closed beads once at startup to build a parent→active-child count index.
Note: `blocked` is NOT a real stored status in bd (confirmed empirically — bd uses dependency tracking, not a stored status field, to derive "blocked" state). Use `open,in_progress` only:

```python
# Verified CLI: --status comma syntax valid; --type comma NOT supported; no stored 'blocked' status.
all_active = bd_json('list', '--status', 'open,in_progress', '--json')

# Build parent → active-child count (O(N) one pass)
active_child_count = {}
for b in all_active:
    parent = b.get('parent', '')
    if parent:
        active_child_count[parent] = active_child_count.get(parent, 0) + 1

CONTAINER_ALWAYS  = {'milestone', 'epic'}
CONTAINER_DESIGN  = {'feature'}   # container-design types

def is_container(bead_id, bead_type):
    """True when bead should be hidden from brainstorm/impl lists."""
    if bead_type in CONTAINER_ALWAYS:
        return True
    if bead_type in CONTAINER_DESIGN:
        return active_child_count.get(bead_id, 0) > 0
    return False
```

**Change 2 — Updated brainstorm candidate filter**

Explicitly exclude all container-design types from brainstorm-ready regardless of child count:

```python
CONTAINER_DESIGN_TYPES = {'milestone', 'epic', 'feature', 'decision'}

def is_brainstorm_candidate(bead):
    labels = bead.get('labels', [])
    btype  = bead.get('issue_type', '')
    return (
        btype not in CONTAINER_DESIGN_TYPES      # never brainstorm-ready
        and 'implementation-ready' not in labels
        and 'merge-gate'           not in labels
        and 'human'                not in labels  # human beads → attention list only
        and not re.search(r'-mol-', bead.get('id', ''))
    )
```

**Change 3 — Memoized ancestor walk (extend existing)**

`resolve_all_ancestry` is already memoized. Extend `enrich()` to extract three typed ancestors:

```python
def extract_typed_ancestors(bead_id, ancestry_map, known, shorten):
    chain = ancestry_map.get(bead_id, [])  # root-first, so chain[-1] = immediate parent
    # "Nearest" = traverse parent-first (reversed) so the closest typed ancestor wins.
    # Example: if chain = [milestone, epic1, epic2], reversed gives epic2 first.
    milestone_col = next(
        (shorten(a) for a in reversed(chain)
         if known.get(a, {}).get('issue_type') == 'milestone'), '')
    feature_col = next(
        (shorten(a) for a in reversed(chain)
         if known.get(a, {}).get('issue_type') == 'feature'), '')
    parent_epic_col = shorten(chain[-1]) if chain else ''  # key name: parent_epic_col everywhere
    return milestone_col, feature_col, parent_epic_col
```

**Variable name invariant**: `parent_epic_col` is the canonical key name in collect.py output, SKILL.md renderer, and all AC items. Never `parent_col`. The column header is "Parent Epic" and represents the immediate parent regardless of type. The SKILL.md renderer should display the value as-is without asserting it is an epic type; if the parent is a task or bug (unusual but possible), the column will show that bead's short_id under the "Parent Epic" header — acceptable given the design intent that direct parents are almost always epics.

Extend `enrich()` to also emit `type`. Updated output fields per bead: `id`, `short_id`, `priority`, `title`, `labels`, `milestone_col`, `feature_col`, `parent_epic_col`, `type`. The `type` field is required by the SKILL.md's Type column renderer.

**Note on `is_container` vs `CONTAINER_DESIGN_TYPES` (intentional divergence — verified empirically):**
`bd ready` DOES return container-type beads (milestones, epics, features) — confirmed by running `bd ready --json` which returned multiple epic and feature beads. Therefore `CONTAINER_DESIGN_TYPES` in `is_brainstorm_candidate` is the PRIMARY gate that prevents container beads from appearing in the brainstorm-ready list (not `bd ready` pre-filtering them). `is_container` serves a separate purpose: gating the "hide from ALL lists" path for feature-with-children. A childless feature without `implementation-ready` passes `is_container` (False → not hidden from all lists), fails `is_brainstorm_candidate` (CONTAINER_DESIGN_TYPES excludes all features), and appears in planning-ready via Change 4. This is intentional, not a bug.

**Change 4 — Planning-ready list**

Uses three separate `bd list --type <type>` calls (comma-separated type NOT supported by CLI):

```python
# Planning-ready dep-gate: use --ready flag (same semantics as bd ready — excludes beads
# with active blocking deps). Verified: bd ready returns container types (epics/features)
# so --ready correctly surfaces dep-unblocked containers. No cross-reference needed.
planning_raw = (
    bd_json('list', '--type', 'milestone', '--ready', '--json') +
    bd_json('list', '--type', 'epic',      '--ready', '--json') +
    bd_json('list', '--type', 'feature',   '--ready', '--json')
)

planning_beads = [
    b for b in planning_raw
    if active_child_count.get(b['id'], 0) == 0            # no active children
    and 'implementation-ready' not in b.get('labels', []) # not a leaf impl bead
    and 'human' not in b.get('labels', [])
]
```

**Change 5 — Output schema, `--mode` flag, and atomic commit requirement**

Replace output JSON fields `feature`/`epic_chain` with `milestone_col`, `feature_col`, `parent_epic_col`. Add `type` field to each bead entry. Add top-level `mode` field. Add `--mode` argparse flag:

```python
parser.add_argument(
    '--mode',
    choices=['default', 'brainstorm', 'implementation', 'planning', 'human'],
    default='default',
    help='Which section(s) to emit (default: human+planning_ready+brainstorm)',
)
```

**This change MUST be shipped in one atomic commit covering both collect.py and whats-next SKILL.md.** No backward-compat shim.

### Surface 2: brainstorm-bead finalize (Step 0 container gate)

Add **Step 0 — Container gate** immediately at the top of finalize, BEFORE Step 1 (idempotency probe). This ensures the gate fires before any Y is created.

**TOML placement:** The Step 0 bash block goes in the finalize step's `run` field (the same field that holds all other finalize step shell code). `{{bead-id}}` uses standard formula variable interpolation (double-braces). `<this-mol-id>` follows the same convention as the existing Step 9 — the agent driving the molecule has the wisp-id in context from when it ran `bd mol wisp create`. No bd list resolution needed; insert the known mol-id directly at execution time.

```bash
# ── STEP 0: Container gate ───────────────────────────────────────────────
X_TYPE=$(bd show "{{bead-id}}" --json | jq -r '.[0].issue_type // "task"')

CONTAINER=0
case "$X_TYPE" in
  milestone|epic) CONTAINER=1 ;;
  feature)
    CHILD_COUNT=$(bd list --parent "{{bead-id}}" \
                      --status open,in_progress --json \
                  | jq 'length')
    # Note: 'blocked' is not a real stored status; dep-blocked children have status
    # open or in_progress. open,in_progress covers all non-closed children.
    [ "$CHILD_COUNT" -gt 0 ] && CONTAINER=1 || CONTAINER=0 ;;
esac

if [ "$CONTAINER" = "1" ]; then
  # Check for a prior run that produced Y when X was still a leaf.
  PRODUCED_COUNT=$(bd label list "{{bead-id}}" --json \
    | jq '[.[] | select(startswith("produced-bead-"))] | length')

  if [ "$PRODUCED_COUNT" -gt 1 ]; then
    # Multiple produced-bead-* labels: route to same ambiguous-Y HEP as Step 1b.
    # (Step 1b is not reached for containers, so we must handle it here.)
    X_PRIORITY=$(bd show "{{bead-id}}" --json | jq -r '.[0].priority // "2"')
    ESC_ID=$(bd create --type task --priority "$X_PRIORITY" \
      --title "Manual triage: multiple produced-bead labels on {{bead-id}} (container)" \
      --description "finalize halted: $PRODUCED_COUNT produced-bead-* labels on {{bead-id}} which is now a container. Remove all but the correct label, then re-run finalize." \
      --json | jq -r 'if type == "array" then .[0].id else .id end // empty')
    [ -z "$ESC_ID" ] || [ "$ESC_ID" = "null" ] && { echo "HEP: failed to extract escalation bead id" >&2; exit 1; }
    # Full HEP 5-command sequence (beads.md §HEP):
    # (2) label human
    bd label add "$ESC_ID" human
    # (3) --append-notes with context
    bd update "$ESC_ID" --append-notes \
      "Source: {{bead-id}}
Step-bead: N/A (pre-pour container gate)
Molecule: <this-mol-id>
Worktree: N/A
Scenario hint: scope-expanded (multiple produced-bead labels on container)"
    # (4) dep add blocked-by
    bd dep add "{{bead-id}}" "$ESC_ID" --type blocked-by
    # (5) revert source to open
    bd update "{{bead-id}}" --status open
    bd mol burn <this-mol-id> --force
    exit 0
  fi

  if [ "$PRODUCED_COUNT" -gt 0 ]; then
    # Single reclassification case: Y exists but X is now a container. Full HEP sequence.
    X_PRIORITY=$(bd show "{{bead-id}}" --json | jq -r '.[0].priority // "2"')
    # (1) create escalation bead
    ESC_ID=$(bd create --type task --priority "$X_PRIORITY" \
      --title "Manual triage: container reclassification of {{bead-id}} after Y was produced" \
      --description "finalize halted: {{bead-id}} produced a Y impl bead in a prior run but is now a container (type=$X_TYPE, CHILD_COUNT=$CHILD_COUNT). Determine whether to close the orphan Y or proceed. Re-run finalize after resolution." \
      --json | jq -r 'if type == "array" then .[0].id else .id end // empty')
    if [ -z "$ESC_ID" ] || [ "$ESC_ID" = "null" ]; then
      echo "HEP: failed to extract escalation bead id" >&2; exit 1
    fi
    # (2) label human
    bd label add "$ESC_ID" human
    # (3) append-notes — resolve step-bead-id from bd mol current at execution time
    STEP_BEAD_ID=$(bd mol current <this-mol-id> --json 2>/dev/null \
      | jq -r 'if type == "array" then .[0].id else .id end // "unknown"')
    bd update "$ESC_ID" --append-notes \
      "Source: {{bead-id}}
Step-bead: $STEP_BEAD_ID
Molecule: <this-mol-id>
Worktree: N/A
Scenario hint: scope-expanded (container reclassification after Y produced)"
    # (4) dep add blocked-by
    bd dep add "{{bead-id}}" "$ESC_ID" --type blocked-by
    # (5) revert source to open
    bd update "{{bead-id}}" --status open
    echo "PAUSED: container reclassification; escalation bead $ESC_ID created."
    bd mol burn <this-mol-id> --force
    exit 0
  fi

  # Clean container case: stamp decomposition labels, close X, burn wisp.
  # Step 0 exits unconditionally here; Steps 1-2 are only reached on the leaf path.
  # I2 walk behavior: identical to normal X-close (Step 8). Ancestors are closed if
  # all their children are closed; the claim walk already marked them in_progress.
  # IMPORTANT: stamp epic-decomposed BEFORE bd-close-walk.sh (the walk must not stamp it).
  echo "Container bead (type=$X_TYPE): decomposition outcome; implementation-ready NOT stamped."
  # Do NOT stamp 'brainstormed' — Rule C prohibits it on containers. Use 'epic-decomposed' only.
  bd label add "{{bead-id}}" epic-decomposed   # audit trail; MUST precede bd-close-walk.sh
  ~/.beads/scripts/bd-close-walk.sh \
    --bead-id "{{bead-id}}" \
    --reason "brainstormed (decomposition); no impl bead produced"
  bd mol burn <this-mol-id> --force
  exit 0
fi
# Not a container: fall through to Step 1 (idempotency probe → children check → ...).
```

**`epic-decomposed` label definition** — audit trail only; not a filter input. Add to beads-labels.md:

| Label | Set by | Meaning |
|-------|--------|---------|
| `epic-decomposed` | brainstorm-bead finalize (container path) | Container bead brainstormed for decomposition; no impl bead produced. Use `bd list --label epic-decomposed --status closed` to query historical decompositions. |

### Surface 3: implement-bead SKILL.md

Add `milestone` to the existing `epic → flag-human` path (§1 type-based fallback):

```bash
epic|milestone)
  # flag-human: "<type> source bead requires decomposition, not formula pour"
  <HEP escalation procedure per §0>
  exit 0
  ;;
```

### Surface 4: whats-next SKILL.md

Update (atomic with Surface 1 collect.py change):
1. Replace two-mode model (default / implementation) with four-mode model (`--mode` flag table above).
2. Replace `feature`/`epic_chain` column references with `milestone_col`/`feature_col`/`parent_epic_col`.
3. Add planning-ready section rendering.
4. Intent-to-mode mapping:
   - No qualifier / "what's next" / "what needs attention" → `--mode default`
   - "brainstorm" / "what's next to brainstorm" / "ready to brainstorm" → `--mode brainstorm`
   - "implement" / "implementation-ready" / "run-queue" / "what to implement" → `--mode implementation`
   - "planning" / "planning-ready" / "needs decomposition" → `--mode planning`
   - "human" / "human escalations" / "needs attention" (explicit) → `--mode human`
   
   Note: `--mode planning` and `--mode human` are also valid programmatic modes (e.g., for tooling that queries specific sections directly).

---

## I1/I2 Ancestor Walk — Prose Update Only

Scripts traverse parent links type-agnostically; no changes needed. Update beads.md I1 prose: "mark the bead AND every ancestor **epic** `in_progress`" → "mark the bead AND every ancestor `in_progress`".

---

## Migration — 3 Targeted Fixes

### abn9.8 — strip labels + trim AC

```bash
bd label remove agents-config-abn9.8 brainstormed
bd label remove agents-config-abn9.8 implementation-ready
bd update agents-config-abn9.8 \
  --acceptance="All [Impl] beads for prgroom complete."
# "Build passes. Tests pass." removed — covered by each child impl bead's AC.
```

### 7bk.19 — strip labels + move verification AC to child

```bash
bd label remove agents-config-7bk.19 brainstormed
bd label remove agents-config-7bk.19 "implementation-readied-session-2d3015f7"

# Guard: verify 7bk.19.9 is open before modifying it
STATUS=$(bd show agents-config-7bk.19.9 --json | jq -r '.[0].status')
if [ "$STATUS" != "open" ]; then
  echo "ERROR: 7bk.19.9 status is '$STATUS', not open; manual triage required" >&2
  exit 1
fi

# Programmatic AC merge: extract both ACs, concatenate with section header.
# Merge strategy: append parent's verification AC to child, prefixed with origin header.
EPIC_AC=$(bd show agents-config-7bk.19 --json \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0].get('acceptance_criteria',''))")
CHILD_AC=$(bd show agents-config-7bk.19.9 --json \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0].get('acceptance_criteria',''))")

MERGED_AC="${CHILD_AC}

[Verification criteria migrated from 7bk.19]
${EPIC_AC}"

bd update agents-config-7bk.19.9 --acceptance="$MERGED_AC"
```

### bt9e — reclassify epic → spike

```bash
# Dep audit (verified pre-migration): bt9e has only blocked-by incoming deps
# (7bk, 7bk.19, lu3) and parent-child with vaac. No outgoing `blocks` edges.
# Epic-wall constraint does not apply. Reclassification is safe.
# bd update -t confirmed supported by CLI.
bd update agents-config-bt9e -t spike
```

---

## Discovered Work

**biy4** (P3, `discovered-from agents-config-pqa5`) — I2 close walk: enforce parent AC satisfaction before auto-closing container beads.

*I3 sibling test:* pqa5 has no parent epic; biy4 is a deferred follow-up enforcement concern, not part of pqa5's core deliverable. Correct placement: orphan + `discovered-from pqa5`. Confirmed.

---

## Out of Scope

- Automated enforcement of Rules A and C — conventions documented here; structural filter handles symptoms.
- Sweep of closed beads for historical label cleanup.
- `bd doctor` lint command — YAGNI.
- Changes to implement-feature or fix-bug formulas — no dependencies found.

---

## Acceptance Criteria

1. `src/plugins/beads/.claude/rules/beads.md`: "Container Beads" section added with three rules and filter matrix. I1 prose updated: "every ancestor **epic**" → "every ancestor".

2. `src/plugins/beads/.claude/rules/beads-labels.md`: `epic-decomposed` entry added to label reference table (audit-trail-only note included).

3. `collect.py` updated (atomic commit with AC#4):
   - `all_active` built from `--status open,in_progress` (single call; `blocked` is not a real stored status in bd)
   - `active_child_count` dict populated in one O(N) pass
   - `is_container(bead_id, bead_type)` uses the index; no per-bead subprocess
   - `CONTAINER_DESIGN_TYPES = {'milestone', 'epic', 'feature', 'decision'}` exclusion in `is_brainstorm_candidate`
   - Planning-ready list via three separate `bd list --type <type> --ready` calls (dep-unblocked, verified to return container types)
   - `enrich()` produces `milestone_col`, `feature_col`, `parent_epic_col`, `type` (replaces `feature`/`epic_chain`; `type` = `b.get('issue_type', '')`)
   - `--mode` flag: `parser.add_argument('--mode', choices=[...], default='default')` — see argparse stanza in Change 5; absent sections omitted from output JSON
   - `human`/`planning_ready`/`brainstorm` sections in default mode; `implementation` section only on `--mode implementation`

4. `whats-next` SKILL.md updated (atomic commit with AC#3): intent→`--mode` mapping, 7-column table rendering, four sections, old `feature`/`epic_chain` references removed.

5. `brainstorm-bead.formula.toml` finalize updated: Step 0 container gate added BEFORE Step 1; gate exits unconditionally on any container case (leaf path reaches Step 1 only); both reclassification HEP paths (PRODUCED_COUNT > 1 and PRODUCED_COUNT == 1) include the canonical 5-command HEP sequence from beads.md §"Human-Escalation Pattern": (1) bd create, (2) bd label add human, (3) bd update --append-notes, (4) bd dep add --type blocked-by, (5) bd update --status open; `<this-mol-id>` is the agent-known wisp-id (no bd list probe); `epic-decomposed` stamped BEFORE `bd-close-walk.sh` on clean-container exit; `brainstormed` is NOT stamped on container path (Rule C); child count uses `--status open,in_progress` only (`blocked` is not a real stored status).

6. `implement-bead` SKILL.md: `milestone` added to `epic → flag-human` branch.

7. Migration applied:
   - `abn9.8`: labels stripped, AC trimmed
   - `7bk.19`: labels stripped, 7bk.19.9 open-status guard passes, verification AC moved
   - `bt9e`: `bd update agents-config-bt9e -t spike` executed

8. Post-migration verification (all must return 0):
   ```bash
   FORBIDDEN_PATTERN='implementation-ready|brainstormed|human'
   for TYPE in milestone epic; do
     COUNT=$(bd list --type "$TYPE" --status open,in_progress --json \
       | jq --arg p "$FORBIDDEN_PATTERN" \
           '[.[] | select(.labels | map(select(test($p))) | length > 0)] | length')
     echo "$TYPE: $COUNT violations"
   done
   # Feature-with-children check (uses active_child_count index logic):
   bd list --type feature --status open,in_progress --json \
     | python3 -c "
import sys, json, subprocess
features = json.load(sys.stdin)
violations = []
for f in features:
    try:
        children = json.loads(subprocess.check_output(
            ['bd','list','--parent',f['id'],'--status','open,in_progress','--json']))
    except subprocess.CalledProcessError:
        children = []
    if children and any(l in f.get('labels',[])
                        for l in ['implementation-ready','brainstormed','human']):
        violations.append(f['id'])
print('feature-with-children violations:', violations)
"
   ```

9. `--mode` flag contract tests (all must pass):
   - `python3 collect.py --mode implementation`: output contains `implementation` key; does NOT contain `human`, `planning_ready`, or `brainstorm` keys; top-level `mode` field equals `"implementation"`.
   - `python3 collect.py --mode default` (or no flag): output contains `human`, `planning_ready`, `brainstorm` keys; does NOT contain `implementation` key; top-level `mode` field equals `"default"`.
   - `python3 collect.py --mode brainstorm`: output contains `brainstorm` key only; `human`, `planning_ready`, `implementation` absent; `mode` field equals `"brainstorm"`.
   - `python3 collect.py --mode planning`: output contains `planning_ready` key only; `mode` field equals `"planning"`.
   - `python3 collect.py --mode human`: output contains `human` key only; `mode` field equals `"human"`.

10. Migration 7bk.19 completion: after the manual AC merge step, `bd show agents-config-7bk.19.9 --json | jq -r '.[0].acceptance_criteria'` must be non-empty and must include the grep/smoke verification text previously on `7bk.19`.

11. Migration abn9.8 verification: `bd label list agents-config-abn9.8 --json | jq '[.[] | select(test("^(implementation-ready|brainstormed)$"))] | length == 0'` must return `true`.

12. Migration bt9e verification: `bd show agents-config-bt9e --json | jq -r '.[0].issue_type == "spike"'` must return `true`.

13. Migration 7bk.19 label verification: `bd label list agents-config-7bk.19 --json | jq '[.[] | select(test("^(implementation-ready|brainstormed|implementation-readied-session-)")) ] | length == 0'` must return `true`.
