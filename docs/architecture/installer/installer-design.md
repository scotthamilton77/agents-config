# Rewrite `scripts/install.sh` as a Python package

> **HLD artifacts**: see [`index.md`](index.md) for the C4 (L2 container / L3 engine), sequence, and data-view diagrams derived from this spec. This document is the design-of-record; the diagrams visualise it and are amended in step.

## Context

`/Users/scott/src/projects/agents-config/scripts/install.sh` is 1788 lines of shell carrying ten subsystems: tool/plugin detection, 7-phase staging, three DYNAMIC-INCLUDE directive forms, a Gemini-only frontmatter transform, a sentinel-driven carrier-merge, JSON union-merge via embedded `jq`, path-aware backup routing, hash-compare sync, and orphan scan + prune. The script works but is brittle and not testable. Per `AGENTS.md` ("Python over Bash — any logic that needs good testing needs to be in Python"), the file is overdue for a port.

This rewrite is also the **first Python subproject** in what is becoming a modular monorepo: the repo will host multiple Python projects (and some non-Python tool-config trees) over time, so the installer's layout is designed to be the template the next subproject follows.

The rewrite ships **alongside** install.sh during the implementation phase. install.sh remains the parity reference until the golden-master suite goes green; once parity is established, install.sh collapses to a thin `uv run` wrapper. The golden-master suite is **transitional** — once parity is proven and the Python implementation has earned its miles, golden-master retires and divergence (including deliberately fixing install.sh bugs in the Python code) is welcome.

User-locked constraints:

1. **Hybrid fidelity (initial)** — observable install output is byte-identical to install.sh at the parity gate; thereafter, deliberate divergence is allowed (and expected, e.g. when the Python code fixes a latent install.sh bug). Internal mechanics may refactor freely.
2. **Interactive UX preserved but abstracted** — every prompt, diff, and confirmation matches install.sh user-side; all I/O routes through a single `IOPort` protocol so tests inject a scripted fake.
3. **Side-by-side during rollout; install.sh becomes a uv wrapper at the parity gate** — install.sh is not deleted, but its 1788 lines collapse to `exec uv run ...`.
4. **Tool-agnostic core + tool adapters** — the merge engine, staging engine, and sync engine are pure and tool-agnostic; tool-specific behaviour (OpenCode XDG path, OpenCode skips shared `agents/`, Gemini frontmatter transform, Codex placeholder extensions) lives in per-tool adapter modules behind a `ToolAdapter` protocol.
5. **Merge strategies are separate classes** — append-merge, JSON union, last-wins-warn, fatal, etc., each in its own module under `core/merge/strategies/`, each testable in isolation, dispatched through a registry.

## Architecture

### Repo layout (monorepo-shaped, forward-thinking)

```
/Users/scott/src/projects/agents-config/
├── packages/                                (new — home for Python subprojects)
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
│           ├── unit/   integration/   golden_master/   fixtures/
├── scripts/
│   ├── install.sh                           (today: parity reference; at parity gate: 3-line uv wrapper)
│   ├── install.py                           (new — tiny entry stub: `from installer.cli import main`)
│   └── prune-list                           (legacy; deprecated when installer.toml ships)
├── src/                                     (unchanged — agent-config tree, non-Python)
│   ├── user/   plugins/
└── Makefile                                 (new — top-level dev targets; delegates to per-package targets)
```

The existing `src/user/` and `src/plugins/` agent-config trees stay where they are. They are not Python subprojects; they may eventually migrate under `packages/agents-config/` (or similar) in a separate refactor, but that is out of scope here. The point of introducing `packages/installer/` now is to establish the precedent so the next Python subproject lands in the same shape.

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

The installer is a `uv`-managed Python project. `pyproject.toml` declares deps; `uv.lock` is committed. End users still invoke via `python3 scripts/install.py` (the entry stub picks up the venv via `uv run` under the hood) or, post-parity, the converted `scripts/install.sh` which is just `exec uv run python -m installer "$@"`.

**Python floor:** 3.11 (broad availability; stdlib `tomllib` for reading TOML).

**Runtime deps (targeted, not stdlib-only):**

