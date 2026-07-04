# User Overrides + Install Profiles + Project-Scoped Staging — Design

**Date:** 2026-07-04
**Status:** Draft (pending review)
**Beads:** agents-config-wgclw.16 (user-owned overrides), agents-config-viiud (project-scoped staging), agents-config-uxns2.1 (install profiles)
**Decision:** Three cooperating installer capabilities sharing one config surface: user-owned override files that survive every install (personas replace, extensions append), a permission-gated migration path that rescues existing hand-edits, a `profiles.toml` manifest selecting composable subsets of installable content, and an explicit opt-in project-scope install route.

## 1. Problem

Three gaps, one pipeline:

1. **User customizations die on install.** The per-tool instruction files
   (`~/.claude/AGENTS.md`, `~/.codex/AGENTS.md`, `~/.gemini/GEMINI.md`, the
   OpenCode skeleton) are assembled at install time — DYNAMIC-INCLUDE flattening
   inlines the persona templates and shared instruction blocks, and the sync
   engine overwrites the destination (with a timestamped backup, but no
   preservation). Receipts deliberately do not record instruction files
   (merge-targets are never wholesale-owned), so nothing even notices the user
   had edited them. The owner's work-machine `~/.claude/AGENTS.md` — customized
   personas plus added sections — was silently replaced.
2. **All-or-nothing installs.** Every detected tool gets the full discipline
   layer. Projects that use an agent CLI for non-code work (writing, research)
   drag the whole SDLC apparatus — completion gates, PR workflows, TDD skills —
   into contexts where it is pure noise.
3. **No project-scope route.** Some assets belong in a project repo, not user
   space (the richer beads `PRIME.md` is the motivating case). The installer
   has no mechanism to write into a project directory at all.

Owner pain classification (interview 2026-07-04): customizations are
**A — different personas** and **B — user-added sections**. Not C (removing
shipped sections) and not D (editing shipped text in place) — so structured
override points suffice; no three-way merge, no arbitrary-edit preservation.

## 2. Locked owner decisions (2026-07-04 brainstorm — requirements, not options)

1. Personas **replace** when a user-owned persona file exists; user extensions
   **append** at a defined point in every assembled instruction file.
2. Override files are **user-owned**: the installer reads them during assembly
   and never writes, updates, or deletes them.
3. **Extraction/migration** is the rich path: with per-file permission, the
   installer rescues existing persona edits and user-added sections out of a
   hand-modified instruction file into the override files, then assembles.
4. Project-scope trigger is an **explicit opt-in command** (recorded on the
   viiud bead): detection may print a suggestion; it never writes.
5. Profiles use a **central manifest** (`profiles.toml`), composable by
   set-union, defaulting to today's full install; chosen sets are persisted per
   machine and per project. (Per-asset frontmatter tags and fixed presets were
   rejected.)
6. Section-level toggles are a **non-goal** (no C-class edits in practice).

## 3. Vocabulary

The installer already has an "overlay": Phase 6 overlays *plugin* content onto
the staged plan (`core/overlay.py`). This design therefore uses **user
overrides** for the user-owned customization files, and **project scope** for
the project-directory install route. "Overlay" keeps meaning plugins.

## 4. User overrides

### 4.1 Files and root

A user-owned directory at `~/.agents/` (the same tool-agnostic user-config root
the model-routing spec establishes for `model-routing.toml` and `spend.jsonl`;
if the root moves, all of it moves together):

| File | Effect when present | Effect when absent |
|---|---|---|
| `~/.agents/AGENT-PERSONA.md` | Replaces the shipped agent-persona template in every assembled instruction file | Shipped template applies |
| `~/.agents/USER-PERSONA.md` | Replaces the shipped user-persona template | Shipped template applies |
| `~/.agents/EXTENSIONS.md` | Appended at the user-extensions include point in every assembled instruction file | Include point resolves to nothing |

`ASSUMPTION:` v1 fixes the override surface to exactly these three files via an
explicit override registry (shipped-template → override-path map) rather than a
general "any `*.template` include may be overridden" rule. The general rule is
a one-line widening later; starting narrow keeps the contract auditable.

