# Track Backfill Migration Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Label every non-closed, non-milestone work item with exactly one `track:*` label, from a committed decision artifact, so `work lint` invariants 1–2 report zero violations among covered items.

**Architecture:** A reviewed JSON artifact (`scripts/track-backfill/assignment.json`) holds the decided track for every item. A thin applicator reconciles that artifact against live `work lint` output — applying what is still live, skipping what closed, and reporting live-but-uncovered items as residue — then writes each label through the validated `work track set` gate. No classifier ships. All reconciliation logic is a pure function with tests; the I/O loop around it is deliberately trivial.

**Tech Stack:** Python 3 (stdlib only), `work` CLI (workcli), `bd`/Dolt storage, TOML config.

**Spec:** `docs/specs/2026-07-19-track-backfill-migration-design.md`
**Bead:** `agents-config-jpn0s`

---

## Critical execution constraints

Read these before Task 1. Violating any of them corrupts the migration.

1. **Run from the main checkout, never a worktree.** The bd/Dolt database lives in the main tree. This plan is written in a worktree; the *applicator must be executed* from `/Users/scott/src/projects/agents-config`.
2. **Config before application.** `work track set` calls `require_known_track` first. Applying before Task 1 lands fails every write to a new track with `E_UNKNOWN_TRACK` — that is 100+ of 367 writes.
3. **Checkpoint before mutating.** Task 4 opens with `bd dolt commit`. That commit is the only rollback point; re-running the applicator is forward-healing and cannot undo a wrong decision.
4. **`work track set` is the only write path.** Raw `bd label add track:*` bypasses vocabulary validation and is forbidden.

---

## File Structure

| File | Responsibility |
|---|---|
| `project-config.toml` (modify) | Track vocabulary: `[tracks].names`, `[tracks].organizing-only`, `[operating-model].groom-state-bead` |
| `scripts/track-backfill/assignment.json` (exists, committed) | The decided assignment. Input only — never written by the applicator. |
| `scripts/track-backfill/reconcile.py` (create) | Pure reconciliation: given the artifact's ids and live violation ids, return what to apply / skip / report as residue. No I/O. |
| `scripts/track-backfill/test_reconcile.py` (create) | Tests for the above. |
| `scripts/track-backfill/apply.py` (create) | CLI wrapper: reads artifact, shells `work lint`, calls `reconcile`, prints plan under `--dry-run`, applies otherwise. |
| `scripts/track-backfill/README.md` (create) | Run instructions, the four constraints above, and the retirement note. |

`reconcile.py` holds every decision; `apply.py` holds every side effect. That split is why the logic is testable without touching a live database.

---

### Task 1: Track vocabulary in `project-config.toml`

**Files:**
- Modify: `project-config.toml:118-129`

- [ ] **Step 1: Read the current block**

Run: `sed -n '111,131p' project-config.toml`

Expected: a `[tracks]` table with `names`, `organizing-only`, `enforcement`, then `[operating-model]`.

- [ ] **Step 2: Replace the `[tracks]` and `[operating-model]` values**

Replace the `names` and `organizing-only` assignments with:

```toml
[tracks]
names = ["installer", "prgroom", "workcli", "pdlc-orchestrator",
         "holding-place", "vizsuite", "review-and-merge",
         "pipeline-discipline", "grind-runtime", "ops-meta"]
organizing-only = ["pipeline-discipline", "grind-runtime", "ops-meta"]
enforcement = "advisory"   # flip to "required" is agents-config-63nm3
```

Leave `[operating-model]` alone for now — `groom-state-bead` is set in Task 6.

- [ ] **Step 3: Verify the config parses and the vocabulary loads**

Run: `work lint > /dev/null && echo CONFIG_OK`
Expected: `CONFIG_OK`. Any `E_NOT_CONFIGURED` or TOML parse error means Step 2 was malformed — fix before continuing.

- [ ] **Step 4: Verify the retired names are gone and the new ones present**

Run:
```bash
python3 -c "
import tomllib
c = tomllib.load(open('project-config.toml','rb'))['tracks']
names = set(c['names'])
assert 'skills-discipline' not in names, 'skills-discipline not retired'
assert 'portability' not in names, 'portability not retired'
for t in ('pipeline-discipline','review-and-merge','grind-runtime'):
    assert t in names, f'{t} missing'
assert set(c['organizing-only']) <= names, 'organizing-only not a subset of names'
print('VOCAB_OK', len(names), 'tracks')
"
```
Expected: `VOCAB_OK 10 tracks`

