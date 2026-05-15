#!/usr/bin/env bash
# Red-phase tests for DYNAMIC-INCLUDE-RULES refactor (bead agents-config-abn9.23.1).
#
# Scope: structural/content assertions verifying the shared-rules move from
# src/user/.claude/rules/ into src/user/.agents/rules/, the rename of
# git-commits.md -> claude-sandbox.md and codex-routing.md ->
# claude-to-codex-routing.md, the introduction of DYNAMIC-INCLUDE-ALL-RULES
# in non-Claude templates, install.sh staging changes, and downstream
# documentation/regex updates.
#
# These tests are expected to FAIL against the unimplemented state (current
# main / feature-branch starting point) and PASS once the refactor is done.

set -u

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
while [ "$REPO_ROOT" != "/" ] && [ ! -d "$REPO_ROOT/src/user" ]; do
    REPO_ROOT="$(dirname "$REPO_ROOT")"
done
[ -d "$REPO_ROOT/src/user" ] \
    || fail "could not locate repo root containing src/user (started at $SCRIPT_DIR)"

SHARED_RULES_DIR="$REPO_ROOT/src/user/.agents/rules"
CLAUDE_RULES_DIR="$REPO_ROOT/src/user/.claude/rules"
INSTALL_SH="$REPO_ROOT/scripts/install.sh"
PRUNE_LIST="$REPO_ROOT/scripts/prune-list"
VERIFY_ARTIFACTS="$REPO_ROOT/scripts/smoke/verify-artifacts.sh"
CLAUDE_AGENTS_TPL="$REPO_ROOT/src/user/.claude/AGENTS.md.template"
CODEX_AGENTS_TPL="$REPO_ROOT/src/user/.codex/AGENTS.md.template"
GEMINI_TPL="$REPO_ROOT/src/user/.gemini/GEMINI.md.template"
OPENCODE_AGENTS_TPL="$REPO_ROOT/src/user/.opencode/AGENTS.md.template"
OPENCODE_EXT_TPL="$REPO_ROOT/src/user/.opencode/OPENCODE-EXTENSIONS.md.template"
CLAUDE_README="$REPO_ROOT/src/user/.claude/README.md"
CLAUDE_AGENTS_MD="$REPO_ROOT/src/user/.claude/AGENTS.md"
SHARED_AGENTS_MD="$REPO_ROOT/src/user/.agents/AGENTS.md"
WAIT_FOR_PR="$REPO_ROOT/src/user/.agents/skills/wait-for-pr-comments/SKILL.md"

# -----------------------------------------------------------------------------
# AC1 — Shared rules dir exists and contains the five tool-agnostic rules.
# -----------------------------------------------------------------------------
[ -d "$SHARED_RULES_DIR" ] || fail "AC1: $SHARED_RULES_DIR does not exist"
for rule in delegation.md delivery.md completion-gate.md subagents.md worktrees.md; do
    [ -f "$SHARED_RULES_DIR/$rule" ] \
        || fail "AC1: $SHARED_RULES_DIR/$rule does not exist (rule must move into shared dir)"
done
pass "AC1: shared rules dir contains all five tool-agnostic rules"

# -----------------------------------------------------------------------------
# AC2 — Claude rules dir contains only Claude-specific rules; the five
# tool-agnostic ones are absent from src/user/.claude/rules/.
# -----------------------------------------------------------------------------
for moved in delegation.md delivery.md completion-gate.md subagents.md worktrees.md; do
    [ ! -f "$CLAUDE_RULES_DIR/$moved" ] \
        || fail "AC2: $CLAUDE_RULES_DIR/$moved still present; tool-agnostic rules must move out of .claude/rules/"
done
pass "AC2: tool-agnostic rules absent from src/user/.claude/rules/"

# -----------------------------------------------------------------------------
# AC3 — git-commits.md and codex-routing.md must not exist anywhere under src/.
# (Renamed to claude-sandbox.md / claude-to-codex-routing.md.)
# -----------------------------------------------------------------------------
old_git=$(find "$REPO_ROOT/src" -type f -name 'git-commits.md' 2>/dev/null)
[ -z "$old_git" ] \
    || fail "AC3: stale git-commits.md still present: $old_git"
old_codex=$(find "$REPO_ROOT/src" -type f -name 'codex-routing.md' 2>/dev/null)
[ -z "$old_codex" ] \
    || fail "AC3: stale codex-routing.md still present: $old_codex"
pass "AC3: no git-commits.md or codex-routing.md anywhere under src/"

