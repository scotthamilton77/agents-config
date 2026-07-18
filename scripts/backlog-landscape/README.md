# Backlog Landscape (interim)

A self-contained HTML visualization of the non-closed backlog: milestone
swimlanes, track colors, cross-track edge emphasis, and a placement-demo
panel for "where would a new bead like X land." Client-side pan/zoom/filter
only — all layout is precomputed at generation time.

Parked here from `/tmp` per `docs/specs/2026-07-15-workcli-track-partition-design.md`
§6/§11 (the 2026-07-15 interim seeing layer).

## Regenerate

One command, run from anywhere:

```sh
scripts/backlog-landscape/regenerate.sh
```

This runs a live `bd export`, classifies every non-closed bead into a track
(anchor-epic then keyword heuristics — `classify.py`), builds a layout-ready
graph JSON (`build_graph.py`), and renders the final HTML
(`build_landscape.py`). Output lands in `scripts/backlog-landscape/output/`
(gitignored — regenerate fresh each Backlog Grooming session, never commit
the artifact) with `backlog-landscape.html` as the file to open.

Each script also runs standalone if you need an intermediate artifact (e.g.
to inspect the track classification): `python3 classify.py --help`,
`python3 build_graph.py --help`, `python3 build_landscape.py --help`.

## Retirement condition

Delete this directory when the vizsuite V2 work-map ships its track
grouping/filter view (spec §6, §8). `bd graph --html --all` remains
available for ad-hoc dependency inspection in the meantime.

## Known limitation

Track assignment here is a keyword/anchor-epic heuristic (`classify.py`),
independent of the real `track:*` label the workcli track layer now applies
via `work track set` — the §7 backfill migration that would let this script
source live labels instead of guessing hasn't landed yet. Once it does, this
script should switch to reading `track:*` labels directly instead of
re-guessing per run.
