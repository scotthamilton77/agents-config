# Track Backfill Migration Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Label every non-closed, non-milestone work item with exactly one `track:*` label, from a committed decision artifact, so `work lint` invariants 1–2 report zero violations among covered items.

**Architecture:** A reviewed JSON artifact (`scripts/track-backfill/assignment.json`) holds the decided track for every item. A thin applicator reconciles it against live `work lint` output — applying what is still live, skipping what closed, reporting live-but-uncovered items as residue — then writes each label through the validated `work track set` gate. All decision logic is a pure, tested function; the I/O loop around it is deliberately trivial. No classifier ships.

**Tech Stack:** Python 3 (stdlib only), `work` CLI (workcli), `bd`/Dolt storage, TOML config.

**Spec:** `docs/specs/2026-07-19-track-backfill-migration-design.md`
**Bead:** `agents-config-jpn0s`

---

## Phase split — read this first

The migration **cannot run from a worktree**: the bd/Dolt database lives in the main checkout, and `work` resolves `project-config.toml` by walking up from the working directory. A branch that adds the vocabulary and the scripts is invisible to a run executed from `main`.

So this plan has two phases with a merge between them:

| Phase | Tasks | Where | Mutates |
|---|---|---|---|
| **Build** | 1–4 | this worktree/branch | files only |
| *(merge to `main`)* | | | |
| **Execute** | 5–9 | **main checkout, on `main`** | the live database |

Task 5 gates on the merge having happened. Do not start it otherwise.

## Execution constraints

1. **Run Phase 2 from the main checkout**, never a worktree. `git rev-parse --show-toplevel` must not contain `.claude/worktrees/`.
2. **The vocabulary must be live before applying.** `work track set` calls `require_known_track` first; applying against the old vocabulary fails **147** writes (`pipeline-discipline` 92 + `review-and-merge` 47 + `grind-runtime` 8). `apply.py` pre-flights this.
3. **Snapshot before mutating.** `bd backup sync` plus a `bd export` dump. Note: `bd dolt` has **no `reset` and no `log`** subcommands — recovery is `bd backup restore` or re-import from the export, not a Dolt reset.
4. **`work track set` is the only track write path.** Raw `bd label add track:*` bypasses vocabulary validation and is forbidden.

---

## File Structure

| File | Responsibility |
|---|---|
| `project-config.toml` (modify) | Track vocabulary; `[operating-model].groom-state-bead` |
| `scripts/track-backfill/assignment.json` (exists) | The decided assignment. Input only. |
| `scripts/track-backfill/expected_mismatches.json` (exists) | The 54 cross-track parent edges the assignment implies. Baseline for criterion 5. |
| `scripts/track-backfill/reconcile.py` (create) | Pure reconciliation. No I/O. |
| `scripts/track-backfill/test_reconcile.py` (create) | Tests for the above. |
| `scripts/track-backfill/apply.py` (create) | Pre-flight guards, dry-run, apply, run-log. |
| `scripts/track-backfill/verify.py` (create) | The seven acceptance criteria, all enforced. |
| `scripts/track-backfill/README.md` (create) | Run instructions, constraints, recovery, retirement note. |

---

# PHASE 1 — BUILD (this branch)

### Task 1: Track vocabulary in `project-config.toml`

**Files:**
- Modify: `project-config.toml` (the `[tracks]` block)

- [ ] **Step 1: Read the current block**

Run: `sed -n '111,131p' project-config.toml`
Expected: a `[tracks]` table with `names`, `organizing-only`, `enforcement`, then `[operating-model]`.

- [ ] **Step 2: Replace `names` and `organizing-only`**

```toml
[tracks]
names = ["installer", "prgroom", "workcli", "pdlc-orchestrator",
         "holding-place", "vizsuite", "review-and-merge",
         "pipeline-discipline", "grind-runtime", "ops-meta"]
organizing-only = ["pipeline-discipline", "grind-runtime", "ops-meta"]
enforcement = "advisory"   # flip to "required" is agents-config-63nm3
```

Leave `[operating-model]` alone; `groom-state-bead` is set in Task 8.

