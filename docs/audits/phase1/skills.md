# Phase 1 Audit: Skills
Auditor: audit-skills subagent
SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851
Files audited: 19 primary SKILL.md files

---

F1: `wait-for-pr-comments` exceeds 500-line body budget by 65%
  File: src/user/.agents/skills/wait-for-pr-comments/SKILL.md:1-828
  Category: skill
  Severity: High
  Tier: 2
  Issue: The SKILL.md body is 828 lines — 66% over the 500-line progressive-disclosure budget. The file contains the full 9-phase operational specification, per-comment subagent contract (with SHA-discovery procedure and orchestrator-side enforcement), mode-aware ESCALATE protocol, hand-off contract with full JSON schema, schema validation guards (duplicated verbatim from the `reply-and-resolve-pr-threads` SKILL.md), concurrency recovery branch table, and reply text templates. Many of these sections are reference material consulted only during specific execution phases, not at first-step launch. The combined weight forces an agent to load the entire specification on every invocation regardless of which phase is relevant.
  Recommendation: Extract the following sections to supporting reference files, one level deep from SKILL.md: (1) `SCHEMA.md` — hand-off contract JSON schema + field notes; (2) `SUBAGENT-CONTRACT.md` — per-comment subagent contract, SHA-discovery procedure, orchestrator-side enforcement, non-compliant recovery; (3) `RECOVERY.md` — concurrency recovery branch table + `crash_recovery` phase label semantics. Keep the 9-phase outline, arg protocol, reply text templates, and red flags in SKILL.md. Add a TOC to each extracted file (>100 lines). Schema validation guards appear verbatim in both this skill and `reply-and-resolve-pr-threads` — consolidate to one reference and cross-link.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 (guardrail every completion claim with mechanical evidence): a 828-line SKILL.md risks partial reads by the agent, which can cause the orchestrator to mis-apply phase contracts mid-run and emit false completion signals. Splitting into progressive-disclosure reference files ensures each phase's execution contract is read in full when needed.
  Promotion-eligible: yes
  Related: F2, F5

F2: `reply-and-resolve-pr-threads` duplicates schema validation guards from `wait-for-pr-comments`
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:200-214
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: The nine schema validation guards are reproduced verbatim in both `reply-and-resolve-pr-threads` (lines 200–214) and `wait-for-pr-comments` (lines 683–713). These guards define the same contract from Skill A's write side and Skill B's read side. Two copies means any future change must be kept in sync manually, and the current guard numbering is already inconsistent (Skill B's list has 9 guards numbered 1–9; Skill A's has 9 guards numbered 1–9 with slightly different prose). This is an active coherence risk as the schema evolves.
  Recommendation: Define the guards once in a shared `SCHEMA.md` (per F1) referenced by both SKILL.md files. Each file adds only the guards that are implementation-specific (e.g., Skill A's note about `interactive Phase 3.5 reclassification` before write). Alternatively, move the authoritative definition to `validate-inventory.sh` header comments (the script is the enforcement point) and have both skills reference the script.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 (guardrail every completion claim with mechanical evidence): divergent guard descriptions between Skill A and Skill B will eventually cause a mismatch between what the writer enforces and what the reader expects, silently breaking the completion gate on PR review cycles.
  Promotion-eligible: yes
  Related: F1

F3: `bd` commands and bead-tracker terminology leak into `wait-for-pr-comments` (shared content)
  File: src/user/.agents/skills/wait-for-pr-comments/SKILL.md:191,548,557-561
  Category: skill
  Severity: Critical
  Tier: 2
  Issue: `wait-for-pr-comments` is in `src/user/.agents/skills/` (shared across all tools) but contains direct `bd` command invocations in its normative execution path: `bd label add <bead-id> human`, `bd update <bead-id> --append-notes`, `bd create --parent`, `bd dep add`. These appear in the Mode-aware ESCALATE section (autonomous mode) and the DEFER placement logic. This is not incidental mention — these are executable instructions the agent must follow during autonomous operation. A Codex CLI or Gemini CLI agent using this skill will encounter `bd` commands it cannot execute, with no fallback defined.
  Recommendation: Either (a) move `wait-for-pr-comments` to `src/plugins/beads/.agents/skills/` since autonomous mode is inherently beads-coupled, or (b) wrap the `bd`-dependent behavior behind a conditional ("in autonomous mode with beads: …; in autonomous mode without beads: …") with a generic fallback (e.g., write a local file or log a structured escalation). Option (a) is cleaner and matches the architectural intent of the plugin namespace. The interactive mode (no `bd` invocations) could remain in the shared namespace if split from the autonomous mode logic.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context so work survives compaction, agent handoff, and overnight runs): bead tracker coupling in shared content means autonomous mode silently fails on non-Claude tools, breaking the overnight run capability the vision depends on.
  Promotion-eligible: yes
  Related: F4

