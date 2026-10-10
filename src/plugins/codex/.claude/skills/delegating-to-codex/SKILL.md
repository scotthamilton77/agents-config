---
name: delegating-to-codex
description: Use when a run is being launched on Codex and the model tier still has to be chosen — the user named Codex, or another skill sent a dispatch here. Not for deciding whether to leave Claude in the first place, not for questions about Codex when nothing is being dispatched, not for Codex CLI setup or auth, and not for OpenRouter or agy.
admission:
  provides: The dispatch procedure for a Codex run and the pointer to its model row — the one routing decision the Codex plugin declines to make, since its own runtime leaves the model unset unless the caller names one.
  cost: The dispatch mechanics need re-verifying whenever the Codex plugin changes its runtime contract.
  remove_when: The Codex plugin's runtime selects a model by task profile itself, so a caller that names nothing still gets the right tier.
---

# Delegating to Codex

Work that may write, such as a fix or an implementation, goes to the
`codex-rescue` agent, which you dispatch with the Agent tool. A run that only
reads, such as a review or a second opinion, is the read-only run below, which
you start from your own shell.
This skill addresses the caller. If you *are* the `codex-rescue` agent, the
dispatch has already happened: reach Codex through your own runtime, as your
agent definition says, and do not dispatch another `codex-rescue` — a rescue
agent that dispatches a rescue agent reviews nothing.
That agent comes from the Claude Code plugin `codex`, published by the
`openai-codex` marketplace — `codex@openai-codex` written in full — and not
from the plugin that deployed this skill, which shares the short name and
nothing else. If the agent does not appear as an agent type in the session,
check whether `codex@openai-codex` is installed, and if it is not, stop and
tell the user rather than falling back to the raw `codex` binary, which stays
forbidden either way.
How the agent reaches Codex once dispatched is its own runtime's contract, not
this skill's.

## Which model

A Codex run carries no explicit model by default, and the runtime keeps it that
way unless the caller names one. Naming it is this skill's whole job, and the
name comes from the `choosing-a-delegate` skill's model routing table: take the
task's tier from its `openai` column. Ask for an effort in the dispatch as
well, chosen for the task from the model's accepted list: the runtime leaves
effort unset unless the request states one, and one OpenAI model serves two
tiers that differ only by the effort you pick. Those rows are captured from the
Codex CLI's own model list, which is the authority for which ids exist and
which effort levels each accepts.

No profile matching cleanly is itself an answer: leave the model unset and take
the plugin's default rather than forcing a row to fit.

## Where this sits relative to the rescue agent

The rescue agent is the executor. This table is the decision made just before it
runs, so the two compose rather than compete — dispatch the agent as you would
anyway, and let the dispatch carry a model when a profile above matches.

Which one leads depends on who is stuck:

- **Routing a defined task to Codex** — the profile is known, so pick the tier
  here, then dispatch.
- **Reaching for help because the work has stalled** — dispatch first. Let the
  runtime default stand unless the profile is obvious.

## Dispatching the rescue agent

Dispatch `codex-rescue` **unnamed**. A `name` turns it into a teammate with the
orchestration kit; it then reads this skill, follows "dispatch the rescue
agent", and spawns a second copy of itself instead of forwarding. Brief it to
put an explicit Bash `timeout` (about 1,500,000 ms) on the companion call and
never to pass `--wait` — an unknown flag is folded into the Codex prompt, and
an untimed call past the default 120 s is auto-backgrounded where a Bash-only
agent cannot collect it. A result that says it is "waiting for the background
task" is a dead agent, not a pending one.

Never export `CODEX_HOME` pointing at the plugin directory. It is Codex's own
home, where `auth.json` lives; pointed elsewhere, requests go out with no
credential and `401 Missing bearer` from `api.openai.com/v1/responses` is the
fingerprint. Hold the companion path in a variable of another name.

## The read-only run

Run the plugin's companion script with its `task` command and no `--write`.
Without that flag Codex runs in a read-only sandbox, where it cannot write a
file, so never ask it to write its report. Your shell redirects stdout into the
report file instead, and writes the pid of the process it launched to a file:

```bash
COMPANION="$(ls ~/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs | sort -V | tail -n 1)"
node "$COMPANION" task --model <model> --effort <level> --prompt-file <brief> \
  > <report> 2> <log> & echo $! > <pidfile>; wait $!
```

Give the Bash call a timeout of about 1,500,000 ms. A whole-spec read on the
frontier tier has run 24 to 28 minutes, so a call can outlive that timeout and
be moved to the background. The run is not dead then. It keeps writing to your
files, and starting a second run only pays twice. Wait until the pid in
`<pidfile>` has exited, then read the report: the run is finished only when
that process is gone. Check at intervals of a minute or so, with
`kill -0 "$(cat <pidfile>)"`, for up to 45 minutes, then stop it.

To stop a run, signal that pid: `kill -TERM "$(cat <pidfile>)"`. Never select
the process by name, because another agent's Codex run on this machine has the
same name. A run you stopped yourself is over; do not start it elsewhere.

How the run ended, read from the exit status, or from the log when the call was
moved to the background:

| What you see | Outcome |
|---|---|
| Exit `0`, the report in `<report>`, `[codex] Turn completed.` in `<log>` | Usable output. |
| Exit `0`, and `<report>` holds `Codex did not return a final message.` or a reply that is not the report you asked for | The run produced unusable output. Re-brief, or try another model. |
| Exit `1`, with a `[codex] Codex error:` line or a turn that ended other than `Turn completed.` | The provider did not serve the run. `You've hit your usage limit` in that line means the subscription is spent, and repeating the run fails the same way. |
| Exit `1`, with `Codex CLI is not installed…` | The provider did not serve the run. |
| Exit `1`, with one line in `<log>` and no `[codex]` line at all | The companion refused the invocation. Fix the command. |

The model and the effort reach Codex as `--model` and `--effort`, chosen as the
section above says.