### 4.2 Assembly mechanics

- The DYNAMIC-INCLUDE resolver (template flattening, `core/templates.py`)
  consults the override registry before `repo_root`: an include whose source is
  a registered persona template resolves to the override file's bytes when that
  file exists.
- Each instruction template gains one new marker,
  `<!-- DYNAMIC-INCLUDE-USER-EXTENSIONS -->`, placed after the shipped content
  blocks; the resolver replaces it with `EXTENSIONS.md`'s content, or with
  nothing. All four tools' templates carry the marker, so one extensions file
  reaches every assembled surface (Claude, Codex, Gemini, OpenCode).
- Override content is wrapped in **sentinel comments** in the assembled output
  (`<!-- user-override:agent-persona:begin/end -->`, and likewise for
  user-persona and extensions). Sentinels are what make future extraction (§5)
  deterministic instead of heuristic. Shipped-template content gets no
  sentinels — only user-sourced blocks are marked.
- The installer never stages anything into `~/.agents/` on a normal install;
  the sync engine treats the override root as read-only input.

## 5. Extraction / migration

Two regimes, split by what the installer can know:

### 5.1 Baseline going forward: instruction-file hashes in the receipt

Receipts today record only wholesale-owned prunable items. This design extends
the receipt with a small `instruction_hashes` map — dest-relative path →
sha256 of the assembled bytes as written. `ASSUMPTION:` recorded as a new
receipt field with a schema-version bump (receipt `SCHEMA_VERSION` 1 → 2),
older receipts remaining readable with an empty map.

On a later install, for each instruction destination:

- **Hash matches** → file is exactly what we last wrote; assemble and
  overwrite as today.
- **Hash differs** (user edited since last install) → the file contains user
  content. If the previous install wrote sentinels, extraction is
  deterministic: shipped blocks are identifiable, sentinel-wrapped blocks and
  any text outside both are user content. With per-file consent, persona-block
  divergence lands in the persona override files and everything else lands
  appended to `EXTENSIONS.md`; then assembly proceeds.
- **No recorded hash** (first run after this feature ships, or a legacy
  receipt) → legacy regime, §5.2.

### 5.2 Legacy regime: backup + report, not guesswork

For a modified instruction file with no baseline (the owner's current work
machine, exactly), the installer does not guess which lines are the user's:

- With consent, it saves the existing file via the existing timestamped-backup
  machinery (`core/backup.py`) under a `.pre-override` label, prints a unified
  summary of what will change, and proceeds with assembly.
- Declining consent skips that file (counted and reported as skipped), leaving
  the destination untouched — the user can move their content into
  `~/.agents/` manually and re-run.

`ASSUMPTION:` no diff-against-shipped-template heuristics in v1 for legacy
files. The persona templates change across repo versions, so "differs from
current shipped text" cannot distinguish user edits from staleness without a
recorded baseline; pretending otherwise risks silently mis-filing shipped text
as user content. One manual rescue on machines that predate the feature is the
honest cost.

## 6. Install profiles

### 6.1 Manifest

A versioned `profiles.toml` at the repo root:

```toml
schema = 1

[profiles.full]
include = ["**"]                     # today's behavior

[profiles.minimal-user]
include = [
  "instructions",                     # assembled instruction files + personas
  "rules/memory-routing",
  "rules/user-prompts",
]

[profiles.sdlc]
include = ["rules/**", "skills/**", "agents/**", "commands/**", "workflows/**"]

[profiles.project-beads]
include = ["project/beads/**"]        # project-scope assets (PRIME.md kit)
```

- Selectors address staged content by namespace path (the same
  namespace vocabulary staging already uses: `rules/`, `skills/`, `agents/`,
  `commands/`, `workflows/`, plus `instructions` for the assembled instruction
  files and `settings` for settings payloads).
- `ASSUMPTION:` the starter profile set is `full`, `minimal-user`, `sdlc`,
  `project-beads`, with contents as sketched above — owner review re-cuts these
  freely; the mechanism, not the cut, is the contract.

