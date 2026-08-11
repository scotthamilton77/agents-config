# Python Installer — C4 Level 3: Engine

> **Up**: [index](index.md)
> **Previous (reading order)**: [Sequences](sequences.md)
> **Next (reading order)**: [Data View](data-view.md)
> **Source item**: `agents-config-w1qls.9` — archive-era, resolvable in the private archive repository and not through `work`
> **Source spec**: [`installer-design.md`](installer-design.md) — §"Package layout", §"Data model highlights"
> **Container**: the `installer` process (see [`c4-l2-container.md`](c4-l2-container.md))

## Glossary

| Term | Meaning |
|---|---|
| `core/` | The pure, tool-agnostic engine. Knows nothing about any specific tool; parameterised by a `ToolAdapter` and a source root. Fully unit-testable against a private per-file test double (e.g. `_IdentityAdapter`). |
| `orchestrator` | `orchestrator.py`'s `stage_and_transform` — staging only: per active tool, drives build_plan → plugin overlay → merge-on-collision → post-staging transforms, returning every tool's finished plan. `cli.py`, not `orchestrator.py`, is the true top-level controller — it calls `stage_and_transform` once, then separately drives sync and prune via `core/run.py`. |
| `ToolAdapter` | Protocol abstracting per-tool behaviour: `name`, `source_dir`, `dest_dir`, `is_detected`, `scoped_namespaces`, `project_namespaces`, `should_install_namespace`, `post_staging_transforms`. One implementation per tool. |
| `PluginAdapter` | Protocol for an optional plugin overlay. String-keyed registry; dynamically discovered by scanning `src/plugins/`. |
| `MergeStrategy` | Collision-resolution protocol; one class per strategy module; dispatched by the registry on `(FileKind, namespace)`. |
| `IOPort` | The single I/O abstraction. `TerminalIO` (real, via `rich`) and `ScriptedIO` (test fake) are the two implementations; no other module calls `print`/`input`. |
| Protocol seam | A `typing.Protocol` boundary (`ToolAdapter`, `PluginAdapter`, `MergeStrategy`, `IOPort`) across which tests substitute a fake. The four seams are what make the engine unit-testable in isolation. |

## Purpose

Open the `installer` process boundary and show its components. Answers: *what code inside the process actually does the work, how is the tool-agnostic core kept separate from tool/plugin specifics, and where are the seams a test substitutes a fake across?*

This is the most-detailed structural artifact in the set. It is the L3 zoom to read alongside the module being changed — staging, a merge strategy, the plugin overlay.

## Diagram

