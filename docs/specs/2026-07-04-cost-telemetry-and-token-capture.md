# Cost Telemetry: Token Capture, Ledger Bridge, Weekly Rollup — Design

**Date:** 2026-07-04
**Status:** Draft (pending review)
**Beads:** agents-config-abn9.40.1 (cost telemetry + rollup), agents-config-25rmt (usage-line token parser). One spec, two beads — edits here affect both; each bead's AC section is separate (§9).
**Related:** `2026-07-04-model-routing-policy-and-escalation-ladder.md` §7 defines the ledger this spec feeds; `2026-07-04-cross-model-heavy-gate-panel.md` §5 appends `heavy-gate-run` records this spec's rollup must aggregate; bead agents-config-abn9.8.26 owns the per-attempt `usage_hook` plumbing this spec deliberately does not duplicate (§4 interface contract).
**Decision:** Capture real token/cost figures from the claude and codex CLIs using their **verified** output formats (§3 — captured live 2026-07-04, no longer stipulated); bridge prgroom dispatches into the canonical `~/.agents/spend.jsonl` ledger at dispatch completion; make cost visible through a `spend_rollup.py` script run as a weekly manual ritual. Interactive-session cost comes from `ccusage` at rollup time, not from a new capture hook.

## 1. Problem

The model-routing spec locked a spend ceiling enforced from `~/.agents/spend.jsonl` — but
the ledger has **zero writers**. prgroom's own `usage.jsonl` also receives zero production
rows (`usage_hook` is never passed at either dispatcher build site, `cli.py:134-167`), and
even when wired its `input_tokens`/`output_tokens` are hardcoded `None`
(`dispatcher.py:353-354`) because no parser exists for what the CLIs emit. Four design
docs assert "Claude and Codex CLIs both emit a usage line" without one captured example.
Interactive-session cost (the main loop the human drives) has no capture mechanism at all.

Post-Fable operations cannot tune model routing without seeing cost per dispatch, per
model, per session. That visibility is this spec.

## 2. Architecture: three sources, one canonical ledger