# -----------------------------------------------------------------------------
# AC4 — Renamed files exist with content semantically identical to the
# originals. We assert presence of canonical headings/anchors from each.
# -----------------------------------------------------------------------------
CLAUDE_SANDBOX="$CLAUDE_RULES_DIR/claude-sandbox.md"
CLAUDE_TO_CODEX="$CLAUDE_RULES_DIR/claude-to-codex-routing.md"
[ -f "$CLAUDE_SANDBOX" ] || fail "AC4: $CLAUDE_SANDBOX does not exist (renamed git-commits.md)"
[ -f "$CLAUDE_TO_CODEX" ] || fail "AC4: $CLAUDE_TO_CODEX does not exist (renamed codex-routing.md)"

# Canonical content markers for the old git-commits.md (preserved in
# claude-sandbox.md). Assert MULTIPLE markers so a partial / truncated rename
# can't pass.
for marker in 'Sandbox mode: heredocs fail' 'dangerouslyDisableSandbox' 'NEVER use heredoc syntax'; do
    grep -q "$marker" "$CLAUDE_SANDBOX" \
        || fail "AC4: $CLAUDE_SANDBOX missing canonical git-commits.md marker ('$marker')"
done
# Canonical content markers for old codex-routing.md (preserved in
# claude-to-codex-routing.md).
for marker in 'codex-companion.mjs' 'CLAUDE_PLUGIN_ROOT' 'gpt-5.5' 'Slash commands'; do
    grep -q "$marker" "$CLAUDE_TO_CODEX" \
        || fail "AC4: $CLAUDE_TO_CODEX missing canonical codex-routing.md marker ('$marker')"
done
# Sanity: each renamed file is non-trivially sized (>= 5 non-empty lines).
sandbox_lines="$(grep -cve '^$' "$CLAUDE_SANDBOX")"
[ "$sandbox_lines" -ge 5 ] \
    || fail "AC4: $CLAUDE_SANDBOX has only $sandbox_lines non-empty lines (expected >= 5); content looks truncated"
codex_lines="$(grep -cve '^$' "$CLAUDE_TO_CODEX")"
[ "$codex_lines" -ge 5 ] \
    || fail "AC4: $CLAUDE_TO_CODEX has only $codex_lines non-empty lines (expected >= 5); content looks truncated"
pass "AC4: claude-sandbox.md and claude-to-codex-routing.md exist with preserved content"

# -----------------------------------------------------------------------------
# AC5 — Claude AGENTS.md.template no longer carries any DYNAMIC-INCLUDE-RULES
# marker (rules now flow in via shared-rules staging, not a marker).
# -----------------------------------------------------------------------------
[ -f "$CLAUDE_AGENTS_TPL" ] || fail "AC5: $CLAUDE_AGENTS_TPL missing"
if grep -q 'DYNAMIC-INCLUDE-RULES' "$CLAUDE_AGENTS_TPL"; then
    fail "AC5: Claude AGENTS.md.template still has DYNAMIC-INCLUDE-RULES marker"
fi
pass "AC5: Claude AGENTS.md.template has no DYNAMIC-INCLUDE-RULES marker"

# -----------------------------------------------------------------------------
# AC6 — Codex AGENTS.md.template contains DYNAMIC-INCLUDE-ALL-RULES.
# -----------------------------------------------------------------------------
[ -f "$CODEX_AGENTS_TPL" ] || fail "AC6: $CODEX_AGENTS_TPL missing"
grep -q 'DYNAMIC-INCLUDE-ALL-RULES' "$CODEX_AGENTS_TPL" \
    || fail "AC6: Codex AGENTS.md.template missing DYNAMIC-INCLUDE-ALL-RULES marker"
if grep -q '<!-- DYNAMIC-INCLUDE-RULES:' "$CODEX_AGENTS_TPL"; then
    fail "AC6: Codex AGENTS.md.template still has hardcoded DYNAMIC-INCLUDE-RULES list"
fi
pass "AC6: Codex AGENTS.md.template contains DYNAMIC-INCLUDE-ALL-RULES (no hardcoded list)"

# -----------------------------------------------------------------------------
# AC7 — Gemini GEMINI.md.template contains DYNAMIC-INCLUDE-ALL-RULES.
# -----------------------------------------------------------------------------
[ -f "$GEMINI_TPL" ] || fail "AC7: $GEMINI_TPL missing"
grep -q 'DYNAMIC-INCLUDE-ALL-RULES' "$GEMINI_TPL" \
    || fail "AC7: Gemini GEMINI.md.template missing DYNAMIC-INCLUDE-ALL-RULES marker"