F4: `reply-and-resolve-pr-threads` contains `bd` commands and bead ID references (shared content)
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:111,240-242
  Category: skill
  Severity: Critical
  Tier: 2
  Issue: `reply-and-resolve-pr-threads` is in `src/user/.agents/skills/` (shared) but the autonomous mode Phase 1.5 recovery section prescribes `bd label add <bead-id> human` + `bd update <bead-id> --append-notes` as the escalation path. The Red Flags table also references bead IDs contextually. The autonomous `--bead-id` argument is a first-class parameter of the skill's arg protocol. A non-beads tool loading this shared skill will receive instructions it cannot execute.
  Recommendation: Move `reply-and-resolve-pr-threads` to `src/plugins/beads/.agents/skills/` alongside `wait-for-pr-comments`, since Skill A and Skill B are architecturally coupled and both require beads in autonomous mode. If a non-beads interactive version of thread-reply is desired later, it can be split into a shared `reply-pr-threads` skill (no autonomous mode, no `--bead-id`) and a beads-specific `reply-and-resolve-pr-threads` that adds the autonomous protocol.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #5 (persist context so work survives compaction, agent handoff, and overnight runs): these two skills together form the PR review completion gate — if they silently fail on non-Claude tools, autonomous overnight PR cycles break without any error signal.
  Promotion-eligible: yes
  Related: F3

F5: `implement-bead` contains extremely dense single-line prose exceeding 1100 characters
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:24,48,56,87
  Category: skill
  Severity: High
  Tier: 2
  Issue: Multiple lines in the SKILL.md body exceed 400–1100 characters of inline prose. Line 48 alone is 1100 characters — a single unbroken sentence encoding type-to-formula routing logic, formula variable shapes, bead linkage stamping, and molecule disambiguation all in one paragraph. Line 24 (784 chars) encodes existence probe logic with an inline explanatory parenthetical that fills nearly a full screen. These dense single lines are both hard for the agent to follow (partial reads or attention limits may truncate them) and hard for humans to review and maintain. This is the opposite of the "lead with what to do" principle from the Skills Primer.
  Recommendation: Break §1's dense paragraphs into structured lists or decision tables for each sub-decision: (1) formula selection table (type → formula mapping), (2) variable shape table (formula → `--var` shape), (3) post-pour steps as a numbered list. The formula-label parsing shell snippet (duplicated between §1 and §2) should reference a single canonical block rather than repeating 20 lines verbatim twice. Consider extracting the full resolution algorithm to a `RESOLUTION.md` reference file and keeping §1/§2 as algorithm summaries with a "See RESOLUTION.md for the full decision tree" pointer.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #4 (guardrail every completion claim with mechanical evidence): the orchestrator cannot reliably follow a 1100-character prose line encoding 4 interleaved decision branches — agent attention compression increases the probability of skipping a guard, causing silent pipeline errors.
  Promotion-eligible: yes
  Related: F6

