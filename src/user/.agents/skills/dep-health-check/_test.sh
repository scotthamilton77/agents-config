#!/usr/bin/env bash
# Red-phase tests for bead agents-config-he9o:
#   "Implement dep-health-check skill"
#
# These tests fail until the dep-health-check skill exists in the beads
# plugin (SKILL.md + collect.py), the slash-command wrapper is in place,
# and scripts/install.sh stages the new skill.
#
# Discovery: this file sits under src/user/.agents/skills/dep-health-check/
# so the project test runner picks it up (find ... -name '*_test.sh'),
# but every assertion targets paths under src/plugins/beads/. The shared
# "dep-health-check" entry under .agents is the carrier directory for these
# contract tests; the actual SKILL.md + collect.py ship in the beads plugin.
#
# Pattern adapted from src/user/.agents/skills/resolve-human-bead/_test.sh.

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
# HERE = src/user/.agents/skills/dep-health-check; repo root is five levels up.
REPO_ROOT="$(cd "$HERE/../../../../.." && pwd)"

SKILL_DIR="$REPO_ROOT/src/plugins/beads/.agents/skills/dep-health-check"
SKILL_MD="$SKILL_DIR/SKILL.md"
COLLECT_PY="$SKILL_DIR/collect.py"
CMD_MD="$REPO_ROOT/src/plugins/beads/.claude/commands/dep-health-check.md"
INSTALL_SH="$REPO_ROOT/scripts/install.sh"

FAIL=0

# ----- helpers -------------------------------------------------------------

pass() { echo "  ok: $1"; }

fail() {
  echo "  FAIL: $1"
  if [ "${2:-}" != "" ]; then
    echo "        $2"
  fi
  FAIL=1
}

require_file() {
  if [ -f "$1" ]; then
    pass "$2 exists ($1)"
    return 0
  fi
  fail "$2 missing" "expected file: $1"
  return 1
}

# grep_in <file> <pattern> <label>  (ERE)
grep_in() {
  local file="$1" pat="$2" lab="$3"
  if [ ! -f "$file" ]; then
    fail "$lab" "file not found: $file"
    return 1
  fi
  if grep -Eq -- "$pat" "$file"; then
    pass "$lab"
    return 0
  fi
  fail "$lab" "pattern not found in $file: $pat"
  return 1
}

# grep_in_fixed <file> <fixed-string> <label>
grep_in_fixed() {
  local file="$1" pat="$2" lab="$3"
  if [ ! -f "$file" ]; then
    fail "$lab" "file not found: $file"
    return 1
  fi
  if grep -Fq -- "$pat" "$file"; then
    pass "$lab"
    return 0
  fi
  fail "$lab" "string not found in $file: $pat"
  return 1
}

# grep_not_in <file> <fixed-string> <label>
grep_not_in() {
  local file="$1" pat="$2" lab="$3"
  if [ ! -f "$file" ]; then
    fail "$lab" "file not found: $file"
    return 1
  fi
  if grep -Fq -- "$pat" "$file"; then
    fail "$lab" "forbidden string present in $file: $pat"
    return 1
  fi
  pass "$lab"
  return 0
}

# ===========================================================================
# AC2 — Install staging recognizes dep-health-check skill.
#       scripts/install.sh --dry-run exits 0 AND output mentions
#       "dep-health-check" under the skills sync section.
# ===========================================================================
echo "[ac2_install_dry_run_lists_skill]"

if [ ! -f "$INSTALL_SH" ]; then
  fail "AC2 install.sh present" "expected: $INSTALL_SH"