if grep -q '<!-- DYNAMIC-INCLUDE-RULES:' "$GEMINI_TPL"; then
    fail "AC7: Gemini GEMINI.md.template still has hardcoded DYNAMIC-INCLUDE-RULES list"
fi
pass "AC7: Gemini GEMINI.md.template contains DYNAMIC-INCLUDE-ALL-RULES (no hardcoded list)"

# -----------------------------------------------------------------------------
# AC8 — OpenCode AGENTS.md.template contains DYNAMIC-INCLUDE-ALL-RULES (and
# does NOT contain the old DYNAMIC-INCLUDE-RULES: <list> hardcoded form).
# -----------------------------------------------------------------------------
[ -f "$OPENCODE_AGENTS_TPL" ] || fail "AC8: $OPENCODE_AGENTS_TPL missing"
grep -q 'DYNAMIC-INCLUDE-ALL-RULES' "$OPENCODE_AGENTS_TPL" \
    || fail "AC8: OpenCode AGENTS.md.template missing DYNAMIC-INCLUDE-ALL-RULES marker"
if grep -q '<!-- DYNAMIC-INCLUDE-RULES:' "$OPENCODE_AGENTS_TPL"; then
    fail "AC8: OpenCode AGENTS.md.template still has hardcoded DYNAMIC-INCLUDE-RULES list"
fi
pass "AC8: OpenCode AGENTS.md.template uses DYNAMIC-INCLUDE-ALL-RULES (no hardcoded list)"

# -----------------------------------------------------------------------------
# AC9 — install.sh Phase 2 stages shared rules to staging/<tool>/rules/.
# Detect: an additional stage_content_from_dir call against $SRC_SHARED for
# the "rules" subdir must appear (alongside the existing skills/agents calls).
# -----------------------------------------------------------------------------
[ -f "$INSTALL_SH" ] || fail "AC9: $INSTALL_SH missing"
grep -q 'stage_content_from_dir "$SRC_SHARED" "$staging" "rules"' "$INSTALL_SH" \
    || fail "AC9: install.sh missing shared-rules staging line: stage_content_from_dir \"\$SRC_SHARED\" \"\$staging\" \"rules\""
pass "AC9: install.sh Phase 2 stages shared rules for all tools"

# -----------------------------------------------------------------------------
# AC10 — flatten_agents_md collects rules via `find` (not glob/ls) and emits
# a `warn` when the rules dir is empty or missing. We probe by inspecting
# the function body for both signals.
# -----------------------------------------------------------------------------
# Extract lines from flatten_agents_md function body.
flatten_body="$(awk '/^flatten_agents_md\(\)/{flag=1} flag{print} flag && /^}/{flag=0; exit}' "$INSTALL_SH")"
[ -n "$flatten_body" ] || fail "AC10: could not locate flatten_agents_md() in install.sh"

# Must reference DYNAMIC-INCLUDE-ALL-RULES handling and use `find`.
printf '%s' "$flatten_body" | grep -q 'DYNAMIC-INCLUDE-ALL-RULES' \
    || fail "AC10: flatten_agents_md does not handle DYNAMIC-INCLUDE-ALL-RULES marker"
printf '%s' "$flatten_body" | grep -qE '\bfind\b' \
    || fail "AC10: flatten_agents_md does not use 'find' to collect rules (expected find-based discovery)"
printf '%s' "$flatten_body" | grep -q 'warn' \
    || fail "AC10: flatten_agents_md does not call 'warn' when rules dir is empty/missing"
pass "AC10: flatten_agents_md uses find + warns on empty/missing rules dir"

# -----------------------------------------------------------------------------
# AC11 — Phase 6 plugin_agents_dir loop covers rules alongside skills/agents.
# Today the loop only iterates `skills agents` over $plugin_agents_dir; the
# refactor must extend it to include `rules`.
# -----------------------------------------------------------------------------
# Look specifically at the second plugin loop (over plugin_agents_dir) — the
# tell is the immediately-preceding `if [[ -d "$plugin_agents_dir" ]]; then`.
plugin_agents_block="$(awk '
    /if \[\[ -d "\$plugin_agents_dir" \]\]; then/{flag=1}
    flag{print}
    flag && /^[[:space:]]*fi[[:space:]]*$/{count++; if (count==2) {flag=0; exit}}
' "$INSTALL_SH")"
[ -n "$plugin_agents_block" ] || fail "AC11: could not locate plugin_agents_dir block in install.sh"
# The for-loop's subdir list must now include `rules`.
printf '%s' "$plugin_agents_block" | grep -qE 'for subdir in [^;]*\brules\b' \
    || fail "AC11: plugin_agents_dir for-loop does not include 'rules' subdir"
