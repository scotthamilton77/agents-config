# Design: Install receipt replaces glob-based pruning

**Date:** 2026-06-25
**Status:** draft (design — awaiting review)
**Scope:** Replace the hand-maintained `installer.toml` `[prune] retired` glob list with a post-install **receipt** — a record of every file/dir the installer authors wholesale. Pruning becomes a differential of the prior receipt against the current staging plan, scoped to what the run actually addressed. Deletes the glob-scan code path in `core/prune.py` (`scan_orphans` and helpers, the `_BEADS_*` hardcodes) and the `[prune]` section. Bead: `agents-config-abn9.37.1.2`. Supersedes `agents-config-abn9.37.1.1`; subsumes `agents-config-cr7bi`.

## Summary

Today the installer only removes a retired file from a user's tree if a human remembered to add a matching glob to `installer.toml`'s `[prune] retired` list when they deleted the source. That coupling is the root problem: the list is a manual reconstruction, from memory, of "what did we install last time" — and memory is exactly the thing that fails. The result is litter (retired files left behind) and a latent class of correctness bugs in the glob scan itself.

The fix is to stop reconstructing that knowledge and instead **record it**. After each install the installer writes a receipt of every entry it authored wholesale. On the next run, an entry present in the prior receipt but no longer staged — within the run's scope — is an orphan. The prune list's job (remember what we used to install) is done by data the installer already has at write time, not by a person.

## Terminology — "receipt", not "manifest"

This codebase already uses **manifest** for a different artifact: the `.installignore` *exclusion manifest* (`2026-06-20-installignore-exclusion-manifest-design.md`), a repo-root data file naming **source** files to exclude from staging. To avoid two unrelated "manifests", the record introduced here is the **install receipt**: a record of what the installer **wrote** to the user's home. The two never overlap — exclusion manifest governs source input; install receipt records destination output.

## Motivation / root cause

The coupling is not a one-off; it produces a **class** of defects, all rooted in the glob scan having no memory of prior installs:

- **Litter from forgotten globs.** Delete a source skill, forget the glob → the retired copy lives forever in every installed tree.
- **Hardcoded route coverage** (`agents-config-abn9.37.1.1`, now superseded). `core/prune.py` pins `_BEADS_TOOL="beads"` / `_BEADS_NAMESPACE="formulas"` and scans only `~/.beads/formulas`. Beads' *own* second route, `~/.beads/scripts`, gets zero orphan coverage; so does any future plugin route.
- **Cross-tree relocation blindness** (`agents-config-cr7bi`, subsumed). When `zoom-out` moved from shared (`src/user/.agents/skills/`) to Claude-only (`src/user/.claude/skills/`), the stale copies at `~/.codex/skills/zoom-out`, `~/.gemini/skills/zoom-out`, `~/.config/opencode/skills/zoom-out` were left behind. The glob scan compares dest names against a *merged* source set and cannot tell "this name appears in `src/user/.claude/`" from "this name was staged to `~/.codex/`."

A receipt collapses all three. It records the **actual per-tool/plugin destination** of every wholesale-authored entry, so "what did we put here, and is it still wanted?" is answered by lookup, not inference.

### Why a receipt rather than generalizing the glob scan

The superseded bead proposed making the glob scan data-driven over plugin routes — enumerating route dests from the discovered plugin set, deriving staged baselines from the active set, etc. That is real complexity whose only purpose is to *reconstruct*, at scan time, the per-dest knowledge a receipt simply *records* at install time. The receipt makes the reconstruction unnecessary: an excluded plugin's dests, a relocated skill's old home, a retired script — all are already named in the prior receipt. The "active vs discovered plugin set" gymnastics disappear.

## The receipt

- **Location:** `~/.config/agents-config/install-receipt.json`. A tool-neutral state dir outside every dest tree, so the receipt is never itself installed or pruned.
- **One central file.** The installer is a single actor writing many homes (`~/.claude`, `~/.codex`, `~/.gemini`, `~/.config/opencode`, `~/.beads`). One receipt is the natural model: a single atomic write at run-end, with each entry tagged by its owner so the diff can scope per-tool/plugin.
- **Schema (v1):**

