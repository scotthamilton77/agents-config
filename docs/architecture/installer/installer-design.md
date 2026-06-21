# Installer — Architecture & Design

> **HLD artifacts**: see [`index.md`](index.md) for the C4 (L2 container / L3 engine), sequence, and data-view diagrams derived from this spec. This document is the design-of-record; the diagrams visualise it and are amended in step.

## Purpose

A `uv`-managed Python package (`packages/installer`) that installs agent configuration from this repo into AI coding assistant homes (`~/.claude/`, `~/.codex/`, `~/.gemini/`, OpenCode XDG). User-facing entry point is `scripts/install.sh`, a thin `exec uv run --project packages/installer python -m installer` stub. This repo is the first Python subproject in a modular monorepo; its layout is the template for future Python subprojects.

## Architecture

### Design principles

- **Tool-agnostic core + tool adapters** — the merge engine, staging engine, and sync engine are pure and tool-agnostic; tool-specific behaviour (OpenCode XDG path, OpenCode skips shared `agents/`, Gemini frontmatter transform, Codex placeholder extensions) lives in per-tool adapter modules behind a `ToolAdapter` protocol.
- **Merge strategies are separate classes** — append-merge, JSON union, last-wins-warn, fatal, etc., each in its own module under `core/merge/strategies/`, each testable in isolation, dispatched through a registry.
- **Pure core, injected I/O** — engine modules under `core/` are pure functions; all terminal interaction routes through the `IOPort` protocol (`TerminalIO` real, `ScriptedIO` test fake). No module calls `print`/`input` or imports `rich` directly.

### Repo layout

```
/Users/scott/src/projects/agents-config/
├── packages/
│   └── installer/
│       ├── pyproject.toml                   (uv-managed; targeted deps allowed)
│       ├── installer.toml                   (installer config — prune list, tool registry overrides)
│       ├── src/installer/
│       │   ├── core/                        (pure, tool-agnostic engine)
│       │   ├── tools/                       (per-tool adapters)
│       │   ├── plugins/                     (per-plugin adapters)
│       │   ├── cli.py
│       │   ├── config.py
│       │   └── orchestrator.py
│       └── tests/
│           ├── unit/   integration/   fixtures/
├── scripts/
│   ├── install.sh                           (thin exec uv run --project packages/installer python -m installer stub)
│   └── install.py                           (entry stub: `from installer.cli import main`)
├── src/                                     (agent-config tree, non-Python)
│   ├── user/   plugins/
└── Makefile                                 (top-level dev targets; delegates to per-package targets)
```

### Package layout (`packages/installer/src/installer/`)

```
installer/
├── cli.py                       Parse argv, build Config, wire IOPort, invoke orchestrator
├── config.py                    Config dataclass; tool/plugin auto-detection; loads installer.toml
├── orchestrator.py              Top-level controller; composes core engines + adapters
├── core/                        ── pure, tool-agnostic, fully unit-testable
│   ├── model.py                 FileKind, StagedItem, StagingPlan, Orphan, IncludeDirective, Counters
│   ├── io_port.py               IOPort protocol + TerminalIO + ScriptedIO
│   ├── templates.py             DYNAMIC-INCLUDE flattening (all three directive forms)
│   ├── staging.py               Phases 1–6.9: source-walk → StagingPlan; parameterised by ToolAdapter
│   ├── sync.py                  Phase 7: hash-compare, diff, prompt, backup, write
│   ├── prune.py                 Orphan scan + interactive prune flow
│   └── merge/
│       ├── registry.py          (FileKind, namespace) → MergeStrategy dispatch
│       ├── base.py              MergeStrategy protocol
│       └── strategies/
│           ├── append_rules.py        rules/*.md → join with \n---\n
│           ├── fatal.py               commands/skills/agents collision → raise
│           ├── json_union.py          settings.json → deep union merge
│           ├── last_wins_warn.py      jsonc / toml → warn + replace
│           └── last_wins_silent.py    other → silent replace
├── tools/                       ── tool-specific adapters
│   ├── base.py                  ToolAdapter protocol
│   ├── claude.py
│   ├── codex.py
│   ├── gemini.py                Owns Gemini frontmatter transform
│   ├── opencode.py              Owns XDG dest + "skip shared agents/" rule
│   └── registry.py
└── plugins/                     ── plugin adapters
    ├── base.py                  PluginAdapter protocol
    ├── beads.py                 Owns ~/.beads/ destination, chmod +x on scripts
    ├── extensions.py            apply_extensions(): YAML-patch base markdown assets post-staging
    └── registry.py
```

The `ToolAdapter` protocol abstracts everything the engine needs to know about a tool:

```python
class ToolAdapter(Protocol):
    name: str
    def source_dir(self, repo_root: Path) -> Path: ...
    def dest_dir(self, home: Path) -> Path: ...
    def is_detected(self, home: Path) -> bool: ...
    def scoped_namespaces(self) -> tuple[str, ...]: ...
    def should_install_namespace(self, ns: str, source: str) -> bool: ...  # OpenCode: False for shared agents/
    def post_staging_transforms(self, plan: StagingPlan, io: IOPort) -> StagingPlan: ...  # Gemini frontmatter
```

The core engine takes a `ToolAdapter` and a source root; tests substitute a `FakeAdapter` to exercise the engine independently of any real tool.

`MergeStrategy` protocol:

```python
class MergeStrategy(Protocol):
    def merge(self, existing: StagedItem, incoming: StagedItem) -> StagedItem: ...
```

Each strategy class lives in its own module with its own test file. `core/merge/registry.py` provides the `(FileKind, namespace) → MergeStrategy` lookup (namespace is unused for non-namespaced kinds — see §"Data model highlights"), easily swapped in tests.

### Dependency management — `uv`

The installer is a `uv`-managed Python project. `pyproject.toml` declares deps; `uv.lock` is committed. Users invoke via `scripts/install.sh` (the exec stub) or `python3 scripts/install.py` (direct entry).

**Python floor:** ≥3.11 (broad availability; stdlib `tomllib` for reading TOML).

**Runtime deps (targeted, not stdlib-only):**

- `pyyaml` — for the Gemini frontmatter transform.
- `tomli-w` — to write `installer.toml` updates (3.11 stdlib reads TOML; it does not write).
- `rich` — pretty diffs, colored output, prompt formatting.

The dependency list is deliberately tight, but we no longer refuse a library that exists and solves the problem.

**Dev deps:** `pytest`, `pytest-xdist`, `ruff`, `mypy` (strict). `uv tool run` is the local invocation pattern.

### Configuration — `installer.toml`

Structured TOML at `packages/installer/installer.toml` owns installer configuration:

```toml
[prune]
# Retired paths (one per glob pattern) — see installer/core/prune.py for matching semantics.
retired = [
  "*/skills/condition-based-waiting",
  "claude/rules/git-commits.md",
]

[tools]
# Optional overrides — leave commented to use built-in adapters.
# claude.dest = "~/.claude"
```

### `--dump-stage` flag

A debug mode that materialises the in-memory `StagingPlan` to a directory and exits without touching destinations:

```
python3 scripts/install.py --dump-stage /tmp/stage-debug
```

Writes the full plan as a real directory tree (`<dump>/<tool>/...`), prints the dump path, and exits 0. Useful for debugging template flattening, plugin overlay, and collision resolution without committing to a destination write. Mutually exclusive with `--prune`/`--prune-only`.

### `IOPort` protocol

Single injectable abstraction (`info`/`ok`/`warn`/`err`/`header`/verbose variants/`show_diff`/`confirm`/`confirm_three_way`/`confirm_per_item`/`is_interactive`). Two implementations: `TerminalIO` (real, uses `rich`) and `ScriptedIO` (test). No module reaches for `print`/`input` directly.

### Data model highlights

- `Tool` is an enum for exhaustive type-checking; `ToolAdapter` instances live in a registry keyed by `Tool` value. Plugins are **not** enumerated — they are discovered dynamically by scanning `src/plugins/<name>/` and registered by name string, so adding a plugin requires no code change to `model.py`. `PluginAdapter` instances live in a string-keyed registry. Per-`StagedItem` provenance is tracked via a `Provenance(kind: Literal["tool","plugin"], name: str)` dataclass so tool-vs-plugin origin survives the asymmetry.
- `FileKind` enum keys `MergeStrategy` dispatch in `core/merge/registry.py` on **`(FileKind, namespace)`** because `NAMESPACED_MD` items need their parent-dir namespace to pick the right strategy (e.g. `(NAMESPACED_MD, "rules")` → append-merge; `(NAMESPACED_MD, "commands")` → fatal). For non-namespaced kinds (`SETTINGS_JSON`, `JSONC`, `TOML`, `OTHER`, `DIR`) the namespace component is unused and the lookup degenerates to a `FileKind`-only key.
- `StagingPlan` is the in-memory staging structure — a `dict[Path, StagedItem]` plus provenance tracking.
- `Orphan` dataclass carries tool, namespace, path, and kind for each item found in the destination but not in the current source.
- `Config` is frozen, populated from argv + `installer.toml` + auto-detection probes (which themselves consult adapters).

## Test architecture

Three suites under `packages/installer/tests/`. Target ~120–150 tests, full run under one minute.

### Unit (`tests/unit/`, ~80–100 tests, <2s)

Pure-function tests against the core engine, exercised through a `FakeToolAdapter` so each module tests in isolation. Examples by module:

- `core/templates.py` — directive recognition; ALL-RULES join; trailing-newline preservation; Gemini frontmatter strip + tools-list YAML conversion.
- `core/merge/strategies/append_rules.py` — empty/non-empty concat; separator placement.
- `core/merge/strategies/json_union.py` — nested dict precedence; array union+dedupe (first-seen order); type mismatch; key only in incoming.
- `core/merge/strategies/fatal.py` — raises with informative message including filenames.
- `core/merge/registry.py` — `(FileKind, namespace)` dispatch correctness; unknown key raises.
- `core/prune.py` — TOML prune-list load; glob matching (`*/skills/foo` vs exact match).
- `core/io_port.py` (`ScriptedIO`) — consumes scripts in order; raises on exhaustion; records transcript faithfully.
- `tools/<name>.py` — each adapter's `is_detected`, `dest_dir`, `should_install_namespace` rules tested independently.

### Integration (`tests/integration/`, ~30–40 tests, <30s)

**Behaviour-driven, not implementation-driven.** Fixtures live in `tests/fixtures/states/` and represent versioned snapshots of *user-state-before-install*: clean home, normal-user-with-existing-config, conflicting-rules, orphans-present, corrupted-settings, legacy-backups-present, plugin-overlay-active, etc. Each fixture is a real directory tree the test can `shutil.copytree` into `tmp_path`.

Tests assert **end-state goals**, not how those goals were achieved:

- "After install against the `normal-user` fixture, `~/.claude/skills/<name>/SKILL.md` content matches the source."
- "After install, the user's pre-existing `settings.json.user-keys` are preserved."
- "After `--prune --yes` against `orphans-present`, the orphan files are gone AND their pre-prune content is recoverable from a backup directory."
- "After install with the test-plugin active, the plugin's rule appears appended to the matching base rule, separated by `\n---\n`."

Test names describe the contract, e.g. `test_user_modified_settings_keys_are_preserved_after_install`. Implementation details (which phase touched what, which strategy fired) are not asserted; the strategy is tested at the unit level.

### Fixture strategy

- `tests/fixtures/states/` — versioned, on-disk, hand-curated snapshots of pre-install user-state (one subdir per scenario). Committed to git so reviewers can inspect them.
- `tests/fixtures/sources/` — synthetic source trees (one per scenario) that exercise specific behaviours without depending on the real `src/user/`.
- Builder functions in `conftest.py` for ad-hoc fixture composition.

## CLI surface

```
python3 scripts/install.py [--dry-run] [--yes] [--verbose] [--tools=TOOLS] [--plugins=PLUGINS]
                           [--prune | --prune-only] [--dump-stage <path>] [--help]
```

`--dump-stage` is mutually exclusive with `--prune` / `--prune-only`. All other flags are mutually exclusive per the standard install / prune-only split.

## Implementation discipline

**Total TDD.** Every change follows the same arc; no production code lands without a failing test that justifies it.

1. **Test plan review** (collaborative, before any code). For the story, co-author a list of unit and integration test cases — names + brief intent + which fixture or scripted-IO scenario each exercises. The list captures the contract the implementation must satisfy. User signs off before red-phase work starts.
2. **Red phase.** Implement the tests. No production code yet. Tests fail by definition. Commit the red phase.
3. **Green phase.** Write the minimum production code to make the tests pass. No speculative scope, no extra abstractions beyond what the tests require.
4. **Refactor + verify.** Run the verification gate: `quality-reviewer` agent, `simplify` skill, full suite + lint + typecheck green.

**Test plan completeness criteria** — before signing off on a test plan, confirm:
- Every public function/class introduced has at least one unit test.
- Every documented behaviour has a corresponding integration test.
- Failure modes are covered (malformed input, missing files, collisions, non-interactive guard, etc.).
- Each test name names the *contract*, not the implementation (`test_user_settings_keys_are_preserved` not `test_json_union_strategy_invokes_recursive_merge`).

## Critical files

- `packages/installer/src/installer/core/model.py`
- `packages/installer/src/installer/core/io_port.py`
- `packages/installer/src/installer/core/staging.py`
- `packages/installer/src/installer/core/merge/registry.py` plus each strategy module
- `packages/installer/src/installer/tools/base.py` + per-tool adapters

## Verification

1. **Unit suite:** `uv run pytest packages/installer/tests/unit -q` — green; coverage ≥90% on touched modules.
2. **Integration suite:** `uv run pytest packages/installer/tests/integration -q` — green; assertions phrased as end-state contracts, not phase mechanics; scripted IOPort scripts fully consumed.
3. **Lint + typecheck:** `uv run ruff check packages/installer && uv run mypy --strict packages/installer/src` — clean.
4. **`--dump-stage` sanity:** dump the plan; confirm contents match the expected tree by inspection.

Or run all four in one shot: `make ci-installer` from the repo root.