F6: `implement-bead` duplicates the formula-label parsing shell snippet verbatim in §1 and §2
  File: src/plugins/beads/.agents/skills/implement-bead/SKILL.md:26-46,58-79
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: The 20-line shell snippet for parsing `formula-*` labels (variables: `formula_names`, `formula_count`, `formula_to_pour`) appears twice — once in §1 (lines 26–46, for first-stage pour decision) and once in §2 (lines 58–79, for mode resolution). The snippets are functionally equivalent but the output variable names differ (`formula_to_pour` vs `mode`). The duplication doubles the context load and means any change to the parsing logic (e.g., to handle edge cases in `bd label list --json` output) must be applied twice. Each copy also carries a long explanatory parenthetical about the `awk-with-exit` historical bug that was the motivation for this pattern.
  Recommendation: Extract the common label-parsing logic to a single named procedure block (e.g., "Formula-label parsing procedure") near the top of the skill, with a note that it is used in both §1 and §2. Each section then references the procedure and specifies only the output variable name and how to act on the result. The historical bug explanation belongs once, in the procedure block, not repeated in both use sites.
  Vision-advancement-tier: C
  Vision-advancement: Removes duplicated content that adds context weight without serving agent judgment or execution — a direct noise-reduction improvement.
  Promotion-eligible: yes
  Related: F5

F7: `test-review` uses undocumented frontmatter fields `context: fork` and `agent: general-purpose`
  File: src/user/.agents/skills/test-review/SKILL.md:1-8
  Category: skill
  Severity: Medium
  Tier: 1
  Issue: The frontmatter of `test-review` includes `context: fork` and `agent: general-purpose` — neither of which appears in the official Anthropic SKILL.md schema (`name`, `description`, `model`, `effort`, `allowed-tools`, `compatibility`, `metadata`, `license`) nor in the project-specific extensions documented in the Skills Primer (`model`, `effort`). These fields have no known harness interpretation and may be silently ignored, used by an undocumented harness feature, or be stale residue from an older schema version. Their presence creates false documentation (readers may assume these fields have behavioral effect).
  Recommendation: Determine whether these fields are consumed by any harness or tool. If not, remove them. If `context: fork` is intended to request a forked context window (similar to subagent dispatch), document this behavior in the Skills Primer and use a consistent field name. Until behavior is confirmed, remove the fields to avoid misleading readers.
  Vision-advancement-tier: C
  Vision-advancement: Removes undocumented fields that create false expectations about harness behavior — a clarity improvement that prevents agents from citing non-existent capabilities.
  Promotion-eligible: no

F8: `simplify` skill body contains an external-source drift annotation as an HTML comment
  File: src/user/.agents/skills/simplify/SKILL.md:7
  Category: skill
  Severity: Low
  Tier: 1
  Issue: Line 7 contains an HTML comment `<!-- Source: /simplify slash command (sidekick injection — outside this repo); Drift policy: (C) accept periodic re-sync as known cost; Last sync: 2026-05-02 -->`. This is maintenance metadata about the file's external origin — not instruction content. While the intent is reasonable (tracking that this file is a copy of an external skill and may drift), the HTML comment form renders invisibly in markdown previews and will not be read by an agent parsing the skill. It belongs in a `# Maintenance` section or a git commit message, not embedded as a silent annotation in the body.
  Recommendation: Either (a) delete the comment and record the drift-sync policy in the git history or a repo-level MAINTENANCE.md, or (b) convert it to an explicit `## Maintenance Note` section at the bottom of the file (below all executable content) so it is visible during review. The current form adds no value to agent execution and is invisible during normal reading.
  Vision-advancement-tier: C
  Vision-advancement: Removes invisible metadata noise from skill body — an invisible comment contributes no signal to agent judgment and obscures the effective line count.
  Promotion-eligible: no

