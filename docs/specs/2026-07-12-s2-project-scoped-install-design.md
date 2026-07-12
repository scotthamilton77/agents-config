# S2 — Project-Scoped Install: Design

**Status:** draft
**Slice:** S2 of the profiles-only scope-routing rollout
**Bead:** agents-config-viiud
**Elaborates:** `docs/specs/2026-07-06-profiles-scope-routing.md` §8 (Project materialization)
**Depends on:** S1 (`agents-config-uxns2.1.3`, the pure resolver + manifest loader) — landed

## 1. Scope

S2 turns the pure scope-routing resolver landed in S1 into a working install
path and adds project materialization on top of it. Concretely it delivers:

- a `--project <path>` CLI flag that binds the **project** scope for a run;
- a per-tool `project_namespaces()` capability declaration and a validation
  pass that enforces it;
- a `src/kits/<kit>/` source tree for tool-agnostic, project-relative content,
  with a first inhabitant: the **beads kit** (`.beads/PRIME.md`);
- a project-local install receipt at `<project>/.agents-config/install-receipt.json`
  with its own lock, prune, and uninstall mechanics;
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
   space. Beyond the `kits/** → project` default in `[scopes]`, an explicit
   per-selector override that would route a kit to a non-project scope is a
   fail-loud validation error (§5.6).
5. **Kits materialize as project-scoped routes; selection is whole-kit.** Kit
   content is installed, recorded, and pruned through the *existing* plugin-route
   machinery (§5.1, §6.2) rather than a bespoke channel — a kit is the
   project-scope mirror of a plugin route. A kit is selected as a unit (a profile
   includes `kits/<kit>/**`); sub-file kit selection is not a v1 use case.

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
  src/kits/<kit>/   ┌──────────────────────────────┐
  (NEW tree)        │ stage_kits() ──► KitStaging   │
                    │  refs:  kits/beads/… (tool=None)│ kit_universe(kits)
                    │  routes: src→<project>/.beads/ │   keys: kits/beads/… (refs)
                    └──────────────┬────────────────┘
                                   ▼
                merged universe: dict[selector → [ref…]]   (tool refs ∪ kit refs)
                                   │
              resolve(manifest, selection, universe, bound_scopes)
                (pure; one-line sort-key fix for tool=None — §4.1)
                                   │
                       ResolvedPlan.included[scope] = [refs…]
                                   │
                   ┌───────────────┴────────────────┐
          tool refs (tool≠None)            kit refs (tool=None)
                   │                                │
   filter_plan_to_scope + sync_plan(        selected kit → Route(s);
     adapter, home=<project_root>)          sync_routes(routes, dest=<project>)
     → <project>/.claude/<ns>/              → <project>/.beads/PRIME.md
                   │                                │
   entries_from_outcomes            entries_from_route_outcomes(owner=kit)
                   └───────────────┬────────────────┘
              one project receipt @ <project>/.agents-config/ (one lock)
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
(`profiles.py:447`) and must become tolerant of `None`
(`(r.tool.value if r.tool is not None else "", r.dest_relpath.as_posix())`).
That is the *only* resolver change S2 makes; a `KitRef` union would instead force
every `ResolvedPlan.included` consumer to pattern-match two types.

Note: `tool=None` is free for the resolver and for materialization dispatch, but
receipt attribution needs a concrete owner string that `None` cannot supply.
That owner is defined in §6.2 (`kit:<name>`), independent of the ref's `tool`
field.

### 4.2 `stage_kits`

`stage_kits(kits_root)` walks `src/kits/<kit>/**` recursively and produces, per
kit:

- **universe refs** — one `UniverseRef(tool=None, dest_relpath=<subpath>)` per
  file, keyed by its **selector key** `kits/<kit>/<subpath>` (source-relative)
  for the resolver;
- **routes** — one `PluginRoute`-shaped route per distinct destination
  directory (routes install a flat file set per directory), with
  `source_dir = <kit>/<destdir>`, `dest_dir = <project>/<destdir>`, a glob
  selecting the kit's files there, and `executable` from the source mode bit.
  The beads kit is a single route (`src/kits/beads/.beads/*` → `<project>/.beads/`).

A missing `src/kits/` yields nothing. Two kit sources resolving to the same
destination is a fatal error naming both source paths.

### 4.3 `kit_universe` and merge

`kit_universe(stage_kits output)` groups the kit refs by selector key into
`dict[str, list[UniverseRef]]`. The caller merges it with
`project_universe(transformed_plans)` and hands the union to `resolve()`. Kits
ride the resolver for **selection** only.

