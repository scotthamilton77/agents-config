# Phase 3 By-Category: Scripts
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

This file consolidates all Phase 1 and Phase 2 findings targeting the scripts category.
Phase 2 full-bead-lifecycle (F6) also addresses scripts; included below.

---

F1: bd-record-decision.sh — usage block is a one-liner, inconsistent with sibling scripts
  File: src/plugins/beads/.beads/scripts/bd-record-decision.sh:28
  Category: script
  Severity: Medium
  Tier: 1
  Issue: The `usage()` function emits a terse one-line echo while all four sibling bd-toolkit scripts emit a full `cat >&2 <<'EOF'` block documenting every option, output format, and exit contract. --help on this script gives less information than on any other script in the same directory.
  Recommendation: Replace the one-line echo in usage() with a `cat >&2 <<'EOF' ... EOF` block covering: each option with type hint (--bead-id <id>, --title <text>, --notes <text>), the mutually exclusive flags (--implemented | --needs-approval), stdout output on success, and the exit code contract. Match the style of bd-close-walk.sh's usage block.
  Vision-advancement-tier: A
  Vision-advancement: Commitment #4 (guardrail completion claims) requires that helper scripts surface their contracts clearly; inconsistent usage blocks make automated error diagnosis harder.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/scripts.md:F1

---

F2: bd-record-decision.sh — stdout contract should stay human-readable; add opt-in --json mode if needed
  File: src/plugins/beads/.beads/scripts/bd-record-decision.sh:79-83
  Category: script
  Severity: Medium
  Tier: 2
  Issue: Phase 1 recommends changing the default stdout contract from human-readable to machine-readable key=value. Phase 2 formula-step-execution reviewer DISAGREE (D2): the audited formula callsite does not capture or parse stdout — the human-readable sentence is immediate confirmation that the decision bead was created. Changing the default would optimize for a caller model not present on the actual runtime path.
  Recommendation: Leave the default stdout behavior alone. Add an opt-in `--json` or `--machine` mode only if a concrete structured caller is introduced. Priority: fix the usage block (F1) first.
  Vision-advancement-tier: C
  Vision-advancement: Avoids churn that does not improve the common execution path and preserves the immediately-readable confirmation the step currently benefits from.
  Promotion-eligible: no
  Resolution: DROPPED (per D2)
  Rationale: Phase 2 DISAGREE accepted — changing the default stdout is not warranted without a concrete structured caller.
  Sources: phase1/scripts.md:F2, phase2/formula-step-execution.md:F4

---

F3: poll-ready-beads.sh — no named-parameter interface, no error guards, wrong shebang
  File: src/plugins/beads/.agents/skills/run-queue/poll-ready-beads.sh:14
  Category: script
  Severity: High
  Tier: 2
  Issue: `MAX_MINUTES="${1:-}"` accepted purely positionally with no --max-minutes flag, no --help flag, no usage block. Calling with `--max-minutes 60` silently treats `--max-minutes` as the value (not integer). Also uses `#!/bin/bash` (not `#!/usr/bin/env bash`), breaking portability. Phase 2 full-bead-lifecycle reviewer AGREE: this script is the queue's idle-state backbone and too flimsy for autonomous overnight use.
  Recommendation: Add `--max-minutes <N>` named flag with --help and usage(). Add guard that rejects non-integer values with a clear error. Change shebang to `#!/usr/bin/env bash`. Target of agents-config-2gzy.
  Vision-advancement-tier: A
  Vision-advancement: Commitment #4 (guardrail completion claims) requires polling scripts fail loudly on bad input rather than silently producing wrong results.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 AGREE (full-bead-lifecycle:F6).
  Sources: phase1/scripts.md:F3, phase2/full-bead-lifecycle.md:F6

---

F4: poll-ready-beads.sh — timeout message on stdout contaminates machine-readable channel
  File: src/plugins/beads/.agents/skills/run-queue/poll-ready-beads.sh:25-27,31
  Category: script
  Severity: Medium
  Tier: 2
  Issue: Exit 0 emits valid JSON on stdout. Exit 1 emits plain-text timeout message on stdout. A caller that captures stdout and pipes to jq will get a JSON parse error on the timeout path. Phase 2 full-bead-lifecycle reviewer AGREE.
  Recommendation: Move the timeout message to stderr. On exit 1, emit a JSON sentinel on stdout: `echo '{"status":"timeout"}'`. This aligns with poll-copilot-review.sh which already does this correctly.
  Vision-advancement-tier: A
  Vision-advancement: Commitment #4 (guardrail completion claims) depends on scripts producing reliably machine-parseable output.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 AGREE (full-bead-lifecycle:F6 bundles all poll-ready-beads.sh issues).
  Sources: phase1/scripts.md:F4, phase2/full-bead-lifecycle.md:F6

---

