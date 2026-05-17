# Phase 1 Audit: Scripts
Auditor: audit-scripts subagent
SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851
Files audited: 16 shell scripts (5 bd-toolkit + 11 skill-supporting)

## Drift check
Both `git diff` and `ls-files --others` on `src/plugins/beads/.beads/scripts/` were empty — no drift from audit SHA.

---

## Summary

The five bd-toolkit scripts (`bd-claim-walk.sh`, `bd-close-walk.sh`, `bd-finalize-create-impl-bead.sh`, `bd-migrate-deps.sh`, `bd-record-decision.sh`) are notably well-crafted: named parameters throughout, `--help` / usage blocks, `set -euo pipefail`, structured stdout contracts, and meaningful idempotency guards. They are the target of bead `agents-config-2gzy` and largely represent the refactored ideal the project is converging toward.

The skill-supporting scripts split cleanly into two quality tiers:

- **Strong tier** (`closed-bead-preflight.sh`, `closed-bead-preflight.test.sh`, `validate-inventory.sh`, `write-inventory.sh`, all `wait-for-pr-comments/` scripts): named or well-documented positional interfaces, error paths surfaced, exit codes meaningful.
- **Weak tier** (`poll-ready-beads.sh`, `check-merge-eligibility.sh`): positional-only interfaces, no named params, minimal or no `--help`, and one case of diagnostic output on stdout that contaminates the machine-readable channel.

Specific findings follow. Numbers F1–F7 are Tier 2 (judgment/interface redesign); F8–F11 are Tier 1 (mechanical, inline). F12–F14 are polish-level.

---

## Findings

F1: `bd-record-decision.sh` usage block is a one-liner, mismatched to sibling scripts
  File: src/plugins/beads/.beads/scripts/bd-record-decision.sh:28
  Category: script
  Severity: Medium
  Tier: 1 (mechanical, inline)
  Issue: The `usage()` function emits a terse one-line `echo` while all four sibling bd-toolkit scripts emit a full `cat >&2 <<'EOF'` block documenting every option, output format, and exit contract. The discrepancy means `--help` on `bd-record-decision.sh` gives less information than on any other script in the same directory. A developer (or agent) reading the help for all five scripts will get inconsistent self-documentation.
  Recommendation: Replace the one-line `echo` in `usage()` with a `cat >&2 <<'EOF' ... EOF` block that covers: each option with a type hint (--bead-id <id>, --title <text>, --notes <text>), the mutually exclusive flags (--implemented | --needs-approval), stdout output on success, and the exit code contract. Match the style of `bd-close-walk.sh`'s usage block.
  Vision-advancement-tier: A
  Vision-advancement: Commitment 4 (guardrail every completion claim with mechanical evidence) requires that helper scripts surface their contracts clearly; inconsistent usage blocks make automated error diagnosis by agents harder and increase troubleshooting escalations.
  Related: F2

F2: `bd-record-decision.sh` outputs to stdout on success instead of a machine-readable line
  File: src/plugins/beads/.beads/scripts/bd-record-decision.sh:79-83
  Category: script
  Severity: Medium
  Tier: 2 (design, deferred)
  Issue: On success the script emits human-readable sentences to stdout ("Decision DEC_ID created and closed …"). Every sibling bd-toolkit script emits a single key=value line (e.g. `walked=N`, `closed=csv`). Callers that capture stdout in a variable to parse the outcome cannot distinguish the human text from the bead ID. Callers that only care about the ID currently have no reliable way to extract it without parsing prose.
  Recommendation: Define an explicit stdout contract — emit `decision-id=<DEC_ID>` (one key=value line) on success, move the human-readable sentence to stderr. This matches the sibling convention and makes the script composable without parsing fragility. Callers must be updated to consume the new key=value line instead of discarding stdout.
  Vision-advancement-tier: A
  Vision-advancement: Commitment 5 (persist context so work survives handoff) depends on agents being able to capture and store bead IDs reliably; prose stdout breaks that chain and forces fragile text parsing or manual triage.
  Promotion-eligible: yes
  Related: F1

