# agy Model Routing Table

Captured **2026-09-27** from `agy models` on agy 1.2.12. That command is the
authority for which ids exist. Run it again before trusting this table after an
agy update, because agy's model list changes with its releases.

| Task profile | Model id (`--model` value) |
|---|---|
| Architecture, cross-subsystem, security, whole-artifact frontier lens | `gemini-3.1-pro-high` |
| Standard review, implementation, general default | `gemini-3.8-flash-high` |
| Delta re-review, mid-tier lens | `gemini-3.8-flash-medium` |
| Triage, extraction, cost-sensitive runs | `gemini-3.8-flash-low` |

## Reading the ids

The suffix of each id is its effort level. agy refuses an effort flag that
conflicts with the id, so the launcher defines no `--effort` flag and refuses
one. To change effort, pick the id with the level you want.

Flash carries `-low`, `-medium` and `-high`. Pro carries `-low` and `-high`
only, so there is no medium Pro run.

The table is advisory. An id agy does not know fails inside agy, and the
launcher reports it as exit 75 with `reason=error`. A `claude-` id is refused
with exit 78 before anything starts, because a Claude model runs natively in
the harness that launched the run.
