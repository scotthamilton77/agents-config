# S2 — Project-Scoped Install: Design

**Status:** draft
**Slice:** S2 of the profiles-only scope-routing rollout
**Bead:** agents-config-viiud
**Elaborates:** `docs/specs/2026-07-06-profiles-scope-routing.md` §8 (Project materialization)
**Depends on:** S1 (`agents-config-uxns2.1.3`, the pure resolver + manifest loader) — landed

## 1. Scope

S2 turns the pure scope-routing resolver landed in S1 into a working install
path and adds project materialization on top of it. Concretely it delivers:

- **manifest additions** to the shipped `profiles.toml`: a `kits/** → project`
  `[scopes]` default and a `beads-kit` profile — neither exists today, and kits
  cannot resolve without them (§2 decision 6);
- a `--project <path>` CLI flag that binds the **project** scope for a run;
- a per-tool `project_namespaces()` capability declaration and a validation
  pass that enforces it;
- a `src/kits/<kit>/` source tree for tool-agnostic, project-relative content,
  with a first inhabitant: the **beads kit** (`.beads/PRIME.md`);
- a project-local install receipt at `<project>/.agents-config/install-receipt.json`
  with its own lock, prune, and uninstall mechanics;
- project profile persistence to `<project>/project-config.toml` `[install]`;
- the detection-suggests-only notice on user-scope runs.

### 1.1 Starting reality

The S1 resolver (`packages/installer/src/installer/core/profiles.py`) is pure and
fully unit-tested but has **zero production callers** — `cli.py` has no
`--profiles` flag and the resolver is not wired into the install pipeline. S2
therefore also performs the **first wiring** of the resolver into the live
install flow. That wiring is deliberately scoped: see §7 (Deferred work).

## 2. Decisions

Settled inputs, not open questions.

1. **Resolver-on for every run; project-only selection UX in S2.** The resolver
   is wired into *every* install (user and project). User runs resolve the
   default `full` profile, which is provably a no-op filter (§6.1). The
   `--profiles` selection surface and profile persistence are honored only for
   `--project` runs in S2. User-scope `--profiles`, user persistence, and the
   `DYNAMIC-INCLUDE-ALL-RULES` exclude-flattening are deferred (§7).
2. **Kit destinations use the tree-mirror convention.** A kit's source layout
   *is* its project-relative destination layout:
   `src/kits/beads/.beads/PRIME.md` → `<project>/.beads/PRIME.md`. No per-kit
   manifest, no per-file frontmatter.
3. **The beads kit v1 ships `PRIME.md` only.** Content adapted from this repo's
   curated `.beads/PRIME.md`, generalized where repo-specific. This repo does
   not dogfood the kit in S2 (a follow-up).
4. **Kits are structurally project-only.** Kit content never installs to user
   space. Beyond the `kits/** → project` default S2 *adds* to `[scopes]`, an
   explicit per-selector override that would route a kit to a non-project scope
   is a fail-loud validation error (§5.6).
5. **Kits materialize whole-route through the plugin-route machinery.** Kit
   content is installed, recorded, and pruned through the *existing*
   plugin-route path (§5.1, §6.2) rather than a bespoke channel — a kit is the
   project-scope mirror of a plugin route. Materialization is **whole-route**: a
   kit route installs its entire source directory; a route runs iff at least one
   of its files appears in the resolved `PROJECT` partition. Per-file kit
   selectors cannot subset a route in v1 (a matching selector promotes to the
   whole route); the `beads-kit` profile selects the whole kit via
   `kits/beads/**`.
6. **S2 edits the shipped `profiles.toml`.** Add `"kits/**" = "project"` to
   `[scopes]` and add `[profiles.beads-kit]` with `include = ["kits/beads/**"]`.
   This is a required S2 change, not a pre-existing state — the parity golden
   (§6.6 test 1) must be re-pinned to account for it (it adds a project-default
   selector and a profile but changes nothing a `full` user run stages).

## 3. Architecture

Project-scoped content is two populations that share one resolver for
*selection* and split into two thin materialization tails.

### 3.1 Where the resolver sits

