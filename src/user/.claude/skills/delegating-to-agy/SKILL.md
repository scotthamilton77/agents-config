---
name: delegating-to-agy
description: "Use when a run is being launched on Antigravity CLI (agy), Google's runtime for Gemini models: as a full worker in the current checkout, or as a fresh-context review lens over a snapshot whose instruction files stay out. Apply when the user names agy, Antigravity or a Gemini model, or when another skill sends a Gemini dispatch here. Not for deciding whether to leave Claude, not for agy setup or sign-in, and not for OpenRouter, which runs a Gemini model only on the user's explicit instruction."
admission:
  provides: "An agy run in one of two verified shapes: a worker in the current checkout that reads the user's and the repository's instruction files like a Claude or Codex worker does, or a fresh-context lens over a snapshot of a revision, run under a temporary home that holds only a Keychain link so no user-level rule or skill loads, with the change's own instruction files renamed so nothing under review instructs the reviewer, every hook and MCP configuration under a customization root renamed so nothing launches, and the change's diff beside them. Invoking it produces the launcher command, its exit code contract, and the model id for the task profile."
  cost: agy must be installed and signed in, and every run bills the Google AI Pro subscription; lens mode needs macOS for the Keychain link and leaves a snapshot of the reviewed revision and a temporary home on disk for the run's duration; the shared model routing table's Google rows need a refresh whenever agy's model list changes.
  remove_when: The Google AI Pro subscription lapses, agy loses headless print mode, or the review tooling addresses agy natively so no launcher stands between a caller and a Gemini seat.
---

# Delegating to agy

agy is Antigravity CLI, Google's command-line runtime for Gemini models. Its runs
bill the user's Google AI Pro subscription.

Launch agy only through `agy_run.py`, which ships in this skill's `scripts/`
directory. A bare `agy -p` run reports a denied tool call or a timeout as
success.

## Pick the mode

| Mode | What runs | Pick it for |
|---|---|---|
| `worker` | agy in the current directory with the real home. The user's agy rules and skills load, and so do the checkout's own instruction files. It can edit files. | Implementing or investigating in this checkout, as a Claude or Codex worker would. |
| `lens` | agy read-only over a snapshot of one committed revision, under a temporary home. No user-level rule or skill loads. | An independent review, where neither the user's own rules nor the change under review may instruct the reviewer. |

## Launch

```bash
uv run "${CLAUDE_SKILL_DIR}/scripts/agy_run.py" worker \
  --model <model> --effort <level> --timeout <seconds> -p "<prompt>"

uv run "${CLAUDE_SKILL_DIR}/scripts/agy_run.py" lens \
  --repo <path> --base <base-rev> [--rev <rev>] --model <model> --effort <level> \
  [--timeout <seconds>] [--keep-snapshot] -p "<prompt>"
```

`-p` comes last, and the prompt is the one argument after it. Pass a long brief
as `-p "$(cat brief.md)"`. Take the model from the `google` column of the
`choosing-a-delegate` skill's model routing table and the effort from that
model's accepted list, and pass them as `--model` and `--effort`, for example
`--model gemini-3.8-flash --effort low`. The launcher hands both to agy
unchanged. agy refuses a pairing it does not offer before the run starts, and
its message names the levels the model has; that refusal arrives as exit 78,
to fix and not to fail over.

Set the Bash tool's timeout above the run's seconds plus 40. A lens that omits
`--timeout` runs for 600 seconds. Alternatively, run the command in the
background, and write stdout and stderr to separate files.

A worker's edits stay in the checkout whatever the exit code, so check
`git status` after every worker run. What a worker may edit and run is set in
`~/.gemini/antigravity-cli/settings.json`. Editing that file widens what agy may
do on the user's machine, so ask the user first.

A lens reviews a committed revision, never a working tree, so commit
uncommitted work before launching one. It can only read, so never ask it to run
a command, a test or git. The instruction files the change adds or modifies are
hidden from the lens, and the unchanged ones load as the project's accepted
rules. Passing the same revision as `--base` and `--rev` reviews the whole
revision rather than a change. Lens mode needs macOS.

## Exit codes

| Exit | Meaning | Your move |
|---|---|---|
| `0` | A usable response, on stdout. | Use it. |
| `70` | agy finished, but the output is unusable. `reason=empty` means no response. `reason=denied` means agy denied a tool call, and the `denied=` field names it. `reason=unread` means a lens answered without calling a single tool, so it never looked at the snapshot. | Re-brief, for example to keep the run inside its workspace or to read the diff first, or move to another route. A worker's denied command can instead go on `permissions.allow`, with the user's agreement. |
| `75` | The route did not serve the run. The `reason=` line on stderr says why. | Fail over to the next route or model, quoting the reason. After a signal you sent yourself, stop. |
| `78` | The launcher refused the invocation, or agy refused the model and effort it was given. The `agy_run.py:` line on stderr names what was refused and why, and agy's own line above it names the levels the model has. | Fix the invocation, or its setup when the worker's directory is untrusted. Do not fail over. |

Any other exit is a launcher defect, reported with a Python traceback. Treat it
as `78`, and report it rather than failing over.

Two stderr lines ask for action. `[agy-run] pid=<pid>` names agy's process
group, so if the launcher itself dies, end the group with `kill -TERM -<pid>`.
`[agy-run] leak=<path>` names a directory the launcher could not remove, so
remove it yourself.

## When the subscription runs out

No quota-exhaustion run has been observed yet. Whatever agy reports then
arrives as exit `75` or `70`, and agy's own stderr says why. Stop and tell the
user: a Gemini model runs on the `openrouter-claude-subagent` launcher only on
their explicit instruction. If they give it, dispatch there with the same
model's `openrouter` row in the routing table, passing the effort as that
launcher's flag; the agy ids are not valid there, so take the row's id rather
than translating one by hand. Repeating the agy run against the same spent
quota fails the same way.
