# Dispatch scenarios for the skill's doctrine

These six scenarios check that a dispatcher who reads this skill's doctrine arrives at the pinned
dispatch for a lens, at the next step of the ladder for a lens whose run died, and at the ladder's
end. The key is the authority: the doctrine is judged against the key and never the other way
round.

## How to run them

Run each scenario three times. Each run is a fresh reader on the `mid` tier of the `anthropic`
provider, given only the files the scenario names and the prompt below with the scenario's
question filled in. Give it nothing else: no conversation history, no instruction file, no
memory and no skill. A headless `claude -p --model sonnet` started in an empty directory with
`--setting-sources ""`, a replaced `--system-prompt`, `--tools Read,Grep,Glob` and the named
files reachable through `--add-dir` is such a reader. An Agent-tool subagent is not, because it
inherits the global instruction files and the memory index.
A run passes when its answer matches the key on every part the question asks for. A run that
returns no answer is a failed run, and it is not retried. The scenarios pass when all eighteen
runs pass.

The prompt for every run:

```text
You are dispatching one attacker of a criteria-attack panel. Read the files listed below and
answer the question from them alone. Answer with the model id, the effort level and the tool
grant (or, where the question asks what to do, the action and whether the round can close), each
on its own line, and then one sentence saying which file and which entry each value came from.

Files:
<the two files every scenario gives, one absolute path per line>

The round being dispatched: <the absolute path of the scenario's round record, with the words
"this file is the round's round.json">

Question: <the scenario's question>
```

The files every scenario gives:

- this skill's `SKILL.md`
- the `choosing-a-delegate` skill's `references/model-routing.md`

Every scenario adds the round record `round-1.json` beside this file, which the emitter wrote
over a one-criterion document. Every attack read is a whole-document read with the text inline,
so a round record has one entry per lens and no scope field.

The keys name the models the routing table named when it was captured on 2026-10-03, and the
efforts each of those models accepts there. Each key also states the derivation it rests on.
When the routing table is re-captured with other models or efforts, re-derive each key from the
table along that derivation before running the scenarios.

The proxy line the dead-run scenarios quote is
`response ends on thinking and contains no text block to promote`.

## Scenario 1

- Question: what model, effort and tools does the `set-consistency` lens dispatch with?
- Key: model `z-ai/glm-5.3`, effort `low`, no tools.
- Derivation: the round record's `set-consistency` entry has transport `openrouter`, which is
  the routing table's provider `openrouter`, and tier `mid`. The table's `mid` cell for that
  provider names `z-ai/glm-5.3`. The effort and the tools are the entry's own `effort` and
  `tools` fields, and an empty `tools` list is no tools.
- A wrong answer to watch for: `moonshotai/kimi-k3`, which is the provider's `frontier` model.

## Scenario 2

- Question: what model, effort and tools does the `what-if` lens dispatch with?
- Key: model `z-ai/glm-5.3`, effort `low`, no tools.
- Derivation: as scenario 1; the `what-if` entry declares the same transport, tier and pin.

## Scenario 3

- Question: what model, effort and tools does the `behavioural-outcome` lens dispatch with?
- Key: model `gpt-6.1-sol`, effort `high`, tools the Codex runtime's read-only sandbox.
- Derivation: the `behavioural-outcome` entry has transport `codex`, which is the routing
  table's provider `openai`, and tier `frontier`. The table's `frontier` cell for that provider
  names `gpt-6.1-sol`. The effort and the tools are the entry's own `effort` and `tools` fields,
  and the value `read-only-sandbox` names the Codex runtime's read-only sandbox.
- A wrong answer to watch for: effort `medium`, which is the failover pin for a lens arriving
  on Codex from the other transport.

## Scenario 4

- Question: the `set-consistency` lens's attempt at its pinned effort ended with the proxy line
  `response ends on thinking and contains no text block to promote`; what model, effort and
  tools does its next dispatch use?
- Key: model `gpt-6.1-sol`, effort `medium`, tools the Codex runtime's read-only sandbox.
- Derivation: the attempt was a dead run on `z-ai/glm-5.3` at the pinned effort `low`, from
  scenario 1. The ladder's first step is the same model at the next lower effort the routing
  table lists for it, and the table lists `low`, `high` and `max` for `z-ai/glm-5.3`, so
  nothing lies below the pin. The ladder therefore goes to the failover seat: the other
  transport, `codex`, at the same tier, `mid`. The table's `mid` cell for provider `openai`
  names `gpt-6.1-sol`. The effort and the tools are the failover pin the skill states for a lens
  arriving on Codex.
- Wrong answers to watch for: a second attempt on `z-ai/glm-5.3`, and effort `high`, which is
  the pin of the lenses that start on Codex.

## Scenario 5

- Question: the `behavioural-outcome` lens's attempt at its pinned effort and its attempt one
  effort step down were both ended by the watchdog for silence; what model, effort and tools
  does its next dispatch use?
- Key: model `moonshotai/kimi-k3`, effort `low`, no tools.
- Derivation: a watchdog kill for silence is a dead run. The pinned attempt ran `gpt-6.1-sol`
  at `high`, and the step down ran it at `medium`, the next lower effort the table lists. The
  ladder allows one step down, so after the second dead run the next dispatch is the failover
  seat: the other transport, `openrouter`, at the same tier, `frontier`. The table's `frontier`
  cell for provider `openrouter` names `moonshotai/kimi-k3`. The effort and the tools are the
  failover pin the skill states for a lens arriving on OpenRouter.
- Wrong answers to watch for: a further step down to `low` on `gpt-6.1-sol`, and
  `z-ai/glm-5.3`, which is a seat at another tier.

## Scenario 6

- Question: the `set-consistency` lens's pinned attempt ended with the proxy line
  `response ends on thinking and contains no text block to promote`, and its failover attempt was
  ended by the watchdog for silence; what does the dispatcher do next, and can the round close?
- Key: no further dispatch; the lens has no report for the round; the round does not close.
- Derivation: a watchdog kill for silence is a dead run on either transport, and a dead run on
  the failover attempt ends the ladder. The lens has no report, and
  the record's own rules give a lens that returned nothing usable no entry: the round closes
  only by running that lens again later, never by recording it empty.
- Wrong answers to watch for: a step down on the failover model, a third model, or closing the
  round with the lens recorded empty.
