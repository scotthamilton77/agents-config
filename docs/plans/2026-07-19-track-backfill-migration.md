# Track Backfill Migration Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Label every non-closed, non-milestone work item with exactly one `track:*` label, from a committed decision artifact, so `work lint` invariants 1–2 report zero violations among covered items.

**Architecture:** A reviewed JSON artifact (`scripts/track-backfill/assignment.json`) holds the decided track for every item. A thin applicator reconciles it against the **live item set** — applying where the current track differs, leaving already-correct items untouched, skipping what closed, reporting live-but-uncovered items as residue — then writes each label through the validated `work track set` gate. Lint is consulted only to derive residue, never as evidence that an item is alive. All decision logic is a pure, tested function; the I/O loop around it is deliberately trivial. No classifier ships.

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

1. **Run Phase 2 from the main checkout**, never a worktree. **All three scripts** enforce this through the shared `context.resolve_root()`: it compares `--absolute-git-dir` against `--git-common-dir` (catching every linked-worktree layout, not just the `.claude/worktrees/` naming convention), requires the caller's repo to be the script's own repo, and runs every `work` subprocess with that root as its CWD. Otherwise a script invoked by absolute path from another clone would read the artifact from beside itself and write to a different tracker.
2. **The vocabulary must be live before applying.** `work track set` calls `require_known_track` first; applying against the old vocabulary fails **147** writes (`pipeline-discipline` 92 + `review-and-merge` 47 + `grind-runtime` 8). `apply.py` pre-flights this.
3. **The migration needs a quiescent window.** `work track set` has no status guard and the tracker offers no compare-and-set, so a concurrent agent's track write would be silently overwritten. `apply.py` refuses to run while any covered item is leased. Do not dispatch agents during the run — the applicator closes the wide window, operational discipline closes the last seconds of it.
4. **Snapshot before mutating.** `bd backup sync` is the recovery point; the `bd export` dump is a forensic record beside it, **not** a second restore path. `bd dolt` has no `reset` and no `log` subcommand, and `bd import` upserts rather than replaces — so re-importing the export would not remove labels this migration added. Rollback is `bd backup restore`, full stop.
5. **`work track set` is the only track write path.** Raw `bd label add track:*` bypasses vocabulary validation and is forbidden.

---

## File Structure

| File | Responsibility |
|---|---|
| `project-config.toml` (modify) | Track vocabulary; `[operating-model].groom-state-bead` |
| `scripts/track-backfill/assignment.json` (exists) | The decided assignment. Input only. |
| `scripts/track-backfill/expected_mismatches.json` (exists) | The 55 whole `(child, parent, track)` cross-track edges expected after the migration. Baseline for criterion 5. |
| `scripts/track-backfill/context.py` | Shared root binding + `work` invocation. One copy of the safety check. |
| `scripts/track-backfill/reconcile.py` | Pure reconciliation against the live item set. No I/O. |
| `scripts/track-backfill/test_reconcile.py` | Tests for the above. |
| `scripts/track-backfill/test_payload_keys.py` | Pins the `work lint` payload keys, with non-empty fixtures. |
| `scripts/track-backfill/apply.py` | Pre-flight guards, quiescence check, dry-run, apply, run-log. |
| `scripts/track-backfill/anchor_orphans.py` | Guarded anchoring and exemption of the nine milestone orphans. |
| `scripts/track-backfill/verify.py` | Acceptance criteria C1-C6, all able to fail. |
| `scripts/track-backfill/README.md` | Run instructions, constraints, recovery, retirement note. |

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

### Tasks 2-4: The migration modules

Built and committed. The files in `scripts/track-backfill/` are authoritative —
read them, not a transcription. Each was developed test-first and every guard
below is exercised by a test or a demonstrated run.

| Module | Responsibility | Key guarantee |
|---|---|---|
| `context.py` | Root binding and `work` invocation, shared by all three executables. | One copy of the main-checkout guard. Three copies would be three chances to fix two of them. |
| `reconcile.py` | Pure partition of the artifact against the live backlog. No I/O. | Liveness comes from the live item set, never from lint. An item carrying a *wrong* track is corrected, not silently skipped. |
| `test_reconcile.py` | Tests for the above. | Covers wrong-track correction, already-correct no-op, partial-run resume, and residue. |
| `test_payload_keys.py` | Pins the `work lint` payload keys the scripts read. | Fixtures are non-empty on purpose — an empty list cannot distinguish a right key from a wrong one. |
| `apply.py` | Pre-flight guards, dry-run, apply, run log. | Refuses a linked worktree (by git-dir, not path naming), a caller repo that is not the script's repo, a vocabulary that misses the artifact's tracks, an artifact failing its own integrity metadata, and any lease on a covered item. |
| `anchor_orphans.py` | The three anchors and six exemptions. | Every write is guarded on current state and followed by an assertion of the exact intended mapping. |
| `verify.py` | Acceptance criteria C1-C6. | Enumerates closed items and counts raw `track:*` labels (not the derived track), compares whole cross-track edges in both directions, and compares target tracks for **live** items only — an artifact item that closed before apply is correctly skipped by `reconcile()`, so comparing it would fail the documented drift case after an entirely correct run. |

