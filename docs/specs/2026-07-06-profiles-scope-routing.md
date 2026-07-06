# Install Profiles as the Sole Scope-Routing Mechanism — Design

**Date:** 2026-07-06
**Status:** Draft (pending review)
**Beads:** agents-config-uxns2.1 (install profiles), agents-config-viiud (project-scoped staging)
**Relation to prior spec:** Supersedes §6 (profiles) and §7 (project-scoped
install) of `2026-07-04-user-overlay-profiles-project-staging.md`. That spec's
§4–5 (user overrides, extraction/migration) remain authoritative and are not
touched here.
**Decision:** One mechanism decides both *what* installs and *where* it lands:
a `profiles.toml` manifest whose entries carry destination scope as data. One
pure resolver turns (profile definitions, selected set, staged universe, bound
scope roots) into per-scope install plans. No source-tree scope partition, no
per-route special rules, no second config surface.

## 1. Problem

The superseded design routed scope through structure: `src/user/` content could
only land in user space, a new `src/project/` tree could only land in
projects, profiles selected *what* within a run, and a flag selected *where*
the run pointed. Four axes cooperating — plus a special rule ("project scope
has no implicit full") to keep them from misfiring. The owner's concern,
recorded on the beads: that shape accretes conditionals, drifts as content
evolves, and becomes undebuggable — "why did X install to Y?" has no single
place to look.

Owner requirements (2026-07-06 interview):

1. Install to a project ONLY — zero user-scope changes.
2. Install a general subset to user scope, then target a specific project for
   the rest.
3. User-definable profile configuration controlling what installs *where*,
   with useful defaults so destination scope needn't be configured
   exhaustively.
4. Profiles can exclude content entirely (e.g. never install the brainstorming
   skill, anywhere).

Requirements 3 and 4 are inexpressible in the superseded design: profiles were
include-only (no exclude semantics), and scope was a property of the source
tree, not of configuration.

A code survey (packages/installer, 2026-07-06) confirms the ground is clear
and favorable: no profile code exists anywhere; `StagedItem.dest_relpath` is
already root-agnostic with the destination root supplied only at consumption
(`adapter.dest_dir(home)`, two call sites); `home` is a pure injected
parameter package-wide (`Path.home()` appears exactly once, in `cli.py`); and
`dump_plan` already materializes a plan under an arbitrary root. Routing by
scope is a data problem, not a rewrite.

## 2. Decision

**Routing is data; resolution is one function.**

- `profiles.toml` declares default destination scopes per namespace
  (`[scopes]`) and named profiles (`[profiles.*]`) whose include entries may
  override scope per selector and whose exclude entries subtract content
  unconditionally.
- One resolver — a pure function — maps the selected profiles onto the staged
  universe and emits per-scope plans. Every "why did X land at Y?" answer is
  in its output.
- The staged universe is **run-invariant**: every run stages the same
  candidate plan (all namespaces, kits included) regardless of run type.
  Profile selection and scope binding are the only variables — which is what
  makes the resolver a single function rather than a family of modes.
- The CLI binds scopes to roots: a default run binds `user` to the home
  directory; `--project <path>` binds `project` to that path. Entries whose
  scope is unbound are dropped with a counted notice. Project writes therefore
  remain impossible without the explicit flag — the locked viiud decision
  (explicit opt-in; detection only suggests) is preserved structurally.

What this dissolves from the superseded design:

- The `src/project/` source-tree scope partition as a mechanism. Scope comes
  from the manifest; the source tree is just organization.
- The "project scope has no implicit `full`" special rule (§7) as a *scope
  guard*: under scope binding, a project run structurally cannot stage
  user-scoped entries, so there is no implicit spill to guard against. One
  deliberate asymmetry survives, relocated into selection (§6 step 2): user
  runs default to `full`, project runs require an explicit or persisted set —
  one line in one resolver step, not a routing conditional.
- `installer.toml`'s parsed-but-inert `tool_dest_overrides` scaffolding — this
  design supersedes it; it is retired rather than wired in (one config
  surface, not two).

## 3. Vocabulary

- **Scope** — a destination realm: `user` (per-tool home-dir config roots) or
  `project` (a specific repository's working tree). The closed set for v1.
- **Selector** — a namespace path pattern (`skills/**`,
  `rules/memory-routing`, `instructions`) addressing staged content in a
  **normalized vocabulary** the resolver defines over the staged universe, not
  a raw installer output. Normalization: each item's `dest_relpath` with its
  `.md`/`.template` suffix stripped (`rules/memory-routing.md` →
  `rules/memory-routing`), and the tool-root instruction and settings templates
  (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, … / `settings.json`, `opencode.jsonc`)
  collapsed to the synthetic `instructions` and `settings` selectors — there is
  no `instructions` namespace on disk today, and staging keys on raw
  `dest_relpath`. This one canonical selector surface is what the §9
  vocabulary-consolidation prerequisite lands; every selector below matches
  against it, never against raw `dest_relpath`.
- **Profile** — a named set of include entries (selector, optional scope
  override) and exclude entries (selector only).
- **Scope binding** — the CLI-supplied mapping from scope name to a concrete
  destination root for one run.
- **Kit** — tool-agnostic content with project-relative destinations (e.g.
  the beads `PRIME.md` kit landing at `.beads/`), sourced under `src/kits/`.

## 4. Requirements → guarantees

| # | Requirement | How this design guarantees it |
|---|---|---|
| 1 | Project-only install | `--project` binds *only* the project scope; user-scoped entries are structurally unbound that run — no profile discipline required |
| 2 | User subset + project rest | Two runs: `install.sh --profiles minimal-user`, then `install.sh --project <path> --profiles beads-kit` — each persisted at its own scope |
| 3 | Configurable what-goes-where with defaults | `[scopes]` supplies defaults per namespace; include entries override per selector; user-defined profiles compose in from `~/.agents/profiles.toml` |
| 4 | Exclude content entirely | `exclude` entries subtract scope-agnostically; excludes always win over includes; `--profiles full,no-brainstorming` composes |

## 5. Manifest

A versioned `profiles.toml` at the repo root (shipped), plus an optional
user-owned `~/.agents/profiles.toml` (never written by the installer,
consistent with the user-override philosophy of the 07-04 spec §4).

```toml
schema = 1

# Default destination scope per namespace selector.
# Every staged item MUST match an entry; most-specific match wins.
[scopes]
"instructions"  = "user"
"settings"      = "user"
"rules/**"      = "user"
"skills/**"     = "user"
"agents/**"     = "user"
"commands/**"   = "user"
"workflows/**"  = "user"
"hooks/**"      = "user"
"kits/**"       = "project"

[profiles.full]
include = ["**"]                      # today's behavior (user-scoped entries)

[profiles.minimal-user]
include = ["instructions", "rules/memory-routing", "rules/user-prompts"]

[profiles.sdlc]
include = ["rules/**", "skills/**", "agents/**", "commands/**", "workflows/**"]

[profiles.beads-kit]
include = ["kits/beads/**"]

[profiles.no-brainstorming]
exclude = ["skills/brainstorming"]    # an exclude-only profile composes with anything

# Scope override: route a user-default asset into the project realm.
[profiles.project-lean]
include = [
  "kits/beads/**",
  { select = "skills/writing-plans", scope = "project" },
]
```

- Include entries are either a bare selector string (scope from `[scopes]`)
  or an inline table `{ select = "...", scope = "..." }` (explicit scope).
- Exclude entries are bare selectors only — exclusion is scope-agnostic by
  design ("not anywhere" is the requirement).
- Selectors are the **normalized** vocabulary (§3): extension-less
  (`rules/memory-routing`, not `rules/memory-routing.md`), with `instructions`
  and `settings` addressing the tool-root instruction/settings templates. The
  resolver normalizes the staged universe once before matching, so a manifest
  never carries a `.md` suffix or a tool-root filename.
- `ASSUMPTION:` the starter profile set is `full`, `minimal-user`, `sdlc`,
  `beads-kit`, `no-brainstorming`, `project-lean` as sketched — the owner
  re-cuts contents freely; the mechanism, not the cut, is the contract.
- `ASSUMPTION:` user-defined profiles live at `~/.agents/profiles.toml` and
  merge with the shipped manifest by profile *name*; a user profile whose name
  collides with a shipped profile is an error (no silent shadowing — compose
  or rename instead). The user file may not declare `[scopes]` entries in v1.

## 6. Resolution semantics

One pure function: `(definitions, selection, universe, bindings) →
(per-scope plans, dropped-entry counts)`. Every failure below is fail-loud
with the offending name in the message.

**Specificity** (used wherever "most-specific match wins" appears): a selector
with no wildcards is more specific than any glob; among globs, the one with
more literal path segments before its first wildcard is more specific
(`skills/brainstorming` > `skills/*` and `skills/**`; `skills/*` and
`skills/**` are equal). Equal specificity is a **tie** — ties never resolve
silently (see step 7).

1. **Load definitions** — shipped `profiles.toml`, then `~/.agents/profiles.toml`
   if present. Duplicate profile name across the two → error.
2. **Resolve the selected set** — `--profiles a,b` if given; else the
   persisted set for the run's bound scope (§7); else `full` for user runs.
   Project runs with no explicit or persisted set → error (a project install
   never guesses).
3. **Validate names** — unknown profile name → error naming the known
   profiles.
4. **Union** — includes := union of include entries across selected profiles;
   excludes := union of exclude entries. Order-independent.
5. **Match** — selectors match against the staged universe: the post-overlay,
   pre-flattening plan, projected into the normalized selector vocabulary (§3)
   — suffix-stripped, with tool-root instruction/settings templates mapped to
   the `instructions`/`settings` selectors. Any selector (include *or* exclude)
   matching nothing in the universe → error naming the selector. This is the anti-drift guard:
   a manifest entry cannot rot silently when an asset is renamed. An exclude
   *may* subtract nothing from the current include set (no-op subtraction
   keeps exclude profiles composable with any include set); it must still
   match the universe.

   **Boundary — filtering vs template composition.** Profile selectors govern
   *staged items*. Template flattening interacts with filtering per include
   form: the `DYNAMIC-INCLUDE-ALL-RULES` form rebuilds its rule set from the
   filtered plan, so an excluded rule never reaches an instruction file
   assembled that way (Codex/Gemini/OpenCode). The `DYNAMIC-INCLUDE: <path>`
   and `DYNAMIC-INCLUDE-RULES: a,b` forms resolve from the *source tree* —
   a template that names content explicitly is authored composition, and it
   inlines that content regardless of profile filtering. Excluding such
   content removes its standalone staged copy only. (Claude's instruction
   template carries no ALL-RULES marker; Claude rules ship as standalone
   files, which excludes remove normally.) `ASSUMPTION:` authored template
   composition deliberately wins over profile exclusion in v1 — re-pointing
   the named-include forms at the filtered plan is a follow-on if evidence
   demands.
6. **Subtract** — result := matched(includes) − matched(excludes). Excludes
   always win, regardless of which profile contributed them. An empty result
   → error ("selected profiles resolve to zero items") — an install that
   installs nothing is a mistake, not a success.
7. **Assign scope** — for each resulting item: collect the explicit-scope
   include entries matching it across all selected profiles. If any exist,
   the most-specific one wins; a *specificity tie* between entries carrying
   different scopes → error naming both profiles and selectors. If none, the
   most-specific `[scopes]` entry applies; `[scopes]` entries are validated
   at manifest load — two same-specificity entries that could assign
   different scopes to one item are rejected there. No `[scopes]` match →
   error (no catch-all default; new namespaces must be routed deliberately).
8. **Bind and partition** — partition the result by scope; plans for bound
   scopes proceed to flattening and sync; entries for unbound scopes are
   dropped with a single counted notice line naming the scope and the opt-in
   flag. If *everything* drops (non-empty result, empty bound partition) →
   error: the run would do nothing, and a run that does nothing is a wrong
   profile/flag combination, not a quiet no-op. `ASSUMPTION:` notice-and-drop
   for partial drops, error for total drops — partial keeps `full` composable
   on plain user runs; a strict flag can follow evidence.

Debugging story: `--dump-stage` already materializes the staged plan; it now
reflects the resolved, scope-partitioned result. "Why did X install to Y" is
answered by the resolver's inputs — all of them named files or flags.

## 7. CLI surface, binding, persistence

- **Flags:** `--profiles a,b` (CSV, set-union semantics) and
  `--project <path>`. `ASSUMPTION:` flag spellings carried over from the
  superseded design.
- **Binding:** a default run binds `user` → resolved home. `--project <path>`
  binds `project` → that path *and does not bind user scope* — one primary
  binding per run. Requirement 1 is thereby structural: a project run cannot
  write user space at all. `ASSUMPTION:` no dual-scope single run in v1;
  requirement 2 is satisfied by two runs. A combined-run mode can follow
  evidence without schema change.
- **Persistence:** user runs persist the chosen set in
  `~/.agents/agents-config.toml` (`ASSUMPTION:` name/location per the 07-04
  spec §6.3, beside the other `~/.agents/` surfaces); project runs persist in
  the project's `project-config.toml` under `[install]`
  (`profiles = [...]`) so a project's lean context is reproducible by anyone
  who clones it. `--profiles` overrides and re-persists at the run's scope.
- **Default:** no profiles given or persisted, user run → `full`. A fresh
  clone installs exactly what it installs today; zero behavior change without
  opt-in (test-pinned, §10).
- **Detection suggests (unchanged, locked):** a user-scope run whose cwd shows
  project signals (`.beads/` present, or `project-config.toml` with an
  `[install]` table) prints one suggestion line naming the opt-in command.
  No prompt, no write, no scanning beyond the cwd.

## 8. Project materialization

- **Support matrix (declarative, per tool):** each `ToolAdapter` declares
  `project_namespaces()` — the namespaces it can materialize under a project
  root. v1: Claude → `("skills", "agents", "commands")` (landing under
  `<project>/.claude/<ns>/`); Codex, Gemini, OpenCode → `()` (no project-level
  equivalents worth targeting yet). Routing a namespace to project scope for a
  tool that doesn't support it → validation error naming the tool and
  namespace. Capability facts live in code as data; preferences live in the
  manifest. Note: since `[scopes]` defaults all of skills/agents/commands to
  `user`, Claude's project namespaces are reachable only via explicit
  per-selector scope overrides — `--project` with a stock user profile (e.g.
  `sdlc`) stages nothing and errors per §6 step 8, by design.
- **Instructions and settings are never project-routable in v1** — a project's
  `CLAUDE.md`/`AGENTS.md` and settings are project-authored artifacts the
  installer must not collide with. Enforced by the matrix.
- **Kits:** tool-agnostic project content sources from `src/kits/<kit>/`
  (`ASSUMPTION:` supersedes the 07-04 spec's `src/project/` home — the new
  name doesn't bake scope into the tree, consistent with routing-as-data).
  Kit items declare project-relative destinations (the beads kit →
  `<project>/.beads/PRIME.md`); `[scopes]` defaults `kits/**` to project.
- **Receipt:** each project install writes its own receipt at
  `<project>/.agents-config/install-receipt.json` (`ASSUMPTION:` carried over
  from the superseded §7) — the same receipt schema the current machinery
  writes (v1 at time of writing; the wgclw.16 user-override slice bumps to v2
  with `instruction_hashes`, and project receipts simply adopt whatever
  version is current — the version number is not an invariant of this
  design), same integrity digest, but entry paths anchored
  project-root-relative instead of home-relative, with its own sibling lock
  file. Prune and uninstall mechanics work per receipt; the user receipt is
  untouched by project runs and vice versa.
- **Collision model:** project scope reuses the existing merge registry
  unchanged (same `(FileKind, namespace)` dispatch, same strategies) —
  `ASSUMPTION:` carried over; no blanket "project wins" rule. A per-kind
  carve-out can follow evidence.
- Corporate constraints (unchanged): no network use, no admin privileges —
  home-dir and project-dir writes only.

## 9. Consumers and seams

Grounded in the 2026-07-06 code survey; module references are to
`packages/installer/src/installer/`.

| Surface | Change |
|---|---|
| New `core/profiles.py` | Manifest load/validate (shipped + user), resolver (§6), scope partition |
| `core/orchestrator.py` | Resolution hooks in between plugin overlay/extensions and `flatten_plan_templates` (filtering must precede flattening, §6 step 5) |
| `core/run.py` | `install_pipeline` fans out per (tool × bound scope) instead of per tool; second receipt triple (read/lock/record) for project runs |
| `cli.py` | `--profiles`, `--project`; persisted-set resolution; project receipt path; detection suggestion line |
| `config.py` | Persisted-set read/write for both scope homes |
| `tools/base.py` + adapters | `project_namespaces()` on the `ToolAdapter` protocol |
| `core/model.py` | Either a scope annotation on staged items or an external scope→plan partition — implementer's choice; the resolver's contract (§6) is what's pinned |
| `profiles.toml` (repo root) | New versioned manifest |
| `~/.agents/profiles.toml` | Optional user-owned profile definitions (read-only to the installer) |
| `core/installer_toml.py` | `tool_dest_overrides` retired (superseded by this design) |
| Namespace vocabulary | **Prerequisite:** the survey found five divergent namespace lists (`tools/claude.py` scoped set, `core/staging.py` shared + carrier sets, `core/overlay.py` overlay sets, `core/ownership.py` prune set, `core/backup.py` backup set) that disagree (e.g. `hooks` present in some, absent in others). Selector matching needs one canonical vocabulary with per-concern views — landed as its own slice before the resolver (Continuations) |

## 10. Test plan (behavioral contracts; ScriptedIO fakes, temp trees, no live installs)

1. No profiles anywhere → staged plan identical to today's full install
   (golden plan comparison — the zero-breakage pin).
2. Union composition: staged set for `a,b` equals union of each alone; order
   of the CSV is irrelevant.
3. Exclude subtracts: `full,no-brainstorming` stages everything except the
   excluded skill (a standalone asset — removal from the staged plan is the
   whole guarantee for it).
4. Flattening boundary (§6 step 5): excluding a rule removes it from an
   instruction file assembled via `DYNAMIC-INCLUDE-ALL-RULES` (Codex/Gemini
   path — rebuilt from the filtered plan) AND removes its standalone staged
   copy; a rule named explicitly by `DYNAMIC-INCLUDE-RULES` remains inlined
   in that template's output while its standalone copy is removed (authored
   composition wins — the pinned v1 boundary).
5. Exclude wins regardless of contributing profile; exclude that subtracts
   nothing from the include set is a silent no-op; exclude matching nothing in
   the *universe* errors naming the selector; a selection resolving to zero
   items errors (§6 step 6).
6. Unknown profile name → error naming known profiles; include selector
   matching nothing → error naming the selector. Selector matching runs against
   the normalized vocabulary (§3): `rules/memory-routing` matches the staged
   `rules/memory-routing.md`, and `instructions` matches the tool-root
   instruction templates — a `.md`-suffixed or tool-root-filename selector is
   not the manifest vocabulary.
7. Duplicate profile name across shipped and user manifests → error; user
   manifest declaring `[scopes]` → error (v1).
8. Scope-assignment specificity (§6 step 7): a literal include entry
   (`skills/writing-plans`, scope=project) beats a broader glob entry
   (`skills/**`, scope=user) from another selected profile — no error, the
   specific one wins; two *equal-specificity* entries with different scopes →
   error naming both profiles and selectors; overlapping `[scopes]` entries
   apply most-specific-wins, and same-specificity conflicting `[scopes]`
   entries are rejected at manifest load.
9. Item with no `[scopes]` match and no explicit scope → error naming the
   item's namespace.
10. Scope-override entry routes a user-default asset to project scope; it
    stages under the project root and NOT under user roots.
11. User run: project-scoped entries drop with one counted notice line; zero
    project writes (plan inspection).
12. Project run (`--project`): user-scoped entries drop with notice; zero
    user-space writes; only `project_namespaces()`-supported namespaces and
    kits materialize; unsupported tool+namespace routing errors; an explicit
    `{ select = "instructions", scope = "project" }` (or `settings`) entry
    errors via the matrix (never project-routable).
13. Total-drop error (§6 step 8): a project run whose resolved set is entirely
    user-scoped (e.g. `--project . --profiles sdlc`) errors rather than
    silently doing nothing.
14. Project run with no explicit or persisted profile set → error.
15. Project receipt written at `<project>/.agents-config/install-receipt.json`
    with project-root-relative entry paths; user receipt byte-identical before
    and after a project run; prune driven by the project receipt removes only
    project-side entries.
16. Persisted user set reused on a bare re-run; `--profiles` overrides and
    re-persists; project persisted set read from `project-config.toml
    [install]`.
17. Detection: cwd with `.beads/` prints exactly one suggestion line and
    stages no project writes (ScriptedIO transcript).

## 11. Non-goals

- Dual-scope single runs (one binding per run in v1).
- Project-routable `instructions`/`settings` (project-authored artifacts).
- Project-defined profile *definitions* (projects persist a chosen set only;
  definitions live in shipped + user manifests).
- Wiring `installer.toml`'s `tool_dest_overrides` (retired instead).
- Receipt schema v2 / `instruction_hashes` — that belongs to the user-override
  slice of the 07-04 spec (wgclw.16), unaffected here.
- Section-level toggles, arbitrary-edit preservation, multi-project scanning,
  any project write without the explicit flag (all unchanged from the 07-04
  spec).

## 12. Rollout

Independently landable slices, each keeping `make ci-installer` green:

1. **S0 — namespace vocabulary consolidation** (prerequisite): one canonical
   module with per-concern views; reconciles the five divergent lists.
2. **S1 — manifest + resolver + user-scope filtering**: `profiles.toml`,
   `core/profiles.py`, excludes, user-defined profiles, persistence; bare
   install pinned byte-identical (golden test).
3. **S2 — project binding + materialization**: `--project`, support matrix,
   kit staging under `src/kits/`, project receipt, detection suggestion.
4. **S3 — retire `tool_dest_overrides`**: remove the inert field and loader
   schema; note the supersession in `installer.toml`'s comments.

## 13. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` §5 starter profile set and contents.
- `ASSUMPTION:` §5 user profiles at `~/.agents/profiles.toml`; name collision
  with shipped profiles errors; user file may not declare `[scopes]` in v1.
- `ASSUMPTION:` §6 unbound-scope entries drop with a counted notice on
  partial drops; total drops and empty resolutions error (strict flag for
  partial drops deferred to evidence).
- `ASSUMPTION:` §6 step 5 — authored template composition
  (`DYNAMIC-INCLUDE: <path>`, `DYNAMIC-INCLUDE-RULES`) wins over profile
  exclusion in v1; only the plan-sourced `ALL-RULES` form respects filtering.
- `ASSUMPTION:` §6 specificity metric — literal-prefix segment count; ties
  never resolve silently.
- `ASSUMPTION:` §7 flag spellings `--profiles` / `--project`.
- `ASSUMPTION:` §7 one scope binding per run; requirement 2 via two runs.
- `ASSUMPTION:` §7 persistence homes — `~/.agents/agents-config.toml` (user)
  and `project-config.toml [install]` (project).
- `ASSUMPTION:` §8 v1 support matrix — Claude `("skills", "agents",
  "commands")`, all other tools none.
- `ASSUMPTION:` §8 kits source home `src/kits/` (supersedes the blessed
  `src/project/` assumption of the 07-04 spec — re-review deliberately).
- `ASSUMPTION:` §8 project receipt at
  `<project>/.agents-config/install-receipt.json` (carried over).
- `ASSUMPTION:` §8 merge registry unchanged for project scope (carried over).

## Continuations

- task: Centralize installer namespace vocabulary — AC: a single canonical
  namespace module in `packages/installer` exposing per-concern views
  (scoped, shared, carrier, prune, backup, overlay); the five existing
  divergent lists consume it; intentional divergences (e.g. `hooks` excluded
  from prune) are named in code, accidental ones reconciled; `make
  ci-installer` green. Blocks the profiles resolver (S1).
- task: Retire `installer.toml` `tool_dest_overrides` — AC: field and loader
  schema removed from `core/installer_toml.py`; `installer.toml` comments
  point to `profiles.toml`; `make ci-installer` green.
- note: agents-config-uxns2.1 and agents-config-viiud are existing beads
  re-scoped by this spec (S1–S2 respectively), not new mints — their
  descriptions are updated and readiness labels re-stamped at spec merge.
