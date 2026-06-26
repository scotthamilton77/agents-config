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
  "integrity": "sha256:9f2b…",
  "roots": [".claude", ".codex", ".gemini", ".config/opencode", ".beads"],
  "entries": [
    { "path": ".claude/skills/brainstorming", "owner": "claude", "root": ".claude", "kind": "dir",  "sha256": null },
    { "path": ".claude/rules/delivery.md",    "owner": "claude", "root": ".claude", "kind": "file", "sha256": "ab12…" },
    { "path": ".beads/scripts/foo.sh",        "owner": "beads",  "root": ".beads",  "kind": "file", "sha256": "cd34…" }
  ]
}
```

  - **`path`** is **home-relative** (the differ rejoins the caller's `home` at runtime). Portable across machines and home moves; testable under a fixture home. Because the receipt is now a **deletion-authority input**, every `path` is **validated before it can become an orphan** (see *Path trust boundary*).
  - **`owner`** is the tool name (`claude`/`codex`/`gemini`/`opencode`) or plugin name (`beads`). It is the diff-scope tag *and* the prune `Counters` bucket (`Orphan.tool` already carries a plugin name today).
  - **`root`** is the home-relative **install root** the entry lives under (`.claude`, `.config/opencode`, `.beads`, …), recorded at install time. `path` is checked for **containment** under its own recorded `root`, and the `root` itself is validated per *Path trust boundary* (live code for tool/discovered-plugin owners; the `roots` allowlist for retired plugins). For a tool owner it is redundant with `owner` (cross-checked against live `dest_dir`); for a plugin route it is the only durable record of the route's dest root.
  - **`kind`** is `file` or `dir` (top-level skill/agent dirs are recorded as one `dir` entry, matching how staging treats them).
  - **`sha256`** is the hex digest of a file's bytes (`sync._sha256` already computes it), `null` for `dir` entries. **v1 records it but does not branch on it** — see Deferred work.
  - **`schema_version`** gates forward-compatible evolution; an unrecognized version is treated as unreadable (fail-safe, below).
  - **`integrity`** is a `sha256` over the canonical serialization of the rest of the receipt (`schema_version` + `roots` + `entries`, with entries in a stable order). On read it is **recomputed and compared**; a mismatch (or a missing `integrity`) means the file changed since we wrote it and is treated as **corrupt → fail closed** (see *Receipt lifecycle*). This is what makes the *accidental-corruption-never-prunes-wild* guarantee real even for the trusted-state retired-plugin path: any stray edit, truncation, or bad merge — including one that happens to leave `roots` and an `entry` self-consistent — breaks the digest and disables pruning. A deliberate forger who recomputes `integrity` is, by *Trust model*, out of scope (it requires the same write access needed to delete files directly).
  - **`roots`** (top-level) is the persisted record of installer-owned install roots — maintained across runs as `prior_roots ∪ this-run's live install roots`, and never derived from `entries`. It is the **trusted-state fallback** used only for *retired*-plugin validation: tool and discovered-plugin roots come from **live code** (authoritative), so `roots` matters only when an owner is no longer live. It rejects *accidental* garbage roots; per *Trust model* it is not claimed as a defense against a deliberately forged receipt.

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
              AND e.path ∉ desired_staged_keys }

desired_staged_keys = the owned dest paths in THIS run's staging plan, for owners in scope
                      (the plan is built even under --prune-only — it is "what we want installed now")

scope = resolved_tools
      ∪ discovered_plugins
      ∪ { plugin owners recorded in prior_receipt }     # so a *retired* plugin is still pruned
