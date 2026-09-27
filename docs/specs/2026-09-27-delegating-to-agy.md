# delegating-to-agy: Antigravity CLI as a fresh-context lens or a full worker

**Date:** 2026-09-27
**Status:** Child spec of `docs/specs/2026-07-21-harness-rework-way-forward.md` (D4 contract-only rule, D5 foreign eyes in review seats, D16 removal conditions). Draft for review; no attack or review is claimed for this document.
**Work item:** `agents-config-9k9.437`. Its five acceptance lines are restated here as AGY criteria (section 7 maps them; section 8 proposes new wording for line 2).
**Consumers:** `agents-config-9k9.17.29` (review-panel Gemini seats run on agy first, OpenRouter as fallback) consumes lens mode and the failure contract. `agents-config-9k9.436` (agy as an install target) and `agents-config-9k9.408` (per-seat routing pins) are siblings; this spec changes nothing they own.
**Quality contract:** `docs/specs/2026-09-18-acceptance-criteria-quality.md`. **Lifecycle:** `docs/specs/2026-09-18-acceptance-criteria-lifecycle.md`.

## 1. Problem statement

Antigravity CLI (`agy`) replaced Gemini CLI on this machine and bills against a Google AI Pro subscription. Today every Gemini-model dispatch pays OpenRouter rates and rides a transport that has died mid-stream in live rounds, while the subscription route sits unused. Two sibling skills exist for other vendors: `delegating-to-codex` (OpenAI, through the Codex plugin's agent) and `openrouter-claude-subagent` (a nested Claude harness pointed at OpenRouter). Both still exclude "Gemini CLI" in their descriptions, naming a tool that no longer exists, and `choosing-a-delegate` routes every non-OpenAI model to OpenRouter.

A Gemini run has two shapes with opposite needs. A **worker** is a first-class session: it implements or investigates in the user's checkout with the real `HOME`, and it reads every user and project instruction file, rule and skill agy supports, as Claude and Codex workers do. A **lens** is a read-only reviewer whose context is the embedded mandate, the criteria and the target. The governing rule for a lens: it may be instructed by what the project has already accepted, never by what is under review. The user-level `~/.gemini/GEMINI.md` is the house rulebook and stays out. A repository's own instruction files load when they are accepted and stay out when they are the change. agy has no flag, setting or environment variable that draws either line.

## 2. Scope

In scope: one skill, `delegating-to-agy`, with one launcher script that runs agy in worker mode or lens mode; the model table; the failure contract callers fail over on; the launch check that proves lens isolation; the diff a lens reads; timeouts and kill-by-pid; the edits to the three sibling skills; the admission case.

Out of scope: the review-panel routing that consumes lens mode (`agents-config-9k9.17.29`); deploying skills or rules where agy discovers them (`agents-config-9k9.436`); pricing Gemini in the admission gate; agy sign-in; reviewing uncommitted working trees in lens mode (section 10).

## 3. Facts established on 2026-09-27

Every claim in the tracker notes was treated as a hypothesis and re-tested against agy 1.2.12 (the notes were taken on 1.2.11; the machine auto-updated). Probes ran from scratch directories with `--print-timeout` on every run. F13 and F14 are the owner's runs, recorded on the work item; a session's permission policy forbids an agent from probing with a substituted `HOME`, so they were not re-run by an agent. F15 is the one probe that passed a permission bypass, because the bypass is what it tests. Each row states what the launcher design rests on.

| # | Observation | Consequence for the design |
| --- | --- | --- |
| F1 | `agy -p ... --output-format json` returns `{conversation_id, status, response, duration_seconds, num_turns, usage}` and, when a tool was auto-denied, `denied_actions: [{action, display_name}]`. `--output-format stream-json` emits one JSON object per line, each `{"event": <kind>, <kind>: {...}}`: an `init` event (`cwd`, `model`, `permission_mode`, the tool roster, and the agent when one was named), one `step_update` per agent response and per tool call (with `tool_name` and `tool_info.parameters`, and the tool's `output` once `DONE`), and a final `result` event holding the same object as json mode. | The launcher reads stream-json: the tool events are the read evidence the review-panel dispatch gate wants, and the `result` event is the outcome. |
| F2 | A tool that needs a permission headless mode cannot prompt for is auto-denied, and the run then ends with `status: SUCCESS`, an empty `response`, `denied_actions` filled, exit 0, and a `jetski: no output produced` notice on stderr. Seen for `RunCommand` (a shell command) and for `ViewFile` on a path outside the workspace, and again in the owner's temporary-home run without the tool-restricted agent (F13). | "Non-SUCCESS status" is not the failure contract. Empty response or any denied action is a failure the launcher must report on its own. |
| F3 | `--print-timeout 3s` on a long turn returns `status: SUCCESS`, empty `response`, zero usage, exit 0, and `[agy] print timeout after 3s with turn in progress; returning partial output` on stderr. | A timeout looks like success to a naive caller. The launcher owns the clock and reports timeouts itself. |
| F4 | An unknown `--model` returns `status: ERROR`, an `error` field, exit 1 and the same text on stderr. An invalid custom-agent tool name returns `status: ERROR`, exit 3, and an `AGY_ERROR: {"short_error", "status", "error_code", "code_kind", "retryable", "error_id"}` line on stderr. The changelog states model and agent API failures also exit 3 with an `AGY_ERROR` line. | Non-zero exit, non-SUCCESS status, or an `AGY_ERROR` line is the transport-failure class. Quota exhaustion is unobserved and lands in this class by construction. |
| F5 | `agy models` lists Gemini 3.6, 3.7 and 3.8 Flash at `-low`, `-medium`, `-high`, Gemini 3.1 Pro at `-low` and `-high`, two Claude ids and one GPT-OSS id, as full model ids. `--model gemini-3.8-flash-low --effort high` is refused: "conflicts with --effort=high". | Effort rides in the model id. The launcher never passes `--effort`. |
| F6 | With `HOME` real and a Seatbelt profile `(deny file-read* (literal "$HOME/.gemini/GEMINI.md"))`, agy starts, authenticates and answers. The banana canary scripted in that file (the deployed `AGENTS.local.md` tail) fires in an unwrapped run ("not anyone's business") and does not fire under the profile ("typically yellow"). `cat` and `stat` on the file under the profile fail with "Operation not permitted" (EPERM, not ENOENT); the parent directory still lists the name. | The banana rule is the behavioural check the recorded runs use (AGY-E2). A deny profile is the refuted alternative for lens isolation (AGY-D4): it is a deny list that needs a new line for every rule source agy adds, it cannot be applied from a shell that already carries a different profile (F7), and each launch needs a subprocess canary to prove it. An absent file (F13) needs none of that. |
| F7 | Nesting: an inner `sandbox-exec` whose profile equals the outer one succeeds; an inner profile that differs, wider or narrower, fails with `sandbox_apply: Operation not permitted`, exit 71. | A Seatbelt-wrapped process cannot run Codex, a sandboxed Claude, or agy `--sandbox` (F15). Workers stay unwrapped. Lens mode wraps nothing, so a caller whose own shell is sandboxed can still launch one. |
| F8 | A root-level `AGENTS.md` at the cwd loads in every run, trusted workspace or not (`trustedWorkspaces` in `~/.gemini/antigravity-cli/settings.json` gates nothing observed here). A sub-directory `AGENTS.md` did not load at start nor after the model read a file beside it. Frontmatter-less `.agents/rules/*.md` files, at the root and in a sub-directory, did not load. The customization guide bundled with agy nonetheless names `GEMINI.md`, `AGENTS.md` and `.agents/rules/*.md` as hierarchical rule sources, walked up from each touched file, and names `.agents`, `.agent`, `_agents` and `_agent` as customization roots holding `rules/`, `skills/`, `workflows/`, `agents/`, `plugins/`, `hooks.json` and `mcp_config.json`. | The rename class in the snapshot follows the documented sources, not only the observed ones, so it covers both. `--add-dir` from an empty cwd loads the added repository's root rules (tracker note, not re-tested) and stays rejected. |
| F9 | A workspace custom agent at `.agents/agents/<name>/agent.md` with `tools: [view_file, grep_search, find_by_name, list_dir]` is selected by `--agent <name>` in headless mode from an untrusted scratch directory. The run used only those four tools across 58 calls; `grep_search` and `find_by_name` work without any command permission, and no shell command was attempted. Asked to create a file, the agent reported it has no write or shell tool (agy adds only `manage_task`), and no file appeared, with or without `--mode plan`. In default mode a workspace file read needs no permission. | A read-only tool allowlist exists after all, as a custom agent. It is the lens's first write barrier, and it is why the lens never runs a shell: the swapped `HOME` (F13) changes what a shell would read, and no shell runs. |
| F10 | `--mode plan` reports `permission_mode: request-review` in the init event and writes its plan artifact under `<HOME>/.gemini/antigravity-cli/brain/`. A controlled A/B (same snapshot of `packages/installer/src` at main `be008439`, the `agy-lens` agent, one prompt needing a search then a file read, `gemini-3.8-flash-high`, two runs per arm) measured default mode at 113 s with 133k input tokens and 48 s with 61k, and plan mode at 60 s with 81k and 119 s with 136k. All four answers were correct, and no plan-mode run stalled on approval. Run-to-run variance exceeds any difference between the modes. A one-constant lookup on flash-high takes up to about two minutes in either mode. | Plan mode costs a lens nothing measurable and stays in the lens argv as a second write barrier beside the agent's tool list. Its plan artifact lands in the temporary `HOME` and is removed with it. The lens timeout default allows the two-minute lookup (AGY-D9). |
| F11 | The rules guide bundled with agy: 24,000-byte cap per rule file, a shared 20,000-token budget for always-on and global rules, `@[label](path)` includes. Global customizations live under `~/.gemini/config/` (`rules/`, `skills/`, `agents/`, `workflows/`); today that directory holds only `config.json`, `mcp_config.json` and `projects/`. | For a lens the whole `~/.gemini/config/` tree is absent from the temporary `HOME` (F13), so the house skills `agents-config-9k9.436.1` will deploy there stay out of every lens without a launcher change. |
| F12 | A headless file write is auto-denied in default mode everywhere, and under `--mode accept-edits` in an untrusted directory; under `--mode accept-edits` in a directory beneath a path listed in `trustedWorkspaces` of `~/.gemini/antigravity-cli/settings.json` the write succeeds. The trusted match is by ancestor path: the probe directory had its own `.git` and was not itself listed. | A worker edits only with `--mode accept-edits` from a trusted workspace; a worktree beneath a trusted repository path inherits the trust. A lens snapshot is untrusted by construction: the temporary `HOME` holds no settings file, so nothing is trusted. That is the third write barrier. |
| F13 | Owner's run, agy 1.2.12. With `HOME` pointed at a temporary directory holding an empty `.gemini/` directory and `Library/Keychains` symlinked to the real `~/Library/Keychains`, agy starts and answers with no browser challenge. The banana rule in the real `~/.gemini/GEMINI.md` does not fire (the answer was "Yellow"). A canary rule in the cwd's `AGENTS.md` still fires (`PLUM-7`). | The temporary `HOME` is the lens's user-level isolation, and it is an allow-list: the user rules file and `config/` are absent rather than denied. The Keychain link alone keeps sign-in headless. Project instruction files still load, which is what the governing rule wants for accepted ones. |
| F14 | Owner's run, agy 1.2.12: a `.geminiignore`, a `.gitignore` and an `.rgignore` naming `AGENTS.md` do not stop agy loading the cwd's `AGENTS.md`. `strings` over the agy 1.2.12 binary finds no `.geminiignore` at all; it does reference `.gitignore` and `.rgignore`, which govern its file-search tools, not rule discovery. | No ignore file substitutes for renaming. The rename in the snapshot is the only project-level mechanism. |
| F15 | `agy --sandbox --dangerously-skip-permissions -p ...` from an untrusted scratch repository under `/tmp` (`gemini-3.8-flash-low`): the init event reports `permission_mode: always-proceed`. The first `run_command` (`touch ./inside-437.txt`) returned `Operation not permitted`; the identical retry two seconds later returned `INSIDE_OK`, with no permission event between them. A `run_command` touching `/tmp/agy-437-outside.txt` and a `write_to_file` to `/tmp/agy-437-outside-write.txt` both succeeded, and all three files existed afterwards. agy's changelog describes the terminal sandbox as one the agent asks to bypass, and headless runs as honouring the `settings.json` sandbox policy. A second run targeting a file under the home directory was refused by this session's permission classifier. | The observed sequence fits the bypass flag auto-approving a sandbox escape and does not fit a confining sandbox, so the pair is unproven as confinement and the launcher ships no bypass flag (AGY-D3). `/tmp` is also writable under Codex's workspace-write sandbox, so the deciding probe targets the home directory (section 9). |
| F16 | agy's changelog, in a release before 1.2.12, adds slash-command and skill expansion to print mode (`-p "/my-skill review this diff"` applies the skill) with `--disable-slash-commands` to opt out; `agy --help` on 1.2.12 lists the flag as "Disable slash command and skill expansion in print mode". Read from the changelog and `--help`, not probed. | A lens prompt is never a command. The lens argv carries `--disable-slash-commands`, so text in a mandate cannot expand a workspace skill, including one that is under review. |

Claims the probes contradicted are collected in section 11.

## 4. Decisions

**AGY-D1 — Name and placement.** The skill is `delegating-to-agy` at `src/user/.claude/skills/delegating-to-agy/`. The name matches its siblings (`delegating-to-codex`) and the tool it launches. Placement follows the repository's capability-dependency rule, applied to the procedure. Lens mode exists to serve `review-panel` and is routed by `choosing-a-delegate`, both Claude-only skills. Its launch is proven only from Claude Code's shell: Codex's shell on macOS runs under its own Seatbelt profile, and whether a Keychain-linked temporary `HOME` signs in from inside it is untested. The refuted alternative is the shared tree: worker mode alone would work on every tool, but one artifact ships as one unit and follows its most demanding step, and a shared placement would advertise a lens step that three of four tools have not been shown to perform.

**AGY-D2 — One launcher, two modes, Python.** `scripts/agy_run.py` is a PEP 723 script (the convention `content-tests` runs) with `scripts/agy_run_test.py` beside it. Sub-commands `worker` and `lens` share argv parsing, the stream-json reader, the outcome classifier and the watchdog; they differ only in what they set up around agy. Python over Node: the launcher needs a tar extraction, a process group, a temporary home, and JSON line parsing, all standard library; the OpenRouter launcher is Node because it hosts a proxy, which this launcher does not. The refuted alternative is two scripts, which would duplicate the classifier and let the two modes' failure contracts drift apart.

**AGY-D3 — Worker launch contract.** `agy_run.py worker --model ID --timeout SECONDS -p PROMPT` spawns exactly `agy -p PROMPT --model ID --output-format stream-json --print-timeout <SECONDS>s --mode accept-edits` in the invoking directory, with the parent's environment untouched, `HOME` included. No `sandbox-exec`, no `--agent`, no `--add-dir`, no `--effort`, no `--sandbox`, no `--dangerously-skip-permissions`. The user's `~/.gemini/GEMINI.md`, the user's `~/.gemini/config/` customizations and the checkout's own rules, skills and hooks load, as Claude's and Codex's instruction files load for their workers. A headless worker edits files only under `--mode accept-edits` and only inside a trusted workspace (F12), so the launcher checks before spawning that the invoking directory is at or beneath a path in `trustedWorkspaces` of `~/.gemini/antigravity-cli/settings.json`, and exits 78 naming that file and the remedy when it is not; a worker whose every edit is silently denied returns an empty run at full cost (F2), and a preflight names the cause for nothing. Shell commands stay governed by the user's `permissions.allow` list in the same settings file; a command outside it is auto-denied and surfaces in the ledger. The launcher never wraps a worker (F7).

The launcher defines no permission bypass. `--dangerously-skip-permissions` is adopted only in combination with agy's own `--sandbox`, and only after a probe shows that the pair confines a worker to edits and commands inside the workspace, which is what Codex's workspace-write sandbox provides. The one probe run so far (F15) points the other way, and the deciding probe is section 9's open question. Until it passes, a caller who needs unattended commands widens `permissions.allow` in agy's settings. Refuted alternative: a bare `--dangerously-skip-permissions`; under it every action auto-proceeds, a sandbox denial included (F15), so a worker with it is confined by nothing.

**AGY-D4 — Lens launch contract.** `agy_run.py lens --repo PATH --base BASE [--rev REV] --model ID [--timeout SECONDS] [--keep-snapshot] -p PROMPT` builds a snapshot (AGY-D5), builds a temporary `HOME`, proves it (AGY-D8), then spawns `agy --agent agy-lens --mode plan --disable-slash-commands --model ID -p <preamble + PROMPT> --output-format stream-json --print-timeout <SECONDS>s` with the snapshot as cwd and the parent's environment with exactly one change: `HOME` set to the temporary home. The argv carries no `sandbox-exec`, no `--add-dir`, no `--effort`, no `--sandbox`, no `--dangerously-skip-permissions`.

The temporary `HOME` is a fresh directory outside the repository holding exactly an empty `.gemini/` directory and `Library/Keychains` symlinked to the real `~/Library/Keychains`. It is an allow-list. `GEMINI.md`, `config/rules`, `config/skills`, `config/agents`, `config/workflows` and `antigravity-cli/settings.json` are absent, so nothing user-level loads and nothing needs denying (F13, F11). The Keychain link is what keeps sign-in headless. A shell started under the swapped `HOME` would read different dotfiles and build a different `PATH`; the lens agent has no command tool (F9), so no shell runs and that side effect reaches nothing. The launcher removes the home on every exit path, signals included, and never keeps it.

Three write barriers stack: the agent's tool list (F9), plan mode (F10), and the snapshot being untrusted by construction (F12). Plan mode's cost was measured and is nil; its plan artifact lands in the temporary home. `--disable-slash-commands` keeps the mandate from expanding a workspace skill (F16). Refuted alternative: a Seatbelt deny profile over the real `HOME` (F6). It works, and it is a deny list: the house skills `agents-config-9k9.436.1` will deploy under `~/.gemini/config/skills/` would need a new deny line, as would every rule source agy adds; the profile cannot be applied from a shell that already carries a different one (F7); and each launch needs a subprocess canary to prove the denial. An absent file needs none of that.

**AGY-D5 — How a lens reads the repository under review.** The launcher extracts `git archive REV` of `--repo` into a fresh temporary directory outside the repository, runs `git init` in the snapshot so agy's walk to a repository root stops there, writes `.agents/agents/agy-lens/agent.md`, and writes the change diff (below). Snapshots are of a revision only. A caller reviewing uncommitted work commits it to a temporary ref or runs the round on a worktree head, which is how every review-panel round already runs.

Instruction files. Unchanged instruction files load normally and are not renamed: the project has accepted them, and the governing rule lets them instruct a lens. Only instruction files the change adds or modifies are renamed `<name>.under-review`; a deleted one is absent from the snapshot and appears only in the diff. An instruction file is any file whose basename is `AGENTS.md` or `GEMINI.md`, and any file with a path component equal to one of agy's customization roots `.agents`, `.agent`, `_agents` or `_agent` (F8). The change is `git diff --name-status --no-renames BASE REV`; a path with status `A`, `M` or `T` is under review. The lens reads a renamed file as an ordinary file, which keeps it reviewable, and nothing loads it as a rule, skill, workflow or agent.

Process files. `hooks.json` and `mcp_config.json` directly under a customization root launch processes rather than instruct. They are renamed whether or not the change touches them: a hook or an MCP server runs repository code with the user's Keychain and environment, and a lens launches nothing.

Diff channel. The snapshot has no history and the lens agent cannot run git, so without a diff a lens cannot see what changed. The launcher runs `git -C REPO diff --no-color --no-ext-diff --find-renames --unified=10 BASE REV` in the real repository and writes its output to `.review/change.diff` in the snapshot. Paths in the diff are the original paths. `--no-ext-diff` keeps a repository-configured diff driver from running. The preamble the launcher prepends to the prompt names the snapshot path, `BASE`, `REV`, the diff path, every rename as `original -> original.under-review`, the note that a deleted file appears only in the diff, and the instruction to stay inside the snapshot. The snapshot is deleted on every exit path unless `--keep-snapshot`.

Refuted alternatives: renaming every instruction file blinds the lens to the accepted rules that Codex's and OpenRouter's lenses read in the live worktree, and contradicts the governing rule; a regex deny on `AGENTS.md` reads blinds the lens to the files most often under review here; `--add-dir` from an empty cwd loads the added repository's root rules (F8); an ignore file changes nothing (F14); running in the real checkout loads the real rules and lets a tool write to it; a working-tree copy adds a second snapshot path to test for a case the review flow never produces.

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
| `75` | The route did not serve the run: agy exit non-zero, non-SUCCESS status, an `AGY_ERROR` line, `agy` not on PATH, timeout (AGY-D9), or the temporary home failed its check (AGY-D8) | Fail over to the next route or model, quoting the stderr reason | `transport-error` |
| `78` | The launcher refused the invocation: missing flags, `--effort`, a `claude-` model, a permission bypass or `--sandbox` flag, a worker directory outside every trusted workspace, an unreadable repository, revision or base, a `.review` path in the archived revision, or a rename target still present | Fix the invocation; do not fail over | — |

Quota exhaustion is unobserved; whatever agy reports, it is either a non-zero exit, a non-SUCCESS status, or an empty response, and all three map to a code the consumer fails over on. The stderr line `[agy-run] reason=<word>` names the sub-cause (`error`, `no-route`, `timeout`, `home-unproven`, `empty`, `denied`, `untrusted-workspace`).

**AGY-D8 — Launch check.** Before spawning agy in lens mode the launcher checks the temporary home it built: `<home>/.gemini` is a directory with no entries; `<home>/Library/Keychains` is a symlink whose target is the real `~/Library/Keychains`, and that target is a directory; `<home>` is neither the real home nor inside `--repo`; and the child environment's `HOME` equals `<home>`. Any failed condition means the lens could load a user-level file or could not sign in: exit 75, `reason=home-unproven`, no agy spawn. A real `~/Library/Keychains` that does not exist means the route cannot sign in headlessly on this machine: exit 75, `reason=no-route`. The check proves the isolation mechanism, not the model's behaviour, so the behavioural check (the banana rule fires for a worker and not for a lens) is a recorded evidence run on the work item rather than a per-launch cost. Refuted alternatives: a `sandbox-exec ... cat` canary belongs to the deny profile and has nothing to prove against an absent file; a model-answered canary per launch spends a model turn to learn what a directory listing learns for free.

**AGY-D9 — Timeouts and kill-by-pid.** `--timeout SECONDS` is required for a worker and defaults to 600 for a lens; a one-constant lookup on flash-high takes up to about two minutes (F10), so a lens default below that would time out routine work. The launcher passes `--print-timeout <SECONDS>s` to agy and arms its own watchdog at `SECONDS + 30`. agy runs in a new session (process group led by the agy pid); the launcher prints `[agy-run] pid=<pid>` at spawn so a runner can kill the group by pid. On the watchdog firing it sends `SIGTERM` to the group, `SIGKILL` ten seconds later, and exits 75 `reason=timeout`. A run that ends by agy's own print-timeout notice (F3) is also 75 `reason=timeout`, so a caller never mistakes a partial run for success. Refuted alternative: `timeout N agy ...` alone, which the OpenRouter launcher's history shows survives `SIGTERM` and leaves the run orphaned.

**AGY-D10 — The ledger on stderr.** From the stream: `[agy-run] pid=`, one `[agy-run] tool=<tool_name> <first parameter>` per tool `step_update` entering `ACTIVE`, `[agy-run] agent=<name> permission_mode=<mode>` from `init` (`agent=` only when the event carries one; a default-agent run omits it), and a final `[agy-run] status=<status> turns=<n> tokens=<total> denied=<names>`. agy's own stderr passes through unchanged so an `AGY_ERROR` line and the jetski notice survive for the round's records. The `tool=` count is what a no-read check reads (`agents-config-9k9.408` names that check for the other transports).

**AGY-D11 — Sibling edits in the same change.** `choosing-a-delegate`'s route table gains a row before the OpenRouter row: Gemini models run through this skill, on the subscription, and OpenRouter is the fallback once quota is spent. `delegating-to-codex`'s description drops "and not for OpenRouter or Gemini CLI" in favour of "and not for OpenRouter or agy". `openrouter-claude-subagent`'s description drops "Codex or Gemini CLI" in favour of "Codex, and not the first route for a Gemini model, which is the agy skill; this transport is its fallback", and keeps Gemini in its hosted-model list because the fallback still names those ids. No other deployed prose changes; `src/user/.gemini/` and the shared README name Gemini CLI as an install target and belong to `agents-config-9k9.436`.

**AGY-D12 — Admission case.** The record the front matter carries, in the shape `admit-request` evaluates. It states one worth field: this is a repeatable procedure, so the assistive case is the honest one.

```yaml
admission:
  provides: An agy run in one of two verified shapes: a worker in the current checkout that reads the user's and the repository's instruction files like a Claude or Codex worker does, or a fresh-context lens over a snapshot of a revision, run under a temporary home that holds only a Keychain link so no user-level rule or skill loads, with the change's own instruction files renamed so nothing under review instructs the reviewer, and the change's diff beside them. Invoking it produces the launcher command, its exit code contract, and the model id for the task profile.
  cost: agy must be installed and signed in, and every run bills the Google AI Pro subscription; lens mode needs macOS for the Keychain link and leaves a snapshot of the reviewed revision and a temporary home on disk for the run's duration; the model table needs a refresh whenever agy's model list changes.
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
agy_run.py worker --model ID --timeout SECONDS -p PROMPT
agy_run.py lens   --repo PATH --base BASE [--rev REV] --model ID [--timeout SECONDS] [--keep-snapshot] -p PROMPT
```

`REV` defaults to `HEAD`; `REV` and `BASE` accept any commit-ish `git diff` accepts, and `REV` must also be one `git archive` accepts. `PROMPT` is the last argument and is never parsed for flags.

### 5.3 Python signatures

```python
EXIT_OK = 0
EXIT_UNUSABLE = 70
EXIT_ROUTE = 75
EXIT_CONFIG = 78

LENS_AGENT = "agy-lens"
LENS_TOOLS = ("view_file", "grep_search", "find_by_name", "list_dir")
LENS_TIMEOUT_DEFAULT_S = 600
RENAME_SUFFIX = ".under-review"
CUSTOMIZATION_ROOTS = (".agents", ".agent", "_agents", "_agent")
PROCESS_FILES = ("hooks.json", "mcp_config.json")
DIFF_PATH = PurePosixPath(".review/change.diff")
DIFF_CONTEXT_LINES = 10
WATCHDOG_GRACE_S = 30
KILL_GRACE_S = 10
AGY_SETTINGS = Path("~/.gemini/antigravity-cli/settings.json")

class Outcome(NamedTuple):
    exit_code: int
    reason: str | None       # error | no-route | timeout | home-unproven | empty | denied | untrusted-workspace | None
    response: str
    ledger: list[str]

def parse_args(argv: list[str]) -> argparse.Namespace: ...
def refuse_model(model: str) -> str | None: ...
def trusted_workspace(cwd: Path, settings: Path) -> bool: ...
def build_worker_argv(model: str, timeout_s: int, prompt: str) -> list[str]: ...
def build_lens_argv(model: str, timeout_s: int, prompt: str) -> list[str]: ...
def make_lens_home(parent: Path, real_home: Path) -> Path: ...
def lens_env(parent_env: Mapping[str, str], home: Path) -> dict[str, str]: ...
def prove_home(home: Path, real_home: Path, repo: Path, env: Mapping[str, str]) -> Outcome | None: ...
def lens_agent_definition() -> str: ...
def lens_preamble(repo: Path, base: str, rev: str, snapshot: Path, renamed: list[tuple[PurePosixPath, PurePosixPath]]) -> str: ...
def changed_paths(repo: Path, base: str, rev: str, run: Callable[..., subprocess.CompletedProcess]) -> list[tuple[str, PurePosixPath]]: ...
def neutralized_names(archived: Iterable[PurePosixPath], changed: Iterable[tuple[str, PurePosixPath]]) -> list[tuple[PurePosixPath, PurePosixPath]]: ...
def change_diff(repo: Path, base: str, rev: str, run: Callable[..., subprocess.CompletedProcess]) -> bytes: ...
def make_snapshot(repo: Path, base: str, rev: str, parent: Path, run: Callable[..., subprocess.CompletedProcess]) -> Path: ...
def classify(exit_code: int, events: list[dict], stderr_text: str, timed_out: bool) -> Outcome: ...
def run_agy(argv: list[str], cwd: Path, env: Mapping[str, str], timeout_s: int, spawn: Callable[..., subprocess.Popen], clock: Callable[[], float]) -> Outcome: ...
def main(argv: list[str]) -> int: ...
```

`spawn`, `run` and `clock` are seams so the suite runs against a fake `agy` (a script that replays canned stream-json lines, sleeps, or exits with a chosen code) and a fake real home, and never against the real ones.

### 5.4 The lens agent definition

```markdown
---
name: agy-lens
description: Read-only review lens. Reads, searches and lists files in this snapshot and nothing else.
tools: [view_file, grep_search, find_by_name, list_dir]
subagent: false
---

# Lens

You review a snapshot of a repository at one revision. You can read, search and list files in it and nothing else. The change under review is in .review/change.diff, a unified diff against the base revision, with original paths. Instruction files the change adds or modifies were renamed with the suffix .under-review; read them as ordinary files and cite them by their original names. Answer the request directly. Do not write a plan document.
```

### 5.5 The temporary home

```
<tmp>/agy-lens-home-<random>/
├── .gemini/                                   # empty directory
└── Library/Keychains -> <real HOME>/Library/Keychains
```

Nothing else is created there by the launcher. What agy writes there during the run (`.gemini/antigravity-cli/`, the plan artifact) is removed with the directory.

### 5.6 SKILL.md description

> Use when a run is being launched on Antigravity CLI (agy), Google's runtime for Gemini models: as a full worker in the current checkout, or as a fresh-context review lens over a snapshot whose instruction files stay out. Apply when the user names agy, Antigravity or a Gemini model, or when another skill sends a Gemini dispatch here. Not for deciding whether to leave Claude, not for agy setup or sign-in, and not for OpenRouter, which is this route's fallback once the subscription quota is spent.

## 6. Slices and acceptance criteria

Each criterion is one observable obligation with its check named. Suite criteria run under `content-tests` through the seams in 5.3; staging criteria run under `content-lint`; recorded criteria are `observed:` rows on the work item.

### Slice A — launcher core and worker mode

- **AGY-A1** `worker --model M --timeout N -p P` spawns argv `["agy", "-p", P, "--model", M, "--output-format", "stream-json", "--print-timeout", "Ns", "--mode", "accept-edits"]` with cwd equal to the invoking directory and an environment equal to the parent's (`HOME` included); the argv contains no `sandbox-exec`, `--agent`, `--add-dir`, `--effort`, `--sandbox`, `--dangerously-skip-permissions` or `--disable-slash-commands`. Check: suite, fake spawn records argv, cwd and env.
- **AGY-A2** `--skip-permissions`, `--dangerously-skip-permissions` or `--sandbox` anywhere in the launcher's argv, in either mode, exits 78 before anything spawns, with stderr naming the flag. Check: suite, fake spawn records zero calls.
- **AGY-A3** Each of the following exits 78 before anything spawns, with stderr naming the offending flag: a missing `--model` or prompt in either mode; a missing `--timeout` on `worker`; `--effort` anywhere in the launcher's argv; a `--model` beginning `claude-`. A prompt whose text contains `--effort` is not a flag. Check: suite, fake spawn records zero calls.
- **AGY-A4** A `result` event with `status: SUCCESS`, a non-empty `response` and no `denied_actions` exits 0; stdout is exactly the response text; stderr holds `[agy-run] pid=<pid>`, one `[agy-run] tool=<name>` line per tool `step_update` that entered `ACTIVE`, and one final `[agy-run] status=SUCCESS` line. Check: suite over a canned stream with three tool steps.
- **AGY-A5** A `result` with `status: SUCCESS` and an empty `response`, or with a non-empty `denied_actions`, exits 70 with `[agy-run] reason=empty` or `reason=denied` naming each denied action's `display_name`, and stdout empty. Check: suite, both inverses of AGY-A4.
- **AGY-A6** agy exiting non-zero, a `result` whose `status` is not `SUCCESS`, or an `AGY_ERROR:` line on agy's stderr exits 75 with `reason=error`, agy's error text present on the launcher's stderr verbatim, and stdout empty. An `agy` binary absent from PATH exits 75 with `reason=no-route`. Check: suite, one case per trigger.
- **AGY-A7** No `result` event within `N + 30` seconds: the launcher sends `SIGTERM` to the agy process group, `SIGKILL` ten seconds later if it is still alive, and exits 75 with `reason=timeout`; a `result` whose stderr carries agy's `print timeout` notice and whose `response` is empty also exits 75 `reason=timeout`. Check: suite with a fake agy that sleeps past a one-second timeout and ignores `SIGTERM`; the group is gone afterwards.
- **AGY-A8** Repeated invocation with identical arguments produces identical argv and identical classification. Check: suite.
- **AGY-A9** `worker` spawns only when the invoking directory equals or lies beneath a path listed in `trustedWorkspaces` of the settings file at `AGY_SETTINGS`; a directory outside every listed path, a settings file that is missing or unparseable, or a list that is absent, exits 78 with `reason=untrusted-workspace`, names the settings path, and spawns nothing. `lens` performs no such check. Check: suite with a temporary settings file, four cases.

### Slice B — lens mode

- **AGY-B1** `lens --repo R --base B --rev V --model M --timeout N -p P` spawns argv `["agy", "--agent", "agy-lens", "--mode", "plan", "--disable-slash-commands", "--model", M, "-p", <preamble + P>, "--output-format", "stream-json", "--print-timeout", "Ns"]` with cwd equal to a directory that is not under R, and an environment equal to the parent's with exactly one difference, `HOME` set to the temporary home; the argv contains no `sandbox-exec`, `--add-dir`, `--effort`, `--sandbox` or `--dangerously-skip-permissions`. Check: suite, fake spawn records argv, cwd and env.
- **AGY-B2** The snapshot contains every path `git archive V` of R emits and no path of R's working tree that V lacks; every path `neutralized_names` returns for (archive, `changed_paths(B, V)`) exists as `<name>.under-review` with identical bytes and does not exist under its original name; every other archived path exists unchanged under its original name; `.git` exists as a freshly initialised repository; `.agents/agents/agy-lens/agent.md` equals the definition in 5.4. Check: suite over a fixture repository with two commits, an uncommitted extra file, a changed and an unchanged `AGENTS.md` at two depths, an `AGENTS.md` deleted between B and V, a changed and an unchanged `.agents/rules/*.md`, and an unchanged `.agents/hooks.json`.
- **AGY-B3** `neutralized_names` returns exactly: every changed path with status `A`, `M` or `T` whose basename is `AGENTS.md` or `GEMINI.md` or whose path has a component in `CUSTOMIZATION_ROOTS`; plus every archived `hooks.json` and `mcp_config.json` directly under a component in `CUSTOMIZATION_ROOTS`, changed or not. It returns nothing for an unchanged `AGENTS.md`, a path with status `D`, or a changed `CLAUDE.md`, `README.md`, `AGENTS.md.template`, or `rules/x.md` whose parent is not one of the four root names. Check: suite, pure function.
- **AGY-B4** If any path AGY-B3 names still exists under its original name after the rename step, the launcher exits 78 before spawning and names the path. Check: suite with a fixture that recreates the file through the seam.
- **AGY-B5** The temporary home holds exactly two entries when agy is spawned: `.gemini`, an empty directory, and `Library/Keychains`, a symlink to `<real HOME>/Library/Keychains`; the home is outside R and is not the real home. Check: suite with a fake real home, filesystem listing at the spawn seam.
- **AGY-B6** Before spawning, `prove_home` yields launcher exit 75 `reason=home-unproven` and no agy spawn when `.gemini` has an entry, when `Library/Keychains` is missing or resolves elsewhere, or when the child environment's `HOME` differs from the home; it yields 75 `reason=no-route` and no spawn when `<real HOME>/Library/Keychains` does not exist; a sound home proceeds to the spawn. Check: suite with a fake real home, five refusing cases and the sound one.
- **AGY-B7** The preamble precedes the caller's prompt and names the snapshot path, B, V, `.review/change.diff`, every rename as `<original> -> <original>.under-review`, the note that a deleted file appears only in the diff, and the instruction to stay inside the snapshot; the caller's prompt follows byte-for-byte. Check: suite.
- **AGY-B8** After exit 0, 70 or 75, and after `SIGTERM` or `SIGINT` delivered to the launcher while agy runs, the snapshot directory and the temporary home are gone and the agy process group is gone; with `--keep-snapshot` the snapshot remains, the home is still gone, and stderr carries `[agy-run] snapshot=<path>`. Check: suite over each exit path and both signals, with a fake agy that sleeps.
- **AGY-B9** `worker` creates no snapshot, no temporary home, no agent definition and no diff, and its child environment's `HOME` equals the parent's. Check: suite, filesystem before and after, fake spawn env.
- **AGY-B10** `.review/change.diff` in the snapshot equals byte-for-byte the stdout of `["git", "-C", R, "diff", "--no-color", "--no-ext-diff", "--find-renames", "--unified=10", B, V]` through the `run` seam; B equal to V yields an empty file, zero renames and a spawn; a B git does not resolve, or a `.review` path present in the archive of V, exits 78 before spawning and names the cause. Check: suite, fixture repository, four cases.
- **AGY-B11** `lens` without `--timeout` passes `--print-timeout 600s` and arms the watchdog at 630 s; with `--timeout N` it passes `Ns` and arms at N + 30. Check: suite, fake spawn and fake clock.

### Slice C — skill prose, admission, siblings

- **AGY-C1** `src/user/.claude/skills/delegating-to-agy/SKILL.md` exists with `name: delegating-to-agy`, the admission block of AGY-D12, and the description of 5.6; `content-lint` reports the skill staged for Claude within the model-invoked body cap. Check: `make content-lint` exit 0 and its staged listing.
- **AGY-C2** `scripts/agy_run.py` and `scripts/agy_run_test.py` exist and `content-tests` runs the suite to a clean pass; `references/model-routing.md` carries the AGY-D6 table and its capture date. Check: `make content-tests` exit 0.
- **AGY-C3** No staged skill description for any tool contains the string "Gemini CLI"; `delegating-to-codex` and `openrouter-claude-subagent` descriptions read as AGY-D11 states. Check: `grep -r "Gemini CLI"` over the staged skills namespace returns nothing.
- **AGY-C4** `choosing-a-delegate`'s route table has a row naming Gemini models, this skill, and OpenRouter as the fallback, placed before the OpenRouter row. Check: read of the deployed table.
- **AGY-C5** `evals/trigger-eval.json` holds at least six `should_trigger: true` queries (naming agy, Antigravity, or a Gemini model with a run to launch) and at least six `should_trigger: false` queries covering OpenRouter, Codex, agy sign-in, and a plain "review this PR". Check: file read.

### Slice D — recorded evidence on the work item

- **AGY-E1** An `admit-request` verdict for the skill is recorded on `agents-config-9k9.437`, and if it is `ADMIT-WITH-CHANGES` every named edit is in the same change. Check: `observed:` row citing the note.
- **AGY-E2** Two recorded runs of the deployed launcher on the same day and agy version: `worker` with the banana question returns the scripted answer; `lens` with the same question returns an answer that is not the scripted one. Check: `observed:` row citing the note with both outputs.
- **AGY-E3** One recorded `lens` run over a snapshot of this repository at a named head against a named base exits 0 with at least one `[agy-run] tool=` line and a non-empty response. Check: `observed:` row citing the note.

### Edge-case taxonomy

| Criteria | Inverse and boundary | Dependency failure | Repetition and idempotency |
| --- | --- | --- | --- |
| AGY-A1 to AGY-A3, AGY-A9 | Flag present versus absent, prompt text containing a flag name, `claude-` prefix, bypass or sandbox flag in either mode, directory equal to versus beneath versus outside a trusted path | Settings file missing or unparseable | Same argv twice is byte-equal (AGY-A8) |
| AGY-A4 to AGY-A7 | Empty response, denied actions, non-SUCCESS, missing result | agy absent, agy killed by signal, stderr without a result | A second run after a timeout starts clean; no orphaned process group |
| AGY-B1 to AGY-B11 | Changed versus unchanged instruction file at depth 0 and 2, deleted file, process file unchanged, file outside the class, uncommitted file, base equal to rev, worker mode, timeout absent versus given | Repository unreadable, revision or base unknown, real Keychains absent, home populated, `.review` collision | Snapshot and home removed on every exit and signal; `--keep-snapshot` leaves one snapshot and no home |
| AGY-C1 to AGY-C5 | Description containing the retired tool name | Gate unavailable | Re-staging changes nothing |
| AGY-E1 to AGY-E3 | Canary fires in worker, not in lens | agy version drift between the two runs is a fresh pair | Two runs, one day |

## 7. Coverage of the work item's acceptance lines

| Work-item line | Criteria |
| --- | --- |
| 1. admit-request verdict recorded | AGY-E1 |
| 2. launcher tests pin both modes: worker unwrapped; lens wrapped with the deny profile and JSON output; non-SUCCESS yields a distinct exit | AGY-A1, AGY-A2, AGY-A9 (worker); AGY-B1, AGY-B5, AGY-B6, AGY-B10 (lens); AGY-A5, AGY-A6, AGY-A7 (distinct exits). The line's wording names a deny profile this design replaces; section 8 proposes the amendment |
| 3. recorded canary runs | AGY-E2 |
| 4. the spec settles how a lens reads the repository and the launcher implements it | AGY-D5, AGY-B2 to AGY-B4, AGY-B7, AGY-B10, AGY-E3 |
| 5. no deployed description names "Gemini CLI"; choosing-a-delegate routes Gemini to this skill | AGY-C3, AGY-C4 |

## 8. Proposed wording for the work item's acceptance line 2

The item's line 2 reads: "Launcher tests pin both modes: the worker argv carries no sandbox wrapper; the lens argv carries the sandbox profile denying the user rules file, plan mode and JSON output; a non-SUCCESS status yields a distinct exit the caller can fail over on." It names the deny profile this design replaces, and F2 shows a non-SUCCESS status is not the whole failure signal. Proposed replacement, for the orchestrator to set through `work acceptance set --why`:

> 2. Launcher tests pin both modes: the worker argv carries no sandbox wrapper, no permission bypass and the parent's own HOME; the lens argv carries the read-only agent, plan mode and stream-json output, runs under a temporary HOME holding only an empty `.gemini/` and a link to the real Keychains, and reads a snapshot of the reviewed revision that carries the change's diff and renames only the change's own instruction files; an unusable run (empty response or denied action), a route failure (non-SUCCESS status, non-zero exit, timeout, unproven home) and a refused invocation each yield a distinct exit the caller can act on.

Lines 1, 3, 4 and 5 need no change: the banana runs of line 3 are AGY-E2 as written, and line 4 is what AGY-D5 settles.

## 9. Open question for the owner

One remains. **Worker permission bypass with `--sandbox`.** AGY-D3 admits `--dangerously-skip-permissions` only paired with agy's `--sandbox`, and only once a probe shows the pair confines a worker to edits and commands inside the workspace, as Codex's workspace-write sandbox does. The probe run here (F15) shows the pair auto-proceeding past a sandbox denial and writing under `/tmp`; `/tmp` is also writable under Codex's sandbox, so that run does not decide the question, and the deciding run was refused by the session's permission classifier. The deciding probe: from an untrusted scratch repository, `agy --sandbox --dangerously-skip-permissions -p "<touch a file under the home directory with the shell tool, then create one there with the file-writing tool>"`. If both writes are denied and no retry succeeds, the pair confines comparably, and the launcher may add a worker flag that forwards the two agy flags together, with AGY-A2 amended to admit that pair and to keep refusing either flag alone. If either write succeeds, the flag stays out, and `permissions.allow` in agy's settings remains the only route to unattended commands. The owner runs the probe.

## 10. Out of scope

Review-panel routing rows and the failover ledger (`agents-config-9k9.17.29`); installer changes for agy (`agents-config-9k9.436`); admission-gate pricing for Gemini; agy sign-in and quota monitoring; a Linux lens mode (the Keychain link is macOS); the Claude and GPT-OSS models agy lists; reviewing uncommitted working trees (AGY-D5 snapshots a revision only).

## 11. Premises the probes contradicted

- "Seatbelt profiles cannot nest": an identical inner profile re-applies; only a differing inner profile fails with exit 71 (F7). The design consequence is unchanged.
- "Substituting HOME forces a browser login or strips the login-shell PATH agy builds" (the work item's description): a temporary home whose only content is a Keychain link signs in headlessly (F13), and the PATH a swapped home builds reaches nothing in a lens, whose agent has no command tool (F9).
- "A non-SUCCESS status is the failure contract": a denied tool and a print-timeout both end in `status: SUCCESS` with an empty response and exit 0 (F2, F3).
- "No tool allowlist exists": a custom agent's `tools` list is one, and it holds in headless mode (F9).
- "Plan mode adds ceremony a lens does not need" (the draft's F10, which compared a 171 s run against a 7 s run of different requests): the controlled A/B shows no measurable cost and no approval stall (F10). Plan mode stays.
- "An ignore file could keep AGENTS.md out of a lens": `.geminiignore`, `.gitignore` and `.rgignore` change nothing, and the binary does not know `.geminiignore` (F14).
- "`--sandbox` with the bypass flag might confine a worker comparably to Codex": the one run so far shows the pair proceeding past a sandbox denial (F15); the pair is unproven and the deciding probe is section 9's question.
- "agy 1.2.11": the machine runs 1.2.12; every observation here is against that version.
- The tracker's untested candidate "an empty cwd with `--add-dir`" was already refuted in its own later note; this spec did not re-test it.
- Frontmatter-less `.agents/rules/*.md` and sub-directory `AGENTS.md` files did not load in headless runs (F8), so renaming a changed one is defence in depth rather than the only barrier for those files; the root-level file is the one that loads.
- "Worker: plain agy with the real HOME": plain agy in headless mode cannot edit a file. Edits need `--mode accept-edits` and a trusted workspace together (F12); `--mode accept-edits` alone, in an untrusted directory, is denied like the default mode.

## 12. Continuations

Use `work promote` on each resulting feature before implementation; the child spec supplies the implementation manifest and dependencies. Slice D closes last and cannot close before the human runs the installer, because AGY-E2 and AGY-E3 run the deployed launcher.

- feat: delegating-to-agy launcher core and worker mode — AC: AGY-A1, AGY-A2, AGY-A3, AGY-A4, AGY-A5, AGY-A6, AGY-A7, AGY-A8, AGY-A9
- feat: delegating-to-agy lens mode — AC: AGY-B1, AGY-B2, AGY-B3, AGY-B4, AGY-B5, AGY-B6, AGY-B7, AGY-B8, AGY-B9, AGY-B10, AGY-B11
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
- AGY-B10 | open
- AGY-B11 | open
- AGY-C1 | open
- AGY-C2 | open
- AGY-C3 | open
- AGY-C4 | open
- AGY-C5 | open
- AGY-E1 | open
- AGY-E2 | open
- AGY-E3 | open
