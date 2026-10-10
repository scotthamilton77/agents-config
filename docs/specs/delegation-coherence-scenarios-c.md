# Delegation coherence: scenarios for slice C

These are the scenarios for criteria DEL-C1, DEL-C2, DEL-C3, DEL-C6 and DEL-C8
of `docs/specs/2026-10-01-delegation-coherence.md`, and the signal list
DEL-C3 is checked against. They follow that spec's scenario protocol. Each
scenario gives a fresh native subagent on the `mid` tier the named files and
one captured input, and asks one question with a closed answer set. Each
scenario runs three times. A criterion passes when every run of every one of
its scenarios returns the keyed answer. The scenarios, inputs, keys and the
signal list below were committed before the skill prose they test.

Skill directories, relative to the repository root:

- `codex`: `src/plugins/codex/.claude/skills/delegating-to-codex`
- `openrouter`: `src/user/.claude/skills/openrouter-claude-subagent`
- `agy`: `src/user/.claude/skills/delegating-to-agy`
- `harvest`: the single file `src/user/.claude/skills/review-panel/harvest.md`
- `ac-attack`: the single file `src/user/.claude/skills/ac-attack/SKILL.md`

## The reader's prompts

`<SKILL>` is the skill's name, `<SKILL_DIR>` the absolute path of its
directory in the tree under test, `<FILE>` the absolute path of a single
caller file, and `<INPUT>` the scenario's captured input, verbatim.

### Prompt L: classify a launcher's ending

Used by C1a to C1c and by every launcher scenario of DEL-C3.

```text
You are a coding agent working in a user's session. The only skill you hold is
`<SKILL>`, and its files are under <SKILL_DIR>. Read <SKILL_DIR>/SKILL.md, and
any other file under <SKILL_DIR> it points you to. Read nothing outside
<SKILL_DIR>. Run no command of any kind.

You launched a run through this skill. This is what you observe now:

<INPUT>

Question: which one of these does what you observe mean?
- USABLE: the run produced usable output
- REFUSED: the launcher refused the invocation
- NOT-SERVED: the provider did not serve the run
- UNUSABLE: the run produced unusable output
- RUNNING: the run has not ended yet

Reply with exactly one line: `ANSWER: ` followed by one of the five words.
```

### Prompt Q: answer from a launcher skill

Used by C1d and C2a to C2e. `<QUESTION>` is the scenario's question,
which states its own reply format.

```text
You are a coding agent working in a user's session. The only skill you hold is
`<SKILL>`, and its files are under <SKILL_DIR>. Read <SKILL_DIR>/SKILL.md, and
any other file under <SKILL_DIR> it points you to. Read nothing outside
<SKILL_DIR>. Run no command of any kind.

<INPUT>

<QUESTION>
```

### Prompt K: a caller's response to an outcome

Used by the caller scenarios of DEL-C3.

```text
You are a coding agent running a review. The only instructions you hold for
it are in <FILE>. Read that file and nothing else. Run no command of any kind.

<INPUT>

Question: what do you do next? Pick one:
- INGEST: ingest the output and claim nothing further for this attempt
- FIX-INVOCATION: fix the invocation
- transport-error: claim again with reason `transport-error`
- unusable-output: claim again with reason `unusable-output`
- STOP: stop, with no further claim for this dispatch

Reply with exactly one line: `ANSWER: ` followed by one of the five.
```

### Prompts for the live scenarios

C6 and C8 use their own prompts, given under each scenario. Their readers
may run commands, because the key is what those commands do.

## DEL-C1: classifying a read-only Codex run

Skill: `codex`.

### C1a: finished

Prompt L.

```text
You started a read-only run with the command the skill gives. The Bash call
returned exit status 0 after 14 minutes. The report file holds the JSON
object of findings your prompt asked for. The last line of the stderr capture
file is `[codex] Turn completed.`
```

Key: `ANSWER: USABLE`.

### C1b: still running at minute 26 after the call was backgrounded

Prompt L.

```text
You started a read-only run with the command the skill gives at 10:02, with
the Bash timeout the skill names. At 10:27 the Bash tool reported that the
command was moved to the background and returned control to you. It is now
10:28. The pid file holds 48213, and `kill -0 48213` succeeds. The report file
is empty. The stderr capture file was last written 40 seconds ago, and its
last line is `[codex] Running command: rg -n "timeout" src/`.
```

Key: `ANSWER: RUNNING`.

### C1c: usage limit reached

Prompt L. This scenario is also the DEL-C3 scenario for the Codex usage
limit, so its three runs count for both criteria.

```text
You started a read-only run with the command the skill gives. The Bash call
returned exit status 1 after 3 seconds. The report file holds one line:
`You've hit your usage limit. Upgrade to Pro (https://openai.com/chatgpt/pricing) or try again at 4:12 PM.`
The stderr capture file holds:

[codex] Starting Codex task thread.
[codex] Thread ready (thr_7f2a).
[codex] Turn started (turn_01).
[codex] Codex error: You've hit your usage limit. Upgrade to Pro (https://openai.com/chatgpt/pricing) or try again at 4:12 PM.
[codex] Turn failed.
```

Key: `ANSWER: NOT-SERVED`.

### C1d: stopping a running one

Prompt Q.

```text
Your read-only Codex run is still going. Its pid file holds 48213. `ps`
shows two codex-companion processes on this machine: pid 48213, which is
yours, and pid 51007, which belongs to another agent's review. The user says:
stop the Codex run now.
```

Question:

```text
What single shell command do you run to stop it? Reply with exactly one line:
`COMMAND: ` followed by the command.
```

Key: the command signals pid 48213, signals no other pid, and selects no
process by name (no `pkill`, `killall`, `pgrep` or `ps | grep`).

## DEL-C2: bounding and stopping an OpenRouter run

Skill: `openrouter`. Prompt Q, with an empty `<INPUT>`.

### C2a: the two flags

```text
Which two flags of the launcher bound how long a run may last? Reply with
exactly one line: `FLAGS: ` followed by the two flags.
```

Key: `--timeout` and `--idle-timeout`, in either order.

### C2b: what an expiry does

```text
A run is launched with both of the launcher's flags that bound how long a
run may last. When each of those bounds expires, what does the launcher do to
the run, and what does it report? Reply with exactly three lines:
`TIMEOUT: exit=<code> line=<the stderr line it prints>`
`IDLE: exit=<code> line=<the stderr line it prints>`
`ACTION: <what the launcher does to the running run>`
```

Key: both lines carry exit `75`; the lines are `[run] reason=timeout` and
`[run] reason=idle`; the action ends the child process or its process group.

### C2c: ending a run early

```text
You want to end a running launch early. Reply with exactly two lines:
`SIGNAL: <signal name> TO: <which process>`
`REPORTS: exit=<code> line=<the stderr line the launcher prints>`
```

Key: `SIGTERM` or `SIGINT`, sent to the launcher (`run.js`) process; exit
`75` and `[run] reason=signal`.

### C2d: the effort for a whole-artifact read on Kimi K3

```text
You are about to run a single-pass read of a whole artifact on
`moonshotai/kimi-k3`. Which effort level do you pass? Reply with exactly one
line: `EFFORT: ` followed by the level.
```

Key: `EFFORT: low`.

### C2e: the measured durations

```text
How long have healthy runs on `moonshotai/kimi-k3` through this launcher been
measured to take? Reply with exactly two lines:
`INLINE: <duration>` for a read of text given inline with no tools
`REPO: <duration>` for a read of a repository
```

Key: `INLINE` states 4 to 9 minutes; `REPO` states 27 minutes.

## DEL-C3: launcher signals and caller responses

### The signal list

Every signal the three launcher skills document once slice C's text is in
them, with the outcome each means. Each row was cross-checked against the
launcher's code: the OpenRouter launcher's `scripts/run.js` and
`scripts/proxy.js`, the agy launcher's `scripts/agy_run.py`, and the Codex
plugin's `scripts/codex-companion.mjs` with `scripts/lib/codex.mjs` and
`scripts/lib/tracked-jobs.mjs` at plugin version 1.0.3.

| Id | Launcher | Signal | Outcome | Emitted by |
| --- | --- | --- | --- | --- |
| X0 | Codex | exit 0, the report on stdout, `[codex] Turn completed.` on stderr | usable output | `runForegroundCommand`; the progress line in `lib/codex.mjs` |
| X1 | Codex | exit 1, `[codex] Codex error: You've hit your usage limit…` on stderr, the same message on stdout | the provider did not serve the run | the `error` notification's progress line; exit from `buildResultStatus` |
| X2 | Codex | exit 1, another `[codex] Codex error:` line, or a turn ending other than `[codex] Turn completed.`; the error on stdout | the provider did not serve the run | the same, the `turn/completed` progress line, and `renderTaskResult` printing the failure message |
| X3 | Codex | exit 1, no `[codex]` line, and the companion's complaint about its own arguments: `Missing value for …`, `Unsupported reasoning effort …`, `Provide a prompt…`, `A prompt is required…`, `Choose either …`, `Unknown subcommand …`, or an `ENOENT` for the prompt file | the launcher refused the invocation | `parseArgs`, `normalizeReasoningEffort`, `requireTaskRequest`, `handleTask`, `main`, through the `main().catch` handler |
| X4 | Codex | exit 1, no `[codex]` line, and any other message, such as `Codex CLI is not installed or is missing required runtime support…` | the provider did not serve the run | `ensureCodexAvailable`, through `main().catch` |
| X6 | Codex | exit 1, no `[codex]` line, `codex app-server exited unexpectedly (exit 1).` | the provider did not serve the run | `lib/app-server.mjs`, through `main().catch` |
| X5 | Codex | exit 0, stdout `Codex did not return a final message.`, or a reply that is not the report asked for | the run produced unusable output | `renderTaskResult` |
| O0 | OpenRouter | the child's exit 0, its result on stdout holding an answer | usable output | `main` returns the child's code |
| O1 | OpenRouter | exit 78, a `[run]` line naming what was refused: a missing flag, a bad clock value, a refused model, an unset key | the launcher refused the invocation | `EXIT_CONFIG_ERROR` paths in `main` |
| O2 | OpenRouter | exit 75, `[run] reason=timeout` | the provider did not serve the run | `supervise`, `EXIT_ROUTE` |
| O3 | OpenRouter | exit 75, `[run] reason=idle` | the provider did not serve the run | `supervise`, `EXIT_ROUTE` |
| O4 | OpenRouter | exit 75, `[run] reason=signal` | the provider did not serve the run; after a signal the caller sent, the caller stops | `supervise`, `EXIT_ROUTE` |
| O5 | OpenRouter | any other non-zero exit, such as the child's `1` with a `[proxy]` error line: `upstream <status> …`, `upstream request error`, `upstream response error`, `upstream request timeout`, `upstream stream ended without message_stop` | the provider did not serve the run | the child's code; the proxy's upstream lines |
| O6 | OpenRouter | `[proxy] WARNING: response ends on thinking and contains no text block to promote`, no answer, whatever the exit | the run produced unusable output | the proxy's stream repair |
| O8 | OpenRouter | the child's `1` with `[proxy] upstream request timeout` | the provider did not serve the run | the proxy's upstream timeout |
| O9 | OpenRouter | `[proxy] WARNING: response ends on redacted_thinking and contains no text block to promote`, no answer | the run produced unusable output | the proxy's stream repair |
| O7 | OpenRouter | every `[proxy] model-ledger` line carries `decision=deny-pin` or `decision=deny-denylist`, and the child exits non-zero | the launcher refused the invocation | `screenModel` and its ledger line |
| A0 | agy | exit 0 | usable output | `EXIT_OK` |
| A1 | agy | exit 70, `[agy-run] reason=empty` | the run produced unusable output | `EXIT_UNUSABLE` |
| A2 | agy | exit 70, `[agy-run] reason=denied` | the run produced unusable output | `EXIT_UNUSABLE` |
| A3 | agy | exit 70, `[agy-run] reason=unread` | the run produced unusable output | `EXIT_UNUSABLE` |
| A4 | agy | exit 75 with its `[agy-run] reason=` line | the provider did not serve the run | `EXIT_ROUTE` |
| A5 | agy | exit 75, `[agy-run] reason=signal` | the provider did not serve the run; after a signal the caller sent, the caller stops | `EXIT_ROUTE` |
| A6 | agy | exit 78, an `agy_run.py:` line naming what was refused | the launcher refused the invocation | `EXIT_CONFIG` |
| A7 | agy | any other exit, with a Python traceback | treated as exit 78: the launcher refused the invocation | an uncaught exception |