F3: `poll-ready-beads.sh` uses positional parameter with no named-parameter interface
  File: src/plugins/beads/.agents/skills/run-queue/poll-ready-beads.sh:14
  Category: script
  Severity: High
  Tier: 2 (design, deferred)
  Issue: `MAX_MINUTES="${1:-}"` is the only parameter, accepted purely positionally with no `--max-minutes` flag, no `--help` flag, and no usage block. The comment header documents the positional convention, but there is no runtime guard: calling the script with `--max-minutes 60` silently treats `--max-minutes` as the value (string, not integer), which then causes an integer comparison failure inside the loop rather than a clean argument error. The script also uses `#!/bin/bash` (not `#!/usr/bin/env bash`), breaking portability on systems where bash is not at `/bin/bash` (rare but not impossible in container environments).
  Recommendation: Add `--max-minutes <N>` named flag with `--help` and `usage()`. Add a guard that rejects non-integer values with a clear error. Change shebang to `#!/usr/bin/env bash`. This script is a target for `agents-config-2gzy`.
  Vision-advancement-tier: A
  Vision-advancement: Commitment 4 (guardrail every completion claim) requires that polling scripts fail loudly on bad input rather than silently producing wrong results; a silent integer-comparison failure in the main loop would cause the poll to never time out, blocking autonomous overnight runs.
  Promotion-eligible: yes
  Related: F4

F4: `poll-ready-beads.sh` mixes machine-readable JSON and diagnostic text on stdout
  File: src/plugins/beads/.agents/skills/run-queue/poll-ready-beads.sh:25-27, 31
  Category: script
  Severity: Medium
  Tier: 2 (design, deferred)
  Issue: Exit 0 emits `$RESULT` (valid JSON) on stdout. Exit 1 emits `"No implementation-ready beads found after ${MAX_MINUTES} minutes."` as plain text on stdout. A caller that captures stdout and pipes to `jq` will get a JSON parse error on the timeout path. The sibling toolkit scripts emit all diagnostics to stderr and emit only structured data (key=value or JSON) to stdout.
  Recommendation: Move the timeout message to stderr: `echo "No implementation-ready beads found after ${MAX_MINUTES} minutes." >&2`. On exit 1, emit a JSON sentinel on stdout if callers need a parseable result: `echo '{"status":"timeout"}'`. This aligns with `poll-copilot-review.sh` which already does this correctly.
  Vision-advancement-tier: A
  Vision-advancement: Commitment 4 (guardrail every completion claim with mechanical evidence) depends on scripts producing reliably machine-parseable output so agents can act on results without fragile text matching.
  Promotion-eligible: yes
  Related: F3

F5: `check-merge-eligibility.sh` uses positional-only parameters, no named interface
  File: src/user/.agents/skills/merge-guard/check-merge-eligibility.sh:1-38
  Category: script
  Severity: High
  Tier: 2 (design, deferred)
  Issue: All three parameters (`owner/repo`, `pr-number`, `comments-seen`) are positional. The usage block (a two-line `echo` in `usage()`) documents the order, but there is no `--repo`, `--pr`, or `--comments-seen` named flag, and no `--help` trigger. While the positional interface is documented in the comment header, callers must remember the exact order. This is particularly hazardous for `comments-seen` which is a count that could easily be transposed with the PR number by an LLM-generated invocation. The script otherwise has strong error handling, meaningful exit codes, pre-flight checks, and a well-defined JSON stdout contract.
  Recommendation: Add named flags (`--repo`, `--pr`, `--comments-seen`) while preserving the positional fallback for backward compatibility if callers exist. Add a full `usage()` block using `cat >&2 <<'EOF' ... EOF` pattern consistent with the bd-toolkit scripts. This is a 2gzy-adjacent concern; coordinate with that bead to avoid duplicate refactor passes.
  Vision-advancement-tier: A
  Vision-advancement: Commitment 4 (guardrail every completion claim with mechanical evidence) requires that the merge-guard is invocable without fragile positional ordering; an LLM that swaps PR-number and comments-seen will get misleading eligibility results, potentially allowing an un-reviewed PR to merge.
  Promotion-eligible: yes
  Related: F6

