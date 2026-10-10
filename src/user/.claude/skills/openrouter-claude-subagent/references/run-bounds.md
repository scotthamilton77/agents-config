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

Read the rows in order; the first that matches decides.

| What you see | Outcome | Your move |
|---|---|---|
| `[proxy] WARNING: response ends on thinking` or `on redacted_thinking`, `and contains no text block to promote`, and the result holds no answer, whatever the exit | The run produced unusable output. | The reply ended inside the model's thinking. Lower the effort, or move to another model. |
| Exit `0`, and the child's result on stdout holds an answer | Usable output. | Use it. |
| Exit `78`, with a `[run]` line naming what was refused or is missing: a flag, a clock value, a model, the API key, the `claude` binary | The launcher refused the invocation. | Fix the invocation. Another provider would not repair it. |
| Every `[proxy] model-ledger` line carries `decision=deny-pin` or `decision=deny-denylist`, and the child exits non-zero | The launcher refused the invocation. | The run's own model id was refused. Fix the model id. |
| Exit `75`, with `[run] reason=timeout` or `[run] reason=idle` | The provider did not serve the run. | Move to another provider or model, quoting the reason line. |
| Exit `75`, with `[run] reason=signal` | The provider did not serve the run. | After a signal you sent yourself, stop. |
| Any other non-zero exit, such as the child's `1` with a `[proxy]` error line: `upstream <status> …` (`402` for spent credits), `upstream request error`, `upstream response error`, `upstream request timeout`, or `upstream stream ended without message_stop` | The provider did not serve the run. | Move to another provider, quoting the line. |

A `decision=deny-pin` or `decision=deny-denylist` line among forwarded requests
is not an ending. The proxy refused one nested request for a model this run may
not use, and the run goes on to one of the endings above.
