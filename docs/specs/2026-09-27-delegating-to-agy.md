# delegating-to-agy: Antigravity CLI as a fresh-context lens or a full worker

**Date:** 2026-09-27
**Status:** Child spec of `docs/specs/2026-07-21-harness-rework-way-forward.md` (D4 contract-only rule, D5 foreign eyes in review seats, D16 removal conditions). Draft for review; no attack or review is claimed for this document.
**Work item:** `agents-config-9k9.437`. Its five acceptance lines are restated here as AGY criteria (section 7 maps them).
**Consumers:** `agents-config-9k9.17.29` (review-panel Gemini seats run on agy first, OpenRouter as fallback) consumes lens mode and the failure contract. `agents-config-9k9.436` (agy as an install target) and `agents-config-9k9.408` (per-seat routing pins) are siblings; this spec changes nothing they own.
**Quality contract:** `docs/specs/2026-09-18-acceptance-criteria-quality.md`. **Lifecycle:** `docs/specs/2026-09-18-acceptance-criteria-lifecycle.md`.

## 1. Problem statement

Antigravity CLI (`agy`) replaced Gemini CLI on this machine and bills against a Google AI Pro subscription. Today every Gemini-model dispatch pays OpenRouter rates and rides a transport that has died mid-stream in live rounds, while the subscription route sits unused. Two sibling skills exist for other vendors: `delegating-to-codex` (OpenAI, through the Codex plugin's agent) and `openrouter-claude-subagent` (a nested Claude harness pointed at OpenRouter). Both still exclude "Gemini CLI" in their descriptions, naming a tool that no longer exists, and `choosing-a-delegate` routes every non-OpenAI model to OpenRouter.

A Gemini run has two shapes with opposite needs. A **worker** is a first-class session: it implements or investigates in the user's checkout with the real `HOME`, and it reads every user and project instruction file, rule and skill agy supports, as Claude and Codex workers do. A **lens** is a read-only reviewer whose context is the embedded mandate, the criteria and the target. The governing rule for a lens: it may be instructed by what the project has already accepted, never by what is under review. The user-level `~/.gemini/GEMINI.md` is the house rulebook and stays out. A repository's own instruction files load when they are accepted and stay out when they are the change. agy has no flag, setting or environment variable that draws either line.

## 2. Scope

In scope: one skill, `delegating-to-agy`, with one launcher script that runs agy in worker mode or lens mode; the model table; the failure contract callers fail over on; the launch check that proves lens isolation; the diff a lens reads; timeouts and kill-by-pid; the edits to the three sibling skills; the admission case.

Out of scope: the review-panel routing that consumes lens mode (`agents-config-9k9.17.29`); deploying skills or rules where agy discovers them (`agents-config-9k9.436`); pricing Gemini in the admission gate; agy sign-in; reviewing uncommitted working trees in lens mode (section 9).

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
| F15 | `agy --sandbox --dangerously-skip-permissions -p ...` from an untrusted scratch repository under `/tmp` (`gemini-3.8-flash-low`): the init event reports `permission_mode: always-proceed`. The first `run_command` (`touch ./inside-437.txt`) returned `Operation not permitted`; the identical retry two seconds later returned `INSIDE_OK`, with no permission event between them. A `run_command` touching `/tmp/agy-437-outside.txt` and a `write_to_file` to `/tmp/agy-437-outside-write.txt` both succeeded, and all three files existed afterwards. agy's changelog describes the terminal sandbox as one the agent asks to bypass, and headless runs as honouring the `settings.json` sandbox policy. A second run targeting a file under the home directory was refused by this session's permission classifier. | The observed sequence fits the bypass flag auto-approving a sandbox escape and does not fit a confining sandbox, so the pair is unproven as confinement and the launcher ships no bypass flag (AGY-D3). `/tmp` is also writable under Codex's workspace-write sandbox, so the deciding probe targets the home directory (section 8). |
| F16 | agy's changelog, in a release before 1.2.12, adds slash-command and skill expansion to print mode (`-p "/my-skill review this diff"` applies the skill) with `--disable-slash-commands` to opt out. Probed on 1.2.12: an argv carrying both `--mode plan` and `--disable-slash-commands` prints `warning: --mode plan has no effect while slash command expansion is disabled.` on stderr, and its `init` event still reports `permission_mode: request-review`, the same value plan mode alone reports. Plan mode alone, plan mode with `--agent agy-lens`, and plan mode with `--output-format json` print no warning. | The two flags conflict, and the stream does not reveal the loss: an argv with both passes every check that reads the `init` event while plan mode is off. Plan mode is the barrier F10 measured, so the lens argv omits `--disable-slash-commands` and the launcher refuses to build an argv carrying both (AGY-B1). What a mandate could expand is bounded by what the lens can reach instead: the user-level skills directory is absent from the temporary home (F11), and a workspace skill the change adds or modifies is renamed in the snapshot (AGY-D5), so only an accepted skill can expand. |

Claims the probes contradicted are collected in section 10.

## 4. Decisions

**AGY-D1 — Name and placement.** The skill is `delegating-to-agy` at `src/user/.claude/skills/delegating-to-agy/`. The name matches its siblings (`delegating-to-codex`) and the tool it launches. Placement follows the repository's capability-dependency rule, applied to the procedure. Lens mode exists to serve `review-panel` and is routed by `choosing-a-delegate`, both Claude-only skills. Its launch is proven only from Claude Code's shell: Codex's shell on macOS runs under its own Seatbelt profile, and whether a Keychain-linked temporary `HOME` signs in from inside it is untested. The refuted alternative is the shared tree: worker mode alone would work on every tool, but one artifact ships as one unit and follows its most demanding step, and a shared placement would advertise a lens step that three of four tools have not been shown to perform.

**AGY-D2 — One launcher, two modes, Python.** `scripts/agy_run.py` is a PEP 723 script (the convention `content-tests` runs) with `scripts/agy_run_test.py` beside it. Sub-commands `worker` and `lens` share argv parsing, the stream-json reader, the outcome classifier and the watchdog; they differ only in what they set up around agy. Python over Node: the launcher needs a tar extraction, a process group, a temporary home, and JSON line parsing, all standard library; the OpenRouter launcher is Node because it hosts a proxy, which this launcher does not. The refuted alternative is two scripts, which would duplicate the classifier and let the two modes' failure contracts drift apart.

**AGY-D3 — Worker launch contract.** `agy_run.py worker --model ID --timeout SECONDS -p PROMPT` spawns exactly `agy -p PROMPT --model ID --output-format stream-json --print-timeout <SECONDS>s --mode accept-edits` in the invoking directory, with the parent's environment untouched, `HOME` included. No `sandbox-exec`, no `--agent`, no `--add-dir`, no `--effort`, no `--sandbox`, no `--dangerously-skip-permissions`. The user's `~/.gemini/GEMINI.md`, the user's `~/.gemini/config/` customizations and the checkout's own rules, skills and hooks load, as Claude's and Codex's instruction files load for their workers. A headless worker edits files only under `--mode accept-edits` and only inside a trusted workspace (F12), so the launcher checks before spawning that the invoking directory is at or beneath a path in `trustedWorkspaces` of `~/.gemini/antigravity-cli/settings.json`, and exits 78 naming that file and the remedy when it is not; a worker whose every edit is silently denied returns an empty run at full cost (F2), and a preflight names the cause for nothing. Shell commands stay governed by the user's `permissions.allow` list in the same settings file; a command outside it is auto-denied and surfaces in the ledger. The launcher never wraps a worker (F7).

The launcher defines no permission bypass. `--dangerously-skip-permissions` is adopted only in combination with agy's own `--sandbox`, and only after a probe shows that the pair confines a worker to edits and commands inside the workspace, which is what Codex's workspace-write sandbox provides. The one probe run so far (F15) points the other way, and the deciding probe is section 8's open question. Until it passes, a caller who needs unattended commands widens `permissions.allow` in agy's settings. Refuted alternative: a bare `--dangerously-skip-permissions`; under it every action auto-proceeds, a sandbox denial included (F15), so a worker with it is confined by nothing.

**AGY-D4 — Lens launch contract.** `agy_run.py lens --repo PATH --base BASE [--rev REV] --model ID [--timeout SECONDS] [--keep-snapshot] -p PROMPT` builds a snapshot (AGY-D5), builds a temporary `HOME`, proves it (AGY-D8), then spawns `agy --agent agy-lens --mode plan --model ID -p <preamble + PROMPT> --output-format stream-json --print-timeout <SECONDS>s` with the snapshot as cwd and the parent's environment with exactly one change: `HOME` set to the temporary home. The argv carries no `sandbox-exec`, no `--add-dir`, no `--effort`, no `--sandbox`, no `--dangerously-skip-permissions`, and no `--disable-slash-commands`: that flag turns plan mode off while agy's `init` event still reports plan mode (F16), so the launcher never builds an argv holding both.

The temporary `HOME` is a fresh directory outside the repository holding exactly an empty `.gemini/` directory and `Library/Keychains` symlinked to the real `~/Library/Keychains`. It is an allow-list. `GEMINI.md`, `config/rules`, `config/skills`, `config/agents`, `config/workflows` and `antigravity-cli/settings.json` are absent, so nothing user-level loads and nothing needs denying (F13, F11). The Keychain link is what keeps sign-in headless. A shell started under the swapped `HOME` would read different dotfiles and build a different `PATH`; the lens agent has no command tool (F9), so no shell runs and that side effect reaches nothing. The launcher removes the home on every exit path, signals included, and never keeps it.

Three write barriers stack: the agent's tool list (F9), plan mode (F10), and the snapshot being untrusted by construction (F12). Plan mode's cost was measured and is nil; its plan artifact lands in the temporary home. Skill expansion in the prompt is bounded by reach rather than by a flag: the only skills a lens can expand are the accepted workspace ones, because the user-level skills directory is absent from the temporary home and a changed workspace skill is renamed (F16, AGY-D5). Refuted alternative: a Seatbelt deny profile over the real `HOME` (F6). It works, and it is a deny list: the house skills `agents-config-9k9.436.1` will deploy under `~/.gemini/config/skills/` would need a new deny line, as would every rule source agy adds; the profile cannot be applied from a shell that already carries a different one (F7); and each launch needs a subprocess canary to prove the denial. An absent file needs none of that.

**AGY-D5 — How a lens reads the repository under review.** The launcher extracts `git archive REV` of `--repo` into a fresh temporary directory outside the repository, runs `git init` in the snapshot so agy's walk to a repository root stops there, writes `.agents/agents/agy-lens/agent.md`, and writes the change diff (below). Snapshots are of a revision only. A caller reviewing uncommitted work commits it to a temporary ref or runs the round on a worktree head, which is how every review-panel round already runs.

Instruction files. Unchanged instruction files load normally and are not renamed: the project has accepted them, and the governing rule lets them instruct a lens. Among instruction files, the ones the change adds or modifies are renamed `<name>.under-review`, and no other instruction file is; a deleted one is absent from the snapshot and appears only in the diff. Process files (below) are the one class renamed regardless of the change. An instruction file is any file whose basename is `AGENTS.md` or `GEMINI.md`, and any file with a path component equal to one of agy's customization roots `.agents`, `.agent`, `_agents` or `_agent` (F8). The change is `git diff --name-status --no-renames BASE REV`; a path with status `A`, `M` or `T` is under review. The lens reads a renamed file as an ordinary file, which keeps it reviewable, and nothing loads it as a rule, skill, workflow or agent.

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
| `0` | `status: SUCCESS`, non-empty response, no denied action, no print-timeout notice | Use the output | — |
| `70` | agy finished but the output is unusable: empty response, or `denied_actions` non-empty | Re-brief (for example, keep the model inside the workspace) or move to another route | `unusable-output` |
| `75` | The route did not serve the run: agy exit non-zero, non-SUCCESS status, an `AGY_ERROR` line, `agy` not on PATH, `git` not on PATH in lens mode, timeout or a signal that ended the run (AGY-D9), or the temporary home failed its check (AGY-D8) | Fail over to the next route or model, quoting the stderr reason; after a signal the caller sent, nothing | `transport-error` |
| `78` | The launcher refused the invocation: a missing flag, an argv element before `-p` that is not a launcher flag (`--effort`, `--disable-slash-commands` and every other agy flag included), an element after the prompt, a `claude-` model, a permission bypass or `--sandbox` flag, a worker directory outside every trusted workspace, an unreadable repository, an unresolvable revision or base, a `.review` path or a rename target `<name>.under-review` already present in the archived revision, or any other git command the launcher runs exiting non-zero | Fix the invocation; do not fail over | — |

Quota exhaustion is unobserved; whatever agy reports, it is either a non-zero exit, a non-SUCCESS status, or an empty response, and all three map to a code the consumer fails over on. The stderr line `[agy-run] reason=<word>` names the sub-cause (`error`, `no-route`, `timeout`, `signal`, `home-unproven`, `empty`, `denied`, `untrusted-workspace`). When more than one cause applies, the first in this order decides the exit and the reason: a signal the launcher received (`signal`); the launcher's watchdog or agy's print-timeout notice (`timeout`); agy's exit code, `status` and `AGY_ERROR` line (`error`); `denied_actions` (`denied`); an empty `response` (`empty`). A run the launcher itself ended is therefore never reported as agy's error, and a `SUCCESS` result under the print-timeout notice, empty or partial, is a timeout.

Cleanup never changes the exit code. When the snapshot or the temporary home cannot be removed at exit, the launcher exits with the run's own code and prints one `[agy-run] leak=<path>` line per directory still present, so a good response is not discarded over a directory and the caller knows what to remove. Refuted alternative: a distinct exit for a cleanup failure, which would send a consumer to the next route to re-spend the run and produce the same leak.

**AGY-D8 — Launch check.** Before spawning agy in lens mode the launcher checks the temporary home it built: `<home>/.gemini` is a directory with no entries; `<home>/Library/Keychains` is a symlink whose target is the real `~/Library/Keychains`, and that target is a directory; `<home>` is neither the real home nor inside `--repo`; and the child environment's `HOME` equals `<home>`. Any failed condition means the lens could load a user-level file or could not sign in: exit 75, `reason=home-unproven`, no agy spawn. A real `~/Library/Keychains` that does not exist means the route cannot sign in headlessly on this machine: exit 75, `reason=no-route`. The check proves the isolation mechanism, not the model's behaviour, so the behavioural check (the banana rule fires for a worker and not for a lens) is a recorded evidence run on the work item rather than a per-launch cost. Refuted alternatives: a `sandbox-exec ... cat` canary belongs to the deny profile and has nothing to prove against an absent file; a model-answered canary per launch spends a model turn to learn what a directory listing learns for free.

**AGY-D9 — Timeouts and kill-by-pid.** `--timeout SECONDS` is required for a worker and defaults to 600 for a lens; a one-constant lookup on flash-high takes up to about two minutes (F10), so a lens default below that would time out routine work. The launcher passes `--print-timeout <SECONDS>s` to agy and arms its own watchdog at `SECONDS + 30`. agy runs in a new session (process group led by the agy pid); the launcher prints `[agy-run] pid=<pid>` at spawn so a runner can kill the group by pid. On the watchdog firing it sends `SIGTERM` to the group, `SIGKILL` ten seconds later, and exits 75 `reason=timeout`. A run that ends by agy's own print-timeout notice (F3) is also 75 `reason=timeout`, whether the partial `response` is empty or not, so a caller never mistakes a partial run for success. A `SIGTERM` or `SIGINT` delivered to the launcher itself while agy runs, in either mode, takes the same path: `SIGTERM` to the group, `SIGKILL` ten seconds later, cleanup, exit 75 `reason=signal`. A worker left running after its launcher died would keep editing files and spending quota with nobody reading the result. Refuted alternative: `timeout N agy ...` alone, which the OpenRouter launcher's history shows survives `SIGTERM` and leaves the run orphaned.

**AGY-D10 — The ledger on stderr.** From the stream, in this order: `[agy-run] pid=<pid>` at spawn; `[agy-run] agent=<name> permission_mode=<mode>` from `init` (`agent=` only when the event carries one; a default-agent run omits it); one `[agy-run] tool=<tool_name> <first parameter>` per tool `step_update` entering `ACTIVE`, in stream order; and a final `[agy-run] status=<status> turns=<n> tokens=<total> denied=<names>` from the `result` event. After the final line come `[agy-run] reason=<word>` on every non-zero exit (AGY-D7), `[agy-run] snapshot=<path>` when `--keep-snapshot` kept one, and `[agy-run] leak=<path>` per directory cleanup could not remove. agy's own stderr passes through unchanged as it arrives, so an `AGY_ERROR` line and the jetski notice survive for the round's records. The `tool=` lines with their first parameter are the read evidence a no-read check reads (`agents-config-9k9.408` names that check for the other transports).

**AGY-D11 — Sibling edits in the same change.** `choosing-a-delegate`'s route table gains a row before the OpenRouter row: Gemini models run through this skill, on the subscription, and OpenRouter is the fallback once quota is spent. `delegating-to-codex`'s description drops "and not for OpenRouter or Gemini CLI" in favour of "and not for OpenRouter or agy". `openrouter-claude-subagent`'s description drops "Codex or Gemini CLI" in favour of "Codex, and not the first route for a Gemini model, which is the agy skill; this transport is its fallback", and keeps Gemini in its hosted-model list because the fallback still names those ids. No other deployed prose changes; `src/user/.gemini/` and the shared README name Gemini CLI as an install target and belong to `agents-config-9k9.436`.

**AGY-D12 — Admission case.** The record the front matter carries, in the shape `admit-request` evaluates. It states one worth field: this is a repeatable procedure, so the assistive case is the honest one.

```yaml
admission:
  provides: An agy run in one of two verified shapes: a worker in the current checkout that reads the user's and the repository's instruction files like a Claude or Codex worker does, or a fresh-context lens over a snapshot of a revision, run under a temporary home that holds only a Keychain link so no user-level rule or skill loads, with the change's own instruction files renamed so nothing under review instructs the reviewer, every hook and MCP configuration under a customization root renamed so nothing launches, and the change's diff beside them. Invoking it produces the launcher command, its exit code contract, and the model id for the task profile.
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

`REV` defaults to `HEAD`; `REV` and `BASE` accept any commit-ish `git diff` accepts, and `REV` must also be one `git archive` accepts. `-p` is the last launcher flag: the single argv element after it is `PROMPT`, taken verbatim whatever its text, and a further element is refused. A launcher flag is an argv element before `-p`; nothing after `-p` is read as one.

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
    reason: str | None       # error | no-route | timeout | signal | home-unproven | empty | denied | untrusted-workspace | None
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
- **AGY-A2** `--skip-permissions`, `--dangerously-skip-permissions` or `--sandbox` as a launcher flag (an argv element before `-p`), in either mode, exits 78 before anything spawns, with stderr naming the flag. The element after `-p` is the prompt and is never read as a flag: `-p "--sandbox"` and a prompt whose text contains any of the three strings spawn normally. Check: suite; fake spawn records zero calls for each flag in each mode and one call for each of the two prompt cases.
- **AGY-A3** Each of the following exits 78 before anything spawns, with stderr naming the cause: a missing `--model` or a missing `-p` in either mode; a missing `--timeout` on `worker`; `--effort` as a launcher flag; an argv element before `-p` that is not a launcher flag (`--disable-slash-commands` and `--output-format` are the suite's cases); an argv element after the prompt; a `--model` beginning `claude-`. `-p "--effort"` and a prompt whose text contains `--effort` spawn normally. Check: suite; fake spawn records zero calls for every refusal and one call for each of the two prompt cases.
- **AGY-A4** A `result` event with `status: SUCCESS`, a non-empty `response` and no `denied_actions`, on a run whose stderr carries no `print timeout` notice (AGY-A7), exits 0, and stdout is exactly the response text. Check: suite over a canned stream with an `init` event, three tool steps, a `result` event and no notice on stderr.
- **AGY-A5** A `result` with `status: SUCCESS` and an empty `response`, or with a non-empty `denied_actions`, on a run whose stderr carries no `print timeout` notice, exits 70 with `[agy-run] reason=empty` or `reason=denied` naming each denied action's `display_name`, and stdout empty. Check: suite, both inverses of AGY-A4, neither stream carrying the notice.
- **AGY-A6** agy exiting non-zero, a `result` whose `status` is not `SUCCESS`, or an `AGY_ERROR:` line on agy's stderr, on a run the launcher neither timed out nor ended for a signal (AGY-A7, AGY-A11), exits 75 with `reason=error`, agy's error text present on the launcher's stderr verbatim, and stdout empty. An `agy` binary absent from PATH exits 75 with `reason=no-route`. Check: suite, one case per trigger.
- **AGY-A7** No `result` event within `N + 30` seconds: the launcher sends `SIGTERM` to the agy process group, `SIGKILL` ten seconds later if it is still alive, and exits 75 with `reason=timeout`. A run whose stderr carries agy's `print timeout` notice also exits 75 `reason=timeout` whatever its `result` event holds: a `SUCCESS` status with a partial `response` and no `denied_actions` is still a timeout, and AGY-A4, AGY-A5 and AGY-A6 apply only to runs without the notice. stdout is empty in every timeout case. Check: suite with a fake agy that sleeps past a one-second timeout and ignores `SIGTERM` (the group is gone afterwards), and two canned streams carrying the notice, each ending in a `result` with `status: SUCCESS` and no `denied_actions`, one with an empty and one with a non-empty `response`; the pass rule is exit 75, `reason=timeout` and empty stdout in all three cases.
- **AGY-A8** Repeated invocation with identical arguments produces identical argv and identical classification. Check: suite.
- **AGY-A9** `worker` spawns only when the invoking directory equals a path listed in `trustedWorkspaces` of the settings file at `AGY_SETTINGS` or lies beneath one by path ancestry; a directory outside every listed path, a sibling directory whose name extends a listed path (`<listed>-backup` beside `<listed>`), a settings file that is missing or unparseable, or a list that is absent, exits 78 with `reason=untrusted-workspace`, names the settings path and the remedy (add the directory or an ancestor of it to `trustedWorkspaces` there), and spawns nothing. `lens` performs no such check. Check: suite with a temporary settings file over seven cases: the listed directory and a descendant spawn once each; the prefix sibling, an unrelated directory, a missing file, an unparseable file and a file without the list spawn nothing and exit 78 with the reason line, the settings path and the string `trustedWorkspaces` on stderr.
- **AGY-A10** In both modes stderr carries the ledger of AGY-D10 in that order: `[agy-run] pid=<pid>`; `[agy-run] agent=<name> permission_mode=<mode>` from the `init` event, with `agent=` present when the event names an agent and absent when it does not; one `[agy-run] tool=<tool_name> <first parameter>` per tool `step_update` entering `ACTIVE`, in stream order; and a final `[agy-run] status=<status> turns=<n> tokens=<total> denied=<names>` from the `result` event, followed by `[agy-run] reason=<word>` when the exit is not 0. Lines from agy's own stderr pass through verbatim. Check: suite over one canned stream per mode, the lens stream's `init` naming `agy-lens` and the worker's naming none, each with three tool steps carrying parameters and a `result`, plus one stream with a denied action; the pass rule is line-by-line equality of the `[agy-run]` lines with the expected ledger.
- **AGY-A11** `SIGTERM` or `SIGINT` delivered to the launcher while agy is alive, in either mode: the launcher sends `SIGTERM` to the agy process group, `SIGKILL` ten seconds later if it is still alive, and exits 75 `reason=signal` with stdout empty; the group is gone afterwards. Check: suite with a fake agy that sleeps and ignores `SIGTERM`, one case per signal per mode, the ten-second step taken through the fake clock; the pass rule is exit 75, the reason line, and no live process in the group.

### Slice B — lens mode

- **AGY-B1** `lens --repo R --base B --rev V --model M --timeout N -p P` spawns argv `["agy", "--agent", "agy-lens", "--mode", "plan", "--model", M, "-p", <preamble + P>, "--output-format", "stream-json", "--print-timeout", "Ns"]` with cwd equal to the snapshot directory `make_snapshot` returned, and an environment equal to the parent's with exactly one difference, `HOME` set to the temporary home; the argv contains no `--disable-slash-commands`, `sandbox-exec`, `--add-dir`, `--effort`, `--sandbox` or `--dangerously-skip-permissions`. Check: suite; fake spawn records argv, cwd and env, and the argv assertion is exact equality, so an argv that carries `--disable-slash-commands` beside `--mode plan`, or that lacks `--mode plan`, fails it; the cwd assertion compares against the snapshot path, so the temporary home or any other directory as cwd fails it.
- **AGY-B2** The snapshot contains every path `git archive V` of R emits and no path of R's working tree that V lacks; every instruction file the change adds or modifies, and every process file, exists as `<name>.under-review` with identical bytes and does not exist under its original name; every other archived path exists unchanged under its original name; `.git` exists as a freshly initialised repository; `.agents/agents/agy-lens/agent.md` equals the definition in 5.4. Check: suite over a fixture repository with two commits, an uncommitted extra file, a changed and an unchanged `AGENTS.md` at two depths, an `AGENTS.md` deleted between B and V, an `AGENTS.md` moved between B and V with its bytes unchanged, a changed and an unchanged `.agents/rules/*.md`, and an unchanged `.agents/hooks.json`. The expected renamed set is written out in the test rather than computed through `neutralized_names`, and it holds the moved file's new path: `git diff --name-status` reports that move as `R100` unless `--no-renames` is passed (git's `diff.renames` defaults to true), so an implementation that lets git detect renames leaves the moved file loadable under its original name and fails this check.
- **AGY-B3** `neutralized_names` returns exactly: every changed path with status `A`, `M` or `T` whose basename is `AGENTS.md` or `GEMINI.md` or whose path has a component in `CUSTOMIZATION_ROOTS`; plus every archived `hooks.json` and `mcp_config.json` directly under a component in `CUSTOMIZATION_ROOTS`, changed or not. It returns nothing for an unchanged `AGENTS.md`, a path with status `D`, or a changed `CLAUDE.md`, `README.md`, `AGENTS.md.template`, or `rules/x.md` whose parent is not one of the four root names. Check: suite, pure function.
- **AGY-B4** When the extracted archive of V already holds `<name>.under-review` for a path AGY-B3 names, the launcher exits 78 before renaming anything and before spawning, and stderr names both paths. Check: suite with a fixture commit holding a changed `AGENTS.md` beside a committed `AGENTS.md.under-review`; the pass rule is exit 78, both names on stderr and zero spawn calls. AGY-B8 covers the directories this refusal leaves behind.
- **AGY-B5** The temporary home holds exactly two entries when agy is spawned: `.gemini`, an empty directory, and `Library/Keychains`, a symlink to `<real HOME>/Library/Keychains`; the home is outside R and is not the real home. Check: suite with a fake real home, filesystem listing at the spawn seam.
- **AGY-B6** Before spawning, `prove_home` yields launcher exit 75 `reason=home-unproven` and no agy spawn when `.gemini` has an entry, when `Library/Keychains` is missing or resolves elsewhere, when the home is the real home, when the home lies inside R, or when the child environment's `HOME` differs from the home; it yields 75 `reason=no-route` and no spawn when `<real HOME>/Library/Keychains` does not exist; a sound home proceeds to the spawn. Check: suite with a fake real home and a fixture repository, seven refusing cases (among them the fake real home passed as the home, and a directory created under R passed as the home) and the sound one; fake spawn records zero calls for each refusal and one for the sound home.
- **AGY-B7** The preamble precedes the caller's prompt and names the snapshot path, B, V, `.review/change.diff`, every rename as `<original> -> <original>.under-review`, the note that a deleted file appears only in the diff, and the instruction to stay inside the snapshot; the caller's prompt follows byte-for-byte. Check: suite.
- **AGY-B8** After the launcher exits with 0, 70, 75 or 78, including a 78 raised after the snapshot or the temporary home exists (AGY-B4's rename collision is the suite's case), and after `SIGTERM` or `SIGINT` delivered to the launcher while agy runs, the snapshot directory and the temporary home are gone; with `--keep-snapshot` the snapshot remains, the home is still gone, and stderr carries `[agy-run] snapshot=<path>`. Check: suite over each of the four exit codes, both signals and the keep flag, with a fake agy that sleeps for the signal cases; the pass rule is a filesystem listing after exit showing neither directory, or only the kept snapshot.
- **AGY-B9** `worker` creates no snapshot, no temporary home, no agent definition and no diff, and its child environment's `HOME` equals the parent's. Check: suite, filesystem before and after, fake spawn env.
- **AGY-B10** `.review/change.diff` in the snapshot equals byte-for-byte the stdout of `["git", "-C", R, "diff", "--no-color", "--no-ext-diff", "--find-renames", "--unified=10", B, V]` through the `run` seam; B equal to V yields an empty file, zero renames and a spawn. Check: suite, fixture repository, both cases.
- **AGY-B11** `lens` without `--timeout` passes `--print-timeout 600s` and arms the watchdog at 630 s; with `--timeout N` it passes `Ns` and arms at N + 30. Check: suite, fake spawn and fake clock.
- **AGY-B12** Each of the following exits 78 before anything spawns, with stderr naming the cause and carrying git's own stderr: `--repo` is not a readable git repository; `B` does not resolve in it; `V` does not resolve in it, or `git archive` refuses it; the archive of `V` contains a path under `.review`; `git init` in the snapshot, the `git diff` that lists the changed paths, or the `git diff` that writes the diff file exits non-zero for any other reason. A `git` binary absent from PATH exits 75 with `reason=no-route`, as an absent `agy` does (AGY-A6). Check: suite, fixture repository, eight cases; the three git command failures and the absent binary are injected through the `run` seam (a non-zero return, and the not-found error the real `subprocess.run` raises); fake spawn records zero calls for every case.
- **AGY-B13** When the snapshot or the temporary home cannot be removed at exit, the launcher's exit code is the run's own code and stderr carries one `[agy-run] leak=<path>` line per directory still present; a run whose cleanup succeeds prints no `leak=` line. Check: suite; the directory holding the snapshot and the home is made read-only before agy's fake `result` arrives and restored after, one case ending in exit 0 and one in exit 75; the pass rule is the unchanged exit code and one `leak=` line per surviving directory.
- **AGY-B14** `lens` without `--rev` reviews `HEAD` of R: the snapshot is the archive of `HEAD`, and the renamed set and `.review/change.diff` are those of B against `HEAD`. Check: suite over a fixture repository with three commits, B the first, whose third commit at `HEAD` changes an `AGENTS.md` the second commit leaves alone; pass when the snapshot holds the third commit's content, that file exists only as `AGENTS.md.under-review`, and the diff file equals the `run` seam's output for B against `HEAD`.

### Slice C — skill prose, admission, siblings

- **AGY-C1** `src/user/.claude/skills/delegating-to-agy/SKILL.md` exists with `name: delegating-to-agy`, the admission block of AGY-D12, and the description of 5.6; `content-lint` reports the skill staged for Claude within the model-invoked body cap. Check: `make content-lint` exit 0, and its listing carries a `<tokens> / <cap> tokens .../delegating-to-agy/SKILL.md [claude]` line with tokens below the cap.
- **AGY-C2** `scripts/agy_run.py` and `scripts/agy_run_test.py` exist beside each other, and `content-tests` discovers the suite and runs it to a clean pass. Check: `make content-tests` exit 0 and its per-suite line naming `agy_run_test.py` as passed.
- **AGY-C3** The `description:` line of every `SKILL.md` under `src/`, plugin trees included, is free of the string `Gemini CLI`; `delegating-to-codex`'s description contains `and not for OpenRouter or agy`; `openrouter-claude-subagent`'s description contains `not the first route for a Gemini model, which is the agy skill; this transport is its fallback` and still names Gemini in its hosted-model list. Check: three greps over the `description:` lines of `src/**/SKILL.md`; pass when the first returns no line and each of the other two returns exactly one line, in the named skill's file.
- **AGY-C4** `choosing-a-delegate`'s route table has a row whose route column names Gemini models and whose reach column names this skill as the route and the OpenRouter subagent skill as the fallback once the subscription quota is spent; that row precedes the OpenRouter row. Check: read of `src/user/.claude/skills/choosing-a-delegate/SKILL.md`; pass when a grep for `delegating-to-agy` matches exactly one table row and that row's line number is smaller than the OpenRouter row's, so the row sits earlier in the file. AGY-E4 establishes that the row routes.
- **AGY-C5** `evals/trigger-eval.json` holds at least six `should_trigger: true` queries (naming agy, Antigravity, or a Gemini model with a run to launch) and at least six `should_trigger: false` queries covering OpenRouter, Codex, agy sign-in, and a plain "review this PR", in the shape `writing-skills`' testing methodology defines. Check: file read against that shape; pass when both counts hold and every entry has `query` and `should_trigger`. AGY-E5 establishes that the description triggers on it.
- **AGY-C6** `references/model-routing.md` carries the four rows of the AGY-D6 table, each with its full agy model id, and the date the ids were captured from `agy models`. Check: file read; pass when the four ids of AGY-D6 appear in the table and a capture date is stated.

### Slice D — recorded evidence on the work item

- **AGY-E1** An `admit-request` verdict for the skill is recorded on `agents-config-9k9.437`, and if it is `ADMIT-WITH-CHANGES` every named edit is in the same change. Check: `observed:` row citing the note.
- **AGY-E2** Two recorded runs of the deployed launcher on the same day and agy version: `worker` with the banana question returns the scripted answer; `lens` with the same question returns an answer that is not the scripted one. Check: `observed:` row citing the note with both outputs.
- **AGY-E3** One recorded `lens` run over a snapshot of this repository at a named head against a named base exits 0 with at least one `[agy-run] tool=` line and a non-empty response. Check: `observed:` row citing the note.
- **AGY-E4** Two recorded Claude Code sessions with the deployed skills, one per prompt, each asked for a Gemini model's independent review of a named file without naming agy, Antigravity or OpenRouter ("have a Gemini model review <file>" and "get a second opinion on <file> from Gemini"): the first delegation skill each session invokes after `choosing-a-delegate` is `delegating-to-agy`, and `openrouter-claude-subagent` is invoked in neither session before it. Pass when both sessions do; one session invoking the OpenRouter skill first fails. Check: `observed:` row citing the note with both transcripts.
- **AGY-E5** One recorded run of the manual trigger-eval workflow in `writing-skills`' testing methodology over the deployed skill and the AGY-C5 corpus, three dispatches per query: every `should_trigger: true` query triggers the skill in at least two of its three dispatches, and every `should_trigger: false` query triggers it in at most one. Pass when every query meets its threshold; any query missing it fails. Check: `observed:` row citing the note with the tabulated hit rates.

### Edge-case taxonomy

| Criteria | Inverse and boundary | Dependency failure | Repetition and idempotency |
| --- | --- | --- | --- |
| AGY-A1 to AGY-A3, AGY-A9 | Flag before `-p` versus the same string as or inside the prompt, an agy flag the launcher does not define, an element after the prompt, `claude-` prefix, bypass or sandbox flag in either mode, directory equal to, beneath, a prefix sibling of, or outside a trusted path | Settings file missing or unparseable | Same argv twice is byte-equal (AGY-A8) |
| AGY-A4 to AGY-A7, AGY-A10, AGY-A11 | Empty response, partial response with the print-timeout notice, denied actions, non-SUCCESS, missing result, `init` with and without an agent name | agy absent, agy killed by the watchdog or a signal (classified as `timeout` or `signal`, never as agy's error), launcher signalled in either mode, stderr without a result | A second run after a timeout or a signal starts clean; no orphaned process group |
| AGY-B1 to AGY-B14 | Changed versus unchanged instruction file at depth 0 and 2, deleted file, file moved with unchanged bytes, process file unchanged, file outside the class, uncommitted file, base equal to rev, `--rev` absent versus given, worker mode, timeout absent versus given, argv with `--mode plan` alone versus beside `--disable-slash-commands`, cwd equal to the snapshot versus the home, home equal to the real home or under the repository | Repository unreadable, revision or base unknown, git absent, `git init` or `git diff` failing, real Keychains absent, home populated, `.review` or `.under-review` collision, directories unremovable at exit | Snapshot and home removed on every exit code and signal; `--keep-snapshot` leaves one snapshot and no home; a cleanup failure keeps the run's exit code |
| AGY-C1 to AGY-C6 | Description containing the retired tool name, the required substring absent, a row after the OpenRouter row, a corpus entry missing a field, a table missing an id or its date | Gate unavailable | Re-staging changes nothing |
| AGY-E1 to AGY-E5 | Canary fires in worker, not in lens; a session routing to OpenRouter first; a query on the wrong side of its threshold | agy version drift between the two runs is a fresh pair; a session without the deployed skills is not a run | Two runs, one day; three dispatches per query |

## 7. Coverage of the work item's acceptance lines

| Work-item line | Criteria |
| --- | --- |
| 1. admit-request verdict recorded | AGY-E1 |
| 2. launcher tests pin both modes: the worker argv carries no sandbox wrapper, no permission bypass and the parent's own HOME; the lens argv carries the read-only agent, plan mode and stream-json output, runs under a temporary HOME holding only an empty `.gemini/` and a Keychains link, and reads a snapshot carrying the change's diff, with the change's own instruction files renamed plus every hooks.json and mcp_config.json under a customization root renamed on every run; an unusable run, a route failure and a refused invocation each yield a distinct exit | AGY-A1, AGY-A2, AGY-A3, AGY-A9 (worker); AGY-B1, AGY-B5, AGY-B6, AGY-B10, AGY-B12 (lens argv, home and snapshot); AGY-B3 (the renames, process files included); AGY-A5, AGY-A6, AGY-A7, AGY-A11 (distinct exits) |
| 3. recorded canary runs | AGY-E2 |
| 4. the spec settles how a lens reads the repository and the launcher implements it | AGY-D5, AGY-B2 to AGY-B4, AGY-B7, AGY-B10, AGY-B14, AGY-E3 |
| 5. no deployed description names "Gemini CLI"; choosing-a-delegate routes Gemini to this skill | AGY-C3, AGY-C4, AGY-E4 |

## 8. Open question for the owner

One remains. **Worker permission bypass with `--sandbox`.** AGY-D3 admits `--dangerously-skip-permissions` only paired with agy's `--sandbox`, and only once a probe shows the pair confines a worker to edits and commands inside the workspace, as Codex's workspace-write sandbox does. The probe run here (F15) shows the pair auto-proceeding past a sandbox denial and writing under `/tmp`; `/tmp` is also writable under Codex's sandbox, so that run does not decide the question, and the deciding run was refused by the session's permission classifier. The deciding probe: from an untrusted scratch repository, `agy --sandbox --dangerously-skip-permissions -p "<touch a file under the home directory with the shell tool, then create one there with the file-writing tool>"`. If both writes are denied and no retry succeeds, the pair confines comparably, and the launcher may add a worker flag that forwards the two agy flags together, with AGY-A2 amended to admit that pair and to keep refusing either flag alone. If either write succeeds, the flag stays out, and `permissions.allow` in agy's settings remains the only route to unattended commands. The owner runs the probe.

## 9. Out of scope

Review-panel routing rows and the failover ledger (`agents-config-9k9.17.29`); installer changes for agy (`agents-config-9k9.436`); admission-gate pricing for Gemini; agy sign-in and quota monitoring; a Linux lens mode (the Keychain link is macOS); the Claude and GPT-OSS models agy lists; reviewing uncommitted working trees (AGY-D5 snapshots a revision only).

## 10. Premises the probes contradicted

- "Seatbelt profiles cannot nest": an identical inner profile re-applies; only a differing inner profile fails with exit 71 (F7). The design consequence is unchanged.
- "Substituting HOME forces a browser login or strips the login-shell PATH agy builds" (the work item's description): a temporary home whose only content is a Keychain link signs in headlessly (F13), and the PATH a swapped home builds reaches nothing in a lens, whose agent has no command tool (F9).
- "A non-SUCCESS status is the failure contract": a denied tool and a print-timeout both end in `status: SUCCESS` with an empty response and exit 0 (F2, F3).
- "No tool allowlist exists": a custom agent's `tools` list is one, and it holds in headless mode (F9).
- "Plan mode adds ceremony a lens does not need" (the draft's F10, which compared a 171 s run against a 7 s run of different requests): the controlled A/B shows no measurable cost and no approval stall (F10). Plan mode stays.
- "An ignore file could keep AGENTS.md out of a lens": `.geminiignore`, `.gitignore` and `.rgignore` change nothing, and the binary does not know `.geminiignore` (F14).
- "`--sandbox` with the bypass flag might confine a worker comparably to Codex": the one run so far shows the pair proceeding past a sandbox denial (F15); the pair is unproven and the deciding probe is section 8's question.
- "agy 1.2.11": the machine runs 1.2.12; every observation here is against that version.
- The tracker's untested candidate "an empty cwd with `--add-dir`" was already refuted in its own later note; this spec did not re-test it.
- Frontmatter-less `.agents/rules/*.md` and sub-directory `AGENTS.md` files did not load in headless runs (F8), so renaming a changed one is defence in depth rather than the only barrier for those files; the root-level file is the one that loads.
- "Worker: plain agy with the real HOME": plain agy in headless mode cannot edit a file. Edits need `--mode accept-edits` and a trusted workspace together (F12); `--mode accept-edits` alone, in an untrusted directory, is denied like the default mode.
- "`--disable-slash-commands` stacks with plan mode as a further lens barrier" (the draft's F16 and lens argv): agy 1.2.12 warns that plan mode has no effect while slash-command expansion is disabled, and its `init` event reports plan mode either way (F16). The lens argv carries plan mode alone.

## 11. Continuations

Use `work promote` on each resulting feature before implementation; the child spec supplies the implementation manifest and dependencies. Slice D closes last and cannot close before the human runs the installer, because AGY-E2 and AGY-E3 run the deployed launcher and AGY-E4 and AGY-E5 run sessions over the deployed skills.

- feat: delegating-to-agy launcher core and worker mode — AC: AGY-A1, AGY-A2, AGY-A3, AGY-A4, AGY-A5, AGY-A6, AGY-A7, AGY-A8, AGY-A9, AGY-A10, AGY-A11
- feat: delegating-to-agy lens mode — AC: AGY-B1, AGY-B2, AGY-B3, AGY-B4, AGY-B5, AGY-B6, AGY-B7, AGY-B8, AGY-B9, AGY-B10, AGY-B11, AGY-B12, AGY-B13, AGY-B14
- feat: delegating-to-agy skill prose, admission and sibling routing — AC: AGY-C1, AGY-C2, AGY-C3, AGY-C4, AGY-C5, AGY-C6
- feat: delegating-to-agy recorded evidence — AC: AGY-E1, AGY-E2, AGY-E3, AGY-E4, AGY-E5

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
- AGY-A10 | open
- AGY-A11 | open
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
- AGY-B12 | open
- AGY-B13 | open
- AGY-B14 | open
- AGY-C1 | open
- AGY-C2 | open
- AGY-C3 | open
- AGY-C4 | open
- AGY-C5 | open
- AGY-C6 | open
- AGY-E1 | open
- AGY-E2 | open
- AGY-E3 | open
- AGY-E4 | open
- AGY-E5 | open