pass "AC11: Phase 6 plugin_agents_dir loop iterates over rules + skills + agents"

# -----------------------------------------------------------------------------
# AC12 — delegation.md line 11 references claude-to-codex-routing.md
# (not codex-routing.md).
# -----------------------------------------------------------------------------
# delegation.md must now live under the shared rules dir (per AC1).
DELEGATION_MD="$SHARED_RULES_DIR/delegation.md"
[ -f "$DELEGATION_MD" ] || fail "AC12: $DELEGATION_MD does not exist (delegation.md must be in shared rules)"
# Line 11 specifically — exact match per spec.
line11="$(sed -n '11p' "$DELEGATION_MD")"
case "$line11" in
    *claude-to-codex-routing.md*) : ;;
    *) fail "AC12: delegation.md:11 does not reference claude-to-codex-routing.md. Got: $line11" ;;
esac
case "$line11" in
    *' codex-routing.md'*|*'`codex-routing.md`'*)
        fail "AC12: delegation.md:11 still references old codex-routing.md filename" ;;
esac
pass "AC12: delegation.md:11 references claude-to-codex-routing.md"

# -----------------------------------------------------------------------------
# AC13 — wait-for-pr-comments SKILL.md:657 references claude-sandbox.md
# (not git-commits.md).
# -----------------------------------------------------------------------------
[ -f "$WAIT_FOR_PR" ] || fail "AC13: $WAIT_FOR_PR missing"
line657="$(sed -n '657p' "$WAIT_FOR_PR")"
case "$line657" in
    *claude-sandbox.md*) : ;;
    *) fail "AC13: wait-for-pr-comments SKILL.md:657 does not reference claude-sandbox.md. Got: $line657" ;;
esac
case "$line657" in
    *git-commits.md*)
        fail "AC13: wait-for-pr-comments SKILL.md:657 still references old git-commits.md" ;;
esac
pass "AC13: wait-for-pr-comments SKILL.md:657 references claude-sandbox.md"

# -----------------------------------------------------------------------------
# AC14 — Claude README.md and Claude AGENTS.md no longer reference the old
# filenames git-commits.md or codex-routing.md.
# -----------------------------------------------------------------------------
[ -f "$CLAUDE_README" ] || fail "AC14: $CLAUDE_README missing"
[ -f "$CLAUDE_AGENTS_MD" ] || fail "AC14: $CLAUDE_AGENTS_MD missing"
for path in "$CLAUDE_README" "$CLAUDE_AGENTS_MD"; do
    if grep -q 'git-commits.md' "$path"; then
        fail "AC14: $path still references git-commits.md"
    fi
    if grep -q 'codex-routing.md' "$path"; then
        fail "AC14: $path still references codex-routing.md"
    fi
done
pass "AC14: Claude README.md and AGENTS.md contain no references to old rule filenames"

# -----------------------------------------------------------------------------
# AC15 — OpenCode OPENCODE-EXTENSIONS.md.template reflects new filenames /
# inclusion set, and contains no reference to the old names.
# -----------------------------------------------------------------------------
[ -f "$OPENCODE_EXT_TPL" ] || fail "AC15: $OPENCODE_EXT_TPL missing"
if grep -q 'git-commits.md' "$OPENCODE_EXT_TPL"; then
    fail "AC15: OPENCODE-EXTENSIONS.md.template still references git-commits.md"
fi
if grep -q 'codex-routing.md' "$OPENCODE_EXT_TPL"; then
    fail "AC15: OPENCODE-EXTENSIONS.md.template still references codex-routing.md"
fi
# Must reference at least one new filename or the new inclusion model
# (DYNAMIC-INCLUDE-ALL-RULES) to prove the template was actually updated.
if ! grep -qE 'claude-sandbox.md|claude-to-codex-routing.md|DYNAMIC-INCLUDE-ALL-RULES' "$OPENCODE_EXT_TPL"; then
    fail "AC15: OPENCODE-EXTENSIONS.md.template does not reflect new rule filenames or inclusion model"
fi
pass "AC15: OPENCODE-EXTENSIONS.md.template reflects new filenames and inclusion set"

