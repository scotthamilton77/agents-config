# Bounding, stopping and reading a run

## Bound it

Two flags bound how long a run may last. Both belong to the launcher, which
never passes them on to the child.

- `--timeout SECONDS` ends the run that long after it starts.
- `--idle-timeout SECONDS` ends the run once that long passes with no
  completion request forwarded to OpenRouter.

When either one expires, the launcher ends the child's whole process group,
sending `SIGTERM` and then `SIGKILL` to whatever is still alive five seconds
later. It then closes the proxy, prints `[run] reason=timeout` or
`[run] reason=idle` on stderr, and exits `75`. A flag given no value, or a
value that is not a positive number of seconds, exits `78` before anything
starts. Set the Bash tool's timeout above the run's seconds, or run the
command in the background with stdout and stderr written to files.

Without either flag, nothing ends a run whose model never stops thinking.
Choose the values for your task from what runs have been measured to take on
`moonshotai/kimi-k3`:

- A healthy read of text given inline, with no tools, finishes in 4 to 9
  minutes.
- A healthy read of a repository ran 27 minutes over 27 forwarded requests.
- Three recorded runs ended inside a thinking block, one of them after 67
  minutes.

## Stop it early

Send `SIGTERM` or `SIGINT` to the launcher's own process, the `node run.js`
process you started. The launcher ends the child's process group the same way,
even a child that ignores the signal, and exits `75` with
`[run] reason=signal`. Do not signal the child or the proxy yourself; the
launcher owns both.

## Read how it ended

| What you see | Outcome | Your move |
|---|---|---|
| Exit `0`, the child's result on stdout | Usable output. | Use it. |
| Exit `78`, with a `[run]` line naming what was refused or is missing: a flag, a clock value, a model, the API key, the `claude` binary | The launcher refused the invocation. | Fix the invocation. Another provider would not repair it. |
| A `[proxy] model-ledger` line with `decision=deny-pin` or `decision=deny-denylist` | The launcher refused the invocation. | A request named a model this run may not use. Fix the model id or the brief. |
| Exit `75`, with `[run] reason=timeout` or `[run] reason=idle` | The provider did not serve the run. | Move to another provider or model, quoting the reason line. |
| Exit `75`, with `[run] reason=signal` | The provider did not serve the run. | After a signal you sent yourself, stop. |
| The child's non-zero exit, with `[proxy] upstream <status> …` on stderr, such as `402` for spent credits | The provider did not serve the run. | Move to another provider, quoting the upstream line. |
| `[proxy] WARNING: response ends on thinking and contains no text block to promote`, and no answer | The run produced unusable output. | The reply ended inside the model's thinking. Lower the effort, or move to another model. |
