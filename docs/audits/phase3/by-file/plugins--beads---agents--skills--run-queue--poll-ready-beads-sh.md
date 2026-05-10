# Findings for src/plugins/beads/.agents/skills/run-queue/poll-ready-beads.sh
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

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