- [ ] **Step 3: Verify the config parses**

Run: `work lint > /dev/null && echo CONFIG_OK`
Expected: `CONFIG_OK`. `work lint` exits non-zero on `E_NOT_CONFIGURED`, so this genuinely gates.

- [ ] **Step 4: Verify vocabulary, subset rule, and that enforcement was not disturbed**

```bash
python3 -c "
import tomllib, json, pathlib
c = tomllib.load(open('project-config.toml','rb'))['tracks']
names = set(c['names'])
assert 'skills-discipline' not in names, 'skills-discipline not retired'
assert 'portability' not in names, 'portability not retired'
for t in ('pipeline-discipline','review-and-merge','grind-runtime'):
    assert t in names, f'{t} missing'
assert set(c['organizing-only']) <= names, 'organizing-only not a subset of names'
assert c['enforcement'] == 'advisory', f\"enforcement disturbed: {c['enforcement']}\"
art = json.loads(pathlib.Path('scripts/track-backfill/assignment.json').read_text())
used = {e['track'] for e in art['items'].values()}
assert used <= names, f'artifact uses tracks not in vocabulary: {sorted(used - names)}'
print('VOCAB_OK', len(names), 'tracks;', len(used), 'used by artifact')
"
```
Expected: `VOCAB_OK 10 tracks; 10 used by artifact`

- [ ] **Step 5: Commit**

```bash
git add project-config.toml
git commit -m "feat(tracks): retire skills-discipline and portability, mint three tracks"
```

---

### Task 2: Reconciliation logic (pure, tested)

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

### Task 3: The applicator, with pre-flight guards and a run log

Prose constraints are not a safety mechanism for 366 writes. Both execution constraints are mechanically checkable, so the script checks them.

**Files:**
- Create: `scripts/track-backfill/apply.py`

- [ ] **Step 1: Write the applicator**

Create `scripts/track-backfill/apply.py`:

