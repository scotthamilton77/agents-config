---
name: optimize-my-skill
model: sonnet[1m]
allowed-tools: Read, Write, Edit, Glob, Grep, AskUserQuestion
description: Audits and improves existing SKILL.md files for discoverability, progressive disclosure, and methodology rigor. Use when asked to optimize a skill, when reviewing a skill folder for quality, or when a SKILL.md needs frontmatter or body cleanup. Do NOT use for agent persona files or AGENTS.md configuration files.
---

<!--
Sources (amalgam):
  - Native (audit/assess methodology — Phases 1–3, 6)
  - oss-snapshots/anthropics/skill-creator/
    Upstream: https://github.com/anthropics/skills @ f458cee31a7577a47ba0c9a101976fa599385174
Last sync: 2026-05-20
Drift policy: accept-periodic-resync

Dormant scripts:
  - scripts/quick_validate.py — amalgamated verbatim but currently dormant (no live callers). Kept per the accept-periodic-resync drift policy pending a future wire-or-delete decision.

Known divergences from upstream `anthropics/skill-creator @ f458cee`:
  Kept verbatim per drift policy; future decision per item = upstream PR /
  document-and-accept / local divergence (TBD). Each entry below is a known
  defect we have consciously chosen NOT to locally patch.

  - scripts/eval-viewer/generate_review.py — `_kill_port()` SIGTERMs any PID returned by `lsof -ti :<port>`, which is risky in dev workspaces (can kill unrelated user services; PermissionError when the PID is owned by another user; lsof unavailable on some platforms).
  - scripts/eval-viewer/generate_review.py — `find_runs()` sorts by `(eval_id, id)` where `eval_id` may be string-typed in JSON, raising TypeError in Python 3 when mixing string/numeric keys.
  - scripts/run_loop.py — `split_eval_set()` can produce an empty `train_set` for very small eval sets (always reserves ≥1 per bucket for test_set, leaving nothing for training).
  - scripts/quick_validate.py — PyYAML stdlib gap: the script `import yaml` requires the third-party `pyyaml` package which is not in the Python stdlib. (Naturally moot while the script remains dormant per the note above, but the import concern is documented here for the eventual wire-or-delete decision.)
  - scripts/aggregate_benchmark.py — `aggregate_results()` uses insertion-order of the first two configuration keys to pick baseline vs primary, which can silently flip if input ordering changes and becomes meaningless with >2 configs.
-->

# Optimize My Skill

Audit and improve existing SKILL.md files for clarity, discoverability, and effectiveness. This skill is for *auditing and improving* existing skills — if a `writing-skills` skill is available (e.g. `superpowers:writing-skills`), prefer it for *creating* new skills from scratch.

## Core Principle

**Audit before writing.** Read the existing skill completely before proposing any change — never rewrite content you haven't fully understood.

## Boundaries (default: audit-only)

Phases 1–5 are **read-only against the target skill folder**. The skill discovers, assesses, proposes, and (under `--deep`) measures — but it does not modify any target `SKILL.md`, frontmatter, or body content until **Phase 6** has user confirmation. The only writes permitted before Phase 6 are workspace artifacts under `<skill-dir>/.eval-runs/` (gitignored) and the eval set draft at `<skill-dir>/evals.json` (Phase 4a, user-reviewed before the loop runs).

A run that silently mutates a target SKILL.md during audit is a defect, not a feature, regardless of how well-intentioned the change.

## Phase 1: Discover and Read

Find all SKILL.md files in the target scope. For each one, read the complete file (frontmatter + body) and also check the skill's folder structure.

Scope resolution from the invoking command's argument:

- **Specific skill name** (e.g. `bugfix`, `writing-unit-tests`) — search for a folder whose `name` frontmatter field or directory name matches. Optimize that single skill.
- **Directory path** (e.g. `~/.claude/skills/` or `.claude/skills/`) — enumerate every immediate subdirectory containing a `SKILL.md`. Optimize all of them.
- **Empty argument** — the command layer is responsible for probing default locations and either passing a resolved path or aborting with a "no skills found" message. This skill expects a resolved scope.

