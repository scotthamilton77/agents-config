# Model-Routing Policy + Escalation Ladder — Design

**Date:** 2026-07-04
**Status:** Draft (pending review)
**Beads:** agents-config-abn9.40.2 (routing policy rule), agents-config-vaac.3 (escalation-ladder dispatch)
**Decision:** One archetype-keyed routing table (preferred model + ordered fallback chain per worker archetype), a two-speed bounded escalation ladder, and a user-scoped spend ceiling enforced from a local append-only ledger.

## 1. Problem

Post-Fable operations run the pipeline on Opus/Sonnet/cheap-model economics. Today, model
selection is scattered prose and hardcoded defaults:

- The subagents rule says "right-size model and effort on every dispatch" but gives only a
  three-bucket heuristic (mechanical → haiku/sonnet low; implementation → sonnet;
  judgment-dense → opus/high). Every dispatcher re-derives the mapping.
- prgroom ships per-contract provider chains (`[agents.cluster]` / `[agents.fix]` in
  `.prgroom.toml`, defaults hardcoded in `dispatcher.py`) — the right *shape*, but private
  to prgroom and per-repo.
- The quality-gate workflow tiers finder/refuter/synthesis by *effort* only and leaves the
  model to the harness default.
- `project-config.toml [foreign-cli]` pins per-stage foreign models (per-repo, stage-named
  keys, no fallback semantics).

Nothing budgets spend. Nothing distinguishes "provider unavailable, try a peer" from
"output failed the gate, climb to a stronger model." Workers are not homogeneous — a coding
worker, a code reviewer, and a review-issue classifier need different preferred models and
different fallbacks — but no artifact encodes that.

## 2. Locked decisions (owner interview, 2026-07-04)

These are requirements, not open questions:

1. **Spend ceiling** counts only usage *beyond* the Claude Max 5x subscription plus all
   non-Anthropic metered fees (OpenRouter, OpenAI, Gemini). User-configurable, **default
   $100/month**.
2. **Per-model cost rates are user-configured** alongside the model entry (provider billing
   APIs are not assumed queryable).
3. **Cost accrual** is a local append-only ledger in user space; user-scoped so it accrues
   across sessions and projects.
