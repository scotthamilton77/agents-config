# V1 PR-shape prototype — findings log

PROTOTYPE — wipe me (but fold this file's content into the visualization-suite spec first).
Question under test: which visual representation of a multi-axis PR heat map
(complexity × load-bearing × consequence) best directs human review attention?

## Verdicts so far (Scott, round 1)

- **A Estate treemap — STRONG KEEP.** "Really like this, even though it's very crowded."
  Needed: label declutter (long filenames are the main crowding driver); collapsible
  groups (collapse plans/specs/architecture to a solid block colored by rolled-up
  worst-offender heat); default-collapse groups with no PR impact; expand-group-to-
  fill-screen (e.g. just `packages/`) for more detail.
- **B Dependency constellation — CLOSER (round 3): "if it became less cumbersome, it
  would be useful."** Needs better graph rendering + usability; true utility judgment
  requires experience across multiple real PRs, not one specimen. Round-3 asks: stable
  layout (no re-sim on slider drag; pre-settled, non-scrunched start), fresh-measure
  rendering, and a legend explaining node size / edge width / color / ring encodings.
- **C Attention ledger — STRONG KEEP.** "Really cool way of quickly seeing the PR files."
  Wanted: toggle between separated (PR vs context) and mixed single-ranking views;
  per-file link to that file's diff in the PR; drill panel praised.
- **D Impact sonar — RETIRED as a top-level variant (round 3).** Ring-1/ring-2 segment
  positioning carried no readable meaning ("what are io_port.py and place.py doing above
  backup.py?") — angular adjacency implied relationships the data didn't assert. The
  containment question survives as a per-file drill-down concept: click a file anywhere →
  sonar centered on THAT file's blast radius. variant_D.js kept as .retired for reference.

## Design principles extracted (spec input)

1. **Attention bar for narrative content.** Drill-panel "what to check" items must earn
   human attention: anything mechanically catchable (deleted assertions, lint-class
   findings) does not belong — the tool's premise is directing *judgment*, not
   restating automation. (Trigger: test_ownership.py "any deleted assertions?".)
2. **Weighted-average semantics need in-UI explanation.** Slider = share of importance,
   not volume knob; a file weak on an axis cools as that axis gains weight. Confused
   the user in round 1. Candidates: live mix readout, caption, per-file contribution
   breakdown in drill.
3. **History-based centrality is blind to new load-bearing code** — the PR itself
   creates dependencies (namespaces.py scored 0). Centrality must be projected from
   the post-PR graph (changed imports), not the pre-PR graph alone.
4. **Roll-up coloring**: collapsed containers inherit worst-offender (max) heat, so
   hiding detail never hides risk.
5. **Estate scope**: tracked-only (git ls-files) + curated artifact excludes
   (graphify-out, .beads, archive/, locks, generated). A `.vizignore`-style file for
   tracked-but-boring paths is a plausible future config surface.
6. **Intra-file hotspots**: file-level heat is not the floor — users want function/hunk-
   level hotspots inside the drill (mocked in round 2 for namespaces.py, backup.py).
7. **Annotation round-trip (shared-canvas validation)**: user leaves notes on nodes/files
   in the artifact; notes flow back to the agent for processing (PR comments,
   discussion). Mocked in round 2 via localStorage notes + copy-as-JSON button. This is
   the F0 agent-dialog construct in embryo.
8. **Light mode default, dark toggle** (round 2: implemented in shell).
9. **Self-contained artifacts only** — no server dependency; d3 + data inlined.
10. **Layout reflows around attention** (round 3): collapsing a container should shrink
    it and let siblings absorb the space — collapse is an attention-allocation act, not
    just a label-hiding act. Hierarchical: collapse/zoom must work at every container
    depth (packages/prgroom), not only top level.
11. **Shared-canvas hygiene**: variants render into a shared stage; any inline styling
    of the shared element leaks across views (round-3 bug cluster: drawer/resize
    truncations). Shell now hard-resets stage styles between renders — in the real
    system, view modules get a fresh container, never the shared mount point.
12. **Force layouts must be deterministic-feeling**: pre-settle the simulation before
    first paint, never restart it on encoding-only changes (weight sliders), and keep
    user-pinned positions. Every visual encoding needs a legend.
13. **Text legibility beats decoration**: no text-shadows on small labels; pick label
    color by luminance of the underlying fill, per theme.
14. **The annotation layer must escape user content** (surfaced by the HEAVY-gate
    review): any drill panel, tooltip, or notes field that carries paths, story
    text, or saved notes must set them as data (`textarea.value` / `textContent`),
    never build them into a raw innerHTML string — otherwise a note containing
    `</textarea>` or HTML breaks the DOM (stored self-XSS). The V1 prototype sets
    notes programmatically for this reason; the requirement only hardens once notes
    round-trip through agents or render non-local data. Corollary: data-out
    affordances must never fake success — the notes Copy button reports success
    only when the clipboard write resolves, and shows a failure state otherwise.
15. **Centrality tuning — exclude self-edges**: gen_data.py's in-degree counts
    intra-file edges (the majority of graph links are self-file), inflating
    "load-bearing" scores for big self-referential files; the coupling map already
    excludes them. The real scoring model must use a consistent edge set.

## Fabrication ledger (what's real vs mock in the prototype)

- Real: repo file tree, file sizes, graphify in-degree centrality, PR #238 file list
  and adds/dels, directory-level dependency edges.
- Fabricated: consequence scores (path heuristics + hand tags), complexity scores
  (numstat-scaled, story-tuned), all drill stories, intra-file hotspot scans
  (marked "mock scan" in UI), namespaces.py projected centrality (0.75).