- [ ] **Step 5: Commit**

```bash
git add project-config.toml
git commit -m "feat(tracks): retire skills-discipline and portability, mint three tracks"
```

---

### Task 2: Reconciliation logic (pure, tested)

The artifact decays — items close and new untracked items appear between generation and application. This function is the drift tolerance the spec's §5.1 requires.

**Files:**
- Create: `scripts/track-backfill/reconcile.py`
- Test: `scripts/track-backfill/test_reconcile.py`

- [ ] **Step 1: Write the failing tests**

Create `scripts/track-backfill/test_reconcile.py`:

```python
"""Tests for track-backfill reconciliation."""
import unittest

from reconcile import reconcile


class TestReconcile(unittest.TestCase):
    def test_all_assigned_ids_live_applies_everything(self):
        result = reconcile(
            assignment={"a": "installer", "b": "prgroom"},
            live_violations={"a", "b"},
        )
        self.assertEqual(result.to_apply, {"a": "installer", "b": "prgroom"})
        self.assertEqual(result.skipped, [])
        self.assertEqual(result.residue, [])

    def test_assigned_id_no_longer_live_is_skipped_not_applied(self):
        """An item closed since generation must not be written to."""
        result = reconcile(
            assignment={"a": "installer", "closed": "prgroom"},
            live_violations={"a"},
        )
        self.assertEqual(result.to_apply, {"a": "installer"})
        self.assertEqual(result.skipped, ["closed"])
        self.assertEqual(result.residue, [])

    def test_live_violation_absent_from_artifact_is_residue(self):
        """A new untracked item is reported, never guessed at."""
        result = reconcile(
            assignment={"a": "installer"},
            live_violations={"a", "brand_new"},
        )
        self.assertEqual(result.to_apply, {"a": "installer"})
        self.assertEqual(result.skipped, [])
        self.assertEqual(result.residue, ["brand_new"])

    def test_skipped_and_residue_are_sorted_for_stable_reporting(self):
        result = reconcile(
            assignment={"z": "ops-meta", "y": "ops-meta"},
            live_violations={"q", "b"},
        )
        self.assertEqual(result.skipped, ["y", "z"])
        self.assertEqual(result.residue, ["b", "q"])

    def test_empty_assignment_makes_every_violation_residue(self):
        result = reconcile(assignment={}, live_violations={"a", "b"})
        self.assertEqual(result.to_apply, {})
        self.assertEqual(result.residue, ["a", "b"])

    def test_is_clean_true_only_when_no_residue(self):
        clean = reconcile(assignment={"a": "installer"}, live_violations={"a"})
        self.assertTrue(clean.is_clean)
        dirty = reconcile(assignment={"a": "installer"}, live_violations={"a", "n"})
        self.assertFalse(dirty.is_clean)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd scripts/track-backfill && python3 -m unittest test_reconcile -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reconcile'`

- [ ] **Step 3: Write the minimal implementation**

Create `scripts/track-backfill/reconcile.py`:

```python
"""Reconcile the decided track assignment against live lint violations.

Pure logic, no I/O — see apply.py for the side-effecting wrapper. The
migration is drift-tolerant by design (design doc §5.1): the backlog moves
faster than the review cycle that produced the artifact, so this function
partitions rather than assuming the artifact is exhaustive.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reconciliation:
    to_apply: dict[str, str]
    """Assigned id -> track, for ids still reported as violations."""

    skipped: list[str]
    """Assigned ids no longer live (closed since generation). Never written."""

    residue: list[str]
    """Live violations absent from the artifact. Reported, never guessed."""

    @property
    def is_clean(self) -> bool:
        """True when the artifact covers every live violation."""
        return not self.residue


def reconcile(assignment: dict[str, str], live_violations: set[str]) -> Reconciliation:
    return Reconciliation(
        to_apply={i: t for i, t in assignment.items() if i in live_violations},
        skipped=sorted(i for i in assignment if i not in live_violations),
        residue=sorted(live_violations - set(assignment)),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd scripts/track-backfill && python3 -m unittest test_reconcile -v`
Expected: `Ran 6 tests` … `OK`