### 6.2 Semantics

- **Composition** is set-union: `--profiles minimal-user,project-beads` stages
  everything either profile includes. Order is irrelevant.
- **Default** is `full` when no profile is given anywhere — a fresh clone
  installs exactly what it installs today; zero behavior change without
  opt-in.
- **Validation is fail-loud:** an unknown profile name errors naming the known
  profiles; a selector that matches nothing in the staged plan errors naming
  the selector (this is the anti-drift guard — a manifest entry cannot rot
  silently when an asset is renamed).
- **Filtering happens on the staged plan** after base staging and plugin
  overlay, before template flattening — profiles subtract from the one
  already-correct plan rather than teaching every staging phase about
  profiles. Plugin content is therefore profile-addressable like everything
  else.
- Settings and the instruction files ride with the `instructions`/`settings`
  selectors; a profile that omits them produces a content-only install (valid —
  e.g. refreshing skills without touching instruction files).

### 6.3 Persistence

- User scope: the chosen profile set is recorded in `~/.agents/install.toml`
  (`ASSUMPTION:` file name/location; lives beside the other user-config
  surfaces) and reused on a bare re-run; `--profiles` overrides and
  re-persists.
- Project scope: recorded in the project's `project-config.toml` under an
  `[install]` table (`profiles = [...]`), so a project's lean context is
  reproducible by anyone who clones it.

## 7. Project-scoped install

- **Trigger (locked):** explicit only — `install.sh --project <path>`
  (`ASSUMPTION:` flag spelling; could be a subcommand). A user-scope run never
  writes into any project.
- **Detection suggests:** when the installer's working directory is a git repo
  showing project signals (`.beads/` present, or `project-config.toml` with an
  `[install]` table), a user-scope run prints one suggestion line naming the
  opt-in command. No prompt, no write, no scanning beyond the cwd.
- **Source home:** `ASSUMPTION:` project-scope assets live under a new
  `src/project/` source root (sibling of `src/user/`), organized by kit
  (e.g. `src/project/beads/`), so user-scope and project-scope content never
  share a source tree and the `project/...` profile selectors map 1:1 onto it.
