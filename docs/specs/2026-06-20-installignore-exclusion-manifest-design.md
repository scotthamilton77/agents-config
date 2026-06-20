# Design: Shared `.installignore` exclusion manifest

**Date:** 2026-06-20
**Status:** draft (design — awaiting review)
**Scope:** Introduce a single repo-root `.installignore` manifest consumed by *both* installers (legacy `scripts/install.sh` and the Python rewrite at `packages/installer/`) at the staging choke point, replacing the Python-only hardcoded `DEAD_MARKERS` frozenset. Kills the bash↔python "which source files are excluded" divergence at its root, closing the three RED golden-master parity tests.

## Summary

Bash and Python disagree on which source files are **excluded** from the install fileset. Python has a hardcoded staging filter `DEAD_MARKERS = {AGENTS.md, CLAUDE.md, GEMINI.md}` (`core/staging.py`); bash has **no equivalent**. So a folder-doc marker like `src/user/.agents/rules/AGENTS.md` leaks on the bash side two ways: its prose gets **inlined** into the assembled per-tool instruction file (content-leak), and the file itself gets **deployed** standalone into the installed tree (file-leak).

The fix is a single source of truth — a gitignore-flavored (not gitignore-complete) `.installignore` at the repo root — that **both** installers consult at the one staging step that sits upstream of both leak surfaces. Python's hardcoded `DEAD_MARKERS` is removed in favor of it. The grammar is a deliberately trivial subset (exact basenames + directory names; no globs, no `**`, no negation, no anchoring) so the two implementations are provably equivalent and can be parity-tested against each other.

## Motivation / root cause

The divergence is not a one-off bug; it is a **class**. Today's symptom is `rules/AGENTS.md` (added in the recent rules-rightsizing work, #186), but the underlying defect is that exclusion lives in two places with two different fidelities: a hardcoded list in Python and *nothing* in bash. Every future namespace dev-doc someone adds re-opens the same leak on the bash side.

A shared manifest collapses the two-implementation drift into one reviewable data file. The trivial grammar keeps the per-installer matcher to a few lines each, and a matcher-parity test pins them together.

### Why a manifest rather than codifying the rule in code

The root cause *is* "the same rule implemented (or not) twice." Re-encoding it as logic in both bash and Python recreates the exact drift being killed. Only a shared data file consulted by both structurally prevents it. The trivial grammar means the two *parsers* are the only duplicated logic, and they are parity-tested.

## The manifest

- **Location:** repo-root `/.installignore`. Outside `src/`, so it never stages itself. Patterns are basenames/dirnames, so location is about discoverability, not anchoring.
- **Grammar (simple subset):**
  - One entry per line. `#` starts a comment line; blank lines ignored.
  - **Basename entry** — an exact filename (e.g. `AGENTS.md`). Matches a file whose basename equals it.
  - **Directory entry** — a name with a trailing `/` (e.g. `rules-readmes/`). Matches a directory whose name equals it (sans slash).
  - **No** `*`/`?` globs, **no** `**`, **no** negation (`!`), **no** path anchoring. Equality only.
- **Entries (the full known set), with reachability provenance from the source audit:**

| Entry | Kind | Leaks **today**? | Evidence |
|---|---|---|---|
| `AGENTS.md` | basename | **YES** | `src/user/.agents/rules/AGENTS.md` → content-leak (DYNAMIC-INCLUDE-ALL-RULES inlines it) **+** file-leak; `src/user/.agents/skills/AGENTS.md` and `src/user/.claude/rules/AGENTS.md` → file-leak. Python drops via `DEAD_MARKERS`; bash does not. This is the RED. |
| `CLAUDE.md` | basename | defensive | Mirrors `DEAD_MARKERS`. No plain `CLAUDE.md` sits inside a staged subdir today (only `src/user/.claude/CLAUDE.md` at a namespace root, which is never staged). |
| `GEMINI.md` | basename | defensive | Mirrors `DEAD_MARKERS`. No plain `GEMINI.md` in a staged subdir today. |
| `README.md` | basename | defensive | All five (`.agents`, `.claude`, `.codex`, `.gemini`, `.opencode`) sit at namespace roots → never staged (bash copies only `*.md.template` globs + enumerated subdirs, never wholesale tool dirs). |
| `SESSION-PRIMER-README.md` | basename | defensive | At `.agents/` root → never staged. |
| `rules-readmes/` | directory | defensive | Sibling of `rules/`; never appears in any staged-subdir enumeration, including the plugin staging loops. |

**Only `AGENTS.md` is a live leaker.** The other five are the rest of the *class*, listed so the next dev-doc dropped into a staged subdir cannot leak. The audit table is the spec's record of the bead's "audit README/rules-readmes reachability" requirement: real leaker folded in, non-leakers documented as already-excluded-by-namespace-scoping.

### Loading & failure semantics (fail-closed)

