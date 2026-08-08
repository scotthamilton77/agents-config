# track-backfill

Applies the decided track assignment to the backlog.
Vocabulary, per-track charters and the rules deciding which track an item takes:
`docs/specs/2026-07-15-workcli-track-partition-design.md` §3. The migration design
that first specified this procedure was retired to
`scotthamilton77/agents-config-ARCHIVE`; what was load-bearing in it is either
stated here or in that §3.

Built as a one-shot migration and run twice: once in July 2026 against the
database the tracker reset later retired, and again in August 2026 against its
replacement, which inherited none of the labels. Each run needs its own decided
`assignment.json`; everything else here is re-runnable as written.

## Constraints

1. Run from the **main checkout**, never a worktree — the bd/Dolt DB lives there.
   **All three scripts** (`apply.py`, `anchor_orphans.py`, `verify.py`) enforce
   this via the shared `context.resolve_root()`: it detects a linked worktree by
   comparing `--absolute-git-dir` against `--git-common-dir` rather than by path
   naming, and separately requires the caller's repo to be the script's own repo.
   Every `work` subprocess then runs with that root as its CWD.

   The check lives in one module on purpose. Each script reads an artifact that
   sits *beside the script* but talks to a tracker resolved from the *working
   directory*; when those differ, the script operates on a split brain — the
   decided assignment from one checkout, the database from another. Three copies
   of that guard would be three chances to fix two of them.
2. The track vocabulary in `project-config.toml` must be live before applying, or
   every write against a missing name fails `E_UNKNOWN_TRACK`. `apply.py`
   pre-flights this and names what is missing.
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

Note: `work create --raw` **refuses** `--track` with `E_USAGE` and creates
nothing, so a bypass create can never look tracked when it is not. Set a track
with `work track set`, or supply `--track` to the lifecycle `work create <noun>`,
which validates it against the vocabulary.

## Run

    python3 scripts/track-backfill/apply.py --dry-run
    python3 scripts/track-backfill/apply.py --apply
    python3 scripts/track-backfill/anchor_orphans.py --dry-run
    python3 scripts/track-backfill/anchor_orphans.py --apply
    python3 scripts/track-backfill/gen_expected_mismatches.py
    python3 scripts/track-backfill/verify.py

Re-running is safe. `reconcile()` classifies an item already carrying its target
track as `already_correct` and issues no write, so a second full run reports
`apply: 0` with every covered item counted as `unchanged`. A partial run is
repaired by running again. Every successful write is appended to `applied.log`,
which spans every run rather than resetting per migration.

## Tests

    cd scripts/track-backfill && python3 -m unittest test_reconcile test_payload_keys test_apply_contract test_gen_expected_mismatches test_verify_c1 test_show_shape

`test_apply_contract.py` pins `set_track`'s failure classification by substituting
the backend. It exists because a regression shipped here: the shared `work()`
helper defaults to `require_ok=True` and raises before returning, so the
`E_NOT_FOUND` recovery branch was unreachable dead code in the very commit that
added it. Reconciliation tests could not catch that — the failure path needs a
failing backend, not pure logic.

`test_payload_keys.py` pins the `work lint` payload keys these scripts read, with
deliberately **non-empty** fixtures. That is not incidental: a wrong key was
shipped and survived a live run precisely because the list it indexed was empty,
so the loop body never executed. An empty fixture cannot tell a right key from a
wrong one.

`test_show_shape.py` pins that `context.show` reads **both** `work show` reply
shapes. These scripts shell out to whichever `work` is on PATH, which is not
necessarily the one built in the checkout they run from: protocol 2.0 made
`work show ID` answer `{"items": [...]}` where earlier versions answered a
single id with the item object directly, so a helper written for either shape
alone breaks against half the installations in existence. The same hazard, one
verb over, is what verify.py's C1 comment records about the `work list` status
default.

## Recovery

The facade has no backup, export or recovery-point verb, so every command below is
one a human runs. An agent that needs a recovery point asks for one and waits; it
does not reach for the backend itself.

Before applying:

    bd backup sync
    bd export --all -o /tmp/pre-track-backfill.jsonl
    bd vc status          # record Branch/Commit

**`bd backup restore` is the only rollback.** `bd vc status` names the commit;
there is no `bd dolt reset`.

The export is a **forensic record, not a restore mechanism**. `bd export`'s own
help states it "does not produce the JSONL backup snapshot used by `bd backup
restore`", and `bd import` has *upsert* semantics — it creates and updates, so
re-importing a pre-migration export would not remove the labels this migration
added. Keep the export to answer "what did this item look like before?", and use
`bd backup restore` to actually go back.

This is why `bd backup sync` runs first and its success is checked: it is the
recovery point, and the export is not a substitute for it.

## Residue

`assignment.json` is a snapshot and decays — items close and new untracked items
appear. The applicator reports live-but-unassigned ids as **residue** rather than
guessing. Residue converges to zero only once `[tracks].enforcement` flips to
`required`. Until then each Backlog Grooming cycle sweeps what accumulated.

## expected_mismatches.json

The whole edges — `(child, child_track, parent, parent_track)` — expected after
the migration. **Generated, not maintained by hand:** run
`gen_expected_mismatches.py`, which derives them from `assignment.json` plus the
live parent graph using the same rule `work lint` applies. The file is not
committed, because it is a function of live state that is stale the moment either
input moves; `verify.py` fails loudly on its absence rather than comparing
against a stale set. Generate it immediately before verifying, and **read what it
produces** — every edge listed is a cross-track parenting the migration is about
to make real, and reviewing that list is the point of the file.

`track_mismatches` reads 0 while nothing is labelled; labelling materializes
every pre-existing cross-track parent at once. Reading that 0 as a stable
baseline is the mistake this file exists to prevent.

Criterion 5 compares whole edges in **both** directions. Bare child ids are not
enough: a child reparented to a *different* non-milestone parent on a different
track still reports the same child id, so an id-only check would pass while the
reviewed edge silently changed. An edge beyond the set means an unintended
cross-track parenting; an edge missing from it means the graph moved under the
migration unnoticed.

Note `work lint` keys these entries on `child`, not `id`.

## Retirement

Delete this directory once `[tracks].enforcement` is `required` **and** residue
has been zero across a full Backlog Grooming cycle. Migration code earns no
permanent residence.

**"The migration has run" is not that condition, and is not sufficient.** This
directory was retired once on exactly that reasoning, in August 2026, and had to
come back within the day: the tracker reset had discarded the labels the July run
applied, so the migration had run and its result did not exist. The stated
condition is stricter on purpose. `enforcement = "required"` is what stops new
untracked items appearing, and a grooming cycle at zero residue is what
demonstrates none are. Until both hold, a reset — or ordinary drift — leaves work
this directory is the tool for, and deleting it converts a re-run into a
rebuild.
