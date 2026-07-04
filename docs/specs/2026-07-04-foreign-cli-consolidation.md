# Consolidate `[foreign-cli]` into the Model-Routing Surface — Design

**Date:** 2026-07-04
**Status:** Draft (pending review)
**Beads:** agents-config-g42cj (sole bead)
**Related specs:** `2026-07-04-model-routing-policy-and-escalation-ladder.md` (the archetype table this spec consolidates into). Changes to that spec's §3/§4 config shape ripple here.
**Decision:** Delete the four dead per-stage model keys and two dead concurrency keys from `project-config.toml [foreign-cli]`; the section retains binary paths only. Future per-stage foreign-model choice routes through the archetype table (`[model-routing]` per-repo override), per the forward-mapping table in §4. No code changes — every deleted key is dead config.

## 1. Problem

`project-config.toml [foreign-cli]` (lines 101–115) pins per-stage foreign models
(`codex_red_tests_model`, `codex_green_loop_iter1_model`, `codex_adversarial_review_model`,
`gemini_green_loop_iter2_model`) plus concurrency hints (`codex_max_concurrent`,
`gemini_max_concurrent`) with no fallback semantics. The model-routing spec introduced an
archetype-keyed table with ordered fallback chains and a per-repo `[model-routing]`
override, making stage-named single-model pins a competing, weaker mechanism.

**Ground truth (2026-07-04 consumer audit):** every model and concurrency key in
`[foreign-cli]` is dead config. The only readers that ever existed are the archived
bead-formula TOMLs (`archive/src/plugins/beads/.beads/formulas/implement-feature.formula.toml:311`,
`fix-bug.formula.toml:358`), superseded by the M0 rearchitecture. The stages named in the
section's own doc-comment (`red-tests`, `green-loop`) survive only as a display-label
string in `packages/pdlc` and in design prose. The two live mechanisms that *do* pick
foreign models — the ralf-implement skill's hardcoded cycle models and merge-guard's
`[merge-policy].judge-model` — never read `[foreign-cli]`.

Consolidation is therefore a deletion plus a forward-mapping convention, not a migration.

## 2. Changes to `project-config.toml`

Delete:

- `codex_red_tests_model`, `codex_green_loop_iter1_model`, `codex_adversarial_review_model`,
  `gemini_green_loop_iter2_model` — stage pins with zero live readers.
- `codex_max_concurrent`, `gemini_max_concurrent` — zero live readers; the chain-entry
  shape (`cli`, `model`, `effort`, `write`, `timeout`, `provider`) has no concurrency
  field, and inventing one without a consumer would be dead config with a new name. If a
  real concurrency limiter lands, its natural home is per-provider
  (`[providers.*].max_concurrent` in `model-routing.toml`), where the limit is a property
  of the account/endpoint, not of a stage.

Retain (binaries only, with a rewritten section comment):

```toml
# ---------------------------------------------------------------------------
# [foreign-cli] — foreign-CLI binary locations only.
# Model selection lives in the archetype routing table
# (~/.agents/model-routing.toml, overridable per-repo via [model-routing]).
# ---------------------------------------------------------------------------
[foreign-cli]
# codex_binary_path  = ""        # default: ${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs
gemini_binary_path   = "gemini"
```

No `[model-routing]` rows are added now — the shipped archetype defaults already cover
every live dispatch site, and a per-repo override without a divergent need is noise.

## 3. Code changes

None. The consumer audit found zero live code paths reading any deleted key. Acceptance
is proven by grep, not by tests.

## 4. Forward mapping (the convention this spec establishes)

When a future orchestrator revives stage-shaped dispatches, the old stage pins map to
archetype rows — resolve through the routing table, never through new stage-named keys:

| Historical `[foreign-cli]` key | Intent | Archetype row |
|---|---|---|
| `codex_red_tests_model` | adversarial test review | `reviewer` |
| `codex_green_loop_iter1_model` | foreign-eyes implementation review, cycle 1 | `reviewer` |
| `codex_adversarial_review_model` | deep pre-merge adversarial pass | `judge` |
| `gemini_green_loop_iter2_model` | foreign-eyes review, cycle 2 | `reviewer` (panel diversity comes from the cross-model round-robin, not a per-stage pin) |

A repo wanting a different model for one of these purposes writes a `[model-routing]`
archetype override row (same shape as the user table), not a bespoke key.

## 5. Documentation sweep

- `docs/guide/reference.md:80` — `[foreign-cli]` row becomes "foreign-CLI binary paths";
  add a `[model-routing]` row pointing at the archetype table.
- `docs/guide/configuration.md:103-106` — same reframing; note model selection moved to
  the routing table.
- `project-config.toml` §2 comment block — rewritten as shown above.

## 6. Explicitly out of scope (deliberate, not missed)

- **`[merge-policy].judge-model` / `judge-effort`** — structurally the same
  pinned-model pattern, but a *sanctioned, pinned contract*: merge-guard's
  `judge_merge.py` is an autonomous `codex task` caller whose flags and model are pinned
  by the codex-routing rule ("do not change or remove them without updating that judge").
  A merge-authorization judge must not silently re-route through a fallback ladder — a
  cheaper rung substituting mid-judgment would weaken the cross-model guard. Consolidating
  it is a separate decision with its own risk profile; recorded here so the asymmetry is
  conscious.
- **ralf-implement's hardcoded cycle models** (`SKILL.md:110,206-212`,
  `subagent-foreign-cycle.md:48`) — wiring RALF onto the resolver is the deferred
  model-sequencing-hints work (bead agents-config-evi), not a config sweep.
- Building a concurrency limiter or `[providers.*].max_concurrent` — no consumer exists.

## 7. Acceptance criteria

1. `project-config.toml [foreign-cli]` contains only binary-path keys and the rewritten
   comment; the four model keys and two concurrency keys are gone.
2. `grep -rn "codex_red_tests_model\|codex_green_loop_iter1_model\|codex_adversarial_review_model\|gemini_green_loop_iter2_model\|codex_max_concurrent\|gemini_max_concurrent" --include="*" .`
   over the live tree (excluding `archive/` and `docs/specs/`) returns zero hits.
3. `docs/guide/reference.md` and `docs/guide/configuration.md` describe `[foreign-cli]`
   as binaries-only and point model selection at the routing table.
4. The forward-mapping table (§4) is present in this spec and cited from the
   `[foreign-cli]` comment block, so the next stage-dispatch author finds the convention.

## 8. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` the archived formula pipeline never returns in a form that reads these
  keys (M0 supersession is final). If it does, its successor consumes the resolver.
- `ASSUMPTION:` the §4 archetype assignments for the historical stage intents
  (reviewer/reviewer/judge/reviewer) match your mental model; re-map on review if not.
- `ASSUMPTION:` leaving `[merge-policy].judge-model` pinned (not consolidating) is the
  right risk call for the merge-judge contract (§6).