else
  pass "AC2 install.sh present"

  # Exercise the ACTUAL beads-plugin staging path with --plugins=beads
  # --verbose so we can see plugin-skill placement in the dry-run output.
  # The carrier dir under src/user/.agents/skills/dep-health-check/ and the
  # plugin skill dir under src/plugins/beads/.agents/skills/dep-health-check/
  # follow the same merge model as resolve-human-bead; install.sh handles
  # the collision. If --plugins=beads --verbose surfaces a fatal collision
  # error here, the test will fail loudly — that is the intended signal.
  DRY_OUT="$(cd "$REPO_ROOT" && bash "$INSTALL_SH" --dry-run --tools=claude --plugins=beads --verbose 2>&1)"
  DRY_RC=$?
  if [ "$DRY_RC" -eq 0 ]; then
    pass "AC2 install.sh --dry-run exit 0"
  else
    fail "AC2 install.sh --dry-run exit 0" "exit code: $DRY_RC; output tail: $(printf '%s\n' "$DRY_OUT" | tail -c 600)"
  fi

  # Must mention dep-health-check AND it must appear in a plugin-skill
  # staging line (i.e. paths under plugins/beads/...skills/dep-health-check).
  # Without this, an implementer could place SKILL.md in the carrier dir
  # alone and the test would pass — that's the bug Codex flagged.
  if printf '%s\n' "$DRY_OUT" | grep -Eq "(plugins/beads|beads-plugin|beads).*skills/dep-health-check"; then
    pass "AC2 dry-run output stages beads-plugin dep-health-check skill"
  else
    fail "AC2 dry-run output stages beads-plugin dep-health-check skill" \
      "expected a staging line mentioning the beads plugin and skills/dep-health-check; got tail: $(printf '%s\n' "$DRY_OUT" | tail -c 600)"
  fi
fi

# ===========================================================================
# AC3 — /dep-health-check slash command exists; body is exactly
#       'Skill dep-health-check $ARGUMENTS' and contains no other content.
# ===========================================================================
echo "[ac3_slash_command_body]"

require_file "$CMD_MD" "AC3 slash command file"
if [ -f "$CMD_MD" ]; then
  EXPECTED='Skill dep-health-check $ARGUMENTS'
  # Strip trailing whitespace/newlines for the equality check.
  ACTUAL="$(awk '{print}' "$CMD_MD" | sed -e 's/[[:space:]]*$//' )"
  # Body must be a single non-empty line equal to EXPECTED.
  LINE_COUNT="$(grep -c -v '^[[:space:]]*$' "$CMD_MD" 2>/dev/null || echo 0)"
  if [ "$LINE_COUNT" = "1" ] && [ "$ACTUAL" = "$EXPECTED" ]; then
    pass "AC3 slash command body is exactly '$EXPECTED'"
  else
    fail "AC3 slash command body is exactly '$EXPECTED'" \
      "got: $(cat "$CMD_MD" 2>/dev/null)"
  fi
fi

# ===========================================================================
# AC4 — collect.py --mode all produces valid JSON matching schema, exit 0.
# ===========================================================================
echo "[ac4_collect_mode_all_json]"

if [ ! -f "$COLLECT_PY" ]; then
  fail "AC4 collect.py present" "expected: $COLLECT_PY"