```python
#!/usr/bin/env python3
"""Apply the decided track assignment to the live backlog.

Usage:
    python3 scripts/track-backfill/apply.py --dry-run
    python3 scripts/track-backfill/apply.py --apply

Refuses to run from a worktree, or against a config whose vocabulary does not
cover the artifact. Appends every successful write to a run log so a mid-run
abort leaves a reconcilable record.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tomllib

HERE = pathlib.Path(__file__).parent
ARTIFACT = HERE / "assignment.json"
RUNLOG = HERE / "applied.log"


def preflight(assignment: dict[str, str]) -> None:
    """Abort on the two constraints that silently corrupt a run."""
    if not ARTIFACT.exists():
        raise SystemExit(f"artifact missing: {ARTIFACT} — run from the merged main checkout")

    root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    ).stdout.strip()
    if ".claude/worktrees/" in root:
        raise SystemExit(
            f"refusing to run from a worktree ({root}); the bd database lives in the main checkout"
        )

    config_path = pathlib.Path(root) / "project-config.toml"
    names = set(tomllib.load(open(config_path, "rb"))["tracks"]["names"])
    unknown = sorted(set(assignment.values()) - names)
    if unknown:
        raise SystemExit(
            f"config vocabulary at {config_path} is missing {unknown} — "
            "land the vocabulary change before applying"
        )


def live_violations() -> set[str]:
    """Ids currently failing lint invariant 1."""
    proc = subprocess.run(["work", "lint"], capture_output=True, text=True)
    payload = json.loads(proc.stdout)
    if not payload.get("ok"):
        raise SystemExit(f"work lint failed: {payload.get('error')}")
    return {v["id"] for v in payload["data"]["track_violations"]}


def load_assignment() -> dict[str, str]:
    doc = json.loads(ARTIFACT.read_text())
    return {i: entry["track"] for i, entry in doc["items"].items()}


def set_track(item_id: str, track: str) -> tuple[bool, str]:
    """Write one track through the validated gate. Returns (ok, error_code)."""
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

    assignment = load_assignment()
    preflight(assignment)
    from reconcile import reconcile

    plan = reconcile(assignment, live_violations())

    print(f"apply  : {len(plan.to_apply)}")
    print(f"skip   : {len(plan.skipped)} (closed since artifact generation)")
    print(f"residue: {len(plan.residue)} (live, unassigned — reported not guessed)")
    for i in plan.residue:
        print(f"  RESIDUE {i}")

    if args.dry_run:
        for i, t in sorted(plan.to_apply.items()):
            print(f"  WOULD SET {i} -> {t}")
        return 0

    applied = 0
    with RUNLOG.open("a") as log:
        for n, (i, t) in enumerate(sorted(plan.to_apply.items()), 1):
            ok, code = set_track(i, t)
            if ok:
                log.write(f"{i}\t{t}\n")
                log.flush()
                applied += 1
                continue
            if code == "E_NOT_FOUND":
                print(f"  VANISHED {i} (closed during run)")
                continue
            # Contention or timeout: stop rather than keep writing into a
            # contended database. Re-running is safe (design doc §5.5).
            print(f"  ABORT at {n}/{len(plan.to_apply)}: {i} -> {code}", file=sys.stderr)
            print(f"FAILED after {applied} writes; see {RUNLOG}. Fix the cause and re-run.")
            return 1

    print(f"OK — {applied} applied, {len(plan.residue)} residue, log at {RUNLOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verify the worktree guard actually fires**

Run from **this worktree**: `python3 scripts/track-backfill/apply.py --dry-run`
Expected: exits non-zero with `refusing to run from a worktree (...)`. This proves the guard works — it is the check that prevents the whole B1/B2 failure class.

- [ ] **Step 3: Commit**

```bash
git add scripts/track-backfill/apply.py
git commit -m "feat(track-backfill): applicator with preflight guards, run log, abort-on-contention"
```

---

### Task 4: The verifier and the README

**Files:**
- Create: `scripts/track-backfill/verify.py`
- Create: `scripts/track-backfill/README.md`

- [ ] **Step 1: Write the verifier**

Every criterion must be able to fail. Criterion 4 is measured against **live** data, not the static artifact; criterion 5 against the committed 54-id baseline; the groom-state bead is carved out of the stray check.

Create `scripts/track-backfill/verify.py`:

```python
#!/usr/bin/env python3
"""Verify the seven acceptance criteria of the track backfill migration.

Every criterion appends to `failures` — none is a bare print. Exit 1 on any.
"""

from __future__ import annotations

import collections
import json
import pathlib
import subprocess
import tomllib

HERE = pathlib.Path(__file__).parent


def work(*argv: str) -> dict:
    return json.loads(subprocess.run(["work", *argv], capture_output=True, text=True).stdout)


