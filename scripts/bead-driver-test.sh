#!/usr/bin/env bash
# scripts/bead-driver-test.sh
# Minimal test harness for the per-stage claude -p bead pipeline (bead 7bk.9).
#
# IMPORTANT: This is a TEST HARNESS only. It is interactive, single-instance,
# and MUST NOT run unattended in production. Continuous-loop autonomy requires
# the production driver from agents-config-7bk.11. Until then, the architecture
# runs in operator-supervised single-shot mode.
#
# Behavior:
#   1. Polls bd for implementation-ready beads via:
#        bd ready --label implementation-ready --json
#   2. For each ready bead, spawns:
#        claude -p --session-id <uuidv5> "/implement-bead <bead-id>"
#      from the correct cwd per the architecture's cwd contract.
#   3. Waits for the claude process to exit, then loops.
#
# Usage:
#   bash scripts/bead-driver-test.sh [--once] [--dry-run]
#
# Options:
#   --once      Process one bead then exit (useful for testing)
#   --dry-run   Print what would be run without spawning claude processes
#
# Environment variables:
#   REPO_ROOT   Override the repository root (default: git toplevel)
#   POLL_INTERVAL_SECS  Seconds between bd ready polls (default: 5)

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || echo "${SCRIPT_DIR}/..")}"
POLL_INTERVAL_SECS="${POLL_INTERVAL_SECS:-5}"

OPT_ONCE=false
OPT_DRY_RUN=false

for arg in "$@"; do
  case "${arg}" in
    --once)     OPT_ONCE=true ;;
    --dry-run)  OPT_DRY_RUN=true ;;
    *)
      echo "Unknown option: ${arg}" >&2
      echo "Usage: $0 [--once] [--dry-run]" >&2
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# UUIDv5 derivation
# Namespace pinned per architecture spec section 5.3.
# ---------------------------------------------------------------------------
NAMESPACE_UUID="27ece4fd-4a06-49bf-a921-bf07ecb0dc10"

uuidv5() {
  local name="$1"
  if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found — required for UUIDv5 derivation" >&2
    exit 1
  fi
  python3 -c "import sys, uuid; print(uuid.uuid5(uuid.UUID(sys.argv[1]), sys.argv[2]))" \
    "${NAMESPACE_UUID}" "${name}"
}

# ---------------------------------------------------------------------------
# cwd resolution per architecture spec section 5.4
# ---------------------------------------------------------------------------
resolve_cwd() {
  local bead_id="$1"
  local stage_role="$2"

  case "${stage_role}" in
    preflight|merge-or-handoff)
      echo "${REPO_ROOT}"
      ;;
    *)
      # Decode worktree-path-* label from the bead's active molecule.
      local mol_id encoded_path decoded_path
      mol_id=$(bd list --label "for-bead-${bead_id}" --type molecule --json 2>/dev/null \
        | python3 -c "import sys,json; mols=[m for m in json.load(sys.stdin) if m.get('status')!='closed']; print(mols[0]['id'] if mols else '')" 2>/dev/null || true)

      if [ -z "${mol_id}" ]; then
        # No active molecule yet — fall back to repo root (preflight will pour one).
        echo "${REPO_ROOT}"
        return
      fi

      # Decode worktree-path label: first __ -> /, then _u -> _
      encoded_path=$(bd label list "${mol_id}" 2>/dev/null \
        | grep '^worktree-path-' | head -1 | sed 's/^worktree-path-//' || true)

      if [ -z "${encoded_path}" ]; then
        echo "${REPO_ROOT}"
        return
      fi

      decoded_path=$(python3 -c "
import sys
s = sys.argv[1]
out = s.replace('__', '\x00').replace('_u', '_').replace('\x00', '/')
print(out)
" "${encoded_path}")
      echo "${decoded_path}"
      ;;
  esac
}

# ---------------------------------------------------------------------------
# Main poll loop
# ---------------------------------------------------------------------------
echo "==> bead-driver-test.sh starting"
echo "    REPO_ROOT: ${REPO_ROOT}"
echo "    POLL_INTERVAL_SECS: ${POLL_INTERVAL_SECS}"
"${OPT_ONCE}" && echo "    Mode: --once (exit after first bead)"
"${OPT_DRY_RUN}" && echo "    Mode: --dry-run (no claude processes spawned)"
echo ""

