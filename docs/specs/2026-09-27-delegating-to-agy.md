# delegating-to-agy: Antigravity CLI as a fresh-context lens or a full worker

**Date:** 2026-09-27
**Status:** Child spec of `docs/specs/2026-07-21-harness-rework-way-forward.md` (D4 contract-only rule, D5 foreign eyes in review seats, D16 removal conditions). Draft for review; no attack or review is claimed for this document.
**Work item:** `agents-config-9k9.437`. Its five acceptance lines are restated here as AGY criteria (section 7 maps them).
**Consumers:** `agents-config-9k9.17.29` (review-panel Gemini seats run on agy first, OpenRouter as fallback) consumes lens mode and the failure contract. `agents-config-9k9.436` (agy as an install target) and `agents-config-9k9.408` (per-seat routing pins) are siblings; this spec changes nothing they own.
**Quality contract:** `docs/specs/2026-09-18-acceptance-criteria-quality.md`. **Lifecycle:** `docs/specs/2026-09-18-acceptance-criteria-lifecycle.md`.

## 1. Problem statement

Antigravity CLI (`agy`) replaced Gemini CLI on this machine and bills against a Google AI Pro subscription. Today every Gemini-model dispatch pays OpenRouter rates and rides a transport that has died mid-stream in live rounds, while the subscription route sits unused. Two sibling skills exist for other vendors: `delegating-to-codex` (OpenAI, through the Codex plugin's agent) and `openrouter-claude-subagent` (a nested Claude harness pointed at OpenRouter). Both still exclude "Gemini CLI" in their descriptions, naming a tool that no longer exists, and `choosing-a-delegate` routes every non-OpenAI model to OpenRouter.

A Gemini run has two shapes with opposite needs. A **worker** implements or investigates in the user's checkout and should read the same instruction files Claude and Codex read. A **lens** reviews a change against the world, so the house rulebook must stay out of its context: the user-level `~/.gemini/GEMINI.md`, and the repository's own `AGENTS.md` files, which in this repository are often the change under review. agy has no flag, setting or environment variable that keeps those files out.

## 2. Scope

In scope: one skill, `delegating-to-agy`, with one launcher script that runs agy in worker mode or lens mode; the model table; the failure contract callers fail over on; the canary that proves lens isolation; timeouts and kill-by-pid; the edits to the three sibling skills; the admission case.

Out of scope: the review-panel routing that consumes lens mode (`agents-config-9k9.17.29`); deploying skills or rules where agy discovers them (`agents-config-9k9.436`); pricing Gemini in the admission gate; agy sign-in; reviewing uncommitted working trees in lens mode (section 9).

## 3. Facts established on 2026-09-27

Every claim in the tracker notes was treated as a hypothesis and re-tested against agy 1.2.12 (the notes were taken on 1.2.11; the machine auto-updated). Probes ran from scratch directories with the real `HOME`, `--print-timeout` on every run, and no permission bypass. Each row states what the launcher design rests on.

| # | Observation | Consequence for the design |
| --- | --- | --- |
| F1 | `agy -p ... --output-format json` returns `{conversation_id, status, response, duration_seconds, num_turns, usage}` and, when a tool was auto-denied, `denied_actions: [{action, display_name}]`. `--output-format stream-json` emits an `init` event (cwd, `agent`, tool roster, `permission_mode`), one `step_update` per agent response and per tool call (with `tool_name` and parameters), and a final `result` event holding the same object as json mode. | The launcher reads stream-json: the tool events are the read evidence the review-panel dispatch gate wants, and the `result` event is the outcome. |
| F2 | A tool that needs a permission headless mode cannot prompt for is auto-denied, and the run then ends with `status: SUCCESS`, an empty `response`, `denied_actions` filled, exit 0, and a `jetski: no output produced` notice on stderr. Seen for `RunCommand` (a shell command) and for `ViewFile` on a path outside the workspace. | "Non-SUCCESS status" is not the failure contract. Empty response or any denied action is a failure the launcher must report on its own. |
| F3 | `--print-timeout 3s` on a long turn returns `status: SUCCESS`, empty `response`, zero usage, exit 0, and `[agy] print timeout after 3s with turn in progress; returning partial output` on stderr. | A timeout looks like success to a naive caller. The launcher owns the clock and reports timeouts itself. |
| F4 | An unknown `--model` returns `status: ERROR`, an `error` field, exit 1 and the same text on stderr. An invalid custom-agent tool name returns `status: ERROR`, exit 3, and an `AGY_ERROR: {"short_error", "status", "error_code", "code_kind", "retryable", "error_id"}` line on stderr. The changelog states model and agent API failures also exit 3 with an `AGY_ERROR` line. | Non-zero exit, non-SUCCESS status, or an `AGY_ERROR` line is the transport-failure class. Quota exhaustion is unobserved and lands in this class by construction. |
| F5 | `agy models` lists Gemini 3.6, 3.7 and 3.8 Flash at `-low`, `-medium`, `-high`, Gemini 3.1 Pro at `-low` and `-high`, two Claude ids and one GPT-OSS id, as full model ids. `--model gemini-3.8-flash-low --effort high` is refused: "conflicts with --effort=high". | Effort rides in the model id. The launcher never passes `--effort`. |
| F6 | With `HOME` real and a Seatbelt profile `(deny file-read* (literal "$HOME/.gemini/GEMINI.md"))`, agy starts, authenticates and answers. The banana canary scripted in that file (the deployed `AGENTS.local.md` tail) fires in an unwrapped run ("not anyone's business") and does not fire under the profile ("typically yellow"). `cat` and `stat` on the file under the profile fail with "Operation not permitted" (EPERM, not ENOENT); the parent directory still lists the name. | The profile is the isolation mechanism for the user file. Denials are visible to a subprocess check, which is the launch canary. |
| F7 | Nesting: an inner `sandbox-exec` whose profile equals the outer one succeeds; an inner profile that differs, wider or narrower, fails with `sandbox_apply: Operation not permitted`, exit 71. | A wrapped process cannot run Codex, a sandboxed Claude, or agy `--sandbox`. Workers stay unwrapped. A caller whose own shell is already Seatbelt-sandboxed cannot launch a lens; the canary catches it. |
| F8 | A root-level `AGENTS.md` at the cwd loads in every run, trusted workspace or not (`trustedWorkspaces` in `~/.gemini/antigravity-cli/settings.json` gates nothing observed here). A sub-directory `AGENTS.md` did not load at start nor after the model read a file beside it. Frontmatter-less `.agents/rules/*.md` files, at the root and in a sub-directory, did not load. The customization guide bundled with agy nonetheless names `GEMINI.md`, `AGENTS.md` and `.agents/rules/*.md` as hierarchical rule sources, walked up from each touched file. | Renaming the whole rules class in the snapshot is cheap and covers both the observed and the documented behaviour. `--add-dir` from an empty cwd loads the added repository's root rules (tracker note, not re-tested) and stays rejected. |
| F9 | A workspace custom agent at `.agents/agents/<name>/agent.md` with `tools: [view_file, grep_search, find_by_name, list_dir]` is selected by `--agent <name>` in headless mode from an untrusted scratch directory. The run used only those four tools across 58 calls; `grep_search` and `find_by_name` work without any command permission, and no shell command was attempted. Asked to create a file, the agent reported it has no write or shell tool (agy adds only `manage_task`), and no file appeared, with or without `--mode plan`. In default mode a workspace file read needs no permission. | A read-only tool allowlist exists after all, as a custom agent. It replaces plan mode as the lens's write barrier. |
| F10 | `--mode plan` makes the model write a plan artifact under `~/.gemini/antigravity-cli/brain/` and ask for approval even for "say hi" (58k input tokens), and its `permission_mode` is `request-review`. The same read-only agent answered a small search-and-read request in 171 s and 268k input tokens under plan mode, and a comparable read-and-answer request in 7 s and 9k input tokens in default mode. | Plan mode adds ceremony a lens does not need once the agent has no mutating tool. |
| F12 | A headless file write is auto-denied in default mode everywhere, and under `--mode accept-edits` in an untrusted directory; under `--mode accept-edits` in a directory beneath a path listed in `trustedWorkspaces` of `~/.gemini/antigravity-cli/settings.json` the write succeeds. The trusted match is by ancestor path: the probe directory had its own `.git` and was not itself listed. | A worker edits only with `--mode accept-edits` from a trusted workspace; a worktree beneath a trusted repository path inherits the trust. A lens snapshot in a temporary directory is untrusted by construction, which is a second write barrier. |
| F11 | The rules guide bundled with agy: 24,000-byte cap per rule file, a shared 20,000-token budget for always-on and global rules, `@[label](path)` includes. Global customizations live under `~/.gemini/config/` (`rules/`, `skills/`, `agents/`, `workflows/`); today that directory holds only `config.json`, `mcp_config.json` and `projects/`. | The lens profile denies `~/.gemini/config/rules` now, so a future rules deploy there stays out of a lens without a launcher change. |

Claims the probes contradicted are collected in section 10.

## 4. Decisions

**AGY-D1 — Name and placement.** The skill is `delegating-to-agy` at `src/user/.claude/skills/delegating-to-agy/`. The name matches its siblings (`delegating-to-codex`) and the tool it launches. Placement follows the repository's capability-dependency rule, applied to the procedure: lens mode wraps agy in `sandbox-exec`, which fails inside any shell that already carries a different Seatbelt profile (F7), so the procedure works only from a runtime whose shell is unsandboxed or shares no profile; Codex's shell on macOS is sandboxed, so the lens step cannot run there. Lens mode also exists to serve `review-panel` and is routed by `choosing-a-delegate`, both Claude-only. The refuted alternative is the shared tree: worker mode alone would work on every tool, but one artifact ships as one unit and follows its most demanding step, and a shared placement would advertise a lens step that three of four tools cannot perform.

**AGY-D2 — One launcher, two modes, Python.** `scripts/agy_run.py` is a PEP 723 script (the convention `content-tests` runs) with `scripts/agy_run_test.py` beside it. Sub-commands `worker` and `lens` share argv parsing, the stream-json reader, the outcome classifier and the watchdog; they differ only in what they wrap. Python over Node: the launcher needs a tar extraction, a process group, and JSON line parsing, all standard library; the OpenRouter launcher is Node because it hosts a proxy, which this launcher does not. The refuted alternative is two scripts, which would duplicate the classifier and let the two modes' failure contracts drift apart.

**AGY-D3 — Worker launch contract.** `agy_run.py worker --model ID --timeout SECONDS [--skip-permissions] -p PROMPT` spawns exactly `agy -p PROMPT --model ID --output-format stream-json --print-timeout <SECONDS>s --mode accept-edits` in the invoking directory, with the parent's environment untouched. No `sandbox-exec`, no `--agent`, no `--add-dir`, no `--effort`. The user's `~/.gemini/GEMINI.md` and the checkout's own rules load, as Claude's and Codex's instruction files load for their workers. A headless worker edits files only under `--mode accept-edits` and only inside a trusted workspace (F12), so the launcher checks before spawning that the invoking directory is at or beneath a path in `trustedWorkspaces` of `~/.gemini/antigravity-cli/settings.json`, and exits 78 naming that file and the remedy when it is not; a worker whose every edit is silently denied returns an empty run at full cost (F2), and a preflight names the cause for nothing. Shell commands stay governed by the user's `permissions.allow` list in the same settings file; a command outside it is auto-denied and surfaces in the ledger. `--skip-permissions` forwards `--dangerously-skip-permissions` verbatim and is a caller decision under the same gate the OpenRouter skill applies to write and network grants: ask the user before passing it. The launcher never wraps a worker (F7).

**AGY-D4 — Lens launch contract.** `agy_run.py lens --repo PATH [--rev REV] --model ID --timeout SECONDS [--keep-snapshot] -p PROMPT` builds a snapshot (AGY-D5), writes the read-only agent and the Seatbelt profile, proves the profile (AGY-D8), then spawns `sandbox-exec -f <profile> agy --agent agy-lens --model ID -p <preamble + PROMPT> --output-format stream-json --print-timeout <SECONDS>s` with the snapshot as cwd and the parent's environment untouched. The argv carries no `--mode`, no `--dangerously-skip-permissions`, no `--add-dir`, no `--effort`. The write barrier is the agent's tool list (F9), not plan mode (F10); headless auto-denial of anything outside the workspace, and of every write in an untrusted directory (F12), is the backstop, and the lens performs no trust check because its snapshot is meant to stay untrusted. The refuted alternative, `--mode plan`, blocks nothing the agent can reach and costs a plan artifact and an approval request per run.

**AGY-D5 — How a lens reads the repository under review.** The launcher extracts `git archive REV` of `--repo` into a fresh temporary directory outside the repository. In that snapshot it renames every file whose basename is `AGENTS.md` or `GEMINI.md`, every `*.md` directly under a `rules/` directory whose parent is `.agents`, `.agent`, `_agents` or `_agent`, and every `hooks.json` under those four directories, to `<name>.under-review`. It then runs `git init` in the snapshot so agy's walk to a repository root stops there, and writes `.agents/agents/agy-lens/agent.md`. The lens reads the renamed files as ordinary files, which keeps them reviewable, and nothing loads them as rules. A preamble the launcher prepends to the prompt names the snapshot path, the revision, the suffix convention, and the instruction to stay inside the snapshot. The snapshot is deleted on every exit path unless `--keep-snapshot`. Refuted alternatives: a regex deny on `AGENTS.md` reads blinds the lens to the files most often under review here; `--add-dir` from an empty cwd loads the added repository's root rules (F8); running in the real checkout loads the real rules and lets a tool write to it. Hooks are renamed because a hook runs repository code with the user's credentials and a lens never needs one. Skills, workflows and other agents in the snapshot's `.agents/` are left in place: they load on demand only, and they may be the change under review.

**AGY-D6 — Model and effort are one lever.** The launcher requires `--model` and passes it verbatim; it defines no `--effort` flag and refuses one (F5). The skill's `references/model-routing.md` maps task profiles to full agy model ids, captured from `agy models` on 2026-09-27:

| Task profile | Model id |
| --- | --- |
| Architecture, cross-subsystem, security, whole-artifact frontier lens | `gemini-3.1-pro-high` |
| Standard review, implementation, general default | `gemini-3.8-flash-high` |
| Delta re-review, mid-tier lens | `gemini-3.8-flash-medium` |
| Triage, extraction, cost-sensitive runs | `gemini-3.8-flash-low` |

Pro carries `low` and `high` only. A `claude-` model id is refused before anything spawns: Claude runs natively in the harness that launched the run, the same denial the OpenRouter launcher makes. An id agy does not know is agy's error (F4) and classifies as a route failure, so the table is advisory and agy stays the authority.

**AGY-D7 — Failure contract.** Four exit codes, chosen so a caller decides the next move from the code alone. stdout carries the model's final `response` text and nothing else; stderr carries the ledger (AGY-D10) and agy's own stderr verbatim.

| Exit | Meaning | Caller's move | Dispatch-gate reason |
| --- | --- | --- | --- |
| `0` | `status: SUCCESS`, non-empty response, no denied action | Use the output | — |
| `70` | agy finished but the output is unusable: empty response, or `denied_actions` non-empty | Re-brief (for example, keep the model inside the workspace) or move to another route | `unusable-output` |
| `75` | The route did not serve the run: agy exit non-zero, non-SUCCESS status, an `AGY_ERROR` line, `agy` not on PATH, timeout (AGY-D9), or the sandbox canary failed (AGY-D8) | Fail over to the next route or model, quoting the stderr reason | `transport-error` |
| `78` | The launcher refused the invocation: missing flags, `--effort`, a `claude-` model, `--skip-permissions` on a lens, a worker directory outside every trusted workspace, an unreadable repository or revision | Fix the invocation; do not fail over | — |

Quota exhaustion is unobserved; whatever agy reports, it is either a non-zero exit, a non-SUCCESS status, or an empty response, and all three map to a code the consumer fails over on. The stderr line `[agy-run] reason=<word>` names the sub-cause (`error`, `no-route`, `timeout`, `sandbox-unproven`, `empty`, `denied`, `untrusted-workspace`).

**AGY-D8 — Canary at launch.** Before spawning agy in lens mode the launcher runs `sandbox-exec -f <profile> /bin/cat $HOME/.gemini/GEMINI.md`. The expected outcome is a non-zero exit with "Operation not permitted" on stderr (F6). A zero exit means the profile is not denying and the lens would read the house rulebook: exit 75, `reason=sandbox-unproven`, no agy spawn. An exit 71 or a missing `sandbox-exec` means the route cannot run from this shell (F7): exit 75, `reason=no-route`. The canary proves the mechanism, not the model's behaviour, so the behavioural check (the banana rule fires for a worker and not for a lens) is a recorded evidence run on the work item rather than a per-launch cost. Refuted alternative: a model-answered canary per launch spends a model turn to learn what `cat` learns for free.

**AGY-D9 — Timeouts and kill-by-pid.** `--timeout SECONDS` is required in both modes. The launcher passes `--print-timeout <SECONDS>s` to agy and arms its own watchdog at `SECONDS + 30`. agy runs in a new session (process group led by the agy pid); the launcher prints `[agy-run] pid=<pid>` at spawn so a runner can kill the group by pid. On the watchdog firing it sends `SIGTERM` to the group, `SIGKILL` ten seconds later, and exits 75 `reason=timeout`. A run that ends by agy's own print-timeout notice (F3) is also 75 `reason=timeout`, so a caller never mistakes a partial run for success. Refuted alternative: `timeout N agy ...` alone, which the OpenRouter launcher's history shows survives `SIGTERM` and leaves the run orphaned.

**AGY-D10 — The ledger on stderr.** From the stream: `[agy-run] pid=`, one `[agy-run] tool=<tool_name> <first parameter>` per tool `step_update` entering `ACTIVE`, `[agy-run] agent=<name> permission_mode=<mode>` from `init`, and a final `[agy-run] status=<status> turns=<n> tokens=<total> denied=<names>`. agy's own stderr passes through unchanged so an `AGY_ERROR` line and the jetski notice survive for the round's records. The `tool=` count is what a no-read check reads (`agents-config-9k9.408` names that check for the other transports).

**AGY-D11 — Sibling edits in the same change.** `choosing-a-delegate`'s route table gains a row before the OpenRouter row: Gemini models run through this skill, on the subscription, and OpenRouter is the fallback once quota is spent. `delegating-to-codex`'s description drops "and not for OpenRouter or Gemini CLI" in favour of "and not for OpenRouter or agy". `openrouter-claude-subagent`'s description drops "Codex or Gemini CLI" in favour of "Codex, and not the first route for a Gemini model, which is the agy skill; this transport is its fallback", and keeps Gemini in its hosted-model list because the fallback still names those ids. No other deployed prose changes; `src/user/.gemini/` and the shared README name Gemini CLI as an install target and belong to `agents-config-9k9.436`.

**AGY-D12 — Admission case.** The record the front matter carries, in the shape `admit-request` evaluates. It states one worth field: this is a repeatable procedure, so the assistive case is the honest one.

```yaml
admission:
  provides: An agy run in one of two verified shapes: a worker in the current checkout that reads the user's and the repository's instruction files like a Claude or Codex worker does, or a fresh-context lens over a snapshot of a revision whose instruction files are renamed so nothing loads them as rules, wrapped in a Seatbelt profile that keeps the user rules file out and proven by a canary before the model starts. Invoking it produces the launcher command, its exit code contract, and the model id for the task profile.
  cost: agy must be installed and signed in, and every run bills the Google AI Pro subscription; lens mode needs macOS sandbox-exec and leaves a snapshot of the reviewed revision on disk for the run's duration; the model table needs a refresh whenever agy's model list changes.
  remove_when: The Google AI Pro subscription lapses, agy loses headless print mode, or the review tooling addresses agy natively so no launcher stands between a caller and a Gemini seat.
```

Live-counterpart check: no artifact in `src/` launches agy; the two delegation skills address other vendors and route Gemini elsewhere, which this change corrects rather than duplicates.

## 5. Contract

Names below are the spec's public surface. Bodies are not specified; a scaffold may reference only these names (D4).

### 5.1 Skill layout

```
src/user/.claude/skills/delegating-to-agy/
├── SKILL.md                      # front matter: name, description, admission (AGY-D12)
├── references/model-routing.md   # the table in AGY-D6 with its capture date
├── scripts/agy_run.py            # the launcher
├── scripts/agy_run_test.py       # its suite
└── evals/trigger-eval.json       # trigger corpus, source-side only
```

### 5.2 Launcher command line

```
agy_run.py worker --model ID --timeout SECONDS [--skip-permissions] -p PROMPT
agy_run.py lens   --repo PATH [--rev REV] --model ID --timeout SECONDS [--keep-snapshot] -p PROMPT
```

`REV` defaults to `HEAD` and accepts any tree-ish `git archive` accepts. `PROMPT` is the last argument and is never parsed for flags.

### 5.3 Python signatures

```python
EXIT_OK = 0
EXIT_UNUSABLE = 70
EXIT_ROUTE = 75
EXIT_CONFIG = 78

LENS_AGENT = "agy-lens"
LENS_TOOLS = ("view_file", "grep_search", "find_by_name", "list_dir")
RENAME_SUFFIX = ".under-review"
WATCHDOG_GRACE_S = 30
KILL_GRACE_S = 10
AGY_SETTINGS = Path("~/.gemini/antigravity-cli/settings.json")

class Outcome(NamedTuple):
    exit_code: int
    reason: str | None       # error | no-route | timeout | sandbox-unproven | empty | denied | untrusted-workspace | None
    response: str
    ledger: list[str]

def parse_args(argv: list[str]) -> argparse.Namespace: ...
def refuse_model(model: str) -> str | None: ...
def trusted_workspace(cwd: Path, settings: Path) -> bool: ...
def build_worker_argv(model: str, timeout_s: int, prompt: str, skip_permissions: bool) -> list[str]: ...
def build_lens_argv(model: str, timeout_s: int, prompt: str, profile: Path) -> list[str]: ...
def lens_profile(home: Path) -> str: ...
def lens_agent_definition() -> str: ...
def lens_preamble(repo: Path, rev: str, snapshot: Path) -> str: ...
def neutralized_names(paths: Iterable[PurePosixPath]) -> list[tuple[PurePosixPath, PurePosixPath]]: ...
def make_snapshot(repo: Path, rev: str, parent: Path) -> Path: ...
def prove_sandbox(profile: Path, home: Path, run: Callable[..., subprocess.CompletedProcess]) -> Outcome | None: ...
def classify(exit_code: int, events: list[dict], stderr_text: str, timed_out: bool) -> Outcome: ...
def run_agy(argv: list[str], cwd: Path, timeout_s: int, spawn: Callable[..., subprocess.Popen], clock: Callable[[], float]) -> Outcome: ...
def main(argv: list[str]) -> int: ...
```

`spawn`, `run` and `clock` are seams so the suite runs against a fake `agy` (a script that replays canned stream-json lines, sleeps, or exits with a chosen code) and never against the real one.

### 5.4 The lens agent definition

```markdown
---
name: agy-lens
description: Read-only review lens. Reads, searches and lists files in this snapshot and nothing else.
tools: [view_file, grep_search, find_by_name, list_dir]
subagent: false
---

# Lens

You review a snapshot of a repository at one revision. You can read, search and list files in it and nothing else. Files named AGENTS.md, GEMINI.md, rules under .agents/rules and hooks.json were renamed with the suffix .under-review; read them as ordinary files and cite them by their original names. Answer the request directly. Do not write a plan document.
```

### 5.5 The Seatbelt profile

```
(version 1)
(allow default)
(deny file-read* (literal "<HOME>/.gemini/GEMINI.md") (subpath "<HOME>/.gemini/config/rules"))
```

`<HOME>` is the launcher's own `HOME`, substituted at launch, never a substitute home (F6 and the tracker note on the rejected `HOME` substitution).

### 5.6 SKILL.md description

> Use when a run is being launched on Antigravity CLI (agy), Google's runtime for Gemini models: as a full worker in the current checkout, or as a fresh-context review lens over a snapshot whose instruction files stay out. Apply when the user names agy, Antigravity or a Gemini model, or when another skill sends a Gemini dispatch here. Not for deciding whether to leave Claude, not for agy setup or sign-in, and not for OpenRouter, which is this route's fallback once the subscription quota is spent.

## 6. Slices and acceptance criteria

Each criterion is one observable obligation with its check named. Suite criteria run under `content-tests` through the seams in 5.3; staging criteria run under `content-lint`; recorded criteria are `observed:` rows on the work item.

### Slice A — launcher core and worker mode

- **AGY-A1** `worker --model M --timeout N -p P` spawns argv `["agy", "-p", P, "--model", M, "--output-format", "stream-json", "--print-timeout", "Ns", "--mode", "accept-edits"]` with cwd equal to the invoking directory and an environment equal to the parent's (`HOME` included); the argv contains no `sandbox-exec`, `--agent`, `--add-dir`, `--effort` or `--dangerously-skip-permissions`. Check: suite, fake spawn records argv, cwd and env.
- **AGY-A2** `--skip-permissions` on `worker` appends `--dangerously-skip-permissions` to the argv verbatim; its absence leaves the argv without it. Check: suite.
- **AGY-A3** Each of the following exits 78 before anything spawns, with stderr naming the offending flag: a missing `--model`, `--timeout` or prompt; `--effort` anywhere in the launcher's argv; a `--model` beginning `claude-`; `--skip-permissions` on `lens`. A prompt whose text contains `--effort` is not a flag. Check: suite, fake spawn records zero calls.
- **AGY-A4** A `result` event with `status: SUCCESS`, a non-empty `response` and no `denied_actions` exits 0; stdout is exactly the response text; stderr holds `[agy-run] pid=<pid>`, one `[agy-run] tool=<name>` line per tool `step_update` that entered `ACTIVE`, and one final `[agy-run] status=SUCCESS` line. Check: suite over a canned stream with three tool steps.
- **AGY-A5** A `result` with `status: SUCCESS` and an empty `response`, or with a non-empty `denied_actions`, exits 70 with `[agy-run] reason=empty` or `reason=denied` naming each denied action's `display_name`, and stdout empty. Check: suite, both inverses of AGY-A4.
- **AGY-A6** agy exiting non-zero, a `result` whose `status` is not `SUCCESS`, or an `AGY_ERROR:` line on agy's stderr exits 75 with `reason=error`, agy's error text present on the launcher's stderr verbatim, and stdout empty. An `agy` binary absent from PATH exits 75 with `reason=no-route`. Check: suite, one case per trigger.
- **AGY-A7** No `result` event within `N + 30` seconds: the launcher sends `SIGTERM` to the agy process group, `SIGKILL` ten seconds later if it is still alive, and exits 75 with `reason=timeout`; a `result` whose stderr carries agy's `print timeout` notice and whose `response` is empty also exits 75 `reason=timeout`. Check: suite with a fake agy that sleeps past a one-second timeout and ignores `SIGTERM`; the group is gone afterwards.
- **AGY-A8** Repeated invocation with identical arguments produces identical argv and identical classification; the launcher writes nothing outside its temporary directory in worker mode. Check: suite.
- **AGY-A9** `worker` spawns only when the invoking directory equals or lies beneath a path listed in `trustedWorkspaces` of the settings file at `AGY_SETTINGS`; a directory outside every listed path, a settings file that is missing or unparseable, or a list that is absent, exits 78 with `reason=untrusted-workspace`, names the settings path, and spawns nothing. `lens` performs no such check. Check: suite with a temporary settings file, four cases.

### Slice B — lens mode

- **AGY-B1** `lens --repo R --rev V --model M --timeout N -p P` spawns argv `["sandbox-exec", "-f", <profile>, "agy", "--agent", "agy-lens", "--model", M, "-p", <preamble + P>, "--output-format", "stream-json", "--print-timeout", "Ns"]` with cwd equal to a directory that is not under R, and an environment equal to the parent's; the argv contains no `--mode`, `--add-dir`, `--effort` or `--dangerously-skip-permissions`. Check: suite, fake spawn.
- **AGY-B2** The snapshot contains every path `git archive V` of R emits and no path of R's working tree that V lacks; every emitted file whose basename is `AGENTS.md` or `GEMINI.md`, every `*.md` directly under `rules/` whose parent directory is `.agents`, `.agent`, `_agents` or `_agent`, and every `hooks.json` directly under one of those four directories, exists as `<name>.under-review` with identical bytes and does not exist under its original name; `.git` exists as a freshly initialised repository; `.agents/agents/agy-lens/agent.md` equals the definition in 5.4. Check: suite over a fixture repository committed in a temporary directory, with an uncommitted extra file and one of each renamed class at two depths.
- **AGY-B3** `neutralized_names` maps exactly the paths AGY-B2 describes and leaves every other path unchanged, including `CLAUDE.md`, `README.md`, `AGENTS.md.template`, and a `rules/x.md` whose parent is not one of the four directory names. Check: suite, pure function.
- **AGY-B4** If any path AGY-B2 says must be renamed still exists under its original name after the rename step, the launcher exits 78 before spawning and names the path. Check: suite with a fixture that recreates the file through the seam.
- **AGY-B5** The profile file's content equals 5.5 with `<HOME>` replaced by the launcher's `HOME`; `lens_profile` given a home containing a space or a quote produces a profile `sandbox-exec` parses. Check: suite; the parse case skips where `sandbox-exec` is absent and records the skip.
- **AGY-B6** Before spawning agy, the launcher runs `sandbox-exec -f <profile> /bin/cat <HOME>/.gemini/GEMINI.md`: a zero exit yields launcher exit 75 `reason=sandbox-unproven` with no agy spawn; an exit 71, or a missing `sandbox-exec`, yields 75 `reason=no-route` with no agy spawn; a non-zero exit with "Operation not permitted" proceeds. Check: suite through the `run` seam, three cases.
- **AGY-B7** The preamble precedes the caller's prompt, names the snapshot path, V, the suffix `.under-review` and the instruction to stay inside the snapshot; the caller's prompt follows byte-for-byte. Check: suite.
- **AGY-B8** After exit 0, 70 or 75 the snapshot directory and the profile file are gone; with `--keep-snapshot` the snapshot remains and stderr carries `[agy-run] snapshot=<path>`. Check: suite over each exit path.
- **AGY-B9** `worker` creates no snapshot, no profile, and no agent definition. Check: suite, filesystem before and after.

### Slice C — skill prose, admission, siblings

- **AGY-C1** `src/user/.claude/skills/delegating-to-agy/SKILL.md` exists with `name: delegating-to-agy`, the admission block of AGY-D12, and the description of 5.6; `content-lint` reports the skill staged for Claude within the model-invoked body cap. Check: `make content-lint` exit 0 and its staged listing.
- **AGY-C2** `scripts/agy_run.py` and `scripts/agy_run_test.py` exist and `content-tests` runs the suite to a clean pass; `references/model-routing.md` carries the AGY-D6 table and its capture date. Check: `make content-tests` exit 0.
- **AGY-C3** No staged skill description for any tool contains the string "Gemini CLI"; `delegating-to-codex` and `openrouter-claude-subagent` descriptions read as AGY-D11 states. Check: `grep -r "Gemini CLI"` over the staged skills namespace returns nothing.
- **AGY-C4** `choosing-a-delegate`'s route table has a row naming Gemini models, this skill, and OpenRouter as the fallback, placed before the OpenRouter row. Check: read of the deployed table.
- **AGY-C5** `evals/trigger-eval.json` holds at least six `should_trigger: true` queries (naming agy, Antigravity, or a Gemini model with a run to launch) and at least six `should_trigger: false` queries covering OpenRouter, Codex, agy sign-in, and a plain "review this PR". Check: file read.

### Slice D — recorded evidence on the work item

- **AGY-E1** An `admit-request` verdict for the skill is recorded on `agents-config-9k9.437`, and if it is `ADMIT-WITH-CHANGES` every named edit is in the same change. Check: `observed:` row citing the note.
- **AGY-E2** Two recorded runs of the deployed launcher on the same day and agy version: `worker` with the banana question returns the scripted answer; `lens` with the same question returns an answer that is not the scripted one. Check: `observed:` row citing the note with both outputs.
- **AGY-E3** One recorded `lens` run over a snapshot of this repository at a named head exits 0 with at least one `[agy-run] tool=` line and a non-empty response. Check: `observed:` row citing the note.

### Edge-case taxonomy

| Criteria | Inverse and boundary | Dependency failure | Repetition and idempotency |
| --- | --- | --- | --- |
| AGY-A1 to AGY-A3, AGY-A9 | Flag present versus absent, prompt text containing a flag name, `claude-` prefix, directory equal to versus beneath versus outside a trusted path | Settings file missing or unparseable | Same argv twice is byte-equal (AGY-A8) |
| AGY-A4 to AGY-A7 | Empty response, denied actions, non-SUCCESS, missing result | agy absent, agy killed by signal, stderr without a result | A second run after a timeout starts clean; no orphaned process group |
| AGY-B1 to AGY-B9 | Rename class at depth 0 and 2, file outside the class, uncommitted file, worker mode | Repository unreadable, revision unknown, `sandbox-exec` absent, canary reads the file | Snapshot removed on every exit; `--keep-snapshot` leaves one |
| AGY-C1 to AGY-C5 | Description containing the retired tool name | Gate unavailable | Re-staging changes nothing |
| AGY-E1 to AGY-E3 | Canary fires in worker, not in lens | agy version drift between the two runs is a fresh pair | Two runs, one day |

## 7. Coverage of the work item's acceptance lines

| Work-item line | Criteria |
| --- | --- |
| 1. admit-request verdict recorded | AGY-E1 |
| 2. launcher tests pin both modes: worker unwrapped; lens wrapped with the deny profile and JSON output; non-SUCCESS yields a distinct exit | AGY-A1, AGY-A9, AGY-B1, AGY-B5, AGY-A6; plan mode is replaced by the read-only agent (AGY-D4), an amendment section 8 asks the owner to ratify |
| 3. recorded canary runs | AGY-E2 |
| 4. the spec settles how a lens reads the repository and the launcher implements it | AGY-D5, AGY-B2 to AGY-B4, AGY-E3 |
| 5. no deployed description names "Gemini CLI"; choosing-a-delegate routes Gemini to this skill | AGY-C3, AGY-C4 |

## 8. Open questions for the owner

Ranked recommendation first in each.

1. **Plan mode in the lens argv.** The work item's second acceptance line names plan mode; this spec drops it because the read-only agent is the write barrier (F9) and plan mode only adds a plan artifact and an approval request (F10). (a) Amend the acceptance line to cite AGY-B1, which pins the agent and the profile instead. (b) Keep both: add `--mode plan` to AGY-B1 as belt and braces and accept the ceremony in every lens run.
2. **Denying global skills, agents and workflows to a lens.** `agents-config-9k9.436.1` will deploy the house skills under `~/.gemini/config/skills/`, whose descriptions then reach every lens catalogue. (a) Extend the profile to deny `~/.gemini/config/skills`, `agents`, `workflows` and `global_workflows` once that deploy lands, after one probe shows agy still starts when its scan of those directories gets EPERM. (b) Accept the leak as the Codex route does today (Codex lenses read deployed house skills under the Codex home on their own initiative).
3. **Worker permission bypass.** `--skip-permissions` is specified as a caller decision gated on the user's consent per run and was not probed here (the session's permission classifier refused the probe). (a) Keep it as specified. (b) Remove the flag and let workers rely on `permissions.allow` in agy's settings alone.
4. **Uncommitted working trees in lens mode.** The snapshot is a revision. (a) Callers commit to a temporary ref or run the round on a worktree head, which is how every review-panel round already runs. (b) Add a `--worktree` variant that copies the working tree minus `.git`, at the cost of a second snapshot path to test.

