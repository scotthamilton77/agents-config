# Delegation skills and rules as one system

**Date:** 2026-10-01, revised 2026-10-04
**Status:** Child spec of `docs/specs/2026-07-21-harness-rework-way-forward.md` (D5 foreign eyes in review seats, D16 removal conditions). Draft for review. Six criteria attacks ran, two on 2026-10-01, two on 2026-10-03 and two on 2026-10-04 after DEL-D9 and slice D were amended; the sixth covers the current text, and its record is `docs/specs/2026-10-01-delegation-coherence-ac-attack.json`.
**Work item:** `agents-config-9k9.458`, design child `agents-config-9k9.458.1`. The 2026-10-04 amendment is `agents-config-9k9.469`.
**Related:** `agents-config-9k9.457` (the model routing table, pull request 803), `agents-config-9k9.408` (review-seat pins, pull requests 772 to 774), `agents-config-9k9.17.29` (review-panel Gemini seats on agy).
**Quality contract:** `docs/specs/2026-09-18-acceptance-criteria-quality.md`. **Lifecycle:** `docs/specs/2026-09-18-acceptance-criteria-lifecycle.md`.

## 1. Problem statement

Nine artifacts decide, brief, launch and supervise delegated agents: the `choosing-a-delegate`, `delegating-to-codex`, `delegating-to-agy`, `openrouter-claude-subagent`, `instructing-subagents` and `orchestrating-teammates` skills, the review panel's harvest doctrine, the `ac-attack` skill's transport paragraph, and the user rule on delegation. They were written one at a time. An agent following one can be contradicted by another, and some rules an agent needs are written in none of them.

This spec audits the set as of 2026-10-01 and decides, finding by finding, whether to converge, correct or leave alone. It proposes a change only where the return exceeds the cost, and prefers deleting surface to adding it.

## 2. Scope

In scope: the nine artifacts above; the model routing table they cite; the OpenRouter launcher's supervision behaviour; the agy launcher's model and effort flags; a lint that keeps the routing table the only model inventory; one word, "provider", for what a run is launched through.

Out of scope: the roster moves and the no-read gate that `agents-config-9k9.408` owns; routing review-panel Gemini seats to agy (`agents-config-9k9.17.29`); prgroom's dispatcher chains, which are package code with their own release rule; the brief format `instructing-subagents` teaches; the user's memory files, which no repository gate can read.

## 3. Audit findings

Each finding was verified against main `c90c0001` plus pull request 803 on 2026-10-01, and re-read against pull request 803 at `f0036453` on 2026-10-03.