The manifest now encodes load-bearing exclusion policy, so a *missing* manifest must never silently mean "exclude nothing" — that would re-enable the exact leaks this work removes, **identically on both installers** (the shared-wrongness case the parity oracle cannot see).

- **Absent or unreadable** `/.installignore` → **fail-fast**: both installers abort with a clear error (e.g. "`.installignore` not found at `<resolved repo root>`; refusing to install with exclusions disabled") rather than proceeding. This converts every "missing / wrong-root / absent-in-fixture" mode from a silent leak into a loud error.
- **Present but empty** (no entries) → allowed; it is an explicit choice, and is backstopped by the Python invariant test (a known leaker slipping through turns that test red).
- Both installers resolve the manifest relative to their own location-derived repo root (bash: `PROJECT_ROOT` from `$0`; Python: `repo_root` from `__file__`, or the test-injected `repo_root`) — the same root used to resolve `src/`, so the manifest travels with the source it governs.

## Application model — why bare basenames are safe

The matcher is consulted **at the staging choke point, on the direct children of each staged subdir, before any `.template` suffix is stripped** — exactly where Python's `DEAD_MARKERS` runs today.

The same basename is both a thing-to-exclude (the namespace dev-doc `AGENTS.md`) and a thing-to-keep (the tool-root instruction file). Bare basenames are nonetheless safe because in *source* the instruction file is named `AGENTS.md.template`, and equality matching never hits `AGENTS.md.template` — so no namespace-anchoring (`*/AGENTS.md`) is needed.

Because the matcher runs over **direct children only**:
- `rules/AGENTS.md`, `skills/AGENTS.md` (direct children of staged subdirs) → matched, excluded.
- A nested file such as `skills/<skill>/README.md` is *not* a direct child of `skills/`; it is staged as part of the skill folder's content and is **not** matched. This is correct — it is skill content, not a namespace dev-doc. (No such file exists today; the rule simply does not reach into folder content.)
- The real instruction files are staged via separate `*.md.template` globs, never through the matched subdir iteration, so they are untouched.

## Dual consumption — one choke point each

### Python (`packages/installer/`)
- Load the manifest **once** in `stage_and_transform` (`core/orchestrator.py`), thread it down into `stage_namespace` (`core/staging.py`).
- **Replace** the hardcoded `DEAD_MARKERS` frozenset and its file-name check with manifest membership: skip a direct-child entry when it is a file whose basename is in the manifest's basename set, or a directory whose name is in the manifest's directory set.
- **Fail-fast** if the manifest is absent or unreadable (see "Loading & failure semantics") — never default to an empty exclusion set.
- This single point already fans out to both deploy (`install_pipeline`) and prune (`scan_orphans`) — no second integration needed.

### Bash (`scripts/install.sh`)
- Consult the manifest inside `stage_content_from_dir` (the universal per-subdir staging helper): inside its `for item in "$src_dir"/*` loop, skip any direct child whose basename (for files) or name (for directories) is in the manifest.
- **Fail-fast** if `$PROJECT_ROOT/.installignore` is absent or unreadable — abort before staging, never proceed with exclusions disabled.
- This is **upstream of both leaks**: excluded files never enter staging, so the DYNAMIC-INCLUDE-ALL-RULES `find` over `$staging/.../rules` cannot inline them, and `sync_directory` cannot deploy them.
- **Single-point sufficiency (verified):** plain `.md` files reach deploy *only* through staged subdirs (`sync_directory`). `sync_templates` handles `*.md.template` only and never touches plain `.md`. So filtering at `stage_content_from_dir` covers both the staging loop and the sync loop, because both operate on already-staged content. (Do **not** move the filter to the sync layer — the two bash subdir loops, staging and sync, are separate, and a sync-layer filter would have to patch both.)
- Bash effort is **not** throwaway: `install.sh` retirement is **parity-gated** (it collapses to a thin `uv run` wrapper only once the golden-master suite goes green), with no version date. The RED tests are red *because* bash and Python disagree, so the manifest must land in both simultaneously to close them.

## Oracle — simplify, don't extend

The golden-master oracle's job is purely "does bash's installed tree equal Python's installed tree?" (`ParityResult.diff()` → `diff_trees(home_a, home_b)`). Today it carries `_is_namespace_dead_marker` (`tests/golden_master/_diff.py`), which **skips** dead markers on **both** trees before comparing — a band-aid that hides the known bash-installs/Python-omits divergence so the suite stays green.

**Delete `_is_namespace_dead_marker` and the skip entirely.** Once both installers exclude the dead-docs, neither tree contains them, so a plain tree comparison passes with zero special-casing. No `.installignore` awareness is threaded into the harness; the post-strip namespace-anchoring problem never arises because the oracle stops trying to reason about dead markers at all.

This is also **stronger** than today. The skip currently masks the *file-leak* on both sides — including on `test_bare_install_single_tool` (claude), which is **falsely green** today because its `~/.claude/rules/AGENTS.md` file-leak is hidden. Deleting the skip turns that test red for the right reason; the fix turns it (and the three flat-tool tests) green.