```json
{
  "schema_version": 1,
  "entries": [
    { "path": ".claude/skills/brainstorming", "owner": "claude", "kind": "dir",  "sha256": null },
    { "path": ".claude/rules/delivery.md",    "owner": "claude", "kind": "file", "sha256": "ab12…" },
    { "path": ".beads/scripts/foo.sh",        "owner": "beads",  "kind": "file", "sha256": "cd34…" }
  ]
}
```

  - **`path`** is **home-relative** (the differ rejoins the caller's `home` at runtime). Portable across machines and home moves; testable under a fixture home.
  - **`owner`** is the tool name (`claude`/`codex`/`gemini`/`opencode`) or plugin name (`beads`). It is the diff-scope tag *and* the prune `Counters` bucket (`Orphan.tool` already carries a plugin name today).
  - **`kind`** is `file` or `dir` (top-level skill/agent dirs are recorded as one `dir` entry, matching how staging treats them).
  - **`sha256`** is the hex digest of a file's bytes (`sync._sha256` already computes it), `null` for `dir` entries. **v1 records it but does not branch on it** — see Deferred work.
  - **`schema_version`** gates forward-compatible evolution; an unrecognized version is treated as unreadable (fail-safe, below).

## Ownership model — what the receipt records

The receipt records **only entries the installer authors wholesale** — entries it would be correct to delete in their entirety when they stop being staged. It must never record a **merge-target**, a file the installer only contributes *part* of, because dropping a contribution must never delete the whole file.

| Dest write | Strategy | Recorded? |
|---|---|---|
| `skills/`, `agents/`, `commands/` top-level entries | wholesale copy (`DIR`/file; `FatalStrategy` on collision) | **Yes** |
| Claude `rules/*.md` (individual files) | wholesale copy | **Yes** |
| Beads `~/.beads/formulas/*`, `~/.beads/scripts/*` | route copy (`PluginRoute`) | **Yes** |
| `settings.json` | `JsonUnionStrategy` — unioned *into* | **No — never** |
| Codex/Gemini/OpenCode instruction files (rules append-merged in) | `AppendRulesStrategy` / assembled templates | **No — never** |

This boundary coincides with the **existing prune scope**: the namespaced entries (`commands`/`skills`/`agents`/`rules`) plus plugin route dests. Merge-targets (`settings.json`, the assembled `AGENTS.md`/`GEMINI.md`/`opencode.jsonc`) live outside those namespaces, so the receipt introduces no new deletion surface — it records the same class of thing the current scan already considers, with explicit per-owner provenance added.

**Ownership is decided by a single pure classifier** (`StagedItem → bool`): recorded iff the item is a wholesale file/dir write (not a merge-target). The classifier keys off the item's `FileKind`/namespace and its resolved merge strategy, so a future namespace inherits correct behavior without touching prune code.

**Owner assignment.** A **tool-tree entry** — anything under a tool's `commands`/`skills`/`agents`/`rules`, *including content a generic plugin overlaid there* — is owned by the **dest tool**. A **bespoke route dest** outside any tool tree (beads' `~/.beads/...`) is owned by the **plugin**. This split is load-bearing for retiring a whole plugin (see *Diff scope*): an overlaid skill is reclaimed through its tool's scope, a route file through the plugin's. It matches today's `Orphan.tool` semantics (the `beads` bucket for formulas; the dest tool for namespaced entries).

## The prune differential

```
orphans = { e ∈ prior_receipt :
              e.owner ∈ scope
              AND e.path ∉ installed_this_run }

scope = resolved_tools
      ∪ discovered_plugins
      ∪ { plugin owners recorded in prior_receipt }     # so a *retired* plugin is still pruned
```

Each orphan becomes the existing `Orphan` model and flows through the **existing** `run_prune` flow (backup + consent, unchanged). The receipt only *identifies* orphans; deletion machinery is reused verbatim. (`installed_this_run` — not "the plan" — is what an entry is checked against; see *Receipt lifecycle*.)

### Diff scope — the correctness crux

A naive diff (`prior_receipt − current_plan`) is **actively dangerous**: `install --tools=claude` stages only Claude items, so every codex/gemini/opencode entry would look "no longer staged" and be deleted. The diff is therefore **scoped to what the run actually addressed** — and tools and plugins have deliberately *different* scope semantics, because "not staged this run" means different things for each:

- **Owner in `resolved_tools`** (a tool this run targeted) → in scope. An entry no longer staged is an orphan.
- **Owner is an untargeted tool** (not in `resolved_tools`) → **out of scope, untouched.** A partial `--tools=` run never disturbs another tool's entries. For a tool, "not addressed" means *later, not now* — preserve. (Tools are a closed, known set; fully dropping a tool adapter is a rare, deliberate code change and is an accepted residual, not handled here.)
- **Owner is a plugin** → in scope when the plugin is **either currently discovered OR recorded in the prior receipt**. This covers three cases with one rule:
  - *active plugin* → its files are staged this run → not orphaned.
  - *excluded via `--plugins=`* (still discovered) → stages nothing → recorded entries are orphans → pruned (strict-mode intent).
  - *retired* — its `src/plugins/` source removed or renamed, so no longer discovered → it would fall out of scope under "discovered only" and its files would be litter forever. Including **prior-receipt plugin owners** keeps it in scope → its recorded entries are orphaned → pruned. The differ works purely off recorded paths, so a vanished plugin needs no source or route lookup.

This is the same concern the superseded bead chased ("active vs discovered set"), expressed cleanly: scope by recorded `owner`, not by re-deriving routes — and, for plugins, never let a recorded owner silently drop out of scope. A generic plugin that overlaid into a tool tree is pruned through that **tool's** scope (its entries are owned by the tool); only bespoke route files carry a plugin owner and rely on the prior-receipt-owner rule.

## Receipt lifecycle

- **Read** the prior receipt at the start of the prune step (tolerant — see fail-safe). Its entries, scoped as above, drive orphan detection.
- **Write** the new receipt at the **end of a successful, non-dry-run run** (after install and any prune complete), atomically (temp file + `os.replace`). Written on **every** such run — not only under `--prune` — so the record never goes stale; *pruning* the diff stays gated behind `--prune`/`--prune-only`, but *recording* is unconditional.
- **The receipt mirrors disk.** The new receipt is **not** a blind overwrite of staged items, nor an owner-scoped carve-out. It is the single invariant *an entry leaves the receipt only when it actually leaves the disk, and enters only when actually written to disk*:
  `new_receipt = (prior_receipt − entries actually pruned this run) ∪ installed_this_run`, unioned by `path` with the `installed_this_run` entry winning (refreshed `sha256`).
- **`installed_this_run` is what was actually written, not what was planned.** It is the owned plan entries the install half **actually wrote or confirmed-present** this run (created + updated + skipped-identical). **When the install half does not run — `--prune-only` — `installed_this_run` is empty**, so the receipt is exactly `prior_receipt − pruned`. This is the critical distinction: the staging plan is built even under `--prune-only` (it drives orphan detection), but its entries were **not** placed on disk, so they must never be added to the receipt. Recording a planned-but-unwritten path would let a later source deletion classify a *user's* file at that path as our orphan and delete it. (On first adoption / empty receipt, `--prune-only` therefore prunes nothing and records nothing — a clean no-op.)
  The invariant is correct for every mode with no further special-casing: a plain install prunes nothing, so nothing is dropped and written entries are refreshed; a `--prune` run drops exactly the entries it removed; a `--tools=claude` subset run never prunes codex/gemini/opencode entries, so they carry over untouched; and an orphan detected but **not** removed (no `--prune`, or consent declined) stays recorded *because it is still on disk*. Writing "intended" state instead would silently lose track of files left behind — the exact litter this work removes.
- **`--dry-run` writes nothing** — no receipt write, no deletion. Preview only.
- **Fail-safe on read.** A missing, unreadable, malformed, or unrecognized-`schema_version` receipt is treated as **empty**: the run prunes nothing and writes a fresh receipt. This *is* the agreed clean-break migration — pre-receipt litter that was never recorded is simply not seen; everything installed from adoption forward is covered. No migration code, no legacy glob sweep.

## Components (each independently testable)

