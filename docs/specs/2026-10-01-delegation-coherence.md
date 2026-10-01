# Delegation skills and rules as one system

**Date:** 2026-10-01
**Status:** Child spec of `docs/specs/2026-07-21-harness-rework-way-forward.md` (D5 foreign eyes in review seats, D16 removal conditions). Draft for review. One criteria attack ran on 2026-10-01; its record is `docs/specs/2026-10-01-delegation-coherence-ac-attack.json`.
**Work item:** `agents-config-9k9.458`, design child `agents-config-9k9.458.1`.
**Related:** `agents-config-9k9.457` (the one model routing table, pull request 803), `agents-config-9k9.408` (review-seat pins, pull requests 772 to 774), `agents-config-9k9.17.29` (review-panel Gemini seats on agy).
**Quality contract:** `docs/specs/2026-09-18-acceptance-criteria-quality.md`. **Lifecycle:** `docs/specs/2026-09-18-acceptance-criteria-lifecycle.md`.

## 1. Problem statement

Nine artifacts decide, brief, launch and supervise delegated agents. They are the `choosing-a-delegate`, `delegating-to-codex`, `delegating-to-agy`, `openrouter-claude-subagent`, `instructing-subagents` and `orchestrating-teammates` skills, the review panel's harvest doctrine, the `ac-attack` skill's transport paragraph, and the user rule on delegation. They were written one at a time. An agent that follows one of them can be contradicted by another, and some rules an agent needs are written in none of them.

This spec audits the set as it stands on 2026-10-01 and decides, finding by finding, whether to converge, correct or leave alone. A change is proposed only where its return exceeds its cost, and deleting surface is preferred to adding it.

## 2. Scope

In scope: the nine artifacts above; the model routing table they cite; the OpenRouter launcher's supervision behaviour; a lint that keeps the routing table the only model inventory.

Out of scope: the content of the review-seat pins and the roster moves that `agents-config-9k9.408` owns; routing review-panel Gemini seats to agy (`agents-config-9k9.17.29`); prgroom's dispatcher chains, which are package code with their own release rule; the brief format `instructing-subagents` teaches; the user's memory files, which no repository gate can read.

## 3. Audit findings

Each finding was verified against the tree at main `c90c0001` plus pull request 803 on 2026-10-01. "Route" means one of the four ways a run is launched: native, Codex, agy, OpenRouter.

