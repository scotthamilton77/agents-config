# Design: Global `ruff-postedit` PostToolUse hook + `hooks/` installer namespace

**Date:** 2026-06-13
**Status:** draft (design — awaiting review)
**Scope:** Adds a global discipline-layer PostToolUse hook that runs ruff on just-edited Python files, plus the `hooks/` installer namespace needed to deploy it.

## Summary

After an agent edits a Python file, run ruff on that one file: silently apply every fix ruff can make (safe lint fixes + formatting), and surface only the residual *unfixable* violations back to the agent. The hook ships to every tool/project via the discipline layer, so it must be **invisible unless it has a real, actionable result**, and must **degrade silently** wherever ruff is absent or unconfigured.

Delivering it requires a new `hooks/` namespace in both installers (legacy `scripts/install.sh` and the Python rewrite at `packages/installer/`), since neither stages a `hooks/` directory today.

## Motivation

Lint/format feedback currently arrives only at `make ci` / pre-push time. A per-edit hook tightens the loop: the agent fixes (or is told about) ruff violations the moment it writes them, not after a full gate run. Auto-applying ruff's fixes keeps the agent's files continuously clean with zero agent effort; reporting the rest keeps the agent honest about what it can't auto-resolve.

## Behavior contract

| Condition | Outcome |
|---|---|
| Non-Python file, missing `file_path`, unparseable hook JSON, file no longer exists | **exit 0, silent** |
| Python file, but no ruff config found walking up the tree | **exit 0, silent** (opt-in gate) |
| ruff not resolvable (no PATH ruff, no usable `uv` env) | **exit 0, silent** |
| ruff crash, ruff "abnormal" exit (2), or internal timeout | **exit 0, silent** (never block on our own failure) |
| ruff applied fixes and nothing remains | **exit 0, silent** (file may have been rewritten) |
| Unfixable violations remain after fix + format | **exit 2**, residual diagnostics + nudge on **stderr** |

**Invariant:** the hook exits 2 *only* for genuine remaining lint on an in-scope file in a ruff-configured project. Every other path is a silent exit 0.

## Auto-fix scope (accepted tradeoff)

The hook applies `ruff check --fix` **safe fixes only** (never `--unsafe-fixes`) and `ruff format`. This includes import sorting and unused-import removal. Accepted hazard: a safe fix can remove code the agent planned to use across a multi-edit sequence (e.g. an import added in one edit, intended for use two edits later, removed as "unused" in between). This is judged acceptable because:

- The harness file-state guard prevents data loss: after the hook mutates the file, the agent's next `Edit`/`Write` fails with a "modified since read" error, forcing a re-read — so the agent sees the change rather than clobbering blindly.
- Formatting changes are semantically inert; the agent's understanding of the *code* stays correct even before the re-read.
- This matches familiar format/fix-on-save editor behavior.

Costs we accept: one wasted edit round-trip per touched file (re-read after the staleness error); whole-file reformat can add diff churn to a one-line edit (mitigated by the opt-in gate — ruff-using repos keep files formatted); benign re-format oscillation if the agent's next op is a stale full `Write`.

## Component 1 — `ruff-postedit.py`

A self-contained Python script (`#!/usr/bin/env python3`, standard library only). Source: `src/user/.claude/hooks/ruff-postedit.py`. Deploys to `~/.claude/hooks/ruff-postedit.py`.

### Algorithm

1. Read stdin JSON. On parse failure → exit 0.
2. Extract `tool_input.file_path`. Missing → exit 0. (Note: `NotebookEdit` uses `notebook_path`, so notebooks fall out here.)
3. Resolve to an absolute path. Suffix must be `.py` or `.pyi` and the file must exist → else exit 0.
4. **Activation gate / config-root discovery.** Walk upward from the file's directory to the filesystem root, looking for the first of:
   - `pyproject.toml` containing a `[tool.ruff` table (substring check on the file text — avoids a TOML dependency and tolerates `[tool.ruff]` and `[tool.ruff.<subtable>]`),
   - `ruff.toml`, or `.ruff.toml`.

   None found → exit 0. The directory containing the match is the **config root** (ruff runs with this as CWD so it loads the right config).