The resolver is wired into `cli._run` **after** `stage_and_transform` completes —
on the fully transformed per-tool plans, never on raw `build_plan` output. This
placement is load-bearing for the byte-identical-parity invariant (§6.1): the
live staging pipeline is

```
build_plan → overlay_plugins → apply_extensions → flatten_plan_templates → post_staging_transforms
```

Plugin overlay *adds* items to `plan.items` (beads/graphify/codex rules) and
flattening *rewrites/drops* items. Building the universe from `build_plan` output
(pre-overlay) would leave plugin-contributed dest paths out of the universe, and
`filter_plan_to_scope` would then silently drop them from the plan that reaches
`sync_plan`. The universe **must** be projected from the transformed plans so its
key set equals the transformed plans' item set.

### 3.2 Data flow

```
  src/user/.claude/  ─ build_plan ─┐
  + src/plugins/*    (overlay)     │  stage_and_transform (full pipeline)
  + extensions/flatten/transforms  ▼
                    transformed per-tool StagingPlans
                                   │ project_universe(transformed_plans)
                                   │   keys: skills/x, agents/y … (tool refs)
                                   ▼
  src/kits/<kit>/   ┌──────────────────────────────────────┐
  (NEW tree)        │ stage_kits(kits_root) ──► kit refs     │ kit_universe(refs)
                    │   UniverseRef(tool=None, dest_relpath) │   keys: kits/beads/… (refs)
                    └──────────────┬─────────────────────────┘
                                   ▼
                merged universe: dict[selector → [ref…]]   (tool refs ∪ kit refs)
                                   │
              resolve(manifest, selection, universe, bound_scopes)
                (pure; one-line sort-key fix for tool=None — §4.1)
                                   │
                       ResolvedPlan.included[scope] = [refs…]
                                   │
       ┌───────────────────────────┴───────────────────────────┐
  USER run (bound {USER})                        PROJECT run (bound {PROJECT})
  install_pipeline(home=~)                       ── the user tool sync and
   + install_plugin_routes(home=~)                  install_plugin_routes are
                                                     NOT run (§5.1, §6.1) ──
                                                 tool tail:  filter_plan_to_scope
                                                   + sync_plan(adapter, home=<p>)
                                                   → <p>/.claude/<ns>/
                                                 kit tail:   for name in selected_kits:
                                                   sync_routes(kit_routes[name])
                                                     (dest_dir baked into each route)
                                                   → <p>/.beads/PRIME.md
                                                   entries_from_route_outcomes(
                                                     plugin=f"kit:{name}")  # per kit
                                                 one receipt @ <p>/.agents-config/
```

### 3.3 Why kits are not just another namespace

For a *tool* item, the selector key **is** the normalized destination path — a
skill stages as `dest_relpath = skills/brainstorming` and the selector
`skills/brainstorming` matches it directly. Source layout, destination layout,
and selector vocabulary coincide.

Kits break that coincidence in two places, which is why they are a separate
channel:

1. **Selector ≠ destination.** The beads kit's selector is `kits/beads/**`
   (source-tree-relative, under `src/kits/`), but its destination is
   `.beads/PRIME.md` (project-root-relative). The existing selector-key
   derivation (`_selector_key`) reads the selector *from* the destination; kits
   cannot, so they carry both paths explicitly.
2. **Verbatim destination.** `_selector_key` strips `.md`/`.template` for
   namespaced items. `PRIME.md` is consumed verbatim by `bd prime`; its name and
   bytes must be preserved. The route path (§5.1) installs verbatim names,
   matching this requirement exactly.

## 4. Ref shape and staging

### 4.1 `UniverseRef.tool` becomes nullable

```python
@dataclass(frozen=True, slots=True)
class UniverseRef:
    tool: Tool | None   # None ⇒ tool-agnostic kit ref; materialize at the project root
    dest_relpath: Path
```

`tool=None` means the ref materializes at the project root, not under a tool
subtree. A single nullable is preferred over a distinct `KitRef` union: the pure
resolver treats refs opaquely — it groups by selector key and partitions by
scope — so a nullable flows through `resolve()` **transparently except for one
line**: the `final_included` sort key currently reads `r.tool.value`
(`profiles.py:447`, the only read of `r.tool` in `resolve()`) and must become
tolerant of `None`
(`(r.tool.value if r.tool is not None else "", r.dest_relpath.as_posix())`).
That is the *only* resolver change S2 makes; a `KitRef` union would instead force
every `ResolvedPlan.included` consumer to pattern-match two types.