| # | Finding | Kind |
| --- | --- | --- |
| F1 | After pull request 803 one file under `src/` carries model prices, efforts and tiers: the routing table beside `choosing-a-delegate`. Nothing mechanical keeps it the only one. The example commands in `review-panel`'s `harvest.md` and in the OpenRouter skill name model ids, and nothing fails when such an id leaves the table. | Unguarded |
| F2 | Pull request 772 (`agents-config-9k9.408`, open since 2026-09-17) adds review-seat pin rows to the OpenRouter skill's routing reference and to the Codex skill's table. Pull request 803 deletes the first file and removes the second table. The two changes cannot both merge as written. | Conflict |
| F3 | `agents-config-9k9.408` pins the OpenRouter mid review seat to `google/gemini-3.8-flash`. The routing table states that a Gemini model on OpenRouter is the agy fallback and never a pick. | Contradiction |
| F4 | `agents-config-9k9.408` settles that the OpenRouter launcher refuses every `gpt-` id with no `-mini` exemption. Pull request 803 adds a `gpt-6` prefix and keeps the exemption for the 5.5 and 5.6 prefixes. | Divergence |
| F5 | `agents-config-9k9.408` runs a whole-artifact read on `moonshotai/kimi-k3` at `medium`, a level that model does not list. The routing table says `low`. | Divergence |
| F6 | `delegating-to-codex` says the raw `codex` binary "stays forbidden either way". `harvest.md` and the `ac-attack` skill both say a codex lens runs "through the codex command-line tool". A reader of the second pair is told to do what the first forbids. | Contradiction |
| F7 | No artifact under `src/` says how a Codex review lens is launched. The working procedure exists only in the owner's memory files: the caller's shell redirects the companion call's output to the claimed file because Codex's sandbox is read-only; the caller waits on the process it launched and on its own capture file; a usage-limit failure is exit 1 with `You've hit your usage limit` on stderr and means the route is down. | Missing |
| F8 | `delegating-to-codex` prescribes a Bash timeout of about 1,500,000 ms, which is 25 minutes, and calls a backgrounded call a dead agent. Whole-spec runs on the frontier Codex tier were measured at 24 to 28 minutes on 2026-09-30 and finished after being backgrounded. The skill's rule declares a live run dead. | Wrong |
| F9 | The agy launcher owns its clock: `--timeout`, a watchdog, a kill of the process group, and exit 75 with a reason line. The OpenRouter launcher has no timeout flag and its skill gives no timeout or kill guidance. The caps a runner applies to an OpenRouter lens exist only in memory files. Three recorded runs on `moonshotai/kimi-k3` ended inside a thinking block, one after 67 minutes. | Missing |
| F10 | `harvest.md` distinguishes a dead route from a failed reviewer and bounds each differently. The agy skill maps its exits to "fail over" and "re-brief". Nothing maps the Codex and OpenRouter launchers' failure signals onto the same two reasons. | Missing |
| F11 | The OpenRouter skill's description tells a caller to add "a Write grant" for a mandated report file. Its body says a `Write(<path>)` grant is not matched and the grant must be `Edit(<path>)`. | Contradiction |
| F12 | The report-delivery protocol (an explicit send, the `UPDATE` and `FINAL REPORT` markers) is stated in `instructing-subagents`, restated in `orchestrating-teammates`, and pointed at by the delegation rule. The three agree. | Duplication, consistent |
| F13 | Failover order is stated in the routing table (route preference per family), in `harvest.md` (any lens may run on any live transport, recorded as a substitution) and in `ac-attack` (run the lenses over the other transport and say so). The three agree, and each serves a different record. | Duplication, consistent |
| F14 | prgroom's dispatcher chains name `gpt-5.6-luna` and `gpt-5.6-terra`. Both ids are live in Codex. They are absent from the routing table, which lists only the GPT-6 tiers. | Divergence, out of scope |

## 4. Decisions

Each decision states its cost and the observation that removes it.

**DEL-D1. The routing table stays the only model inventory, and a lint enforces it.** A content test reads every Markdown file under `src/`, except those under an `evals/` directory, and fails when one names a model id that the routing table does not list. A trigger query under `evals/` quotes what a user might type, and nothing under `evals/` deploys, so those files are exempt. The test also fails on a line outside the routing table that pairs a listed model id with a dollar price, which is the mark of a second inventory. The test owns a short list of id patterns, one per vendor naming scheme. Cost: one test file, and a pattern to add when a vendor invents a naming scheme. Remove when: the routing table itself is removed. Refuted alternative: review alone. Review catches a stale id in a changed file and cannot catch one in a file nobody is editing, which is how the five tables drifted apart.

**DEL-D2. Review-seat pins are rows of the routing table.** `agents-config-9k9.408`'s pins land as a review-seats section of the routing table, and pull request 772's table edits are re-made against it. Cost: rework of one open pull request. Remove when: `agents-config-9k9.408`'s own removal condition fires. Refuted alternative: pins in per-launcher tables, as pull request 772 is written. That restores the per-skill tables pull request 803 deletes. This decision constrains `agents-config-9k9.408` and adds no criterion here; section 6 lists the three settings the owner must reconcile first.

**DEL-D3. The route skills answer the same four questions, and this spec fills the gaps the audit found.** The questions are: which modes exist (a worker that may edit, a lens that only reads), how each is launched, what each failure signal means, and how a run is timed and killed. `delegating-to-agy` already answers all four. `delegating-to-codex` gains the lens launch and the long-run rule (F7, F8). `openrouter-claude-subagent` gains the timing section (F9). `harvest.md` gains one table mapping each launcher's failure signals onto its two reasons (F10), and `harvest.md` and `ac-attack` name the Codex route by its skill (F6). Text outside those passages does not change. Cost: about forty lines across four files. Remove when: each skill's own removal condition fires. Refuted alternatives: a shared supervision skill, which would hold three unlike procedures under one heading and add a hop before every launch; and leaving the procedures in memory files, which another machine, another tool and a reviewer never see.