```

**Orphan detection diffs against the desired *staged plan*, not against what was written.** These are two different sets and must not be confused:
- **`desired_staged_keys`** = what this run *wants* installed (the staging plan, always built — including under `--prune-only`). An entry recorded before but absent from the desired plan is retired → an orphan. This drives the diff.
- **`installed_this_run`** = what was *actually written to disk* this run (created/updated/skipped-identical; empty under `--prune-only`). This drives only the **receipt write** (see *Receipt lifecycle*), never orphan detection.

Conflating them is catastrophic: subtracting the (empty) `installed_this_run` under `--prune-only` would mark *every* scoped recorded entry — including still-wanted files — as an orphan and delete the whole installed tree. Diffing against `desired_staged_keys` instead means `--prune-only` prunes exactly the retired entries and preserves everything still in the plan.

Each orphan becomes the existing `Orphan` model and flows through the **existing** `run_prune` flow (backup + consent, unchanged). The receipt only *identifies* orphans; deletion machinery is reused verbatim.

### Diff scope — the correctness crux

A naive diff (`prior_receipt − current_plan`) is **actively dangerous**: `install --tools=claude` stages only Claude items, so every codex/gemini/opencode entry would look "no longer staged" and be deleted. The diff is therefore **scoped to what the run actually addressed** — and tools and plugins have deliberately *different* scope semantics, because "not staged this run" means different things for each:

- **Owner in `resolved_tools`** (a tool this run targeted) → in scope. An entry no longer staged is an orphan.
- **Owner is an untargeted tool** (not in `resolved_tools`) → **out of scope, untouched.** A partial `--tools=` run never disturbs another tool's entries. For a tool, "not addressed" means *later, not now* — preserve. (Tools are a closed, known set; fully dropping a tool adapter is a rare, deliberate code change and is an accepted residual, not handled here.)
- **Owner is a plugin** → in scope when the plugin is **either currently discovered OR recorded in the prior receipt**. This covers three cases with one rule:
  - *active plugin* → its files are staged this run → not orphaned.
  - *excluded via `--plugins=`* (still discovered) → stages nothing → recorded entries are orphans → pruned (strict-mode intent).
  - *retired* — its `src/plugins/` source removed or renamed, so no longer discovered → it would fall out of scope under "discovered only" and its files would be litter forever. Including **prior-receipt plugin owners** keeps it in scope → its recorded entries are orphaned → pruned. The differ works purely off recorded paths, and validation runs against each entry's recorded `root` plus the persisted `roots` allowlist, so a vanished plugin needs no source or route lookup.

This is the same concern the superseded bead chased ("active vs discovered set"), expressed cleanly: scope by recorded `owner`, not by re-deriving routes — and, for plugins, never let a recorded owner silently drop out of scope. A generic plugin that overlaid into a tool tree is pruned through that **tool's** scope (its entries are owned by the tool); only bespoke route files carry a plugin owner and rely on the prior-receipt-owner rule.

### Trust model

The receipt is **trusted installer state**, exactly as a package manager trusts its installed-file database (dpkg's `/var/lib/dpkg/info`, Homebrew's `INSTALL_RECEIPT.json`). It lives in user-writable space, so it cannot be made tamper-proof against its own owner — and it need not be: **anyone who can rewrite `~/.config/agents-config/install-receipt.json` can already `rm -rf ~/.ssh` directly.** Defending a local state file against a local actor who already has that write access is not a boundary the design can or should claim. So the threat model is drawn deliberately:

- **In scope — accidental corruption.** Truncated/partial writes, parse failures, version drift, and stray garbage values are caught and **fail closed**. The decisive mechanism is the **`integrity` checksum**: the whole receipt is hashed on write and re-verified on read, so *any* accidental change — including one that leaves `roots` and an `entry` self-consistent — breaks the digest and disables pruning (prune nothing, file untouched; see *Receipt lifecycle*). This is what makes "accidental corruption never prunes wild" a real guarantee rather than a hope; the per-entry validation below is defense-in-depth on top of it.
- **In scope — live-code authority for the common case.** For tools and *currently-discovered* plugins, the legitimate root is taken from **live code, not the receipt** — so a forged or corrupted `root`/`roots` value for those owners is ignored. This covers ~all entries; the receipt is only *trusted* for the rare retired-plugin tail.
- **Out of scope — deliberate forgery.** A hand-crafted receipt that impersonates a *retired* plugin **and recomputes a valid `integrity` digest** is trusted (its files prune). Closing this would require either a tamper-proof out-of-band registry (impossible on a single-user machine) or abandoning retired-plugin cleanup; it is accepted as equivalent to direct home write access — an actor who can rewrite the receipt and its digest can already delete the files outright.

### Path trust boundary

Every entry is validated before it can become an `Orphan`, reusing the installer's existing relpath guard:

- **Structural** — `path` and `root` must both be **relative** (reject absolute) and contain **no `..`**.
- **Containment (symlink-aware)** — containment is checked on **fully-resolved** paths, not lexical ones: `(home/root/path).resolve()` must be relative to `(home/root).resolve()`. A relative no-`..` path is *not* guaranteed under `$HOME` — `~/.claude` or `~/.beads` is frequently a symlink into a dotfiles repo outside `$HOME`. The boundary the design actually enforces is therefore **"within the resolved install root"** (where we genuinely installed), *not* "under `$HOME`": pruning legitimately operates inside a symlinked root's target, but a `path` that uses symlink components to escape its resolved root is rejected. (If a deployment needs the stricter `$HOME` guarantee, it must reject symlinked roots — `root.resolve().is_relative_to(home.resolve())` — as a configuration choice; the default supports symlinked roots and prunes within their target.)
- **Root legitimacy** — resolved by owner kind, *live code first*:
  - **Tool owner** → `root` must equal that tool's live `dest_dir(home)` (closed set, always derivable). The receipt cannot override it — a forged `{owner:"claude", root:".ssh"}` is rejected because claude's live root is `.claude`.
  - **Discovered plugin owner** → `root` must be one of that plugin's **live** route roots. Again receipt-independent.
  - **Retired plugin owner** (not a live tool, not discovered) → `root` must be in the persisted `roots` allowlist. This is **trusted state**, but it sits **behind the `integrity` gate** (per *Trust model*): accidental corruption — even a self-consistent one that adds a root to both `roots` and an entry — breaks the digest and fails closed before this check is reached. Only a forge that also recomputes `integrity` passes, which is out of scope (= direct home write access).
- An entry failing any check is treated as **receipt corruption for that entry**: skipped, logged, **never emitted as an `Orphan`**.

Net effect: for tools and discovered plugins the deletion surface is pinned by live code regardless of the receipt; for retired plugins it is pinned by trusted persisted state **behind the `integrity` gate**. A *damaged* receipt fails that gate and prunes nothing; even if it somehow parsed, the structural checks above bound each path so it prunes less, never wild. A *forged* one (valid recomputed digest) is bounded to impersonating a retired plugin — accepted, because that already requires the write access needed to delete files outright.

## Receipt lifecycle

- **Read** the prior receipt at the start of the prune step (tolerant — see fail-safe). Its entries, scoped as above, drive orphan detection.
- **Single-writer — over the whole mutation section, not just the receipt I/O.** An **exclusive advisory lock** on a sibling lockfile (`install-receipt.lock`) is acquired **before any install or prune filesystem mutation that contributes to the receipt**, and held through *install outcomes → prune → atomic receipt write*. Locking only `read → write` is **not** enough: install runs before prune, so a concurrent run could install a route file that a second (locked) run's prune deletes, after which the first run still records ownership of a now-deleted path — resurrecting the stale entry the lock was meant to prevent, and later deleting a user's replacement file there. Two concurrent installs also race on the dest trees themselves, so serializing the full mutation section is correct regardless. A run that cannot acquire the lock fails fast ("another install is in progress") rather than racing; the installer is infrequent and serial, so the lock is cheap insurance, not a bottleneck. (An optimistic generation/re-read-and-verify-on-disk before recording `installed_this_run` and before `os.replace` is an acceptable alternative; the held lock is simpler and preferred.)
- **Write** the new receipt at the **end of a successful, non-dry-run run** (after install and any prune complete), atomically (temp file + `os.replace`), computing the `integrity` digest over the canonical serialization just before the write. Written on **every** such run — not only under `--prune` — so the record never goes stale; *pruning* the diff stays gated behind `--prune`/`--prune-only`, but *recording* is unconditional. The top-level `roots` allowlist is updated the same run as `prior_roots ∪ this run's live install roots`, so a legitimate root persists across a plugin's retirement (and is what later validates that retired plugin's entries). Roots accumulate; optional housekeeping may drop a root once no entry references it and it is not a live root (a shrink-only step that can never admit a new root).
- **The receipt mirrors disk.** The new receipt is **not** a blind overwrite of staged items, nor an owner-scoped carve-out. It is the single invariant *an entry leaves the receipt only when it actually leaves the disk or its ownership is relinquished, and enters only when actually written to disk*:
  `new_receipt = (prior_receipt − pruned_this_run − relinquished_this_run) ∪ installed_this_run`, unioned by `path` with the `installed_this_run` entry winning (refreshed `sha256`).
  `relinquished_this_run` is previously-recorded paths whose ownership we hand back to the user this run — currently the **consent-declined overwrites of already-recorded entries** (see below).
- **`installed_this_run` is what the install layer actually wrote, not what was planned.** It is the **per-item install outcome** reported by the install layer: owned entries that were **created, updated, or skipped-identical** (already on disk as our bytes). It explicitly **excludes**:
  - **consent-declined overwrites** — when a user declines to overwrite a changed dest, the installer leaves the *user's* file untouched (`sync._consent_to_overwrite` → keep existing) and tallies it as `skipped`. That path is the user's content, not ours, so it is excluded from `installed_this_run`. **Crucially, if it was *already in the prior receipt* (we installed it on an earlier run, the user has since edited it, and now refuses our overwrite), it is also added to `relinquished_this_run` and thereby removed from the new receipt** — a declined overwrite of a recorded path is an ownership hand-back. Without this, the prior entry would carry forward and a later source removal would delete the user's edited file. (The receipt must record from the install layer's *outcome*, **not** the plan and **not** the raw `skipped` tally, which conflates skipped-identical with consent-declined.) When hash-aware prune lands (`fkewj`) this can soften to "keep but never auto-delete"; v1 relinquishes.
  - **the entire install half when it does not run** — under `--prune-only`, `installed_this_run` is empty, so the receipt is exactly `prior_receipt − pruned`. The staging plan is still built (it drives orphan detection), but nothing was placed on disk, so nothing is recorded. (On first adoption / empty receipt, `--prune-only` therefore prunes nothing and records nothing — a clean no-op.)
  The invariant is correct for every mode with no further special-casing: a plain install prunes nothing, so nothing is dropped and written entries are refreshed; a `--prune` run drops exactly the entries it removed; a `--tools=claude` subset run never prunes codex/gemini/opencode entries, so they carry over untouched; an orphan detected but **not** removed (no `--prune`) stays recorded *because it is still on disk*; and a consent-declined overwrite of a recorded path is relinquished, because that file is now the user's. Writing "intended" state instead would silently lose track of files left behind — the exact litter this work removes.
