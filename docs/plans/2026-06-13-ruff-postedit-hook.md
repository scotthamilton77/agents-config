# ruff-postedit Hook Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a global Claude Code PostToolUse hook that runs ruff on a just-edited Python file — silently applying safe fixes + formatting, and surfacing only residual unfixable violations — deployed via the active `scripts/install.sh` through a new `hooks/` namespace.

**Architecture:** A self-contained stdlib-only Python script (`ruff-postedit.py`) parses the hook's stdin JSON, gates on a discovered ruff config, runs `ruff check --fix` → `ruff format` → `ruff check`, and maps the final exit code to silent-0 / feedback-2. It is wired into `settings.json.template` (invoked via `python3 <path>`) and deployed by adding `hooks` to `install.sh`'s tool-subdir staging loop.

**Tech Stack:** Python 3 (stdlib), bash (`install.sh`, `*_test.sh` test convention), ruff, Claude Code hooks.

**Spec:** `docs/specs/2026-06-13-ruff-postedit-hook-design.md`

## Scope

**In scope (this plan / branch):** the hook script + tests, the `settings.json.template` wiring, the `project-config.toml` test-glob extension, and the **legacy `scripts/install.sh`** `hooks/` namespace (the active installer — this is what deploys the hook today).

**Out of scope (tracked separately):** the **`packages/installer/` (Python rewrite)** `hooks/` namespace + golden-master coverage. Tracked under **`agents-config-w1qls.8.7`** (Epic H). The Epic H parity harness is the forcing function that surfaces any divergence before cutover; the Python installer is not the active installer today.

## File Structure

| Path | Responsibility | Action |
|---|---|---|
| `src/user/.claude/hooks/ruff-postedit.py` | The hook: parse → gate → run ruff → map exit code | Create |
| `src/user/.claude/hooks/ruff-postedit_test.sh` | Hermetic tests via a fake `ruff` PATH shim | Create |
| `src/user/.claude/settings.json.template` | Register the PostToolUse matcher | Modify |
| `project-config.toml` | Extend the `test` target glob to include `hooks/` | Modify |
| `scripts/install.sh` | Add `hooks` to the tool-subdir staging loop (line 802) | Modify |

---

### Task 1: Hook script `ruff-postedit.py` (+ hermetic tests)

**Files:**
- Create: `src/user/.claude/hooks/ruff-postedit.py`
- Test: `src/user/.claude/hooks/ruff-postedit_test.sh`

- [ ] **Step 1: Write the failing test**

Create `src/user/.claude/hooks/ruff-postedit_test.sh`:

```bash
#!/usr/bin/env bash
# Hermetic tests for ruff-postedit.py. A fake `ruff` shim on PATH makes
# exit-code/gating behavior deterministic without depending on real ruff
# (ruff's own fix/format behavior is ruff's to test, not ours).
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK="$SCRIPT_DIR/ruff-postedit.py"
PASS=0; FAIL=0

assert_rc()       { if [ "$2" -eq "$3" ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL: $1 (expected rc=$2, got $3)"; fi; }
assert_contains() { case "$3" in *"$2"*) PASS=$((PASS+1));; *) FAIL=$((FAIL+1)); echo "FAIL: $1 (stderr missing '$2')";; esac; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

# fake ruff shim: only the final `check --force-exclude` decides the outcome
BIN="$WORK/bin"; mkdir -p "$BIN"
cat > "$BIN/ruff" <<'SH'
#!/bin/sh
if [ "$1" = "check" ] && [ "$2" = "--force-exclude" ]; then
  if [ "${FAKE_RUFF_RESIDUAL:-0}" = "1" ]; then
    echo "bad.py:1:1: F821 Undefined name \`x\`"
    exit 1
  fi
fi
exit 0
SH
chmod +x "$BIN/ruff"
PATH="$BIN:$PATH"; export PATH

# ruff-configured project fixture (no uv.lock -> hook uses PATH ruff = our shim)
PROJ="$WORK/proj"; mkdir -p "$PROJ"
printf '[tool.ruff]\nline-length = 100\n' > "$PROJ/pyproject.toml"
echo "x = 1" > "$PROJ/clean.py"

run_hook() { ERR="$(printf '%s' "$1" | python3 "$HOOK" 2>&1 >/dev/null)"; RC=${PIPESTATUS[1]}; }

# 1. non-.py -> silent 0
run_hook "{\"tool_input\":{\"file_path\":\"$PROJ/clean.txt\"}}"
assert_rc "non-python file is ignored" 0 "$RC"

# 2. .py with no ruff config in tree -> silent 0
echo "x=1" > "$WORK/loose.py"
run_hook "{\"tool_input\":{\"file_path\":\"$WORK/loose.py\"}}"
assert_rc "no ruff config -> skip" 0 "$RC"

# 3. clean .py in configured project -> silent 0
run_hook "{\"tool_input\":{\"file_path\":\"$PROJ/clean.py\"}}"
assert_rc "clean file -> exit 0" 0 "$RC"

# 4. residual unfixable -> exit 2 + helpful stderr
export FAKE_RUFF_RESIDUAL=1
run_hook "{\"tool_input\":{\"file_path\":\"$PROJ/clean.py\"}}"
assert_rc       "residual -> exit 2" 2 "$RC"
assert_contains "residual names rule" "F821" "$ERR"
assert_contains "residual has nudge"  "manual attention" "$ERR"
unset FAKE_RUFF_RESIDUAL

# 5. malformed JSON -> silent 0
run_hook "not json at all"
assert_rc "malformed JSON -> exit 0" 0 "$RC"

# 6. missing file_path -> silent 0
run_hook "{}"
assert_rc "missing file_path -> exit 0" 0 "$RC"

# 7. ruff absent (PATH has only python3) -> silent 0
PYBIN="$WORK/pybin"; mkdir -p "$PYBIN"; ln -s "$(command -v python3)" "$PYBIN/python3"
ERR="$(printf '%s' "{\"tool_input\":{\"file_path\":\"$PROJ/clean.py\"}}" | PATH="$PYBIN" python3 "$HOOK" 2>&1 >/dev/null)"; RC=$?
assert_rc "ruff absent -> exit 0" 0 "$RC"

echo "----"
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bash src/user/.claude/hooks/ruff-postedit_test.sh`
Expected: FAIL — `python3` cannot open `ruff-postedit.py` (file does not exist yet), so every case reports a non-zero rc and the script exits non-zero.

- [ ] **Step 3: Write the hook script**

Create `src/user/.claude/hooks/ruff-postedit.py`:

```python
#!/usr/bin/env python3
"""PostToolUse hook: run ruff on a just-edited Python file.

Applies ruff's safe fixes + formatting silently; exits 2 with the residual
unfixable violations on stderr. Any internal problem (no ruff, no config,
crash, timeout, bad input) is a silent exit 0 — the hook is invisible unless
it has a real, actionable lint result.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

PY_SUFFIXES = {".py", ".pyi"}
CONFIG_FILENAMES = ("ruff.toml", ".ruff.toml")
TIMEOUT_SECONDS = 10


def _read_file_path():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    tool_input = payload.get("tool_input") or {}
    fp = tool_input.get("file_path")
    if not fp or not isinstance(fp, str):
        return None
    return Path(fp)


def _find_config_root(start: Path):
    """Walk upward for a ruff config; return the directory that holds it."""
    for d in [start, *start.parents]:
        for name in CONFIG_FILENAMES:
            if (d / name).is_file():
                return d
        pyproject = d / "pyproject.toml"
        if pyproject.is_file():
            try:
                if "[tool.ruff" in pyproject.read_text(encoding="utf-8", errors="ignore"):
                    return d
            except OSError:
                pass
    return None


def _ruff_argv(config_root: Path):
    """Prefer the project-pinned ruff (uv, no sync); else PATH ruff."""
    if (config_root / "uv.lock").is_file() or (config_root / ".venv").is_dir():
        if shutil.which("uv"):
            return ["uv", "run", "--no-sync", "ruff"]
    if shutil.which("ruff"):
        return ["ruff"]
    return None


def _run(argv, cwd: Path):
    try:
        return subprocess.run(
            argv, cwd=str(cwd), capture_output=True, text=True,
            timeout=TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def main() -> int:
    file_path = _read_file_path()
    if file_path is None:
        return 0
    if file_path.suffix not in PY_SUFFIXES or not file_path.is_file():
        return 0

    config_root = _find_config_root(file_path.parent)
    if config_root is None:
        return 0

    ruff = _ruff_argv(config_root)
    if ruff is None:
        return 0

    target = str(file_path)
    if _run([*ruff, "check", "--fix", "--force-exclude", target], config_root) is None:
        return 0
    if _run([*ruff, "format", "--force-exclude", target], config_root) is None:
        return 0
    final = _run([*ruff, "check", "--force-exclude", target], config_root)
    if final is None:
        return 0

    # ruff check: 0 = clean, 1 = violations remain, 2 = ruff internal error
    if final.returncode == 1:
        sys.stderr.write(
            "ruff auto-fixed what it could; the following need manual attention:\n"
            + (final.stdout or final.stderr or "")
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Then make it executable:

Run: `chmod +x src/user/.claude/hooks/ruff-postedit.py`

- [ ] **Step 4: Run the test to verify it passes**

Run: `bash src/user/.claude/hooks/ruff-postedit_test.sh`
Expected: `PASS=8 FAIL=0` and exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/user/.claude/hooks/ruff-postedit.py src/user/.claude/hooks/ruff-postedit_test.sh
git commit -m "feat(hooks): add ruff-postedit PostToolUse hook + hermetic tests"
```