else
  pass "AC4 collect.py present"

  OUT_FILE="$(mktemp -t depcheck.XXXXXX)"
  ERR_FILE="$(mktemp -t depcheck-err.XXXXXX)"
  ( cd "$REPO_ROOT" && python3 "$COLLECT_PY" --mode all >"$OUT_FILE" 2>"$ERR_FILE" )
  RC=$?

  if [ "$RC" -eq 0 ]; then
    pass "AC4 collect.py --mode all exit 0"
  else
    fail "AC4 collect.py --mode all exit 0" \
      "exit=$RC stderr=$(head -c 400 "$ERR_FILE")"
  fi

  if python3 -c "import sys,json; json.load(open('$OUT_FILE'))" 2>/dev/null; then
    pass "AC4 stdout is valid JSON"
  else
    fail "AC4 stdout is valid JSON" "could not json.load stdout file"
  fi

  # Schema-shape probe (two-file output contract per SKILL.md): summary JSON
  # on stdout carries metadata + paths to the beads/findings files. The
  # `beads` array lives in the text beads_file; the `findings` array lives
  # inside the findings_file JSON.
  for key in project_prefix mode bead_count beads_file findings_file finding_counts; do
    if python3 -c "import json; d=json.load(open('$OUT_FILE')); assert '$key' in d" 2>/dev/null; then
      pass "AC4 summary has top-level key '$key'"
    else
      fail "AC4 summary has top-level key '$key'" "missing in JSON output"
    fi
  done

  # mode field should equal 'all' in this invocation.
  if python3 -c "import json; d=json.load(open('$OUT_FILE')); assert d.get('mode')=='all'" 2>/dev/null; then
    pass "AC4 summary mode == 'all'"
  else
    fail "AC4 summary mode == 'all'" "mode field absent or not 'all'"
  fi

  # bead_count is an int; finding_counts is an object.
  if python3 -c "import json; d=json.load(open('$OUT_FILE')); assert isinstance(d.get('bead_count'), int) and isinstance(d.get('finding_counts'), dict)" 2>/dev/null; then
    pass "AC4 bead_count is int and finding_counts is object"
  else
    fail "AC4 bead_count is int and finding_counts is object" "wrong types"
  fi

  # bead_count must be positive. This repo has 100+ open beads — an empty
  # graph from --mode all is a defect, not a boundary case.
  if python3 -c "import json; d=json.load(open('$OUT_FILE')); assert d['bead_count']>0" 2>/dev/null; then
    pass "AC4 bead_count > 0"
  else
    fail "AC4 bead_count > 0" "expected positive bead_count for --mode all against live repo"
  fi

  # beads_file: path exists, non-empty, '=== ' bead-header count obeys the
  # ordering invariant below. beads_file filters mol/wisp only;
  # open_bead_count filters mol/wisp + closed. Strict equality is fragile
  # under concurrent bd writes (a bead may be closed between the bulk bd
  # list and per-bead bd show, landing in detailed_by_id with status=closed
  # but still written to beads_file). Invariant: open_bead_count <= headers
  # <= bead_count AND headers > 0.
  BEADS_FILE_PATH="$(python3 -c "import json; print(json.load(open('$OUT_FILE')).get('beads_file',''))" 2>/dev/null || echo "")"
  if [ -n "$BEADS_FILE_PATH" ] && [ -f "$BEADS_FILE_PATH" ]; then
    pass "AC4 beads_file exists ($BEADS_FILE_PATH)"
    HEADER_COUNT="$(grep -c '^=== ' "$BEADS_FILE_PATH" 2>/dev/null)"
    if python3 -c "import json; d=json.load(open('$OUT_FILE')); assert d['open_bead_count']<=$HEADER_COUNT<= d['bead_count'] and $HEADER_COUNT>0" 2>/dev/null; then
      pass "AC4 beads_file header count in [open_bead_count, bead_count] and > 0"
    else
      fail "AC4 beads_file header count in [open_bead_count, bead_count] and > 0" \
        "headers=$HEADER_COUNT, open_bead_count=$(python3 -c "import json; print(json.load(open('$OUT_FILE')).get('open_bead_count'))"), bead_count=$(python3 -c "import json; print(json.load(open('$OUT_FILE')).get('bead_count'))")"
    fi
  else
    fail "AC4 beads_file exists" "summary path: '$BEADS_FILE_PATH'"
  fi

  # findings_file: path exists, valid JSON, has a 'findings' list.
  FINDINGS_FILE_PATH="$(python3 -c "import json; print(json.load(open('$OUT_FILE')).get('findings_file',''))" 2>/dev/null || echo "")"
  if [ -n "$FINDINGS_FILE_PATH" ] && [ -f "$FINDINGS_FILE_PATH" ]; then
    pass "AC4 findings_file exists ($FINDINGS_FILE_PATH)"
    if python3 -c "import json; f=json.load(open('$FINDINGS_FILE_PATH')); assert isinstance(f.get('findings'), list)" 2>/dev/null; then
      pass "AC4 findings_file has 'findings' list"
    else
      fail "AC4 findings_file has 'findings' list" "missing or wrong type"
    fi
  else
    fail "AC4 findings_file exists" "summary path: '$FINDINGS_FILE_PATH'"
  fi

  rm -f "$OUT_FILE" "$ERR_FILE" "$BEADS_FILE_PATH" "$FINDINGS_FILE_PATH"
