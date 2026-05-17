#!/usr/bin/env bash
# bootstrap-installer-beads.sh
#
# Bootstrap the bd work-tracking structure for the Python installer rewrite.
# See docs/specs/2026-05-17-python-installer-rewrite.md for the full spec
# and dependency graph.
#
# Creates (in full-run mode):
#   1   feature bead   (container)
#   8   epic beads     (containers, parented to the feature)
#   34  story beads    (parented to their respective epic)
#   52  blocks deps    (story -> direct prereqs, drawn exhaustively up front)
#
# Tasks under each story (test-plan-review / red-phase / green-phase /
# verify-gate) are NOT created here. They land just-in-time when each
# story moves to in_progress.
#
# Idempotency: YES. Beads are matched by title against existing bd state on
# every run; matching beads are reused (no duplicates). Dependency edges are
# attempted unconditionally; "already exists" errors from `bd dep add` are
# tolerated as no-ops. Safe to re-run after a partial failure.
#
# Epic targeting:
#   ./bootstrap-installer-beads.sh                # all epics A-H (default)
#   ./bootstrap-installer-beads.sh A B            # only epics A and B
#   ./bootstrap-installer-beads.sh F              # only epic F
#   ./bootstrap-installer-beads.sh --help         # usage
#
# Cross-epic dep edges are attempted against the full title->id cache built
# from existing bd state plus newly-created beads in this run. Edges whose
# endpoints are not yet known are silently skipped (will be added on a later
# run once the missing endpoint exists).
#
# Prerequisites:
#   - bd CLI on PATH
#   - jq on PATH
#   - run from /Users/scott/src/projects/agents-config (or any beads-init'd dir)

set -euo pipefail

SPEC="docs/specs/2026-05-17-python-installer-rewrite.md"

############################################################
# CLI parsing
############################################################
print_usage() {
    cat <<'EOF'
Usage: bootstrap-installer-beads.sh [EPIC...]

  Default (no args): create/reconcile all epics A-H.
  Otherwise: create/reconcile only the listed epics.

  EPIC letters are case-insensitive: A B C D E F G H.

  -h, --help   Show this usage and exit.

Idempotent: re-running creates no duplicates. Safe to invoke after a partial
failure. Cross-epic dep edges land whenever both endpoints exist.
EOF
}

declare -a TARGET_EPICS
if [[ $# -eq 0 ]]; then
    TARGET_EPICS=(A B C D E F G H)
else
    TARGET_EPICS=()
    for arg in "$@"; do
        case "$arg" in
            -h|--help) print_usage; exit 0 ;;
            *)
                arg_upper="$(printf '%s' "$arg" | tr '[:lower:]' '[:upper:]')"
                if [[ ! "$arg_upper" =~ ^[A-H]$ ]]; then
                    echo "ERROR: invalid epic letter '$arg' (must be one of A B C D E F G H)" >&2
                    exit 1
                fi
                TARGET_EPICS+=("$arg_upper")
                ;;
        esac
    done
fi

epic_enabled() {
    local needle="$1"
    local e
    for e in "${TARGET_EPICS[@]}"; do
        [[ "$e" == "$needle" ]] && return 0
    done
    return 1
}

############################################################
# Title->ID cache and bd helpers
############################################################
declare -A BEAD_IDS

bd_load_existing() {
    # Populate BEAD_IDS with every active bead's title -> id from bd's state.
    # Filter is --status open,in_progress: we ignore closed beads to cut noise.
    # Trade-off: if a bootstrap bead is closed and the script re-runs, that
    # closed bead will not appear in the cache and a duplicate will be created.
    # Don't close bootstrap beads if you intend to re-run this script.
    # --limit 0 returns all rows. Errors are tolerated (fresh bd may be empty).
    local payload
    payload=$(bd list --status open,in_progress --json --limit 0 2>/dev/null || echo "[]")
    while IFS=$'\t' read -r id title; do
        [[ -n "$id" && -n "$title" ]] && BEAD_IDS["$title"]="$id"
    done < <(printf '%s' "$payload" | jq -r '.[] | "\(.id)\t\(.title)"' 2>/dev/null || true)
}

# bd_ensure TITLE [bd-create-args...]
# Returns the bead ID on stdout. If a bead with the given TITLE already exists
# (in BEAD_IDS), returns its existing ID without creating. Otherwise creates,
# captures the new ID, caches it, and returns it.
bd_ensure() {
    local title="$1"; shift
    if [[ -n "${BEAD_IDS[$title]:-}" ]]; then
        printf '%s' "${BEAD_IDS[$title]}"
        return 0
    fi
    local new_id
    new_id=$(bd create --title "$title" "$@" --json \
        | jq -r 'if type == "array" then .[0].id else .id end // empty')
    if [[ -z "$new_id" ]]; then
        echo "ERROR: bd create failed for title: $title" >&2
        return 1
    fi
    BEAD_IDS["$title"]="$new_id"
    printf '%s' "$new_id"
}

