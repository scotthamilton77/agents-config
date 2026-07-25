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

When debugging a run, note that `run.js` sets these four in the child
environment and a caller cannot override them: `ANTHROPIC_BASE_URL` (the
proxy), `ANTHROPIC_AUTH_TOKEN` (from `$OPENROUTER_API_KEY`), `ANTHROPIC_API_KEY`
(forced empty — present and empty, since an inherited real key would take
precedence and quietly bill Anthropic), and `CLAUDE_CONFIG_DIR`
(`~/.claude_openrouter`, so the nested process neither collides with nor
inherits the parent session's `~/.claude`).

`CLAUDE_CONFIG_DIR_OPENROUTER` is the one supported override, for pointing the
nested session's config elsewhere.

## What to re-verify when the CLI changes

The launcher requires `--model`, `--effort`, `--permission-mode`, and
`--allowedTools`, and exits `78` naming any that are missing. Those spellings
are Claude Code's, and CLI flags drift across versions. In a fresh environment,
or after a Claude Code upgrade that starts producing exit-`78` failures on
arguments that look correct, check `claude --help` and update the required-flag
list in `run.js` — its tests cover the validation, not the spellings.