F9: `simplify` skill references `bd remember` in a negation without defining what mechanism to use instead for non-Claude tools
  File: src/user/.agents/skills/simplify/SKILL.md:57
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: Line 57 states "Do NOT use `bd remember` for this — that mechanism is for bead-tracker context, not agent/project memory." The reference to `bd remember` (a beads CLI command) appears in `src/user/.agents/skills/` (shared across all tools). While the sentence is a prohibition, not an instruction, it introduces bead-tracker vocabulary into shared content and assumes the reader understands what `bd remember` is. A Codex CLI or Gemini CLI agent has no `bd remember` — the sentence is meaningful context for Claude but meaningless or confusing for other tools. The positive instruction ("use the host runtime's memory mechanism") is already in the preceding sentence and is correct.
  Recommendation: Remove the `bd remember` negation from shared content. The prohibition is redundant for non-Claude tools (they have no `bd remember`) and creates unnecessary bead-tracker vocabulary leakage. Replace with a tool-agnostic note: "Do not use issue-tracker or task-tracking mechanisms for this — use the host's project memory system." This preserves the intent without leaking bead terminology.
  Vision-advancement-tier: C
  Vision-advancement: Removes bead-tracker vocabulary from shared skill content, keeping the shared namespace tool-agnostic and reducing cognitive noise for non-Claude agents.
  Promotion-eligible: yes
  Related: F3, F4

F10: `wait-for-pr-comments` uses hardcoded `~/.claude/skills/` install path instead of `$CLAUDE_SKILL_DIR`
  File: src/user/.agents/skills/wait-for-pr-comments/SKILL.md:227,244,261,326,354,410,655,672
  Category: skill
  Severity: High
  Tier: 1
  Issue: The SKILL.md body prescribes helper script invocations using the hardcoded path `~/.claude/skills/wait-for-pr-comments/write-inventory.sh` and `~/.claude/skills/wait-for-pr-comments/validate-inventory.sh` at 8+ locations. The Skills Primer establishes `${CLAUDE_SKILL_DIR}` as the portable runtime variable for the current skill's directory (as used correctly in `merge-guard/SKILL.md` line 54 and `run-queue/SKILL.md` line 59). Using the hardcoded path means: (1) the skill breaks if installed to a non-standard location, (2) it is inconsistent with the project's own portable-path convention, and (3) it leaks the Claude-specific install path into content that is in the shared `src/user/` namespace.
  Recommendation: Replace all `~/.claude/skills/wait-for-pr-comments/` prefixes with `${CLAUDE_SKILL_DIR}/`. This is a mechanical substitution at 8+ locations. Also apply to `reply-and-resolve-pr-threads/SKILL.md` line 65 which has the same hardcoded path referencing `wait-for-pr-comments/validate-inventory.sh`.
  Vision-advancement-tier: C
  Vision-advancement: Removes hardcoded install path that breaks portability — a mechanical correctness fix ensuring the skill works when installed to non-default locations.
  Promotion-eligible: no
  Related: F4

F11: `reply-and-resolve-pr-threads` uses hardcoded `~/.claude/skills/` path for cross-skill script reference
  File: src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:65
  Category: skill
  Severity: High
  Tier: 1
  Issue: Phase 0 schema validation invokes `~/.claude/skills/wait-for-pr-comments/validate-inventory.sh` using a hardcoded path pointing to a *different* skill's directory. This is a cross-skill script reference that has no portable equivalent via `$CLAUDE_SKILL_DIR` (which resolves to the current skill's directory). The hardcoded path will break if the installation prefix changes, and couples the two skills' filesystem layout at the prose level. This is a separate issue from F10 because the solution is different: a cross-skill reference requires either (a) an absolute path via an environment variable like `$CLAUDE_SKILLS_ROOT`, or (b) copying/symlinking `validate-inventory.sh` into the `reply-and-resolve-pr-threads/` skill directory.
  Recommendation: Add `validate-inventory.sh` as a supporting file in the `reply-and-resolve-pr-threads/` skill directory (symlink or copy) and reference it via `${CLAUDE_SKILL_DIR}/validate-inventory.sh`. This makes Skill B self-contained and eliminates the cross-skill filesystem coupling. Alternatively, if a `$CLAUDE_SKILLS_ROOT` environment variable is established as a convention, use `${CLAUDE_SKILLS_ROOT}/wait-for-pr-comments/validate-inventory.sh`.
  Vision-advancement-tier: C
  Vision-advancement: Removes brittle cross-skill filesystem coupling that will silently break Phase 0 validation if skills are relocated — a reliability fix for the PR completion gate.
  Promotion-eligible: yes
  Related: F10