F6: `check-merge-eligibility.sh` duplicates `lib.sh` helpers inline
  File: src/user/.agents/skills/merge-guard/check-merge-eligibility.sh:55-75
  Category: script
  Severity: Low
  Tier: 1 (mechanical, inline)
  Issue: `check-merge-eligibility.sh` contains its own `gh_api()` function, `gh auth status` pre-flight check, and `jq` availability check — all of which are already defined in `src/user/.agents/skills/wait-for-pr-comments/lib.sh`. The two implementations are functionally identical but diverge in one cosmetic detail: `check-merge-eligibility.sh` prefixes the gh auth error with "Error:", while `lib.sh` uses "Error:" too — so no behavioral divergence today, but any future change to the shared logic requires two edits. The scripts live in separate skill directories, so a simple `source lib.sh` is not obviously possible without restructuring, but the duplication is still worth flagging.
  Recommendation: Consider promoting `lib.sh` to a shared location (e.g. `src/user/.agents/skills/shared/lib.sh`) so `check-merge-eligibility.sh` can source it. If cross-skill sourcing is not desired, at minimum add a comment referencing `wait-for-pr-comments/lib.sh` as the canonical source. This is a structural decision; defer to bead tracking if the change is non-trivial.
  Vision-advancement-tier: C
  Vision-advancement: Reduces code duplication and drift risk, improving long-term maintainability of the shared GitHub API layer.
  Related: F5

F7: `closed-bead-preflight.sh` uses a mixed positional + `--flag=value` interface
  File: src/plugins/beads/.agents/skills/start-bead/closed-bead-preflight.sh:9-11, 30-50
  Category: script
  Severity: Low
  Tier: 2 (design, deferred)
  Issue: The interface mixes conventions: the primary required argument (`target-id`) is positional while the optional arguments (`--original=<id>`, `--chain=<csv>`) use `--flag=value` syntax. This is deliberately asymmetric — the positional target maps to the recursive agent invocation pattern where the target is always the first word. The design choice is defensible and documented in the header comment, but it diverges from the `--flag value` convention of the bd-toolkit scripts. The test suite (`closed-bead-preflight.test.sh`) exercises this interface thoroughly. No change is urgently required, but the interface deviation should be noted for the 2gzy refactor to consciously decide whether to normalize it.
  Recommendation: When 2gzy addresses interface normalization, explicitly evaluate whether `--target <id>` is preferable to the positional convention. If the positional is kept, add a note in the header explaining why it was intentional. Either way, the decision should be recorded, not left implicit.
  Vision-advancement-tier: C
  Vision-advancement: Interface consistency across the script suite reduces the cognitive load on LLM callers and lowers the chance of argument mis-ordering during autonomous overnight runs.
  Promotion-eligible: yes
  Related: F3, F5

F8: `poll-ready-beads.sh` missing `set -euo pipefail`
  File: src/plugins/beads/.agents/skills/run-queue/poll-ready-beads.sh:1
  Category: script
  Severity: High
  Tier: 1 (mechanical, inline)
  Issue: The script uses `#!/bin/bash` and has no `set -e`, `set -u`, or `set -o pipefail`. All other scripts in this audit use `set -euo pipefail` (the bd-toolkit scripts, `check-merge-eligibility.sh`, `poll-copilot-review.sh`, etc.) or at minimum `set -e` (`closed-bead-preflight.sh`). Without `set -e`, a failed `bd ready` or `jq` call inside the loop continues silently. Without `set -u`, an unset variable reference (e.g. if `MAX_MINUTES` logic were ever extended) produces an empty string rather than an error. This is an active hazard for an autonomous polling script that runs in the background.
  Recommendation: Add `set -euo pipefail` immediately after the shebang. Review the `jq ... || echo "0"` fallback on line 22 — with `pipefail` this may need adjustment to `(jq 'length' 2>/dev/null || echo "0")` to prevent the fallback from being masked. Test the loop's error behavior after adding the safety flags.
  Vision-advancement-tier: A
  Vision-advancement: Commitment 4 (guardrail every completion claim with mechanical evidence) requires that background polling scripts fail loudly rather than silently producing wrong results; missing `set -e` is an active hazard for overnight autonomous runs.
  Related: F3, F4