Criterion 7 (idempotency) is deliberately **not** in `verify.py` — it is a
sequenced check, run in Task 9. `verify.py` says so in its own pass message
rather than claiming a coverage it does not have.

To re-verify the build at any point:

```bash
cd scripts/track-backfill && python3 -m unittest test_reconcile test_payload_keys
```
Expected: `Ran 18 tests` ... `OK`

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
Expected: backup completes; the export file is non-empty; `bd vc status` prints `Branch:` and `Commit:` — **record that commit hash, it names your recovery point.**

Do not proceed on a failed `bd backup sync`. It is the only rollback: there is no `bd dolt reset`, and the export cannot substitute (`bd import` upserts, so it would not remove the labels this migration adds).

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

These nine decisions were made against the backlog as it stood when the artifact was generated. An item that has since closed, or gained a different parent, must not be blindly rewritten — `work dep add` adds an edge, it is not a guarded "replace parent" operation, so issuing it against an item that already has a *different* parent is a graph mutation nobody reviewed. Every write below is therefore preceded by a current-state assertion.

The three anchors and six exemptions live in `scripts/track-backfill/anchor_orphans.py`, which performs the guards and the post-write verification. Anchoring is a graph mutation, not a label write; `work dep add A B --type parent-child` makes **A the child of B**, and the `blocks` type-wall does not apply to `parent-child`.

- [ ] **Step 1: Dry run**

```bash
python3 scripts/track-backfill/anchor_orphans.py --dry-run
```
Expected: three `WOULD ANCHOR` lines and six `WOULD EXEMPT` lines, and no mutation. Any `ABORT` means the world moved since the artifact was generated — stop and re-decide that item rather than forcing the edge.

- [ ] **Step 2: Apply**

```bash
python3 scripts/track-backfill/anchor_orphans.py --apply
```
Expected: three `ANCHORED` lines, six `EXEMPTED` lines, then `ORPHANS_OK`. On a re-run these read `ALREADY`/`SKIP` instead — the script is idempotent. `ORPHANS_OK` is an assertion over the exact intended mapping, not a print of whatever it found.

- [ ] **Step 3: Verify invariant 2 is clean**

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

- [ ] **Step 4: Assert the cross-track parent set is exactly what the migration implies**

```bash
python3 -c "
import json, subprocess, pathlib
base = json.loads(pathlib.Path('scripts/track-backfill/expected_mismatches.json').read_text())['edges']
key = lambda m: (m['child'], m['child_track'], m['parent'], m['parent_track'])
expected = {key(m) for m in base}
d = json.loads(subprocess.run(['work','lint'],capture_output=True,text=True).stdout)
assert d['ok'], f\"work lint failed: {d.get('error')}\"
actual = {key(m) for m in d['data']['track_mismatches']}   # keyed on 'child', NOT 'id'
print(f'track_mismatches: {len(actual)} edges  expected: {len(expected)}')
print('beyond expected:', sorted(actual - expected)[:3])
print('expected but missing:', sorted(expected - actual)[:3])
assert actual == expected, 'the cross-track edge set is not what the migration implies'
print('MISMATCH_SET_OK')
"
```
Expected: `track_mismatches: 55 edges  expected: 55`, both difference lists empty, `MISMATCH_SET_OK`.

Four things this step gets right that the obvious version does not:

1. **The key is `child`, not `id`** (`report.py` `_track_mismatches`). The wrong key raises `KeyError` — but only once the list is non-empty, which is to say only after the migration, which is exactly when this check matters.
2. **The count is 55, not 1.** `track_mismatches` reads 0 before the migration solely because nothing is labelled; labelling materializes every pre-existing cross-track parent edge at once. The 55th is the deliberate `9v0y` reparent, already baked into the baseline.
3. **The comparison is two-sided.** Checking only `actual - expected` passes when an expected edge *disappears*, which would mean the graph moved under the migration unnoticed.
4. **Whole edges, not bare child ids.** A child reparented to a *different* non-milestone parent on a different track reports the same child id, so an id-only comparison would pass while the reviewed edge silently changed.

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

### Task 9: Verify all seven criteria (C1-C6 mechanically, C7 by sequence)

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
Expected: `apply    : 0` and `unchanged: 366` in the applicator's own header — the reconciliation classifies every item as already-correct and issues no writes at all — and `bd vc status` reporting the same commit before and after, with no new uncommitted changes.

Both signals matter. The `unchanged` count proves idempotency at the decision layer (nothing was even attempted); `bd vc status` proves it at the storage layer (nothing landed).

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
