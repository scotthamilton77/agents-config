---
name: gate-triage
description: >
  Deterministic completion-gate router. Computes the tier floor
  (SKIP / SERIAL / HEAVY) for the current change from diff facts,
  .critical-paths markers, and [completion-gate] config, and emits it as JSON.
  Invoked by the completion-gate routing preamble before the numbered gate
  steps; it decides verification depth, it does not run the review.
model: sonnet[1m]
effort: low
---

# Gate Triage

Pure-core Python helper that routes each change to a verification depth. It reads
diff facts (committed + staged + unstaged + untracked vs the merge-base), the
repo's `.critical-paths` markers, and the `[completion-gate]` config, then emits a
JSON tier floor. All judgment — the risk-class escalation and the review itself —
lives in the completion-gate rule and the `quality-gate` workflow; this helper
only measures and classifies.

**Invoked by:** the completion-gate routing preamble. Not a standalone agent
action.

## Invocation

```bash
uv run "${CLAUDE_SKILL_DIR}/gate_triage.py" --repo-root . --base-ref <default-branch>
```

- Runs via `uv run` with PEP 723 inline metadata (`pathspec` is the only
  dependency; `uv` resolves it). No separate install step.
- `--repo-root` defaults to the current directory.
- `--base-ref` defaults to the repo's default branch (`origin/HEAD`, else `main`).
- Reads git and the working tree only; never writes.

## Output (stdout, JSON)

```json
{
  "tier_floor": "SERIAL",
  "files": 12, "loc_changed": 340, "subsystems": 3,
  "new_deps": false, "file_classes": ["code", "docs"],
  "critical_path_hits": ["src/auth/token.py ← src/auth/.critical-paths:*.py"],
  "scale_hint": {"finder_dimensions": 4, "refuters": 2, "synthesis_effort": "high"}
}
```

- `tier_floor` — `SKIP` | `SERIAL` | `HEAVY`. The **floor**: the risk-class list in
  the rule may escalate it, never lower it.
- `files`, `loc_changed`, `subsystems`, `new_deps`, `file_classes` — the driving
  facts, for the announce line.
- `critical_path_hits` — `"<path> ← <marker>:<pattern>"` per `.critical-paths` or
  policy-input match. Any non-empty entry means `HEAVY`.
- `scale_hint` — fleet sizing the `HEAVY` `quality-gate` workflow consumes. Pass
  the whole payload through as the workflow's `args`; without it the workflow
  launches at default scale.

## Tier floor rules

- `HEAVY` — any `critical_path_hits`, OR `files ≥ heavy_min_files`, OR
  `loc_changed ≥ heavy_min_loc`, OR `subsystems ≥ heavy_min_subsystems`, OR
  `new_deps`. `project-config.toml` and every `.critical-paths` file are always
  hits (gate policy inputs — a change to the gate's own policy can never route
  itself down).
- `SKIP` — exactly 1 file, `loc_changed ≤ trivial_max_loc`, and no hit. A size
  bound, not a file-type bound.
- `SERIAL` — everything else (the default).

Thresholds come from `[completion-gate]` in `project-config.toml`; invalid or
absent config fails closed to built-in defaults (8 files / 400 LOC / 3 subsystems,
`trivial_max_loc` 3, hard-capped at 20).

## Exit codes

| Exit | Meaning | Caller action |
|------|---------|---------------|
| 0 | Success — JSON tier floor on stdout | Route per `tier_floor` |
| non-zero | Triage failed (git error, bad args) — no reliable JSON | **Fall back to `SERIAL`; never `SKIP`** — a failed measurement must not skip the gate |