# -----------------------------------------------------------------------------
# AC16 — verify-artifacts.sh regex (around line 123) catches
# DYNAMIC-INCLUDE-ALL-RULES as an unprocessed marker.
# -----------------------------------------------------------------------------
[ -f "$VERIFY_ARTIFACTS" ] || fail "AC16: $VERIFY_ARTIFACTS missing"
# The current regex is '<!-- DYNAMIC-INCLUDE(-RULES)?:' — must be widened so
# '<!-- DYNAMIC-INCLUDE-ALL-RULES' (and the existing forms) all match.
# Behavioural check: synthesise a probe line and confirm the regex extracted
# from verify-artifacts.sh matches it.
probe='<!-- DYNAMIC-INCLUDE-ALL-RULES -->'
# Extract the relevant grep-pattern line.
regex_line="$(grep -E 'grep -qE .*DYNAMIC-INCLUDE' "$VERIFY_ARTIFACTS" | head -1)"
[ -n "$regex_line" ] || fail "AC16: could not locate DYNAMIC-INCLUDE regex line in verify-artifacts.sh"
# Pull out the single-quoted regex.
pattern="$(printf '%s' "$regex_line" | sed -n "s/.*grep -qE '\([^']*\)'.*/\1/p")"
[ -n "$pattern" ] || fail "AC16: could not extract regex from verify-artifacts.sh line: $regex_line"
if ! printf '%s\n' "$probe" | grep -qE "$pattern"; then
    fail "AC16: verify-artifacts.sh regex '$pattern' does not match DYNAMIC-INCLUDE-ALL-RULES probe"
fi
pass "AC16: verify-artifacts.sh regex catches DYNAMIC-INCLUDE-ALL-RULES"

# -----------------------------------------------------------------------------
# AC17 — prune-list contains entries for the retired Claude rule paths.
# -----------------------------------------------------------------------------
[ -f "$PRUNE_LIST" ] || fail "AC17: $PRUNE_LIST missing"
grep -Eq '^[[:space:]]*claude/rules/git-commits\.md[[:space:]]*$' "$PRUNE_LIST" \
    || fail "AC17: prune-list missing active entry for claude/rules/git-commits.md (must not be commented out)"
grep -Eq '^[[:space:]]*claude/rules/codex-routing\.md[[:space:]]*$' "$PRUNE_LIST" \
    || fail "AC17: prune-list missing active entry for claude/rules/codex-routing.md (must not be commented out)"
pass "AC17: prune-list contains retired claude/rules/ entries"

# -----------------------------------------------------------------------------
# AC18 — src/user/.agents/AGENTS.md has a rules/ bullet alongside agents/
# and skills/.
# -----------------------------------------------------------------------------
[ -f "$SHARED_AGENTS_MD" ] || fail "AC18: $SHARED_AGENTS_MD missing"
# Look for a bullet line of the form '- `rules/`' (matching the existing
# format of the agents/ and skills/ bullets).
grep -qE '^- `rules/`' "$SHARED_AGENTS_MD" \
    || fail "AC18: src/user/.agents/AGENTS.md missing 'rules/' bullet"
# Sanity-check that agents/ and skills/ bullets are still present.
grep -qE '^- `agents/`' "$SHARED_AGENTS_MD" \
    || fail "AC18: src/user/.agents/AGENTS.md missing 'agents/' bullet (precondition)"
grep -qE '^- `skills/`' "$SHARED_AGENTS_MD" \
    || fail "AC18: src/user/.agents/AGENTS.md missing 'skills/' bullet (precondition)"
pass "AC18: src/user/.agents/AGENTS.md lists rules/ alongside agents/ and skills/"

# -----------------------------------------------------------------------------
# AC19 — src/user/.claude/AGENTS.md no longer describes the 5 tool-agnostic
# rules as living under src/user/.claude/rules/. The block that today
# enumerates "delegation, completion gate, delivery, git, subagents, codex
# routing" as the contents of `rules/` must be revised.
# -----------------------------------------------------------------------------
[ -f "$CLAUDE_AGENTS_MD" ] || fail "AC19: $CLAUDE_AGENTS_MD missing"
# The current text reads: "rules/ is the append-only extension point for
# Claude-specific workflow (delegation, completion gate, delivery, git,
# subagents, codex routing)." After the refactor the parenthetical must NOT
# enumerate all five tool-agnostic rules (delegation, completion gate,
# delivery, subagents) as Claude-specific.
#
# We detect the offending state by looking for the line that lists
# 'delegation' AND 'completion gate' AND 'delivery' AND 'subagents' in
# combination in the rules/ description.
if grep -E 'delegation.*completion gate.*delivery.*subagents' "$CLAUDE_AGENTS_MD" >/dev/null; then
    fail "AC19: $CLAUDE_AGENTS_MD still describes tool-agnostic rules (delegation/completion-gate/delivery/subagents) as living in src/user/.claude/rules/"
fi
pass "AC19: src/user/.claude/AGENTS.md no longer claims tool-agnostic rules live in .claude/rules/"

echo ""
echo "ALL TESTS PASSED"