## 5. Materialization, capability matrix, and enforcement

### 5.1 Two tails

`resolve()` returns `ResolvedPlan.included[scope]`, a mix of tool refs and kit
refs. Materialization dispatches on `ref.tool`:

- **Tool refs** (`tool != None`): `filter_plan_to_scope(plan, kept_dest_relpaths)`
  narrows the tool's transformed `StagingPlan` to the project-bound refs, then
  `sync_plan(adapter, filtered_plan, home=<project_root>)` writes them. Because
  `dest_dir(base) → base/".claude"` is parameterized on its base, passing the
  project root yields `<project>/.claude/<ns>/` with no new sync code. Receipt
  entries come from `entries_from_outcomes` (their dest paths are
  namespace-rooted, e.g. `skills/…`, so they pass the `PRUNE_NAMESPACES` filter).
- **Kit refs** (`tool == None`): the selected kit's routes are installed via the
  existing `sync_routes(routes, dest_dir=<project_root>/…)`, and recorded via
  `entries_from_route_outcomes(outs, plugin="kit:<name>", home=<project_root>)`.
  This reuses the plugin-route path wholesale: verbatim names, `.beads`-rooted
  entries (`route_entry_for` computes `root = dest_dir.relative_to(base).parts[0]`
  → `.beads`), consent-gated overwrite, and prune tracking — the same machinery
  that already installs the beads plugin's `~/.beads/formulas` on the user side.

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

### 5.4 Validation pass (post-resolve, not in the resolver)

The pure resolver stays selector-agnostic. A post-resolve validation pass in the
orchestrator/cli layer enforces the capability rules over `ResolvedPlan`:

- For each **tool** ref bound to project scope, assert its namespace is in that
  adapter's `project_namespaces()`, else error naming tool + namespace.
- For each **kit** ref (`tool=None`), assert its assigned scope is `PROJECT`,
  else error naming the selector (§5.6).

### 5.5 One binding per run

Per §7 of the parent spec, a run has exactly one primary scope binding. A
`--project` run binds `PROJECT` and does **not** bind `USER`; it structurally
cannot write user space. There is thus no dual-scope run, no receipt-lock
nesting, and no lock-ordering hazard — a run holds exactly one receipt lock. The
project run's tool tail and kit tail both write under that one lock and both feed
one receipt (§6.2).

### 5.6 Kit scope enforcement

Kits are structurally project-only. Any kit ref (`tool=None`) that resolves to a
non-`PROJECT` scope — reachable only via a hand-authored explicit override such
as `{ select = "kits/beads/**", scope = "user" }` — is a fail-loud validation
error naming the selector. This mirrors the "instructions/settings are never
project-routable" guardrail and keeps a clean boundary: plugin routes carry
user-space out-of-tree content; kits carry project-space out-of-tree content.

## 6. CLI, binding, receipt, collisions, errors

### 6.1 Scope binding

`--project <path>` sets the run's scope binding. `<path>` must already exist and
be a directory — a missing path or a non-directory is a fail-loud error naming
the path (§6.5). Write permission is not pre-checked; a non-writable destination
surfaces through the existing OS-error/consent path like any other write. The
installer does not require `<path>` to look like a project (no `.git`/
`project-config.toml` precondition); detection (§6.4) only *suggests*.

One resolver, a scope-parameterized tail:

| Facet | User run (no `--project`) | Project run (`--project <p>`) |
|---|---|---|
| `bound_scopes` | `{USER}` | `{PROJECT}` |
| Selection | forced `full`; `--profiles` rejected (§6.5) | `--profiles` CSV → else persisted `[install]` in `<p>/project-config.toml` → else error |
| Universe | `project_universe(transformed_plans)` | same **+** `kit_universe(stage_kits())` |
| Dest base | `home` → `~/.claude` | `<p>` → `<p>/.claude` (same `dest_dir` fn) |
| Out-of-tree content | plugin routes (`~/.beads/formulas`) | kit routes (`<p>/.beads/…`) |
| Receipt + lock | `~/.config/agents-config/install-receipt.json` | `<p>/.agents-config/install-receipt.json` (own `.lock`) |
| Persistence | none in S2 (deferred) | chosen profiles → `<p>/project-config.toml [install]` |

The user run's forced-`full` resolution matches `**`, routes everything to its
`user` default, drops nothing, and is byte-identical to today's install. This is
the safety invariant behind the resolver-on decision, guarded end-to-end by the
parity test (§6.6 test 1).