F12: `ralf-it` is a deprecated stub that still costs context window on every session
  File: src/user/.agents/skills/ralf-it/SKILL.md:1-16
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: `ralf-it` is explicitly labeled deprecated and contains only 16 lines: a stub saying "use `ralf-review` or `ralf-implement` instead." Despite being retired, the skill occupies a slot in the skills discovery manifest and loads its frontmatter (`name`, `description`, `model: opus[1m]`, `effort: low`) into every agent context at startup. The `model: opus[1m]` assignment on a stub that does nothing is also semantically wrong — if accidentally invoked (which the description does not guard against by listing trigger phrases), it would spin up an expensive Opus model to say "use something else." The description "Deprecated alias" is not a negative trigger, so the skill can still be selected by agents that parse the description loosely.
  Recommendation: Delete `ralf-it/SKILL.md` and its directory entirely. The delegation rule in `src/user/.claude/rules/delegation.md` already states `ralf-implement` and `ralf-review` are opt-in via explicit invocation — `ralf-it` adds no safety net. If backward compatibility for existing workflows is required, keep the directory but reduce the skill to: `model: haiku`, `effort: low`, and a body that immediately says "Deprecated: invoke `ralf-review` or `ralf-implement` explicitly" with no other content.
  Vision-advancement-tier: C
  Vision-advancement: Removing a deprecated stub reduces startup context weight — a noise-reduction improvement that directly benefits agent token budget on every session.
  Promotion-eligible: yes

F13: `ralf-implement` and `ralf-review` do not reference their supporting prompt files from the body
  File: src/user/.agents/skills/ralf-implement/SKILL.md:44-51
  File: src/user/.agents/skills/ralf-review/SKILL.md:40-45
  Category: skill
  Severity: Medium
  Tier: 2
  Issue: Both `ralf-implement` and `ralf-review` have supporting prompt files (`foreign-agent-prompt.md`, `foreign-eyes-prompt.md`, `fresh-eyes-prompt.md`, `implementer-prompt.md` for ralf-implement; `fresh-eyes-prompt.md` for ralf-review). Neither SKILL.md body references these files — there is no "See `fresh-eyes-prompt.md`" or "Dispatch with the prompt template in `${CLAUDE_SKILL_DIR}/fresh-eyes-prompt.md`" instruction anywhere in either skill. An agent executing the skill will know it must dispatch a fresh-eyes subagent (from the body text), but has no signal that pre-built prompt templates exist to use. The templates go unused unless the agent discovers them by other means.
  Recommendation: Add explicit references in both SKILL.md bodies at the point where fresh-eyes/foreign-eyes dispatch is described. For example, in `ralf-implement` step 4: "Dispatch with `${CLAUDE_SKILL_DIR}/fresh-eyes-prompt.md` (pure-Claude) or `${CLAUDE_SKILL_DIR}/foreign-agent-prompt.md` (Codex/Gemini cycle)." This is a progressive-disclosure improvement: the templates are already in supporting files; the SKILL.md just needs to point to them.
  Vision-advancement-tier: A
  Vision-advancement: Advances commitment #3 (substitute adversarial cross-model review for human review): the foreign-eyes and fresh-eyes prompt templates only deliver their adversarial posture when the agent actually uses them — unreferenced supporting files are dead weight that degrades the quality gate.
  Promotion-eligible: yes
  Related: F5