- [ ] **Step 5: Commit**

```bash
git add scripts/track-backfill/reconcile.py scripts/track-backfill/test_reconcile.py
git commit -m "feat(track-backfill): drift-tolerant reconciliation with tests"
```

---

### Task 3: The applicator CLI

**Files:**
- Create: `scripts/track-backfill/apply.py`
- Create: `scripts/track-backfill/README.md`

- [ ] **Step 1: Write the applicator**

Create `scripts/track-backfill/apply.py`:

```python
#!/usr/bin/env python3
"""Apply the decided track assignment to the live backlog.

RUN FROM THE MAIN CHECKOUT, NEVER A WORKTREE — the bd/Dolt database lives in
the main tree.

Usage:
    python3 scripts/track-backfill/apply.py --dry-run
    python3 scripts/track-backfill/apply.py --apply
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

from reconcile import reconcile

HERE = pathlib.Path(__file__).parent
ARTIFACT = HERE / "assignment.json"


def live_violations() -> set[str]:
    """Ids currently failing lint invariant 1."""
    out = subprocess.run(
        ["work", "lint"], capture_output=True, text=True, check=True
    ).stdout
    payload = json.loads(out)
    if not payload.get("ok"):
        raise SystemExit(f"work lint failed: {payload.get('error')}")
    return {v["id"] for v in payload["data"]["track_violations"]}


def load_assignment() -> dict[str, str]:
    doc = json.loads(ARTIFACT.read_text())
    return {i: entry["track"] for i, entry in doc["items"].items()}


def set_track(item_id: str, track: str) -> tuple[bool, str]:
    """Write one track through the validated gate. Returns (ok, detail)."""
    proc = subprocess.run(
        ["work", "track", "set", item_id, track], capture_output=True, text=True
    )
    if proc.returncode == 0:
        return True, ""
    try:
        code = json.loads(proc.stdout)["error"]["code"]
    except (ValueError, KeyError, TypeError):
        code = proc.stderr.strip() or "UNKNOWN"
    return False, code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print the plan, mutate nothing")
    mode.add_argument("--apply", action="store_true", help="write the labels")
    args = parser.parse_args()

    plan = reconcile(load_assignment(), live_violations())

    print(f"apply : {len(plan.to_apply)}")
    print(f"skip  : {len(plan.skipped)} (closed since artifact generation)")
    print(f"residue: {len(plan.residue)} (live, unassigned — reported not guessed)")
    for i in plan.residue:
        print(f"  RESIDUE {i}")

    if args.dry_run:
        for i, t in sorted(plan.to_apply.items()):
            print(f"  WOULD SET {i} -> {t}")
        return 0

    failures: list[tuple[str, str]] = []
    for n, (i, t) in enumerate(sorted(plan.to_apply.items()), 1):
        ok, code = set_track(i, t)
        if ok:
            continue
        if code == "E_NOT_FOUND":
            # Closed mid-run. Skip and record; not a failure.
            print(f"  VANISHED {i} (closed during run)")
            continue
        # Contention or timeout: abort rather than keep writing into a
        # contended database. Re-running is safe (design doc §5.5).
        failures.append((i, code))
        print(f"  ABORT at item {n}/{len(plan.to_apply)}: {i} -> {code}", file=sys.stderr)
        break

    if failures:
        print("FAILED — fix the cause and re-run; applied writes are idempotent.")
        return 1
    print(f"OK — {len(plan.to_apply)} assignments applied, {len(plan.residue)} residue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verify `--dry-run` mutates nothing**

Run from the **main checkout**:
```bash
cd /Users/scott/src/projects/agents-config
python3 scripts/track-backfill/apply.py --dry-run | tail -5
work lint | python3 -c "import json,sys; print('violations still:', len(json.load(sys.stdin)['data']['track_violations']))"
```
Expected: a `WOULD SET` list, and the violation count **unchanged** from before the dry run.

- [ ] **Step 3: Write the README**

Create `scripts/track-backfill/README.md`:

```markdown
# track-backfill

One-shot migration applying the decided track assignment to the backlog.
Design: `docs/specs/2026-07-19-track-backfill-migration-design.md`.

## Constraints

1. Run from the **main checkout**, never a worktree — the bd/Dolt DB lives there.
2. `project-config.toml`'s track vocabulary must be updated **first**, or every
   write to a new track fails `E_UNKNOWN_TRACK`.