def main() -> int:
    root = pathlib.Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
        ).stdout.strip()
    )
    config = tomllib.load(open(root / "project-config.toml", "rb"))
    organizing_only = set(config["tracks"]["organizing-only"])
    cap = config["extraction"]["pressure"]["max-track-backlog"]
    groom_bead = config["operating-model"]["groom-state-bead"]

    assigned = {
        i: e["track"]
        for i, e in json.loads((HERE / "assignment.json").read_text())["items"].items()
    }
    expected_mismatch = set(json.loads((HERE / "expected_mismatches.json").read_text()))

    lint = work("lint")["data"]
    violations = {v["id"] for v in lint["track_violations"]}
    items = work("list", "--limit", "0")["data"]["items"]
    failures: list[str] = []

    # C1 — outcome matches the artifact; nothing outside it was written to.
    # The groom-state bead is minted by this migration and is deliberately
    # not in the artifact, so it is carved out of the stray check.
    mismatched, stray = [], []
    for item in items:
        want = assigned.get(item["id"])
        if want is not None:
            if item["track"] != want:
                mismatched.append((item["id"], want, item["track"]))
        elif item["track"] is not None and item["id"] != groom_bead:
            stray.append((item["id"], item["type"], item["track"]))
    if mismatched:
        failures.append(f"C1 outcome != artifact: {mismatched[:5]} ({len(mismatched)} total)")
    if stray:
        failures.append(f"C1 track written outside the artifact: {stray[:5]} ({len(stray)} total)")

    # C2 — zero violations among covered ids; residue reported, not asserted away.
    leak = violations & set(assigned)
    residue = violations - set(assigned)
    if leak:
        failures.append(f"C2 covered ids still violating: {sorted(leak)[:5]} ({len(leak)} total)")
    print(f"residue (live, unassigned): {len(residue)} {sorted(residue)}")

    # C3 — zero milestone orphans.
    if lint["milestone_orphans"]:
        failures.append(f"C3 milestone_orphans: {lint['milestone_orphans']}")

    # C4 — no EXTRACTABLE track over the cap, measured LIVE (not from the artifact).
    live_counts = collections.Counter(
        item["track"] for item in items if item["track"] is not None
    )
    over = {t: n for t, n in live_counts.items() if t not in organizing_only and n > cap}
    if over:
        failures.append(f"C4 extractable tracks over cap {cap}: {over}")

    # C5 — no cross-track parent edge beyond the set the artifact implies.
    actual_mismatch = {m["id"] for m in lint["track_mismatches"]}
    unexpected = actual_mismatch - expected_mismatch
    if unexpected:
        failures.append(
            f"C5 unexpected cross-track parents: {sorted(unexpected)[:5]} "
            f"({len(unexpected)} beyond the {len(expected_mismatch)} baseline)"
        )
    print(f"track_mismatches: {len(actual_mismatch)} (baseline {len(expected_mismatch)})")

    # C6 — groom-state bead exists, tracked ops-meta, exempt.
    if not groom_bead:
        failures.append("C6 groom-state-bead empty")
    else:
        got = work("show", groom_bead)
        if not got.get("ok"):
            failures.append(f"C6 groom-state-bead {groom_bead} does not exist")
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

Criterion 7 (idempotency) is a sequenced check, not a static one — Task 9 Step 2.

- [ ] **Step 2: Verify the verifier fails before the migration runs**

Run this **from the branch worktree**, not the main checkout: the verifier only exists on this branch, so from `main` there is no file to run. It is read-only (`work lint`, `work list`, `work show`), so running it from the worktree is safe — unlike `apply.py`, which writes and therefore refuses.

Run: `python3 scripts/track-backfill/verify.py; echo "exit=$?"`
Expected: `exit=1` with `C2 covered ids still violating` — nothing is labelled yet, so it *must* fail. A verifier that passes before the work is done is broken.

- [ ] **Step 3: Write the README**

Create `scripts/track-backfill/README.md`:

```markdown
# track-backfill

One-shot migration applying the decided track assignment to the backlog.
Design: `docs/specs/2026-07-19-track-backfill-migration-design.md`.

## Constraints

1. Run from the **main checkout**, never a worktree — the bd/Dolt DB lives there.
   `apply.py` refuses otherwise.
2. The track vocabulary in `project-config.toml` must be live before applying, or
   147 writes fail `E_UNKNOWN_TRACK`. `apply.py` pre-flights this.
3. Snapshot before applying (see Recovery). `bd dolt` has **no `reset` and no
   `log`** subcommand — a Dolt-reset rollback does not exist.
4. `work track set` is the only track write path. Raw `bd label add track:*`
   bypasses vocabulary validation and is forbidden.

Note: `work create --raw` silently ignores `--track` (it builds `CreateFields`
with no track field). Always set a track with `work track set`, never at create.

## Run

    python3 scripts/track-backfill/apply.py --dry-run
    python3 scripts/track-backfill/apply.py --apply
    python3 scripts/track-backfill/verify.py

Re-running `--apply` is safe: `work track set` is idempotent, so a partial run is
repaired by running again. Every successful write is appended to `applied.log`.

## Recovery

Before applying:

    bd backup sync
    bd export --all -o /tmp/pre-track-backfill.jsonl
    bd vc status          # record Branch/Commit

To recover: `bd backup restore`, or re-import the export. `bd vc status` names
the commit; there is no `bd dolt reset`.

## Residue

`assignment.json` is a snapshot and decays — items close and new untracked items
appear. The applicator reports live-but-unassigned ids as **residue** rather than
guessing. Residue converges to zero only once `[tracks].enforcement` flips to
`required`. Until then each Backlog Grooming cycle sweeps what accumulated.

## expected_mismatches.json

The 54 cross-track parent edges the assignment implies. `track_mismatches` reads
0 today only because nothing is labelled; labelling materializes every
pre-existing cross-track parent. Criterion 5 asserts no mismatch *beyond* this
baseline.

## Retirement

Delete this directory once enforcement is `required` and residue has been zero
across a full Backlog Grooming cycle. Migration code earns no permanent residence.
```