Cross-check findings, script by script:

- `agy_run.py` emits six reasons with exit 75: `error`, `no-route`,
  `timeout`, `signal`, `home-unproven` and `no-result`. The agy skill names
  `signal` and covers the other five with its generic exit-75 row, which
  says the `reason=` line names the cause. Row A4 is that generic row. Every
  exit code the script returns (0, 70, 75, 78) is documented, and the skill
  documents no signal the script does not emit.
- `run.js` returns 78, 75 with `timeout`, `idle` or `signal`, or the
  child's own exit code. Each is a row above. Its `[run]` lines are the 78
  messages (row O1), the reason lines (rows O2 to O4), and
  `proxy listening on`, which marks a start and no ending. The skill's table
  is read in order, and its first matching row decides, so a thinking-only
  reply with exit 0 is O6 and never O0.
- `proxy.js` writes these `[proxy]` lines, each cross-checked:
  - `upstream <status> …`, `upstream request error`, `upstream response
    error`, `upstream request timeout` and `upstream stream ended without
    message_stop` are named in the skill's "any other non-zero exit" row (O5,
    O8).
  - `response ends on <type> and contains no text block to promote` is
    named for both block types the proxy treats as reasoning, `thinking` and
    `redacted_thinking` (O6, O9).
  - A `model-ledger` line with `decision=deny-pin` or `deny-denylist` is an
    ending only when every ledger line of the run carries one (O7). A single
    denied nested request among forwarded ones is not an ending, and the
    skill says so.
  - `refused: unparseable request target`, `refused: request target names
    <host>`, `refused: request body exceeds <n> bytes`, `request adjudication
    error`, `client request error` and `request handler error` answer one
    request from the child with an HTTP error. The skill does not name them.
    Its generic "any other non-zero exit" row maps the child's resulting exit
    to the provider not serving the run, because each one means the proxy
    could not carry the request to OpenRouter.
  - `reordered: …` and the `WARNING` lines about a duplicate
    `content_block_start` or a delta for an unstarted index record a repair
    the proxy made to a stream it still delivers. They are not endings, and
    the skill does not name them.
- `codex-companion.mjs` returns 0, or 1 for a failed turn and for any error
  its `main` catches. It has no reason line of its own; its stderr carries
  `[codex]` progress lines. An unknown flag is not refused: the companion
  folds it into the prompt text, so "unknown flag refused" is a signal the
  script does not emit, and no skill documents it. A failed turn prints its
  error message on stdout, so the report file holds it (`renderTaskResult`).
  An error `main` catches prints one stderr line with no `[codex]` prefix. The
  skill maps the companion's checks of its own arguments to a refusal (X3)
  and every other such line to the provider not serving the run (X4, X6),
  which includes a dead `codex app-server`.

### Launcher scenarios

Prompt L, one scenario per failure signal above. X1 is C1c. The key is the
outcome's answer word: usable output is `USABLE`, the launcher refused the
invocation is `REFUSED`, the provider did not serve the run is `NOT-SERVED`,
and the run produced unusable output is `UNUSABLE`.

#### X2 (skill `codex`)

```text
You started a read-only run with the command the skill gives. The Bash call
returned exit status 1 after 9 seconds. The report file holds one line:
`unexpected status 401 Unauthorized: Missing bearer or basic authentication in header`
The stderr capture file ends:

[codex] Codex error: unexpected status 401 Unauthorized: Missing bearer or basic authentication in header
[codex] Turn failed.
```

Key: `ANSWER: NOT-SERVED`.

#### X3 (skill `codex`)

```text
You started a read-only run with the command the skill gives. The Bash call
returned exit status 1 in under a second. The report file is empty. The
stderr capture file holds one line:

Provide a prompt, a prompt file, piped stdin, or use --resume-last.
```

Key: `ANSWER: REFUSED`.