- `pyyaml` — for the Gemini frontmatter transform. Hand-writing YAML parsing was a previous over-correction; we use the library.
- `tomli-w` — to write `installer.toml` updates (3.11 stdlib reads TOML; it does not write).
- `rich` — pretty diffs, colored output, prompt formatting. Replaces hand-rolled ANSI.

The dependency list is deliberately tight, but we no longer refuse a library that exists and solves the problem.

**Dev deps:** `pytest`, `pytest-xdist`, `ruff`, `mypy` (strict). `uv tool run` is the local invocation pattern.

### Configuration — `installer.toml`

The `scripts/prune-list` text file (current home of retired-path globs) is replaced by structured TOML at `packages/installer/installer.toml`:

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

`scripts/prune-list` remains in tree, read by install.sh during the side-by-side window; the Python installer reads `installer.toml`. At the parity gate, install.sh becomes a uv wrapper and `scripts/prune-list` retires.

### `--dump-stage` flag

A new mode that materialises the in-memory `StagingPlan` to a directory and exits without touching destinations:

```
python3 scripts/install.py --dump-stage /tmp/stage-debug
```

Writes the full plan as a real directory tree (`<dump>/<tool>/...`), prints the dump path, and exits 0. Useful for debugging template flattening, plugin overlay, and collision resolution without committing to a destination write. Mutually exclusive with `--prune`/`--prune-only`.

### `IOPort` protocol

Unchanged from prior design. Single injectable abstraction (`info`/`ok`/`warn`/`err`/`header`/verbose variants/`show_diff`/`confirm`/`confirm_three_way`/`confirm_per_item`/`is_interactive`). Two implementations: `TerminalIO` (real, uses `rich`) and `ScriptedIO` (test). No module reaches for `print`/`input` directly.

### Data model highlights

- `Tool` is an enum for exhaustive type-checking; `ToolAdapter` instances live in a registry keyed by `Tool` value. Plugins are **not** enumerated — they are discovered dynamically by scanning `src/plugins/<name>/` and registered by name string, so adding a plugin requires no code change to `model.py`. `PluginAdapter` instances live in a string-keyed registry. Per-`StagedItem` provenance is tracked via a `Provenance(kind: Literal["tool","plugin"], name: str)` dataclass so tool-vs-plugin origin survives the asymmetry.
- `FileKind` enum mirrors install.sh:486-505; `MergeStrategy` dispatch in `core/merge/registry.py` keys on **`(FileKind, namespace)`** because `NAMESPACED_MD` items need their parent-dir namespace to pick the right strategy (e.g. `(NAMESPACED_MD, "rules")` → append-merge; `(NAMESPACED_MD, "commands")` → fatal). For non-namespaced kinds (`SETTINGS_JSON`, `JSONC`, `TOML`, `OTHER`, `DIR`) the namespace component is unused and the lookup degenerates to a `FileKind`-only key.
- `StagingPlan` is the in-memory replacement for install.sh's temp-dir staging — a `dict[Path, StagedItem]` plus provenance tracking.
- `Orphan` dataclass replaces install.sh's four parallel arrays (`ORPHAN_TOOLS` / `ORPHAN_NS` / `ORPHAN_PATHS` / `ORPHAN_KINDS` at install.sh:1456-1467).
- `Config` is frozen, populated from argv + `installer.toml` + auto-detection probes (which themselves consult adapters).

## Test architecture

Three suites under `packages/installer/tests/`. Target ~120–150 tests, full run under one minute.

### Unit (`tests/unit/`, ~80–100 tests, <2s)

Pure-function tests against the core engine, exercised through a `FakeToolAdapter` so each module tests in isolation. Examples by module:

- `core/templates.py` — directive recognition; ALL-RULES join; trailing-newline preservation; Gemini frontmatter strip + tools-list YAML conversion (the conversion lives in `tools/gemini.py` but the test plugs it into the core).
- `core/merge/strategies/append_rules.py` — empty/non-empty concat; separator placement.
- `core/merge/strategies/json_union.py` — nested dict precedence; array union+dedupe (first-seen order); type mismatch; key only in incoming.
- `core/merge/strategies/fatal.py` — raises with informative message including filenames.
- `core/merge/registry.py` — `(FileKind, namespace)` dispatch correctness (NAMESPACED_MD with namespace "rules" vs "commands" dispatches to different strategies; non-namespaced kinds ignore the namespace); unknown `(FileKind, namespace)` key raises.
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