F14: `condition-based-waiting` uses `user-invocable: false` — a non-standard frontmatter field with unclear harness effect
  File: src/user/.agents/skills/condition-based-waiting/SKILL.md:3
  Category: skill
  Severity: Low
  Tier: 1
  Issue: The frontmatter contains `user-invocable: false`, which is not in the official Anthropic SKILL.md schema. The same field appears in `testing-anti-patterns/SKILL.md` (line 2). Neither the Skills Primer nor official docs describe `user-invocable` as a valid field with defined behavior. If the harness ignores unknown fields, this has no effect and the skill remains discoverable via normal description matching. If the harness honors it, it prevents user invocation — but the current behavior is undocumented and the field name does not match any official `allowed-tools` or `compatibility` mechanism.
  Recommendation: Document the intended meaning of `user-invocable: false` in the Skills Primer if this field is intentionally used to gate direct user invocation. If it has no harness effect, remove it and rely on the description to naturally de-prioritize the skill for user invocation (e.g., the description "Use when writing or changing tests..." already implies agent-triggered use). The `user-invocable: false` pattern is used consistently in two skills — if intended, it warrants a project convention note; if cargo-culted, it should be removed.
  Vision-advancement-tier: C
  Vision-advancement: Removes non-standard frontmatter field that creates false impressions of harness capability — a clarity fix that prevents agents from citing enforcement that does not exist.
  Promotion-eligible: no
  Related: F7

F15: `writing-unit-tests` references "follow-up bead" in shared content
  File: src/user/.agents/skills/writing-unit-tests/SKILL.md:60,180,197
  Category: skill
  Severity: Medium
  Tier: 1
  Issue: Three locations in `writing-unit-tests/SKILL.md` use "follow-up bead" as a rationalization-to-reject pattern: line 60 ("I'll file a follow-up bead to fix it later"), line 180 (same phrase in the rationalizations table), line 197 (same in red flags). This is bead-tracker vocabulary in shared content. The argument is correct — deferred cleanup rarely happens — but the framing assumes the reader knows what a "bead" is. On a non-beads tool, the sentence reads as a reference to an unknown concept. The underlying principle (deferred tickets are graveyard items) is universally valid and should be expressed in tool-agnostic terms.
  Recommendation: Replace "follow-up bead" with "follow-up ticket" or "deferred issue" in all three locations. The principle is the same; the language becomes tool-agnostic. This is a mechanical substitution.
  Vision-advancement-tier: C
  Vision-advancement: Removes bead-tracker vocabulary from shared skill content, keeping the shared namespace tool-agnostic — a three-site mechanical fix.
  Promotion-eligible: no

F16: `verify-checklist` references `bead:ID` as a discovered-work recording format in shared content
  File: src/user/.agents/skills/verify-checklist/SKILL.md:65,94
  Category: skill
  Severity: Medium
  Tier: 1
  Issue: Line 65 says "create beads, issues, or memory entries as appropriate." Line 94 includes `bead:ID` in the Discovered Work table template. Both references treat beads as a first-class tracking mechanism alongside generic `issue:#N` and `memory`. In shared content, this is appropriate if `bead:ID` is just an example alongside generic alternatives — but it is the first item listed (privileged position) and uses bead-specific formatting (`bead:ID`) that only means something in a beads-enabled project. A Codex CLI or Gemini CLI user would see a template column value that references an unknown system.
  Recommendation: Reorder the alternatives to list the generic option first: `issue:#N / memory / backlog / bead:ID`. Replace the standalone "create beads, issues, or memory entries" with "record in the project's tracking system (issues, backlog, memory, or beads if available)." The beads-specific shorthand can remain as one option rather than the default framing.
  Vision-advancement-tier: C
  Vision-advancement: Makes the completion-gate verify step tool-agnostic by not privileging beads-specific tracking notation, reducing friction for non-beads users adopting the verification discipline.
  Promotion-eligible: no