## 9. Out of scope

Review-panel routing rows and the failover ledger (`agents-config-9k9.17.29`); installer changes for agy (`agents-config-9k9.436`); admission-gate pricing for Gemini; agy sign-in and quota monitoring; a Linux sandbox for lens mode; the Claude and GPT-OSS models agy lists; reviewing uncommitted working trees (section 8, question 4).

## 10. Premises the probes contradicted

- "Seatbelt profiles cannot nest": an identical inner profile re-applies; only a differing inner profile fails with exit 71 (F7). The design consequence is unchanged.
- "The denied file still exists to stat-style checks": `stat` on it fails with EPERM under the profile; only the parent directory listing still shows the name (F6).
- "A non-SUCCESS status is the failure contract": a denied tool and a print-timeout both end in `status: SUCCESS` with an empty response and exit 0 (F2, F3).
- "No tool allowlist exists": a custom agent's `tools` list is one, and it holds in headless mode (F9).
- "agy 1.2.11": the machine runs 1.2.12; every observation here is against that version.
- The tracker's untested candidate "an empty cwd with `--add-dir`" was already refuted in its own later note; this spec did not re-test it.
- Frontmatter-less `.agents/rules/*.md` and sub-directory `AGENTS.md` files did not load in headless runs (F8), so the rename policy is defence in depth rather than the only barrier for those files; the root-level file is the one that loads.
- "Worker: plain agy with the real HOME": plain agy in headless mode cannot edit a file. Edits need `--mode accept-edits` and a trusted workspace together (F12); `--mode accept-edits` alone, in an untrusted directory, is denied like the default mode.
- "Plan mode is the closest thing to read-only": a custom agent with a read-only tool list is closer, cheaper, and holds without plan mode (F9, F10).