| Source | Granularity | Writer | Record kind |
|---|---|---|---|
| prgroom dispatches | per completed dispatch | the bridge (§4, this spec) | routing-spec §7 dispatch record |
| HEAVY gate runs | per gate run | quality-gate workflow (already spec'd, PR #220) | `heavy-gate-run` |
| Interactive sessions | per session/day/week | **none** — `ccusage` reads Claude Code's local session data at rollup time | not ledgered in v1 |

`spend.jsonl` stays the single canonical cost store (locked decision 3 of the routing
spec). prgroom's `usage.jsonl` remains prgroom's *internal per-attempt* observability
record (every chain-link attempt, including failures — agents-config-abn9.8.26's
domain); `spend.jsonl` records *per-dispatch outcomes* (the winning rung). Two files, two
jobs, one direction of flow.

Interactive sessions are deliberately not ledgered: they bill against the subscription
(ceiling-exempt, `cost_usd` would be 0) and Claude Code already persists the session data
`ccusage` aggregates. A capture hook would add machinery for a number we can already read.

## 3. Token capture — verified CLI formats (bead agents-config-25rmt)

Both formats below were captured live on 2026-07-04 (probe transcripts in the PR).
They are facts, not assumptions.

### 3.1 claude CLI — JSON envelope

`claude -p <prompt> --output-format json` emits a single JSON envelope on stdout:

```json
{"type":"result","subtype":"success","is_error":false,"duration_ms":2436,
 "result":"<the agent's final text — the contract payload lives here>",
 "session_id":"...","total_cost_usd":0.02487,
 "usage":{"input_tokens":10,"cache_creation_input_tokens":18301,
          "cache_read_input_tokens":17757,"output_tokens":43, "...":"..."},
 "modelUsage":{"claude-haiku-4-5-20251001":{"inputTokens":10,"outputTokens":43,
               "costUSD":0.02487,"...":"..."}}}
```

Change `_invocation_for_claude` (`subprocess_runner.py:227-239`) to append
`--output-format json`, and post-process in the runner (claude-only):

1. Parse stdout as the envelope. On success: expose `envelope["result"]` as the
   effective stdout the dispatcher sees, and populate a new
   `AgentRunResult.usage: UsageFigures | None` from `usage.input_tokens`,
   `usage.output_tokens`, and `total_cost_usd` (authoritative-estimate from the CLI —
   preferred over rate math whenever present).
2. On parse failure (older CLI, plain text): fall back to current behavior — raw stdout
   through, `usage=None`. Never fail a dispatch over telemetry.

**Interaction trap (do not skip):** today `_loads_lenient` (`dispatcher.py:392-422`)
takes the **last top-level JSON object** in stdout. With the envelope flag, that object
is the *envelope*, not the contract payload — the unwrap in step 1 MUST happen in the
runner before the dispatcher parses, or every claude dispatch becomes `malformed`.
The unwrap is keyed on the envelope shape (`"type":"result"` + `"result"` key present),
not on the CLI name alone.

### 3.2 codex CLI — stderr trailer

`codex exec --model <m> <prompt>` emits the reply on stdout and a **stderr** trailer:

```
tokens used
21,631
```

Parse the last non-empty stderr lines for `tokens used` followed by a
comma-grouped integer → `tokens_total`. codex provides **no in/out split** in this mode;
`input_tokens`/`output_tokens` stay `None`. (A `--json` mode may carry richer usage; the
one verified codex JSON envelope in-repo — the merge-judge's `task --json` — has **no**
usage field, so this spec builds only on the verified stderr trailer.)

### 3.3 Schema additions

`UsageRecord` (`usage.py`) gains two nullable fields (additive JSONL evolution — readers
must tolerate absent keys): `tokens_total: int | None` (codex path) and
`reported_cost_usd: float | None` (claude path). opencode and ollama emit no counts —
all token fields stay `None` (ollama is `billing = "free"`; its rungs never hit the
ceiling regardless).

## 4. Ledger bridge — prgroom → `spend.jsonl` (bead agents-config-abn9.40.1)

One spend record per **completed dispatch** (success or terminal failure), appended at
the `cli.py` layer where the dispatcher returns — not inside `_run_chain`. Mapping to the
routing-spec §7 record:

| spend field | source |
|---|---|
| `archetype` | contract: `cluster` → `classifier`, `fix` → `implementer` |
| `context` | `"background"` (prgroom is never interactive) |
| `cli`, `model` | the winning chain link's `AgentSpec` |
| `provider`, `billing` | routing-spec §4.1 default `cli→provider` map (explicit `provider` key when the chain entry carries one); billing from `model-routing.toml [providers.*]` when present |
| `rung` | index of the winning link in the chain |
| `tokens_in`/`tokens_out` | `AgentRunResult.usage` (§3); null when uncaptured |
| `cost_usd` | claude: `reported_cost_usd` verbatim. codex: `tokens_total × cost_per_mtok_out` from configured rates, ceiling-conservative. others: `null` |
| `estimated` | **new boolean field** (heavy-gate-run precedent): `false` for claude's reported cost, `true` for codex rate-math, absent/`null` when `cost_usd` is null |
| `outcome`, `retries`, `escalated_to` | from the dispatch result (`gate-pass`/`provider-fail`/`timeout`/`parse-fail` vocabulary per routing spec §7) |

Config read (`model-routing.toml` rates) is parse-only and optional: absent file or
missing rate → `cost_usd: null`, never a crash, never a blocked dispatch.

**Interface contract with agents-config-abn9.8.26 (no scope overlap):** abn9.8.26 wires
the per-attempt `usage_hook` into both dispatcher build sites and fixes `decided_by`;
this spec's bridge appends per-dispatch spend records at dispatch completion. They touch
the same call sites but different records; either can land first. When both are in:
`usage.jsonl` = every attempt (with real tokens from §3), `spend.jsonl` = every dispatch.

## 5. Weekly rollup (bead agents-config-abn9.40.1)

`spend_rollup.py` — PEP 723 script, shipped on the same skill-asset route as the routing
spec's `resolve_route.py` (code over prose; no new installer namespace). Reads
`~/.agents/spend.jsonl`, emits markdown to stdout:

- Month-to-date metered spend vs. `[budget].monthly_ceiling_usd`, with days remaining.
- Per-archetype × model table: dispatches, gate-pass rate, tokens, `cost_usd`
  (estimated share flagged) — the A/B substrate the routing spec's outcome fields exist
  for, plus `heavy-gate-run` records aggregated as their own row.
- Week-over-week delta (this ISO week vs. last).
- Corrupt lines counted and reported (`ledger_errors` discipline), never fatal.
- **Session section:** if `ccusage` is on PATH, shell out (`ccusage --json`, last 7 days)
  and render per-day session cost; if absent, print the one-line install hint. `ccusage`
  is a rollup-time *reader*, never a ledger writer — no double counting.

**Ritual:** manual, weekly — `uv run spend_rollup.py` (documented in `docs/guide/`, one
paragraph). No cron in v1: the ritual's consumer is a human deciding routing changes, and
an unread scheduled report is noise. Revisit after two manual cycles.

## 6. Out of scope

- OTel/Claude Code telemetry export — no consumer exists; ccusage covers session
  visibility. Revisit only if a dashboard consumer materializes.
- Provider billing-API reconciliation (unchanged from routing spec §10).
- Hook-based automatic ledger capture for interactive sessions (§2 rationale).
- opencode/ollama token parsing (no counts exposed by those CLIs' plain modes today).
- prgroom reading `model-routing.toml` for *routing* (unchanged deferral) — the bridge's
  read here is rates-only.
- The `usage_hook` wiring and `decided_by`/partial-fallback fixes (agents-config-abn9.8.26).

## 7. Test plan

Fixtures are the captured probe outputs, embedded as literal strings — no live CLI calls:

1. claude envelope → unwrapped `result` reaches the dispatcher; `usage` populated;
   contract JSON inside `result` parses via the existing lenient path.
2. claude plain-text stdout (no envelope) → passthrough, `usage=None`, dispatch succeeds.
3. Envelope with `is_error: true` → dispatch outcome follows the error; usage still
   captured when present.
4. codex stderr with trailer → `tokens_total` parsed (comma-grouped); stderr without
   trailer → `None`, no error.
5. Bridge: completed fix dispatch (fake result, temp ledger dir) → exactly one
   spend line, correct archetype/rung/provider mapping; cost paths: reported (claude),
   estimated (codex + rates), null (no rates).
6. Rollup: temp `spend.jsonl` with dispatch + heavy-gate-run + one corrupt line →
   table renders, corrupt count = 1, ceiling math correct across a month boundary.

## 8. Sequencing

25rmt (§3) has no dependencies and unblocks real numbers everywhere. The bridge (§4)
consumes §3 but can land with null tokens. The rollup (§5) consumes whatever exists.
Strictly independent of abn9.8.26, by the §4 interface contract.

## 9. Acceptance criteria

**agents-config-25rmt:** claude invoker uses `--output-format json` with envelope unwrap
+ plain-text fallback (tests 1–3); codex stderr trailer parsed (test 4);
`AgentRunResult.usage` populated; `UsageRecord` carries the new nullable fields;
`make ci-prgroom` green.

**agents-config-abn9.40.1:** every completed prgroom dispatch appends one spend record
(test 5); `spend_rollup.py` ships and renders the §5 sections from a real ledger
(test 6); the weekly ritual is documented in `docs/guide/`; cost per dispatch and per
model is answerable from the rollup output, and per session via its ccusage section.

## 10. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` pricing codex's undifferentiated `tokens_total` at the **output** rate is
  the right ceiling-conservative call (overestimates spend, never under). Alternative: a
  configurable in/out split ratio — rejected as tuning theater without evidence.
- `ASSUMPTION:` interactive sessions stay un-ledgered in v1 (ccusage at read time
  suffices; subscription billing makes their ceiling contribution 0). If you want session
  rows in `spend.jsonl` for unified queries, that's a v2 record kind.
- `ASSUMPTION:` `--output-format json` is safe for all prgroom claude dispatches (the
  envelope's `result` field faithfully carries the final text; verified on one probe).
  The plain-text fallback bounds the blast radius if an environment ships an older CLI.
- `ASSUMPTION:` manual weekly ritual beats cron in v1 (§5). Flip to `schedule`/cron only
  after the manual loop proves the report gets read.