F5: check-merge-eligibility.sh — positional-only parameters, no named interface
  File: src/user/.agents/skills/merge-guard/check-merge-eligibility.sh:1-38
  Category: script
  Severity: High
  Tier: 2
  Issue: All three parameters (`owner/repo`, `pr-number`, `comments-seen`) are positional. Particularly hazardous for `comments-seen` which could easily be transposed with the PR number by an LLM-generated invocation. Incorrect transposition produces misleading eligibility results, potentially allowing an un-reviewed PR to merge. Otherwise has strong error handling and a well-defined JSON stdout contract.
  Recommendation: Add named flags (--repo, --pr, --comments-seen) while preserving the positional fallback for backward compatibility. Add a full usage() block using `cat >&2 <<'EOF' ... EOF` pattern consistent with bd-toolkit scripts. Coordinate with agents-config-2gzy to avoid duplicate refactor passes.
  Vision-advancement-tier: A
  Vision-advancement: Commitment #4 (guardrail completion claims) requires the merge-guard is invocable without fragile positional ordering.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not directly address; Phase 1 finding stands.
  Sources: phase1/scripts.md:F5

---

F6: check-merge-eligibility.sh — duplicates lib.sh helpers inline
  File: src/user/.agents/skills/merge-guard/check-merge-eligibility.sh:55-75
  Category: script
  Severity: Low
  Tier: 1
  Issue: Contains its own `gh_api()` function, `gh auth status` pre-flight check, and `jq` availability check — all already defined in `src/user/.agents/skills/wait-for-pr-comments/lib.sh`. Two implementations that must stay in sync manually.
  Recommendation: Consider promoting lib.sh to a shared location (e.g., `src/user/.agents/skills/shared/lib.sh`) so check-merge-eligibility.sh can source it. If cross-skill sourcing is not desired, at minimum add a comment referencing `wait-for-pr-comments/lib.sh` as the canonical source.
  Vision-advancement-tier: C
  Vision-advancement: Reduces code duplication and drift risk, improving long-term maintainability of the shared GitHub API layer.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands as Tier 1.
  Sources: phase1/scripts.md:F6

---

F7: closed-bead-preflight.sh — intentional mixed positional+flag interface; document explicitly
  File: src/plugins/beads/.agents/skills/start-bead/closed-bead-preflight.sh:9-11,30-50
  Category: script
  Severity: Low
  Tier: 2
  Issue: Interface mixes conventions: primary required argument (`target-id`) is positional while optional arguments use `--flag=value` syntax. The design choice is defensible and documented in the header comment. Test suite exercises this interface thoroughly.
  Recommendation: When agents-config-2gzy addresses interface normalization, explicitly evaluate whether `--target <id>` is preferable to the positional convention. If the positional is kept, add a note in the header explaining why it was intentional. Record the decision either way.
  Vision-advancement-tier: C
  Vision-advancement: Interface consistency across the script suite reduces cognitive load on LLM callers and lowers the chance of argument mis-ordering.
  Promotion-eligible: yes
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/scripts.md:F7

---

F8: poll-ready-beads.sh — missing set -euo pipefail
  File: src/plugins/beads/.agents/skills/run-queue/poll-ready-beads.sh:1
  Category: script
  Severity: High
  Tier: 1
  Issue: Script uses `#!/bin/bash` with no `set -e`, `set -u`, or `set -o pipefail`. All other scripts use `set -euo pipefail` or `set -e`. Without `set -e`, a failed `bd ready` or `jq` call continues silently. Without `set -u`, unset variable produces empty string. Active hazard for an autonomous polling script running in the background.
  Recommendation: Add `set -euo pipefail` immediately after the shebang. Review the `jq ... || echo "0"` fallback on line 22 — with pipefail this may need adjustment to `(jq 'length' 2>/dev/null || echo "0")`.
  Vision-advancement-tier: A
  Vision-advancement: Commitment #4 (guardrail completion claims) requires background polling scripts fail loudly rather than silently; missing set -e is an active hazard for overnight autonomous runs.
  Resolution: ACCEPTED
  Rationale: Phase 2 full-bead-lifecycle AGREE (F6 bundles this with other poll-ready-beads.sh issues).
  Sources: phase1/scripts.md:F8, phase2/full-bead-lifecycle.md:F6

---

F9: validate-inventory.sh — non-standard exit codes undocumented
  File: src/user/.agents/skills/wait-for-pr-comments/validate-inventory.sh:13-23
  Category: script
  Severity: Low
  Tier: 1
  Issue: Script exits with codes 64 (EX_USAGE), 65 (EX_DATAERR), 66 (EX_NOINPUT) — BSD sysexits.h values. Comment header documents only `exit 0` (pass) and `exit non-zero` (fail). A caller who sees `exit 64` with no context may not know whether to retry, escalate, or treat as a validation error.
  Recommendation: Add an exit-code table to the header comment: `# Exit codes: 0 — all guards pass; 1 — validation failed; 64 — wrong arg count (EX_USAGE); 65 — jq write failed (EX_DATAERR); 66 — input file not found (EX_NOINPUT)`.
  Vision-advancement-tier: C
  Vision-advancement: Consistent exit-code documentation reduces agent troubleshooting time when a script exits unexpectedly.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/scripts.md:F9

---