| Unit | Responsibility | Notes |
|---|---|---|
| `ownership` classifier | `StagedItem → bool`: wholesale-owned & prune-eligible? | Pure; excludes merge-targets |
| `Receipt` / `ReceiptEntry` model + JSON (de)serialize | Data + schema-versioned round-trip | New `core/receipt.py` |
| receipt **store** | read (fail-safe → empty) · write (atomic temp+replace) | I/O isolated; pure core stays pure |
| receipt **builder** | owned entries actually installed this run → in-scope `ReceiptEntry` set | Empty when the install half is skipped (`--prune-only`) |
| orphan **differ** | prior receipt ∩ scope − `installed_this_run` → `list[Orphan]` | **Replaces** `scan_orphans`; `scope` reads prior-receipt plugin owners |

The sync engine is **not** modified. On the success path the install half's owned plan entries equal what is on disk (`sync` aborts the whole run on failure), so `installed_this_run` is built from the **plan's owned items, gated on the install half having run** — no need to widen `sync()`'s `Counters` return to report written paths. Under `--prune-only` the install half does not run, so the builder contributes nothing (only `prior_receipt − pruned` is written).

## Deleted vs reused

**Deleted:**
- `core/prune.py`: `scan_orphans`, `_scan_namespace`, `_staged_basenames`, `_routed_staged_basenames`, `_BEADS_TOOL`, `_BEADS_NAMESPACE`, `_PRUNE_SUBDIRS`. *(The hardcoded-formula bug dies with the code that holds it.)*
- `installer.toml`: the `[prune]` section.
- `core/installer_toml.py`: the `prune_globs` loading. (The `[tools]` override loading — currently inert — is out of scope for this change; left as-is.)

**Reused:**
- `core/prune_flow.py` `run_prune` and its backup/consent flow — the deletion executor, **lightly extended** to report which orphans it actually removed (the receipt write needs the removed-paths set, per *The receipt mirrors disk*).
- The `Orphan` model — the differ emits it directly.
- `core/sync.py` — untouched. `installed_this_run` is built from the install half's owned plan entries, so `sync()`'s `Counters` return is **not** widened.

## Bugs subsumed

- **`agents-config-abn9.37.1.1`** (superseded). `~/.beads/scripts` and any future route gain coverage automatically — the receipt records whatever `sync_routes` wrote, regardless of route. The `_BEADS_*` hardcodes are deleted.
- **`agents-config-cr7bi`** (subsumed; the `zoom-out` relocation). Prior receipt holds `.codex/skills/zoom-out` (owner `codex`), `.gemini/skills/zoom-out` (owner `gemini`), `.config/opencode/skills/zoom-out` (owner `opencode`). After the relocation narrows the skill to Claude, this run stages `zoom-out` only under `owner=claude`. For each of codex/gemini/opencode (all in `resolved_tools`), the recorded entry is no longer staged → orphan → pruned; Claude's entry is still staged → kept. The "which source tree did this name come from" confusion is gone because the receipt records the *destination* owner explicitly.

## Edge cases

- **`.installignore` interaction.** `.installignore` excludes **source** files at the staging choke point, upstream of the plan. Excluded files are therefore never staged and never recorded. A file that *was* installed and later becomes excluded (or is dropped) is simply not in the new plan → it is an orphan → pruned. That is correct cleanup, not a regression; no special carve-out is needed. (`.installignore` is itself fail-closed: an absent manifest aborts the install before prune runs.)
- **User-deleted file we recorded.** Still in the prior receipt; if still staged, it is reinstalled; if also dropped from source, it is an orphan whose deletion is a harmless no-op (already gone).
- **User-created file we never installed.** Never in the receipt → never an orphan → never touched. The ownership-by-receipt model inherently protects genuine user files — a strict improvement over globs, which could match a user's like-named file.
- **Retired plugin (source removed).** A plugin previously installed and recorded, whose `src/plugins/` source is later removed or renamed, is no longer *discovered*. Because `scope` also includes **prior-receipt plugin owners**, its recorded route files (`owner=plugin`) are still in scope → orphaned → pruned; any content it overlaid into a tool tree is owned by that tool and pruned through the tool's scope. Without the prior-receipt-owner rule this whole plugin's files would be permanent litter — the precise failure this design exists to remove.
- **`--prune-only` on an empty / fresh receipt.** The install half is skipped, so `installed_this_run` is empty and nothing is recorded; with no prior receipt there are no orphans. A clean no-op — and, crucially, it does **not** record the (unwritten) staging plan as installer-owned, which would mis-claim user files for later deletion.
- **First run / fresh adoption.** No prior receipt → empty → prunes nothing, writes the first receipt from what this run installed. Pruning begins on the second run.