3. `bd dolt commit` before applying — that commit is the only rollback point.
4. `work track set` is the only write path; raw `bd label add track:*` bypasses
   vocabulary validation and is forbidden.

## Run

    python3 scripts/track-backfill/apply.py --dry-run
    python3 scripts/track-backfill/apply.py --apply

Re-running is safe: `work track set` is idempotent, so a partial run is repaired
by running again. Rollback is `bd dolt reset` to the pre-migration commit.

## Residue

`assignment.json` is a snapshot and decays — items close and new untracked items
appear. The applicator reports live-but-unassigned ids as **residue** rather than
guessing. Residue converges to zero only once `[tracks].enforcement` flips to
`required`. Until then each Backlog Grooming cycle sweeps what accumulated.

## Retirement

Delete this directory once enforcement is `required` and residue has been zero
across a full Backlog Grooming cycle. Migration code earns no permanent residence.
```

- [ ] **Step 4: Commit**

```bash
git add scripts/track-backfill/apply.py scripts/track-backfill/README.md
git commit -m "feat(track-backfill): applicator with dry-run and abort-on-contention"
```

---

### Task 4: Checkpoint and apply

This is the first mutating task. There is no test-first step — the "test" is the dry run from Task 3 and the verification in Task 7.

**Files:** none modified in git; this task mutates the bd database.

- [ ] **Step 1: Confirm you are in the main checkout**

Run: `git rev-parse --show-toplevel`
Expected: `/Users/scott/src/projects/agents-config` — **not** a path containing `.claude/worktrees/`. Stop if it is.

- [ ] **Step 2: Announce against live leases**

Run: `work lint | python3 -c "import json,sys; [print(l['id']) for l in json.load(sys.stdin)['data']['leases']['leases']]"`

Expected: a list of `in_progress` item ids. A concurrent agent that sets a track mid-run will be silently overwritten by this migration. Confirm no other session is actively labelling before proceeding.

- [ ] **Step 3: Take the rollback checkpoint**

```bash
bd dolt commit -m "pre-track-backfill checkpoint"
```
Expected: a commit hash. **This is the only rollback point.** If it fails because there is nothing to commit, that is fine — the current HEAD is the checkpoint; record its hash with `bd dolt log -n 1`.

- [ ] **Step 4: Dry run once more and read the residue**

```bash
python3 scripts/track-backfill/apply.py --dry-run | head -20
```
Expected: `apply : N`, `skip : M`, `residue: R`. Record R — Task 7 asserts against it.

- [ ] **Step 5: Apply**

```bash
python3 scripts/track-backfill/apply.py --apply
```
Expected: `OK — N assignments applied, R residue`. On `FAILED`, fix the reported cause and re-run; applied writes are idempotent.

- [ ] **Step 6: Confirm invariant 1 is clean among covered items**

```bash
python3 -c "
import json, subprocess, pathlib
doc = json.loads(pathlib.Path('scripts/track-backfill/assignment.json').read_text())
live = json.loads(subprocess.run(['work','lint'],capture_output=True,text=True).stdout)['data']
remaining = {v['id'] for v in live['track_violations']}
covered = set(doc['items'])
leak = remaining & covered
print('covered violations remaining:', len(leak), sorted(leak)[:5])
print('residue (uncovered):', len(remaining - covered))
assert not leak, 'a covered item did not receive its track'
print('INVARIANT_1_OK')
"
```
Expected: `covered violations remaining: 0` and `INVARIANT_1_OK`

---

### Task 5: Milestone orphans

Three items are anchored (their descriptions name their milestone); six are exempted. Anchoring is a graph mutation, not a label write.

**Files:** none modified in git; mutates the bd database.

- [ ] **Step 1: Anchor the three items whose descriptions name a milestone**

```bash
work dep add agents-config-ysfvl  agents-config-t142  --type parent-child
work dep add agents-config-9v0y   agents-config-7bk   --type parent-child
work dep add agents-config-n7q0p  agents-config-yf2ov --type parent-child
```
Expected: each returns an `ok` envelope. All three currently have no parent, so these are pure adds with no edge to remove. The `blocks` type-wall check does not apply to `parent-child`.

- [ ] **Step 2: Verify each now has a milestone ancestor**

```bash
for id in agents-config-ysfvl agents-config-9v0y agents-config-n7q0p; do
  work show $id | python3 -c "import json,sys; d=json.load(sys.stdin)['data']; print(d['id'], '-> parent', d['parent'])"
