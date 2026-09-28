---
name: delegating-to-agy
description: "Use when a run is being launched on Antigravity CLI (agy), Google's runtime for Gemini models: as a full worker in the current checkout, or as a fresh-context review lens over a snapshot whose instruction files stay out. Apply when the user names agy, Antigravity or a Gemini model, or when another skill sends a Gemini dispatch here. Not for deciding whether to leave Claude, not for agy setup or sign-in, and not for OpenRouter, which is this route's fallback once the subscription quota is spent."
admission:
  provides: "An agy run in one of two verified shapes: a worker in the current checkout that reads the user's and the repository's instruction files like a Claude or Codex worker does, or a fresh-context lens over a snapshot of a revision, run under a temporary home that holds only a Keychain link so no user-level rule or skill loads, with the change's own instruction files renamed so nothing under review instructs the reviewer, every hook and MCP configuration under a customization root renamed so nothing launches, and the change's diff beside them. Invoking it produces the launcher command, its exit code contract, and the model id for the task profile."
  cost: agy must be installed and signed in, and every run bills the Google AI Pro subscription; lens mode needs macOS for the Keychain link and leaves a snapshot of the reviewed revision and a temporary home on disk for the run's duration; the model table needs a refresh whenever agy's model list changes.
  remove_when: The Google AI Pro subscription lapses, agy loses headless print mode, or the review tooling addresses agy natively so no launcher stands between a caller and a Gemini seat.
---

# Delegating to agy

agy is Antigravity CLI, Google's command-line runtime for Gemini models. Its runs
bill the user's Google AI Pro subscription.

Launch agy only through `agy_run.py`, which ships in this skill's `scripts/`
directory. A bare `agy -p` run reports a denied tool call or a timeout as
success, with exit 0 and an empty answer. The launcher reads agy's event
stream and turns each of those cases into an exit code you can act on.

## Pick the mode

| Mode | What runs | Pick it for |
|---|---|---|
| `worker` | agy in the current directory with the real home. The user's agy rules and skills load, and so do the checkout's own instruction files. It can edit files. | Implementing or investigating in this checkout, as a Claude or Codex worker would. |
| `lens` | agy read-only over a snapshot of one committed revision, under a temporary home. No user-level rule or skill loads, and neither does any instruction file the change adds or modifies. | An independent review, where neither the user's own rules nor the change under review may instruct the reviewer. |

## Launch

```bash
uv run "${CLAUDE_SKILL_DIR}/scripts/agy_run.py" worker \
  --model <agy-model-id> --timeout <seconds> -p "<prompt>"

uv run "${CLAUDE_SKILL_DIR}/scripts/agy_run.py" lens \
  --repo <path> --base <base-rev> [--rev <rev>] --model <agy-model-id> \
  [--timeout <seconds>] [--keep-snapshot] -p "<prompt>"
```

The mode comes first. `-p` comes last, and the prompt is the one argument after
it. Pass a long brief as `-p "$(cat brief.md)"`. The launcher refuses any
element after the prompt, and any element before `-p` that is not one of its
own flags. If `uv` is
missing, run the script with `python3` 3.12 or later, since it needs only the
standard library.

`--model` takes a full agy model id, and the id carries the effort. Look the id
up in `references/model-routing.md` by task profile. The launcher refuses
`--effort` and any `claude-` id.

`--timeout` is a positive whole number of seconds. A worker must pass it, and a
lens defaults to 600. agy enforces the limit itself. If agy overruns it, the
launcher stops agy 30 seconds later and kills its process group 10 seconds after
that. Set the Bash tool's timeout above the run's seconds plus 40, or run the
command in the background. In the background, write stdout and stderr to
separate files, because they carry different things.

A worker's edits stay in the checkout whatever the exit code, so check
`git status` after every worker run.

### Worker preconditions

The launcher refuses a worker unless the current directory is at or beneath a
path in `trustedWorkspaces` of `~/.gemini/antigravity-cli/settings.json`,
because agy denies every headless edit anywhere else. A relative entry in that
list trusts nothing. A worker's shell commands are limited to the
`permissions.allow` list in the same file. Adding a trusted path or a command
widens what agy may do on the user's machine, so ask the user before editing
that file. The launcher defines no permission bypass, and it refuses
`--sandbox`, `--dangerously-skip-permissions` and `--skip-permissions`.