F10: write-inventory.sh — non-standard exit codes undocumented
  File: src/user/.agents/skills/wait-for-pr-comments/write-inventory.sh:27-49
  Category: script
  Severity: Low
  Tier: 1
  Issue: Same issue as F9: exit codes 64 (EX_USAGE) and 65 (EX_DATAERR) are correct per sysexits.h but undocumented in the header.
  Recommendation: Add exit-code table to the header comment, same pattern as F9. Note that `exit 65` on jq failure is consistent with EX_DATAERR (syntactically invalid input JSON).
  Vision-advancement-tier: C
  Vision-advancement: Same rationale as F9 — consistent exit-code documentation reduces escalation load.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/scripts.md:F10

---

F11: poll-copilot-rereview-start.sh — hardcoded polling schedule, not configurable
  File: src/user/.agents/skills/wait-for-pr-comments/poll-copilot-rereview-start.sh:49-71
  Category: script
  Severity: Low
  Tier: 1
  Issue: Script hardcodes `sleep 20` (initial pre-sleep) + `6 × sleep 10` (poll loop) = 80-second maximum window. Sibling poll-new-comments.sh accepts `<interval-secs>` and `<max-duration-secs>` as arguments. The hardcoded 80-second window may be too short for high-latency GitHub environments or too long for fast CI setups.
  Recommendation: Extract `INITIAL_SLEEP`, `POLL_INTERVAL`, and `POLL_COUNT` as optional named arguments (with current values as defaults), matching poll-new-comments.sh's pattern. This is a medium-term improvement; current hardcoded values are functional.
  Vision-advancement-tier: B
  Vision-advancement: Making poll timing configurable closes a gap in the wall-clock pipelining vision (vision-85-5-10 tag: "Wall-clock pipelining across external waits — future work").
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/scripts.md:F11

---

F12: lib.sh — validate_repo and preflight_checks functions have no doc comments
  File: src/user/.agents/skills/wait-for-pr-comments/lib.sh:17-31
  Category: script
  Severity: Low
  Tier: 1
  Issue: `validate_repo()` and `preflight_checks()` have no doc comments describing their side effects (exit codes, error behavior). A sourcing script that doesn't know `validate_repo` exits 3 on failure might not set up its own cleanup trap before calling it.
  Recommendation: Add brief function-level doc comments: `# validate_repo <owner/repo> — exits 3 if format invalid` and `# preflight_checks — exits 3 if gh auth fails or jq missing`.
  Vision-advancement-tier: C
  Vision-advancement: Reduces noise in troubleshooting when a sourcing script exits unexpectedly due to a preflight failure.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/scripts.md:F12

---

F13: detect-pr-push.sh — uses echo instead of printf for JSON parsing
  File: src/user/.agents/skills/wait-for-pr-comments/detect-pr-push.sh:10-15
  Category: script
  Severity: Low
  Tier: 1
  Issue: Lines 10-15 use `echo "$input" | jq ...` to extract fields from hook payload. Most other scripts use `printf '%s' "$var" | jq ...` to avoid echo interpretation of escape sequences. If hook payload contains `\t` or `\n`, echo would silently corrupt it.
  Recommendation: Replace `echo "$input" | jq` with `printf '%s' "$input" | jq` on lines 10, 14, 15. Three-line mechanical change.
  Vision-advancement-tier: C
  Vision-advancement: Reduces a latent data-corruption risk in hook payload parsing, protecting PR detection reliability.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/scripts.md:F13

---

F14: bd-finalize-create-impl-bead.sh — tr flag-name derivation fragile for multi-word env var names
  File: src/plugins/beads/.beads/scripts/bd-finalize-create-impl-bead.sh:119
  Category: script
  Severity: Low
  Tier: 1
  Issue: Required-arg validation loop derives `--flag-name` from variable name via `echo "$_flag_var" | tr '[:upper:]_' '[:lower:]-'`. The `tr` character-class positional alignment is subtly fragile: if a variable with a digit or non-alpha char is added to the validation loop, the alignment assumption breaks silently.
  Recommendation: Replace with two separate `tr` calls: `echo "$_flag_var" | tr '[:upper:]' '[:lower:]' | tr '_' '-'`. This removes the alignment dependency. Low-priority polish item.
  Vision-advancement-tier: C
  Vision-advancement: Reduces a latent fragility in argument validation that could silently emit a wrong flag name in an error message.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/scripts.md:F14

---

## agents-config-2gzy Coverage Note

The bead `agents-config-2gzy` ("refactor skill helper scripts to named parameters") should prioritize:

1. F3 + F4 + F8 (`poll-ready-beads.sh`): positional param, missing set -euo pipefail, stdout contamination. Highest risk — active hazard for autonomous runs.
2. F5 (`check-merge-eligibility.sh`): positional params for a three-arg script where arg-ordering errors bypass the merge gate.
3. F1 (`bd-record-decision.sh`): usage block inconsistency. Can be addressed in same commit as 2gzy or independently.
4. F7 (`closed-bead-preflight.sh`): intentional interface asymmetry — document the decision, do not necessarily change it.