## Testing strategy

Unit (driven through `ScriptedIO`; 90% branch floor per package gate):

- **Ownership classifier truth table** — skills/agents/commands/rules recorded; `settings.json` (`JsonUnionStrategy`) and append-merged instruction files **not** recorded.
- **Differ scope matrix** — (a) untargeted tool's entries survive a `--tools=` subset run; (b) excluded plugin's entries are pruned; (c) cross-tree relocation (`zoom-out`) prunes the three non-Claude copies and keeps Claude's; (d) **retired plugin** — a recorded plugin no longer in the discovered set still has its route files orphaned (prior-receipt-owner scope), and its tool-tree overlay entries orphaned through the tool's scope.
- **Receipt store** — round-trip; fail-safe on missing / malformed / unknown-`schema_version` → empty.
- **Receipt mirrors disk** — a `--tools=claude` run preserves codex entries (neither staged nor pruned); an orphan detected but left unpruned (no `--prune`) stays recorded.
- **`--prune-only` records nothing it didn't write** — `--prune-only` over an **empty** receipt records no entries (the staging plan is built but never written), so a later source deletion at one of those paths does not classify a user file as an orphan.
- **Atomic write** — temp + replace; `--dry-run` writes nothing.

Integration (end-to-end through `ScriptedIO`): install → drop a source file → reinstall `--prune` → assert the dest copy is pruned and backed up; install `--tools=claude` over a full prior receipt → assert no codex/gemini/opencode entries are pruned; install a plugin → remove its `src/plugins/` source → reinstall `--prune` → assert both its route files and its tool-tree overlay entries are pruned.

## Deferred work (out of scope)

- **sha256-aware prune** (`agents-config-fkewj`, blocked by this). v1 records `sha256` but does not branch on it: an orphan is backed-up-and-deleted via `run_prune` regardless of whether the user edited it. The follow-up compares an orphan's on-disk hash to the recorded hash and spares a user-customized copy. The data is already captured here; only the prune decision changes.
- **`[tools]` override loading** in `core/installer_toml.py` — untouched by this change.

## Acceptance criteria

- The install receipt records every wholesale-authored entry (namespaced `commands`/`skills`/`agents`/`rules` + plugin route dests) and **never** a merge-target (`settings.json`, assembled instruction files).
- Pruning is driven by the receipt differential, scoped to `resolved_tools ∪ discovered_plugins ∪ prior-receipt plugin owners`: an untargeted tool is untouched; an excluded plugin's recorded entries are pruned; a **retired plugin** (source removed, no longer discovered) still has its recorded files pruned rather than carried forward as litter.
- Cross-tree relocation (shared → single-tool; the `zoom-out`/`cr7bi` case) prunes the stale per-tool dest copies.
- `~/.beads/scripts` is covered (the `abn9.37.1.1` regression seed).
- `_BEADS_TOOL` / `_BEADS_NAMESPACE` and the `[prune]` section are gone; removing them is the tell the scan is genuinely general.
- The receipt is written on every successful, non-dry-run run; `--dry-run` writes nothing; pruning the diff is gated behind `--prune`/`--prune-only`.
- The receipt mirrors disk: an entry leaves only when actually removed, and enters only when actually written. `--prune-only` (install half skipped) records no new entries — a planned-but-unwritten path is never claimed as installer-owned.
- A missing/corrupt receipt is treated as empty (prunes nothing, writes fresh) — the clean-break migration, no legacy sweep.
- Tests cover the ownership classifier, the differ scope matrix (untargeted tool, excluded plugin, cross-tree relocation, retired plugin), receipt-store fail-safe, receipt-mirrors-disk, `--prune-only`-records-nothing, and dry-run.
- `make ci-installer` green.