- [ ] **Step 4: Commit and open the PR**

```bash
git add scripts/track-backfill/verify.py scripts/track-backfill/README.md
git commit -m "feat(track-backfill): acceptance verifier and run instructions"
```

Then take the branch through the normal delivery chain (`finishing-a-development-branch` → PR → review → merge). **Phase 2 does not start until this is merged to `main`.**

---

# PHASE 2 — EXECUTE (main checkout, on `main`, post-merge)

### Task 5: Preconditions and snapshot

**Files:** none; this task mutates nothing but must pass before anything else runs.

- [ ] **Step 1: Confirm you are in the main checkout on merged `main`**

```bash
cd /Users/scott/src/projects/agents-config
git rev-parse --show-toplevel
git branch --show-current
test -f scripts/track-backfill/assignment.json && echo ARTIFACT_PRESENT
python3 -c "
import tomllib
n = set(tomllib.load(open('project-config.toml','rb'))['tracks']['names'])
assert 'pipeline-discipline' in n, 'vocabulary not merged — do not proceed'
print('VOCAB_LIVE', len(n))
"
```
Expected: the main path (no `.claude/worktrees/`), branch `main`, `ARTIFACT_PRESENT`, `VOCAB_LIVE 10`. Any failure means the merge has not landed — stop.

- [ ] **Step 2: Resolve the two stale leases**

Spec §5.5 requires these be confirmed-or-released before the run; a concurrent agent's legitimate track write would be silently overwritten.

```bash
work show agents-config-y9mm agents-config-abn9.23 | python3 -c "
import json,sys
for line in sys.stdin:
    pass
"
work show agents-config-y9mm
work show agents-config-abn9.23
```

For each: if no live session owns it, release with `work release <id>`. Record the decision. Then snapshot the full lease set for comparison after the run:

```bash
work lint | python3 -c "
import json,sys,pathlib
l = json.load(sys.stdin)['data']['leases']['leases']
pathlib.Path('/tmp/leases-before.json').write_text(json.dumps(sorted(x['id'] for x in l)))
print('leases before:', len(l))
"
```

- [ ] **Step 3: Snapshot for recovery**

```bash
bd backup sync
bd export --all -o /tmp/pre-track-backfill.jsonl
bd vc status
```
Expected: backup completes; the export file is non-empty; `bd vc status` prints `Branch:` and `Commit:` — **record that commit hash, it names your recovery point.** There is no `bd dolt reset`; recovery is `bd backup restore` or re-import from the export.

- [ ] **Step 4: Capture the pre-run violation baseline**

```bash
work lint | python3 -c "
import json,sys; print('violations before:', len(json.load(sys.stdin)['data']['track_violations']))
"
```
Expected: a number around 368. Record it — Task 6 Step 1 compares against it.

---

### Task 6: Apply the assignment

- [ ] **Step 1: Dry run and confirm it mutated nothing**

```bash
python3 scripts/track-backfill/apply.py --dry-run | head -8
work lint | python3 -c "
import json,sys; print('violations after dry-run:', len(json.load(sys.stdin)['data']['track_violations']))
"
```
Expected: the `apply/skip/residue` header, and a violation count **identical to the Task 5 Step 4 baseline**. If it changed, the dry run is not read-only — stop.

- [ ] **Step 2: Apply**

```bash
python3 scripts/track-backfill/apply.py --apply
```
Expected: `OK — N applied, R residue, log at .../applied.log`. On `FAILED`, read `applied.log` for exactly what landed, fix the reported cause, and re-run — writes are idempotent.