### What a lens sees

A lens reviews a revision, never a working tree. `--base` and `--rev` take any
commit-ish, and `--rev` defaults to the `HEAD` of `--repo`. Commit uncommitted
work to a temporary ref, or run the lens on a worktree's head. For a branch,
pass the merge base as `--base`, for example
`$(git -C <path> merge-base main HEAD)`, so the diff covers only the branch's
own change. To review a whole artifact rather than a change, pass the same
revision as `--base` and `--rev`, and the diff is empty.

The launcher builds the snapshot from `git archive` and prepends a preamble to
your prompt. The preamble names the snapshot, the base, the revision and the
diff at `.review/change.diff`, so your prompt need not. Instruction files the
change adds or modifies are renamed with the suffix `.under-review`. An
instruction file is one named `AGENTS.md` or `GEMINI.md`, or any file under a
directory named `.agents`, `.agent`, `_agents` or `_agent`. Every `hooks.json`
and `mcp_config.json` directly under one of those directories is renamed too,
changed or not, so the lens launches no process. All of these names match in
any letter case or Unicode form, because agy on macOS loads `agents.md` as it
loads `AGENTS.md`. For the same reason, the launcher refuses a revision that
holds two paths differing only in those ways. A link at an instruction file's
path is renamed too when what it reaches is under review, so a changed
`CLAUDE.md` behind an `AGENTS.md` link stays out. A revision holding a link that
leads outside the snapshot is refused. Unchanged instruction files
load as the project's accepted rules. The lens can read, search and list files
in the snapshot and do nothing else, so never ask it to run a command, a test
or git.

Lens mode needs macOS, because the temporary home signs in through a link to
`~/Library/Keychains`. The snapshot and the home are removed on every exit.
`--keep-snapshot` keeps the snapshot and prints its path, and then removing it
is your job.

## Exit codes

stdout carries agy's final response, and only on exit 0. On every other exit
stdout is empty.

| Exit | Meaning | Your move |
|---|---|---|
| `0` | A usable response. | Use stdout. A lens run with no `tool=` line on stderr read nothing, so treat it as exit `70`. |
| `70` | agy finished, but the output is unusable. `reason=empty` means no response. `reason=denied` means agy denied a tool call, and the `denied=` field names it. | Re-brief, for example to keep the run inside its workspace, or move to another route. A worker's denied command can instead go on `permissions.allow`, with the user's agreement. |
| `75` | The route did not serve the run. The reason is `error`, `timeout`, `no-result`, `signal`, `no-route` (agy, git or the Keychains folder is missing) or `home-unproven` (the lens's temporary home failed its isolation check). | Fail over to the next route or model, quoting the reason. After a signal you sent yourself, stop. |
| `78` | The launcher refused the invocation. The `agy_run.py:` line on stderr names the refused element and the remedy. | Fix the invocation, or its setup when the worker's directory is untrusted. Do not fail over. |

Any other exit is a launcher defect, reported with a Python traceback. Treat it
as `78`, and report it rather than failing over.

## Reading stderr

The launcher writes a ledger of `[agy-run]` lines to stderr in this order.

- `pid=<pid>` names agy's process group. If the launcher itself dies, end the
  group with `kill -TERM -<pid>`.
- `agent=<name> permission_mode=<mode>` comes from agy's start event. A lens
  shows `agent=agy-lens`.
- `tool=<tool> <first parameter>` records each tool call. A lens that exits 0
  with no `tool=` line read nothing, not even the diff, so do not accept it as
  a review.
- `status=<status> turns=<n> tokens=<total> denied=<names>` appears only when
  agy delivered its result.
- `reason=<word>` appears on exit 70 or 75.
- `snapshot=<path>` appears when `--keep-snapshot` kept one.
- `leak=<path>` names a directory cleanup could not remove. Remove it yourself.
  The exit code still reflects the run.

agy's own stderr passes through unchanged, including any `AGY_ERROR:` line.

## When the subscription runs out

No quota-exhaustion run has been observed yet. Whatever agy reports then
arrives as exit `75`, or as exit `70` with `reason=empty`, and agy's own stderr
says why. Fail over to the `openrouter-claude-subagent` skill and pick a
Gemini model from that skill's own routing table. The agy ids are not valid there, so do not
translate one by hand. Repeating the agy run against the same spent quota fails
the same way.