F17: `start-bead` body is approaching the 500-line warning threshold with dense multi-path logic
  File: src/plugins/beads/.agents/skills/start-bead/SKILL.md:1-357
  Category: skill
  Severity: Low
  Tier: 2
  Issue: At 357 lines, `start-bead` is at 71% of the 500-line budget and encodes the full Route Z (closed-bead preflight), Route A (implementation-ready), Route B (trivial inline), and Route C (brainstorm formula) decision paths plus the molecule existence probe, all routing decision tables, red flags, and recovery instructions. The routing decision table and Route Z audit-comment templates are reference material that does not need to be read on every invocation — only the first applicable route does. As the skill evolves (Route Z was recently added with extensive closed-bead handling), the budget will likely be exceeded.
  Recommendation: No immediate action required (below threshold), but flag for proactive extraction before the next significant addition. Candidate extraction: Route Z closed-bead handling prose (lines 39–94) and the full routing decision table (lines 326–357) into a `ROUTING.md` reference file. The SKILL.md would retain the algorithm summary and delegate to `ROUTING.md` for the closed-bead audit-comment templates and the complete decision matrix.
  Vision-advancement-tier: C
  Vision-advancement: Proactive progressive-disclosure preparation prevents a future high-severity finding when the next Route or invariant is added — a maintenance-debt reduction.
  Promotion-eligible: yes

F18: `run-queue` description is written in second person ("do NOT mix")
  File: src/plugins/beads/.agents/skills/run-queue/SKILL.md:1-8
  Category: skill
  Severity: Low
  Tier: 1
  Issue: The description field contains: "Runs in a dedicated session — do NOT mix with brainstorming sessions." The clause "do NOT mix" is a second-person imperative directed at the agent, not a third-person description of what the skill does. Per the Skills Primer, the description must be written in third person because it is injected into the system prompt. The imperative phrasing ("do NOT") is appropriate in the body but not in the frontmatter description trigger contract.
  Recommendation: Rewrite the tail of the description: "…Runs in a dedicated session; must not be mixed with interactive brainstorming sessions." This preserves the constraint while converting from imperative to third-person declarative.
  Vision-advancement-tier: C
  Vision-advancement: Corrects description phrasing to match the third-person trigger contract required by the skills invocation model — a low-stakes correctness fix.
  Promotion-eligible: no

F19: `merge-guard` description uses imperative phrasing that is not third-person
  File: src/user/.agents/skills/merge-guard/SKILL.md:3-7
  Category: skill
  Severity: Low
  Tier: 1
  Issue: The description starts with "Proactively use when about to merge a PR" — the word "Proactively" followed by the verb "use" reads as an instruction directed at the agent ("proactively use this skill") rather than a third-person description of what the skill does. Per the Skills Primer, the description should be written in third person: "Processes X…", "Prevents X…", "Detects X…". The body of the skill can and should say "Use proactively when…" — but the frontmatter trigger contract should describe the skill's behavior.
  Recommendation: Rewrite the description opening: "Pre-merge gate that prevents merging while automated reviews (especially Copilot) are pending or review comments have not been triaged. Invoke proactively before any `gh pr merge`, `git merge`, or merge action."
  Vision-advancement-tier: C
  Vision-advancement: Corrects description phrasing so the skill's trigger contract accurately describes behavior rather than instructing the agent — a frontmatter clarity fix.
  Promotion-eligible: no

---

## Supporting Files Catalogue