# lookup_id TITLE
# Returns the cached bead ID for TITLE, or an empty string if unknown.
lookup_id() {
    printf '%s' "${BEAD_IDS[$1]:-}"
}

# ensure_edge CHILD_ID PARENT_ID
# Adds a `blocks` dependency edge (child depends on parent). Idempotent:
# tolerates bd's "already exists" error if the edge is present from a prior run.
# Skips silently if either ID is empty (endpoint not yet created).
ensure_edge() {
    local child="$1"
    local parent="$2"
    [[ -z "$child" || -z "$parent" ]] && return 0
    local output
    if output=$(bd dep add "$child" "$parent" 2>&1); then
        return 0
    fi
    if printf '%s' "$output" | grep -qiE 'already|duplicate|exists'; then
        return 0
    fi
    echo "ERROR: bd dep add $child $parent failed:" >&2
    echo "$output" >&2
    return 1
}

# edge_by_title CHILD_TITLE PARENT_TITLE
# Resolves titles to IDs via the cache, then adds the edge.
edge_by_title() {
    ensure_edge "$(lookup_id "$1")" "$(lookup_id "$2")"
}

############################################################
# Title constants — single source of truth for title strings.
# Must match exactly between create and edge-add phases.
############################################################
# Feature is parented to milestone M0 (Discipline-layer rearchitecture:
# scripts own determinism, skills own judgment). Hardcoded by ID because
# milestones do not collide on title and the ID is stable.
M0_MILESTONE_ID="agents-config-wgclw"

T_FEATURE="Python installer rewrite (packages/installer/)"

T_EPIC_A="Epic A — Foundation"
T_EPIC_B="Epic B — First end-to-end claude install (minimal)"
T_EPIC_C="Epic C — DYNAMIC-INCLUDE completion + shared content"
T_EPIC_D="Epic D — Multi-tool"
T_EPIC_E="Epic E — Collision matrix"
T_EPIC_F="Epic F — Plugins"
T_EPIC_G="Epic G — Operations (backup, prune, debug)"
T_EPIC_H="Epic H — Parity gate + cutover"

T_A1="A.1 — uv-managed packages/installer/ scaffold + CI green"
T_A2="A.2 — core/model.py (dataclasses + enums)"
T_A3="A.3 — core/io_port.py (IOPort protocol + TerminalIO + ScriptedIO)"

T_B1="B.1 — config + tools/base + tools/claude + tools/registry + CLI --tools="
T_B2="B.2 — minimal core/sync.py (single-file copy, hash-skip, dry-run)"
T_B3="B.3 — .template suffix strip in staging"
T_B4="B.4 — DYNAMIC-INCLUDE file form"

T_C1="C.1 — Phase 1-2 equivalent: shared content staging"
T_C2="C.2 — DYNAMIC-INCLUDE ALL-RULES"
T_C3="C.3 — DYNAMIC-INCLUDE named-RULES"

T_D1="D.1 — Codex adapter"
T_D2="D.2 — Gemini adapter (no transform yet)"
T_D3="D.3 — OpenCode adapter (XDG dest + skip shared agents/)"
T_D4="D.4 — Gemini frontmatter transform"

T_E1="E.1 — core/merge/base.py + core/merge/registry.py"
T_E2="E.2 — strategies/append_rules.py"
T_E3="E.3 — strategies/fatal.py"
T_E4="E.4 — strategies/json_union.py"
T_E5="E.5 — strategies/last_wins_warn.py + last_wins_silent.py"

T_F1="F.1 — plugins/base + plugins/registry + synthetic test-plugin fixture"
T_F2="F.2 — Phase 6 plugin overlay (alphabetical, full collision matrix exercised)"
T_F3="F.3 — carrier-merge logic (in-memory metadata)"
T_F4="F.4 — plugins/beads.py (~/.beads/ destination + chmod +x)"

T_G1="G.1 — path-aware backup placement in core/sync.py"
T_G2="G.2 — installer.toml schema + loader"
T_G3="G.3 — core/prune.py orphan scan"
T_G4="G.4 — interactive prune flow via ScriptedIO"
T_G5="G.5 — --prune / --prune-only CLI integration"
T_G6="G.6 — --dump-stage <path> flag"

T_H1="H.1 — golden-master harness + first 3 scenarios (bare, settings, user-modified)"
T_H2="H.2 — remaining golden-master scenarios (prune, prune-only, plugin, single-tool, Gemini)"
T_H3="H.3 — parity confirmation (14-day clean CI + real-home smoke test)"
T_H4="H.4 — install.sh collapse + scripts/prune-list retirement"
T_H5="H.5 — docs cleanup (AGENTS.md + README + golden-master retirement)"