```mermaid
C4Component
    title Python Installer — internal components (C4 L3)

    Person(operator, "Operator")

    Container_Boundary(proc, "installer process") {

        Component(cli, "cli.py", "Python", "The real top-level controller: resolve tools/plugins; load .installignore; drive orchestrator.stage_and_transform, then run the admission gate (deploy_gate.py), then core/run.py's install_pipeline / install_plugin_routes / deploy_clis / prune_pipeline / prune_clis / record_receipt directly. Wires IOPort (TerminalIO). Enforces --dump-stage vs --prune/--prune-only mutual exclusion; catches ConsentRequiredError as exit 1. The --project fork bypasses the gate by design.")
        Component(config, "config.py", "Python", "Frozen Config dataclass (home, tools, auto_yes — the only fields today) plus resolve_tools / resolve_plugins for auto-detection, called once up front by cli.py. Does NOT load installer.toml — core/installer_toml.py's loader is parsed but unwired (see data-view.md).")

        Container_Boundary(core, "core/ — pure, tool-agnostic engine") {
            Component(orch, "orchestrator.py", "Python", "stage_and_transform: per active tool, build_plan -> overlay_plugins -> apply_extensions -> flatten DYNAMIC-INCLUDE -> adapter.post_staging_transforms; returns every tool's finished StagingPlan to cli.py in one call. Does NOT sync or prune — see sequences.md Sequence 1.")
            Component(model, "model.py", "Python", "FileKind, StagedItem, StagingPlan, Provenance, Orphan, IncludeDirective (FileInclude | AllRulesInclude | NamedRulesInclude), Counters, Tool enum. No behaviour — pure data.")
            Component(ioport, "io_port.py", "Python", "IOPort protocol + TerminalIO (rich) + ScriptedIO (test). The only place stdin/stdout is touched.")
            Component(templates, "templates.py", "Python", "DYNAMIC-INCLUDE flattening: file form, ALL-RULES form, and named-subset form (sorted or listed-order, joined with --- separators).")
            Component(staging, "staging.py", "Python", "Source-walk -> StagingPlan (Phases 1-5), parameterised by a ToolAdapter. Strips .template suffix; scopes namespaces; consults .installignore.")
            Component(ignore, "installignore.py", "Python", "Loads .installignore, the shared exclusion manifest staging.py and overlay.py both consult. Missing/unreadable/non-UTF-8 is a HARD ERROR (cli.py exit 2) — load-bearing policy, not an optional default.")
            Component(overlay, "overlay.py", "Python", "Phase 6: overlay_plugins — merges each active plugin's content onto the base plan, alphabetical plugin order. Carrier-merges a plugin's disjoint files into a shared_carrier skills/agents DIR; every other collision routes through the merge registry (DIR is fatal).")
            Component(sync, "sync.py", "Python", "Phase 7: require_consent guard -> hash-compare -> diff -> confirm -> path-aware backup -> write. Reports per-item InstallOutcome (WRITTEN / SKIPPED_IDENTICAL / DECLINED). Honours --dry-run.")
            Component(consent, "consent.py", "Python", "require_consent: hard-fails a non-interactive run (stdin AND stdout both must be TTYs; either alone is not enough) that passes neither --yes nor --dry-run, before any write. Raises ConsentRequiredError, caught by cli.py as exit 1. Five call sites: sync.py x2, run.py x3.")
            Component(run, "run.py", "Python", "Run-level composition, called directly by cli.py after staging finishes for every tool, in order: install_pipeline + install_plugin_routes (the plugin-route analog: the destinations an adapter claims outside any tool tree) -> deploy_clis (the CLI-deploy stage: uv tool install/uninstall for every console script the CLI_PACKAGES registry names) -> optional prune_pipeline (diff -> partition -> run_prune) -> optional prune_clis -> record_receipt, unconditionally on any non-dry-run install (mirrors disk, now including cli deploy/prune outcomes).")
            Component(clis, "clis.py", "Python", "CLI_PACKAGES registry, each entry pairing a uv tool name with the console script it provides, + RETIRED_CLIS allowlist; cli_source_digest (deployable-source hash); the CliDeployPort protocol + UvCliDeploy (real, the only module that shells out for CLI deploys) + ScriptedCliDeploy (test fake).")
            Component(receipt, "receipt.py + receipt_store.py + receipt_lock.py", "Python", "Receipt / ReceiptEntry model + canonical serialization + integrity digest; read (MISSING vs CORRUPT) / atomic write; single-writer advisory flock on a non-dry-run install (--dry-run takes no lock).")
            Component(rdiff, "receipt_diff.py + receipt_build.py", "Python", "scope_owners + validate_entry + diff_orphans -> Orphan list; desired_staged_keys / desired_route_keys, entry builders, merge_receipt.")
            Component(phash, "prune_hash.py", "Python", "is_safe_to_prune + partition_file_orphans: hash/digest/type-aware prune-vs-relinquish, re-checked at the deletion boundary (TOCTOU guard).")
            Component(pflow, "prune_flow.py", "Python", "run_prune — interactive backup + consent (all / one-by-one / cancel or --yes) + delete; revalidate callback at the destructive boundary.")
            Component(ownership, "ownership.py", "Python", "Wholesale-vs-merge-target classifier: which staged items the receipt records.")
            Component(mreg, "merge/registry.py", "Python", "(FileKind, namespace) -> MergeStrategy dispatch. Single lookup table.")
            Component(mbase, "merge/base.py", "Python", "MergeStrategy protocol: merge(existing, incoming) -> StagedItem.")
            Component(strat, "merge/strategies/* (5 modules)", "Python", "append_rules, fatal, json_union, last_wins_warn, last_wins_silent. One class + one test file each.")
            Component(gate, "deploy_gate.py + admission.py", "Python", "run_admission_gate: partitions every staged artifact by its admission-record front matter, weighs the surface budget, and runs the conflict audit over the admitted set. Record-less content is dropped (zero-base); a malformed record, an over-cap surface, or a claim conflict aborts the deploy before any write. Called directly by cli.py, user-home path only.")
            Component(profiles, "profiles.py", "Python", "load_manifest + resolve(): loads profiles.toml and resolves the active profile selection against the staged universe; filter_plan_to_scope narrows every tool's plan to it. Runs on every real user-home install (guarded on a non-empty universe), before the admission gate. --profiles is --project-only, so the user-home selection is always empty today -- a live but no-op filter on that path.")
            Component(kits, "kits.py", "Python", "stage_kits + kit_universe: the --project path's route-declaring adapter analog -- presents each selected kit as an adapter and installs it through run.py's plugin-route pass into the project tree.")
        }

        Container_Boundary(tools, "tools/ — per-tool adapters") {
            Component(tbase, "base.py", "Python", "ToolAdapter protocol.")
            Component(tclaude, "claude.py", "Python", "Claude adapter.")
            Component(tcodex, "codex.py", "Python", "Codex adapter (placeholder extensions).")
            Component(tgemini, "gemini.py", "Python", "Gemini adapter — OWNS the frontmatter transform (post_staging_transforms).")
            Component(topencode, "opencode.py", "Python", "OpenCode adapter — XDG dest + 'skip shared agents/' rule.")
            Component(treg, "registry.py", "Python", "Tool-enum-keyed adapter registry.")
        }

        Container_Boundary(plugins, "plugins/ — per-plugin adapters") {
            Component(pbase, "base.py", "Python", "PluginAdapter protocol.")
            Component(pgeneric, "generic.py", "Python", "GenericPluginAdapter — every discovered plugin's adapter: detects on ~/.<name>/, declares no bespoke routes.")
            Component(pext, "extensions.py", "Python", "apply_extensions(): YAML-patch base markdown assets post-staging.")
            Component(preg, "registry.py", "Python", "String-keyed plugin registry; dynamic discovery via src/plugins/ scan.")
        }
    }

    System_Ext(src_ext, "Source config tree", "src/user/ + src/plugins/ (read-only)")
    System_Ext(dest_ext, "Destination stores", "~/.claude, ~/.codex, ~/.gemini, ~/.config/opencode")
    System_Ext(state_ext, "Install receipt", "~/.config/agents-config/install-receipt.json (+ .lock) — persisted prune authority")
    System_Ext(term_ext, "Terminal", "stdin / stdout — diffs + confirmations")

    Rel(operator, cli, "python3 scripts/install.py ...")
    Rel(cli, config, "resolve_tools / resolve_plugins")
    Rel(cli, ignore, "load .installignore (hard error if missing/unreadable)")
    Rel(cli, orch, "stage_and_transform(tools, plugins) -- builds every tool's plan, whole-fleet, before any sync")
    Rel(cli, profiles, "load_manifest(profiles.toml) + resolve() -- user-home path, before the gate")
    Rel(cli, gate, "run_admission_gate(plans) -- user-home path only; aborts (exit 1) on a violation before run.py is called")
    Rel(cli, kits, "stage_kits + kit_universe -- --project path only")
    Rel(config, treg, "auto-detect tools")
    Rel(config, preg, "discover plugins")
    Rel(config, src_ext, "probe tool config dirs")

    Rel(orch, staging, "per tool: build_plan(adapter)")
    Rel(orch, overlay, "overlay_plugins(plan, plugins) -- Phase 6")
    Rel(orch, pext, "apply_extensions per tool plan")

    Rel(cli, run, "install_pipeline + install_plugin_routes (separate whole-fleet sync pass) + deploy_clis, then optional prune_pipeline + prune_clis, then record_receipt unconditionally on any non-dry-run install")
    Rel(run, sync, "flush each tool's / plugin's plan to dest")
    Rel(run, clis, "deploy_clis / prune_clis over CLI_PACKAGES via the injected CliDeployPort")
    Rel(clis, dest_ext, "uv tool install/uninstall onto PATH (UvCliDeploy)")
    Rel(cli, consent, "catches ConsentRequiredError -> exit 1")
    Rel(overlay, mreg, "collision -> strategy (plugin overlay)")
    Rel(overlay, ignore, "consult exclusion set for plugin namespace walk")

    Rel(staging, src_ext, "walk + read source")
    Rel(staging, templates, "flatten DYNAMIC-INCLUDE")
    Rel(staging, treg, "ToolAdapter behaviour (dest, namespaces, filter)")
    Rel(orch, tgemini, "post_staging_transforms (frontmatter)")
    Rel(staging, model, "build StagedItem / StagingPlan")
    Rel(staging, ignore, "consult exclusion set during namespace walk")
    Rel(staging, mreg, "collision -> strategy (base staging)")

    Rel(pext, preg, "resolve active plugin patches")
    Rel(mreg, strat, "dispatch")
    Rel(mreg, mbase, "protocol")
    Rel(strat, model, "merge StagedItem")

    Rel(sync, consent, "require_consent guard before any write")
    Rel(sync, ioport, "show_diff / confirm")
    Rel(sync, dest_ext, "backup + write")
    Rel(run, rdiff, "diff prior receipt vs desired plan -> orphans")
    Rel(run, phash, "partition orphans (hash/type-aware)")
    Rel(run, pflow, "run_prune confirmed orphans")
    Rel(run, receipt, "read prior / write new receipt (flock-guarded)")
    Rel(pflow, ioport, "confirm prune (three-way / per-item)")
    Rel(pflow, dest_ext, "backup + remove")
    Rel(receipt, state_ext, "read / atomic write install-receipt.json")
    Rel(ioport, term_ext, "stdin/stdout")

    Rel(tclaude, tbase, "implements")
    Rel(tcodex, tbase, "implements")
    Rel(tgemini, tbase, "implements")
    Rel(topencode, tbase, "implements")
    Rel(pgeneric, pbase, "implements")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="2")
```