done
```
Expected: `ysfvl -> parent agents-config-t142`, `9v0y -> parent agents-config-7bk`, `n7q0p -> parent agents-config-yf2ov`

- [ ] **Step 3: Exempt the six with no honest roadmap position**

```bash
for id in agents-config-4vn5 agents-config-acmh.2 agents-config-717 \
          agents-config-bkvgz agents-config-gvt64 agents-config-ulv3; do
  work label add $id lint-exempt:no-milestone
done
```
Expected: six `ok` envelopes. Each needs its own label — the exemption does **not** cascade to children, which is why `4vn5`'s two children are listed explicitly.

- [ ] **Step 4: Verify invariant 2 is clean**

```bash
work lint | python3 -c "
import json,sys
o = json.load(sys.stdin)['data']['milestone_orphans']
print('milestone_orphans:', len(o), o)
assert not o, 'orphans remain'
print('INVARIANT_2_OK')
"
```
Expected: `milestone_orphans: 0` and `INVARIANT_2_OK`

- [ ] **Step 5: Record the resulting `track_mismatches` count**

```bash
work lint | python3 -c "
import json,sys
m = json.load(sys.stdin)['data']['track_mismatches']
print('track_mismatches:', len(m))
for x in m: print('  ', x)
"
```
Expected: a small number (1 predicted, from `9v0y` — a `prgroom` item now parented under a `pipeline-discipline` epic). Cross-track parenting is legal; this is a soft warning. If the count exceeds the prediction, an unintended cross-track parent was introduced in Step 1 — investigate before continuing.

---

### Task 6: Mint the groom-state bead

`work create <noun>` rejects `--label` at runtime, so the exemption label cannot be set on a noun-templated create. Using `--raw` sets both the label and the item in one call, closing the window where the new bead would itself be a milestone orphan.

**Files:**
- Modify: `project-config.toml` (`[operating-model].groom-state-bead`)

- [ ] **Step 1: Create the bead with its exemption label already attached**

```bash
work create --raw \
  --title "Backlog Grooming state" \
  --type task \
  --priority 2 \
  --description "Carries the last-completed Backlog Grooming timestamp for work groom --status. Deliberately milestone-free; see the track backfill migration design." \
  --label lint-exempt:no-milestone
```
Expected: `{"protocol": ..., "ok": true, "data": {"id": "agents-config-XXXX"}, ...}`. Record the id.

- [ ] **Step 2: Set its track through the validated gate**

```bash
work track set agents-config-XXXX ops-meta
```
(substituting the id from Step 1)
Expected: an `ok` envelope with `"track": "ops-meta"`.

- [ ] **Step 3: Record the id in config**

Edit `project-config.toml`, replacing the empty `groom-state-bead`:

```toml
groom-state-bead = "agents-config-XXXX"   # minted by the track backfill migration
```

- [ ] **Step 4: Verify the bead satisfies both invariants and the config points at it**

```bash
python3 -c "
import json, subprocess, tomllib
bid = tomllib.load(open('project-config.toml','rb'))['operating-model']['groom-state-bead']
assert bid, 'groom-state-bead is empty'
d = json.loads(subprocess.run(['work','show',bid],capture_output=True,text=True).stdout)
assert d['ok'], f'{bid} does not exist'
it = d['data']
assert it['track'] == 'ops-meta', f\"track is {it['track']}\"
assert 'lint-exempt:no-milestone' in it['labels'], 'exemption label missing'
print('GROOM_STATE_OK', bid)
"
```
Expected: `GROOM_STATE_OK agents-config-XXXX`

- [ ] **Step 5: Commit**

```bash
git add project-config.toml
git commit -m "feat(tracks): record the minted groom-state bead"
```

---

### Task 7: Verify all seven acceptance criteria

**Files:** none modified.

- [ ] **Step 1: Write the verification script**

Create `scripts/track-backfill/verify.py`:

```python
#!/usr/bin/env python3
"""Verify the seven acceptance criteria of the track backfill migration."""

from __future__ import annotations

import collections
import json
import pathlib
import subprocess
import tomllib