#### X4 (skill `codex`)

```text
You started a read-only run with the command the skill gives. The Bash call
returned exit status 1 in under a second. The report file is empty. The
stderr capture file holds one line:

Codex CLI is not installed or is missing required runtime support. Install it with `npm install -g @openai/codex`, then rerun `/codex:setup`.
```

Key: `ANSWER: NOT-SERVED`.

#### X5 (skill `codex`)

```text
You started a read-only run with the command the skill gives. The Bash call
returned exit status 0 after 6 minutes. The report file holds one line:
`Codex did not return a final message.` The last line of the stderr capture
file is `[codex] Turn completed.`
```

Key: `ANSWER: UNUSABLE`.

#### X6 (skill `codex`)

```text
You started a read-only run with the command the skill gives. The Bash call
returned exit status 1 after 2 seconds. The report file is empty. The stderr
capture file holds one line:

codex app-server exited unexpectedly (exit 1).
```

Key: `ANSWER: NOT-SERVED`.

#### O1 (skill `openrouter`)

```text
The launcher exited 78 at once. Its stderr holds one line:
[run] --timeout was given "0", which is not a positive number of seconds.
```

Key: `ANSWER: REFUSED`.

#### O2 (skill `openrouter`)

```text
The launcher exited 75. The last line of its stderr is `[run] reason=timeout`.
```

Key: `ANSWER: NOT-SERVED`.

#### O3 (skill `openrouter`)

```text
The launcher exited 75. The last line of its stderr is `[run] reason=idle`.
```

Key: `ANSWER: NOT-SERVED`.

#### O4 (skill `openrouter`)

```text
You sent SIGTERM to the launcher. It exited 75, and the last line of its
stderr is `[run] reason=signal`.
```

Key: `ANSWER: NOT-SERVED`.

#### O5 (skill `openrouter`)

```text
The launcher exited 1. Its stderr holds:
[proxy] upstream 402 POST /api/v1/messages — {"error":{"message":"Insufficient credits. Add more using https://openrouter.ai/settings/credits","code":402}}
Its stdout holds the harness's error result naming the same 402.
```

Key: `ANSWER: NOT-SERVED`.

#### O6 (skill `openrouter`)

```text
The launcher exited 0. The result on stdout carries no text. Its stderr holds:
[proxy] WARNING: response ends on thinking and contains no text block to promote
```

Key: `ANSWER: UNUSABLE`.

#### O7 (skill `openrouter`)

```text
The launcher exited 1. Every `model-ledger` line on its stderr reads:
[proxy] model-ledger POST /api/v1/messages model=z-ai/glm-5.3[1m] decision=deny-pin
Its stdout holds the harness's error result naming a 403.
```

Key: `ANSWER: REFUSED`.

#### O8 (skill `openrouter`)

```text
The launcher exited 1. Its stderr ends:
[proxy] upstream request timeout
Its stdout holds the harness's error result naming the timeout.
```

Key: `ANSWER: NOT-SERVED`.

#### O9 (skill `openrouter`)

```text
The launcher exited 0. The result on stdout carries no text. Its stderr holds:
[proxy] WARNING: response ends on redacted_thinking and contains no text block to promote
```

Key: `ANSWER: UNUSABLE`.

#### A1 (skill `agy`)

```text
The launcher exited 70. Its stderr ends with `[agy-run] reason=empty`.
```

Key: `ANSWER: UNUSABLE`.

#### A2 (skill `agy`)

```text
The launcher exited 70. Its stderr ends with
`[agy-run] status=SUCCESS turns=4 tokens=18211 denied=run_command` and
`[agy-run] reason=denied`.
```

Key: `ANSWER: UNUSABLE`.

#### A3 (skill `agy`)

```text
The launcher, run in lens mode, exited 70. Its stderr ends with
`[agy-run] reason=unread`.
```

Key: `ANSWER: UNUSABLE`.

#### A4 (skill `agy`)

```text
The launcher exited 75. Its stderr ends with `[agy-run] reason=no-result`.
```

Key: `ANSWER: NOT-SERVED`.

#### A5 (skill `agy`)

```text
You sent SIGTERM to the launcher. It exited 75, and its stderr ends with
`[agy-run] reason=signal`.
```

Key: `ANSWER: NOT-SERVED`.

#### A6 (skill `agy`)

```text
The launcher exited 78 at once. Its stderr holds one line:
agy_run.py: --model is required.
```

Key: `ANSWER: REFUSED`.

#### A7 (skill `agy`)

```text
The launcher exited 1. Its stderr ends with a Python traceback:
Traceback (most recent call last):
  File "agy_run.py", line 612, in _lens
KeyError: 'response'
```

Key: `ANSWER: REFUSED`.

### Caller scenarios

Prompt K. `<FILE>` is the harvest file for H1 to H6 and the `ac-attack`
skill file for K1 to K5. The `<INPUT>` names the lens: `correctness` for
harvest, `what-if` for `ac-attack`.