5. **ruff discovery** (first that works, else exit 0):
   - `uv run --no-sync ruff …` when the config root has a `uv.lock` or `.venv` (use the project-pinned ruff with no install side effects — this is the agents-config dogfood case, where ruff lives in each package's uv env, not on PATH);
   - otherwise `ruff` on PATH.
6. **Apply + report** (CWD = config root; each call wrapped in a ~10s timeout):
   1. `ruff check --fix --force-exclude <file>` — applies safe fixes.
   2. `ruff format --force-exclude <file>` — formats in place.
   3. `ruff check --force-exclude <file>` — authoritative residual check.

   `--force-exclude` ensures the project's `exclude`/`extend-exclude` is honored even though we pass an explicit path.

   Interpret the final check's exit code:
   - `0` → exit 0, silent.
   - `1` (violations remain) → print the diagnostics + a one-line nudge (`ruff auto-fixed what it could; the following need manual attention:`) to **stderr**, exit 2.
   - `2` (ruff abnormal/error) → exit 0, silent.
7. Any unexpected exception, missing binary, or timeout anywhere above → exit 0, silent.

## Component 2 — hook wiring (`src/user/.claude/settings.json.template`)

Append a second matcher object to the existing `PostToolUse` array (the `detect-pr-push.sh` Bash entry is preserved by the settings union-merge):

```jsonc
{
  "matcher": "Write|Edit",
  "hooks": [
    {
      "type": "command",
      "command": "python3 ~/.claude/hooks/ruff-postedit.py",
      "timeout": 15
    }
  ]
}
```

- `Write|Edit` matches `Write`, `Edit`, `MultiEdit`, and (harmlessly) `NotebookEdit`; the `.py` filter inside the script is the authoritative gate.
- Invoked via `python3 <path>` rather than a bare exec path, so deployment does not depend on the executable bit or shebang resolution. The source file still ships `+x` as belt-and-suspenders.
- `settings.json.template` union-merges into `~/.claude/settings.json` (`staging.py` `classify_file`; legacy `install.sh` `classify_file`); the new array element is appended without disturbing the existing hook.

## Component 3 — `hooks/` installer namespace

Neither installer stages a `hooks/` directory today. Both enumerate a fixed namespace allowlist (`commands | skills | agents | rules`, shared `skills | agents | rules`). This is the bulk of the work and touches the gated `packages/installer`.

This hook is **Claude-specific** — `settings.json` PostToolUse hooks are a Claude Code feature; Codex/Gemini have no equivalent mechanism. So the source lives under `src/user/.claude/hooks/` and deploys to `~/.claude/hooks/`. The installer's `hooks/` namespace support is added generically (any tool source dir may carry a `hooks/`), but in practice only `.claude` populates it.

### Legacy `scripts/install.sh`
- Add `hooks` to the staged-namespace set so a tool's `hooks/` source dir (here `src/user/.claude/hooks/`) stages to `~/.<tool>/hooks/` (here `~/.claude/hooks/`).
- Apply `chmod +x` to staged hook scripts, mirroring the existing `scripts/` handling.
- `hooks/` is already prune-exempt (the orphan scan excludes top-level non-namespace entries), so no prune change is needed on the bash side.

### Python installer (`packages/installer/`)
- Add `hooks` to namespace staging (alongside the `skills`/`agents`/`rules` handling in `core/staging.py`). Hook files are staged as files (like `rules`/`commands`), not dir-granularity entries (like `skills`/`agents`).
- Preserve the source executable bit via the existing `executable` mode attribute on the staged-item model (`core/model.py`), so deployed scripts land `0o755`.
- Ensure the orphan/prune scan (`core/prune.py`) never treats `~/.<tool>/hooks/` entries as prunable orphans.
- This work is tracked for parity under **`agents-config-w1qls.8.7`** (Epic H); see that bead for the rewrite-side checklist and golden-master coverage.

## Testing

- **`src/user/.claude/hooks/ruff-postedit_test.sh`** — pipes crafted PostToolUse JSON to the script and asserts exit code + stderr against a tmp fixture project (a throwaway `pyproject.toml` with `[tool.ruff]`, plus clean / fixable-dirty / unfixable-dirty `.py` files). Cases:
  - non-`.py` file → exit 0, file untouched;
  - `.py` with no ruff config in the tree → exit 0;
  - clean `.py` → exit 0;
  - fixable-dirty `.py` (e.g. unsorted imports, reformattable layout) → exit 0 **and the file is rewritten clean**;
  - unfixable-dirty `.py` (e.g. an undefined name) → exit 2 **and stderr names the rule**;
  - malformed JSON / missing `file_path` → exit 0;
  - ruff absent on PATH and no uv env → exit 0.
- **Extend `project-config.toml`'s `test` target** to also glob `src/user/.claude/hooks/*_test.sh` (today it scans only `src/user/.agents/skills`).
- **Installer unit tests** for `hooks` namespace staging + exec-bit preservation + prune-exemption, run under `make ci-installer`.

## Out of scope

- Non-Python linters / other tools (this hook is ruff-only).
- Notebook (`.ipynb`) linting.
- `--unsafe-fixes`.
- Project-specific ruff config authoring — the hook consumes whatever config the project already has.

## Risks / verification owed by the plan

- **Legacy-installer exec-bit parity for `hooks/`.** Confirm `install.sh` actually `chmod +x`es a `hooks/` namespace (its current `+x` logic is wired for `scripts/` dirs). Mitigated regardless by invoking via `python3 <path>`.
- **settings union-merge append semantics.** Confirm the `json_union` merge appends the new matcher object rather than collapsing/deduping it against the existing Bash matcher.
- **uv `--no-sync` availability** across the uv versions in use.