fi

# ===========================================================================
# AC5 — collect.py --mode focused --target <id> emits focused neighborhood.
#       Verifies: valid JSON, exit 0, mode/target echoed, bead_count > 0,
#       target bead is present in beads[].
# ===========================================================================
echo "[ac5_collect_mode_focused_json]"

# Choose a target bead that exists in this project's bd DB. Per the dispatcher
# input, agents-config-3up3 is the sample focused target. Fall back to whatever
# `bd ready --json | jq -r '.[0].id'` returns if 3up3 is not present, so the
# test stays deterministic on this repo but remains portable on a fresh
# checkout. We DO NOT silently skip — if no target can be found, that is a
# failure.
TARGET=""
# bd resolves the bead store relative to CWD; run the probes inside REPO_ROOT
# so that the test works regardless of where the runner invoked it from.
if command -v bd >/dev/null 2>&1; then
  if ( cd "$REPO_ROOT" && bd show agents-config-3up3 >/dev/null 2>&1 ); then
    TARGET="agents-config-3up3"
  else
    TARGET="$( ( cd "$REPO_ROOT" && bd ready --json 2>/dev/null ) | python3 -c "import sys,json
try:
    d=json.load(sys.stdin)
    print(d[0]['id'] if d else '')
except Exception:
    print('')
" 2>/dev/null || true)"
  fi
fi

if [ ! -f "$COLLECT_PY" ]; then
  fail "AC5 collect.py present" "expected: $COLLECT_PY"
elif [ -z "$TARGET" ]; then
  fail "AC5 focused target available" \
    "could not resolve a target bead (tried agents-config-3up3 and bd ready)"
