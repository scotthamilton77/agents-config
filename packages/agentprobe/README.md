# agentprobe

Measures how a Claude Code release behaves under scripted multi-agent scenarios, and
reports the rate at which each known behaviour appears, pinned to a version string.

The point is to tell two things apart. A house mitigation that makes a defect rarer
should show a falling hit rate. A Claude Code release that changes the underlying
behaviour should show a step change, in either direction, with no mitigation having
moved. Neither is visible without repeated, identically-scripted runs.

A run only counts once its scenario actually ran. A session whose driver never managed to
type the instruction, or whose lead never reached its terminal state, is reported as
invalid and excluded from every rate. Counting such a run would read as a release having
fixed every behaviour at once.

## A run spends real agent turns

`agentprobe run` launches an interactive Claude Code session on a pseudo-terminal, under
the operator's own configuration and credentials, and lets several agents talk to each
other for a minute or two. That costs real tokens on the operator's account. It is never
part of a continuous-integration gate, and nothing in the test suite launches a session.

The operator's live configuration is deliberate. A fresh configuration directory cannot
authenticate without a human at the keyboard, and the mitigations being measured are the
ones installed there.

## Running one

```bash
uv run agentprobe run teammate-child-messaging --out /tmp/probe --runs 3
uv run agentprobe report /tmp/probe
```

Add `--dry-run` to see the command and the scrubbed environment without launching
anything.

Each run gets its own directory under `--out`, holding:

| file | what it is |
| --- | --- |
| `events.jsonl` | every hook payload, with the hook process's own `CLAUDE*` variables and a snapshot of the session's team config |
| `lead.md` | whatever the scenario's lead wrote |
| `tty.log` | the raw terminal stream, escape sequences and all |
| `claude.err` | the driver's account of the run: what it saw, what it typed, why it stopped |
| `meta.json` | the Claude Code version, the outcome, the start and end times, the scenario and the session id |

## Reading the report

The table gives one row per behaviour, its hits over the runs read, and the version
strings those runs recorded. Under the table, one line per behaviour names the evidence:
event indices into `events.jsonl`, or the message text that carried it.

Under that, any run that did not count is listed by name with the reason, taken from the
driver's own account of the session.

`report` exits 0 whatever it finds. It measures; it does not judge. A behaviour that
shows up is a fact about this version, not a failed build.

The behaviours:

- **phantom-idle** — a teammate is reported idle within three seconds of a *different*
  agent stopping, while the teammate is still blocked inside a foreground call.
- **team-lead-reachable** — whether an agent addressing the alias `team-lead` reaches
  the lead, with the success flag and the message it got back.
- **main-send-lacks-sender** — a message to `main` comes back with no routing, so the
  recipient cannot see who sent it, even when the hook payload names the sender.
- **missing-posttooluse** — a message whose start was recorded and whose completion was
  not.
- **child-to-parent-by-name** — a subagent that is not a team member addresses a member
  by name, the message lands, and the member is resumed by it.
- **duplicate-arrival** — the same message text lands in the lead's record more than
  once.
- **gate-phantom-blocks** — the teammate report gate's block and release decisions that
  coincide with a phantom idle, each one holding a teammate that was never idle.
- **report-file-guard** — per report-shaped filename, whether a subagent's write was
  refused. The refusal happens above the hook layer and produces no event at all, so this
  one reads the agents' own reports, which the scenario has the lead write down.

## Scenarios

Scenarios are prompt files shipped inside the package. The runner substitutes the run
directory into the prompt, so the scenario's lead writes its record where the report will
find it.

- **teammate-child-messaging** — a lead spawns a named teammate, which spawns an
  ordinary subagent, which messages the team lead, the main conversation, and its parent
  teammate by name. The lead records every message that reaches it.
- **report-file-guard** — a lead spawns one unnamed subagent and one named teammate.
  Each tries to write four report-shaped filenames, then edits a file the shell created
  for it, then reports which attempts were refused and with what wording. The two write
  into separate directories, so neither can be refused merely because the other got there
  first.