**DEL-D4. The OpenRouter launcher owns its clock.** `run.js` gains `--timeout SECONDS` and `--idle-timeout SECONDS`. On expiry it ends the child, closes the proxy, and exits 75 with a reason line on stderr, the contract the agy launcher already has. Idle means no completion request forwarded for that long, which separates a model that is reading from one that is stranded. A flag value that is not a positive number is refused with exit 78 before the proxy binds, as every other bad invocation of this launcher is. A `SIGTERM` sent to the launcher ends the child even when the child ignores it, because a runner's own kill is the last resort when no flag was passed (F9). Cost: launcher code and its tests under `content-tests`. Remove when: the OpenRouter launcher is removed. Refuted alternative: a kill loop written into every runner brief. It is prose a runner may skip, and the 67-minute run is what skipping it costs.

**DEL-D5. The OpenRouter skill's description names the grant its body requires** (F11). Cost: one sentence. Remove when: the skill is removed.

**DEL-D6. The delivery protocol and the failover statements stay where they are** (F12, F13). Each restatement sits in the artifact an agent holds at the moment it needs the rule, and the copies agree. Merging them would save about ten lines and add a cross-skill read to every dispatch. This is the audit's "no convergence worth its cost" result for those two findings.

**DEL-D7. prgroom's chains stay in code** (F14). Their ids are valid, and moving them is a package release under that package's version rule. A separate work item updates them to the GPT-6 tiers.

## 5. Slices and acceptance criteria

Suite criteria run under `content-tests`. Scenario criteria use the protocol in 5.4.

### Slice A: the inventory lint

- **DEL-A1** With the tree otherwise unchanged, adding a sentence that names a model id absent from the routing table to any Markdown file under `src/` outside an `evals/` directory makes `content-tests` exit non-zero, and the failure names the file and the id. Check: suite, two cases per vendor id pattern (Claude, GPT, Gemini as agy id, Gemini as OpenRouter id, Kimi, GLM): an invented id, and a listed id with its version number changed.
- **DEL-A2** `content-tests` exits 0 on the tree the slice lands on, with every model id in `src/` Markdown present in the routing table. Check: the gate itself at the landed head.
- **DEL-A3** A fenced example that names an id the routing table lists passes, and removing that id's row from the table makes the same example fail. Check: suite, with a fixture table.
- **DEL-A4** A Markdown file under an `evals/` directory beneath `src/` is not read by the lint. Check: suite, an `evals/` fixture naming an unlisted id passes.
- **DEL-A5** A routing table that is absent, or that lists no model id, makes the lint fail and name the table, whatever the other files hold. Check: suite, one case each.
- **DEL-A6** A Markdown file under `src/` other than the routing table that pairs a listed model id with a dollar price on one line makes `content-tests` exit non-zero, and the failure names the file and the line. Check: suite, a fixture holding a copied table row fails, and the same row with its price removed passes.

### Slice B: the OpenRouter launcher's clock

- **DEL-B1** With `--timeout N`, a child still running N seconds after launch is ended within ten seconds of the expiry, including a child that ignores `SIGTERM`. The proxy stops listening, the launcher exits 75, stderr carries `[run] reason=timeout`, and no child process survives. Check: suite, one compliant fake child and one that ignores `SIGTERM`, with an injected clock.
- **DEL-B2** With `--idle-timeout M`, a run that forwards no completion request for M seconds ends as DEL-B1 does with `[run] reason=idle`; a run that forwards one request every M minus one seconds is not ended by this flag. Check: suite, fake child, injected clock, scripted request times.
- **DEL-B3** With both flags, whichever expires first decides the reason, and when both expire on one tick the reason is `timeout`. A child that exits on its own before an expiry, or on the same tick as one, yields its own exit code and no reason line. Check: suite, five orderings.
- **DEL-B4** With neither flag, the argv the child receives and the child's environment equal, for the same input, those the launcher built before this slice. Check: suite, comparing against fixtures recorded from the pre-slice launcher for three inputs, with the kernel-assigned proxy port replaced by a placeholder; the existing suite also passes unchanged.
- **DEL-B5** A non-numeric, zero or negative value for either flag exits 78 before the proxy binds, with stderr naming the flag. Check: suite.
- **DEL-B6** `SIGTERM` delivered to the launcher while the child is alive ends the child, and the launcher exits within ten seconds with no child surviving, including when the child ignores `SIGTERM`. Check: suite, a fake child that ignores the signal.

### Slice C: the route skills answer the same questions