else
  pass "AC5 collect.py present (using target $TARGET)"

  OUT_FILE="$(mktemp -t depcheck-foc.XXXXXX)"
  ERR_FILE="$(mktemp -t depcheck-foc-err.XXXXXX)"
  ( cd "$REPO_ROOT" && python3 "$COLLECT_PY" --mode focused --target "$TARGET" \
      >"$OUT_FILE" 2>"$ERR_FILE" )
  RC=$?

  if [ "$RC" -eq 0 ]; then
    pass "AC5 collect.py --mode focused --target $TARGET exit 0"
  else
    fail "AC5 collect.py --mode focused --target $TARGET exit 0" \
      "exit=$RC stderr=$(head -c 400 "$ERR_FILE")"
  fi

  if python3 -c "import json; json.load(open('$OUT_FILE'))" 2>/dev/null; then
    pass "AC5 focused stdout is valid JSON"
  else
    fail "AC5 focused stdout is valid JSON" "could not json.load"
  fi

  # Target echoed back into output.
  if python3 -c "import json; d=json.load(open('$OUT_FILE')); assert d.get('mode')=='focused' and d.get('target')=='$TARGET'" 2>/dev/null; then
    pass "AC5 focused mode+target echoed"
  else
    fail "AC5 focused mode+target echoed" "mode/target mismatch"
  fi

  # Two-file output contract: target bead and bead_count live in the
  # beads_file (text), not in the summary JSON.
  BEADS_FILE_PATH="$(python3 -c "import json; print(json.load(open('$OUT_FILE')).get('beads_file',''))" 2>/dev/null || echo "")"
  if [ -n "$BEADS_FILE_PATH" ] && [ -f "$BEADS_FILE_PATH" ]; then
    pass "AC5 focused beads_file exists ($BEADS_FILE_PATH)"
    if grep -q "^=== $TARGET " "$BEADS_FILE_PATH"; then
      pass "AC5 target bead present in beads_file"
    else
      fail "AC5 target bead present in beads_file" "no '=== $TARGET ' header in $BEADS_FILE_PATH"
    fi

    HEADER_COUNT="$(grep -c '^=== ' "$BEADS_FILE_PATH" 2>/dev/null)"
    # beads_file excludes mol/wisp only (NOT closed beads, since focused mode
    # may pull closed neighbors via bd show). Header count must be positive
    # and bounded by bead_count; equality only holds when no mol/wisp are in
    # scope, so test the safer invariant 0 < headers <= bead_count.
    if python3 -c "import json; d=json.load(open('$OUT_FILE')); assert isinstance(d.get('bead_count'), int) and d['bead_count']>0 and $HEADER_COUNT>0 and $HEADER_COUNT<=d['bead_count']" 2>/dev/null; then
      pass "AC5 bead_count > 0 and 0 < beads_file headers <= bead_count"
    else
      fail "AC5 bead_count > 0 and 0 < beads_file headers <= bead_count" \
        "headers=$HEADER_COUNT, bead_count=$(python3 -c "import json; print(json.load(open('$OUT_FILE')).get('bead_count'))")"
    fi
  else
    fail "AC5 focused beads_file exists" "summary path: '$BEADS_FILE_PATH'"
  fi

  # findings_file: path exists, valid JSON, has a 'findings' list.
  FINDINGS_FILE_PATH="$(python3 -c "import json; print(json.load(open('$OUT_FILE')).get('findings_file',''))" 2>/dev/null || echo "")"
  if [ -n "$FINDINGS_FILE_PATH" ] && [ -f "$FINDINGS_FILE_PATH" ]; then
    pass "AC5 focused findings_file exists ($FINDINGS_FILE_PATH)"
    if python3 -c "import json; f=json.load(open('$FINDINGS_FILE_PATH')); assert isinstance(f.get('findings'), list)" 2>/dev/null; then
      pass "AC5 focused findings_file has 'findings' list"
    else
      fail "AC5 focused findings_file has 'findings' list" "missing or wrong type"
    fi
  else
    fail "AC5 focused findings_file exists" "summary path: '$FINDINGS_FILE_PATH'"
  fi

  rm -f "$OUT_FILE" "$ERR_FILE" "$BEADS_FILE_PATH" "$FINDINGS_FILE_PATH"
fi

# ===========================================================================
# AC6 — Exit codes:
#         2  unknown args   (collect.py --bogus-flag)
#         3  bd not on PATH (run with PATH that excludes bd)
#         4  db not found   (run from a non-bd directory)
# ===========================================================================
echo "[ac6_exit_codes]"

if [ ! -f "$COLLECT_PY" ]; then
  fail "AC6 collect.py present" "expected: $COLLECT_PY"
else
  pass "AC6 collect.py present"

  # 6a: unknown args -> 2
  ( cd "$REPO_ROOT" && python3 "$COLLECT_PY" --bogus-flag >/dev/null 2>&1 )
  RC=$?
  if [ "$RC" -eq 2 ]; then
    pass "AC6 unknown arg -> exit 2"
  else
    fail "AC6 unknown arg -> exit 2" "got exit $RC"
  fi

  # 6b: bd not on PATH -> 3
  # Construct a temp bin dir containing ONLY a python3 symlink. This
  # guarantees no bd leak regardless of where bd actually lives — sharing
  # /usr/bin or /opt/homebrew/bin with bd was the bug Codex flagged.
  TMP_BIN="$(mktemp -d -t depcheck-bin.XXXXXX)"
  ln -s "$(command -v python3)" "$TMP_BIN/python3"
  ( cd "$REPO_ROOT" && env -i PATH="$TMP_BIN" HOME="$HOME" \
      python3 "$COLLECT_PY" --mode all >/dev/null 2>&1 )
  RC=$?
  rm -rf "$TMP_BIN"
  if [ "$RC" -eq 3 ]; then
    pass "AC6 bd not on PATH -> exit 3"
  else
    fail "AC6 bd not on PATH -> exit 3" "got exit $RC"
  fi

  # 6c: db not found -> 4
  # Run from a temp dir that has no .beads/ and no bd db lineage. The
  # collect.py is expected to detect db-not-found and exit 4 (distinct from
  # 'bd missing' = 3).
  TMP_NO_DB="$(mktemp -d -t depcheck-nodb.XXXXXX)"
  ( cd "$TMP_NO_DB" && env BEADS_DB="$TMP_NO_DB/does-not-exist.db" \
      BD_HOME="$TMP_NO_DB" \
      python3 "$COLLECT_PY" --mode all >/dev/null 2>&1 )
  RC=$?
  if [ "$RC" -eq 4 ]; then
    pass "AC6 db not found -> exit 4"
  else
    fail "AC6 db not found -> exit 4" "got exit $RC (from $TMP_NO_DB)"
  fi
  rm -rf "$TMP_NO_DB"
