# OpenRouter Model Routing Table

Captured **2026-09-17** from `https://openrouter.ai/api/v1/models`, OpenRouter's
public catalog endpoint. That endpoint is authoritative for price, context
length, max output, and which reasoning-effort levels a model accepts, and it
is machine-readable — refresh this table from it rather than reading model
pages by hand. Read the interactive row of each model, never its `:batch`
variant: batch prices are half and are not what a dispatch from here pays.
Re-verify there before routing anything cost-sensitive: OpenRouter reprices and
retires models without notice, and this table is a snapshot that starts
decaying immediately.

This launcher also denies two model families outright, independent of price:
Claude models, and every `gpt-` model (`scripts/proxy.js`'s
`DENIED_MODEL_PREFIXES` — see `references/proxy-contract.md`'s Denylist
section). Both run properly through other transports, so the table below
omits them entirely: every row here is a model this launcher can actually
start.

Prices are $/M tokens. Rows are sorted by input price.

| Model ID (`--model` value) | Input $/M | Output $/M | Context | Effort levels accepted | Best for |
|---|---|---|---|---|---|
| `deepseek/deepseek-v4.1-flash` | $0.15 | $0.60 | 1M / 384K out | `low` `high` `max` — no `medium` | Cheapest capped reasoner in the table; unqualified for a whole-artifact read until a run completes one |
| `google/gemini-3.5-flash-lite` | $0.30 | $2.50 | 1M / 64K out | `minimal` `low` `medium` `high` | High-volume triage, extraction, formatting |
| `moonshotai/kimi-k2.7-code` | $0.71 | $3.21 | 262K | **none** — reasoning always on, **cannot be capped** | Code-tuned mid-tier, strong cost/perf for implementation |
| `google/gemini-3.8-flash` | $0.75 | $3.75 | 1M / 64K out | `low` `medium` `high` — no `minimal` | Fast agentic coding; the OpenRouter mid seat below |
| `moonshotai/kimi-k2.6` | $0.95 | $4.00 | 262K | **none** — reasoning on/off only | General/mechanical Kimi tier; the one Kimi whose thinking can be switched off |
| `z-ai/glm-5.3` | $1.40 | $4.40 | 1.3M / 944K out | `low` `high` `max` — no `medium`, no `xhigh` | Long-horizon agentic coding at 1M context; returns thinking-only turns on a whole-document single pass, so unfit for one until a run completes it |
| `moonshotai/kimi-k3` | $3.00 | $15.00 | 1M / 944K out | `low` `high` `max` — no `medium`, no `xhigh` | Frontier-tier agentic coding, large repos; the OpenRouter frontier seat below |

## Review seats

A review-panel or ac-attack lens does not go through the task buckets. Its
transport and tier resolve to one row here, and the row fixes the model, the
effort and the tool grant. A lens's scope changes the row: a whole-artifact
read (round 1, a sweep, or any document attack) is one long single pass, while
a delta read (a later round over the change since the head the lens last
judged) is short. The round record states which one each lens has.

| Seat | Model | Effort | Tools |
|---|---|---|---|
| OpenRouter frontier, delta read | `moonshotai/kimi-k3` | `high` | `Read` `Grep` `Glob` |
| OpenRouter frontier, whole-artifact read | `moonshotai/kimi-k3` | `medium` — reaches the model as a thinking budget, since it lists no such level | none when the prompt carries the text inline; `Read` `Grep` `Glob` when the lens must resolve the target itself |
| OpenRouter mid (the re-review tier of the frontier seats) | `google/gemini-3.8-flash` | `high` | `Read` `Grep` `Glob` |
| Staffing recommender | `moonshotai/kimi-k2.6` | `medium` | none |
| Trend checkpoint | Fable, in the launching harness | `high` | the harness's own |

Why the rows are what they are, stated so the next refresh can attack them:

