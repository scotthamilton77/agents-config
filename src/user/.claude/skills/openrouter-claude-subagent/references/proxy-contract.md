# The Repair Proxy Contract

Why `scripts/run.js` is the only supported way to launch, what its in-process
proxy changes on the wire, and what that costs you.

## The failure it repairs

Claude Code returns `"result": ""` — with **exit 0, empty stderr, and tokens
billed** — whenever an assistant response ends on a `thinking` or
`redacted_thinking` block, which OpenRouter emits routinely. The answer is
generated and paid for; it just never reaches the caller. Nothing in the exit
status or the logs says so. This is why pointing `ANTHROPIC_BASE_URL` straight
at `openrouter.ai` is not a shortcut but a silent, billable dead end.

`scripts/proxy.js` moves the trailing text block to the end of the response so
it never terminates on reasoning. The repair is deliberately narrow — block
order is otherwise preserved, because the client replays that order back
upstream on the next turn.

## The second repair, and its consequence for tool grants

Claude Code declares some of its tools as *deferred* — left out of the request
and reachable only through `ToolSearch`. OpenRouter refuses that declaration
for every non-Anthropic model, rejecting the whole request with an HTTP 400
before a single token is generated. For a non-Anthropic model the proxy
removes the deferred-tool declaration, so the run proceeds with exactly the
tools granted via `--allowedTools`.

Practical consequence: **the subagent can use only the tools you list.** There
is no deferred pool to fall back on. List everything the task needs.

## The model pin

A nested run can start runs of its own, and each of those picks its own model
— named outright, taken from an agent type's definition, or taken from a
built-in default. Every one of them bills the same OpenRouter account and
answers in the launching run's name. Left alone, that is how a cheap run on one
vendor's model quietly becomes an expensive run on another's, with the point of
view you launched it for replaced along the way.

The launcher pins the run to the one model you named, three ways:

- **Redirect.** All four model aliases — `ANTHROPIC_DEFAULT_OPUS_MODEL`,
  `..._SONNET_MODEL`, `..._HAIKU_MODEL`, `..._FABLE_MODEL` — are set to
  `--model`. Delegation still works; it just cannot leave the model you paid
  for. This is the part that keeps subagents useful rather than banning them.
- **Pin.** On a completion request the rule is exact match or nothing: any
  other model gets an HTTP 403 carrying an Anthropic-shaped error body, and
  nothing is dialed upstream. A request naming *no* model is refused on the
  same rule — it has not switched models, but it has handed the choice to
  whatever is upstream, which loses the same control by a quieter route. The
  message says what to do instead — carry on unaided, or delegate with the
  model field left out — because an API error is the only channel back to
  whatever asked.
- **Denylist.** Claude models and the large GPT tiers are refused outright,
  pin or no pin: they are served properly elsewhere, so arriving here means
  something misrouted. The `-mini` GPT variants are exempt. The launcher exits
  `78` before binding a listener when `--model` names one; the proxy refuses
  them too, so neither layer depends on the other.

Alias redirection also covers the background chores the harness runs on the
cheap alias, which would otherwise bill the model you named. `run.js` switches
those off with `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`. Note the semantics:
**any non-empty value enables the setting, `"0"` included.** It reads as a
switch, not a boolean, so there is no way to spell "off" except by unsetting it.

Every completion request leaves one line on stderr naming the method, path,
model, and decision (`forward`, `deny-pin`, or `deny-denylist`). When a bill
looks wrong later, that ledger is the record to read.

The gate applies to requests that generate a reply. A request that only
measures a payload — counting its tokens — is forwarded without being checked
or logged, since nothing is produced and nothing is billed.

## Why in-process, on a kernel-assigned port

The proxy runs inside the launcher process, listening on `port: 0`. Two
properties follow, both load-bearing:

- **Concurrent sessions are safe.** The kernel hands out distinct ports
  atomically, where "pick a port and check whether it is free" races.
- **No orphan can survive.** The listener dies with the launcher under any
  signal, including `SIGKILL`. A spawn-plus-trap design only cleans up if the
  wrapper lives long enough to run the trap — and gets no say at all under
  `SIGKILL`, leaving a proxy squatting a port and poisoning every later run.

## What the launcher owns

When debugging a run, note that `run.js` sets all of these in the child
environment and a caller cannot override them: `ANTHROPIC_BASE_URL` (the
proxy), `ANTHROPIC_AUTH_TOKEN` (from `$OPENROUTER_API_KEY`), `ANTHROPIC_API_KEY`
(forced empty — present and empty, since an inherited real key would take
precedence and quietly bill Anthropic), `CLAUDE_CONFIG_DIR`
(`~/.claude_openrouter`, so the nested process neither collides with nor
inherits the parent session's `~/.claude`), the four
`ANTHROPIC_DEFAULT_*_MODEL` aliases and
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` (both above). An alias redirect
inherited from the parent environment is overwritten, not honoured.

`CLAUDE_CONFIG_DIR_OPENROUTER` is the one supported override, for pointing the
nested session's config elsewhere.

## What to re-verify when the CLI changes

The launcher requires `--model`, `--effort`, `--permission-mode`, and
`--allowedTools`, and exits `78` naming any that are missing. Those spellings
are Claude Code's, and CLI flags drift across versions. In a fresh environment,
or after a Claude Code upgrade that starts producing exit-`78` failures on
arguments that look correct, check `claude --help` and update the required-flag
list in `run.js` — its tests cover the validation, not the spellings.