fi

# ===========================================================================
# AC7 — --just-fix-it prohibitions: only HIGH-confidence bd dep add edges,
#       no bd dep remove, no bd close, no bd label remove, no bead content
#       mutation; cap at 10 edges per invocation. Structural test on SKILL.md.
# ===========================================================================
echo "[ac7_just_fix_it_prohibitions]"

require_file "$SKILL_MD" "AC7 SKILL.md"

grep_in_fixed "$SKILL_MD" "--just-fix-it" \
  "AC7 SKILL.md documents --just-fix-it"

# Whitelist: only bd dep add allowed.
grep_in "$SKILL_MD" "([Oo]nly|ONLY).*bd dep add" \
  "AC7 SKILL.md states only bd dep add is allowed in --just-fix-it"

# Forbid each destructive command — must appear as an explicit prohibition.
grep_in "$SKILL_MD" "(MUST NOT|never|NEVER|prohibited|forbidden).*bd dep remove" \
  "AC7 SKILL.md prohibits bd dep remove in --just-fix-it"
grep_in "$SKILL_MD" "(MUST NOT|never|NEVER|prohibited|forbidden).*bd close" \
  "AC7 SKILL.md prohibits bd close in --just-fix-it"
grep_in "$SKILL_MD" "(MUST NOT|never|NEVER|prohibited|forbidden).*bd label remove" \
  "AC7 SKILL.md prohibits bd label remove in --just-fix-it"

# No bead-content mutation calls (bd update --notes, --description, etc.).
grep_in "$SKILL_MD" "(no bead.?content|no content mutation|MUST NOT.*bd update|never.*bd update|do not.*mutate bead content)" \
  "AC7 SKILL.md prohibits bead content mutations in --just-fix-it"

# HIGH-confidence gating language.
grep_in "$SKILL_MD" "(HIGH.confidence|HIGH confidence|high.confidence threshold)" \
  "AC7 SKILL.md requires HIGH-confidence threshold for --just-fix-it edges"

# Cap of 10 edges per invocation.
grep_in "$SKILL_MD" "(at most 10|max.*10 edges|cap.*10|10 per invocation|limit of 10)" \
  "AC7 SKILL.md caps --just-fix-it at 10 edges per invocation"

# ===========================================================================
# AC8 — Each applied edge audit-comments on the DEPENDENT bead in the
#       canonical format:
#         dep-health-check (just-fix-it): added dep <dependent-id> -> <blocker-id> (type <type>); reason: <rationale>
# ===========================================================================
echo "[ac8_audit_comment_format]"

# The format must appear verbatim (minus angle-bracket placeholders) in SKILL.md.
grep_in_fixed "$SKILL_MD" "dep-health-check (just-fix-it): added dep" \
  "AC8 SKILL.md documents audit-comment prefix"
grep_in_fixed "$SKILL_MD" "(type <type>)" \
  "AC8 SKILL.md documents audit-comment '(type <type>)' segment"