| Scenario | Captured input | Key |
| --- | --- | --- |
| H1, K1 | You dispatched the `<lens>` lens. Its launcher's own skill says what its ending means: usable output. | `INGEST` |
| H2, K2 | You dispatched the `<lens>` lens. Its launcher's own skill says what its ending means: the launcher refused the invocation. | `FIX-INVOCATION` |
| H3, K3 | You dispatched the `<lens>` lens. Its launcher's own skill says what its ending means: the provider did not serve the run. | `transport-error` |
| H4 | You dispatched the `<lens>` lens. Its launcher's own skill says what its ending means: the run produced unusable output. The reply was prose in place of the report the prompt asked for, and the response did not end inside the model's reasoning. | `unusable-output` |
| K4 | You dispatched the `<lens>` lens. Its launcher's own skill says what its ending means: the run produced unusable output. | `unusable-output` |
| H5, K5 | You dispatched the `<lens>` lens. The user then told you to abandon this dispatch, so you sent the run a signal to end it. Its launcher's own skill says what its ending means: the provider did not serve the run. | `STOP` |
| H6 | You dispatched the `<lens>` lens through a launcher with an idle limit. The run forwarded nothing for that long, so the launcher ended it. Its launcher's own skill says what its ending means: the provider did not serve the run. | `transport-error` |

## DEL-C6: the read-only run command against a stub

Skill: `codex`. A stub companion at `<STUB>` records its argv to
`<DIR>/invocation.json`, refuses a run carrying `--write` (exit 1, nothing on
stdout), and otherwise prints the fixed report below on stdout,
`[codex] Turn completed.` on stderr, and exits 0. It writes no file but the
invocation record. The stub lives under a temporary directory and is not
committed.

Fixed report: `{"findings": [], "verdict": "clean", "stub": "c6-fixed-report"}`

Reader's prompt (Prompt Q):

```text
The user says: "Get an independent read-only Codex review of the change in
<DIR>/change.diff, looking for unhandled errors, and put the report in
<DIR>/report.json." Use the model `gpt-6.1-sol` at effort `medium`. On this
machine the Codex plugin's companion script is at <STUB>.
```

```text
Write the shell command you would run to launch this run. Reply with the
command alone, in one fenced bash block.
```

The returned command is run once per reader run, from `<DIR>`. Key: after it
exits, `<DIR>/report.json` holds the fixed report, and the recorded argv's
first element is `task` and contains no `--write`, which is the read-only run
form `skills/codex-cli-runtime/SKILL.md` documents in the Codex plugin.

## DEL-C8: collecting a backgrounded run

Skill: `codex`. A stub companion, written per run under a temporary directory
and not committed, prints nothing for 60 seconds, then writes
`[codex] Turn completed.` on stderr and a report holding a token generated
for that run on stdout, then waits 45 more seconds, records its exit time in
epoch seconds to `<DIR>/exited_at`, and exits 0.

The harness starts the stub with the read-only run command the skill teaches,
with stdout to `<DIR>/report.json`, stderr to `<DIR>/run.log` and its pid in
`<DIR>/run.pid`, in the background, and gives the reader this prompt at once:

```text
You are a coding agent working in a user's session. The only skill you hold is
`delegating-to-codex`, and its files are under <SKILL_DIR>. Read
<SKILL_DIR>/SKILL.md and nothing outside <SKILL_DIR>.

You launched a read-only Codex run with this command, from <DIR>:

<COMMAND>

Your Bash call was moved to the background before the run finished, and has
returned. Return the run's report. You may run shell commands.

When you have it, reply with exactly three lines:
`REPORT: ` followed by the report's text
`PROCESS: exited` or `PROCESS: running`, for the launched process at the moment you reply
`ANSWERED_AT: ` followed by the output of `date +%s` run just before you reply
```

Key: `REPORT` holds the run's token, `PROCESS: exited`, and `ANSWERED_AT` is
not earlier than the recorded exit time.

## Runs

Every run was a fresh native subagent pinned to `sonnet`, given the prompt
above and nothing else, on 2026-10-10. A reader's prompt was handed to it as
a file it was told to read first. The C6 and C8 stubs ran under `/tmp` and
were not committed.

The baseline ran once per scenario where the old prose could inform it,
against the skill prose as it stood before the prose change. The agy
scenarios have no baseline, because slice C leaves that skill unchanged. C8
has no baseline, because the live wait is the costly part of the run and the
old prose taught no collection at all. The baseline failed C2b, C2c, C2e, O4
and K4. Several other baselines passed because the reader inferred the
answer from the closed answer set or from the launcher scripts in the skill
directory.

C1d's three answers name the pid through the pid file that the skill's
command writes, which the input says holds 48213. That command signals 48213
and no other process, and it selects nothing by name, so it meets the key.
C6's three commands each wrote the pid file and the prompt file as the skill
teaches. Each one left the fixed report in the named file, and each recorded
invocation was `task --model gpt-6.1-sol --effort medium --prompt-file …`
with no `--write`. In C8 every stub exited at epoch 1791658823, and every
answer was given after that.

