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
returned exit status 1 after 3 seconds. The report file is empty. The stderr
capture file holds:

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
| X1 | Codex | exit 1, `[codex] Codex error: You've hit your usage limit…` on stderr | the provider did not serve the run | the `error` notification's progress line; exit from `buildResultStatus` |
| X2 | Codex | exit 1, another `[codex] Codex error:` line, or a turn ending other than `[codex] Turn completed.` | the provider did not serve the run | the same, and the `turn/completed` progress line |
| X3 | Codex | exit 1, stderr one line with no `[codex]` prefix, such as `Provide a prompt, a prompt file, piped stdin, or use --resume-last.` | the launcher refused the invocation | the `main().catch` handler |
| X4 | Codex | exit 1, `Codex CLI is not installed or is missing required runtime support…` | the provider did not serve the run | `ensureCodexAvailable`, through `main().catch` |
| X5 | Codex | exit 0, stdout `Codex did not return a final message.`, or a reply that is not the report asked for | the run produced unusable output | `renderTaskResult` |
| O0 | OpenRouter | the child's exit 0, its result on stdout | usable output | `main` returns the child's code |
| O1 | OpenRouter | exit 78, a `[run]` line naming what was refused: a missing flag, a bad clock value, a refused model, an unset key | the launcher refused the invocation | `EXIT_CONFIG_ERROR` paths in `main` |
| O2 | OpenRouter | exit 75, `[run] reason=timeout` | the provider did not serve the run | `supervise`, `EXIT_ROUTE` |
| O3 | OpenRouter | exit 75, `[run] reason=idle` | the provider did not serve the run | `supervise`, `EXIT_ROUTE` |
| O4 | OpenRouter | exit 75, `[run] reason=signal` | the provider did not serve the run; after a signal the caller sent, the caller stops | `supervise`, `EXIT_ROUTE` |
| O5 | OpenRouter | the child's non-zero exit, with `[proxy] upstream <status> …` on stderr | the provider did not serve the run | the child's code; the proxy's upstream error line |
| O6 | OpenRouter | `[proxy] WARNING: response ends on thinking and contains no text block to promote`, no report | the run produced unusable output | the proxy's stream repair |
| O7 | OpenRouter | a `[proxy] model-ledger` line with `decision=deny-pin` or `decision=deny-denylist` | the launcher refused the invocation | `screenModel` and its ledger line |
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
  child's own exit code. Each is a row above. The proxy's upstream error
  line, its thinking-block warning and its ledger decisions are the proxy's
  own stderr lines, documented as rows O5 to O7.
- `codex-companion.mjs` returns 0, or 1 for a failed turn and for any error
  its `main` catches. It has no reason line of its own; its stderr carries
  `[codex]` progress lines. An unknown flag is not refused: the companion
  folds it into the prompt text, so "unknown flag refused" is a signal the
  script does not emit, and no skill documents it.

### Launcher scenarios

Prompt L, one scenario per failure signal above. X1 is C1c. The key is the
outcome's answer word: usable output is `USABLE`, the launcher refused the
invocation is `REFUSED`, the provider did not serve the run is `NOT-SERVED`,
and the run produced unusable output is `UNUSABLE`.

#### X2 (skill `codex`)

```text
You started a read-only run with the command the skill gives. The Bash call
returned exit status 1 after 9 seconds. The report file is empty. The stderr
capture file ends:

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
The launcher exited 1. Its stderr holds:
[proxy] model-ledger POST /api/v1/messages model=z-ai/glm-5.3[1m] decision=deny-pin
Its stdout holds the harness's error result naming a 403.
```

Key: `ANSWER: REFUSED`.

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
| H4, K4 | You dispatched the `<lens>` lens. Its launcher's own skill says what its ending means: the run produced unusable output. | `unusable-output` |
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

Filled in after the runs.