### What pure parity cannot see — and where that invariant goes instead

A parity comparison catches *divergence*, never *shared wrongness*. If both installers ever leak the **same** dead-doc **identically** — most realistically via a `.installignore` mis-edit that drops an entry — the trees still match and the suite stays green while both are wrong.

That invariant ("no dead-doc is ever installed") therefore lives **not** in the cross-installer oracle but as a small **Python unit test** against Python's own installed/staged output:
- Assert the **known confirmed leakers** (`src/user/.agents/rules/AGENTS.md`, `src/user/.agents/skills/AGENTS.md`) never appear in Python's installed tree.
- **Hardcode** these specific paths in the test — do **not** source them from `.installignore`. A manifest-sourced check goes blind to the exact manifest mis-edit it should catch.
- Rationale for this home: it tests the consumer of the manifest directly; it guards the realistic regression path; it keeps the oracle dumb; and it **survives the parity gate** (once `install.sh` is a wrapper, the parity oracle tests nothing about dead-docs, but this unit test still does).

## Matcher-parity test

A fixture set of `(path, expect: keep | drop)` run through **both** the bash matcher and the Python matcher, asserting they agree. Cases must include the asymmetry and edge points:
- `rules/AGENTS.md` → drop; `AGENTS.md.template` → keep (suffix mismatch); a tool-root `AGENTS.md` context → keep (not a staged-subdir direct child).
- `rules-readmes/` (directory) → drop; a nested `skills/<skill>/README.md` → keep (not a direct child).
- A comment line and a blank line in the manifest → ignored by both parsers.

This guards the only duplicated logic (the two trivial parsers/matchers). It retires with bash at the parity gate.

## Missing-manifest tests (fail-closed proof)

Explicit tests in **both** installer paths assert that an absent (or unreadable) manifest causes a **hard abort**, not a silent empty-exclusion install:
- **Python:** invoke the installer with a `repo_root` lacking `.installignore` → assert it exits non-zero / raises before staging, and that no namespace dead-doc is written.
- **Bash:** run `install.sh` against a `PROJECT_ROOT` lacking `.installignore` → assert non-zero exit and that nothing was staged.

No test-only "empty denylist" opt-out flag is introduced: the missing-manifest test asserts the abort directly, and the matcher-parity test supplies its own fixture manifest content rather than depending on the repo-root file.

## Outcome

- `test_bare_install_codex`, `test_bare_install_gemini`, `test_bare_install_opencode` go **green** — bash stops inlining `rules/AGENTS.md`, matching Python's (correct) omission.
- `test_bare_install_single_tool` (claude) stays green *for the right reason* after the skip is deleted (the previously-masked file-leak is now genuinely absent on both sides).
- **Gate:** `make ci-installer` (lint, format-check, typecheck, coverage, audit, entry-verify) must pass before push, plus the golden-master suite.

## Out of scope / non-goals

- **No gitignore semantics** — no `*`/`**` globs, negation, anchoring, or per-directory cascade. (If a future need for `*` globs appears, it is a separate, parity-tested grammar extension.)
- **No per-namespace cascade** — one root manifest only.
- **Not** removing `install.sh` — its retirement is parity-gated and tracked separately.
- **No change to which directories count as staged namespaces** — this work filters *within* the existing staged set, it does not add or remove namespaces.

## Risks / verification owed by the plan

- **Manifest path resolution & packaging.** Both installers resolve `/.installignore` from their own location-derived repo root (verified: bash `PROJECT_ROOT` from `$0`; Python `repo_root` from `__file__` / test-injected), so it is co-located with `src/` in all current modes (editable / `uv run`). Confirm fail-fast fires in all invocation modes (direct, dry-run, prune-only). **Caveat:** the manifest lives at repo-root, *outside* both `src/` and `packages/installer/`; if the Python installer is ever distributed as a *non-editable* wheel, repo-root `.installignore` would not be bundled. Fail-fast turns that into a loud error, not a silent leak — but if non-editable packaging is introduced, bundle the manifest as package data or relocate it inside the packaged tree.
- **Bash single-point sufficiency.** Re-confirm at implementation time that no path other than `stage_content_from_dir` stages plain `.md` files into a deployable location (the audit says only `sync_directory` does, fed from staging; verify no regression path via plugin loops).
- **Directory-exclusion semantics in bash.** `stage_content_from_dir` iterates `"$src_dir"/*`; ensure a directory entry (`rules-readmes/`) is matched by *name* and the whole subtree is skipped (it is staged via `stage_item` as a recursive copy today), not partially copied.
- **Coverage of the deleted skip.** Confirm deleting `_is_namespace_dead_marker` does not silently drop coverage that some other test relied on; the matcher-parity test and the Python invariant test together must cover what the skip's removal exposes.
- **`make ci-installer` coverage floor** on the changed Python (`staging.py`, `orchestrator.py`, the new manifest loader/matcher, the new tests).