## Component notes

### Top layer — `cli` / `config`

- **`cli.py`** is the true top-level controller, not just argv parsing: it resolves tools/plugins (via `config.py`), loads `.installignore` (hard error if missing/unreadable — load-bearing policy), calls `orchestrator.stage_and_transform` **once** to build every tool's `StagingPlan` (a whole-fleet pass), runs the admission gate, builds the frozen `Config`, then drives `core/run.py`'s `install_pipeline` + `install_plugin_routes` — a **second, separate** whole-fleet pass that syncs every tool's / plugin's plan to disk — then `deploy_clis` (the CLI-deploy stage, user-home path only), and, if requested, `prune_pipeline` + `prune_clis`, finally `record_receipt`, all under the single-writer receipt lock. It owns argv-level validation (the `--dump-stage` ⊕ `--prune`/`--prune-only` mutual exclusion) and catches `ConsentRequiredError` as exit 1.
- **`config.py`** resolves *what will be installed*: `resolve_tools` (auto-detection — claude always; others when their config dir exists or `--tools=` forces them — note this checks for config **directories**, not running binaries) and `resolve_plugins` (scan `src/plugins/`), both called once, up front, by `cli.py`. The frozen `Config` dataclass itself carries only `home`, `tools`, and `auto_yes` today — see [`data-view.md`](data-view.md) for the full field-by-field accounting, including `installer.toml`'s unwired loader.