grep_in_fixed "$SKILL_MD" "reason: <rationale>" \
  "AC8 SKILL.md documents audit-comment 'reason:' segment"

# Must say the comment goes on the dependent bead (not the blocker).
grep_in "$SKILL_MD" "(dependent bead|on the dependent|audit comment.*dependent)" \
  "AC8 SKILL.md states audit comment lands on the dependent bead"

# Must use bd comments add (not bd update --append-notes) for audit trail.
grep_in_fixed "$SKILL_MD" "bd comments add" \
  "AC8 SKILL.md uses bd comments add for audit trail"

# ===========================================================================
# AC9 — Report sections distinct: deterministic findings vs LLM-inferred
#       findings are reported in separate sections, AND empty sections are
#       omitted from the report.
# ===========================================================================
echo "[ac9_report_section_separation]"

require_file "$SKILL_MD" "AC9 SKILL.md"

# Distinct deterministic vs LLM-inferred section headings.
grep_in "$SKILL_MD" "([Dd]eterministic findings|[Dd]eterministic [Ss]ection|deterministic.*section)" \
  "AC9 SKILL.md names a deterministic-findings section"
grep_in "$SKILL_MD" "(LLM.?inferred|inferred findings|LLM.?inferred [Ss]ection)" \
  "AC9 SKILL.md names an LLM-inferred-findings section"

# Empty-section-omission rule.
grep_in "$SKILL_MD" "(omit empty|empty sections? (are )?omitted|skip empty sections?|do not.*emit empty)" \
  "AC9 SKILL.md says empty sections are omitted"

# ===========================================================================
# AC10 — Every LLM finding carries a per-item rationale citing observable
#        bead content; no finding may cite only LLM-internal reasoning.
# ===========================================================================
echo "[ac10_llm_rationale_requirement]"

# Per-item rationale rule.
grep_in "$SKILL_MD" "(per.?item rationale|each .*finding.*rationale|every .*finding.*rationale)" \
  "AC10 SKILL.md requires per-item rationale on every LLM finding"

# Rationale must reference observable bead content.
grep_in "$SKILL_MD" "(observable bead content|cite.*bead content|reference.*bead.*field|quote.*bead)" \
  "AC10 SKILL.md requires rationale to cite observable bead content"

# Prohibition on LLM-internal-only reasoning.
grep_in "$SKILL_MD" "(LLM.?internal|internal reasoning|model.?internal|no .*finding.*cite only)" \
  "AC10 SKILL.md prohibits LLM-internal-only reasoning"

# ===========================================================================
# Name-uniqueness sanity (R6) — outside any AC, but a structural invariant of
# this project: 'dep-health-check' must only appear in the three sanctioned
# locations.
# ===========================================================================
echo "[name_uniqueness_r6]"

UNIQ_OUT="$( ( grep -rl --exclude-dir=__pycache__ --exclude='*.pyc' \
                  'dep-health-check' "$REPO_ROOT/src" 2>/dev/null \
                | grep -v "$REPO_ROOT/src/plugins/beads/.agents/skills/dep-health-check" \
                | grep -v "$REPO_ROOT/src/user/.claude/commands/dep-health-check" \
                | grep -v "$REPO_ROOT/src/user/.agents/skills/dep-health-check" \
                | grep -v "$REPO_ROOT/src/plugins/beads/.claude/commands/dep-health-check" ) || true )"
if [ -z "$UNIQ_OUT" ]; then
  pass "R6 dep-health-check name appears only in sanctioned locations under src/"
else
  fail "R6 dep-health-check name uniqueness" \
    "unexpected hits:$(printf '\n%s' "$UNIQ_OUT")"
fi

# ----- final --------------------------------------------------------------
if [ "$FAIL" -ne 0 ]; then
  echo "[dep-health-check/_test.sh] OVERALL: FAIL"
  exit 1
fi
echo "[dep-health-check/_test.sh] OVERALL: PASS"
exit 0