| Scenario | Run | Prose | Answer | Key | Result |
| --- | --- | --- | --- | --- | --- |
| C1a | baseline | before | `ANSWER: USABLE` | USABLE | pass |
| C1a | 1 | after | `ANSWER: USABLE` | USABLE | pass |
| C1a | 2 | after | `ANSWER: USABLE` | USABLE | pass |
| C1a | 3 | after | `ANSWER: USABLE` | USABLE | pass |
| C1b | baseline | before | `ANSWER: RUNNING` | RUNNING | pass |
| C1b | 1 | after | `ANSWER: RUNNING` | RUNNING | pass |
| C1b | 2 | after | `ANSWER: RUNNING` | RUNNING | pass |
| C1b | 3 | after | `ANSWER: RUNNING` | RUNNING | pass |
| C1c | baseline | before | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| C1c | 1 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| C1c | 2 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| C1c | 3 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| C1d | baseline | before | `COMMAND: kill 48213` | signals pid 48213 only, no name match | pass |
| C1d | 1 | after | `COMMAND: kill -TERM "$(cat <pidfile>)"` | signals pid 48213 only, no name match | pass |
| C1d | 2 | after | `COMMAND: kill -TERM "$(cat <pidfile>)"` | signals pid 48213 only, no name match | pass |
| C1d | 3 | after | `COMMAND: kill -TERM "$(cat <pidfile>)"` | signals pid 48213 only, no name match | pass |
| C2a | baseline | before | `FLAGS: --timeout and --idle-timeout` | `--timeout`, `--idle-timeout` | pass |
| C2a | 1 | after | `FLAGS: --timeout and --idle-timeout` | `--timeout`, `--idle-timeout` | pass |
| C2a | 2 | after | `FLAGS: --timeout and --idle-timeout` | `--timeout`, `--idle-timeout` | pass |
| C2a | 3 | after | `FLAGS: --timeout and --idle-timeout` | `--timeout`, `--idle-timeout` | pass |
| C2b | baseline | before | `unknown (no bound documented)` | exit 75; `[run] reason=timeout`, `[run] reason=idle`; ends the child process group | fail |
| C2b | 1 | after | `TIMEOUT: exit=75 line=[run] reason=timeout / IDLE: exit=75 line=[run] reason=idle / ACTION: SIGTERM to the child's whole process group, SIGKILL five seconds later, then closes the proxy` | exit 75; `[run] reason=timeout`, `[run] reason=idle`; ends the child process group | pass |
| C2b | 2 | after | `TIMEOUT: exit=75 line=[run] reason=timeout / IDLE: exit=75 line=[run] reason=idle / ACTION: ends the child's whole process group, SIGTERM then SIGKILL five seconds later, then closes the proxy` | exit 75; `[run] reason=timeout`, `[run] reason=idle`; ends the child process group | pass |
| C2b | 3 | after | `TIMEOUT: exit=75 line=[run] reason=timeout / IDLE: exit=75 line=[run] reason=idle / ACTION: SIGTERM to the child's whole process group, SIGKILL five seconds later, closes the proxy` | exit 75; `[run] reason=timeout`, `[run] reason=idle`; ends the child process group | pass |
| C2c | baseline | before | `not documented` | SIGTERM or SIGINT to the launcher; exit 75, `[run] reason=signal` | fail |
| C2c | 1 | after | `SIGNAL: SIGTERM TO: the launcher's own process, the node run.js process (SIGINT also works) / REPORTS: exit=75 line=[run] reason=signal` | SIGTERM or SIGINT to the launcher; exit 75, `[run] reason=signal` | pass |
| C2c | 2 | after | `SIGNAL: SIGTERM TO: the launcher's own process, the node run.js process (SIGINT also works) / REPORTS: exit=75 line=[run] reason=signal` | SIGTERM or SIGINT to the launcher; exit 75, `[run] reason=signal` | pass |
| C2c | 3 | after | `SIGNAL: SIGTERM TO: the launcher's own node run.js process (not the child or the proxy; SIGINT also works) / REPORTS: exit=75 line=[run] reason=signal` | SIGTERM or SIGINT to the launcher; exit 75, `[run] reason=signal` | pass |
| C2d | 1 | after | `EFFORT: low` | `low` | pass |
| C2d | 2 | after | `EFFORT: low` | `low` | pass |
| C2d | 3 | after | `EFFORT: low` | `low` | pass |
| C2e | baseline | before | `not recorded in the skill files` | 4 to 9 minutes; 27 minutes | fail |
| C2e | 1 | after | `INLINE: 4 to 9 minutes / REPO: 27 minutes` | 4 to 9 minutes; 27 minutes | pass |
| C2e | 2 | after | `INLINE: 4 to 9 minutes / REPO: 27 minutes` | 4 to 9 minutes; 27 minutes | pass |
| C2e | 3 | after | `INLINE: 4 to 9 minutes / REPO: 27 minutes` | 4 to 9 minutes; 27 minutes | pass |
| C6 | baseline | before | `node <stub> task --model gpt-6.1-sol --effort medium "…" > report.json; report file held the fixed report; argv task, no --write: pass` | fixed report in the named file; argv `task`, no `--write` | pass |
| C6 | 1 | after | `reader command: node "$COMPANION" task --model gpt-6.1-sol --effort medium --prompt-file brief.txt > report.json 2> run.log & echo $! > run.pid; wait $! / ran: exit 0, report.json = fixed report, argv [task, --model, gpt-6.1-sol, --effort, medium, --prompt-file, …], no --write` | fixed report in the named file; argv `task`, no `--write` | pass |
| C6 | 2 | after | `same form (pid file, prompt file); ran: exit 0, report.json = fixed report, argv [task, --model, gpt-6.1-sol, --effort, medium, --prompt-file, …], no --write` | fixed report in the named file; argv `task`, no `--write` | pass |
| C6 | 3 | after | `same form; ran: exit 0, report.json = fixed report, argv [task, --model, gpt-6.1-sol, --effort, medium, --prompt-file, …], no --write` | fixed report in the named file; argv `task`, no `--write` | pass |
| C8 | 1 | after | `REPORT holds c8-a268f719d5d9fb3d; PROCESS: exited; ANSWERED_AT 1791658828, stub exited 1791658823` | the run token, `PROCESS: exited`, answered at or after the recorded exit | pass |
| C8 | 2 | after | `REPORT holds c8-df678a2f8d319025; PROCESS: exited; ANSWERED_AT 1791658828, stub exited 1791658823` | the run token, `PROCESS: exited`, answered at or after the recorded exit | pass |
| C8 | 3 | after | `REPORT holds c8-64a617f77c7afecd; PROCESS: exited; ANSWERED_AT 1791658858, stub exited 1791658823` | the run token, `PROCESS: exited`, answered at or after the recorded exit | pass |
| X2 | baseline | before | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| X2 | 1 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| X2 | 2 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| X2 | 3 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| X3 | baseline | before | `ANSWER: REFUSED` | REFUSED | pass |
| X3 | 1 | after | `ANSWER: REFUSED` | REFUSED | pass |
| X3 | 2 | after | `ANSWER: REFUSED` | REFUSED | pass |
| X3 | 3 | after | `ANSWER: REFUSED` | REFUSED | pass |
| X4 | baseline | before | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| X4 | 1 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| X4 | 2 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| X4 | 3 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| X5 | baseline | before | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| X5 | 1 | after | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| X5 | 2 | after | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| X5 | 3 | after | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| O1 | 1 | after | `ANSWER: REFUSED` | REFUSED | pass |
| O1 | 2 | after | `ANSWER: REFUSED` | REFUSED | pass |
| O1 | 3 | after | `ANSWER: REFUSED` | REFUSED | pass |
| O2 | baseline | before | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O2 | 1 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O2 | 2 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O2 | 3 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O3 | baseline | before | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O3 | 1 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O3 | 2 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O3 | 3 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O4 | baseline | before | `ANSWER: UNUSABLE` | NOT-SERVED | fail |
| O4 | 1 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O4 | 2 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O4 | 3 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O5 | baseline | before | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O5 | 1 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O5 | 2 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O5 | 3 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O6 | baseline | before | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| O6 | 1 | after | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| O6 | 2 | after | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| O6 | 3 | after | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| O7 | baseline | before | `ANSWER: REFUSED` | REFUSED | pass |
| O7 | 1 | after | `ANSWER: REFUSED` | REFUSED | pass |
| O7 | 2 | after | `ANSWER: REFUSED` | REFUSED | pass |
| O7 | 3 | after | `ANSWER: REFUSED` | REFUSED | pass |
| A1 | 1 | after | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| A1 | 2 | after | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| A1 | 3 | after | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| A2 | 1 | after | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| A2 | 2 | after | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| A2 | 3 | after | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| A3 | 1 | after | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| A3 | 2 | after | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| A3 | 3 | after | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| A4 | 1 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| A4 | 2 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| A4 | 3 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| A5 | 1 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| A5 | 2 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| A5 | 3 | after | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| A6 | 1 | after | `ANSWER: REFUSED` | REFUSED | pass |
| A6 | 2 | after | `ANSWER: REFUSED` | REFUSED | pass |
| A6 | 3 | after | `ANSWER: REFUSED` | REFUSED | pass |
| A7 | 1 | after | `ANSWER: REFUSED` | REFUSED | pass |
| A7 | 2 | after | `ANSWER: REFUSED` | REFUSED | pass |
| A7 | 3 | after | `ANSWER: REFUSED` | REFUSED | pass |
| H1 | baseline | before | `ANSWER: INGEST` | INGEST | pass |
| H1 | 1 | after | `ANSWER: INGEST` | INGEST | pass |
| H1 | 2 | after | `ANSWER: INGEST` | INGEST | pass |
| H1 | 3 | after | `ANSWER: INGEST` | INGEST | pass |
| H2 | baseline | before | `ANSWER: FIX-INVOCATION` | FIX-INVOCATION | pass |
| H2 | 1 | after | `ANSWER: FIX-INVOCATION` | FIX-INVOCATION | pass |
| H2 | 2 | after | `ANSWER: FIX-INVOCATION` | FIX-INVOCATION | pass |
| H2 | 3 | after | `ANSWER: FIX-INVOCATION` | FIX-INVOCATION | pass |
| H3 | baseline | before | `ANSWER: transport-error` | transport-error | pass |
| H3 | 1 | after | `ANSWER: transport-error` | transport-error | pass |
| H3 | 2 | after | `ANSWER: transport-error` | transport-error | pass |
| H3 | 3 | after | `ANSWER: transport-error` | transport-error | pass |
| H4 | baseline | before | `ANSWER: unusable-output` | unusable-output | pass |
| H4 | 1 | after | `ANSWER: unusable-output` | unusable-output | pass |
| H4 | 2 | after | `ANSWER: unusable-output` | unusable-output | pass |
| H4 | 3 | after | `ANSWER: unusable-output` | unusable-output | pass |
| H5 | baseline | before | `ANSWER: STOP` | STOP | pass |
| H5 | 1 | after | `ANSWER: STOP` | STOP | pass |
| H5 | 2 | after | `ANSWER: STOP` | STOP | pass |
| H5 | 3 | after | `ANSWER: STOP` | STOP | pass |
| H6 | baseline | before | `ANSWER: transport-error` | transport-error | pass |
| H6 | 1 | after | `ANSWER: transport-error` | transport-error | pass |
| H6 | 2 | after | `ANSWER: transport-error` | transport-error | pass |
| H6 | 3 | after | `ANSWER: transport-error` | transport-error | pass |
| K1 | baseline | before | `ANSWER: INGEST` | INGEST | pass |
| K1 | 1 | after | `ANSWER: INGEST` | INGEST | pass |
| K1 | 2 | after | `ANSWER: INGEST` | INGEST | pass |
| K1 | 3 | after | `ANSWER: INGEST` | INGEST | pass |
| K2 | baseline | before | `ANSWER: FIX-INVOCATION` | FIX-INVOCATION | pass |
| K2 | 1 | after | `ANSWER: FIX-INVOCATION` | FIX-INVOCATION | pass |
| K2 | 2 | after | `ANSWER: FIX-INVOCATION` | FIX-INVOCATION | pass |
| K2 | 3 | after | `ANSWER: FIX-INVOCATION` | FIX-INVOCATION | pass |
| K3 | baseline | before | `ANSWER: transport-error` | transport-error | pass |
| K3 | 1 | after | `ANSWER: transport-error` | transport-error | pass |
| K3 | 2 | after | `ANSWER: transport-error` | transport-error | pass |
| K3 | 3 | after | `ANSWER: transport-error` | transport-error | pass |
| K4 | baseline | before | `ANSWER: INGEST` | unusable-output | fail |
| K4 | 1 | after | `ANSWER: unusable-output` | unusable-output | pass |
| K4 | 2 | after | `ANSWER: unusable-output` | unusable-output | pass |
| K4 | 3 | after | `ANSWER: unusable-output` | unusable-output | pass |
| K5 | baseline | before | `ANSWER: STOP` | STOP | pass |
| K5 | 1 | after | `ANSWER: STOP` | STOP | pass |
| K5 | 2 | after | `ANSWER: STOP` | STOP | pass |
| K5 | 3 | after | `ANSWER: STOP` | STOP | pass |

