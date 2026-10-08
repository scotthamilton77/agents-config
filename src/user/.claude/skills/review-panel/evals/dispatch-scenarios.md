# Dispatch scenarios for the panel's doctrine

These nine scenarios check that a dispatcher who reads the panel's doctrine arrives at the
pinned dispatch for a lens, at the failover seat for a lens whose route died, at the next step
of the ladder for a lens whose run died, and at the staffing recommendation's pin and its end.
The key is the authority: the doctrine is judged against the key and never the other way round.

## How to run them

Run each scenario three times. Each run is a fresh reader on the `mid` tier of the `anthropic`
provider, given only the files the scenario names and the prompt below with the scenario's
question filled in. Give it nothing else: no conversation history, no instruction file, no
memory and no skill. A headless `claude -p --model sonnet` started in an empty directory with
`--setting-sources ""`, a replaced `--system-prompt`, `--tools Read,Grep,Glob` and the named
files reachable through `--add-dir` is such a reader. An Agent-tool subagent is not, because it
inherits the global instruction files and the memory index.
A run passes when its answer matches the key on every part the question asks for. A run that
returns no answer is a failed run, and it is not retried. The scenarios pass when all
twenty-seven runs pass.

The prompt for every run:

```text
You are dispatching one reviewer of a review panel. Read the files listed below and answer
the question from them alone. Answer with the model id, the effort level and the tool grant
(or, where the question asks for them, the provider and the tier; or, where the question asks
what to do, the action), each on its own line, and then one sentence saying which file and
which entry each value came from.

Files:
<the three files every scenario gives, one absolute path per line>

The round being dispatched: <the absolute path of the scenario's round record, with the words
"this file is the round's round.json", or the words "no round has been emitted yet">

Question: <the scenario's question>
```

The files every scenario gives:

- this skill's `harvest.md`
- this skill's `contracts.json`
- the `choosing-a-delegate` skill's `references/model-routing.md`

Every scenario except 4 and 9 adds one round record from this directory. The emitter wrote both
records for a `typed-code` pull request. In the round-1 record every lens reads the whole
artifact. In the round-2 record every lens reads the change since round 1.

The keys name the models the routing table named when it was captured on 2026-10-03, and the
efforts each of those models accepts there. Each key also states the derivation it rests on.
When the routing table is re-captured with other models or efforts, re-derive each key from the
table along that derivation before running the scenarios.

The proxy line the dead-run scenarios quote is
`response ends on thinking and contains no text block to promote`.

## Scenario 1

- Round record: `round-2-typed-code.json` beside this file
- Question: what model, effort and tools does the `security` lens dispatch with?
- Key: model `z-ai/glm-5.3`, effort `high`, tools `Read`, `Grep` and `Glob`.
- Derivation: the round record's `security` entry has transport `openrouter`, which is the
  routing table's provider `openrouter`, and `tier_this_round` `mid`. The table's `mid` cell for
  that provider names `z-ai/glm-5.3`. The effort and the tools are the entry's own `effort` and
  `tools` fields.

## Scenario 2

- Round record: `round-2-typed-code.json` beside this file
- Question: the `correctness` lens's Codex route returned a usage-limit error; what model,
  effort and tools does its next dispatch use?
- Key: model `moonshotai/kimi-k3`, effort `high`, tools `Read`, `Grep` and `Glob`.
- Derivation: the `correctness` entry is a `codex` seat at `tier_this_round` `frontier` and
  scope `delta`. A usage limit is a dead route, so the next dispatch is the failover seat: the
  other transport's seat at the same tier and scope, which is `openrouter`, `frontier`,
  `delta`. The table's `frontier` cell for provider `openrouter` names `moonshotai/kimi-k3`.
  The effort and the tools are that seat's pin in `contracts.json`.

## Scenario 3

- Round record: `round-1-typed-code.json` beside this file
- Question: the `test-adequacy` lens's Codex route returned a usage-limit error; what model,
  effort and tools does its next dispatch use?
- Key: model `z-ai/glm-5.3`, effort `low`, tools `Read`, `Grep` and `Glob`.
- Derivation: the `test-adequacy` entry is a `codex` seat at `tier_this_round` `mid` and scope
  `full`. Its failover seat is `openrouter`, `mid`, `full`. The table's `mid` cell for provider
  `openrouter` names `z-ai/glm-5.3`. The effort and the tools are that seat's pin in
  `contracts.json`.