Note: `tool=None` is free for the resolver and for materialization dispatch, but
receipt attribution needs a concrete owner string that `None` cannot supply.
That owner is `kit:<name>`, assigned at receipt-build time (§6.2), independent of
the ref's `tool` field.

### 4.2 Staging: `stage_kits` (refs) and `kit_routes` (routes)

Two functions, split by what each needs — mirroring the plugin precedent, where
`PluginAdapter.routes(home)` injects the destination root at call time while the
source layout is fixed:

```python
def stage_kits(kits_root: Path) -> list[UniverseRef]:
    # walks src/kits/<kit>/** ; one UniverseRef(tool=None, dest_relpath=<subpath>)
    # per file, keyed by selector key "kits/<kit>/<subpath>" for the resolver.
    # project-root-independent (refs carry no absolute path).

def kit_routes(kits_root: Path, project_root: Path) -> dict[str, list[PluginRoute]]:
    # keyed by kit name; per kit, one PluginRoute per (destination directory ×
    # exec-bit): source_dir under the kit, dest_dir = project_root/<destdir>,
    # glob selecting that group's files, executable set for the group.
    # Mirrors PluginAdapter.routes(home) but grouped by kit for per-kit owners.
```

`stage_kits` feeds the resolver universe (§4.3). `kit_routes` is called during
materialization for the selected kits (§5.1). Routes are grouped by
`(destination directory × exec-bit)` because a `PluginRoute` applies one
`executable` bit to every file its glob matches (the beads plugin splits
`formulas`/`scripts` for exactly this reason); a single kit directory mixing
executable and non-executable files needs multiple routes. The beads kit is a
single non-executable route (`src/kits/beads/.beads/*` → `<project>/.beads/`).

**Kit identity.** A kit's name is the directory name directly under `src/kits/`,
which is also the second segment of its selector key `kits/<name>/<subpath>`.
Both the selector side (`stage_kits`, which builds the universe keys) and the
materialization/receipt side (`kit_routes`' dict key, the `kit:<name>` receipt
owner, and the prune desired-keys) derive the name from that one source via a
single shared helper, so the `kit:<name>` owner string is provably byte-stable
across an install run and a later prune run.

A missing `src/kits/` yields nothing from both. Two kit sources resolving to the
same destination is a fatal error naming both source paths.

### 4.3 `kit_universe` and merge

`kit_universe(stage_kits(kits_root))` groups the kit refs by selector key into
`dict[str, list[UniverseRef]]`. The caller merges it with
`project_universe(transformed_plans)` and hands the union to `resolve()`. Kits
ride the resolver for **selection** only.

## 5. Materialization, capability matrix, and enforcement

### 5.1 The two tails and the run fork

`cli._run` forks on the scope binding. This fork is the largest implementation
surface and is stated explicitly so two implementers build it identically:

- A **user run** performs the existing `install_pipeline(home=~)` (tool sync) and
  `install_plugin_routes(home=~)` (plugin routes), unchanged — except each tool
  plan is first narrowed by `filter_plan_to_scope` to the `USER`-bound refs
  (which, for the forced-`full` profile, is the whole plan — §6.1 parity).