if ! command -v bd &>/dev/null; then
  echo "ERROR: 'bd' not found on PATH — install beads before running this driver" >&2
  exit 1
fi

if ! command -v claude &>/dev/null && ! "${OPT_DRY_RUN}"; then
  echo "ERROR: 'claude' not found on PATH — install Claude Code CLI before running this driver" >&2
  exit 1
fi

processed=0

while true; do
  # Query for implementation-ready beads (excludes human-labeled beads per bd semantics).
  ready_beads=$(bd ready --label implementation-ready --json 2>/dev/null || echo '[]')
  count=$(echo "${ready_beads}" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)

  if [ "${count}" -eq 0 ]; then
    if "${OPT_ONCE}" && [ "${processed}" -gt 0 ]; then
      echo "==> No more ready beads. Exiting (--once)."
      exit 0
    fi
    echo "    No implementation-ready beads. Polling again in ${POLL_INTERVAL_SECS}s..."
    sleep "${POLL_INTERVAL_SECS}"
    continue
  fi

  echo "==> Found ${count} implementation-ready bead(s)"

  # Process the highest-priority ready bead (lowest numeric priority value = highest urgency).
  bead_id=$(echo "${ready_beads}" | python3 -c "
import sys, json
beads = json.load(sys.stdin)
beads.sort(key=lambda b: b.get('priority', 99))
print(beads[0]['id'] if beads else '')
" 2>/dev/null || true)

  if [ -z "${bead_id}" ]; then
    echo "    Could not parse bead ID from ready list. Sleeping..." >&2
    sleep "${POLL_INTERVAL_SECS}"
    continue
  fi

  # Determine current stage from the molecule's current step.
  mol_id_for_stage=$(bd list --label "for-bead-${bead_id}" --type molecule --json 2>/dev/null \
    | python3 -c "import sys,json; mols=[m for m in json.load(sys.stdin) if m.get('status')!='closed']; print(mols[0]['id'] if mols else '')" 2>/dev/null || true)
  if [ -z "${mol_id_for_stage}" ]; then
    stage_role="preflight"
  else
    stage_role=$(bd mol current "${mol_id_for_stage}" --json 2>/dev/null \
      | python3 -c "
import sys, json
data = json.load(sys.stdin)
steps = data if isinstance(data, list) else [data]
ready = [s for s in steps if s.get('status') not in ('closed',) and s.get('id')]
if not ready:
    sys.exit('ERROR: no current step found in molecule')
print(ready[0].get('role') or ready[0].get('id'))
" 2>/dev/null)
    if [ -z "${stage_role}" ]; then
      echo "ERROR: could not determine current stage for mol ${mol_id_for_stage} — molecule may be complete or malformed" >&2
      sleep "${POLL_INTERVAL_SECS}"
      continue
    fi
  fi

  # Derive session ID (UUIDv5) for resumable sessions.
  session_id=$(uuidv5 "${bead_id}:${stage_role}")

  # Resolve cwd for this stage.
  stage_cwd=$(resolve_cwd "${bead_id}" "${stage_role}")

  echo "    Bead:     ${bead_id}"
  echo "    Stage:    ${stage_role}"
  echo "    cwd:      ${stage_cwd}"
  echo "    Session:  ${session_id}"

  if "${OPT_DRY_RUN}"; then
    echo "    [dry-run] would spawn: claude -p --session-id ${session_id} \"/implement-bead ${bead_id}\""
  else
    echo "    Spawning claude -p ..."
    (cd "${stage_cwd}" && claude -p --session-id "${session_id}" "/implement-bead ${bead_id}")
    echo "    claude -p exited."
  fi

  processed=$((processed + 1))

  if "${OPT_ONCE}"; then
    echo "==> Exiting after one bead (--once)."
    exit 0
  fi

  # Brief pause before next poll to avoid hammering bd.
  sleep "${POLL_INTERVAL_SECS}"
done
