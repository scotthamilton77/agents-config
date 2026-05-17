# Phase 1 Audit: Formulas
Auditor: audit-formulas subagent
SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851
Files audited: 5 formula TOML files

---

## Drift Check

Both `git diff` and `ls-files --others` returned empty. No drift detected. Proceeding.

---

## Summary

| Finding | File | Severity | Tier |
|---------|------|----------|------|
| F1 | brainstorm-bead | High | 2 |
| F2 | brainstorm-bead | Medium | 1 |
| F3 | brainstorm-bead | Medium | 2 |
| F4 | brainstorm-bead + docs-only + fix-bug + implement-feature | High | 2 |
| F5 | fix-bug + implement-feature | High | 2 |
| F6 | fix-bug | Medium | 1 |
| F7 | implement-feature | Low | 1 |
| F8 | merge-and-cleanup | Medium | 2 |
| F9 | merge-and-cleanup | Medium | 2 |
| F10 | merge-and-cleanup | High | 2 |
| F11 | all implementation formulas | Medium | 1 |
| F12 | brainstorm-bead | Medium | 1 |
| F13 | fix-bug | Low | 1 |
| F14 | docs-only + fix-bug + implement-feature | High | 2 |

---

## Findings

---

F1: brainstorm-bead `finalize` step — massive inline shell script is a helper-script candidate
  File: src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml:228-651
  Category: formula
  Severity: High
  Tier: 2
  Issue: The `finalize` step description is ~420 lines of interleaved prose and bash. It includes full shell scripts for idempotency probing (Step 1), pre-flight children checks (Step 2), Y-field computation (Step 3a–3h), implementation bead creation via helper invocation (Step 4), children migration (Step 5a–5b), dep-edge migration (Step 6), label stamping (Step 7), close-walk (Step 8), and wisp burn (Step 9). While some of these sequences correctly delegate to helper scripts (`bd-finalize-create-impl-bead.sh`, `bd-migrate-deps.sh`, `bd-close-walk.sh`), the surrounding orchestration logic — especially Steps 1–3 and 5 — is several hundred lines of inline shell embedded in a TOML description string. The acid test is "will the agent need this to execute reliably?" The answer is: yes for the decision logic, but the deterministic shell sequences (orphan-probe jq pipes, children classification, label-copy filtering) should be extracted into helper scripts. Inlined shell sequences in formula prose drift without test coverage and inflate the agent's context unnecessarily. Step 3's `INTERACTIVE_REQUIRED` placeholder guards are the right model for agent-decision boundaries; the surrounding mechanical logic is not.
  Recommendation: Extract Steps 1 (idempotency probe), 2 (children pre-flight check), 3f (label-copy filtering), 5a (child migration loop), and 5b (merge-gate + [h]-child creation) into named helper scripts under `~/.beads/scripts/`. The `finalize` description should reference the scripts with their inputs/outputs and keep only the agent decision points (3c RALF triage, 3d formula selection, 3g SID, 9 burn + hand-off report). Step 3h (label assembly) may remain as prose since it is purely declarative. Target: reduce finalize from ~420 lines to under 100.
  Vision-advancement-tier: A
  Vision-advancement: Extracting deterministic orchestration logic from formula prose into helper scripts directly advances commitment 5 ("persist context so work survives compaction") — shorter, script-backed steps are more compaction-resistant and survive agent handoff with less context-window cost.
  Promotion-eligible: no

---

F2: brainstorm-bead — motivational rationale embedded in `claim` step prose
  File: src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml:41-51
  Category: formula
  Severity: Medium
  Tier: 1
  Issue: The `claim` step description contains the sentence "Brainstorming IS work — the bead's status must reflect that, so that `bd ready` and `bd list --status=open` never show a bead that is actively being brainstormed as 'available'." This is explanatory motivation, not execution instruction. The executing agent already knows why claim-walks are required (it reads the beads rules). This rationale adds weight without adding reliable execution value.
  Recommendation: Replace the motivational sentence with a bare statement of the action and its DoD. The sentence "The claim walk marks this bead and all ancestor epics in_progress. Read the `walked=N` output to confirm the chain depth." already provides the execution-relevant information. Remove the preceding rationale sentence.
  Vision-advancement-tier: C
  Vision-advancement: Removing background rationale from step prose reduces per-step context weight, which directly reduces agent judgment cycles wasted on non-executable content.

---

