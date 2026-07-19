# track-backfill

One-shot migration applying the decided track assignment to the backlog.
Design: `docs/specs/2026-07-19-track-backfill-migration-design.md`.

## Constraints

1. Run from the **main checkout**, never a worktree — the bd/Dolt DB lives there.
   `apply.py` refuses otherwise, detecting a linked worktree by comparing
   `--absolute-git-dir` against `--git-common-dir` rather than by path naming,
   and separately requiring the caller's repo to be the script's own repo.
2. The track vocabulary in `project-config.toml` must be live before applying, or
   147 writes fail `E_UNKNOWN_TRACK`. `apply.py` pre-flights this.
3. **The migration needs a quiescent window.** `work track set` has no status
   guard and the tracker offers no compare-and-set, so a concurrent agent's
   legitimate track write would be silently overwritten. `apply.py` refuses to
   run while any covered item is leased. Do not dispatch agents during the run:
   the applicator closes the wide window, operational discipline closes the last
   seconds of it.
4. Snapshot before applying (see Recovery). `bd dolt` has **no `reset` and no
   `log`** subcommand — a Dolt-reset rollback does not exist.
5. `work track set` is the only track write path. Raw `bd label add track:*`
   bypasses vocabulary validation and is forbidden.

Note: `work create --raw` silently ignores `--track` (it builds `CreateFields`
with no track field). Always set a track with `work track set`, never at create.

## Run

    python3 scripts/track-backfill/apply.py --dry-run
    python3 scripts/track-backfill/apply.py --apply
    python3 scripts/track-backfill/anchor_orphans.py --dry-run
    python3 scripts/track-backfill/anchor_orphans.py --apply
    python3 scripts/track-backfill/verify.py

Re-running is safe. `reconcile()` classifies an item already carrying its target
track as `already_correct` and issues no write, so a second full run reports
`apply: 0 / unchanged: 366`. A partial run is repaired by running again. Every
successful write is appended to `applied.log`.

## Tests

    cd scripts/track-backfill && python3 -m unittest test_reconcile test_payload_keys

`test_payload_keys.py` pins the `work lint` payload keys these scripts read, with
deliberately **non-empty** fixtures. That is not incidental: a wrong key was
shipped and survived a live run precisely because the list it indexed was empty,
so the loop body never executed. An empty fixture cannot tell a right key from a
wrong one.

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
pre-existing cross-track parent at once. The expected post-migration set is those
54 plus `agents-config-9v0y`, which the Task 7 reparent deliberately adds — 55 in
total. Criterion 5 checks that set in **both** directions: an id beyond it means
an unintended cross-track parenting, an id missing from it means the graph moved
under the migration unnoticed.

Note the entries are keyed on `child`, not `id`.

## Retirement

Delete this directory once enforcement is `required` and residue has been zero
across a full Backlog Grooming cycle. Migration code earns no permanent residence.