### Golden-master (`tests/golden_master/`, 6–8 scenarios, ~30s) — **transitional**

The parity safety net for the side-by-side window only. Harness at `tests/golden_master/_runner.py`:

1. Build `tmp_path/repo/` (synthetic or symlinked to real `src/`)
2. Run `bash scripts/install.sh` with `HOME=tmp_path/home_a`
3. Run `python3 scripts/install.py` with `HOME=tmp_path/home_b`
4. Recursive diff with timestamp normalisation (backup filenames)

Scenarios: bare install; pre-existing settings; user-modified skill; `--prune --yes` with orphan; `--prune-only`; plugin overlay; single-tool single-no-plugin; Gemini frontmatter end-to-end.

**Retirement plan:** once parity is confirmed — the full golden-master suite green, install.py run against the maintainer's real home with zero unexpected diffs, and no blocker-severity parity issues — and the maintainer signs off, golden-master moves to a `tests/golden_master/_retired/` directory (or is deleted outright), install.sh collapses to its uv-wrapper form, and the AGENTS.md note about the transitional nature is updated to reflect retirement.

**AGENTS.md update (Milestone 1):** add a short section noting that `packages/installer/tests/golden_master/` is a transitional bash-vs-python parity suite expected to retire once parity is confirmed and the cutover lands. This keeps future contributors from treating it as a permanent fixture.

### Fixture strategy

- `tests/fixtures/states/` — versioned, on-disk, hand-curated snapshots of pre-install user-state (one subdir per scenario). Committed to git so reviewers can inspect them.
- `tests/fixtures/sources/` — synthetic source trees (one per scenario) that exercise specific behaviours without depending on the real `src/user/`.
- Builder functions in `conftest.py` for ad-hoc fixture composition.
- The real `src/user/` is exercised only by Scenario 1 of golden-master.

## CLI surface

Matches install.sh:106-141 plus two additions:

```
--dump-stage <path>     Materialise the in-memory staging plan to <path> and exit
```

`--dump-stage` is mutually exclusive with `--prune` / `--prune-only`. Standard mutual exclusion otherwise preserved.

## Implementation discipline

**Total TDD.** Every story follows the same arc; no production code lands without a failing test that justifies it.

1. **Test plan review** (collaborative, before any code). For the story, we co-author a list of unit and integration test cases — names + brief intent + which fixture or scripted-IO scenario each exercises. The list captures the contract the implementation must satisfy. User signs off on the plan before red-phase work starts.
2. **Red phase.** Implement the tests. No production code yet. Tests fail by definition (modules under test do not exist or do not behave). Commit the red phase.
3. **Green phase.** Write the minimum production code to make the tests pass. No speculative scope, no extra abstractions beyond what the tests require.
4. **Refactor + verify.** Run the verification gate: `quality-reviewer` agent, `simplify` skill, full suite + lint + typecheck green.
5. **PR + parity check.** Where the story has a corresponding golden-master scenario, that scenario passes.

The **test plan is the load-bearing artifact** of each story — it precedes the implementation and survives it as a regression checklist. Test plans live in the story's bead `notes` field (or, before beads are introduced, in a short `TEST-PLAN-<story>.md` colocated with the source).

**Test plan completeness criteria** — before signing off on a test plan, both parties confirm:
- Every public function/class introduced by this story has at least one unit test.
- Every documented behaviour (in this plan or the bead) has a corresponding integration test.
- Failure modes the bash version handles are covered (malformed input, missing files, collisions, non-interactive guard, etc.).
- Each test name names the *contract*, not the implementation (`test_user_settings_keys_are_preserved` not `test_json_union_strategy_invokes_recursive_merge`).

## Implementation sequence (tracer-bullet slices)

Eight epics, 34 stories — each story is independently mergeable, has its own test plan, and lands red-then-green-then-verified. Story IDs (A.1, A.2, …) below map directly to the bead structure planned later (features → **epics** → **stories** → tasks/chores).