F9: `validate-inventory.sh` uses non-standard exit codes (64, 65, 66) without documentation
  File: src/user/.agents/skills/wait-for-pr-comments/validate-inventory.sh:13-23
  Category: script
  Severity: Low
  Tier: 1 (mechanical, inline)
  Issue: The script exits with codes 64 (EX_USAGE), 65 (EX_DATAERR), 66 (EX_NOINPUT) — BSD sysexits.h values. This is a legitimate convention, but the comment header documents only `exit 0` (pass) and `exit non-zero` (fail) without explaining the specific codes or referencing sysexits. The `usage()` block for `poll-ready-beads.sh` and the bd-toolkit scripts all document their exit codes explicitly. A caller who sees `exit 64` with no context may not know whether to retry, escalate, or treat it as a validation error.
  Recommendation: Add an exit-code table to the header comment, matching the pattern of `poll-copilot-review.sh` and `check-merge-eligibility.sh`. E.g.: `# Exit codes: 0 — all guards pass; 1 — validation failed; 64 — wrong arg count (EX_USAGE); 65 — jq write failed (EX_DATAERR); 66 — input file not found (EX_NOINPUT)`.
  Vision-advancement-tier: C
  Vision-advancement: Consistent exit-code documentation across all scripts reduces agent troubleshooting time when a script exits unexpectedly, supporting the 5% troubleshooting-escalation target.

F10: `write-inventory.sh` uses non-standard exit codes (64, 65) without documentation
  File: src/user/.agents/skills/wait-for-pr-comments/write-inventory.sh:27-49
  Category: script
  Severity: Low
  Tier: 1 (mechanical, inline)
  Issue: Same issue as F9: exit codes 64 (EX_USAGE) and 65 (EX_DATAERR) are used correctly per sysexits.h but are undocumented in the header. The usage block says only "exit 64" in the arg-count guard but provides no exit-code table.
  Recommendation: Add exit-code table to the header comment, same pattern as F9. Also note that `exit 65` on jq failure is consistent with `EX_DATAERR` (the input JSON was syntactically invalid), which is the correct code — just needs to be made visible.
  Vision-advancement-tier: C
  Vision-advancement: Same rationale as F9 — consistent exit-code documentation reduces escalation load.
  Related: F9

F11: `poll-copilot-rereview-start.sh` hardcodes polling schedule without documentation
  File: src/user/.agents/skills/wait-for-pr-comments/poll-copilot-rereview-start.sh:49-71
  Category: script
  Severity: Low
  Tier: 1 (mechanical, inline)
  Issue: The script hardcodes `sleep 20` (initial pre-sleep) + `6 × sleep 10` (poll loop) = 80-second maximum window. These constants appear in the diagnostics line (`"20s pre-sleep + 6 × 10s = 80s max window"`) but are not configurable via arguments. The sibling `poll-new-comments.sh` by contrast accepts `<interval-secs>` and `<max-duration-secs>` as arguments, making it reusable across different timing requirements. The hardcoded 80-second window may be too short for high-latency GitHub environments or too long for fast CI setups.
  Recommendation: Extract `INITIAL_SLEEP`, `POLL_INTERVAL`, and `POLL_COUNT` as optional named arguments (with the current values as defaults), matching `poll-new-comments.sh`'s pattern. This is a medium-term improvement; the current hardcoded values are functional and the script is otherwise well-structured.
  Vision-advancement-tier: B
  Vision-advancement: Making poll timing configurable closes a gap in the wall-clock pipelining vision (`vision-85-5-10` tag: "Wall-clock pipelining across external waits — future work"), allowing the skill to adapt to different CI response times without code changes.