## 11. Continuations

Use `work promote` on each resulting feature before implementation; the child spec supplies the implementation manifest and dependencies. Slice D closes last and cannot close before the human runs the installer, because AGY-E2 and AGY-E3 run the deployed launcher.

- feat: delegating-to-agy launcher core and worker mode — AC: AGY-A1, AGY-A2, AGY-A3, AGY-A4, AGY-A5, AGY-A6, AGY-A7, AGY-A8, AGY-A9
- feat: delegating-to-agy lens mode — AC: AGY-B1, AGY-B2, AGY-B3, AGY-B4, AGY-B5, AGY-B6, AGY-B7, AGY-B8, AGY-B9
- feat: delegating-to-agy skill prose, admission and sibling routing — AC: AGY-C1, AGY-C2, AGY-C3, AGY-C4, AGY-C5
- feat: delegating-to-agy recorded evidence — AC: AGY-E1, AGY-E2, AGY-E3

## Evidence

All criteria describe future implementation; their evidence is open. The probe record in section 3 supports the decisions and establishes no criterion.

- AGY-A1 | open
- AGY-A2 | open
- AGY-A3 | open
- AGY-A4 | open
- AGY-A5 | open
- AGY-A6 | open
- AGY-A7 | open
- AGY-A8 | open
- AGY-A9 | open
- AGY-B1 | open
- AGY-B2 | open
- AGY-B3 | open
- AGY-B4 | open
- AGY-B5 | open
- AGY-B6 | open
- AGY-B7 | open
- AGY-B8 | open
- AGY-B9 | open
- AGY-C1 | open
- AGY-C2 | open
- AGY-C3 | open
- AGY-C4 | open
- AGY-C5 | open
- AGY-E1 | open
- AGY-E2 | open
- AGY-E3 | open