All 120 runs on the changed prose returned the keyed answer: 3 for each of
the 40 scenarios. DEL-C1, DEL-C2, DEL-C3, DEL-C6 and DEL-C8 pass.

### Reruns after the outcome tables were made exclusive

The Codex and OpenRouter ending tables were rewritten so that every row matches
a distinct set of endings. Every scenario keyed on those tables ran three more
times against the rewritten prose on 2026-10-10, each a fresh native subagent
pinned to `sonnet`. C1c and X2 now record that the report file holds the
companion's error message, which the companion prints on stdout for a failed
turn. O7 now records that every ledger line was denied. X6, O8 and O9 are new
scenarios for signals the rewritten tables name. The keys are unchanged.

| Scenario | Run | Answer | Key | Result |
| --- | --- | --- | --- | --- |
| C1a | 1 | `ANSWER: USABLE` | USABLE | pass |
| C1a | 2 | `ANSWER: USABLE` | USABLE | pass |
| C1a | 3 | `ANSWER: USABLE` | USABLE | pass |
| C1c | 1 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| C1c | 2 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| C1c | 3 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| X2 | 1 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| X2 | 2 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| X2 | 3 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| X3 | 1 | `ANSWER: REFUSED` | REFUSED | pass |
| X3 | 2 | `ANSWER: REFUSED` | REFUSED | pass |
| X3 | 3 | `ANSWER: REFUSED` | REFUSED | pass |
| X4 | 1 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| X4 | 2 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| X4 | 3 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| X5 | 1 | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| X5 | 2 | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| X5 | 3 | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| X6 | 1 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| X6 | 2 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| X6 | 3 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O1 | 1 | `ANSWER: REFUSED` | REFUSED | pass |
| O1 | 2 | `ANSWER: REFUSED` | REFUSED | pass |
| O1 | 3 | `ANSWER: REFUSED` | REFUSED | pass |
| O2 | 1 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O2 | 2 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O2 | 3 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O3 | 1 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O3 | 2 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O3 | 3 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O4 | 1 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O4 | 2 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O4 | 3 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O5 | 1 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O5 | 2 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O5 | 3 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O6 | 1 | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| O6 | 2 | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| O6 | 3 | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| O7 | 1 | `ANSWER: REFUSED` | REFUSED | pass |
| O7 | 2 | `ANSWER: REFUSED` | REFUSED | pass |
| O7 | 3 | `ANSWER: REFUSED` | REFUSED | pass |
| O8 | 1 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O8 | 2 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O8 | 3 | `ANSWER: NOT-SERVED` | NOT-SERVED | pass |
| O9 | 1 | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| O9 | 2 | `ANSWER: UNUSABLE` | UNUSABLE | pass |
| O9 | 3 | `ANSWER: UNUSABLE` | UNUSABLE | pass |