| File | Lines | Purpose |
|------|-------|---------|
| `src/plugins/beads/.agents/skills/run-queue/poll-ready-beads.sh` | 36 | Background poller that checks `bd ready --label implementation-ready` on a configurable interval (default 10 min), exits 0 with bead JSON when found, exits 1 on timeout, exits 2 on interrupt. Used by run-queue Step 2. |
| `src/plugins/beads/.agents/skills/start-bead/closed-bead-preflight.sh` | 171 | Route Z preflight helper for start-bead. Pure-read (no `bd` writes). Follows `produced-bead-*` label chain on closed beads, detects cycles and dangling labels, emits a single `decision=...` line on stdout. |
| `src/plugins/beads/.agents/skills/start-bead/closed-bead-preflight.test.sh` | 193 | POSIX shell test suite for `closed-bead-preflight.sh`. Exercises all decision branches (proceed, forward, friendly-exit, halt/dangling, halt/multiple, halt/cycle, halt/error) using mocked `bd` commands. |
| `src/user/.agents/skills/condition-based-waiting/example.ts` | 158 | Complete TypeScript implementation of condition-based waiting utilities (`waitFor`, `waitForEvent`, `waitForEventCount`, `waitForEventMatch`) referenced by SKILL.md line 77 via `${CLAUDE_SKILL_DIR}/example.ts`. |
| `src/user/.agents/skills/merge-guard/check-merge-eligibility.sh` | 248 | Shell script that checks PR merge eligibility: queries GitHub for pending reviewers, Copilot review status (requested/in-progress/complete), and unseen comment count. Exits 0 (eligible), 1 (review in progress), 2 (unseen comments), 3 (error). Invoked from SKILL.md Step 2 via `${CLAUDE_SKILL_DIR}/check-merge-eligibility.sh`. |
| `src/user/.agents/skills/ralf-implement/foreign-agent-prompt.md` | 70 | Prompt template for the cross-model foreign-agent review pass (cycle 1 via Codex, cycle 2 via Gemini) in `ralf-implement`. Not currently referenced from SKILL.md (see F13). |
| `src/user/.agents/skills/ralf-implement/foreign-eyes-prompt.md` | 136 | Prompt template for the foreign-eyes reviewer subagent in `ralf-implement`, including severity rubric, review focus areas, and output format. Not currently referenced from SKILL.md (see F13). |
| `src/user/.agents/skills/ralf-implement/fresh-eyes-prompt.md` | 81 | Prompt template for the pure-Claude fresh-eyes pass in `ralf-implement` (cycle 3+). Not currently referenced from SKILL.md (see F13). |
| `src/user/.agents/skills/ralf-implement/implementer-prompt.md` | 45 | Prompt template for the implementer subagent in `ralf-implement`. Not currently referenced from SKILL.md (see F13). |
| `src/user/.agents/skills/ralf-review/fresh-eyes-prompt.md` | 64 | Prompt template for the fresh-eyes reviewer subagent in `ralf-review`. Not currently referenced from SKILL.md (see F13). |
| `src/user/.agents/skills/wait-for-pr-comments/detect-pr-push.sh` | 38 | PostToolUse hook script (registered in `settings.json.template`). Detects `gh pr create` or `git push` on a PR branch; emits a chat suggestion to invoke `wait-for-pr-comments`. Suggests, does not force invocation. |
| `src/user/.agents/skills/wait-for-pr-comments/lib.sh` | 31 | Shared helper library sourced by the polling scripts. Contains common functions for timestamp formatting, PR field extraction, and exit-code conventions. |
| `src/user/.agents/skills/wait-for-pr-comments/poll-copilot-rereview-start.sh` | 75 | Polls for the `copilot_work_started` event that follows a `review_requested` re-trigger (Phase 6). 80-second max window: 20s pre-sleep + 6×10s polls. Used to detect a fresh Copilot review cycle before launching the full review poller. |
| `src/user/.agents/skills/wait-for-pr-comments/poll-copilot-review.sh` | 205 | Polls GitHub GraphQL for Copilot review completion on a PR. Supports `--skip-request-check` and `--since-timestamp` for re-review guard. Exits 0 (review found), 1 (timeout), 2 (not requested), 3 (error). |
| `src/user/.agents/skills/wait-for-pr-comments/poll-new-comments.sh` | 104 | Polls a PR for new review comments after subagent fixes are pushed. Used in Phase 6 re-review detection to distinguish fresh Copilot feedback from stale cached reviews. |
| `src/user/.agents/skills/wait-for-pr-comments/validate-inventory.sh` | 98 | Enforces the nine schema validation guards on the hand-off contract JSON inventory. Exits 0 if valid; logs the violating item to stderr and exits non-zero on any guard failure. Invoked by Skill B Phase 0 before any replies are posted. |
| `src/user/.agents/skills/wait-for-pr-comments/write-inventory.sh` | 76 | Atomic write helper for the PR-review hand-off contract. Accepts `<state> <last_completed_phase> <path>` on invocation and JSON body on stdin; writes via `mktemp` + `mv` (POSIX-atomic) to prevent partial writes on crash. Also handles housekeeping: deletes inventory files older than 30 days. |