- [ ] **Step 3: Confirm invariant 1 is clean among covered items**

```bash
python3 -c "
import json, subprocess, pathlib
doc = json.loads(pathlib.Path('scripts/track-backfill/assignment.json').read_text())
out = json.loads(subprocess.run(['work','lint'],capture_output=True,text=True).stdout)
assert out['ok'], f\"work lint failed: {out.get('error')}\"
remaining = {v['id'] for v in out['data']['track_violations']}
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

### Task 7: Milestone orphans

Three items are anchored (their descriptions name their milestone); six are exempted. Anchoring is a graph mutation, not a label write. `work dep add A B --type parent-child` makes **A the child of B**.

- [ ] **Step 1: Anchor the three**

```bash
work dep add agents-config-ysfvl  agents-config-t142  --type parent-child
work dep add agents-config-9v0y   agents-config-7bk   --type parent-child
work dep add agents-config-n7q0p  agents-config-yf2ov --type parent-child
```
Expected: three `ok` envelopes. All three currently have no parent, so these are pure adds. The `blocks` type-wall does not apply to `parent-child`.

If a re-run is needed, `work dep add` on an existing edge is safe to re-issue; verify with Step 2 rather than assuming.

- [ ] **Step 2: Verify each now has the intended parent**

```bash
for id in agents-config-ysfvl agents-config-9v0y agents-config-n7q0p; do
  work show $id | python3 -c "
import json,sys
d = json.load(sys.stdin)
assert d['ok'], 'show failed'
print(d['data']['id'], '-> parent', d['data']['parent'])
"
done
```
Expected exactly:
```
agents-config-ysfvl -> parent agents-config-t142
agents-config-9v0y -> parent agents-config-7bk
agents-config-n7q0p -> parent agents-config-yf2ov
```

- [ ] **Step 3: Exempt the six**

Each needs its own label — the exemption does **not** cascade, which is why `4vn5`'s two children are listed explicitly.

```bash
for id in agents-config-4vn5 agents-config-acmh.2 agents-config-717 \
          agents-config-bkvgz agents-config-gvt64 agents-config-ulv3; do
  work label add $id lint-exempt:no-milestone
done
```
Expected: six `ok` envelopes.

- [ ] **Step 4: Verify invariant 2 is clean**

```bash
work lint | python3 -c "
import json,sys
d = json.load(sys.stdin)
assert d['ok'], f\"work lint failed: {d.get('error')}\"
o = d['data']['milestone_orphans']
print('milestone_orphans:', len(o), o)
assert not o, 'orphans remain'
print('INVARIANT_2_OK')
"
```
Expected: `milestone_orphans: 0` and `INVARIANT_2_OK`

- [ ] **Step 5: Check mismatches against the committed baseline — do NOT halt on the raw count**

```bash
python3 -c "
import json, subprocess, pathlib
base = set(json.loads(pathlib.Path('scripts/track-backfill/expected_mismatches.json').read_text()))
d = json.loads(subprocess.run(['work','lint'],capture_output=True,text=True).stdout)
actual = {m['id'] for m in d['data']['track_mismatches']}
print(f'track_mismatches: {len(actual)}  baseline: {len(base)}')
unexpected = actual - base
print('beyond baseline:', sorted(unexpected))
assert not unexpected, 'an unintended cross-track parent was introduced'
print('MISMATCH_BASELINE_OK')
"
```
Expected: around 54–55 total, `beyond baseline: []`, `MISMATCH_BASELINE_OK`.

**The raw count is expected to be ~54, not 1.** `track_mismatches` reads 0 before the migration only because nothing is labelled; labelling materializes every pre-existing cross-track parent edge. Only ids *beyond* the committed baseline indicate a problem. The `9v0y` reparent may add one — if `beyond baseline` contains only `agents-config-9v0y`, that is the expected consequence of Step 1 and is accepted per spec §5.4.

---

### Task 8: Mint the groom-state bead

`work create <noun>` rejects `--label` at runtime, so the exemption cannot be set on a noun create. `--raw` accepts it, so the bead is never briefly a milestone orphan. `--raw` silently **ignores** `--track`, so the track is set separately.

**Files:**
- Modify: `project-config.toml` (`[operating-model].groom-state-bead`)

- [ ] **Step 1: Check it does not already exist (this task is not idempotent)**

```bash
work search "Backlog Grooming state" | python3 -c "
import json,sys
d = json.load(sys.stdin)
hits = [i for i in d['data']['items'] if i['title'] == 'Backlog Grooming state']
print('existing:', [i['id'] for i in hits])
assert not hits, 'already minted — reuse that id, do not create a second'
print('SAFE_TO_MINT')
"
```
Expected: `existing: []` and `SAFE_TO_MINT`. If one exists, skip to Step 3 with its id.

- [ ] **Step 2: Create it, already exempt, then set its track through the gate**

```bash
work create --raw \
  --title "Backlog Grooming state" \
  --type task \
  --priority 2 \
  --description "Carries the last-completed Backlog Grooming timestamp for work groom --status. Deliberately milestone-free; see the track backfill migration design." \
  --label lint-exempt:no-milestone
