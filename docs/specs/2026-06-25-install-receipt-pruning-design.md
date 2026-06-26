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
    { "path": ".claude/skills/brainstorming", "owner": "claude", "root": ".claude", "kind": "dir",  "sha256": null },
    { "path": ".claude/rules/delivery.md",    "owner": "claude", "root": ".claude", "kind": "file", "sha256": "ab12…" },
    { "path": ".beads/scripts/foo.sh",        "owner": "beads",  "root": ".beads",  "kind": "file", "sha256": "cd34…" }
  ]
}
```

  - **`path`** is **home-relative** (the differ rejoins the caller's `home` at runtime). Portable across machines and home moves; testable under a fixture home. Because the receipt is now a **deletion-authority input**, every `path` is **validated before it can become an orphan** (see *Path trust boundary*).
  - **`owner`** is the tool name (`claude`/`codex`/`gemini`/`opencode`) or plugin name (`beads`). It is the diff-scope tag *and* the prune `Counters` bucket (`Orphan.tool` already carries a plugin name today).
  - **`root`** is the home-relative **install root** the entry lives under (`.claude`, `.config/opencode`, `.beads`, …), recorded at install time. It makes containment **self-validating**: a path is checked against its own recorded `root`, so a *retired* plugin's entries can be validated without re-discovering the plugin's live routes (resolving the scope-vs-validation tension — see *Path trust boundary*). For a tool owner it is redundant with `owner` (cross-checked); for a plugin route it is the only durable record of the route's dest root.
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
  - *retired* — its `src/plugins/` source removed or renamed, so no longer discovered → it would fall out of scope under "discovered only" and its files would be litter forever. Including **prior-receipt plugin owners** keeps it in scope → its recorded entries are orphaned → pruned. The differ works purely off recorded paths, and validation runs against each entry's recorded `root`, so a vanished plugin needs no source or route lookup.

This is the same concern the superseded bead chased ("active vs discovered set"), expressed cleanly: scope by recorded `owner`, not by re-deriving routes — and, for plugins, never let a recorded owner silently drop out of scope. A generic plugin that overlaid into a tool tree is pruned through that **tool's** scope (its entries are owned by the tool); only bespoke route files carry a plugin owner and rely on the prior-receipt-owner rule.

### Path trust boundary

The receipt is the new **source of deletion targets** — an `Orphan.path` comes straight from a prior-receipt entry. A receipt that is valid JSON but malformed (hand-edited, partially written by an older tool, or corrupted) must never become a lever to delete files outside the install surface. So **every entry is validated before the diff**, reusing the installer's existing relpath guard. Validation is **self-contained against the entry's recorded `root`**, so it never needs live plugin discovery:

- **Structural** — `path` and `root` must both be **relative** (reject absolute) and contain **no `..`** component. After rejoining `home`, a relative no-`..` path always resolves under `home`, bounding the blast radius to the user's home tree before any owner logic.
- **Containment** — `path` must resolve under `home/root` (its own recorded install root).
- **Root legitimacy** — when the owner is **live-known**, `root` is cross-checked: a tool owner's `root` must equal that tool's `dest_dir(home)` (the tool set is closed and always knowable); a *discovered* plugin's `root` must be one of its live route dest roots. When the owner is a **retired plugin** (no longer discoverable), the **recorded `root` is the authority** — it was written by us at install time when the route was live, and the structural checks already confine it under `home`. This is exactly what lets a retired plugin's route entries become orphans (the scope rule put them in scope; recording `root` lets validation honor that without re-deriving vanished routes).
- An entry failing any check is treated as **receipt corruption for that entry**: skipped, logged, **never emitted as an `Orphan`**.

This keeps the blast radius of a bad receipt at "prunes less than it could," never "deletes something it shouldn't" — and removes the contradiction between retired-plugin scope and path validation.

## Receipt lifecycle

- **Read** the prior receipt at the start of the prune step (tolerant — see fail-safe). Its entries, scoped as above, drive orphan detection.
- **Single-writer.** Because the receipt is a central deletion-authority file derived from `prior ∪ this-run`, the **read → prune → write** sequence is guarded by an **exclusive advisory lock** on a sibling lockfile (`install-receipt.lock`). Without it, two concurrent runs can both read the same prior state and the last writer discards the other's ownership records — or worse, a stale writer *resurrects* an entry another run already pruned, so a user's later file at that path is mis-classified as ours and deleted. A run that cannot acquire the lock fails fast with a clear "another install is in progress" message rather than racing. The installer is run infrequently and serially, so the lock is cheap insurance, not a bottleneck. (An optimistic generation/hash re-read-and-merge before `os.replace` is an acceptable alternative; the lock is simpler and preferred.)
- **Write** the new receipt at the **end of a successful, non-dry-run run** (after install and any prune complete), atomically (temp file + `os.replace`). Written on **every** such run — not only under `--prune` — so the record never goes stale; *pruning* the diff stays gated behind `--prune`/`--prune-only`, but *recording* is unconditional.
- **The receipt mirrors disk.** The new receipt is **not** a blind overwrite of staged items, nor an owner-scoped carve-out. It is the single invariant *an entry leaves the receipt only when it actually leaves the disk, and enters only when actually written to disk*:
  `new_receipt = (prior_receipt − entries actually pruned this run) ∪ installed_this_run`, unioned by `path` with the `installed_this_run` entry winning (refreshed `sha256`).
- **`installed_this_run` is what the install layer actually wrote, not what was planned.** It is the **per-item install outcome** reported by the install layer: owned entries that were **created, updated, or skipped-identical** (already on disk as our bytes). It explicitly **excludes**:
  - **consent-declined overwrites** — when a user declines to overwrite a changed dest, the installer leaves the *user's* file untouched (`sync._consent_to_overwrite` → keep existing) and tallies it as `skipped`. That path is the user's content, not ours; recording it would let a later source deletion delete the user's file. The receipt must therefore record from the install layer's *outcome*, **not** from the plan and **not** from the raw `skipped` tally (which conflates skipped-identical with consent-declined).
  - **the entire install half when it does not run** — under `--prune-only`, `installed_this_run` is empty, so the receipt is exactly `prior_receipt − pruned`. The staging plan is still built (it drives orphan detection), but nothing was placed on disk, so nothing is recorded. (On first adoption / empty receipt, `--prune-only` therefore prunes nothing and records nothing — a clean no-op.)
  The invariant is correct for every mode with no further special-casing: a plain install prunes nothing, so nothing is dropped and written entries are refreshed; a `--prune` run drops exactly the entries it removed; a `--tools=claude` subset run never prunes codex/gemini/opencode entries, so they carry over untouched; and an orphan detected but **not** removed (no `--prune`, or consent declined) stays recorded *because it is still on disk*. Writing "intended" state instead would silently lose track of files left behind — the exact litter this work removes.
- **`--dry-run` writes nothing** — no receipt write, no deletion. Preview only.
- **Missing vs corrupt are different — and only missing bootstraps.** The receipt is now load-bearing state, so a file we *cannot read* must not be silently discarded:
  - **Missing** (file absent) → **bootstrap empty**: prune nothing, write a fresh receipt from this run's installs. This is the agreed clean-break adoption — pre-receipt litter that was never recorded is simply not seen; everything installed from adoption forward is covered. No migration code, no legacy glob sweep.
  - **Corrupt / unreadable / unknown `schema_version`** (file present but unusable) → **fail-closed**: **disable pruning for this run and do NOT overwrite the receipt**, emitting a clear diagnostic (e.g. "install receipt at `<path>` is unreadable; skipping prune and leaving it untouched — reset or migrate it to re-enable pruning"). Treating a corrupt receipt as empty and then rewriting it would, on a scoped run like `--tools=claude`, replace the whole central record with only this run's entries — silently erasing codex/gemini/opencode/plugin ownership and stranding those files as unprunable litter. The install half still runs; only prune and the receipt write are suppressed until the state file is sound.

## Components (each independently testable)

| Unit | Responsibility | Notes |
|---|---|---|
| `ownership` classifier | `StagedItem → bool`: wholesale-owned & prune-eligible? | Pure; excludes merge-targets |
| `Receipt` / `ReceiptEntry` model + JSON (de)serialize | Data + schema-versioned round-trip | New `core/receipt.py` |
| receipt **store** | read (missing → empty; corrupt → distinct "unreadable" signal) · write (atomic temp+replace) | I/O isolated; pure core stays pure |
| receipt **builder** | per-item install outcomes → in-scope `ReceiptEntry` set | Created/updated/skipped-identical only; empty under `--prune-only` |
| orphan **differ** | (prior receipt ∩ scope, path-validated) − `installed_this_run` → `list[Orphan]` | **Replaces** `scan_orphans`; `scope` reads prior-receipt plugin owners |

**The install layer must report per-item outcomes** — the raw `Counters` tally is insufficient, because its `skipped` bucket conflates *skipped-identical* (ours, record it) with *consent-declined* (the user's file, never record it). So `sync_plan` / `sync_routes` are extended to surface, per owned item, whether it was **created / updated / skipped-identical** (→ recorded) versus **consent-declined / errored** (→ not recorded). The receipt builder consumes that outcome set, gated on the install half having run. `sync()`'s core write logic is unchanged — only its *reporting* widens from counts to per-path outcomes.

## Deleted vs reused

**Deleted:**
- `core/prune.py`: `scan_orphans`, `_scan_namespace`, `_staged_basenames`, `_routed_staged_basenames`, `_BEADS_TOOL`, `_BEADS_NAMESPACE`, `_PRUNE_SUBDIRS`. *(The hardcoded-formula bug dies with the code that holds it.)*
- `installer.toml`: the `[prune]` section.
- `core/installer_toml.py`: the `prune_globs` loading. (The `[tools]` override loading — currently inert — is out of scope for this change; left as-is.)

**Reused:**
- `core/prune_flow.py` `run_prune` and its backup/consent flow — the deletion executor, **lightly extended** to report which orphans it actually removed (the receipt write needs the removed-paths set, per *The receipt mirrors disk*).
- The `Orphan` model — the differ emits it directly.
- `core/sync.py` `sync_plan` / `sync_routes` — **lightly extended** to report per-item install outcomes (created / updated / skipped-identical / declined / errored) so the receipt records only paths actually written as our bytes. The write logic itself is unchanged.

## Bugs subsumed

- **`agents-config-abn9.37.1.1`** (superseded). `~/.beads/scripts` and any future route gain coverage automatically — the receipt records whatever `sync_routes` wrote, regardless of route. The `_BEADS_*` hardcodes are deleted.
- **`agents-config-cr7bi`** (subsumed; the `zoom-out` relocation). Prior receipt holds `.codex/skills/zoom-out` (owner `codex`), `.gemini/skills/zoom-out` (owner `gemini`), `.config/opencode/skills/zoom-out` (owner `opencode`). After the relocation narrows the skill to Claude, this run stages `zoom-out` only under `owner=claude`. For each of codex/gemini/opencode (all in `resolved_tools`), the recorded entry is no longer staged → orphan → pruned; Claude's entry is still staged → kept. The "which source tree did this name come from" confusion is gone because the receipt records the *destination* owner explicitly.

## Edge cases

- **`.installignore` interaction.** `.installignore` excludes **source** files at the staging choke point, upstream of the plan. Excluded files are therefore never staged and never recorded. A file that *was* installed and later becomes excluded (or is dropped) is simply not in the new plan → it is an orphan → pruned. That is correct cleanup, not a regression; no special carve-out is needed. (`.installignore` is itself fail-closed: an absent manifest aborts the install before prune runs.)
- **User-deleted file we recorded.** Still in the prior receipt; if still staged, it is reinstalled; if also dropped from source, it is an orphan whose deletion is a harmless no-op (already gone).
- **User-created file we never installed.** Never in the receipt → never an orphan → never touched. The ownership-by-receipt model inherently protects genuine user files — a strict improvement over globs, which could match a user's like-named file.
- **Consent-declined overwrite.** The user declines to overwrite a changed dest, so the installer keeps the *user's* bytes. The per-item outcome is `declined`, **not** recorded — so the path is never claimed as ours and never becomes an orphan, even though it was in the plan. (Recording it from the plan would later delete the user's file when the source is dropped.)
- **Corrupt receipt mid-life.** A present-but-unreadable receipt (hand-edit, partial write, version we don't understand) → prune is **disabled** and the receipt is **left untouched** for that run, with a diagnostic. It is never silently replaced by this run's partial view, which would strand other owners' files. Distinct from a *missing* receipt, which legitimately bootstraps empty.
- **Malformed receipt path.** An entry whose `path` is absolute, contains `..`, or resolves outside its recorded `root` is rejected by the path trust boundary → skipped, never an orphan. A bad receipt prunes *less*, never deletes outside the install surface.
- **Retired plugin (source removed).** A plugin previously installed and recorded, whose `src/plugins/` source is later removed or renamed, is no longer *discovered*. Because `scope` also includes **prior-receipt plugin owners**, its recorded route files (`owner=plugin`) are still in scope → orphaned → pruned; any content it overlaid into a tool tree is owned by that tool and pruned through the tool's scope. Without the prior-receipt-owner rule this whole plugin's files would be permanent litter — the precise failure this design exists to remove.
- **`--prune-only` on an empty / fresh receipt.** The install half is skipped, so `installed_this_run` is empty and nothing is recorded; with no prior receipt there are no orphans. A clean no-op — and, crucially, it does **not** record the (unwritten) staging plan as installer-owned, which would mis-claim user files for later deletion.
- **First run / fresh adoption.** No prior receipt → empty → prunes nothing, writes the first receipt from what this run installed. Pruning begins on the second run.

## Testing strategy

Unit (driven through `ScriptedIO`; 90% branch floor per package gate):

- **Ownership classifier truth table** — skills/agents/commands/rules recorded; `settings.json` (`JsonUnionStrategy`) and append-merged instruction files **not** recorded.
- **Differ scope matrix** — (a) untargeted tool's entries survive a `--tools=` subset run; (b) excluded plugin's entries are pruned; (c) cross-tree relocation (`zoom-out`) prunes the three non-Claude copies and keeps Claude's; (d) **retired plugin** — a recorded plugin no longer in the discovered set still has its route files orphaned (prior-receipt-owner scope), and its tool-tree overlay entries orphaned through the tool's scope.
- **Receipt store** — round-trip; **missing** → empty; **corrupt / malformed / unknown-`schema_version`** → distinct "unreadable" signal (not empty).
- **Per-item outcome / consent-declined** — a changed dest the user declines to overwrite is tallied `skipped` by `Counters` but reported `declined` per-item, and is **not** recorded; a created/updated/skipped-identical path **is** recorded.
- **Path trust boundary** — entries with absolute paths, `..` components, or a `path` outside their recorded `root` are skipped, never emitted as orphans; **a retired plugin's entry with a valid recorded `root` passes validation and IS pruned** (the scope-vs-validation contradiction is gone); a tool entry whose `root` mismatches the live tool dest is rejected.
- **Corrupt receipt during a scoped run** — `--tools=claude` against a corrupt receipt prunes nothing **and** leaves the receipt file unchanged (codex/gemini/opencode/plugin ownership preserved).
- **Single-writer lock** — a second run that cannot acquire the receipt lock fails fast; a stale writer cannot resurrect an entry a concurrent run already pruned.
- **Receipt mirrors disk** — a `--tools=claude` run preserves codex entries (neither staged nor pruned); an orphan detected but left unpruned (no `--prune`) stays recorded.
- **`--prune-only` records nothing it didn't write** — `--prune-only` over an **empty** receipt records no entries (the staging plan is built but never written), so a later source deletion at one of those paths does not classify a user file as an orphan.
- **Atomic write** — temp + replace; `--dry-run` writes nothing.

Integration (end-to-end through `ScriptedIO`): install → drop a source file → reinstall `--prune` → assert the dest copy is pruned and backed up; install `--tools=claude` over a full prior receipt → assert no codex/gemini/opencode entries are pruned; install a plugin → remove its `src/plugins/` source → reinstall `--prune` → assert both its route files and its tool-tree overlay entries are pruned; **adoption with a declined overwrite** → user declines overwriting a changed dest at first adoption, then the source is removed and `--prune` runs → assert the user's file is **not** pruned (never recorded).

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
- The receipt mirrors disk: an entry leaves only when actually removed, and enters only when actually written. The receipt records from **per-item install outcomes** (created/updated/skipped-identical), never from the plan — a **consent-declined** overwrite leaves the user's file and is **not** recorded; `--prune-only` records no new entries.
- A **missing** receipt bootstraps empty (clean-break adoption, no legacy sweep). A **corrupt/unreadable/unknown-version** receipt fails closed: pruning is disabled and the receipt is left untouched (never overwritten with a partial scoped view), with a diagnostic.
- The receipt is a validated deletion-authority input: each entry records its install `root`; validation is self-contained against that `root` (no live discovery), so a retired plugin's entries validate and prune, while an absolute / `..` / outside-`root` path is rejected and never emitted as an orphan.
- The receipt's read → prune → write sequence is single-writer (advisory lock): concurrent runs serialize or fail fast, never losing ownership records or resurrecting already-pruned entries.
- Tests cover the ownership classifier, the differ scope matrix (untargeted tool, excluded plugin, cross-tree relocation, retired plugin), receipt-store missing-vs-corrupt, per-item consent-declined, path trust boundary (including retired-plugin-passes + tampered-root-rejected), corrupt-receipt-during-scoped-run, single-writer lock, receipt-mirrors-disk, `--prune-only`-records-nothing, and dry-run.
- `make ci-installer` green.