A **provider** is what a run is launched through. There are four: `anthropic` (the Agent tool), `openai` (Codex), `google` (agy), and `openrouter` (a nested Claude harness on another vendor's weights).

| # | Finding | Kind |
| --- | --- | --- |
| F1 | After pull request 803, one file under `src/` carries model prices, accepted efforts and the model per provider and tier: the routing table beside `choosing-a-delegate`. Nothing mechanical keeps it the only one. Example commands in the panel's `harvest.md` and in the OpenRouter skill name model ids, and nothing fails when such an id leaves the table. | Unguarded |
| F2 | Pull request 772 (`agents-config-9k9.408`, open since 2026-09-17) adds review-seat rows to the OpenRouter skill's routing reference and to the Codex skill's table. Pull request 803 deletes the first file and removes the second table. The two cannot both merge as written. | Conflict |
| F3 | `agents-config-9k9.408` pins the OpenRouter mid review seat to `google/gemini-3.8-flash`. The routing table names `z-ai/glm-5.3` in that cell and reserves Gemini on OpenRouter for the user's explicit instruction. | Contradiction |
| F4 | `agents-config-9k9.408` settles that the OpenRouter launcher refuses every `gpt-` id with no `-mini` exemption. Pull request 803's launcher adds a `gpt-6` prefix, keeps the 5.5 and 5.6 mini exemption, and admits every Gemini id, while its prose says a GPT or Gemini model runs there only on the user's explicit instruction. The code enforces less than the prose states. | Divergence |
| F5 | `agents-config-9k9.408` runs a whole-artifact read on `moonshotai/kimi-k3` at `medium`, a level that model does not list. The OpenRouter launcher skill says `low`. | Divergence |
| F6 | `delegating-to-codex` says the raw `codex` binary "stays forbidden either way". `harvest.md` and `ac-attack` say a Codex reviewer runs "through the codex command-line tool" and name no entry point. A reader can take that as the raw binary. | Ambiguity |
| F7 | `delegating-to-codex` says how to dispatch the rescue agent. No artifact under `src/` gives the part a read-only reviewer adds: capturing the output and supervising the run. That procedure exists only in the owner's memory files: the caller's shell redirects the companion call's output to the claimed file, because Codex's sandbox is read-only; the caller waits on the process it launched and on its own capture file; a usage-limit failure is exit 1 with `You've hit your usage limit` on stderr and means the provider is down. | Missing |
| F8 | `delegating-to-codex` prescribes a Bash timeout of about 1,500,000 ms (25 minutes) and says an agent whose call was backgrounded cannot collect it. Whole-spec runs on the frontier Codex tier were measured at 24 to 28 minutes on 2026-09-30. They were backgrounded, the Codex process finished, and its output reached the files the caller's shell had redirected it to. The skill gives no way to collect such a run, so a finished report is abandoned. | Incomplete |
| F9 | The agy launcher owns its clock: `--timeout`, a watchdog, a kill of the process group, and exit 75 with a reason line. The OpenRouter launcher has no timeout flag, and its skill gives no timeout or kill guidance. The caps a runner applies to an OpenRouter run exist only in memory files. Three recorded runs on `moonshotai/kimi-k3` ended inside a thinking block, one after 67 minutes. Measured healthy runs: an inline read with no tools finishes in 4 to 9 minutes; a repository read ran 27 minutes over 27 forwarded requests and returned nine findings. | Missing |
| F10 | `harvest.md` distinguishes a dead route from a failed reviewer and bounds each differently. The agy skill maps its exits to "fail over" and "re-brief". Nothing maps the Codex and OpenRouter launchers' failure signals onto the same two reasons. | Missing |
| F11 | The OpenRouter skill's description tells a caller to add "a Write grant" for a mandated report file. Its body says a `Write(<path>)` grant is not matched and the grant must be `Edit(<path>)`. | Contradiction |
| F12 | The report-delivery protocol (an explicit send, the `UPDATE` and `FINAL REPORT` markers) is stated in `instructing-subagents`, restated in `orchestrating-teammates`, and pointed at by the delegation rule. The three agree. | Duplication, consistent |
| F13 | Failover is stated in the routing table (which provider a family runs on), in `harvest.md` (any lens may run on any live transport, recorded as a substitution) and in `ac-attack` (run the lenses over the other transport and say so). The three agree, and each serves a different record. | Duplication, consistent |
| F15 | Three words name the provider. `choosing-a-delegate` and the agy skill's exit table say "route"; the panel's `contracts.json`, `harvest.md`, `dispatch_gate.py`, the `review-verdict` schema and `ac-attack`'s lens front matter say "transport" with the values `codex` and `openrouter`; the routing table says "provider" with the four values above. A reader meets a Codex reviewer as `transport: codex` in one file and as the `openai` provider in the next. | Inconsistency |
| F16 | The agy launcher takes the effort as a suffix on the model id and refuses an `--effort` flag, so the caller composes `gemini-3.8-flash-low` by hand from the table's model and its accepted efforts. The OpenRouter and Codex launchers take the effort apart from the model. | Divergence |
| F17 | agy itself takes an `--effort` flag; its changelog dates the flag to 1.2.11. Probed on agy 1.2.16 on 2026-10-04 with `-p "/model"`, which prints the resolved model and runs no turn: `--model gemini-3.8-flash --effort low` resolves to `gemini-3.8-flash-low`, and every level the routing table's `google` rows list resolves to the matching variant. A level the model lacks, a bare model with no effort, a variant id with a conflicting effort, and an unknown model each exit 1 with an `invalid model selection` message on stderr; the first two name the levels the model has. A variant id with no effort still resolves. The launcher's refusal message says agy carries the effort only in the id. | Stale premise |
| F14 | prgroom's dispatcher chains name `gpt-5.6-luna` and `gpt-5.6-terra`. Both appear in the Codex CLI's model list on 2026-10-01. Neither is in the routing table, which lists only the GPT-6 tiers. | Divergence, out of scope |

## 4. Decisions

Each decision states its cost and the observation that removes it.

### DEL-D1. A lint keeps the routing table the only model inventory

A content test reads every Markdown file under `src/` except those under an `evals/` directory. It fails when:

- a file names a model id the routing table does not list;
- a Markdown table row outside the routing table names a model id, listed or not;
- the routing table's tier grid has a column other than the four providers, its models table has a column other than provider, model, price, context and accepted efforts, or the file holds a third table;
- the routing table is absent or lists no model id.

Prose and fenced example commands may name a listed id. Files under `evals/` are exempt because a trigger query quotes what a user might type, and nothing under `evals/` deploys.

Rationale. A model id in a table is the mark of a second inventory. A column added for one caller is the first step back to per-skill tables. A lint with nothing to compare against would pass every drift, so an empty table fails closed. Rejected alternative: review alone. Review catches a stale id in a changed file and cannot catch one in a file nobody is editing, which is how the five tables drifted apart.

Cost: one test file, with a list of id patterns, one per vendor naming scheme, to extend when a vendor invents a scheme. Remove when: the routing table is removed.

### DEL-D2. The routing table maps provider and tier to a model, and the dispatching skill decides the rest

The table carries two things: the model each provider offers at each tier, and per model the price, context and accepted efforts.

The skill that dispatches chooses the effort, the tool grant and the scope of a run, for its own task, from the accepted list. The review panel's seat pins are therefore an effort and a tool grant per seat, held in the panel's own files. `agents-config-9k9.408` adds no row to the routing table. A constraint on how a model behaves under one launcher, such as the Kimi K3 whole-artifact cap, lives in that launcher's skill, once.

Rejected alternatives: seat rows in the routing table, which load a table every launcher reads with one skill's vocabulary; a scope column in the table, which puts a caller's decision in the provider's data.

Cost: the panel pins two values per seat instead of reading them from a row. Remove when: the review tooling addresses models natively and no pin is needed. This decision constrains `agents-config-9k9.408` and adds no criterion here; section 6 records the settings the owner settled.

### DEL-D3. Each launcher skill owns its launcher's whole contract, and the shared vocabulary is four outcomes named once

**Shared outcomes.** `choosing-a-delegate` names the four outcomes any launcher reports: usable output; the launcher refused the invocation; the provider did not serve the run; the run produced unusable output. The agy launcher already reports exactly these as exits 0, 78, 75 and 70.

**Each launcher skill** answers, in its own words, the four questions a caller has of it: whether a run may write or only read; how each kind is started; which of its own signals means which outcome; how a run is bounded and stopped. `delegating-to-agy` already does. `delegating-to-codex` gains its read-only run, with the output captured by the caller's shell, and the collection rule for a run that outlives the Bash call (F7, F8). `openrouter-claude-subagent` gains how a run is bounded and stopped (F9).

**The callers.** The review panel and `ac-attack` keep one mapping of their own, from outcome to claim reason: provider did not serve the run is `transport-error`; unusable output is `unusable-output`; a refusal means fix the invocation; a run the caller signalled means stop (F10). Both name the Codex delegation skill's read-only run as the way a Codex reviewer is launched (F6).

**Ownership boundary.** No launcher's signals appear in a caller's file. No caller's word, "lens" included, appears in a launcher's file. Text outside the passages named here does not change.

Rejected alternatives: a shared supervision skill, which would hold three unlike procedures under one heading and add a hop before every launch; a table of every launcher's signals in the panel's doctrine, which copies three contracts into a caller's file and drifts when any launcher changes; leaving the procedures in memory files, which another machine, another tool and a reviewer never see.

Cost: about forty lines across five files. Remove when: each skill's own removal condition fires.

### DEL-D4. The OpenRouter launcher owns its clock

`run.js` gains `--timeout SECONDS` and `--idle-timeout SECONDS`. On expiry it ends the child, closes the proxy, and exits 75 with a reason line on stderr, the contract the agy launcher already has. Idle means no completion request was forwarded for that many seconds. The flags are the launcher's own and never reach the child. A flag value that is not a positive number exits 78 before the proxy binds, as a missing flag or a refused model already does. A `SIGTERM` sent to the launcher ends the child even when the child ignores it, because a runner's own kill is the last resort when no flag was passed (F9).

The OpenRouter skill states what each flag bounds and what expiry does, and records the measured durations of F9 as facts. The dispatching skill chooses the values for its task and stores them alongside its effort and tool settings; the review panel's values live in its doctrine beside its seat pins.

Rejected alternative: a kill loop written into every runner brief. It is prose a runner may skip, and the 67-minute run is what skipping it costs.

Cost: launcher code and its tests under `content-tests`. Remove when: the OpenRouter launcher is removed.

### DEL-D5. The OpenRouter skill's description and body both require `Edit(<path>)` for a mandated report file

Corrects F11. Cost: one sentence. Remove when: the skill is removed.

### DEL-D6. The delivery protocol and the failover statements stay where they are

Each restatement (F12, F13) sits in the artifact an agent holds at the moment it needs the rule, and the copies agree. Merging them would save about ten lines and add a cross-skill read to every dispatch. Cost: none. Reconsider when two of the copies are found to disagree.

### DEL-D7. prgroom's chains stay in code

Their ids are valid (F14). Changing them is a package change under that package's version rule, and a separate work item moves them to the GPT-6 tiers. Cost: one inventory the lint of DEL-D1 does not read. Reconsider when a chain names an id that has left the Codex model list.

### DEL-D8. One word, "provider", with the values `anthropic`, `openai`, `google` and `openrouter`

Prose under `src/` says provider. The review panel's and `ac-attack`'s data and code say provider with those values, so `transport: codex` becomes `provider: openai` (F15). The verdict envelope's distinct-vendor count keeps meaning vendors: `openrouter` is a provider, not a vendor, so the count resolves an OpenRouter lens to its model's vendor.

Rejected alternative: rename only the prose. Keeping `transport` in code would still require readers to translate between terms at each file boundary.

Cost: a field rename in the verdict envelope, the version bump that implies, and the field's readers in the panel's scripts and prgroom's verdict posting. Remove when: the panel addresses models natively and carries no provider field.

### DEL-D9. The agy launcher passes the model and the effort to agy unchanged

`agy_run.py` accepts `--model <model>` and `--effort <level>` and hands both to agy as given (F16, F17). It composes no id, and it stops refusing `--effort`. agy resolves the pair to a variant. agy refuses a pairing it does not offer before any turn runs, and its message names the levels the model has. The launcher holds no list of levels or models. It reports agy's refusal of the selection as a refused invocation: exit 78, agy's message on stderr, and no reason line. The caller chose the pairing, so the fix is the invocation, and failing over would not repair it. The launcher recognises that refusal by a non-zero exit with agy's `error: invalid model selection` line. When the caller omits `--effort`, the launcher passes the model alone and adds no level of its own, so a full variant id such as `gemini-3.8-flash-low` runs as it does today, and a bare model reaches agy's own refusal. Skills teach the two-flag form and do not teach callers to compose an id.

An agy older than 1.2.11 has no `--effort` flag. It refuses the flag with a different message, and the launcher reports that as it reports any agy error today: exit 75, `reason=error`, and agy's message on stderr. If agy rewords its selection refusal, the launcher reports it the same way, as an agy error.

Rejected alternatives: the launcher composing `<model>-<level>` itself, which repeats a resolution agy already performs and breaks when agy renames its variants; the caller composing the id from the table, which repeats the suffix rule in every skill that dispatches to agy; the launcher checking the level against the model, which copies the routing table's accepted-efforts column into code, a second inventory; the launcher requiring `--effort`, which refuses a variant id agy accepts and replaces agy's message, which names the available levels, with a poorer one.

Cost: launcher code and tests, the agy skill's launch section, and the routing table's sentence on how an effort reaches agy. Remove when: the agy launcher is removed. One message pattern is tied to agy's wording. Reconsider when agy changes what `--effort` accepts or how it words a refused selection.

### DEL-D10. The OpenRouter launcher refuses GPT and Gemini models unless the user instructed the run

The denylist refuses `claude`, every `gpt-` id and every Gemini id (F4). A `--user-instructed` flag lifts the refusal for the GPT and Gemini families on that run alone, never for Claude. When the flag admitted a run, the proxy's ledger lines carry it, so an audit of a bill can see which runs were instructed; on a model the launcher does not refuse, the flag changes nothing and leaves no mark. The skill tells the caller to pass the flag only when the user said so for the run at hand.

Rejected alternatives: an absolute refusal, which leaves no way to honour the user's instruction when a subscription is spent; the prose rule with no enforcement, which is the state F4 describes.

Cost: one flag, its tests, and one sentence in the skill. Remove when: the launcher is removed.

## 5. Slices and acceptance criteria

Suite criteria run under `content-tests`. Scenario criteria use the protocol in 5.4. Each criterion states the obligation, then its check.

### Slice A: the inventory lint

- **DEL-A1** Adding a sentence that names a model id absent from the routing table to any Markdown file under `src/` outside an `evals/` directory makes `content-tests` exit non-zero, and the failure names the file and the id. Check: suite, two cases per vendor id pattern (Claude, GPT, Gemini as agy id, Gemini as OpenRouter id, Kimi, GLM), an invented id and a listed id with its version number changed, plus one case in a file three directories below `src/`.
- **DEL-A2** On the tree the slice lands on, every model id in the `src/` Markdown the lint reads is present in the routing table, and no table row outside it names one. Check: the lint's own suite member, run at the landed head, exits 0 and reports the files it read.
- **DEL-A3** A fenced example naming a listed id passes, and removing that id's row from the table makes the same example fail. Check: suite, with a fixture table.
- **DEL-A4** A Markdown file under an `evals/` directory beneath `src/` is not read by the lint. Check: suite, a fixture naming an unlisted id passes under an `evals/` directory directly beneath a skill and under one nested two levels deeper.
- **DEL-A5** A routing table that is absent, or that lists no model id, makes the lint fail and name the table, whatever the other files hold. Check: suite, one case each.
- **DEL-A6** Among the files the lint reads, a Markdown table row outside the routing table that names a model id, listed or not, makes `content-tests` exit non-zero, and the failure names the file and the line. Check: suite: a copied routing-table row fails; a row with only a listed id, a tier and an effort fails; a two-column row holding an id and a purpose fails, written with and without outer pipes; the same id in a prose sentence passes.
- **DEL-A7** A routing table whose tier grid has a column other than the four providers, whose models table has a column other than provider, model, price, context and accepted efforts, or that holds a third table, makes the lint fail and name the column or table. Check: suite, one case each.

### Slice B: the OpenRouter launcher's clock

- **DEL-B1** With `--timeout N`, a child still running when the expiry tick is processed is ended within ten seconds of the expiry, including a child that ignores `SIGTERM` and a run whose upstream response is still open. (A child that exits on that same tick is governed by DEL-B3.) The proxy stops listening, the launcher exits 75, stderr carries `[run] reason=timeout`, and no process in the child's process group survives. A descendant that left the group is outside this guarantee. Check: suite with an injected clock over four fake children: compliant, ignoring `SIGTERM`, having started a child of its own in the group, and holding an upstream response open; plus one case on the real clock with N of one second.
- **DEL-B2** With `--idle-timeout M`, a run that forwards no completion request for M seconds ends as DEL-B1 does with `[run] reason=idle`. A run that forwards one request every M minus one seconds is not ended by this flag. A run that forwards one request and then none for M seconds is ended. Check: suite, fake child, injected clock, scripted request times.
- **DEL-B3** With both flags, whichever expires first decides the reason; when both expire on one tick the reason is `timeout`. A child that exits on its own before an expiry, or on the same tick as one, yields its own exit code and no reason line. Check: suite, five orderings.
- **DEL-B4** With neither flag, the argv and environment the child receives equal, for the same input, those the launcher built before this slice. Check: suite, comparing against fixtures recorded from the pre-slice launcher for three inputs, with the kernel-assigned proxy port replaced by a placeholder; the existing suite also passes unchanged.
- **DEL-B5** A non-numeric, zero or negative value for either flag, or a flag given with no value, exits 78 before the proxy binds, with stderr naming the flag. Check: suite, one case each.
- **DEL-B6** `SIGTERM` or `SIGINT` delivered to the launcher while the child is alive ends the child, and the launcher exits within ten seconds with no process in the child's process group surviving, including when the child ignores the signal. When a signal and an expiry fall on one tick, the launcher reports `reason=signal`. Check: suite, one case per signal with a fake child that ignores it and has started a child of its own in the group, and one case with the signal and the expiry on one tick.
- **DEL-B7** With either flag present, neither the argv nor the environment the child receives carries the flag or its value, and both otherwise equal what the child receives without the flags. Check: suite, fake child recording its argv and environment, one case per flag and one with both.

### Slice C: the launcher skills answer the same questions

- **DEL-C1** A reader holding only `delegating-to-codex` classifies three captured endings of a read-only run correctly (finished; still running at minute 26 after the Bash call was backgrounded; usage limit reached) and, asked to stop a running one, names the process it launched by its pid. Check: scenario protocol 5.4, scenarios C1a to C1d.
- **DEL-C2** A reader holding only `openrouter-claude-subagent` names the two flags that bound a run, states what each expiry does and what the launcher reports, states how to end a run early as a signal to the launcher, names the effort for a single-pass read of a whole artifact on `moonshotai/kimi-k3`, and states the measured durations of F9. Check: scenario protocol 5.4, scenarios C2a to C2e, keyed on the flag names, the exit and reason line DEL-D4 states, the signal, `low`, and the two durations.
- **DEL-C3** A reader holding one launcher skill names the outcome, of the four `choosing-a-delegate` defines, for each failure signal that skill documents, its invocation refusals included. A reader holding `harvest.md`, and a reader holding `ac-attack`'s skill, each name the response for every case: the claim reason for the provider not serving the run and for unusable output, "fix the invocation" for a refusal, "ingest, no claim" for usable output, and "stop" for a run the caller itself signalled. Check: scenario protocol 5.4, one scenario per documented signal per launcher skill, and five per caller skill. The signal list holds every signal the three skills document once slice C's own text is in them, including the OpenRouter launcher's `timeout` and `idle` reasons, each launcher's refusals and the Codex usage limit; it is cross-checked against each launcher script's exit codes and reason lines, and a signal the script emits that its skill does not document fails the criterion. The list is committed with the scenarios, keyed on the reason names in force at the head slice C lands on.
- **DEL-C4** No Markdown file under `src/` instructs a reader to launch a Codex run through the `codex` binary, and `harvest.md` and `ac-attack` name the Codex delegation skill's read-only run as the way a Codex reviewer is launched. Check: the reviewer of the slice's pull request reads every line of `src/` Markdown matching `codex` in any letter case, `delegating-to-codex` included, and records the number of lines read, that none gives that instruction, and the sentence in each of the two files that names the skill.
- **DEL-C5** The OpenRouter skill's description and body both name `Edit(<path>)` as the grant for a mandated report file. Check: the reviewer of the slice's pull request reads both passages and records the grant form each names.
- **DEL-C6** The read-only run command a reader holding only `delegating-to-codex` writes, run against a stub companion that records its invocation, prints a fixed report on stdout and refuses every write, leaves that report in the file the reader named, and the recorded invocation asks for a read-only run in the form the Codex plugin's runtime documents at the slice's head. Check: scenario protocol 5.4, scenario C6, keyed on the file's content and on the recorded invocation after the returned command runs against the stub.
- **DEL-C7** In every file slice C changes, the text outside the passages DEL-D3 and DEL-D5 name is unchanged. Check: the reviewer of the slice's pull request reads the slice's diff and records each hunk against the passage it belongs to.
- **DEL-C8** A reader holding only `delegating-to-codex`, whose companion call was moved to the background before the run finished, returns the report once the run finishes. Check: scenario protocol 5.4, scenario C8. The stub companion prints nothing for a fixed delay after the reader's call returns, then writes the completion line and a report holding a token generated for that run, and exits only after a further delay, recording its exit time. The key is that token in the reader's answer together with the reader's statement that the process has exited, given after the recorded exit.
- **DEL-C9** No Markdown file under `src/` outside the review panel and `ac-attack` uses the word "lens" for a run; `choosing-a-delegate` names the four outcomes in one passage and no other file under `src/` defines them; the passages slice C changes in `harvest.md` and `ac-attack` quote no launcher's exit code, reason line or error text; and the passages it changes in the three launcher skills use no panel word. Check: the reviewer of the slice's pull request reads every line of `src/` Markdown matching `lens` in any letter case outside those two skills and records the count and that each remaining use is a launcher's own command name; records the passage that names the four outcomes and a search for each outcome's name showing no second definition; and records, per changed passage, that it holds no text of the other side.

### Slice D: the agy launcher passes the model and the effort through

- **DEL-G1** `agy_run.py worker --model gemini-3.8-flash --effort low ...` spawns agy with `--model gemini-3.8-flash` and `--effort low` in its argv, each value unchanged, and the same holds for `lens`. Check: suite, fake spawn seam, one case per mode, asserting both flags and both values in the recorded argv.
- **DEL-G2** A selection agy refuses is spawned as given, and agy's refusal reaches the caller as a refused invocation: exit 78, agy's message on stderr, an `agy_run.py:` line saying agy refused the selection, and no reason line. The launcher holds no list of levels or models. Check: suite, fake spawn that exits 1 with the `invalid model selection` message F17 records, one case each for a level the model lacks (`medium` on `gemini-3.1-pro`), a variant id with a conflicting `--effort`, an unknown model, and a bare model with no `--effort`; and one case passing `--effort zzz`, a level agy has never offered, which the launcher spawns unchanged.
- **DEL-G3** A missing `--model`, or an `--effort` given with no value, exits 78 before anything spawns, with stderr naming the flag. Check: suite, one case each, asserting the spawn seam was not called.
- **DEL-G4** Every other argv, exit code and stderr line of the launcher is unchanged. Check: the existing suite passes with no edit other than deleting the case that asserts `--effort` is refused.
- **DEL-G5** The commands a reader holding only `delegating-to-agy` and the routing table writes for a cheap-tier Google read-only run and for a cheap-tier Google worker run each pass the model and the level as two flags and compose no id by hand, and when run against the launcher with a fake spawn seam each spawns agy with those two flags. Check: scenario protocol 5.4, scenarios G5a and G5b, keyed on the two flags in each command and on the same two flags and values in each recorded spawn argv.
- **DEL-G6** No Markdown file under `src/` instructs a reader to form an agy model id by appending an effort suffix, and none says agy takes the effort only in the model id. Check: the reviewer of the slice's pull request reads every line of `src/` Markdown matching `-low`, `-medium`, `-high`, `suffix`, `append` or `agy` in any letter case, and records the count and that none gives that instruction or makes that statement.
- **DEL-G7** A run with `--model` and no `--effort` spawns agy with no `--effort` in its argv, so a full variant id runs as it does today. Check: suite, fake spawn seam, one case per mode with `--model gemini-3.8-flash-low`, asserting the argv carries that model value and no `--effort`; and the bare-model case of DEL-G2, whose recorded argv also carries no `--effort`.
- **DEL-G8** On an installed agy of 1.2.11 or later, a `lens` run through `agy_run.py` with `--model gemini-3.8-flash --effort low`, over a one-commit repository and a prompt asking for the first line of one file, exits 0 with that line in its response. The same run with `--model gemini-3.1-pro --effort medium` exits 78 with agy's message naming `low, high` on stderr. Check: the implementer performs both runs once and records the agy version, each command and its output in the slice's pull request. The criterion stays pending while the Google subscription quota is spent.
- **DEL-G9** An agy that refuses the `--effort` flag itself, as one older than 1.2.11 does, is reported as any agy error is today: exit 75, `reason=error`, and agy's message on stderr. Check: suite, fake spawn that exits non-zero with an unknown-flag message that is not an `invalid model selection` line.

### Slice E: one word for the provider

- **DEL-V1** No Markdown file under `src/` uses "route" or "transport" for the provider, and every mention of a provider names one of the four values. Check: the reviewer of the slice's pull request reads every line of `src/` Markdown matching `route`, `transport` or `provider` in any letter case, and records the count, that each remaining `route` or `transport` means something else, and that every provider named is one of the four.
- **DEL-V2** `contracts.json` and every `ac-attack` lens front matter carry `provider` with one of the four values, and `emit_prompts.py` refuses a lens carrying `transport`, an unknown provider value, or no provider at all, each with a coded error. Check: suite, one case each.
- **DEL-V3** `dispatch_gate.py claim` takes `--provider` with one of the four values, records it, and refuses `--transport`. Its ledger and the verdict envelope carry `provider` and `provider_error` where they carried `transport` and `transport_error`, under a bumped schema version that `review-verdict` documents. A ledger or a verdict from the previous schema version is refused with a coded error naming the field, never migrated, so a round in flight finishes on the version it started on. The slice re-keys DEL-C3's committed scenarios to the renamed reasons. Check: suite, including the refusals, and the re-keyed scenarios run once.
- **DEL-V4** `prgroom post-verdict` renders a verdict of the bumped schema and names each lens's provider. Check: prgroom's suite, with a fixture verdict of the new version.
- **DEL-V5** `assemble_verdict.py` counts distinct vendors from the provider that actually ran each lens, resolving `openrouter` to the model's vendor prefix, so lenses on `openai` and `openrouter` count as two vendors only when the OpenRouter model is not an OpenAI model. Check: suite.
- **DEL-V6** In every file slice E changes, the text outside the renamed terms and the re-keyed reasons is unchanged. Check: the reviewer of the slice's pull request reads the slice's diff and records each hunk as a rename, a re-key, or neither; a hunk that is neither fails.

### Slice F: the launcher honours the instruction rule

- **DEL-F1** `run.js` with `--model` naming any `gpt-` id, the formerly exempt `gpt-5.5-mini` and `gpt-5.6-mini` included, or any Gemini id, in any vendor prefix or `:variant` form, exits 78 before the proxy binds, with stderr naming the family and the flag that lifts the refusal. A Claude id exits 78 the same way with no flag named. Check: suite, one case per family and per spelling.
- **DEL-F2** The same invocation with `--user-instructed` starts the run on that model, the proxy forwards its completion requests, and every ledger line for the run carries `user-instructed`, because the flag admitted it. Check: suite, fake child and fake upstream.
- **DEL-F3** `--user-instructed` with a Claude id still exits 78 before the proxy binds. Check: suite.
- **DEL-F4** `--user-instructed` on a model the launcher does not refuse changes nothing: argv, environment, exit code and ledger equal the run without the flag. Check: suite.
- **DEL-F5** The proxy refuses a completion request for a GPT or Gemini model it was not started with the flag for, pin or no pin, with `decision=deny-denylist` in its ledger. Check: suite.
- **DEL-F6** A reader holding only `openrouter-claude-subagent` passes the flag when the scenario's user instructed the run at hand, and withholds it when the user merely asked for a cheap Gemini run and when the user instructed an earlier run but not this one. Check: scenario protocol 5.4, scenarios F6a to F6c.

### 5.4 Scenario protocol

A scenario gives a fresh native subagent on the `mid` tier the named files and one captured input, and asks one question with a closed answer set. No other context is supplied. Each scenario runs three times. A criterion passes when every run of every one of its scenarios returns the keyed answer. The scenarios, their captured inputs and their keys are written before the prose they test and are committed beside the evidence sidecar. The acceptance authority is the key. A run that returns no answer is a failed run and is not retried.

## 6. Owner decisions

Settled with the owner on 2026-10-03:

- The OpenRouter mid seat is `z-ai/glm-5.3`, the mid cell of the `openrouter` column.
- A whole-artifact read on `moonshotai/kimi-k3` runs at `low`, stated once in the OpenRouter launcher skill.
- The OpenRouter launcher refuses every GPT and every Gemini model unless the user instructed the run (DEL-D10).
- The provider rename goes through the verdict schema (DEL-D8).

No question is open.

## 7. Slices and order

Six slices implement this spec. Each is a feature, and each is promoted with `work promote` before implementation.

| Slice | Feature | Criteria | Work item |
| --- | --- | --- | --- |
| A | A lint keeps the routing table the only model inventory | DEL-A1 to DEL-A7 | `agents-config-9k9.458.3` |
| B | The OpenRouter launcher times and kills its own run | DEL-B1 to DEL-B7 | `agents-config-9k9.458.4` |
| C | The launcher skills answer the same four questions | DEL-C1 to DEL-C9 | `agents-config-9k9.458.5` |
| D | The agy launcher and its skill take effort the way agy itself accepts it | DEL-G1 to DEL-G9 | `agents-config-9k9.469` |
| E | One word, provider, through the panel's prose, data, scripts and verdict schema | DEL-V1 to DEL-V6 | `agents-config-9k9.458.6` |
| F | The OpenRouter launcher refuses GPT and Gemini models unless the user instructed the run | DEL-F1 to DEL-F6 | `agents-config-9k9.458.7` |

Ordering: slice C lands after slices B and D, because DEL-C2 reads the flags slice B adds and the agy launch section it preserves is the two-flag one. Slice E lands last and after `agents-config-9k9.408`'s remaining pull requests, because it renames the field they edit. Slice F supersedes the denylist half of pull request 772, which is reworked or closed against it. Outside this spec's criteria, `agents-config-9k9.408` is reworked under DEL-D2, and a new item updates prgroom's chains under DEL-D7.

## Continuations

The six slices, in the form `work deliver` reads. The work items in the table above already exist under the implementation placeholder with these titles, so delivery adopts them and mints nothing.

- feat: A lint keeps the routing table the only model inventory — AC: DEL-A1, DEL-A2, DEL-A3, DEL-A4, DEL-A5, DEL-A6, DEL-A7
- feat: The OpenRouter launcher times and kills its own run — AC: DEL-B1, DEL-B2, DEL-B3, DEL-B4, DEL-B5, DEL-B6, DEL-B7
- feat: The launcher skills answer the same four questions — AC: DEL-C1, DEL-C2, DEL-C3, DEL-C4, DEL-C5, DEL-C6, DEL-C7, DEL-C8, DEL-C9
- feat: The agy launcher and its skill take effort the way agy itself accepts it — AC: DEL-G1, DEL-G2, DEL-G3, DEL-G4, DEL-G5, DEL-G6, DEL-G7, DEL-G8, DEL-G9
- feat: One word, provider, through the panel's prose, data, scripts and verdict schema — AC: DEL-V1, DEL-V2, DEL-V3, DEL-V4, DEL-V5, DEL-V6
- feat: The OpenRouter launcher refuses GPT and Gemini models unless the user instructed the run — AC: DEL-F1, DEL-F2, DEL-F3, DEL-F4, DEL-F5, DEL-F6