```
Expected: `{"ok": true, "data": {"id": "agents-config-XXXX"}, ...}`. Record the id, then:

```bash
work track set agents-config-XXXX ops-meta
```
(substituting the recorded id)
Expected: an `ok` envelope with `"track": "ops-meta"`.

- [ ] **Step 3: Record the id in config**

Edit `project-config.toml`:

```toml
groom-state-bead = "agents-config-XXXX"   # minted by the track backfill migration
```

- [ ] **Step 4: Verify the bead and the config pointer**

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

- [ ] **Step 5: Commit the config change on a branch, not on `main`**

```bash
git checkout -b chore/groom-state-bead
git add project-config.toml
git commit -m "chore(tracks): record the minted groom-state bead"
```
Deliver via the normal PR chain. Do not commit directly to `main`.

---

### Task 9: Verify all seven criteria

- [ ] **Step 1: Run the verifier**

Run: `python3 scripts/track-backfill/verify.py`
Expected: `C1-C6 PASS — criterion 7 (idempotency) is a sequenced check, run it separately`, plus the residue count and the mismatch/baseline line printed for the record. The verifier deliberately does not claim criterion 7; Step 2 below is what establishes it.

- [ ] **Step 2: Verify criterion 7 — a second run is a no-op**

Commit first, so the working set is clean *before* the idempotency check; otherwise the migration's own writes make it impossible to pass.

```bash
bd dolt commit -m "track backfill migration applied"
bd vc status
python3 scripts/track-backfill/apply.py --apply
bd vc status
```
Expected: `bd vc status` reports the same commit before and after the second `--apply`, and no new uncommitted changes — every `work track set` was a no-op because each item already carries its target label.

Use `bd vc status`, **not** `bd dolt status`: the latter reports server PID and port and prints identically whether or not writes occurred, so it can never detect this.

- [ ] **Step 3: Confirm no lease changed underneath the run**

```bash
work lint | python3 -c "
import json,sys,pathlib
before = set(json.loads(pathlib.Path('/tmp/leases-before.json').read_text()))
after = {x['id'] for x in json.load(sys.stdin)['data']['leases']['leases']}
print('leases appeared during run:', sorted(after - before))
print('leases released during run:', sorted(before - after))
"
```
Expected: ideally both empty. A lease that appeared mid-run means another session was active and its track writes may have been overwritten — re-check those ids specifically.

- [ ] **Step 4: Push the database**

```bash
bd dolt push
```
Expected: the migration is durable on the remote.

---

## Post-implementation

- [ ] Release the claim on `agents-config-jpn0s` or deliver it — never leave it claimed behind a merged PR.
- [ ] Mint the continuations listed in §9 of the design doc as children of the still-open objective **before** closing anything.
- [ ] `agents-config-63nm3` (the enforcement flip) is now unblocked, and per §5.1 should follow promptly — the flip is what stops residue accumulating.