---

### Task 2: Include `hooks/` tests in the project test target

**Files:**
- Modify: `project-config.toml` (the `test` command)

- [ ] **Step 1: Read the current `test` target**

Run: `grep -n 'test ' project-config.toml`
Expected: a line of the form
`test = "find src/user/.agents/skills -name '*_test.sh' -print0 | sort -z | xargs -0 -I{} sh -c 'echo \"[TEST] $1\"; bash \"$1\" || exit 1' _ {}"`

- [ ] **Step 2: Extend the glob to also scan `src/user/.claude/hooks`**

Change the `find` path list so both roots are scanned. Replace `find src/user/.agents/skills` with `find src/user/.agents/skills src/user/.claude/hooks`:

```toml
test      = "find src/user/.agents/skills src/user/.claude/hooks -name '*_test.sh' -print0 | sort -z | xargs -0 -I{} sh -c 'echo \"[TEST] $1\"; bash \"$1\" || exit 1' _ {}"
```

(Keep the rest of the line — the `-print0 | sort -z | xargs -0 …` pipeline — byte-for-byte identical.)

- [ ] **Step 3: Verify the hook test is now collected and green**

Run: `find src/user/.agents/skills src/user/.claude/hooks -name '*_test.sh' | grep ruff-postedit`
Expected: prints `src/user/.claude/hooks/ruff-postedit_test.sh`

Run: `bash src/user/.claude/hooks/ruff-postedit_test.sh`
Expected: `PASS=8 FAIL=0`

- [ ] **Step 4: Commit**

```bash
git add project-config.toml
git commit -m "build(hooks): include src/user/.claude/hooks in the test target"
```

---

### Task 3: Wire the hook into `settings.json.template`

**Files:**
- Modify: `src/user/.claude/settings.json.template` (the `hooks.PostToolUse` array)

- [ ] **Step 1: Confirm the current PostToolUse shape**

Run: `python3 -c "import json;print(json.dumps(json.load(open('src/user/.claude/settings.json.template'))['hooks']['PostToolUse'], indent=2))"`
Expected: a one-element array — the `detect-pr-push.sh` Bash matcher.

- [ ] **Step 2: Append the ruff-postedit matcher**

Add a second object to the `PostToolUse` array (leave the existing `detect-pr-push.sh` entry first, unchanged). The array becomes:

```jsonc
"PostToolUse": [
  {
    "matcher": "Bash",
    "hooks": [
      { "type": "command", "command": "~/.claude/skills/wait-for-pr-comments/detect-pr-push.sh", "timeout": 5 }
    ]
  },
  {
    "matcher": "Write|Edit",
    "hooks": [
      { "type": "command", "command": "python3 ~/.claude/hooks/ruff-postedit.py", "timeout": 15 }
    ]
  }
]
```

- [ ] **Step 3: Verify the template still parses and contains both hooks**

Run:
```bash
python3 -c "
import json
d=json.load(open('src/user/.claude/settings.json.template'))
ptu=d['hooks']['PostToolUse']
cmds=[h['command'] for m in ptu for h in m['hooks']]
assert any('detect-pr-push' in c for c in cmds), 'lost detect-pr-push hook'
assert any('ruff-postedit' in c for c in cmds), 'ruff-postedit hook not added'
print('OK: both PostToolUse hooks present')
"
```
Expected: `OK: both PostToolUse hooks present`

- [ ] **Step 4: Commit**

```bash
git add src/user/.claude/settings.json.template
git commit -m "feat(hooks): register ruff-postedit PostToolUse hook in settings template"
```