4. **Ladder is two-speed by context**: interactive dispatches fast-jump (one retry at the
   preferred rung, then jump to the archetype's top rung); background dispatches climb
   stepwise.
5. **All four provider families are candidate rungs**: Anthropic (subscription backbone +
   metered overage), OpenAI gpt-5.x (via the Codex plugin), Google Gemini, OpenRouter cheap
   tier (GLM 5.2, Fugu Ultra, similar).
6. **The routing table is keyed by worker archetype** — each archetype carries a preferred
   model and an ordered fallback chain. A flat "worker" tier is explicitly rejected.

## 3. Worker archetypes

Derived from the real dispatch sites in this repo (subagents rule, completion-gate rule,
quality-gate workflow, prgroom contracts, wait-for-pr-comments per-comment fixers, Track
A/B session patterns).

`ASSUMPTION:` this archetype list and its default routes are the spec author's derivation;
owner review may merge, split, or re-route rows.

| Archetype | What it does | Write access | Default preferred | Default fallback chain |
|---|---|---|---|---|
| `mechanical` | Extraction, file surveys, grep-and-summarize, format conversion | no | cheapest local/OpenRouter rung | haiku(low) → sonnet(low) |
| `classifier` | Review-issue clustering, triage, labeling (prgroom `cluster` is this archetype) | no | local free rung (e.g. ollama gemma4) | haiku(high) → gpt-5.4-mini |
| `finder` | Multi-lens review finders, explorers, searchers | no | haiku(low) | sonnet(low) → gpt-5.4-mini |
| `implementer` | Coding workers: edit + commit (prgroom `fix`, Track B workers) | yes | sonnet(medium) | opus(high) → gpt-5.5 |
| `reviewer` | Code/plan review against standards (quality-reviewer, per-file review passes) | no | sonnet(medium) | opus(high) → gpt-5.5 |
| `refuter` | Adversarial verification panels (quality-gate Verify phase) | no | sonnet(medium) | opus(medium) |
| `judge` | Synthesis, verdicts, architecture judgment, final pre-merge pass | no | opus(high) | gpt-5.5 → gemini top tier |
| `spec-writer` | Judgment-dense authoring (specs, design docs) | yes | opus(high) | gpt-5.5 |
| `interactive` | The main session loop | yes | user's `/model` choice | outside the ladder (§6) |

Two structural facts the table encodes:

- **Preferred rung is the cheapest model that usually passes the archetype's gate**, not
  the best model. The ladder exists so the cheap rung is safe to try.
- **Write-capable archetypes carry the write grant in the chain entry** (prgroom precedent:
  `write=True` on fix links, absent on cluster links — least privilege).

## 4. Routing config: user-scoped table, per-repo override

### 4.1 Canonical file

A user-scoped TOML at `~/.agents/model-routing.toml`, installed as a template and
user-owned thereafter (the installer must never clobber user edits — union-merge semantics,
user values win).

`ASSUMPTION:` `~/.agents/` is the user-space home for tool-agnostic config (the spend
ledger lives beside it). If the user-owned-overlay design (in flight separately) lands a
different user-config root, this file follows it; only the path moves.

```toml
[providers.anthropic]
billing = "subscription"        # subscription | metered
# metered overage is a separate provider entry so the ceiling can see it:
[providers.anthropic-api]
billing = "metered"
[providers.anthropic-api.models.opus]
cost_per_mtok_in = 15.0         # user-maintained; no billing-API dependency
cost_per_mtok_out = 75.0

[providers.openrouter]
billing = "metered"
[providers.openrouter.models."glm-5.2"]
cost_per_mtok_in = 0.6
cost_per_mtok_out = 2.2

[budget]
monthly_ceiling_usd = 100       # counts metered spend only (locked decision 1)

[archetype.implementer]
preferred = { cli = "claude", model = "sonnet", effort = "medium", write = true }
fallback  = [
  { cli = "claude", model = "opus", effort = "high", write = true },
  { cli = "codex",  model = "gpt-5.5", write = true },
]

[archetype.classifier]
preferred = { cli = "ollama", model = "gemma4" }
fallback  = [
  { cli = "claude", model = "haiku", effort = "high" },
  { cli = "codex",  model = "gpt-5.4-mini" },
]
# ... one section per archetype in §3
```

Chain entries reuse prgroom's `AgentSpec` vocabulary (`cli`, `model`, optional `effort`,
`write`, `timeout`) so prgroom chains and routing chains stay one dialect.

### 4.2 Per-repo override

`project-config.toml` may add a `[model-routing]` section overriding specific archetype
rows for that repo (same shape). Precedence: repo override > user table > shipped defaults.
The shipped defaults are the §3 table, embedded in the resolver so a fresh machine routes
sanely with zero config.

## 5. Resolver: `resolve_route.py` (code over prose)