- **`--dry-run` writes nothing** — no receipt write, no deletion. Preview only.
- **Missing vs corrupt are different — and only missing bootstraps.** The receipt is now load-bearing state, so a file we *cannot read* must not be silently discarded:
  - **Missing** (file absent) → **bootstrap empty**: prune nothing, write a fresh receipt from this run's installs. This is the agreed clean-break adoption — pre-receipt litter that was never recorded is simply not seen; everything installed from adoption forward is covered. No migration code, no legacy glob sweep.
  - **Corrupt / unreadable / unknown `schema_version` / `integrity` mismatch** (file present but unusable or changed-since-write) → **fail-closed**: **disable pruning for this run and do NOT overwrite the receipt**, emitting a clear diagnostic (e.g. "install receipt at `<path>` is unreadable; skipping prune and leaving it untouched — reset or migrate it to re-enable pruning"). Treating a corrupt receipt as empty and then rewriting it would, on a scoped run like `--tools=claude`, replace the whole central record with only this run's entries — silently erasing codex/gemini/opencode/plugin ownership and stranding those files as unprunable litter. The install half still runs; only prune and the receipt write are suppressed until the state file is sound.

## Components (each independently testable)

| Unit | Responsibility | Notes |
|---|---|---|
| `ownership` classifier | `StagedItem → bool`: wholesale-owned & prune-eligible? | Pure; excludes merge-targets |
| `Receipt` / `ReceiptEntry` model + JSON (de)serialize | Data + schema-versioned round-trip | New `core/receipt.py` |
| receipt **store** | read (missing → empty; corrupt → distinct "unreadable" signal) · write (atomic temp+replace) | I/O isolated; pure core stays pure |
| receipt **builder** | per-item install outcomes → in-scope `ReceiptEntry` set | Created/updated/skipped-identical only; empty under `--prune-only` |
| orphan **differ** | (prior receipt ∩ scope, path-validated) − `desired_staged_keys` → `list[Orphan]` | **Replaces** `scan_orphans`; diffs against the staged plan, **not** `installed_this_run` |

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
- **Consent-declined overwrite.** The user declines to overwrite a changed dest, so the installer keeps the *user's* bytes. The per-item outcome is `declined`: it is excluded from `installed_this_run`, **and** — if the path was already in the prior receipt — added to `relinquished_this_run` so it is dropped from the new receipt entirely. Either way the path is no longer claimed as ours and never becomes an orphan, whether the decline happens at first adoption (never recorded) or mid-life (recorded earlier, edited, now relinquished). (Carrying a declined prior entry forward would later delete the user's edited file when the source is dropped.)
- **Corrupt receipt mid-life.** A present-but-unreadable receipt (hand-edit, partial write, version we don't understand) → prune is **disabled** and the receipt is **left untouched** for that run, with a diagnostic. It is never silently replaced by this run's partial view, which would strand other owners' files. Distinct from a *missing* receipt, which legitimately bootstraps empty.
- **Malformed receipt path.** An entry whose `path` is absolute, contains `..`, or resolves outside its recorded `root` is rejected by the path trust boundary → skipped, never an orphan. A `root` that disagrees with live code for a tool/discovered-plugin owner is likewise rejected (live wins). A *damaged* receipt therefore prunes **less**, never wild. (Per *Trust model*, a deliberately forged retired-plugin entry is trusted — out of scope, equivalent to direct home write access.)
- **Retired plugin (source removed).** A plugin previously installed and recorded, whose `src/plugins/` source is later removed or renamed, is no longer *discovered*. Because `scope` also includes **prior-receipt plugin owners**, its recorded route files (`owner=plugin`) are still in scope → orphaned → pruned (their recorded `root` is still in the persisted `roots` allowlist, so validation passes without live discovery); any content it overlaid into a tool tree is owned by that tool and pruned through the tool's scope. Without the prior-receipt-owner rule this whole plugin's files would be permanent litter — the precise failure this design exists to remove.
- **`--prune-only` over a populated receipt.** The install half is skipped, but the **staging plan is still built** — so orphan detection diffs the prior receipt against `desired_staged_keys` and prunes **only** entries no longer in the plan; every still-wanted entry is preserved. (Diffing against `installed_this_run` here would be catastrophic — it is empty, so *all* scoped entries would look orphaned. The differ uses the desired plan precisely to avoid that.) The receipt write uses `installed_this_run` (empty) → `prior − pruned`; the unwritten plan is never recorded as owned.
- **`--prune-only` on an empty / fresh receipt.** No prior receipt → no orphans → clean no-op; nothing recorded.
- **First run / fresh adoption.** No prior receipt → empty → prunes nothing, writes the first receipt from what this run installed. Pruning begins on the second run.

## Testing strategy

Unit (driven through `ScriptedIO`; 90% branch floor per package gate):

- **Ownership classifier truth table** — skills/agents/commands/rules recorded; `settings.json` (`JsonUnionStrategy`) and append-merged instruction files **not** recorded.
- **Differ scope matrix** — (a) untargeted tool's entries survive a `--tools=` subset run; (b) excluded plugin's entries are pruned; (c) cross-tree relocation (`zoom-out`) prunes the three non-Claude copies and keeps Claude's; (d) **retired plugin** — a recorded plugin no longer in the discovered set still has its route files orphaned (prior-receipt-owner scope), and its tool-tree overlay entries orphaned through the tool's scope.
- **Receipt store** — round-trip (with `integrity` computed/verified); **missing** → empty; **corrupt / malformed / unknown-`schema_version`** → distinct "unreadable" signal (not empty).
- **Integrity gate** — a parseable receipt with a **self-consistent unintended retired-plugin `root` in `roots` + a matching entry** but a **broken/absent `integrity` digest** → treated as corrupt → **fail closed, prunes nothing** (Codex's accidental-corruption case); the same content **with a valid digest** is trusted (the documented forgery boundary).
- **Per-item outcome / consent-declined** — a changed dest the user declines to overwrite is tallied `skipped` by `Counters` but reported `declined` per-item, and is **not** recorded; a created/updated/skipped-identical path **is** recorded.
- **Mid-life declined-overwrite relinquishment** — a path **in the prior receipt** that the user edits and then declines to overwrite is **removed** from the new receipt (relinquished); a subsequent source removal + `--prune` then does **not** prune the user's edited file (it is no longer recorded as ours).
- **Path trust boundary** — entries with absolute paths, `..` components, or a `path` outside their recorded `root` are skipped; **a forged `root` for a live owner is overridden by live code** (`{owner:"claude", root:".ssh"}` → rejected, claude's live root is `.claude`); a retired plugin's entry whose `root` is in the persisted `roots` allowlist passes and IS pruned, while an accidental garbage retired `root` not in the allowlist is rejected. (A self-consistent forged retired-plugin entry is trusted — documented as out of scope per *Trust model* — so that case is asserted as a known boundary, not a rejection.)
- **Symlinked install root** — with `~/.beads` symlinked outside `$HOME`, a legitimate orphan under the resolved target IS pruned, but a `path` whose resolved location escapes `(home/root).resolve()` (via symlink components) is rejected; containment is checked on resolved paths.
- **Corrupt receipt during a scoped run** — `--tools=claude` against a corrupt receipt prunes nothing **and** leaves the receipt file unchanged (codex/gemini/opencode/plugin ownership preserved).
- **`--prune-only` over a populated receipt** — diffing against `desired_staged_keys` prunes **only** entries absent from the current plan and **preserves every still-staged entry** (regression for the "prune-only deletes the whole tree" trap); the receipt write records nothing new.
- **Single-writer lock** — a second run that cannot acquire the lock fails fast; the lock spans the full install→prune→write section, so a run pruning an excluded plugin while another installs that same plugin cannot leave the receipt claiming a deleted path (no stale resurrection).
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
- Orphan detection diffs the prior receipt against the desired **staged plan** (`desired_staged_keys`, built even under `--prune-only`), **not** against `installed_this_run`. `--prune-only` over a populated receipt prunes only entries absent from the plan and preserves every still-staged entry (never deletes the installed tree).
- Cross-tree relocation (shared → single-tool; the `zoom-out`/`cr7bi` case) prunes the stale per-tool dest copies.
- `~/.beads/scripts` is covered (the `abn9.37.1.1` regression seed).
- `_BEADS_TOOL` / `_BEADS_NAMESPACE` and the `[prune]` section are gone; removing them is the tell the scan is genuinely general.
- The receipt is written on every successful, non-dry-run run; `--dry-run` writes nothing; pruning the diff is gated behind `--prune`/`--prune-only`.
- The receipt mirrors disk: `new = (prior − pruned − relinquished) ∪ installed_this_run`. It records from **per-item install outcomes** (created/updated/skipped-identical), never from the plan — a **consent-declined** overwrite leaves the user's file and is **not** recorded, and a declined overwrite of an **already-recorded** path is **relinquished** (removed from the receipt) so a later source removal can never delete the user's edited file; `--prune-only` records no new entries.
- A **missing** receipt bootstraps empty (clean-break adoption, no legacy sweep). A **corrupt/unreadable/unknown-version/`integrity`-mismatch** receipt fails closed: pruning is disabled and the receipt is left untouched (never overwritten with a partial scoped view), with a diagnostic.
- The receipt carries an **`integrity` checksum** over its canonical content, recomputed on read; any accidental change (including a self-consistent one to `roots` + an entry) breaks it and fails closed. This makes "accidental corruption never prunes wild" a delivered guarantee, including for the trusted-state retired-plugin path.
- Path containment is **symlink-aware**: it is enforced on fully-resolved paths against the resolved install root (`(home/root/path).resolve()` under `(home/root).resolve()`), so a symlinked root prunes within its real target and a symlink-escape `path` is rejected. The enforced boundary is "within the resolved install root", not "under `$HOME`" (a stricter `$HOME`-only mode is an opt-in that rejects symlinked roots).
- The receipt is a validated deletion-authority input under an explicit **trust model** (receipt = trusted installer state, like a package manager's file DB): tool and discovered-plugin roots are taken from **live code** (a forged/corrupt `root` for them is overridden), retired-plugin roots are validated against the persisted `roots` allowlist behind the `integrity` gate, and structural checks (relative, no `..`, containment) bound every path. Accidental corruption fails closed; only a deliberately forged receipt that recomputes `integrity` AND impersonates a retired plugin is trusted — documented as out of scope (equivalent to direct home write access).
- The **full install → prune → receipt-write** mutation section is single-writer (advisory lock held across all of it, not just the receipt I/O): concurrent runs serialize or fail fast, so no run can record ownership of a path a concurrent run deleted (no lost updates, no stale resurrection).
- Tests cover the ownership classifier, the differ scope matrix (untargeted tool, excluded plugin, cross-tree relocation, retired plugin), receipt-store missing-vs-corrupt, integrity-gate (broken digest over self-consistent corrupt content → fail closed), per-item consent-declined, mid-life declined relinquishment, path trust boundary (including retired-plugin-passes + tampered-root-rejected), corrupt-receipt-during-scoped-run, `--prune-only`-over-populated-receipt (preserves still-staged), single-writer lock (install/prune race), receipt-mirrors-disk, and dry-run.
- `make ci-installer` green.