- **What it stages:** the profile set resolved for that project (from
  `--profiles`, else the project's persisted `[install]` table, else error —
  project scope has no implicit `full`; `ASSUMPTION:` requiring an explicit
  profile choice for project installs keeps "install the whole discipline
  layer into a repo" from happening by accident).
- **Where it lands:** project-scope assets declare project-relative
  destinations (e.g. the beads kit → `<project>/.beads/PRIME.md`); the staging
  pipeline runs with the project directory as the destination root.
- **Receipt:** each project install writes its own receipt in the project
  (`ASSUMPTION:` at `<project>/.agents-config/receipt.json`), giving project
  scope the same prune/uninstall mechanics as user scope and keeping the user
  receipt untouched.
- **Collision model:** `ASSUMPTION:` project scope reuses the Epic-E merge
  registry unchanged (same kinds, same strategies) rather than a blanket
  "project wins" rule — the registry already encodes per-kind judgment, and a
  project-scope `settings.json` union-merging like user scope is the least
  surprising behavior. A per-kind carve-out can follow evidence.
- Corporate constraints noted for this route: it must work behind a proxy
  (no network use — it already has none) and needs no admin privileges
  (home-dir and project-dir writes only).

## 8. Consumers and seams

| Surface | Change |
|---|---|
| `core/templates.py` | Override-registry resolution + user-extensions marker + sentinel wrapping |
| `core/receipt.py` / `receipt_store.py` | `instruction_hashes` map, schema v2 |
| `core/sync.py` | Modified-instruction-file gate (hash check → extract/backup consent flow) |
| New `core/profiles.py` | Manifest load/validate, selector match, plan filtering |
| `cli.py` / `config.py` | `--profiles`, `--project`; persisted-set resolution |
| `profiles.toml` (repo root) | New versioned manifest |
| Instruction templates (all four tools) | One `DYNAMIC-INCLUDE-USER-EXTENSIONS` marker each |
| Model-routing spec | Shares the `~/.agents/` root; `model-routing.toml`'s install-if-absent template becomes ordinary user-owned config under this design's vocabulary |
| Cross-model HEAVY gate panel spec | `heavy_panel = "native"` (corporate opt-out) is per-repo config a work-machine project profile naturally pairs with — referenced, not duplicated |

## 9. Non-goals

- Section-level toggles for shipped content (no C-class edits; YAGNI).
- Preserving arbitrary in-place edits to shipped text (no D-class edits).
- Legacy-file extraction heuristics (§5.2 — backup + report only).
- Per-asset profile frontmatter or fixed preset tiers (rejected options).
- Auto-detection that writes, or any project-dir write without the explicit
  opt-in command.
- Multi-project registry/scanning; the suggestion looks at the cwd only.

## 10. Test plan (behavioral contracts; ScriptedIO fakes, temp trees, no live installs)

1. Persona override present → assembled instruction file contains the override
   bytes inside sentinels; shipped persona text absent. Absent → shipped text,
   no sentinels.
2. `EXTENSIONS.md` present → its content lands at the marker in **all four**
   tools' assembled files; absent → marker resolves to nothing (no residue).
3. Normal install stages zero writes under `~/.agents/` (plan inspection).
4. Instruction hash recorded on install (receipt v2); tamper-free re-install
   sees a match and overwrites silently.
5. Hash mismatch + sentinel-bearing file + consent → persona divergence lands
   in the persona override file, out-of-sentinel additions land in
   `EXTENSIONS.md`, assembly proceeds (golden before/after fixture).
6. Hash mismatch + consent declined → dest byte-identical afterward, item
   counted skipped.
7. No recorded hash + modified file + consent → timestamped `.pre-override`
   backup exists, install proceeds; declined → dest untouched, skipped.
8. Receipt v1 (no `instruction_hashes`) loads cleanly as empty map.
9. Unknown profile name → error naming known profiles; selector matching
   nothing → error naming the selector.
10. Union composition: staged set for `a,b` equals union of each alone (no
    dupes, order-insensitive).
11. No profiles anywhere → staged plan identical to today's full install
    (golden plan comparison — the zero-breakage pin).
12. Persisted user set reused on bare re-run; `--profiles` overrides and
    re-persists.
13. `--project` stages only under the project root, writes a project receipt,
    leaves the user receipt untouched; project run with no resolvable profile
    set errors.
14. Detection: cwd with `.beads/` prints exactly one suggestion line and stages
    no project writes (ScriptedIO transcript).

## 11. Rollout

Three independently landable slices, in order: (1) user overrides + sentinels +
receipt v2 (stops the bleeding), (2) profiles (manifest + filtering +
persistence), (3) project scope (route + receipt + detection suggestion). Each
slice keeps `make ci-installer` green on its own.

## 12. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` §4.1 v1 override surface is exactly the three files via an
  explicit registry (no general template-override rule yet).
- `ASSUMPTION:` §5.1 receipt schema v2 with `instruction_hashes`; v1 receipts
  read as empty map.
- `ASSUMPTION:` §5.2 legacy files get backup + report only — no extraction
  heuristics without a recorded baseline.
- `ASSUMPTION:` §6.1 starter profile set and contents (`full`, `minimal-user`,
  `sdlc`, `project-beads`).
- `ASSUMPTION:` §6.3 persistence homes — `~/.agents/install.toml` (user) and
  `project-config.toml [install]` (project).
- `ASSUMPTION:` §7 flag spellings `--profiles` / `--project`.
- `ASSUMPTION:` §7 project-scope assets source home at `src/project/`.
- `ASSUMPTION:` §7 project installs require an explicit profile set (no
  implicit `full`).
- `ASSUMPTION:` §7 project receipt at `<project>/.agents-config/receipt.json`.
- `ASSUMPTION:` §7 collision model — Epic-E registry unchanged for project
  scope (no blanket project-wins).