---

### Task 4: Stage the `hooks/` namespace in `scripts/install.sh`

**Files:**
- Modify: `scripts/install.sh:802` (the tool-subdir staging loop)

- [ ] **Step 1: Confirm the staging loop**

Run: `sed -n '800,805p' scripts/install.sh`
Expected (around line 802):
```bash
        for subdir in commands skills agents rules; do
            stage_content_from_dir "$src_tool" "$staging" "$subdir"
        done
```
`stage_content_from_dir` (line 603) globs every item in `$src_tool/<subdir>/` and stages each via `stage_item`; a `.py` file classifies as `"other"` and copies normally — so no other change is needed to carry the script.

- [ ] **Step 2: Add `hooks` to the loop**

Edit line 802 — append `hooks` to the subdir list:
```bash
        for subdir in commands skills agents rules hooks; do
```
Leave the `prune_subdirs=(commands skills agents rules)` list at line 1529 **unchanged** — `hooks/` must stay prune-exempt (matches the spec and the orphan-scan comment at `install.sh:1453`).

- [ ] **Step 3: Verify deployment into a throwaway HOME**

Run from the worktree root (uses this branch's `src/`):
```bash
TMPHOME="$(mktemp -d)"
HOME="$TMPHOME" bash scripts/install.sh --yes --tools=claude >/tmp/ruff-hook-install.log 2>&1 || { tail -40 /tmp/ruff-hook-install.log; echo "INSTALL FAILED"; }
test -f "$TMPHOME/.claude/hooks/ruff-postedit.py" && echo "DEPLOYED: hook script present"
python3 -c "
import json
d=json.load(open('$TMPHOME/.claude/settings.json'))
ok=any('ruff-postedit' in h.get('command','') for m in d['hooks']['PostToolUse'] for h in m['hooks'])
print('SETTINGS MERGED:' , ok)
assert ok
"
rm -rf "$TMPHOME"
```
Expected: `DEPLOYED: hook script present` and `SETTINGS MERGED: True`.

- [ ] **Step 4: Confirm the deployed script is invocable**

The settings command uses `python3 ~/.claude/hooks/ruff-postedit.py`, so execution does not depend on the deployed file's mode bit. Confirm it nonetheless runs:
```bash
echo '{}' | python3 "$TMPHOME/.claude/hooks/ruff-postedit.py"; echo "rc=$?"
```
(Run before the `rm -rf "$TMPHOME"` above, or re-stage.) Expected: `rc=0`.
If the deployed file is **not** executable and you want belt-and-suspenders parity with the source `+x`, note it for follow-up — it is **not** a blocker because invocation is via `python3`.

- [ ] **Step 5: Commit**

```bash
git add scripts/install.sh
git commit -m "feat(installer): stage hooks/ namespace in install.sh"
```

---

## Self-Review

**Spec coverage:**
- Behavior contract (silent fixes, exit-2 residual, silent-0 on all internal failures) → Task 1 script + test cases 3/4/5/6/7.
- Auto-fix scope (safe `--fix` + `format`) → Task 1 Step 3 (`ruff check --fix` without `--unsafe-fixes`, then `ruff format`).
- Activation gate + config-root discovery → Task 1 `_find_config_root` + test case 2.
- ruff discovery (uv `--no-sync` → PATH ruff → skip) → Task 1 `_ruff_argv` + test case 7.
- `--force-exclude` → Task 1 Step 3.
- Hook wiring `python3 <path>`, matcher `Write|Edit` → Task 3.
- `hooks/` legacy-installer namespace + prune-exemption → Task 4.
- Test-glob extension → Task 2.
- Python-installer parity → **out of scope**, tracked in `w1qls.8.7` (stated in Scope).

**Placeholder scan:** none — all code and commands are concrete.

**Type/name consistency:** `_read_file_path`, `_find_config_root`, `_ruff_argv`, `_run`, `main` are consistent across Task 1; `ruff check --fix` / `ruff format` / `ruff check` order matches the spec; matcher `Write|Edit` matches between spec and Task 3.

**Risks the spec flagged, carried into tasks:** legacy exec-bit (Task 4 Step 4 — mitigated by `python3` invocation); settings union-merge append (Task 4 Step 3 verifies the merged result); `uv --no-sync` availability (Task 1 case 7 covers the no-ruff fallback; real-uv behavior validated at integration time).
