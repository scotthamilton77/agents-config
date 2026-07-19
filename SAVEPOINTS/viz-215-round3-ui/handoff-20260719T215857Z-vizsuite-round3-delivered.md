# HANDOFF — vizsuite round-3 delivered; next: depth-vs-noise discussion + parked findings

## 1. Next-session goal

Convene the depth-vs-noise design discussion with Scott, then (only after that
discussion) plan the remaining parked constellation/sonar findings on bead
`agents-config-yf2ov.2.15`.

## 2. Current state

- **Everything is merged and pushed. Nothing is in flight from this lane.**
- PR #364 (round-3 UI: sonar overlay zoom/pan + fit-to-content, constellation
  label on-screen 13px cap) merged as squash `5395c130` on `main`. Codex clean
  `+1` first pass (reaction id 415827949 on head `1189f509`).
- PR #361 (round-2 constellation fixes) merged earlier as `640f463c`.
- Worktree `viz-215-round3-ui` and its branch: removed/deleted post-merge.
  Main tree is clean and synced (other agents' worktrees under
  `.claude/worktrees/` and `.worktrees/` are NOT this lane's — leave them).
- `make ci-vizsuite` on the merged code: 435 passed, 100% coverage.
- Fresh artifact `viz pr 307` built on main post-merge
  (`.viz/out/pr-307.html`, 1062 nodes) and delivered to Scott.
- Bead `agents-config-yf2ov.2.15` is `open` with delivery notes appended;
  claim released; dolt pushed. `.2.13` closed earlier.

## 3. Decisions made and rationale

- **Sonar zoom mirrors the constellation contract** (scaleExtent [0.3, 6],
  wheel zoom, background pan, dblclick disabled). Node-originating drags are
  excluded from pan EXCEPT the center node — it has no activation wired, so
  excluding it made the largest grab point a dead gesture (kimi-k3 P3).
- **Label cap = one CSS custom property** (`--viz-constellation-label-fs =
  min(8px, 13px/k)`) set in the zoom handler; 13 = legend 12px + 1 (Scott's
  spec). Geometry untouched — layout determinism is a hard product property.
- **`.viz-blast-overlay-close` carries `z-index: 2`** — the full-size zoom
  viewport paints later in tree order and was swallowing its clicks (kimi-k3
  P1). Matches the `.viz-constellation-reset` precedent.
- **Deferred, deliberately**: sonar/constellation fit-transform + zoom-filter
  dedup (rule of three — consolidate into `vizShared` when a third zoomable
  view appears; also flagged informational by the HEAVY gate) and resize
  re-fit of the open overlay (short-lived modal).

## 4. Lessons learned

- kimi-k3 via the `openrouter-claude-subagent` skill (its `run.js` launcher is
  MANDATORY) produced a genuinely load-bearing P1 on a read-only tool grant —
  high effort, ~one review in ~10 min. Good pattern for UI review.
- Codex CAN clean-pass a PR on the first review with only a `+1` reaction —
  `poll-copilot-review.sh` reports `completion_kind: "clean_reaction"` with
  empty `reviews[]`. Verify against the live API before trusting it; here it
  was genuine.
- The merge-guard App approver's own review still trips `untriaged_feedback`
  at the pre-merge floor re-run — preempt by appending a SKIP
  `review_summary` item (with `review_id`) to the retained inventory BEFORE
  re-running the check (memory `pr-review-loop-gotchas` gotcha #4).
- `approve_pr.py` takes `--repo owner/name` and `--key-path <path>` (NOT
  `--owner`/`--key-path-env` — first attempt failed on usage).
- `ExitWorktree(remove)` works when the worktree was created in the SAME
  session; prior-session worktrees need manual `git worktree remove` from the
  main root (post-merge only).

## 5. Open questions and blockers

- **Depth-vs-noise design discussion with Scott is owed BEFORE any
  adaptive-granularity work.** Explicitly parked; do not build. kimi-k3's
  split-on-impact proposal is the strawman (substance is in beads
  `.2.13`/`.2.15` notes).
- Whether ring occupancy (finding E) is still needed now that the sonar
  zooms — Scott may find rings legible with zoom alone. Ask before building.

## 6. Next concrete steps

1. Ask Scott for the depth-vs-noise discussion (brainstorming session).
2. After that discussion, re-plan bead `.2.15`'s parked findings: F
   (direction arrows), E (ring occupancy), P (notes namespace), G (ledger
   reencode), minors — some may be invalidated by the discussion's outcome.
3. If Scott reports issues in the delivered `pr-307.html` artifact, treat as
   a fresh round: worktree → fix → HEAVY gate → PR → corridor → merge.

## 7. References

- Beads: `agents-config-yf2ov.2` (epic), `.2.13` (closed), `.2.15` (open —
  authoritative parked-findings detail)
- Merged PRs: #313, #361 (`640f463c`), #364 (`5395c130`)
- Code: `packages/vizsuite/src/vizsuite/templates/static/`
  (`views/sonar.js`, `views/constellation.js`, `scene.css`),
  `packages/vizsuite/tests/unit/test_templates_html.py`
- Artifact: `.viz/out/pr-307.html` (main, post-round-3)
- Memory: `pr-review-loop-gotchas.md` (gotchas #1–4)
- Prior handoffs (superseded by this one):
  `/tmp/handoff-20260719T184500Z-vizsuite-round3-delivery.md`

## 8. Suggested skills

- `brainstorming` — for the depth-vs-noise discussion (step 1)
- `triaging-discovered-work` — if the discussion spawns new beads
- `using-git-worktrees` → `gate-triage` → `wait-for-pr-comments` →
  `merge-guard` → `sync-after-remote-merge` — the delivery chain for any
  follow-up round
- `openrouter-claude-subagent` — kimi-k3 UI review pattern (read-only grant,
  high effort)