### Epic A — Foundation

- **A.1** `packages/installer/` scaffold with `uv`; `pyproject.toml`; `scripts/install.py` stub; CI runs `pytest` / `ruff` / `mypy` on a hello-world test. Deliverable: green CI, no installer behaviour yet.
- **A.2** `core/model.py` — pure dataclasses + enums (`Tool`, `FileKind`, `Provenance`, `StagedItem`, `StagingPlan`, `Orphan`, `IncludeDirective` as a discriminated union of `FileInclude` + `AllRulesInclude`, `Counters`). No `Plugin` enum — see "Data model highlights" for the string-keyed plugin rationale.
- **A.3** `core/io_port.py` — `IOPort` protocol + `ScriptedIO` fake + `TerminalIO` real (rendered via `rich`).

### Epic B — First end-to-end install (claude only, minimal)

- **B.1** `config.py` + `tools/base.py` + `tools/claude.py` + `tools/registry.py`. CLI parses `--tools=`; auto-detects claude; errors on unknown.
- **B.2** Minimal `core/sync.py` — copy one source file to one dest file; hash-compare skip; `--dry-run` honoured.
- **B.3** `.template` suffix strip in staging.
- **B.4** DYNAMIC-INCLUDE file form (`<!-- DYNAMIC-INCLUDE: path -->`).

### Epic C — DYNAMIC-INCLUDE completion + shared content

Stories ordered for monotonic dependency: shared content staging precedes ALL-RULES (which expands from rules already in the plan).

- **C.1** Phase 1–2 equivalent: stage shared content from `src/user/.agents/` (agents, skills, rules) into the claude plan.
- **C.2** DYNAMIC-INCLUDE ALL-RULES (sorted, `\n---\n`-joined, read from staging rules collection).
- **C.3** _Deferred — DYNAMIC-INCLUDE named-RULES._ The data model (A.2) intentionally omits a `NamedRulesInclude` variant; no current use case justifies adding one. Story slot retained for ID stability; downstream prereqs (D.\*, G.6, H.1) have been re-pointed at C.2 so the roadmap is not blocked on this deferred story. Reopen C.3 only if a concrete named-RULES requirement surfaces.

### Epic D — Multi-tool

- **D.1** Codex adapter.
- **D.2** Gemini adapter (no transform yet).
- **D.3** OpenCode adapter (XDG dest, skip shared `agents/`).
- **D.4** Gemini frontmatter transform in `tools/gemini.py` `post_staging_transforms`.

### Epic E — Collision matrix (one strategy per story)

- **E.1** `core/merge/base.py` + `core/merge/registry.py`.
- **E.2** `strategies/append_rules.py`.
- **E.3** `strategies/fatal.py`.
- **E.4** `strategies/json_union.py`.
- **E.5** `strategies/last_wins_warn.py` + `strategies/last_wins_silent.py`.

### Epic F — Plugins

- **F.1** `plugins/base.py` + `plugins/registry.py` + synthetic test-plugin fixture.
- **F.2** Phase 6 plugin overlay (alphabetical, full collision matrix exercised).
- **F.3** Carrier-merge logic via in-memory metadata.
- **F.4** `plugins/beads.py` (`~/.beads/formulas/`, `~/.beads/scripts/` with chmod +x).
- **F.5** `plugins/extensions.py` — plugin-to-base-asset extension via YAML patches. Plugins declare structured YAML patch files in scope-bearing extension directories (`src/plugins/<plugin>/.agents/extensions/*.yaml` for shared scope; `.<tool>/extensions/*.yaml` for tool scope). Each YAML declares a `target-file`, `target-section` (ATX header text or `frontmatter`), `precision` verb (`replace` | `insert_before` | `insert_after` | `prepend` | `append`), and `content`. `apply_extensions()` runs in the orchestrator as Phase 6.5 — after the Phase 6 plugin overlay (so a patch can target plugin-contributed and carrier-merged files) and before `post_staging_transforms` (so the Gemini frontmatter transform sees extension-patched content), once per enabled tool. Includes YAML schema validation, fenced-code-aware section matching, frontmatter targeting with post-patch YAML re-parse, multi-plugin deterministic ordering, and terminal failure modes. Patches mutate `StagingPlan` state: FILE items in place, files inside opaque DIR items via the `dir_overrides` side channel shared with the F.3 carrier-merge. The `merge-and-cleanup` beads cheat block ships as a plugin extension from birth when that skill is implemented (`agents-config-abn9.14`) — no inline block ever existed to extract. Full requirements in `agents-config-w1qls.6.5`.