A PEP 723 helper shipped as a skill asset (same pattern as merge-guard's
`resolve_policy.py` and gate-triage's `gate_triage.py`). Pure core over value types;
config + ledger I/O confined to the boundary.

```
uv run resolve_route.py --archetype implementer --context background [--repo-root .]
```

Output (JSON): the resolved chain (post-two-speed, post-ceiling), plus
`{ceiling: {spent_usd, ceiling_usd, exhausted}, ledger_errors, warnings}`.

Contract decisions (fail-loud posture, risk-asymmetric on spend):

- Unknown archetype → non-zero exit with a specific error naming the known archetypes.
  Callers must not guess.
- Invalid `[budget]` or rate config → the resolver does **not** fail open to unlimited
  metered spend; it returns the chain filtered to subscription/free rungs plus a warning.
  Bad config can never unlock metered providers.
- Ceiling exhausted (month-to-date metered ≥ ceiling) → metered rungs are filtered from
  the chain; subscription/free rungs survive. If filtering empties the chain, the resolver
  exits non-zero with `ceiling-exhausted` so the dispatcher escalates to the human rather
  than silently stalling.
- Corrupt ledger lines are skipped but **counted** (`ledger_errors`), and parseable spend
  still enforces the ceiling. `ASSUMPTION:` skip-and-count beats fail-hard here because one
  torn append must not brick all dispatch; the count keeps the corruption visible.

## 6. Escalation ladder semantics

Two distinct ladder moves, never conflated:

- **Availability fallback (lateral):** the rung is unusable — binary not on PATH, non-zero
  exit, timeout, unparseable contract output (prgroom's four triggers). Move to the next
  chain entry. No gate involved.
- **Quality escalation (climb):** the rung produced work that **failed the completion
  gate** (or the caller's stated Definition of Done). Climb to the next *stronger* rung and
  re-run with the gate findings appended to the brief, so the stronger model fixes rather
  than re-derives.

Two-speed policy (locked decision 4):

| Context | Policy |
|---|---|
| `interactive` | One retry at the preferred rung, then jump directly to the chain's top rung. Wall-clock matters; minutes beat pennies. |
| `background` | Climb stepwise through every rung. Wall-clock is free overnight; tokens are not. |

Bounds (the vaac.3 "ladder bounded" criterion):

- Chain length is capped at 4 rungs (prgroom's `primary` + 3 fallbacks precedent); the
  resolver rejects longer chains at config-validation time.
- At most **one** gate-failure re-run per rung; a rung that fails its gate twice is
  exhausted. A fully exhausted chain is a terminal failure surfaced to the dispatcher
  (background: escalate to human per the escalation path; interactive: report to the user)
  — never a silent retry loop.
- The `interactive` archetype is outside the ladder: the main session's model is the
  user's choice, and gate failures there route to *subagent* dispatches, not to swapping
  the session model.

## 7. Spend ledger + outcome recording (one file, two jobs)

Append-only JSONL at `~/.agents/spend.jsonl` (locked decisions 1–3). Every **metered**
dispatch appends one record on completion; subscription dispatches append too (cost 0)
because the same record carries the A/B outcome data vaac.3 requires:

```json
{"ts": "2026-07-04T21:14:03Z", "session": "a1b2c3d4", "repo": "agents-config",
 "archetype": "implementer", "context": "background",
 "cli": "claude", "model": "sonnet", "rung": 0,
 "tokens_in": 41000, "tokens_out": 9000, "cost_usd": 0.0, "billing": "subscription",
 "outcome": "gate-pass", "retries": 0, "escalated_to": null}
```

- `cost_usd` is computed from the user-configured rates (locked decision 2) — an estimate,
  not an invoice. The ceiling gates on the sum of current-calendar-month `cost_usd` where
  `billing == "metered"`.
- `outcome` ∈ `gate-pass | gate-fail | provider-fail | timeout | parse-fail` and
  `escalated_to` (next rung's model or null) are the A/B substrate: which rungs pass gates
  per archetype, measured, so table defaults can be re-tuned from evidence.
- Writers append a single line per record (POSIX O_APPEND single-write). `ASSUMPTION:`
  single-line JSONL appends are atomic enough cross-process for this ledger; a lock file is
  deliberately omitted until evidence of torn writes appears (`ledger_errors` in §5 is the
  detector).
- Ledger writing is the **dispatcher's** job (the agent doing the dispatching appends after
  the worker returns; prgroom appends from its usage records). `ASSUMPTION:` no hook-based
  auto-capture in v1 — prose rule + prgroom integration first, hooks only if compliance
  measurably leaks.

## 8. Consumers and seams

| Consumer | Change |
|---|---|
| **subagents rule** (`src/user/.agents/rules/subagents.md`) | The right-sizing bullet becomes: consult the routing table (resolver or §3 defaults) and pass the resolved model+effort explicitly on every dispatch. The three-bucket heuristic survives as the summary of the table, not a separate authority. |
| **New shared rule** `model-routing.md` (`src/user/.agents/rules/`) | The policy itself: archetype vocabulary, two-speed ladder, ceiling behavior, ledger append duty. Deploys to all tools (Claude rules dir; flattened into Codex/Gemini/OpenCode assembled files by the installer). |
| **completion-gate / quality-gate workflow** | Finder/refuter/synthesis map to `finder`/`refuter`/`judge` archetypes. The workflow keeps effort tiers; model comes from the table when the harness supports per-agent model override. |
| **prgroom** | Already chain-native. Alignment: its shipped default chains become the `classifier` and `implementer` rows of §3; `.prgroom.toml [agents.*]` remains the per-repo override. `ASSUMPTION:` teaching prgroom to *read* `model-routing.toml` directly is a follow-up bead, not this spec — one dialect first, one loader later. |
| **Escalation-ladder dispatch** (vaac.3) | Session dispatchers (Track-B-style worker briefs, wait-for-pr-comments fixers) resolve the chain before dispatch and encode rung + escalation policy in the worker brief. The archived bead-formula pipeline (implement-bead) is out of scope; its successor consumes the same resolver. |

## 9. Deployment

- Rule + skill asset live under `src/user/.agents/` (shared); installer stages them into
  every detected tool. The resolver script rides the existing skill-asset route (no new
  installer namespace).
- `model-routing.toml` template installs to `~/.agents/` **only if absent** (user-owned
  after first install; never overwritten). `ASSUMPTION:` install-if-absent is sufficient
  until the user-owned-overlay design lands a general mechanism.
- `spend.jsonl` is created lazily by the first writer; never installed, never deleted by
  the installer.

## 10. Out of scope

- Provider billing-API reconciliation (hybrid true-up) — ledger estimates only in v1.
- Hook-based automatic ledger capture.
- prgroom reading `model-routing.toml` directly (follow-up bead; dialect is shared now).
- Re-tuning the §3 default routes from A/B evidence (that is the point of the outcome
  fields, but the analysis loop is the A/B bead's scope).
- The archived bead-formula pipeline (implement-bead et al.) — superseded by M0
  rearchitecture; its successor consumes this resolver.

## 11. Test plan (behavioral contracts for the resolver)

Pure-core behaviors to pin, one vertical slice each (fakes over mocks; ledger and config
as literal temp files, no provider calls anywhere):

1. Known archetype + `background` → full ordered chain from config, verbatim.
2. Known archetype + `interactive` → compressed chain: `[preferred, top rung]` (two-speed).
3. Unknown archetype → non-zero exit; error names the known archetypes.
4. Month-to-date metered spend ≥ ceiling → metered rungs filtered, subscription rungs
   survive, `ceiling.exhausted == true`.
5. Ceiling filtering empties the chain → non-zero exit `ceiling-exhausted`.
6. Ledger with one corrupt line among valid lines → `ledger_errors == 1`, valid spend
   still summed, ceiling still enforced.
7. Spend from a prior calendar month → excluded from the month-to-date sum.
8. Invalid `[budget]`/rate config → chain filtered to subscription/free rungs + warning
   (never fails open to metered).
9. Chain longer than 4 rungs in config → config-validation error at load.
10. Repo `[model-routing]` override row → wins over the user table for that archetype;
    other archetypes unaffected.

## 12. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` §3 archetype list + default routes (author-derived from dispatch sites).
- `ASSUMPTION:` §4.1 `~/.agents/` as the user-config root, pending the user-owned-overlay
  design.
- `ASSUMPTION:` §5 corrupt ledger lines are skip-and-count, not fail-hard.
- `ASSUMPTION:` §7 single-line JSONL appends need no lock file in v1.
- `ASSUMPTION:` §7 dispatcher-appends (prose duty + prgroom), no hook auto-capture in v1.
- `ASSUMPTION:` §8 prgroom keeps its own loader in v1; shared dialect only.
- `ASSUMPTION:` §9 install-if-absent for the TOML template until the overlay mechanism
  lands.
