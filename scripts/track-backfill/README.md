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