ROOT = pathlib.Path(__file__).parent.parent.parent
ORGANIZING_ONLY = {"pipeline-discipline", "grind-runtime", "ops-meta"}


def work(*argv: str) -> dict:
    return json.loads(
        subprocess.run(["work", *argv], capture_output=True, text=True).stdout
    )


def main() -> int:
    doc = json.loads((pathlib.Path(__file__).parent / "assignment.json").read_text())
    assigned = {i: e["track"] for i, e in doc["items"].items()}
    config = tomllib.load(open(ROOT / "project-config.toml", "rb"))
    lint = work("lint")["data"]
    violations = {v["id"] for v in lint["track_violations"]}
    failures: list[str] = []

    # 1 — outcome matches the artifact, and nothing outside it was written to.
    # Items absent from the assignment are residue (new, deliberately
    # unlabelled) or milestones (exempt); a track on either is a stray write.
    mismatched: list[tuple] = []
    stray: list[tuple] = []
    for item in work("list", "--limit", "0")["data"]["items"]:
        want = assigned.get(item["id"])
        if want is not None:
            if item["track"] != want:
                mismatched.append((item["id"], want, item["track"]))
        elif item["track"] is not None:
            stray.append((item["id"], item["type"], item["track"]))
    if mismatched:
        failures.append(f"C1 outcome != artifact: {mismatched[:5]} ({len(mismatched)} total)")
    if stray:
        failures.append(f"C1 track written outside the artifact: {stray[:5]} ({len(stray)} total)")

    # 2 — zero violations among covered ids; residue reported
    leak = violations & set(assigned)
    residue = violations - set(assigned)
    if leak:
        failures.append(f"C2 covered ids still violating: {sorted(leak)[:5]}")
    print(f"residue (live, unassigned): {len(residue)} {sorted(residue)}")

    # 3 — zero milestone orphans
    if lint["milestone_orphans"]:
        failures.append(f"C3 milestone_orphans: {lint['milestone_orphans']}")

    # 4 — no EXTRACTABLE track over the cap
    cap = config["extraction"]["pressure"]["max-track-backlog"]
    counts = collections.Counter(assigned.values())
    over = {t: n for t, n in counts.items() if t not in ORGANIZING_ONLY and n > cap}
    if over:
        failures.append(f"C4 extractable tracks over cap {cap}: {over}")

    # 5 — track_mismatches at the predicted count
    print(f"track_mismatches: {len(lint['track_mismatches'])} (predicted 1)")

    # 6 — groom-state bead exists, tracked, exempt
    bid = config["operating-model"]["groom-state-bead"]
    if not bid:
        failures.append("C6 groom-state-bead empty")
    else:
        got = work("show", bid)
        if not got.get("ok"):
            failures.append(f"C6 groom-state-bead {bid} does not exist")
        else:
            it = got["data"]
            if it["track"] != "ops-meta":
                failures.append(f"C6 groom-state track is {it['track']}")
            if "lint-exempt:no-milestone" not in it["labels"]:
                failures.append("C6 groom-state missing exemption label")

    for f in failures:
        print("FAIL:", f)
    print("ALL CRITERIA PASS" if not failures else f"{len(failures)} CRITERIA FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it**

Run from the main checkout: `python3 scripts/track-backfill/verify.py`
Expected: `ALL CRITERIA PASS`, plus the residue and mismatch counts printed for the record.

- [ ] **Step 3: Verify criterion 7 — a second run is a no-op**

```bash
python3 scripts/track-backfill/apply.py --apply
bd dolt status
```
Expected: the applicator reports the same counts, and `bd dolt status` shows **no uncommitted changes** — every `work track set` was a no-op because each item already carries its target label.

- [ ] **Step 4: Commit the verifier and push the database**

```bash
git add scripts/track-backfill/verify.py
git commit -m "test(track-backfill): acceptance-criteria verifier"
bd dolt commit -m "track backfill migration applied"
bd dolt push
```

---

## Post-implementation

- [ ] Release the claim on `agents-config-jpn0s` or deliver it — never leave it claimed behind a merged PR.
- [ ] Mint the continuations listed in §9 of the design doc as children of the still-open objective **before** closing anything.
- [ ] `agents-config-63nm3` (the enforcement flip) is now unblocked, and per §5.1 should follow promptly — the flip is what stops residue accumulating.