### Epic G — Operations (backup, prune, debug)

- **G.1** Path-aware backup placement in `core/sync.py`.
- **G.2** `installer.toml` schema + loader.
- **G.3** `core/prune.py` orphan scan.
- **G.4** Interactive prune flow via ScriptedIO (three-way + per-item).
- **G.5** `--prune` / `--prune-only` integration.
- **G.6** `--dump-stage <path>` flag.

### Epic H — Parity gate + cutover

- **H.1** Golden-master harness + first three scenarios (bare install, settings merge, user-modified file).
- **H.2** Remaining golden-master scenarios (prune, prune-only, plugin overlay, single-tool single-no-plugin, Gemini frontmatter).
- **H.3** Parity confirmation — full golden-master suite green; real-home smoke test against the actual repo home with zero unexpected diffs; no blocker-severity parity issues; maintainer sign-off recorded in the bead notes.
- **H.4** `install.sh` collapse to `exec uv run --project packages/installer python -m installer "$@"`; `scripts/prune-list` retired (contents already live in `packages/installer/installer.toml` from G.2).
- **H.5** Docs cleanup — AGENTS.md golden-master retirement note updated; README install instructions updated; `tests/golden_master/` moved to `_retired/` or deleted.

**Initial parity is the baseline, not a permanent constraint.** Once the Python implementation has miles, divergence is welcome — particularly when the Python fixes latent install.sh bugs. The parity gate proves "the rewrite doesn't lose ground"; it does not promise "Python will forever match bash byte-for-byte."

## Dependency graph

Inter-story `blocks` edges drawn exhaustively up front. Each row lists a story's direct prerequisites and (where relevant) sibling stories that can run in parallel. Total edges: 53. Critical path: **A.1 → A.2 → B.1 → B.2 → B.3 → B.4 → C.1 → C.2 → D.2 → D.4 → H.2 → H.3 → H.4 → H.5** (14 stories of strict serial work — derived from the dep table below, where each hop honours a real prereq edge: D.2 prereqs C.2, D.4 prereqs D.2, H.2 prereqs D.4 (and G.5 / F.2 in parallel), H.3 prereqs H.1 and H.2, H.4 prereqs H.3, H.5 prereqs H.4). C.3 used to occupy the C.2 → C.3 → F.2 segment; it is now deferred and downstream stories prereq on C.2 directly, so the path no longer threads through C.3 or F.2 — F.2 remains on a parallel-but-shorter branch (F.1 → F.2 → H.2). Everything else hides inside this calendar time via the parallel fronts below.

C.3 (DYNAMIC-INCLUDE named-RULES) is a placeholder; its row is retained for ID stability but every prior dependent has been re-pointed at C.2 so the deferral does not stall the roadmap.

| Story | Direct prereqs | Parallelisable with |
|---|---|---|
| A.1 | — | — |
| A.2 | A.1 | A.3 |
| A.3 | A.1 | A.2 |
| B.1 | A.2, A.3 | — |
| B.2 | B.1 | — |
| B.3 | B.2 | — |
| B.4 | B.3 | — |
| C.1 | B.4 | — |
| C.2 | C.1, B.4 | — |
| C.3 | _deferred — see story description; no active prereqs_ | _N/A_ |
| D.1 | C.2, B.1 | D.2, D.3 |
| D.2 | C.2, B.1 | D.1, D.3 |
| D.3 | C.2, B.1 | D.1, D.2 |
| D.4 | D.2 | — |
| E.1 | A.2 | A.3, B.\*, C.\* (model-only dep) |
| E.2 | E.1 | E.3, E.4, E.5 |
| E.3 | E.1 | E.2, E.4, E.5 |
| E.4 | E.1 | E.2, E.3, E.5 |
| E.5 | E.1 | E.2, E.3, E.4 |
| F.1 | B.1, A.2 | E.\* |
| F.2 | F.1, E.2, E.3, E.4, E.5 | — |
| F.3 | F.2 | F.4, F.5 |
| F.4 | F.1 | F.3, F.5 |
| F.5 | F.2 | F.3, F.4 |
| G.1 | B.2 | C.\*, D.\*, E.\*, F.\* |
| G.2 | A.1 | most of A.\*–F.\* |
| G.3 | G.2, C.1, F.2 | — |
| G.4 | G.3, A.3 | — |
| G.5 | G.4 | — |
| G.6 | C.2, B.1 | D.\*, E.\*, F.\*, G.{1..5} |
| H.1 | E.4, G.1, C.2 | H.2 (independent scenarios) |
| H.2 | G.5, F.2, F.5, D.4 | H.1 |
| H.3 | H.1, H.2 | — |
| H.4 | H.3 | — |
| H.5 | H.4 | — |