### `core/` — the tool-agnostic engine

The engine knows nothing about any specific tool; it takes a `ToolAdapter` and a source root and runs. This is the load-bearing separation in the whole design — it is what lets the bulk of the test suite exercise the engine through a private per-file test double (e.g. `_IdentityAdapter`) without any real tool present (see `installer-design.md` §"Test architecture" for how to get the current count).

- **`orchestrator.py`** (`stage_and_transform`) is staging only, not the full control flow: for each active tool it builds that tool's `StagingPlan` (`core/staging.py`), overlays active plugins (`core/overlay.py`, Phase 6), applies plugin YAML extensions, flattens DYNAMIC-INCLUDE, and runs the tool's `post_staging_transforms` — returning every tool's finished plan to `cli.py` in one call. It does **not** sync or prune; those run directly from `cli.py` via `core/run.py`, as a separate whole-fleet pass over all tools **after** every tool has finished staging (see [`sequences.md`](sequences.md) Sequence 1).

- **`model.py`** is pure data — the enums and dataclasses every other module passes around (detailed in [`data-view.md`](data-view.md)). No behaviour lives here.
- **`io_port.py`** is the I/O chokepoint. `sync` and `prune` reach the terminal only through the `IOPort` protocol; tests inject `ScriptedIO` to drive every prompt deterministically.
- **`templates.py`** does DYNAMIC-INCLUDE flattening. The file form inlines one fragment; the ALL-RULES form expands the staged rules collection sorted + `\n---\n`-joined. The Gemini frontmatter conversion is a separate concern entirely — it **lives in `tools/gemini.py`**, tested in `test_gemini_frontmatter.py`, and never runs through this module; the engine stays tool-agnostic.
- **`staging.py`** (Phases 1-5) walks the source, strips the `.template` suffix, scopes files into namespaces, consults `.installignore`, and builds `StagedItem`s into the `StagingPlan`. It is parameterised by the `ToolAdapter`, never branching on a tool name itself. A same-dest collision within base staging (shared + per-tool content) routes through the merge registry, same as plugin overlay. It does **not** call the adapter's `post_staging_transforms` — that call site is `orchestrator.py` (see above), after overlay and extensions have run.
- **`installignore.py`** loads `.installignore`, the shared exclusion manifest both `staging.py` and `overlay.py` consult while walking a namespace. A missing, unreadable, or non-UTF-8 file is a **hard error** (`cli.py` exit 2) — the manifest is load-bearing policy, not an optional default. A silent empty-exclusion fallback would deploy every namespace's development docs into every destination store, and a run doing that looks exactly like a correct one from the outside.
- **`overlay.py`** (`overlay_plugins`, Phase 6) merges each active plugin's `.<tool>/` (tool scope) and shared `.agents/` content onto the base plan, in alphabetical plugin order so last-wins collisions resolve deterministically. A plugin directory colliding with a `shared_carrier` skills/agents `DIR` carrier-merges when the two directories' file sets are disjoint (recording the plugin's files in `StagingPlan.dir_overrides`); every other collision — including a second plugin landing on an already-merged carrier — routes through the merge registry, where `FileKind.DIR` is fatal.
- **`sync.py`** is Phase 7: `require_consent` guards up front (hard-fails a non-interactive run with neither `--yes` nor `--dry-run`), then for each planned file, hash-compare against the destination; identical → skip; different → diff via `IOPort`, confirm, path-aware backup, write. It reports a per-item `InstallOutcome` (`WRITTEN` / `SKIPPED_IDENTICAL` / `DECLINED`, with the real `sha256`) so the receipt records only what was actually written as our bytes. `--dry-run` short-circuits before any write.
- **`consent.py`** (`require_consent`) is the non-interactive consent guard: raises `ConsentRequiredError` before any write when `io.is_interactive()` is false (stdin **and** stdout must both be TTYs — either one alone does not count) and neither `--yes` nor `--dry-run` was passed. Called from `sync.py`'s `sync_plan`/`sync_routes`, and three more sites in `run.py`: the CLI-takeover consent prompt (`:626`), the PATH `update_shell` prompt (`:719`), and `prune_clis`' retired-uninstall consent (`:778`). `cli.py` catches the exception and exits 1.
- **The receipt-based prune subsystem** is several small, independently-testable engine modules composed in `run.py`:
  - **`run.py`** is the run-level composition, called directly by `cli.py` (not `orchestrator.py`) once staging has finished for every tool, in order — `install_pipeline` (walk every tool's plan to disk), `install_plugin_routes` (the plugin-side analog: walk every active plugin's bespoke routes — the destinations it claims outside any tool tree), `deploy_clis` (the CLI-deploy stage — detailed in the `clis.py` bullet below), optional `prune_pipeline` (diff → partition → `run_prune`), optional `prune_clis`, and finally `record_receipt` (mirror disk into the new receipt) — unconditional on any non-dry-run install, independent of whether pruning ran. `cli.main` holds the single-writer lock across all of it. Every plugin discovered under `src/plugins/` uses the generic adapter, which declares no routes, so on a user install this pass writes nothing and returns an all-zero counters bucket per plugin — the bucket is present so a verbose summary can still print the plugin's block. The machinery has a live caller elsewhere: a `--project` run presents each selected kit as a route-declaring adapter (`core/kits.py`) and installs it through this same pass into the project tree.
  - **`receipt.py` / `receipt_store.py` / `receipt_lock.py`** are the persisted-state layer: the `Receipt` / `ReceiptEntry` model with canonical serialization + `integrity` digest; the store that reads (distinguishing `MISSING` → bootstrap empty from `CORRUPT` → fail closed) and atomically writes; and the advisory `flock` that serializes the whole read → install → prune → write section on a non-dry-run install (`--dry-run` substitutes `nullcontext()` and takes no lock).
  - **`receipt_diff.py`** finds orphans: `scope_owners` (resolved tools ∪ discovered plugins − tool names ∪ prior-receipt plugin owners), `validate_entry` (structural + symlink-aware containment + owner-kind-aware root legitimacy — a tool owner's root must come from live code and is never checked against the allowlist; a plugin owner's root, active or retired, is legitimate via live code **or** the persisted `roots` allowlist), and `diff_orphans` (in scope ∧ not desired ∧ valid → `Orphan`).
  - **`receipt_build.py`** builds the plan-derived `desired_staged_keys` / `desired_route_keys` and the install-outcome-derived `ReceiptEntry` set, and `merge_receipt` produces the mirrors-disk `(prior − pruned − relinquished) | installed`.
  - **`prune_hash.py`** (`is_safe_to_prune` / `partition_file_orphans`) decides prune-vs-relinquish by on-disk hash (files) or recursive content digest / type (dirs), evaluated against the live FS at scan time AND re-checked at the deletion boundary (TOCTOU guard). (Note: `is_prunable` is a different function, in `ownership.py` — the wholesale-vs-merge-target classifier over a `StagedItem`, not this module's prune-vs-relinquish predicate.)
  - **`prune_flow.py`** (`run_prune`) is the unchanged interactive executor: backup-before-delete always, three-way (all / one-by-one / cancel) or `--yes` consent, with a `revalidate` callback enforcing the boundary re-check.
  - **`ownership.py`** is the wholesale-vs-merge-target classifier deciding which staged items the receipt records (never `settings.json` or the assembled instruction files).
  - **`clis.py`** is the CLI-deploy engine's pure/port half: the closed `CLI_PACKAGES` registry, which is its own authority — read it rather than an enumeration here, since a copy of the list goes stale the first time a package graduates. A package earns a place by shipping a real `[project.scripts]` entry point and its own CI gate; being CI-gated alone does not qualify it, and `installer` is the standing counter-example, reached through `scripts/install.sh` rather than from PATH, `RETIRED_CLIS` (the uninstall allowlist), `cli_source_digest` (a deterministic hash over each package's `pyproject.toml` + `uv.lock` + `src/**`, excluding tests/build churn), and the `CliDeployPort` protocol with its `UvCliDeploy` (real, subprocess-only) and `ScriptedCliDeploy` (test fake) implementations. `run.py`'s `deploy_clis` (verify/heal/fresh decision table) and `prune_clis` (allowlist-bounded retirement) drive it inside the same receipt-lock section as the file install/prune, and their outcomes feed `merge_clis` (`receipt_build.py`) into `record_receipt`.
- **`merge/`** is the collision matrix: `registry.py` maps `(FileKind, namespace)` to a strategy; `base.py` is the `MergeStrategy` protocol; `strategies/` holds the five concrete classes, each in its own module with its own test.

### `tools/` — per-tool adapters

One module per tool behind the `ToolAdapter` protocol (`base.py`). Each adapter declares its own `name`, and answers the engine's questions: where is this tool's source, where is its destination, is it detected, which namespaces does it scope, which namespaces a `--project` install may select, should this namespace be installed from this source, and what transforms run post-staging. The non-trivial adapters: **`gemini.py`** owns the frontmatter transform; **`opencode.py`** owns the XDG destination and the "skip shared `agents/`" rule. `registry.py` is the `Tool`-enum-keyed lookup.

### `plugins/` — per-plugin adapters

Plugins sit behind the `PluginAdapter` protocol (`base.py`), **string-keyed** in `registry.py` and discovered dynamically by scanning `src/plugins/` — adding a plugin requires no change to `model.py`. **`generic.py`** holds `GenericPluginAdapter`, the adapter every discovered plugin gets: it detects on the plugin's own `~/.<name>/` footprint and declares no bespoke routes, so its content reaches disk through the per-tool namespace overlay. A plugin needing behaviour that convention cannot express — a detection probe beyond the home footprint, or a destination outside every tool tree — registers a factory in `registry.py`'s specialized-adapter map, which is the named extension point and is empty. **`extensions.py`** (`apply_extensions()`) applies plugin-declared YAML patches to base markdown assets post-staging, once per enabled tool against that tool's plan.

### The four protocol seams

| Seam | Protocol module | What a test substitutes |
|---|---|---|
| Tool behaviour | `tools/base.py` `ToolAdapter` | a private per-file test double (e.g. `_IdentityAdapter`) — exercises the core engine with no real tool |
| Plugin overlay | `plugins/base.py` `PluginAdapter` | synthetic test-plugin fixture |
| Collision resolution | `core/merge/base.py` `MergeStrategy` | swap a registry entry to assert dispatch |
| All I/O | `core/io_port.py` `IOPort` | `ScriptedIO` — drives prompts, records transcript |

Every cross-boundary dependency is one of these four protocols. That is the design's testability contract: no engine module hard-codes a tool, a plugin, a strategy, or a print statement.

## What this diagram does NOT show

- **Execution order across the components** — detect → stage → overlay → merge → profile filter (user-home path) → admission gate (user-home path) → sync → CLI-deploy (user-home path) → optional prune → receipt rewrite is the subject of [`sequences.md`](sequences.md).
- **The data shapes** the components pass around (`StagingPlan`, `StagedItem`, `Config`, …) and the merge-dispatch table — see [`data-view.md`](data-view.md).
- **The per-strategy merge mechanics** (append separator placement, JSON deep-union rules, fatal message format) — specified in `installer-design.md` §"Test architecture".
- **The container boundary + external stores at process granularity** — see [`c4-l2-container.md`](c4-l2-container.md).
- **The repo-side lint/gate CLIs** (`content_lint_cli.py`, `content_tests_cli.py`, `doc_lint_cli.py`, `spec_lint_cli.py`, and their `core/content_lint.py` / `core/content_tests.py` / `core/doc_lint.py` / `core/spec_lint.py` engines) — each is its own entry point under `python -m installer.<name>_cli`, never called from `cli.py`, and never invokes the installer. They are out of scope for this diagram because it is scoped to "the installer process" (`python3 scripts/install.py` / `python -m installer`), which they are not part of; see the `Makefile`'s `content-lint`, `content-tests`, `doc-lint`, and `spec-lint` targets for how they run.

## Cross-references

- **Previous (reading order)**: [Sequences](sequences.md) — the flows these components execute
- **Next (reading order)**: [Data View](data-view.md) — the data these components read / build / write
- **Companion structural view**: [`c4-l2-container.md`](c4-l2-container.md)
- **Source spec**: [`installer-design.md`](installer-design.md) §"Package layout", §"Data model highlights", §"IOPort protocol"