F3: brainstorm-bead — QUESTION FILTER duplicated across `assess` and `discuss` steps
  File: src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml:74-84 and 104-108
  Category: formula
  Severity: Medium
  Tier: 2
  Issue: The QUESTION FILTER (only ask when the answer has significant architectural/requirements implications OR there are conflicting directions) is stated in full in the `assess` step and then restated as a "reminder" in the `discuss` step. The full filter block appears twice. Since steps are read independently at execution time (each step description is copied into its bead), this duplication is intentional to some degree — but it adds ~10 lines of identical prose to `discuss` that could be compressed to a one-line back-reference.
  Recommendation: In the `discuss` step, replace the full QUESTION FILTER block with a compressed reference: "Apply the QUESTION FILTER from the assess step: only raise questions with significant architectural/requirements implications or conflicting direction — decide everything else yourself." This preserves the constraint without the full repetition.
  Vision-advancement-tier: A
  Vision-advancement: Reducing cross-step prose duplication lowers context cost per step bead, supporting commitment 5 (persisting context that survives compaction) — compacted step beads lose excess prose first.
  Promotion-eligible: no

---

F4: worktree-path encoding procedure duplicated across three formulas
  File: src/plugins/beads/.beads/formulas/docs-only.formula.toml:116-122; fix-bug.formula.toml:100-102 and 139-142; implement-feature.formula.toml:100-106 and 139-141
  Category: formula
  Severity: High
  Tier: 2
  Issue: The worktree-path label encoding/decoding procedure (`_ → _u`, `/ → __`) appears in prose form in at least five locations across three formula files: once in each `preflight` step for encoding, and once in each `red-tests`/`apply-edits` step for decoding. The TOML strings differ slightly (some have step numbers, some don't; `fix-bug` and `implement-feature` have the encoding note as a comment "apply IN ORDER" while `docs-only` adds a numbered decode procedure). This creates a drift risk: if the bijection changes, five prose locations must be updated in sync. Per the FORMULAS_PRIMER and SKILLS_PRIMER, deterministic sequences should be in helper scripts, not prose.
  Recommendation: Extract encoding and decoding into two helper scripts: `bd-worktree-path-encode.sh <path>` and `bd-worktree-path-decode.sh <encoded>`. Each `preflight` step reduces to a single script call; each consuming step reduces to `<path>=$(bd-worktree-path-decode.sh <label>)`. Flag for the audit-scripts subagent.
  Vision-advancement-tier: A
  Vision-advancement: Consolidating five copies of a fragile bijection into one canonical helper script advances commitment 4 (guardrail every completion claim with mechanical evidence) — a shared script can be tested once, whereas five prose copies cannot.
  Promotion-eligible: no

---

F5: reroute protocol (steps 1–11) near-identical across fix-bug and implement-feature
  File: src/plugins/beads/.beads/formulas/fix-bug.formula.toml:237-318; implement-feature.formula.toml:188-284
  Category: formula
  Severity: High
  Tier: 2
  Issue: Both `red-tests` steps contain a Reroute Protocol section (steps 1–11) that creates a `docs-only` clone bead, stamps labels, re-parents children, closes the original, burns the molecule, etc. The text in both files is ~90% identical. The only substantive differences are: (a) fix-bug has only Trigger A while implement-feature has Triggers A, B, and A+B combined; (b) the "Trigger B" rationale block in fix-bug.formula.toml explains why Trigger B is deliberately omitted. All the mechanical steps (2–11) are structurally identical and share the same shell sequences. This is the largest cross-formula duplication in the codebase.
  Recommendation: Extract the shared reroute logic into a helper script `bd-reroute-to-docs-only.sh --source-bead-id <id> --trigger-note "<text>" --mol-id <id>` that handles steps 2–11 mechanically. Each `red-tests` step description reduces to: (1) evaluate triggers, (2) call the script with the trigger note, (3) exit. The Trigger B rationale block in fix-bug is the only unique prose and should remain inline since it explains a deliberate design choice. Flag for the audit-scripts subagent.
  Vision-advancement-tier: A
  Vision-advancement: Eliminating ~90 lines of duplicated reroute logic advances commitment 5 (context persists through compaction and handoff) — a single tested script is more reliable than two prose copies that can silently diverge between formula updates.
  Promotion-eligible: no

---

F6: fix-bug — file header contains pure motivational prose
  File: src/plugins/beads/.beads/formulas/fix-bug.formula.toml:1-19
  Category: formula
  Severity: Medium
  Tier: 1
  Issue: The TOML file-level comment includes "The cardinal sin of bug fixing is patching the symptom. The `diagnose` stage is a hard gate: no tests are written until the root cause is identified." This is motivational framing — the kind of prose that belongs in a README or the spec document, not in a formula file that is parsed at runtime and whose comments are read by agents during formula maintenance. File-level TOML comments are not step descriptions, but they occupy mental space when an agent reads the formula for maintenance or extension.
  Recommendation: Remove the "cardinal sin" motivational sentence. Keep the factual description of the stage sequence and the "See:" and "Usage:" comments, which are actionable references. The `diagnose` step description already enforces the hard gate — the motivational framing is redundant.
  Vision-advancement-tier: C
  Vision-advancement: Removing non-actionable motivational prose from formula headers reduces maintenance cognitive load and keeps formula files in the "strict/lean" category appropriate to their role as execution templates.

---

F7: implement-feature — stale bead reference in file-level comment
  File: src/plugins/beads/.beads/formulas/implement-feature.formula.toml:12-14
  Category: formula
  Severity: Low
  Tier: 1
  Issue: The file-level comment reads: "Note: per-step model/effort flag passthrough from the shell driver is planned for bead 7bk.14. The driver does not currently read per-step Model/Effort fields or pass flags to `claude -p`." Embedding a bead ID in a formula comment is a staleness risk — if the bead is renamed, closed, or the ID scheme changes, this reference rots silently. It also describes a missing feature, which could mislead an agent reading the formula for execution.
  Recommendation: Remove the bead ID reference. Either state the limitation plainly ("Note: per-step model/effort flags in this file are informational only — the shell driver does not currently pass them to `claude -p`") or remove the note entirely if it will be addressed before this formula is widely deployed.
  Vision-advancement-tier: C
  Vision-advancement: Removing volatile bead ID references from formula comments prevents silent documentation rot that could mislead agents reading formulas for maintenance or extension.

---

F8: merge-and-cleanup — file header contains historical motivation, not execution context
  File: src/plugins/beads/.beads/formulas/merge-and-cleanup.formula.toml:1-19
  Category: formula
  Severity: Medium
  Tier: 2
  Issue: The file-level comment block opens with: "This formula exists because agents frequently skip completion gates (code review, simplification, test verification) during feature and bug work, and because merges have been authorized prematurely. It is designed to run standalone — as a trust-but-verify workflow — even when the implementing agent claimed to have done everything correctly." This is historical motivation explaining why the formula was created, not what an agent needs to execute it. The phrase "even when the implementing agent claimed to have done everything correctly" is a trust characterization that is not an execution instruction.
  Recommendation: Replace the "why it exists" paragraph with a one-line purpose statement: "Trust-but-verify merge workflow: checks completion gate evidence, triages all PR comments, requires explicit merge authorization, then cleans up artifacts." Move any design rationale to `docs/specs/bead-pipeline-architecture.md` where it can be read on demand. The phase list (Phases: 1–7) is actionable and should stay.
  Vision-advancement-tier: C
  Vision-advancement: Removing historical motivation from formula headers keeps the formula's runtime-readable content strictly execution-serving, per the "Strict" acid test for formulas.
  Promotion-eligible: no

---

F9: merge-and-cleanup `merge-authorization` step — historical rationale embedded as step prose
  File: src/plugins/beads/.beads/formulas/merge-and-cleanup.formula.toml:184-219
  Category: formula
  Severity: Medium
  Tier: 2
  Issue: The `merge-authorization` step ends with: "This gate exists because merges have been performed without explicit authorization, causing irreversible state changes." This is a historical incident explanation — the kind of "why" that belongs in a rule or spec document, not in step prose that is read at execution time. Similarly, the "When in doubt: they have not authorized it. Ask again." sentence is good execution guidance but the preceding historical sentence is pure motivation.
  Recommendation: Remove the final historical sentence ("This gate exists because..."). The "When in doubt: they have not authorized it. Ask again." sentence is execution-serving and should stay. The examples of sufficient vs. insufficient authorization are execution-critical and must stay.
  Vision-advancement-tier: C
  Vision-advancement: Removing incident-retrospective language from step prose reduces execution noise without losing any enforcement value — the gate behavior is defined by the examples and the "wait for explicit authorization" instruction, not by the historical rationale.
  Promotion-eligible: no

---

F10: merge-and-cleanup `cleanup` step — inline merge-gate detection shell is a helper script candidate
  File: src/plugins/beads/.beads/formulas/merge-and-cleanup.formula.toml:271-299
  Category: formula
  Severity: High
  Tier: 2
  Issue: Step 4 of the `cleanup` step contains an inline bash loop and jq pipeline for detecting the merge-gate child: iterating children, calling `bd label list` per child, checking for the `merge-gate` label, detecting duplicates, and building the `MERGE_GATE` variable. This is ~15 lines of deterministic shell embedded in prose. Per the acid test, the agent does not need to read this shell to make any decision — it needs to invoke a helper that handles the detection and returns the merge-gate child ID (or an error). The same loop pattern appears implicitly in brainstorm-bead's finalize (where the pattern is used for children classification).
  Recommendation: Extract into a helper script `bd-find-merge-gate-child.sh --bead-id <id>` that outputs the merge-gate child ID on success (exit 0) or exits non-zero with a diagnostic. The `cleanup` step references the script: `MERGE_GATE=$(bd-find-merge-gate-child.sh --bead-id {{bead-id}}) || { flag-human; exit 1; }`. Flag for the audit-scripts subagent.
  Vision-advancement-tier: A
  Vision-advancement: Extracting the merge-gate detection loop into a tested helper advances commitment 4 (guardrail completion claims with mechanical evidence) — the helper can be run deterministically in CI while inline prose cannot.
  Promotion-eligible: no

---

F11: `name` field mirrors `id` throughout implement-feature and fix-bug — undocumented field
  File: src/plugins/beads/.beads/formulas/implement-feature.formula.toml:47-48 (and all steps); fix-bug.formula.toml:46-47 (and all steps)
  Category: formula
  Severity: Medium
  Tier: 1
  Issue: Both `implement-feature` and `fix-bug` set `name = "..."` on every step, mirroring `id` exactly. The FORMULAS_PRIMER does not list `name` as a valid step field (valid fields: `id`, `title`, `type`, `priority`, `description`, `notes`, `labels`, `assignee`, `needs`/`depends_on`, `condition`, `expand`, `expand_vars`, `gate`, `loop`, `on_complete`, `metadata`). The in-file comment on the first step says it "is accepted by bd... and serves as the stage-role identifier used by the shell driver." If this is a documented extension for the shell driver, it should be documented in a comment once at the top of each file, not repeated on every step. If it is not load-bearing for the formula runtime, it is noise.
  Recommendation: Confirm whether `name` is required by the shell driver. If required, add one top-level file comment explaining the convention and remove the per-step comment ("name mirrors id intentionally — id is the structural key; name is the human-readable label") from every step. If not required, remove all `name` fields. Note: `docs-only.formula.toml` also sets `name` on every step, extending this issue to 3 formulas.
  Vision-advancement-tier: C
  Vision-advancement: Removing redundant undocumented fields reduces per-step noise and makes formulas easier to audit and maintain as the field set evolves.

---

F12: brainstorm-bead — `phase = "vapor"` conflicts with `pour = true`
  File: src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml:25-26
  Category: formula
  Severity: Medium
  Tier: 1
  Issue: The formula sets `phase = "vapor"` (which per the FORMULAS_PRIMER signals "recommend wisp" — ephemeral, not persisted to git) AND `pour = true` (which materializes steps into the DB on pour, implying durability). The primer defines these as semantically opposite: vapor → wisp (ephemeral), liquid → pour (persistent). The usage comment at the top of the file uses `bd mol wisp create`, consistent with `phase = "vapor"`. But `pour = true` is set, which is the `liquid` convention. The primer says: "Rule of thumb: if you need a full audit trail across git history, pour a molecule. If it's a fire-and-forget operational run... wisp it." Brainstorming sessions need an audit trail and cross-session persistence.
  Recommendation: Decide which behavior is correct. If brainstorm-bead should be a wisp (ephemeral, no git trail), remove `pour = true`. If it should be poured (persisted, audit trail), change `phase = "liquid"` and update the usage comment to use `bd mol pour`. Given that brainstorm-bead produces implementation beads and requires cross-session state, `phase = "liquid"` with `pour = true` is the correct configuration.
  Vision-advancement-tier: A
  Vision-advancement: Resolving the vapor/pour contradiction ensures brainstorm-bead sessions are durably tracked across git history, directly supporting commitment 5 (context persists through compaction and agent handoff) — a vaporized brainstorm session cannot be recovered after compaction.

---

F13: fix-bug `diagnose` step references `superpowers:root-cause-tracing` — unverified skill name
  File: src/plugins/beads/.beads/formulas/fix-bug.formula.toml:134-135
  Category: formula
  Severity: Low
  Tier: 1
  Issue: The `diagnose` step lists `superpowers:root-cause-tracing` as a preloaded skill. This skill name does not appear in the known skill inventory (AGENTS.md system-reminder lists `superpowers:systematic-debugging` but not `superpowers:root-cause-tracing`). If the skill does not exist, the agent will receive no skill content when it invokes this name, and the step description's instruction to "Apply superpowers:systematic-debugging and superpowers:root-cause-tracing" will silently degrade — the agent will attempt to invoke a skill that returns nothing.
  Recommendation: Verify whether `superpowers:root-cause-tracing` exists as an installed skill. If it does not exist, remove it from the preloaded skills list and remove the invocation instruction. If `superpowers:systematic-debugging` covers the root-cause-tracing use case, reference only that skill.
  Vision-advancement-tier: C
  Vision-advancement: Removing references to non-existent skills prevents silent degradation in skill invocation, ensuring the agent's debugging methodology is actually loaded at step execution time.

---

F14: preflight spec validation logic duplicated across docs-only, fix-bug, and implement-feature
  File: src/plugins/beads/.beads/formulas/docs-only.formula.toml:50-93; fix-bug.formula.toml:50-114; implement-feature.formula.toml:51-116
  Category: formula
  Severity: High
  Tier: 2
  Issue: The `preflight` step in all three implementation formulas shares a large block of near-identical logic: (1) verify `brainstormed` + `implementation-ready` labels, (2) check `[coverage].applicable` and handle opt-out, (3) check `[coverage].report-location` and handle missing-config with the human-flag protocol, (4) stamp `for-bead-<mol-id>` label, (5) create worktree with the encoding procedure, (6) stamp `worktree-path-*` label, (7) claim-walk. Steps 1, 2, 3, and 7 are mechanically identical across all three formulas. Steps 4–6 differ only in branch prefix (`docs/`, `fix/`, `feat/`). This is the second-largest duplication pattern after F5. A coverage-config gap in one formula's prose (e.g., the handling of `applicable = false`) has already diverged slightly between `docs-only` (which explicitly skips coverage checks with a comment) and the other two.
  Recommendation: Extract the shared preflight logic into a helper script `bd-preflight.sh --bead-id <id> --mol-id <id> --branch-prefix <prefix>` that handles label verification, coverage config checks, worktree creation, path encoding, and claim-walk. Each `preflight` step description reduces to the script invocation and documents only the formula-specific branch prefix. This eliminates ~60 lines of near-identical prose per formula. Flag for the audit-scripts subagent.
  Vision-advancement-tier: A
  Vision-advancement: Consolidating three copies of the preflight protocol into one tested helper directly advances commitment 4 (guardrail every completion claim with mechanical evidence) — human-flag protocol consistency can be enforced in one place, preventing the silent divergence already visible between docs-only and the other formulas.
  Promotion-eligible: no

---

## Cross-Formula Consistency Notes

**Terminology**: All five formulas use "worktree" consistently. No terminology inconsistency found.

**Model/effort annotations**: `docs-only`, `fix-bug`, and `implement-feature` annotate each step with `Model: claude-X  Effort: Y` inline in the description. `brainstorm-bead` and `merge-and-cleanup` do not. This is a minor inconsistency but not a finding since the model/effort fields are not currently read by the shell driver (per F7 note).

**`phase` vs. usage comment alignment**: `docs-only` is `phase = "liquid"` with `bd mol pour` usage — correct. `fix-bug` and `implement-feature` are `phase = "liquid"` with `bd mol pour` — correct. `merge-and-cleanup` is `phase = "liquid"` with `bd mol wisp create` in the usage comment — potential inconsistency (the usage comment says wisp but the phase says liquid). Not flagged as a separate finding because the phase note may be intentional (persistent tracking for a merge operation).

**TOML structural validity**: All five formulas have `formula`, `version`, `type`, and `[[steps]]` with `id` and `title`. All `needs` references point to step IDs that exist within the same formula. No broken dependency edges found.

---

## Helper Script Candidacy Summary (for audit-scripts subagent)

The following inline shell sequences should be extracted and tracked:

| Location | Script name (proposed) | Lines saved |
|----------|----------------------|-------------|
| brainstorm-bead finalize Steps 1–2, 5 | `bd-finalize-preflight.sh` | ~80 |
| brainstorm-bead finalize Step 3f | absorbed into `bd-finalize-create-impl-bead.sh` | ~15 |
| docs-only + fix-bug + implement-feature preflight | `bd-preflight.sh` | ~60 per formula |
| fix-bug + implement-feature red-tests reroute steps 2–11 | `bd-reroute-to-docs-only.sh` | ~90 |
| merge-and-cleanup cleanup step 4 | `bd-find-merge-gate-child.sh` | ~15 |
| worktree-path encode/decode (5 locations) | `bd-worktree-path-encode.sh` + `bd-worktree-path-decode.sh` | ~10 each |

Total estimated line reduction across all 5 formulas: ~450 lines of prose replaced by script invocations.