- `kimi-k3` at `high` on a whole-artifact read ends the stream inside a
  thinking block and delivers no message: the proxy sees a response that ends
  on thinking with no text block to promote, after the upstream request has
  timed out repeatedly. At `medium`, a level the model does not list, the CLI's
  flag arrives as a thinking budget rather than a named effort, and the same
  read completes with comparable output. `low` bounds the thinking harder and
  is unmeasured for this seat. On a delta read `high` completes and reads per
  criterion, which a cheaper Flash-class model in the seat does not.
- A `Read` grant on a prompt that already carries the whole text invites the
  nested harness to explore the repository instead of answering in one turn:
  a dozen forwarded requests at frontier prices for a review that needed one.
- The two OpenRouter seats name different vendors on purpose. Both on Kimi is
  one vendor filling two seats, and the verdict's distinct-vendor count cannot
  see it.
- `gemini-3.8-flash` holds the mid seat with the least evidence in the table.
  A Flash-class model in this seat can return a clean verdict having read
  little or nothing of the target; the review panel's dispatch gate refuses a
  clean report with no recorded read, which is what makes the seat tolerable
  rather than proven.
- `kimi-k2.6` recommends staffing: on a five-lens typed-code roster it keeps
  every seat with a target-shaped reason each, where a Flash-class recommender
  drops correctness on test-only deltas and security on small ones, and a
  dropped security seat costs a whole sweep round later.

The Codex seats are rows in the `delegating-to-codex` skill. The checkpoint row
lives here because this is the seat table; its dispatch never touches OpenRouter.
The recommender's `medium` satisfies the launcher, which requires an effort flag;
`kimi-k2.6` lists no levels and keeps its reasoning on regardless.

## Reading the effort column

The column lists the discrete levels each model accepts on OpenRouter's
normalized `reasoning.effort` parameter. Two consequences worth internalizing
before dispatch:

- **Not every level exists on every model.** `glm-5.3`, `kimi-k3` and
  `deepseek-v4.1-flash` run `low`/`high`/`max` with no `medium` and no `xhigh`
  — a task that wants "high or xhigh" gets `high` or `max`, nothing between.
  Both Kimi mid-tier models accept no level at all.
- **One of those cannot be capped at all.** `kimi-k2.7-code` reasons
  mandatorily and takes no effort level, so its thinking can only be endured,
  never bounded. Give an uncappable model a long whole-artifact task behind a
  streaming idle deadline — a full-document review, a large-diff pass — and
  the stream can end inside a thinking block having delivered no message at
  all. That is a property of the model class rather than of one row, so it
  recurs as the table turns over: route long single-pass work to a model whose
  effort you can set, and re-check this column before trusting a model that
  reads as `none`. `kimi-k2.6` reads as `none` too but differs where it
  matters — its reasoning is optional, so it can be switched off outright.
  A cappable model is not safe by that fact alone: `kimi-k3` at `high` dies the
  same way on a whole-artifact read, and only a budget-capped row completes one.
- **The mapping from the CLI to that parameter is unverified.** The Claude
  Code CLI's `--effort` flag travels through OpenRouter's Anthropic-compatible
  skin, which speaks the Messages API's thinking budget rather than
  `reasoning.effort` directly. What this table records is what the *model*
  accepts, not proof that a given `--effort` value arrives as that level.
  Asking `kimi-k3` for `medium`, a level it does not list, produces a capped
  run that completes, so something reaches the model; what, exactly, is
  unmeasured. Where the effort lever matters to an outcome, treat model choice
  as the reliable control and the effort level as a hint.

## Sampling parameters