**Widest parallel front:** once Epic A finishes and B.1/B.2 land, the entire collision matrix (E.\*), the three additional tool adapters (D.1/D.2/D.3), backup routing (G.1), and the TOML loader (G.2) can all develop concurrently. Roughly half the stories are co-eligible at this point.

## Work-tracking shape (beads — deferred)

When the user explicitly authorises beads creation, the milestone structure above maps to:

- **Feature** — one bead: "Python installer rewrite (packages/installer/)".
- **Epics** — eight beads, one per Epic A–H.
- **Stories** — 34 beads, one per story (A.1 … H.5); each carries its own test plan in `notes`.
- **Tasks / chores** under each story — typically four: `test-plan-review`, `red-phase`, `green-phase`, `verify-gate`. The test plan is recorded in the story bead before its tasks are filed.

No beads are created until the user explicitly says so. The structure above exists so that mapping is mechanical when the time comes.

## Critical files for implementation

- `/Users/scott/src/projects/agents-config/packages/installer/src/installer/core/model.py`
- `/Users/scott/src/projects/agents-config/packages/installer/src/installer/core/io_port.py`
- `/Users/scott/src/projects/agents-config/packages/installer/src/installer/core/staging.py`
- `/Users/scott/src/projects/agents-config/packages/installer/src/installer/core/merge/registry.py` plus each strategy module
- `/Users/scott/src/projects/agents-config/packages/installer/src/installer/tools/base.py` + per-tool adapters
- `/Users/scott/src/projects/agents-config/packages/installer/tests/golden_master/_runner.py`

Bash behaviour is the initial spec. Key line ranges in `/Users/scott/src/projects/agents-config/scripts/install.sh` to consult during implementation: `106-141` (CLI flags); `268-292`, `296-324` (tool/plugin detection); `415-478` (collision matrix); `486-505` (file classification); `533-599` (carrier-merge); `624-751` (DYNAMIC-INCLUDE); `639-684` (Gemini frontmatter awk); `431-454`, `1306-1330` (JSON union jq); `352-388` (backup routing); `1443-1499` (prune-list); `1505-1543` (orphan scan); `1602-1687` (interactive prune flow).

## Verification

At each milestone:

1. **Unit suite:** `uv run pytest packages/installer/tests/unit -q` — green; coverage ≥90% on touched modules.
2. **Integration suite:** `uv run pytest packages/installer/tests/integration -q` — green; assertions phrased as end-state contracts, not phase mechanics; scripted IOPort scripts fully consumed.
3. **Lint + typecheck:** `uv run ruff check packages/installer && uv run mypy --strict packages/installer/src` — clean.
4. **Golden-master (load-bearing, transitional):** `uv run pytest packages/installer/tests/golden_master -q` — every scenario zero post-normalisation diff.
5. **Smoke test against real home** (parity-gate only): `python3 scripts/install.py --dry-run --verbose` vs `bash scripts/install.sh --dry-run --verbose` against the actual repo; spot-check the preview diffs.
6. **`--dump-stage` sanity** (Milestone 7+): dump the plan; confirm contents match the post-Phase-6.9 expected tree by inspection.

Work is complete for a given milestone when all six steps pass within that milestone's scope.