############################################################
# Phase 1: load existing state
############################################################
echo "==> Loading existing bd state"
bd_load_existing
echo "    Cached ${#BEAD_IDS[@]} pre-existing beads"
echo "    Target epics: ${TARGET_EPICS[*]}"

############################################################
# Phase 2: ensure Feature (always, regardless of target epics)
############################################################
echo "==> Ensuring Feature"
FEATURE=$(bd_ensure "$T_FEATURE" \
  --type feature --priority 1 \
  --parent "$M0_MILESTONE_ID" \
  --description "Port scripts/install.sh to a uv-managed Python package at packages/installer/. Establishes the monorepo packages/ precedent. See ${SPEC} for the full spec and dependency graph." \
  --acceptance "- packages/installer/ ships as a uv-managed Python package with unit, integration, and golden-master test coverage.
- All eight Epics (A–H) close green.
- install.sh collapses to a thin uv-run wrapper after the parity gate.
- AGENTS.md documents the golden-master retirement.")
echo "    FEATURE=$FEATURE"

############################################################
# Phase 3: ensure target Epics
############################################################
echo "==> Ensuring Epics"

EPIC_A=""; EPIC_B=""; EPIC_C=""; EPIC_D=""
EPIC_E=""; EPIC_F=""; EPIC_G=""; EPIC_H=""

if epic_enabled A; then
    EPIC_A=$(bd_ensure "$T_EPIC_A" \
      --type epic --parent "$FEATURE" --priority 1 \
      --description "uv-managed package scaffold; pure data model; IOPort protocol with TerminalIO + ScriptedIO. See ${SPEC} (Epic A).")
    echo "    EPIC_A=$EPIC_A"
fi
if epic_enabled B; then
    EPIC_B=$(bd_ensure "$T_EPIC_B" \
      --type epic --parent "$FEATURE" --priority 1 \
      --description "Config + ClaudeAdapter; minimal sync; .template suffix strip; DYNAMIC-INCLUDE file form. See ${SPEC} (Epic B).")
    echo "    EPIC_B=$EPIC_B"
fi
if epic_enabled C; then
    EPIC_C=$(bd_ensure "$T_EPIC_C" \
      --type epic --parent "$FEATURE" --priority 1 \
      --description "Phase 1-2 shared content staging; ALL-RULES directive; named-RULES directive. See ${SPEC} (Epic C).")
    echo "    EPIC_C=$EPIC_C"
fi
if epic_enabled D; then
    EPIC_D=$(bd_ensure "$T_EPIC_D" \
      --type epic --parent "$FEATURE" --priority 1 \
      --description "Codex / Gemini / OpenCode adapters; Gemini frontmatter transform. See ${SPEC} (Epic D).")
    echo "    EPIC_D=$EPIC_D"
fi
if epic_enabled E; then
    EPIC_E=$(bd_ensure "$T_EPIC_E" \
      --type epic --parent "$FEATURE" --priority 1 \
      --description "MergeStrategy protocol + registry; append_rules, fatal, json_union, last_wins strategies (each its own module). See ${SPEC} (Epic E).")
    echo "    EPIC_E=$EPIC_E"
fi
if epic_enabled F; then
    EPIC_F=$(bd_ensure "$T_EPIC_F" \
      --type epic --parent "$FEATURE" --priority 1 \
      --description "PluginAdapter protocol + registry; Phase 6 overlay; carrier-merge via in-memory metadata; beads plugin. See ${SPEC} (Epic F).")
    echo "    EPIC_F=$EPIC_F"
fi
if epic_enabled G; then
    EPIC_G=$(bd_ensure "$T_EPIC_G" \
      --type epic --parent "$FEATURE" --priority 1 \
      --description "Path-aware backup; installer.toml loader; orphan scan; interactive prune; --prune / --prune-only / --dump-stage flags. See ${SPEC} (Epic G).")
    echo "    EPIC_G=$EPIC_G"
fi
if epic_enabled H; then
    EPIC_H=$(bd_ensure "$T_EPIC_H" \
      --type epic --parent "$FEATURE" --priority 1 \
      --description "Golden-master harness + scenarios; parity confirmation; install.sh collapse; prune-list retirement; docs cleanup. See ${SPEC} (Epic H).")
    echo "    EPIC_H=$EPIC_H"
fi

############################################################
# Phase 4: ensure Stories (only for target epics)
############################################################

# ---- Epic A ----
if epic_enabled A && [[ -n "$EPIC_A" ]]; then
    echo "==> Creating Stories (Epic A)"

    bd_ensure "$T_A1" \
      --type story --parent "$EPIC_A" --priority 1 \
      --description "Stand up packages/installer/ with pyproject.toml (Python 3.11+; ruff, mypy, pytest dev-deps). scripts/install.py stub. Hello-world test. CI runs pytest + ruff + mypy and is green. No installer behaviour yet." \
      --acceptance "- packages/installer/pyproject.toml declares uv-managed deps.
- scripts/install.py prints --help and exits 0.
- CI runs pytest, ruff check, mypy --strict on a hello-world test; all green.
- No installer behaviour yet." > /dev/null
    echo "    A.1=$(lookup_id "$T_A1")"

    bd_ensure "$T_A2" \
      --type story --parent "$EPIC_A" --priority 1 \
      --description "Pure data model: Tool, Plugin, FileKind, StagedItem, StagingPlan, Orphan, IncludeDirective, Counters dataclasses + enums. No behaviour beyond invariants and equality." \
      --acceptance "- All listed dataclasses and enums exist with documented types.
- Frozen where the spec calls for it (Config, ToolPaths).
- Unit tests cover construction, equality, immutability." > /dev/null
    echo "    A.2=$(lookup_id "$T_A2")"

    bd_ensure "$T_A3" \
      --type story --parent "$EPIC_A" --priority 1 \
      --description "IOPort protocol with info/ok/warn/err/header/show_diff/confirm/confirm_three_way/confirm_per_item/is_interactive methods. TerminalIO real impl uses rich. ScriptedIO fake records transcript and consumes scripted answers." \
      --acceptance "- IOPort protocol defined.
- TerminalIO and ScriptedIO both implement the protocol.
- ScriptedIO raises informatively when exhausted.
- Unit tests confirm script consumption order and transcript recording." > /dev/null
    echo "    A.3=$(lookup_id "$T_A3")"
fi

# ---- Epic B ----
if epic_enabled B && [[ -n "$EPIC_B" ]]; then
    echo "==> Creating Stories (Epic B)"

    bd_ensure "$T_B1" \
      --type story --parent "$EPIC_B" --priority 1 \
      --description "Config dataclass; ToolAdapter protocol in tools/base.py; ClaudeAdapter with detection + dest_dir + namespaces; tools/registry.py for adapter lookup. CLI parses --tools= and validates against the registry." \
      --acceptance "- ToolAdapter protocol defined.
- ClaudeAdapter detects ~/.claude correctly via injected home.
- CLI parses --tools=claude; rejects unknown tools.
- Auto-detect includes claude unconditionally." > /dev/null
    echo "    B.1=$(lookup_id "$T_B1")"

    bd_ensure "$T_B2" \
      --type story --parent "$EPIC_B" --priority 1 \
      --description "Smallest possible sync engine: copy one source file to one dest file. Hash-compare to skip no-op writes. Honour --dry-run." \
      --acceptance "- One-file install produces the expected dest file.
- Re-run with no source change is a no-op (no writes).
- --dry-run produces no writes; preview output mentions the would-be write." > /dev/null
    echo "    B.2=$(lookup_id "$T_B2")"

    bd_ensure "$T_B3" \
      --type story --parent "$EPIC_B" --priority 1 \
      --description "Files named *.template in source get the suffix stripped on the way into the StagingPlan." \
      --acceptance "- AGENTS.md.template arrives at the dest as AGENTS.md.
- Files without the suffix pass through untouched.
- Tests cover both cases." > /dev/null
    echo "    B.3=$(lookup_id "$T_B3")"

    bd_ensure "$T_B4" \
      --type story --parent "$EPIC_B" --priority 1 \
      --description "Recognise the file-include marker in templates and substitute the referenced file content. Missing file emits a warning and leaves the marker line empty (matching bash behaviour)." \
      --acceptance "- A template with one DYNAMIC-INCLUDE file marker resolves to the inlined content.
- Missing-file directive produces a warning, not a hard fail.
- Non-directive lines pass through unchanged.
- Trailing newlines preserved iff template had one." > /dev/null
    echo "    B.4=$(lookup_id "$T_B4")"
fi

# ---- Epic C (monotonic dep order: C.1 -> C.2 -> C.3) ----
if epic_enabled C && [[ -n "$EPIC_C" ]]; then
    echo "==> Creating Stories (Epic C)"

    bd_ensure "$T_C1" \
      --type story --parent "$EPIC_C" --priority 1 \
      --description "Stage shared content from src/user/.agents/ (agents, skills, rules) into the active tool StagingPlan. Collisions deferred to Epic E; this story uses no-collision fixtures." \
      --acceptance "- Shared agents/, skills/, rules/ items arrive in the claude plan.
- Items go to the correct namespace in the dest.
- Tests use no-collision fixtures; collision behaviour is out of scope for this story." > /dev/null
    echo "    C.1=$(lookup_id "$T_C1")"

    bd_ensure "$T_C2" \
      --type story --parent "$EPIC_C" --priority 1 \
      --description "Recognise the ALL-RULES marker and expand to all rules in the staging rules collection, sorted, joined with the literal three-character separator newline-three-dashes-newline." \
      --acceptance "- ALL-RULES directive expands to concatenated rules in lexicographic order.
- Separator is exactly newline-three-dashes-newline between adjacent rules.
- Empty rules collection produces a warning and a blank expansion." > /dev/null
    echo "    C.2=$(lookup_id "$T_C2")"

    bd_ensure "$T_C3" \
      --type story --parent "$EPIC_C" --priority 1 \
      --description "Recognise the named-RULES marker (comma-list payload) and expand to the named subset of rules, in argument order, joined with the standard separator. Capability has no current consumer in any template; retained for symmetry per the spec." \
      --acceptance "- named-RULES directive expands to the listed rules in argument order.
- Unknown rule name produces a warning, not a hard fail.
- Empty list expands to blank." > /dev/null
    echo "    C.3=$(lookup_id "$T_C3")"
fi

# ---- Epic D ----
if epic_enabled D && [[ -n "$EPIC_D" ]]; then
    echo "==> Creating Stories (Epic D)"

    bd_ensure "$T_D1" \
      --type story --parent "$EPIC_D" --priority 1 \
      --description "CodexAdapter: source = src/user/.codex/; dest = ~/.codex/; detected when ~/.codex/ exists. Registered in tools/registry.py." \
      --acceptance "- CodexAdapter implements ToolAdapter.
- Detection probe uses injected home.
- Integration test: --tools=codex install produces ~/.codex/ tree with the codex template flattened." > /dev/null
    echo "    D.1=$(lookup_id "$T_D1")"

    bd_ensure "$T_D2" \
      --type story --parent "$EPIC_D" --priority 1 \
      --description "GeminiAdapter: source = src/user/.gemini/; dest = ~/.gemini/; detected via dir existence. Frontmatter transform deferred to D.4." \
      --acceptance "- GeminiAdapter implements ToolAdapter.
- Integration test: --tools=gemini produces ~/.gemini/GEMINI.md with DYNAMIC-INCLUDE flattened.
- No frontmatter transform applied yet (verified by leaving Claude-style frontmatter untouched)." > /dev/null
    echo "    D.2=$(lookup_id "$T_D2")"

    bd_ensure "$T_D3" \
      --type story --parent "$EPIC_D" --priority 1 \
      --description "OpenCodeAdapter: source = src/user/.opencode/; dest = ~/.config/opencode/ (XDG); should_install_namespace returns False for shared agents/. Detected via opencode-on-PATH OR ~/.config/opencode/ existence." \
      --acceptance "- OpenCodeAdapter resolves dest to ~/.config/opencode/.
- Shared agents/ from src/user/.agents/ are NOT installed under OpenCode.
- Tool-specific opencode.jsonc.template lands at ~/.config/opencode/opencode.jsonc." > /dev/null
    echo "    D.3=$(lookup_id "$T_D3")"

    bd_ensure "$T_D4" \
      --type story --parent "$EPIC_D" --priority 1 \
      --description "post_staging_transforms on the Gemini adapter strips Claude-specific YAML keys (skills, color, memory) and converts the comma-separated tools string to a YAML list. Uses pyyaml; lives in tools/gemini.py." \
      --acceptance "- Claude-style frontmatter keys (skills, color, memory) are stripped from agent files in the Gemini plan.
- tools: string is converted to YAML sequence.
- Files without YAML frontmatter pass through unchanged.
- Unit + integration tests cover both real-source and edge-case agents." > /dev/null
    echo "    D.4=$(lookup_id "$T_D4")"
fi

# ---- Epic E ----
if epic_enabled E && [[ -n "$EPIC_E" ]]; then
    echo "==> Creating Stories (Epic E)"

    bd_ensure "$T_E1" \
      --type story --parent "$EPIC_E" --priority 1 \
      --description "MergeStrategy protocol (merge(existing, incoming) -> StagedItem). Registry mapping FileKind to strategy instance. Replaces install.sh's case-statement dispatch." \
      --acceptance "- MergeStrategy protocol defined.
- Registry dispatches by FileKind.
- Unknown FileKind raises with a clear message." > /dev/null
    echo "    E.1=$(lookup_id "$T_E1")"

    bd_ensure "$T_E2" \
      --type story --parent "$EPIC_E" --priority 1 \
      --description "Append-merge strategy for FileKind.RULES_MD. Concatenates incoming after existing with the standard separator." \
      --acceptance "- Two rules with the same name merge by append with the separator between.
- Order is existing-then-incoming.
- Separator is exact; no leading or trailing blank-line artefacts." > /dev/null
    echo "    E.2=$(lookup_id "$T_E2")"

    bd_ensure "$T_E3" \
      --type story --parent "$EPIC_E" --priority 1 \
      --description "Fatal-collision strategy for FileKind.COMMANDS_MD / SKILLS_MD / AGENTS_MD / DIR. Raises CollisionError naming both source paths." \
      --acceptance "- Collision raises CollisionError.
- Error message names both source paths.
- Caller surfaces the error to the user with non-zero exit." > /dev/null
    echo "    E.3=$(lookup_id "$T_E3")"

    bd_ensure "$T_E4" \
      --type story --parent "$EPIC_E" --priority 1 \
      --description "Deep union-merge for FileKind.SETTINGS_JSON. Dict+dict recurses; arrays union+sort+dedupe; scalar conflicts keep existing; type mismatch keeps existing. Matches the jq program at install.sh lines 431-454." \
      --acceptance "- Nested object precedence: existing wins on scalar conflict.
- Arrays in conflicting keys are unioned, deduped, and sorted.
- Keys present only in incoming are added.
- Type mismatch (dict vs scalar) keeps existing." > /dev/null
    echo "    E.4=$(lookup_id "$T_E4")"

    bd_ensure "$T_E5" \
      --type story --parent "$EPIC_E" --priority 1 \
      --description "FileKind.JSONC and TOML: last-wins with warning. FileKind.OTHER: last-wins silently." \
      --acceptance "- last_wins_warn emits a warning identifying both source paths.
- last_wins_silent emits no warning.
- Both return the incoming content." > /dev/null
    echo "    E.5=$(lookup_id "$T_E5")"
fi

# ---- Epic F ----
if epic_enabled F && [[ -n "$EPIC_F" ]]; then
    echo "==> Creating Stories (Epic F)"

    bd_ensure "$T_F1" \
      --type story --parent "$EPIC_F" --priority 1 \
      --description "PluginAdapter protocol; plugins/registry.py; tests/fixtures/sources/test-plugin/ for exercise. Auto-detect honours beads / test-plugin probes per the registry." \
      --acceptance "- PluginAdapter protocol defined.
- Registry enumerates plugins; --plugins= override works.
- tests/fixtures/sources/test-plugin/ exists and is the canonical exercise plugin." > /dev/null
    echo "    F.1=$(lookup_id "$T_F1")"

    bd_ensure "$T_F2" \
      --type story --parent "$EPIC_F" --priority 1 \
      --description "After base + tool-specific staging, overlay each active plugin's .agents/ + .<tool>/ content in alphabetical plugin order. Exercises the full merge matrix (append, fatal, json_union, last_wins)." \
      --acceptance "- Plugin rules append to base rules with the standard separator.
- Plugin command with the same name as a base command raises fatal collision.
- Plugin settings.json fragment deep-union-merges into the base settings.
- Plugins applied alphabetically." > /dev/null
    echo "    F.2=$(lookup_id "$T_F2")"

    bd_ensure "$T_F3" \
      --type story --parent "$EPIC_F" --priority 1 \
      --description "Replace install.sh .carrier-from-user-shared sentinel file with in-memory metadata on StagedItem. Skill/agent dirs sourced from src/user/.agents/ are marked shared-carrier; a plugin can overlay if file sets are disjoint, otherwise fatal." \
      --acceptance "- Shared-carrier dir + plugin overlay with disjoint files: merges file lists, no error.
- Shared-carrier dir + plugin overlay with overlapping files: fatal collision.
- Non-carrier dir + plugin overlay: fatal collision regardless of file sets.
- No on-disk sentinel created." > /dev/null
    echo "    F.3=$(lookup_id "$T_F3")"

    bd_ensure "$T_F4" \
      --type story --parent "$EPIC_F" --priority 1 \
      --description "BeadsPlugin: source = src/plugins/beads/; destinations = ~/.beads/formulas/ and ~/.beads/scripts/ with executable bit set on scripts." \
      --acceptance "- Beads plugin detection probes bd-on-PATH OR ~/.beads/ existence.
- Formulas land at ~/.beads/formulas/.
- Scripts land at ~/.beads/scripts/ with mode 0755." > /dev/null
    echo "    F.4=$(lookup_id "$T_F4")"
fi

# ---- Epic G ----
if epic_enabled G && [[ -n "$EPIC_G" ]]; then
    echo "==> Creating Stories (Epic G)"

    bd_ensure "$T_G1" \
      --type story --parent "$EPIC_G" --priority 1 \
      --description "Items in scoped namespaces (commands, skills, agents, rules, formulas) back up to sibling namespace-backup/ directories with timestamp. Other items get in-place .backup-<ts> suffix." \
      --acceptance "- Files inside commands/skills/agents/rules/formulas backed up to sibling -backup/ dir with timestamp.
- Other files get in-place .backup-<ts> suffix.
- Backup created BEFORE write, recoverable on failure.
- Timestamp matches install.sh format YYYYMMDD-HHMMSS." > /dev/null
    echo "    G.1=$(lookup_id "$T_G1")"

    bd_ensure "$T_G2" \
      --type story --parent "$EPIC_G" --priority 1 \
      --description "Define and parse packages/installer/installer.toml. [prune].retired is a list of glob patterns. Optional [tools] overrides for dest dir. Loaded via stdlib tomllib." \
      --acceptance "- installer.toml in repo with [prune] section is parsed correctly.
- Missing installer.toml: prune list is empty, no error.
- Glob patterns retained as strings; matching happens later in G.3." > /dev/null
    echo "    G.2=$(lookup_id "$T_G2")"

    bd_ensure "$T_G3" \
      --type story --parent "$EPIC_G" --priority 1 \
      --description "Walk scoped namespaces under each dest dir; identify entries not in the StagingPlan AND matching a prune-list glob. Skip legacy *.backup-* files. Same orphan semantics as install.sh lines 1505-1543 but driven by in-memory plan." \
      --acceptance "- Orphans correctly identified given a staging plan and a prune list.
- Legacy *.backup-* files ignored.
- Globs match per fnmatch (tool/namespace/basename keying)." > /dev/null
    echo "    G.3=$(lookup_id "$T_G3")"

    bd_ensure "$T_G4" \
      --type story --parent "$EPIC_G" --priority 1 \
      --description "Three-way prompt (all / one-by-one / cancel). One-by-one drill-down with per-item yes/no/quit. Non-interactive guard. Mirrors install.sh lines 1602-1687 user transcript." \
      --acceptance "- Three-way prompt branches correctly under ScriptedIO.
- Per-item flow processes yes/no/quit correctly including quit-mid-loop.
- Non-interactive + --prune-only without --yes hard-fails.
- --yes deletes all without prompting." > /dev/null
    echo "    G.4=$(lookup_id "$T_G4")"

    bd_ensure "$T_G5" \
      --type story --parent "$EPIC_G" --priority 1 \
      --description "Wire prune flow into the orchestrator. --prune runs the install then prune; --prune-only skips install and only scans+prunes. Mutually exclusive." \
      --acceptance "- --prune executes install then prune.
- --prune-only skips install; only prunes.
- --prune + --prune-only together: argparse mutually-exclusive error.
- Empty staging plan under --prune-only with strict-mode excluded plugins flags all their files as orphans." > /dev/null
    echo "    G.5=$(lookup_id "$T_G5")"

    bd_ensure "$T_G6" \
      --type story --parent "$EPIC_G" --priority 1 \
      --description "Materialise the in-memory StagingPlan to <path> as a real directory tree, print the path, exit 0. No destination writes. Mutually exclusive with --prune / --prune-only." \
      --acceptance "- Dump produces a tree at <path>/<tool>/... matching the in-memory plan.
- No writes to home destinations occur.
- Mutual exclusion with --prune flags enforced.
- Exit code 0 on success; prints the dump path to stdout." > /dev/null
    echo "    G.6=$(lookup_id "$T_G6")"
fi

# ---- Epic H ----
if epic_enabled H && [[ -n "$EPIC_H" ]]; then
    echo "==> Creating Stories (Epic H)"

    bd_ensure "$T_H1" \
      --type story --parent "$EPIC_H" --priority 1 \
      --description "Build tests/golden_master/_runner.py that runs install.sh into HOME_A and install.py into HOME_B and recursively diffs with timestamp normalisation. First scenarios: bare install on clean home; install with pre-existing settings.json; install with user-modified skill (backup path)." \
      --acceptance "- Harness runs both installers and emits a normalised diff.
- Bare install scenario passes (zero post-normalisation diff).
- Settings-merge scenario passes.
- User-modified-skill scenario passes including backup placement check." > /dev/null
    echo "    H.1=$(lookup_id "$T_H1")"

    bd_ensure "$T_H2" \
      --type story --parent "$EPIC_H" --priority 1 \
      --description "Author the rest of the parity scenarios: --prune --yes with orphans; --prune-only; plugin overlay with test-plugin; --tools=codex --plugins= (single-tool); Gemini frontmatter transform end-to-end." \
      --acceptance "- All five additional scenarios produce zero post-normalisation diff.
- Suite completes in under 30 seconds.
- CI runs golden-master on every push." > /dev/null
    echo "    H.2=$(lookup_id "$T_H2")"

    bd_ensure "$T_H3" \
      --type story --parent "$EPIC_H" --priority 1 \
      --description "Watch CI for 14 consecutive days of green golden-master. Run install.py against the actual repo home with --dry-run --verbose and confirm zero unexpected diffs against install.sh --dry-run --verbose." \
      --acceptance "- 14 consecutive days of green golden-master CI runs.
- Real-home smoke test produces zero unexpected diffs.
- Sign-off recorded in this bead notes field." > /dev/null
    echo "    H.3=$(lookup_id "$T_H3")"

    bd_ensure "$T_H4" \
      --type story --parent "$EPIC_H" --priority 1 \
      --description "Replace install.sh body with: exec uv run --project packages/installer python -m installer with passed args. Delete or symlink scripts/prune-list (its contents already live in packages/installer/installer.toml from G.2)." \
      --acceptance "- install.sh is now <= 10 lines of wrapper.
- scripts/prune-list either deleted or replaced with a deprecation pointer.
- bash scripts/install.sh and python3 scripts/install.py produce identical install state in a fresh smoke test." > /dev/null
    echo "    H.4=$(lookup_id "$T_H4")"

    bd_ensure "$T_H5" \
      --type story --parent "$EPIC_H" --priority 1 \
      --description "Update AGENTS.md to reflect the new install command and the golden-master retirement. Update README. Move tests/golden_master/ to tests/golden_master/_retired/ (or delete) once H.4 lands." \
      --acceptance "- AGENTS.md install instructions reference uv-managed Python installer.
- AGENTS.md golden-master note updated from transitional to retired.
- README installation section updated.
- Golden-master tests no longer run in CI by default." > /dev/null
    echo "    H.5=$(lookup_id "$T_H5")"
fi

############################################################
# Phase 5: dependency edges (always attempted; skipped silently
# when an endpoint is missing from the cache)
############################################################
echo "==> Adding dependency edges (skipped silently when endpoints absent)"

# Epic A — 2 edges
edge_by_title "$T_A2" "$T_A1"
edge_by_title "$T_A3" "$T_A1"

# Epic B — 5 edges
edge_by_title "$T_B1" "$T_A2"
edge_by_title "$T_B1" "$T_A3"
edge_by_title "$T_B2" "$T_B1"
edge_by_title "$T_B3" "$T_B2"
edge_by_title "$T_B4" "$T_B3"

# Epic C — 4 edges
edge_by_title "$T_C1" "$T_B4"
edge_by_title "$T_C2" "$T_C1"
edge_by_title "$T_C2" "$T_B4"
edge_by_title "$T_C3" "$T_C2"

# Epic D — 7 edges
edge_by_title "$T_D1" "$T_C3"
edge_by_title "$T_D1" "$T_B1"
edge_by_title "$T_D2" "$T_C3"
edge_by_title "$T_D2" "$T_B1"
edge_by_title "$T_D3" "$T_C3"
edge_by_title "$T_D3" "$T_B1"
edge_by_title "$T_D4" "$T_D2"

# Epic E — 5 edges
edge_by_title "$T_E1" "$T_A2"
edge_by_title "$T_E2" "$T_E1"
edge_by_title "$T_E3" "$T_E1"
edge_by_title "$T_E4" "$T_E1"
edge_by_title "$T_E5" "$T_E1"

# Epic F — 9 edges
edge_by_title "$T_F1" "$T_B1"
edge_by_title "$T_F1" "$T_A2"
edge_by_title "$T_F2" "$T_F1"
edge_by_title "$T_F2" "$T_E2"
edge_by_title "$T_F2" "$T_E3"
edge_by_title "$T_F2" "$T_E4"
edge_by_title "$T_F2" "$T_E5"
edge_by_title "$T_F3" "$T_F2"
edge_by_title "$T_F4" "$T_F1"

# Epic G — 10 edges
edge_by_title "$T_G1" "$T_B2"
edge_by_title "$T_G2" "$T_A1"
edge_by_title "$T_G3" "$T_G2"
edge_by_title "$T_G3" "$T_C1"
edge_by_title "$T_G3" "$T_F2"
edge_by_title "$T_G4" "$T_G3"
edge_by_title "$T_G4" "$T_A3"
edge_by_title "$T_G5" "$T_G4"
edge_by_title "$T_G6" "$T_C3"
edge_by_title "$T_G6" "$T_B1"

# Epic H — 10 edges
edge_by_title "$T_H1" "$T_E4"
edge_by_title "$T_H1" "$T_G1"
edge_by_title "$T_H1" "$T_C3"
edge_by_title "$T_H2" "$T_G5"
edge_by_title "$T_H2" "$T_F2"
edge_by_title "$T_H2" "$T_D4"
edge_by_title "$T_H3" "$T_H1"
edge_by_title "$T_H3" "$T_H2"
edge_by_title "$T_H4" "$T_H3"
edge_by_title "$T_H5" "$T_H4"

############################################################
# Summary
############################################################
echo ""
echo "==> Summary"
echo "  Feature: $FEATURE"
echo "  Target epics this run: ${TARGET_EPICS[*]}"
echo "  Pre-existing beads at start: (printed above as 'Cached ... beads')"
echo "  Total beads in cache after run: ${#BEAD_IDS[@]}"
echo ""
echo "Per-story tasks (test-plan-review / red-phase / green-phase / verify-gate)"
echo "are filed JIT when each story moves to in_progress. They are NOT created here."
echo ""
echo "Next steps:"
echo "  bd ready                 # see what's available to start"
echo "  bd show <story-id>       # inspect a story"
echo "  bd dolt push && git push # persist"