F12: `lib.sh` has no usage comment for the `validate_repo` and `preflight_checks` functions
  File: src/user/.agents/skills/wait-for-pr-comments/lib.sh:17-31
  Category: script
  Severity: Low
  Tier: 1 (mechanical, inline)
  Issue: `lib.sh` is a sourced library, not a standalone script, so it correctly has no shebang argument parsing. However, `validate_repo()` and `preflight_checks()` have no doc comments describing their side effects (exit codes, error behavior). The `gh_api()` function has a one-line comment. A sourcing script that doesn't know `validate_repo` exits 3 on failure might not set up its own cleanup trap before calling it.
  Recommendation: Add brief function-level doc comments: `# validate_repo <owner/repo> — exits 3 if format invalid` and `# preflight_checks — exits 3 if gh auth fails or jq missing`. One line each is sufficient.
  Vision-advancement-tier: C
  Vision-advancement: Reduces noise in troubleshooting when a sourcing script exits unexpectedly due to a preflight failure.

F13: `detect-pr-push.sh` uses unquoted `echo "$input" | jq` pattern inconsistently
  File: src/user/.agents/skills/wait-for-pr-comments/detect-pr-push.sh:10-15
  Category: script
  Severity: Low
  Tier: 1 (mechanical, inline)
  Issue: Lines 10–15 use `echo "$input" | jq ...` to extract fields from the hook payload. Most other scripts in this suite use `printf '%s' "$var" | jq ...` to avoid `echo` interpretation of escape sequences (e.g. `echo` treats `\n` as a newline on some shells). The pattern is harmless for typical JSON that doesn't contain backslash sequences, but the inconsistency is a minor maintenance trap: if the hook payload ever contains `\t` or `\n` in a command string, `echo` would silently corrupt it.
  Recommendation: Replace `echo "$input" | jq` with `printf '%s' "$input" | jq` on lines 10, 14, 15. Three-line mechanical change.
  Vision-advancement-tier: C
  Vision-advancement: Reduces a latent data-corruption risk in hook payload parsing, which protects PR detection reliability for automated delivery workflows.

F14: `bd-finalize-create-impl-bead.sh` flag-name derivation via `tr` is fragile for multi-word env var names
  File: src/plugins/beads/.beads/scripts/bd-finalize-create-impl-bead.sh:119
  Category: script
  Severity: Low
  Tier: 1 (mechanical, inline)
  Issue: The required-arg validation loop derives `--flag-name` from the variable name via `echo "$_flag_var" | tr '[:upper:]_' '[:lower:]-'`. For `SOURCE_BEAD_ID` this yields `source-bead-id`, which is correct. However, `tr '[:upper:]_' '[:lower:]-'` maps the underscore character using character-class positional alignment: `[:upper:]` has 26 chars, `[:lower:]` has 26 chars — so the `_` in the first set and `-` in the second set align correctly. This works today, but the idiom is subtly fragile: if someone extends the validation loop to include a variable with a digit or a non-alpha char, the `tr` character-class alignment assumption breaks silently. The loop also uses `${!_flag_var}` (bash indirect expansion) which is not POSIX, but the script is already bash-only via `set -euo pipefail` so this is fine.
  Recommendation: Replace the `tr` derivation with an explicit `declare -A` mapping from variable name to flag name, or use a simpler `echo "$_flag_var" | tr '[:upper:]' '[:lower:]' | tr '_' '-'` (two separate `tr` calls removes the alignment dependency). This is a low-priority polish item — the current code works correctly for the current set of variables.
  Vision-advancement-tier: C
  Vision-advancement: Reduces a latent fragility in argument validation that could silently emit a wrong flag name in an error message, making escalation diagnostics harder to read.

---

## Coverage note for `agents-config-2gzy`

The bead `agents-config-2gzy` ("refactor skill helper scripts to named parameters") should prioritize:

1. **F3 + F8** (`poll-ready-beads.sh`): positional param, no `set -euo pipefail`, stdout contamination. Highest risk — active hazard for autonomous runs.
2. **F5** (`check-merge-eligibility.sh`): positional params for a three-arg script where arg-ordering errors are consequential (merge gate bypass risk).
3. **F2** (`bd-record-decision.sh`): stdout contract mismatch vs. sibling scripts.
4. **F7** (`closed-bead-preflight.sh`): intentional interface asymmetry — document the decision rather than changing it.

F1 (usage block on `bd-record-decision.sh`) is Tier 1 and can be addressed in the same commit as 2gzy or independently.