For each discovered skill, also inventory:

- Presence of `scripts/` (executable code for deterministic operations)
- Presence of `references/` (detailed docs, API guides, lengthy examples)
- Presence of `assets/` (templates, fonts, icons used in output)
- Any stray `.md` files at the top level (only `SKILL.md` belongs there)

## Phase 2: Assess Against Quality Criteria

Rate each skill against the following areas. Produce a written assessment for every skill in scope before proposing changes.

### Frontmatter

Per SKILLS_PRIMER (see `references/SKILLS_PRIMER.md`):

**Required fields:**

| Criterion | Good | Bad |
|-----------|------|-----|
| **name** | lowercase-kebab-case, matches folder name | camelCase, spaces, uppercase, mismatched |
| **description** | Explains WHEN to invoke with concrete triggers | Explains what the skill does generically |
| **description** | Single line, under 1024 characters | Multi-line YAML (`>` or `\|`), or over limit |
| **description** | Mentions observable situations | Lists abstract keywords |
| **description** | Includes negative triggers ("Do NOT use for...") where appropriate | No scope boundaries, risks over-triggering |

**Security checks** (fail the skill if violated):

- [ ] No XML angle brackets (`<` or `>`) in frontmatter values
- [ ] Name does not contain "claude" or "anthropic" (reserved)

**Optional fields** (flag if present but malformed, suggest if beneficial):

| Field | Purpose | Validation |
|-------|---------|------------|
| **license** | Open-source license identifier | Valid SPDX (MIT, Apache-2.0, etc.) |
| **allowed-tools** | Restrict tool access | Space-separated (e.g. `"Bash(python:*) WebFetch"`) or comma-separated (e.g. `Read, Write, Edit`) — both accepted by Claude Code |
| **compatibility** | Environment requirements | 1-500 characters |
| **metadata** | Custom key-value pairs | Valid YAML object; suggest: author, version, mcp-server |

**Description formula that works:** `[What it does]. Use when [situation A], [situation B], or [situation C]. Do NOT use for [exclusion].`

Examples of effective descriptions:

- "Use when encountering a bug with unclear origins, when multiple files could be involved, or when the symptom does not obviously point to a single root cause"
- "Use when writing unit tests, reviewing test code, or when asked to add tests to complex/untestable code"
- "Manages Linear project workflows including sprint planning and task creation. Use when user mentions 'sprint', 'Linear tasks', or 'project planning'. Do NOT use for general task lists unrelated to Linear."

Examples of ineffective descriptions:

- "Testing helper: test, vitest, jest, coverage, fix suite" (keyword stuffing — Claude isn't a search engine)
- "Helps write better code" (vague, no trigger context)
- "A skill for debugging" (describes what, not when)

### Folder Structure (Progressive Disclosure)

Per SKILLS_PRIMER (see `references/SKILLS_PRIMER.md`): skills use a three-level progressive disclosure system to minimize token usage:

| Level | What | Loaded When |
|-------|------|-------------|
| **1. Frontmatter** | name + description | Always (system prompt) |
| **2. SKILL.md body** | Full instructions | When skill is triggered |
| **3. Linked files** | references/, scripts/, assets/ | On demand within the skill |

Assess:

- [ ] **SKILL.md is the only `.md` file**: No README.md inside the skill folder (all docs go in SKILL.md or references/)
- [ ] **SKILL.md size**: Under 500 lines. If over, flag sections that should move to `references/`
- [ ] **Heavy content in references/**: Detailed docs, API guides, lengthy examples belong in `references/`, linked from SKILL.md
- [ ] **Scripts in scripts/**: Executable code (Python, Bash) for deterministic operations lives in `scripts/`
- [ ] **Templates in assets/**: Templates, fonts, icons used in output belong in `assets/`

### Body Content

Per SKILLS_PRIMER (see `references/SKILLS_PRIMER.md`):

| Criterion | Present? | Quality (1-5) | Notes |
|-----------|----------|---------------|-------|
| **Core principle** | | | One-sentence iron law the skill enforces |
| **When to use / When not to use** | | | Clear decision criteria, ideally a decision tree |
| **The process** | | | Step-by-step methodology, not vague advice |
| **Concrete examples** | | | Good vs bad patterns with real code |
| **Red flags / rationalizations** | | | Table of excuses and rebuttals |
| **Verification checklist** | | | How to confirm the skill was applied correctly |
| **Error handling** | | | What to do when things go wrong |

### Anti-Patterns to Flag

- [ ] Generic advice Claude would follow without being told ("write clean code")
- [ ] Descriptions instead of examples for code patterns
- [ ] No explicit "when NOT to use" criteria (over-triggering risk)
- [ ] No negative triggers in description (over-triggering risk)
- [ ] Process steps that are vague imperatives ("be careful", "consider")
- [ ] Missing decision trees for ambiguous situations
- [ ] No red flags section (skill gets rationalized away)
- [ ] Body content duplicates what's in the frontmatter description
- [ ] SKILL.md over 500 lines without using references/ for overflow
- [ ] README.md inside the skill folder
- [ ] XML angle brackets in frontmatter

## Phase 3: Propose Improvements

For each skill that needs work, present a structured proposal. Do not silently rewrite — surface the change and the rationale so the user can accept, modify, or reject.

### Multi-skill scope: lead with priority summary

When the resolved scope contains more than one skill (directory-path argument enumerating multiple `SKILL.md` files), **present a priority-grouped summary table FIRST**, then offer per-skill detail on request rather than dumping every proposal inline.

```
| Skill | Priority | Headline finding |
|-------|----------|------------------|
| <name> | Critical | <one-line> |
| <name> | High     | <one-line> |
| <name> | Medium   | <one-line> |
| <name> | Low      | <one-line> |
| <name> | OK       | No changes needed |
```

Priority rubric:

- **Critical** — description fails the formula entirely OR XML/reserved-name security check fails
- **High** — description present but missing negative triggers / scope boundaries (over-trigger risk)
- **Medium** — body content gaps (missing red flags, verification checklist, decision trees)
- **Low** — cosmetic frontmatter polish, line-count discipline, structural cleanup
- **OK** — passes all criteria; no changes needed

After the summary, surface detailed per-skill proposals only for Medium-and-higher entries by default; Low and OK can be collapsed into a one-line note unless the user asks for everything. This keeps multi-skill audits scannable without losing depth.

For single-skill scope, skip the summary table and go straight to the per-skill proposal below.

### Per-skill proposal template

**Skill**: `[name]` (`[path]`)
**Current description**:
```
[existing description]
```
**Proposed description**:
```
[improved description]
```
**Why**: [one sentence on what changed and why]

**Structural improvements** (if any):

- [specific addition/removal/transformation with rationale]
- [files to move to references/, scripts to extract, etc.]

**Body improvements** (if any):

- [specific addition/removal/transformation with rationale]

### What NOT to Change

- Do not rewrite skill body content that is already effective
- Do not add keyword lists or "trigger" words — Claude matches semantically, not by keyword
- Do not remove opinionated methodology in favor of generic advice
- Do not add optional frontmatter fields unless they provide clear value for the specific skill

## Phase 4: Empirical Optimization (gated by `--deep`)

Skip this phase entirely when `--deep` is absent — naked invocation collapses
Phase 4 to a one-line note: "Quantitative description and output evaluation
available via `--deep`; see Phase 4 details when ready."

When `--deep` is present, run both 4a and 4b sequentially.

### Phase 4 cost gate

Before launching any model calls, surface an estimate via AskUserQuestion:

> "`--deep` will execute approximately N model calls in total
> (description-improver: K, triggering eval: P runs, output-review subagents:
> Q dispatches, grader: R). Estimated cost ~$X at current rates. Continue?"

User selects Continue / Reduce iterations / Abort. Honor the choice before
proceeding. The cost gate fires on every `--deep` invocation; no persistent
opt-out in this version.

### Runtime contract

Phase 4's scripts shell out to `claude -p` (the Claude Code CLI) as a
subprocess, inheriting your existing session's auth. No separate
`ANTHROPIC_API_KEY` or `anthropic` Python SDK install is required. If
`claude` is not on PATH (rare — usually implicit when this skill is invoked
from Claude Code), surface the error and abort `--deep` rather than
fabricating an alternate auth path.

Both `run_loop.py` and `generate_review.py` use only the Python stdlib —
no third-party packages required.

### Phase 4a: Description loop (automated)

1. **Resolve eval set.** Probe `<skill-dir>/evals.json`.
   - If present: use it. Print one-line summary
     `Using N evals (T trigger / U no-trigger).` Continue to step 2.
   - If absent: auto-draft per `references/eval-set-format.md`. Read the target
     SKILL.md, generate 5–10 should-trigger + 5–10 should-not-trigger queries
     (favor near-miss queries over obviously-unrelated). Write to
     `<skill-dir>/evals.json`. Display via AskUserQuestion with options
     Accept / Edit (skill pauses, user edits file, types continue) / Reject
     (abort `--deep`).
2. **Invoke the loop.** Use module-mode invocation (the script's relative
   imports require it):

   ```bash
   cd <skill-dir> && PYTHONPATH=. python3 -m scripts.run_loop \
     --eval-set <skill-dir>/evals.json \
     --skill-path <skill-dir> \
     --model <model> \
     --max-iterations <N> \
     --holdout 0.4 \
     --runs-per-query 3 \
     --num-workers 10 \
     --results-dir <skill-dir>/.eval-runs/
   ```

   Flag semantics:
   - `--model` is **required** by `run_loop.py` (no default). Use the value
     from the skill's `--model` flag (default: `claude-haiku-4-5-20251001`).
   - `--max-iterations` is the description-loop cap. Use the value from the
     skill's `--max-iterations` flag (default: 5).
   - `--results-dir` writes outputs to a timestamped subdirectory under the
     given path. Phase 4b also writes into `.eval-runs/<local-timestamp>/` —
     create that workspace directory FIRST (here in Phase 4a), then pass it
     to both `run_loop.py --results-dir` and Phase 4b's workspace path so
     they share a single timestamped root.

3. **Capture results.** `run_loop.py` writes `results.json` and an HTML
   report inside the timestamped subdir under `--results-dir`. Locate the
   newest subdir and read `results.json` — expected keys include
   `best_description`, `best_score`, `best_train_score`, `best_test_score`,
   `final_description`, `history`, `iterations_run`, `exit_reason`. Pass to
   Phase 5.

### Phase 4b: Output review (semi-automated)

1. **Use the shared workspace** at `<skill-dir>/.eval-runs/<local-timestamp>/`
   created in Phase 4a Step 2 (the project `.gitignore` excludes `.eval-runs/`).
   Phase 4b artifacts (`run-NNNN/`, `feedback.json`) live as siblings of
   Phase 4a's `results.json` under this same timestamped root.
2. **Select prompts.** First 3 entries with `should_trigger:true` from the
   eval set, in file order (deterministic; no random sampling).
3. **Dispatch run subagents in parallel** (single message, multiple Agent
   calls). For each prompt:
   - Create `<workspace>/run-NNNN/outputs/`
   - Write `<workspace>/run-NNNN/eval_metadata.json` with
     `{eval_id, prompt, expectations}`
   - Dispatch a `general-purpose` subagent with this prompt template:

     > "Read the target skill at `<deployed-skill-path>` and any of its
     > referenced files you need. Then perform the following user task:
     > `<prompt>`. Write any file outputs to
     > `<absolute-workspace-path>/run-NNNN/outputs/`. Write your full
     > turn-by-turn transcript (your thinking, tool calls, results) to
     > `<absolute-workspace-path>/run-NNNN/transcript.md` before returning.
     > Return a one-sentence summary."

4. **Grade** (per run, after the run subagent returns).
   - If the entry's `expectations` list is empty or missing: skip grading.
   - Otherwise: dispatch the `grader` subagent (definition at
     `<skill-dir>/agents/grader.md`) with `expectations`, `transcript_path`,
     and `outputs_dir`. Grader writes `grading.json` to the run dir
     (this is the filename `generate_review.py` looks for; do not rename
     to `metrics.json` despite that term appearing in earlier drafts).
5. **Launch review server.** Shell out:

   ```bash
   python3 <skill-scripts>/eval_viewer/generate_review.py \
     <workspace-path> \
     --skill-name <target-skill-name> \
     --port 8742
   ```

   `generate_review.py` auto-opens the URL in the user's default browser
   on startup (via `webbrowser.open()`). Before binding, the script attempts
   to free the requested `--port` by invoking `lsof -ti :<port>` and sending
   `SIGTERM` to any listening PIDs; if `lsof` is unavailable it prints a
   notice to stderr and skips the kill step. The script then tries to bind
   the requested port; if that still fails (`OSError`), it falls back to an
   OS-assigned ephemeral port (`bind(..., 0)`). Capture the actual bound
   port from the script's stdout — it may differ from `--port`. Then emit:

   > Review server running at http://localhost:<actual-port> (browser tab
   > opened automatically — if it didn't, navigate there manually).
   > Press Ctrl+C in the running terminal when you're done reviewing.
   > Your feedback will be saved to `<workspace>/feedback.json`.
   >
   > Note: if port <requested-port> was already in use, this server may
   > have terminated the prior listener via `lsof` + `SIGTERM` — check for
   > unintended impact on other local processes. (This kill-on-startup
   > behavior comes from the upstream script and is tracked as a
   > known-risk decision in bead `agents-config-nsneu`.)

   The skill **blocks** until the server process exits.

6. **Read feedback.** When the server exits, read
   `<workspace>/feedback.json`. Pass results to Phase 5. If the file is
   empty or missing (user ^C'd before reviewing), ask via AskUserQuestion:
   "No feedback captured — abort `--deep` or proceed with description-loop
   results only?"

### Failure handling

- **Port in use** — the script preemptively `SIGTERM`s any process listening on `--port` (via `lsof -ti`) before binding; if the bind still fails, it falls back to an ephemeral port (`bind(..., 0)`). Always read the actual bound port from stdout and surface it to the user. Warn the user that the kill step may have affected unrelated processes (see bead `agents-config-nsneu` for the upstream-defect decision)
- **Subagent timeout** (default 5 min/run) — write `grading.json` with `{status: "timeout"}` and continue; partial transcript still visible in review server
- **Grader skipped** (empty expectations) — log it, no error
- **run_loop.py non-zero exit** — surface stderr; ask user whether to retry, fall back to advisory-only Phase 4, or abort

## Phase 5: Iterate (gated by `--deep`)

Synthesize Phase 4a (description-loop results) and Phase 4b (output-review
feedback) into a concrete proposal: which description to adopt, which body
edits to make, and whether another `--deep` pass is warranted.

### Inputs

- From Phase 4a: `best_description`, `best_score`, `history` (each iteration's
  description + score), `final_description`
- From Phase 4b: `feedback.json` (per-run user notes from the review server),
  per-run `grading.json` (if grader ran)

### Process

1. **Compare best_description against the current description.** If they
   differ, summarize the delta in 1–2 sentences for the user.
2. **Read feedback.json.** Group user notes by run; identify recurring themes
   (e.g., "skill never read the SKILL.md", "missed a frontmatter check").
3. **Read each grading.json** (where present). Identify expectations that
   failed across multiple runs — those signal systematic skill weaknesses.
4. **Propose a structured update** in this shape:

   ```markdown
   ## Phase 5 proposal — <skill-name>

   ### Description
   - Current: `<text>`
   - Proposed: `<text>` (from Phase 4a best, score <X/Y>)
   - Adopt? [yes / keep current / draft alternative]

   ### Body edits
   - <Section>: <one-sentence change>; rationale: <feedback theme>
   - <Section>: ...

   ### Re-run?
   - Recommend another `--deep` pass: [yes if N>0 unresolved themes / no]
   ```

5. **Surface the proposal to the user and STOP — wait for their letter reply.**

   This question has 5 options, which exceeds `AskUserQuestion`'s 4-option
   cap. Use a prose letter-prompt instead. Print the proposal block (from
   step 4) followed by:

   ```
   Which path forward? Reply with a single letter:

   A) Accept all — apply description + body edits, proceed to Phase 6
   B) Adopt description only — apply Phase 4a winner, skip body edits, proceed to Phase 6
   C) Adopt body edits only — apply Phase 4b-driven body changes, keep current description, proceed to Phase 6
   D) Re-run `--deep` from Phase 4a — loop back using the accepted description as starting point (incurs another cost-gated pass)
   E) Reject all — proceed to Phase 6 with no changes from Phase 4/5
   ```

   End your turn after presenting these. Do NOT infer the user's choice
   from prior context — wait for an explicit single-letter reply. On the
   reply, parse the first letter (A–E, case-insensitive). If ambiguous
   (no letter, multiple letters, or outside A–E), ask once for
   clarification then halt rather than guessing.

### What NOT to do in Phase 5

- Do not silently apply changes — every adoption is explicit
- Do not propose body edits with no grounding in Phase 4b feedback
- Do not loop more than once without checking with the user (cost discipline)

## Phase 6: Confirm and Apply

Present all proposed changes as a single summary table before writing anything:

```
| Skill | Change Type | Description |
|-------|-------------|-------------|
| bugfix | description rewrite | Added negative triggers, clarified scope |
| writing-unit-tests | body: add red flags | Missing rationalization table |
| my-workflow | structure: extract refs | Moved API docs to references/ |
| ... | no changes needed | Already well-structured |
```

**Wait for user confirmation before writing any files.** Use `AskUserQuestion` to capture the accept/reject decision per skill if the batch is large.

Apply approved changes. Show a diff for each modified file so the user can verify the edit landed correctly.

## Red Flags

| Rationalization | Reality |
|---|---|
| "The description is fine, it triggers correctly" | Trigger accuracy is measurable — run `--deep` (Phase 4a) before assuming |
| "I'll just improve the frontmatter" | Body content is where skills fail; frontmatter only gets you discovered |
| "This skill is simple, no changes needed" | Simple skills rot into generic advice; audit every section against the quality criteria |
| "I can rewrite this without reading it first" | Always read the full SKILL.md before proposing changes |

## Verification Checklist

Before closing the optimization session:
- [ ] Frontmatter `description` passes the formula: `[What it does]. Use when [A], [B], or [C]. Do NOT use for [exclusion].`
- [ ] No XML angle brackets in frontmatter values
- [ ] SKILL.md body under 500 lines; heavy content in `references/`
- [ ] Every Phase in the process is actionable ("do" not "consider")
- [ ] Red flags section present so the skill can't be rationalized away
- [ ] If scripts were added: they are executable and tested against known inputs

## Reference: What Makes Skills Effective

See `references/SKILLS_PRIMER.md` for the full file structure, frontmatter schema, body structure template, and key principles.