- A **project run** does **not** run the user tool sync or `install_plugin_routes`
  at all (running either against `home=~` would write user space, violating §5.5;
  against `home=<project>` would leak user-scope plugin content into the project).
  It runs only two project tails, both under the project receipt lock:
  - **Tool tail** (`tool != None` refs): `filter_plan_to_scope(plan, kept)`
    narrows the transformed `StagingPlan` to the project-bound refs, then
    `sync_plan(adapter, filtered_plan, home=<project_root>)` writes them. Because
    `dest_dir(base) → base/".claude"` is parameterized on its base, the project
    root yields `<project>/.claude/<ns>/`. Recorded via `entries_from_outcomes`,
    called with `dest_root=<project>/.claude` (drives the `PRUNE_NAMESPACES` filter
    on `o.dest.relative_to(dest_root)`) and `home=<project_root>` (drives the
    project-relative recorded entry path).
  - **Kit tail** (`tool == None` refs): the caller determines which kits are
    selected by cross-referencing the retained kit-universe map (selector key
    `kits/<name>/…` → refs) against `included[PROJECT]` — a kit is selected iff at
    least one of its refs' `dest_relpath`s is in `included[PROJECT]`. For each
    selected kit, `kit_routes(kits_root, project_root)[<name>]` gives its routes
    (destination already baked into each route's `dest_dir`), `sync_routes`
    installs them, and the writes are recorded with **that kit's** owner via
    `entries_from_route_outcomes(outs, plugin=f"kit:{name}", home=<project_root>)`
    — one call per kit, since the API takes one owner per call. This reuses the
    plugin-route path wholesale: verbatim names, `.beads`-rooted entries
    (`route_entry_for` derives the root from the file's parent under the base →
    `.beads`), consent-gated overwrite, and prune tracking — the same machinery
    that installs the beads plugin's `~/.beads/formulas` on the user side.

### 5.2 `project_namespaces()` capability matrix

Added to the `ToolAdapter` Protocol (it does not exist today) and all four
adapters:

| Tool | `project_namespaces()` |
|---|---|
| Claude | `("skills", "agents", "commands")` — land under `<project>/.claude/<ns>/` |
| Codex | `()` |
| Gemini | `()` |
| OpenCode | `()` |

Capability facts live in code as data; routing *preferences* live in the
manifest. Because `[scopes]` defaults skills/agents/commands to `user`, a
tool-scoped namespace reaches project scope only via an explicit per-selector
scope override in a profile.

### 5.3 Instructions and settings are never project-routable

Enforced by the matrix: no adapter lists `instructions` or `settings`. A
project's `CLAUDE.md`/`AGENTS.md` and settings are project-authored artifacts the
installer must not collide with.

### 5.4 Validation passes

Two capability checks sit outside the pure resolver (which stays
selector-agnostic):

- **Tool-namespace (post-resolve).** For each **tool** ref in
  `ResolvedPlan.included[PROJECT]`, assert its namespace (`dest_relpath.parts[0]`)
  is in that adapter's `project_namespaces()`, else error naming tool + namespace.
  Tool refs routed to project are present in `included[PROJECT]` carrying tool and
  destination, so this check has the identity it needs.
- **Kit-scope (pre-resolve — §5.6).** The mirror check for kits *cannot* run over
  `ResolvedPlan`: a kit wrongly routed to a non-project scope is dropped by
  `resolve()` into an anonymous `dropped_counts` tally, losing its selector
  identity, so a post-resolve pass could neither see nor name it. The kit-scope
  guard therefore runs before `resolve()` — see §5.6.

### 5.5 One binding per run

Per §7 of the parent spec, a run has exactly one primary scope binding. A
`--project` run binds `PROJECT` and does **not** bind `USER`; it structurally
cannot write user space (§5.1 fork). There is thus no dual-scope run, no
receipt-lock nesting, and no lock-ordering hazard — a run holds exactly one
receipt lock, and the project run's tool tail and kit tail both write under it
and feed one receipt (§6.2).

### 5.6 Kit scope enforcement (pre-resolve guard)

Kits are structurally project-only. The only way a kit reaches a non-project
scope is an explicit per-selector override in a selected profile (including a
user-authored `~/.agents/profiles.toml`), e.g.
`{ select = "kits/beads/**", scope = "user" }` — the shipped `kits/** → project`
default cannot be overridden by `[scopes]` (user manifests may not declare
`[scopes]`).

The guard runs in the orchestrator layer **before `resolve()`**, where selector
identity still exists: for each `IncludeEntry` of the selected profiles that
carries an explicit non-`PROJECT` `scope`, if its `selector` matches any key in
the kit universe (via `_selector_matches`), raise a fail-loud error naming the
selector. Running pre-resolve is required because `resolve()` discards the
identity of dropped refs (§5.4), and it makes the error fire regardless of
whether other project content coexists in the run. This mirrors the
"instructions/settings are never project-routable" guardrail and keeps a clean
boundary: plugin routes carry user-space out-of-tree content; kits carry
project-space out-of-tree content.

## 6. CLI, binding, receipt, collisions, errors

### 6.1 Scope binding

`--project <path>` sets the run's scope binding. `<path>` must already exist and
be a directory — a missing path or a non-directory is a fail-loud error naming
the path (§6.5). Write permission is not pre-checked; a non-writable destination
surfaces through the existing OS-error/consent path like any other write. The
installer does not require `<path>` to look like a project (no `.git`/
`project-config.toml` precondition); detection (§6.4) only *suggests*.

One resolver, a scope-parameterized fork (§5.1):

| Facet | User run (no `--project`) | Project run (`--project <p>`) |
|---|---|---|
| `bound_scopes` | `{USER}` | `{PROJECT}` |
| Selection | forced `full`; `--profiles` rejected (§6.5) | `--profiles` CSV → else persisted `[install]` in `<p>/project-config.toml` → else error |
| Universe | `project_universe(transformed_plans)` | same **+** `kit_universe(stage_kits())` |
| Tool sync | `install_pipeline(home=~)` | filtered `sync_plan(home=<p>)`; user `install_pipeline` **not** run |
| Out-of-tree content | `install_plugin_routes(home=~)` | kit routes only; `install_plugin_routes` **not** run |
| Receipt + lock | `~/.config/agents-config/install-receipt.json` | `<p>/.agents-config/install-receipt.json` (own `.lock`) |
| Persistence | none in S2 (deferred) | chosen profiles → `<p>/project-config.toml [install]` (see below) |

The user run's forced-`full` resolution matches `**`, routes everything to its
`user` default, drops nothing, and is byte-identical to today's install. This is
the safety invariant behind the resolver-on decision, guarded end-to-end by the
parity test (§6.6 test 1).

**Universe-coverage coupling.** Wiring the resolver into every run makes it a hard
requirement that every *universe key* has a `[scopes]` (or explicit) match —
`resolve()` raises `ProfilesError` otherwise. Universe keys are exactly the
namespaces that appear in a transformed tool `StagingPlan` (`TOOL_SCOPED ∪
SHARED`) plus the synthetic `instructions`/`settings`. This is **not**
`namespaces.ALL`: `formulas` is in `ALL` but is plugin-routed (installed via a
`PluginRoute`, never staged into a `StagingPlan`), so it never becomes a universe
key and correctly has no `[scopes]` entry. §6.6 test 2 guards coverage of the
*universe-eligible* set (`TOOL_SCOPED ∪ SHARED ∪ {instructions, settings}`), not
`ALL`, so a future *staged* namespace added without a `[scopes]` entry fails in
CI rather than in users' installs. The namespace-addition checklist gains one
edit — a `[scopes]` entry — only when the new namespace is staged (not
plugin-routed).

**Persistence.** On a successful, non-`--dry-run` project run, the resolved
profile set is written to `<p>/project-config.toml` under `[install]` as
`profiles = ["<name>", …]`, at the same point and under the same gating as the
project receipt write (after materialization succeeds, inside the project lock).
`--dry-run` never writes `project-config.toml`. A bare `--project <p>` re-run
with no `--profiles` reads this persisted set (§6.1 Selection); `--profiles`
overrides it and re-persists.

**Flag interactions.** `--tools` continues to gate which tool plans are staged
and therefore which tool refs feed `project_universe`; kit staging is unaffected
(kits are tool-agnostic). A project profile whose selector targets a tool
excluded via `--tools` resolves to nothing and fails loud as a dead selector — S2
adds no distinct message for that mismatch. `--dump-stage` under `--project`
requires a **new** kit-ref rendering (dest path + owner, no content) added
alongside `dump_plan`'s tool-plan tree output, since kit refs never enter a tool
`StagingPlan`; the resolver and kit staging run before the dump branch so the
listing reflects the resolved project plan. `--prune`/`--prune-only` operate
against the project receipt when `--project` is set (§6.2).

### 6.2 Project receipt and prune

The project receipt reuses the `Receipt` schema, `read_receipt`/`write_receipt`/
`merge_receipt`, and `receipt_lock` unchanged, at
`<p>/.agents-config/install-receipt.json` with its own sibling `.lock` and
entries anchored project-root-relative. It records both populations in one
receipt under one lock:

- **Tool entries** via `entries_from_outcomes` (namespace-rooted paths pass the
  `PRUNE_NAMESPACES` filter).
- **Kit entries** via `entries_from_route_outcomes` with owner `kit:<name>` — a
  non-tool owner, exactly like a plugin owner.

**No change is needed** to `scope_owners` (its `retired_plugin_owners` union
already re-includes any non-tool owner found in the prior receipt) or to
`validate_entry` (its non-tool-owner allowlist branch already accepts a `.beads`
root). The two seams that **do** need wiring:

- `record_receipt` (`core/run.py`) gains a kit-outcomes input; the kit route
  entries are appended to the flat `installed` list before `merge_receipt`.
- `prune_pipeline` (`core/run.py`) — **not** `record_receipt` — is where orphan
  detection lives. Today it computes the desired route set via
  `desired_route_keys(plugins, home)`, which iterates `PluginAdapter.routes()`;
  kits are not plugins, so with no change the kit desired-set is empty and a
  still-selected kit's just-installed file is flagged an orphan and pruned. S2
  gives `prune_pipeline` the selected kits' routes (per §5.1) feeding a
  `desired_route_keys`-shaped set, keyed by the same `kit:<name>` owner helper the
  record side uses (§4.2) so install-side and prune-side owners provably match,
  and seeds `live_roots_by_owner["kit:<name>"]`. Selected-kit files are thus
  desired (not orphaned) and a *deselected* kit's files are detected as orphans
  and pruned. The user receipt is never read or written by a project run, and
  vice versa.

### 6.3 Collision handling

Kit content installs through `sync_routes`, inheriting its skip-if-identical /
back-up-before-overwrite / consent behavior — so an existing project file (e.g. a
repo's hand-authored `.beads/PRIME.md`) is backed up and the overwrite is gated
exactly like any other write. Kits never touch the staging **merge registry**
(consulted only by `_add_item` in base staging and `overlay.py::_place` in plugin
overlay — phases kits never enter). Tool-scoped project content reuses
`sync_plan`, inheriting its merge and consent behavior unchanged.

### 6.4 Detection-suggests-only

On a **user** run, if the working directory shows a `.beads/` directory *or* a
`project-config.toml` carrying an `[install]` table, the installer prints exactly
one advisory line via `io.info`, after the install summary:

> This looks like a project. To install project-scoped content here: `install.sh --project .`

No prompt, no write, no scanning beyond the working directory. A `--project` run
prints no suggestion.

### 6.5 Error taxonomy

All fail-loud; every message names the offender.

| Case | Where | Message shape |
|---|---|---|
| `--profiles` without `--project` | cli, pre-resolve | "`--profiles` requires `--project` in this version" |
| `--project <path>` missing or not a directory | cli, pre-stage | names the path |
| Project run, no `--profiles` and no persisted set | pre-resolve CLI guard (see note) | "project install needs an explicit profile (no implicit full)" |
| Selected profiles → empty project partition | resolve (step 8 today) | "the run would do nothing; no content bound to project" |
| Tool ref → project, namespace ∉ `project_namespaces()` | post-resolve validation | names tool + namespace |
| Kit selector overridden to non-`PROJECT` scope | pre-resolve guard (§5.6) | names the selector |
| Two kit sources → same destination | `stage_kits`/`kit_routes` | names both source paths |
| Concurrent project install | project `receipt_lock` | `ReceiptLockBusy` |

Note: the "no implicit full for a project run" rule is enforced as a **pre-resolve
CLI/orchestrator guard**, not inside `resolve()` — `resolve()` today defaults an
empty selection to `["full"]` with no `bound_scopes`-aware branch, and S2 does not
add scope-aware defaulting to the pure resolver. The CLI decides the selection
(explicit `--profiles` → persisted set → error for a project run) *before*
calling `resolve()`.

### 6.6 Testing strategy

Behavioral contracts per the parent spec §10 conventions — ScriptedIO fakes,
temp trees, no live installs.

1. **End-to-end parity (non-negotiable):** a no-flag user install through the
   newly-wired resolver (inserted after `stage_and_transform`) is byte-identical
   to today's install, including plugin-overlaid content, and unaffected by the
   added `kits/**` scope and `beads-kit` profile.
2. **Universe-coverage guard:** the `[scopes]` selectors cover the
   universe-eligible namespace set `TOOL_SCOPED ∪ SHARED ∪ {instructions,
   settings}`, so a future *staged* namespace without a `[scopes]` entry fails in
   CI. The guard must not require a `formulas` entry (plugin-routed, never a
   universe key).
3. `stage_kits`/`kit_routes`: tree-mirror destination; verbatim name (PRIME.md
   stays PRIME.md); source-relative selector key; recursive walk; route grouping
   per (destination directory × exec-bit); executable-bit carry; empty on missing
   `src/kits/`.
4. Integration: `--project p --profiles beads-kit` writes `<p>/.beads/PRIME.md`;
   `--project p --profiles sdlc` errors (empty project partition).
5. Kit-scope guard: a selected profile with `{ select = "kits/**", scope = "user" }`
   errors pre-resolve, naming the selector.
6. `project_namespaces()` matrix: a Claude skill → project works; a namespace →
   project for an unsupporting tool errors naming both.
7. Project receipt round-trip: install → prune → uninstall against a temp project
   tree; a re-install of a still-selected kit does **not** prune its file; a beads
   kit dropped from a later selection **is** pruned as an orphan; the user receipt
   is untouched throughout.
8. Persistence round-trip: `--project p --profiles beads-kit` writes
   `[install] profiles = ["beads-kit"]` to `<p>/project-config.toml`; a bare
   `--project p` re-run reads it; `--project p --profiles beads-kit --dry-run`
   writes no `project-config.toml`.
9. Detection-suggestion: a user run in a cwd with `.beads/` prints exactly one
   line; a `--project` run prints none.
10. Overwrite: a kit install over an existing `.beads/PRIME.md` backs it up and
    respects `--yes` / prompt.
11. `--project p --profiles beads-kit --dry-run` previews would-be writes via
    `io`, creates no files, and leaves no `.agents-config/install-receipt.json`
    or `.lock` under `<p>`.
12. `--project` path missing / not a directory errors naming the path.
13. `--dump-stage` under `--project` lists kit refs (dest + owner) alongside tool
    refs.

## 7. Deferred work (non-goals for S2)

The resolver-on decision intentionally leaves user-scope *selection* unwired.
These move to a dedicated successor slice (§8):

- `--profiles` honored on **user** runs (user-scope filtering end-to-end);
- user-scope profile persistence at `~/.agents/agents-config.toml`;
- the `DYNAMIC-INCLUDE-ALL-RULES` vs `DYNAMIC-INCLUDE-RULES` exclude-flattening
  boundary in `templates.py` (flagged by S1's test docstring as belonging to the
  orchestrator-wiring slice) — required so a user-scope exclude actually removes
  a rule from the rebuilt instruction file, not only its standalone copy.

Also out of scope: dogfooding the beads kit into this repo (decision 3); any kit
beyond beads; a kit directory with **mixed** exec bits (v1 groups routes per
(dir × exec-bit), which handles it, but only the single-route beads case is
exercised); `installer.toml` `tool_dest_overrides` retirement (S3,
`agents-config-uxns2.1.2`, independent).

## 8. Continuations

Work items to mint when this design's PR merges (children under the still-open
`agents-config-uxns2.1` profiles container; release the S2 claim only after
minting):

- **S2.5 — user-scope profile selection wiring.**
  *Acceptance:* `--profiles` filters content on user runs; excluded rules are
  removed from rebuilt `DYNAMIC-INCLUDE-ALL-RULES` instruction files (not only
  their standalone copies); the chosen set persists to
  `~/.agents/agents-config.toml` and is re-read on a subsequent user run;
  `make ci-installer` green.
  *Graph:* child of `agents-config-uxns2.1`; **depends-on** `agents-config-viiud`
  (S2). No child→parent `blocks` edge.

- none further — S3 (`agents-config-uxns2.1.2`) already exists and is independent.