- A wrong answer to watch for: `moonshotai/kimi-k3`, which is a seat at another tier.

## Scenario 4

- Round record: none.
- Question: what provider, tier, effort and tools does the staffing recommendation run with?
- Key: provider `openai`, tier `mid`, effort `medium`, tools the Codex read-only sandbox.
- Derivation: the staffing recommender's pin in `contracts.json` names all four values. The
  model, which the question does not ask for, is the table's `mid` cell for provider `openai`.

## Scenario 5

- Round record: `round-1-typed-code.json` beside this file
- Question: what model, effort and tools does the `correctness` lens dispatch with?
- Key: model `gpt-6.1-sol`, effort `high`, tools the Codex runtime's read-only sandbox.
- Derivation: the `correctness` entry has transport `codex`, which is the routing table's
  provider `openai`, and `tier_this_round` `frontier`. The table's `frontier` cell for that
  provider names `gpt-6.1-sol`. The effort and the tools are the entry's own `effort` and
  `tools` fields, and the value `read-only-sandbox` names the Codex runtime's read-only sandbox.
- A wrong answer to watch for: effort `medium`, which is the pin for the same model at the `mid`
  tier.

## Scenario 6

- Round record: `round-2-typed-code.json` beside this file
- Question: the `security` lens's attempt at its pinned effort ended with the proxy line
  `response ends on thinking and contains no text block to promote`; what model, effort and
  tools does its next dispatch use?
- Key: model `z-ai/glm-5.3`, effort `low`, tools `Read`, `Grep` and `Glob`.
- Derivation: the attempt was a dead run on `z-ai/glm-5.3` at the pinned effort `high`, from
  scenario 1. The ladder's first step is the same model at the next lower effort the routing
  table lists for it. The table lists `low`, `high` and `max` for `z-ai/glm-5.3`, so the next
  lower effort is `low`. The tools stay the seat's pin.
- Wrong answers to watch for: the failover seat, which comes only when no lower effort is
  listed; and effort `medium`, which this model does not accept.

## Scenario 7

- Round record: `round-1-typed-code.json` beside this file
- Question: the `security` lens's attempt at its pinned effort was ended by the watchdog for
  silence; what model, effort and tools does its next dispatch use?
- Key: model `gpt-6.1-sol`, effort `high`, tools the Codex runtime's read-only sandbox.
- Derivation: the `security` entry is an `openrouter` seat at `tier_this_round` `frontier` and
  scope `full`, pinned at `low` on `moonshotai/kimi-k3`. A watchdog kill for silence is a dead
  run. The table lists nothing below `low` for that model, so the ladder goes to the failover
  seat: `codex`, `frontier`, `full`. The table's `frontier` cell for provider `openai` names
  `gpt-6.1-sol`, and that seat's pin in `contracts.json` gives the effort and the tools.

## Scenario 8

- Round record: `round-2-typed-code.json` beside this file
- Question: the `security` lens's attempt at its pinned effort and its attempt one effort step
  down both ended with that same proxy line; what model, effort and tools does its next
  dispatch use?
- Key: model `gpt-6.1-sol`, effort `medium`, tools the Codex runtime's read-only sandbox.
- Derivation: the ladder allows one step down, so after the second dead run the next dispatch
  is the failover seat: `codex` at the same tier and scope as the `security` entry, which is
  `mid` and `delta`. The table's `mid` cell for provider `openai` names `gpt-6.1-sol`, and that
  seat's pin in `contracts.json` gives the effort and the tools.
- A wrong answer to watch for: effort `high`, which is the pin of the `frontier` seat.

## Scenario 9

- Round record: none.
- Question: the staffing recommendation's run at its pinned effort and its re-run one effort
  step down were both ended by the watchdog for silence; what does the invoker do next?
- Key: stop the campaign and ask the human.
- Derivation: the staffing recommender has no failover seat. A dead run on it is re-run once at
  the next lower effort the routing table lists, and a second dead run stops the campaign for
  the human, since nothing else can stand in for a staffing decision.
- Wrong answers to watch for: a dispatch on another provider, a further step down, or
  proceeding without a recommendation.