- **DEL-C1** A reader holding only `delegating-to-codex` classifies each of three captured endings correctly: finished; still running at minute 26, after the Bash call was backgrounded; and usage limit reached. Check: scenario protocol 5.4, scenarios C1a to C1c.
- **DEL-C2** A reader holding only `openrouter-claude-subagent` and the routing table states the timeout flags and the effort to pass for a whole-artifact lens on the table's frontier OpenRouter row and for a worker on its mid row, and the launcher at the same head accepts those flags. Check: scenario protocol 5.4, scenarios C2a and C2b; each returned flag set is then passed to the launcher with a refused model id, and the run exits 78 naming the model and no flag.
- **DEL-C3** A reader holding `harvest.md` names the right response to every failure signal the three launchers document: the claim reason `transport-error`, the claim reason `unusable-output`, or "fix the invocation" for a launcher refusal. Check: scenario protocol 5.4, one scenario per documented signal. The list of signals is read from the three skills at the head the slice starts from and is committed with the scenarios.
- **DEL-C4** No Markdown file under `src/` instructs a reader to launch a Codex run through the `codex` binary, and `harvest.md` and `ac-attack` name the Codex delegation skill as that route. Check: the reviewer of the slice's pull request reads every line of `src/` Markdown outside `delegating-to-codex` that matches `codex` in any letter case, and records the number of lines read and that none gives that instruction.
- **DEL-C5** The OpenRouter skill's description and body both name `Edit(<path>)` as the grant for a mandated report file. Check: the reviewer of the slice's pull request reads both passages and records the grant form each names.
- **DEL-C6** The lens launch command a reader holding only `delegating-to-codex` writes, run against a stub companion that prints a fixed report on stdout and refuses every write, leaves that report in the file the reader named. Check: scenario protocol 5.4, scenario C6, keyed on the file's content after the returned command runs against the stub.
- **DEL-C7** In every file slice C changes, the text outside the passages DEL-D3 and DEL-D5 name is unchanged. Check: the reviewer of the slice's pull request reads the slice's diff and records each hunk against the passage it belongs to.

### 5.4 Scenario protocol

A scenario gives a fresh native subagent on the `mid` tier the named files and one captured input, and asks one question with a closed answer set. No other context is supplied. Each scenario runs three times. A criterion passes when every run of every one of its scenarios returns the keyed answer. The scenarios, their captured inputs and their keys are written before the prose they test and are committed beside the evidence sidecar. The acceptance authority is the key. A run that returns no answer is a failed run and is not retried.

## 6. Open questions for the owner

Three settings differ between `agents-config-9k9.408`, settled on 2026-09-17, and the routing table of 2026-10-01. Each blocks the rework DEL-D2 asks for, and none blocks the slices above.

1. **The OpenRouter mid review seat** (F3). Options: `z-ai/glm-5.3`, which keeps the two OpenRouter seats on different vendors without a Gemini model; or hold the seat for an agy lens under `agents-config-9k9.17.29`. Recommended: `z-ai/glm-5.3` now.
2. **The GPT denylist** (F4). Options: refuse every `gpt-` id with no exemption, as settled on 2026-09-17; or keep the `-mini` exemption. Recommended: refuse every `gpt-` id, since Codex serves every tier.
3. **The effort for a whole-artifact read on `moonshotai/kimi-k3`** (F5). Options: `low`, a level the model lists and two measured reads finished on; or `medium`, which reaches it as a thinking budget. Recommended: `low`.

## 7. Continuations

Use `work promote` on each resulting feature before implementation.

- feat: a lint keeps the routing table the only model inventory. AC: DEL-A1, DEL-A2, DEL-A3, DEL-A4, DEL-A5, DEL-A6
- feat: the OpenRouter launcher times and kills its own run. AC: DEL-B1, DEL-B2, DEL-B3, DEL-B4, DEL-B5, DEL-B6
- feat: the route skills answer the same four questions. AC: DEL-C1, DEL-C2, DEL-C3, DEL-C4, DEL-C5, DEL-C6, DEL-C7

Slice C lands after slice B, because DEL-C2 reads the flags slice B adds. Outside this spec's criteria: `agents-config-9k9.408` is reworked under DEL-D2 once section 6 is answered, and a new item updates prgroom's chains under DEL-D7.