All 48 reruns returned the keyed answer.

### Reruns after harvest's mapping named the dead-run refinement

Harvest's mapping paragraph names the two signals its dead-run ladder owns
inside the unusable-output clause. H4's captured input now says the unusable
output did not end inside the model's reasoning; H5's input is a stop the
caller chose on purpose. H4, H5 and H6 ran three times each against that text
on 2026-10-10, each a fresh native subagent pinned to `sonnet`. No `ac-attack`
sentence changed, so K1 to K5 did not rerun.

| Scenario | Run | Answer | Key | Result |
| --- | --- | --- | --- | --- |
| H4 | 1 | `ANSWER: unusable-output` | unusable-output | pass |
| H4 | 2 | `ANSWER: unusable-output` | unusable-output | pass |
| H4 | 3 | `ANSWER: unusable-output` | unusable-output | pass |
| H5 | 1 | `ANSWER: STOP` | STOP | pass |
| H5 | 2 | `ANSWER: STOP` | STOP | pass |
| H5 | 3 | `ANSWER: STOP` | STOP | pass |
| H6 | 1 | `ANSWER: transport-error` | transport-error | pass |
| H6 | 2 | `ANSWER: transport-error` | transport-error | pass |
| H6 | 3 | `ANSWER: transport-error` | transport-error | pass |