**New coupling from wiring the resolver into every run:** the forced-`full` run
requires that `[scopes]` (plus the synthetic `instructions`/`settings` keys)
matches *every* staged namespace — `resolve()` raises `ProfilesError` if any
universe key has no `[scopes]` match. Today `[scopes]` covers `namespaces.ALL`
plus the synthetics, so parity holds; but a future namespace added to
`namespaces.ALL` without a corresponding `[scopes]` entry would crash *every*
user install. §6.6 test adds a CI guard asserting `[scopes]` coverage of
`namespaces.ALL`. The namespace-addition checklist gains one edit: a `[scopes]`
entry in `profiles.toml`.

**Flag interactions.** `--tools` continues to gate which tool plans are staged
and therefore which tool refs feed `project_universe`; kit staging is unaffected
(kits are tool-agnostic). A project profile whose selector targets a tool
excluded via `--tools` resolves to nothing and fails loud as a dead selector —
S2 does not add a distinct message for the `--tools`/`--profiles` mismatch.
`--dump-stage` under `--project` includes kit refs alongside tool refs (dest
path and owner; content is not dumped), so the dump reflects the resolved project
plan. `--prune`/`--prune-only` operate against the project receipt when
`--project` is set (§6.2).

### 6.2 Project receipt

The project receipt reuses the `Receipt` schema, `read_receipt`/`write_receipt`/
`merge_receipt`, and `receipt_lock` unchanged, at
`<p>/.agents-config/install-receipt.json` with its own sibling `.lock` and
entries anchored project-root-relative. It records both populations in one
receipt under one lock:

- **Tool entries** via `entries_from_outcomes` (namespace-rooted paths pass the
  `PRUNE_NAMESPACES` filter).
- **Kit entries** via `entries_from_route_outcomes` with owner `kit:<name>` — a
  non-tool owner, exactly like a plugin owner. `scope_owners` already unions any
  non-tool owner found in the prior receipt (`retired_plugin_owners`), and
  `validate_entry` already has the non-tool-owner branch, so kit entries are in
  scope for prune with **no change** to `scope_owners`/`validate_entry`/root
  validation (`.beads` is already an accepted route root today).

`record_receipt` gains a kit-outcomes input (route-shaped) whose entries are
appended to the flat `installed` list before `merge_receipt`; the desired-set for
orphan detection includes the selected kits' route keys (a
`desired_route_keys`-shaped set), so a deselected kit's files are detected as
orphans and pruned. The user receipt is never read or written by a project run,
and vice versa.

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
| Kit ref → non-`PROJECT` scope | post-resolve validation | names the selector |
| Two kit sources → same destination | `stage_kits` | names both source paths |
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
   to today's install, including plugin-overlaid content.
2. **`[scopes]` coverage guard:** `[scopes]` plus the synthetic
   `instructions`/`settings` keys cover `namespaces.ALL`, so a future namespace
   addition fails in CI, not in users' installs.
3. `stage_kits`: tree-mirror destination; verbatim name (PRIME.md stays
   PRIME.md); source-relative selector key; recursive walk; route grouping by
   destination directory; executable-bit carry; empty on missing `src/kits/`.
4. Integration: `--project p --profiles beads-kit` writes `<p>/.beads/PRIME.md`;
   `--project p --profiles sdlc` errors (empty project partition).
5. Kit-scope guard: an override routing `kits/**` → user errors.
6. `project_namespaces()` matrix: a Claude skill → project works; a namespace →
   project for an unsupporting tool errors naming both.
7. Project receipt round-trip: install → prune → uninstall against a temp project
   tree; a beads kit dropped from a later selection is pruned as an orphan; the
   user receipt is untouched throughout.
8. Detection-suggestion: a user run in a cwd with `.beads/` prints exactly one
   line; a `--project` run prints none.
9. Overwrite: a kit install over an existing `.beads/PRIME.md` backs it up and
   respects `--yes` / prompt.
10. `--project p --profiles beads-kit --dry-run` previews would-be writes via
    `io`, creates no files, and leaves no `.agents-config/install-receipt.json`
    or `.lock` under `<p>`.
11. `--project` path missing / not a directory errors naming the path.

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
beyond beads; multi-file/nested kits beyond the single-route beads case (the
route-grouping generalizes, but only beads is exercised in S2); `installer.toml`
`tool_dest_overrides` retirement (S3, `agents-config-uxns2.1.2`, independent).

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