This launcher pins none. A parameter absent from the request is omitted
upstream and the provider's own default applies
(<https://openrouter.ai/docs/api-reference/parameters>) — and a parameter you
do send is forwarded, not clamped. Omission is the safe state, because the
rows above disagree about what a pinned value may even be. Before pinning
anything, per provider:

- **Kimi thinking/code tiers** (`moonshotai/kimi-k2.7-code`,
  `moonshotai/kimi-k2.6`): temperature is not modifiable — do not pass one.
  Tool-calling runs want `max_tokens >= 16000`, and multi-turn tool use must
  send the model's `reasoning_content` back with the next request.
  (<https://platform.kimi.ai/docs/guide/use-kimi-k2-thinking-model>)
- **Gemini rows**: Google strongly recommends leaving temperature at its
  default 1.0 for all Gemini 3 models — lowering it can cause looping or
  degraded output (<https://ai.google.dev/gemini-api/docs/gemini-3>) — and
  its structured-output docs grant no exemption for schema-constrained
  requests. Newer Google migration guidance may deprecate
  `temperature`/`top_p`/`top_k` outright for recent Flash tiers; re-read
  <https://ai.google.dev/gemini-api/docs/generate-content/latest-model>
  before pinning anything on a Gemini row. Reproducibility is not
  purchasable here either way: Gemini's `seed` is documented best-effort.
- **GLM**: no first-party sampling recommendation exists; leave the default.

## Selection by task bucket

| Bucket | Default pick | Step down (user said "cheap") | Step up (user said "best"/"most capable") |
|---|---|---|---|
| Mechanical / triage | `google/gemini-3.5-flash-lite` | — cheapest input is already here; take `google/gemini-3.8-flash` instead when the output dominates | `moonshotai/kimi-k2.6` |
| Standard implementation | `moonshotai/kimi-k2.7-code` | `google/gemini-3.5-flash-lite` | `moonshotai/kimi-k3` |
| Architecture / judgment-heavy | `z-ai/glm-5.3` | `google/gemini-3.8-flash` | `moonshotai/kimi-k3` |

## Anthropic-compatibility mechanics

`https://openrouter.ai/api` exposes an Anthropic Messages API–compatible
endpoint (OpenRouter's "Anthropic Skin"), which is what lets
`ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` route a stock Claude Code process
through it. Compatibility is not complete: responses that end on a reasoning
block break the client, which is why this skill routes through the local repair
proxy rather than pointing at OpenRouter directly (see `proxy-contract.md`).
Model IDs are OpenRouter's normal `vendor/model-slug` form — no extra prefixing
beyond what is in this table.

## Supplemental registry

This table is the versioned, source-controlled baseline. A model a user names
that isn't listed here may still be recorded in
`~/.config/agents-config/openrouter-model-registry.json` — a runtime registry
the workflow below reads and writes. Check both before concluding a model is
unverified.

The registry lives outside the repo because it is runtime state this skill
accumulates across invocations, not versioned skill content. It is a JSON
object keyed by model ID:

```json
{
  "vendor/model-id": {
    "input_per_m": 0.00,
    "output_per_m": 0.00,
    "context": "...",
    "supported_efforts": ["low", "high"],
    "best_for": "...",
    "added": "YYYY-MM-DD",
    "source": "user-reported | catalog | researched: <url>"
  }
}
```

An entry written before 2026-07-25 may carry `effort_param` instead, whose
`confirmed` value means only that the model reasons — not which levels it
takes. Treat that as levels-unknown and re-read it from the catalog when it
matters.

## Unknown Model Workflow

Triggered when a user-named `vendor/model-id` appears in neither the table
above nor the supplemental registry.

1. Tell the user plainly: this skill has no pricing, context, or effort data
   on that model.
2. Ask them to choose — **(a)** proceed with it as specified, accepting that
   cost and capability are unverified, or **(b)** look it up now in the catalog
   endpoint, which carries `pricing`, `context_length`, `top_provider`, and
   `reasoning.supported_efforts` for every listed model.
3. Present what you found *and from where* for confirmation before using it.
   If the model is absent from the catalog entirely, say so — that means
   OpenRouter does not serve it, and no amount of further searching will
   change the dispatch outcome.
4. Once confirmed, ask whether to persist it for future invocations. If yes,
   create `~/.config/agents-config/` if absent and write or update the entry
   using the schema above.
