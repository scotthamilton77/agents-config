# Dispatch scenarios for the panel's doctrine

These five scenarios check that a dispatcher who reads the panel's doctrine arrives at the
pinned dispatch for a lens, for a lens that fails over, and for the staffing recommendation.
Each key was written before the doctrine was edited to point at the pins, so the doctrine is
judged against the key and never the other way round.

## How to run them

Run each scenario three times. Each run is a fresh native subagent on the `mid` tier of the
`anthropic` provider, given only the files the scenario names and the prompt below with the
scenario's question filled in. Give it nothing else: no conversation history and no other skill.
A run passes when its answer matches the key on every part the question asks for. A run that
returns no answer is a failed run, and it is not retried. The scenarios pass when all fifteen
runs pass.

The prompt for every run:

```text
You are dispatching one reviewer of a review panel. Read the files listed below and answer
the question from them alone. Answer with the model id, the effort level and the tool grant
(or, where the question asks for them, the provider and the tier), each on its own line, and
then one sentence saying which file and which entry each value came from.

Files:
<the scenario's files, one absolute path per line>

Question: <the scenario's question>
```

The files every scenario gives, as paths from the repository root:

- `src/user/.claude/skills/review-panel/harvest.md`
- `src/user/.claude/skills/review-panel/contracts.json`
- `src/user/.claude/skills/choosing-a-delegate/references/model-routing.md`

Scenarios 1, 2, 3 and 5 add one round record from this directory. The emitter wrote both
records for a `typed-code` pull request. In the round-1 record every lens reads the whole
artifact. In the round-2 record every lens reads the change since round 1.

The keys name the models the routing table named when it was captured on 2026-10-03. Each key
also states the derivation it rests on. When the routing table is re-captured with other models,
re-derive each key's model from the table along that derivation before running the scenarios.

## Scenario 1

- Round record: `src/user/.claude/skills/review-panel/evals/round-2-typed-code.json`
- Question: what model, effort and tools does the `security` lens dispatch with?
- Key: model `z-ai/glm-5.3`, effort `high`, tools `Read`, `Grep`, `Glob`, `Bash(git diff *)` and `Bash(git log *)`.
- Derivation: the round record's `security` entry has transport `openrouter`, which is the
  routing table's provider `openrouter`, and `tier_this_round` `mid`. The table's `mid` cell for
  that provider names `z-ai/glm-5.3`. The effort and the tools are the entry's own `effort` and
  `tools` fields.

## Scenario 2

- Round record: `src/user/.claude/skills/review-panel/evals/round-2-typed-code.json`
- Question: the `correctness` lens's Codex route returned a usage-limit error; what model,
  effort and tools does its next dispatch use?
- Key: model `moonshotai/kimi-k3`, effort `high`, tools `Read`, `Grep`, `Glob`, `Bash(git diff *)` and `Bash(git log *)`.
- Derivation: the `correctness` entry is a `codex` seat at `tier_this_round` `frontier` and
  scope `delta`. Its failover is the other transport's seat at the same tier and scope, which
  is `openrouter`, `frontier`, `delta`. The table's `frontier` cell for provider `openrouter`
  names `moonshotai/kimi-k3`. The effort and the tools are that seat's pin in `contracts.json`.

## Scenario 3

- Round record: `src/user/.claude/skills/review-panel/evals/round-1-typed-code.json`
- Question: the `test-adequacy` lens's Codex route returned a usage-limit error; what model,
  effort and tools does its next dispatch use?
- Key: model `moonshotai/kimi-k3`, effort `low`, tools `Read`, `Grep`, `Glob`, `Bash(git diff *)` and `Bash(git log *)`.
- Derivation: the `test-adequacy` entry is a `codex` seat at `tier_this_round` `mid` and scope
  `full`. The `openrouter` seat at `mid` and `full` has no pin, because the OpenRouter `mid`
  model never reads a whole artifact. The failover is therefore the `openrouter` seat at
  `frontier` and `full`. The table's `frontier` cell for provider `openrouter` names
  `moonshotai/kimi-k3`. The effort and the tools are that seat's pin in `contracts.json`.
- A wrong answer to watch for: `z-ai/glm-5.3` at any effort, which is the `mid` seat the
  failover skips.

## Scenario 4

- Round record: none.
- Question: what provider, tier, effort and tools does the staffing recommendation run with?
- Key: provider `openai`, tier `mid`, effort `medium`, tools the Codex read-only sandbox.
- Derivation: the staffing recommender's pin in `contracts.json` names all four values. The
  model, which the question does not ask for, is the table's `mid` cell for provider `openai`.

## Scenario 5

- Round record: `src/user/.claude/skills/review-panel/evals/round-1-typed-code.json`
- Question: what model, effort and tools does the `correctness` lens dispatch with?
- Key: model `gpt-6.1-sol`, effort `high`, tools the Codex runtime's read-only sandbox.
- Derivation: the `correctness` entry has transport `codex`, which is the routing table's
  provider `openai`, and `tier_this_round` `frontier`. The table's `frontier` cell for that
  provider names `gpt-6.1-sol`. The effort and the tools are the entry's own `effort` and
  `tools` fields, and the value `read-only-sandbox` names the Codex runtime's read-only sandbox.
- A wrong answer to watch for: effort `medium`, which is the pin for the same model at the `mid`
  tier.
