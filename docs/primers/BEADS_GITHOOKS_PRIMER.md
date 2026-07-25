# Beads Git Hooks Primer

`bd hooks install` wires five git hooks (`pre-commit`, `post-merge`,
`pre-push`, `post-checkout`, `prepare-commit-msg`) as thin shims
(`bd hooks run <name>`) wrapped in `# --- BEGIN/END BEADS INTEGRATION`
markers, so upgrading `bd` updates hook behavior automatically and any
pre-existing hook content (husky, lefthook, etc.) outside the markers is
preserved. Install target: `.git/hooks/` by default, or `.beads/hooks/`
with `--beads` (recommended for the Dolt backend — sets `core.hooksPath`).

All hooks run any pre-existing `.old` chained hook first, and are bounded
by a timeout (`BEADS_HOOK_TIMEOUT`, default 300s) so they can never hang a
git operation. A missing/uninitialized Dolt DB (exit code 3) is treated as
a non-blocking warning, not a failure.

The behavior below has changed meaningfully between what's checked out in
this fork and the upstream stable release — see each section.

---

## Section 1 — This fork (`scotthamilton77/beads`, main @ `6a73edde7`)

In this version, `issues.jsonl` **is** the cross-machine sync mechanism:
Dolt state exports to it on commit, and it imports back into Dolt on
pull/merge/checkout.

### What each hook does

| Hook | Purpose |
|---|---|
| `pre-commit` | Exports current Dolt issue state to `issues.jsonl` and stages it, so issue-tracker state lands in the *same* commit as the code change. |
| `post-merge` | Imports `issues.jsonl` into Dolt after a pull/merge, so issues created on other machines enter the local DB before the next auto-export can overwrite them with a stale view. |
| `post-checkout` | Same import, but only on branch switches (flag=1) — not on file-mode checkouts. |
| `pre-push` | No-op placeholder — only runs a chained `.old` hook if present. No bd-specific logic. |
| `prepare-commit-msg` | Not JSONL-related. Appends an `Executed-By: <agent>` trailer to the commit message when `BD_ACTOR` is set — provenance for agent-authored commits. |

### Configuration

Three settings control the JSONL sync, all default **`true`**:

| Setting | Default | Controls |
|---|---|---|
| `export.auto` | `true` | Whether `pre-commit` exports Dolt → `issues.jsonl` at all |
| `export.git-add` | `true` | Whether the exported file is auto-staged into the commit |
| `import.auto` | `true` | Whether `post-merge` / `post-checkout` import `issues.jsonl` → Dolt |

Related: `export.path` (default `issues.jsonl`, relative to `.beads/`),
`export.interval` (min time between auto-exports, default `60s`),
`export.error_policy` (default `strict` for manual exports),
`auto_export.error_policy` (default `best-effort` for hook-driven exports).

```bash
bd config set export.auto false
bd config set export.git-add false
bd config set import.auto false
```

### Impact of on vs. off

**On (default):**
- Every commit carries a current `issues.jsonl` snapshot — Dolt and git
  history stay in lockstep.
- Every pull/merge/branch-switch pulls teammates' issue changes into local
  Dolt before the next export can overwrite them.
- Cost: a `bd export`/`bd import` subprocess runs on the relevant git
  operations (fast, bounded by the hook timeout, tolerant of no-op cases).

**Off:**
- `export.auto=false` — commits proceed with no JSONL refresh; the file
  silently goes stale relative to Dolt. Requires manual `bd export`.
- `export.git-add=false` — export still happens but isn't staged; you must
  `git add` it yourself (easy to forget).
- `import.auto=false` — pulling a branch with new issues does *not* load
  them into local Dolt. The next auto-export can then overwrite
  `issues.jsonl` with your own older view, silently dropping teammates'
  issue additions from the tracked file until someone runs `bd import`
  manually.

The defaults exist to prevent silent data loss between multiple
machines/contributors writing issues concurrently. Disable only with a
specific reason.

---

## Section 2 — Latest stable upstream (`gastownhall/beads` v1.1.0)

Upstream redesigned the sync model. **A configured Dolt remote
(`sync.remote`) is now the source of truth and the actual cross-machine
sync mechanism** (via `bd dolt push`/`bd dolt pull`, e.g. `bd sync`).
`issues.jsonl` is downgraded to an *export* — useful for viewers,
interchange, and backup — not a sync channel. Hooks warn you if you're
relying on JSONL without a Dolt remote configured.

### What each hook does (deltas from Section 1)

| Hook | Purpose |
|---|---|
| `pre-commit` | Exports to `issues.jsonl` **only if** `.beads` paths are staged, **and** skips entirely if the export file is staged for deletion (so `git rm issues.jsonl` sticks instead of being silently revived). Warns to stderr if no `sync.remote` is configured. |
| `post-merge` / `post-checkout` | Import is now a **legacy fallback only** — it's skipped entirely once `sync.remote` is configured, because upsert-only JSONL import can't reconcile against a real remote the way `bd dolt pull` can. |
| `pre-push` | Still a no-op placeholder — unchanged. |
| `prepare-commit-msg` | Unchanged — still appends `Executed-By: <agent>` when `BD_ACTOR` is set. |

Timeout wrapper hardened: falls back `timeout` → `gtimeout` → `perl -e
alarm` → unwrapped, for portability (mainly macOS without coreutils).

### Configuration

| Setting | Default | Controls |
|---|---|---|
| `export.auto` | **`false`** (was `true`) | Whether `pre-commit` exports Dolt → `issues.jsonl` at all |
| `export.git-add` | **`false`** (was `true`) | Whether the exported file is auto-staged into the commit |
| `import.auto` | `true` (unchanged) | Whether the *legacy* JSONL import runs — no-ops once `sync.remote` is set |
| `import.path` | `issues.jsonl` (**new**) | Import source path, separate from `export.path`; falls back to `export.path` for projects that customized it before `import.path` existed |
| `sync.remote` | unset (**new**) | Dolt-compatible remote URL — the real sync mechanism. Set via `bd dolt remote add origin <url>`. `sync.git-remote` is a deprecated alias. |

```bash
bd dolt remote add origin <dolt-remote-url>   # establishes the actual sync channel
bd dolt push                                   # / bd sync
bd config set export.auto true                 # opt back in to JSONL export, if wanted
```

### Impact of on vs. off

**With `sync.remote` configured (the intended path):**
- `bd dolt push`/`bd dolt pull` (or `bd sync`) is the real cross-machine
  sync — full reconciliation, not upsert-only.
- `import.auto` is inert (skipped) regardless of its value.
- `export.auto`/`export.git-add` are independent, off by default — turn
  them on only if you want a JSONL snapshot for viewers or backup; it
  plays no role in sync correctness.

**Without `sync.remote` configured:**
- Hooks print a warning on the relevant operation: no Dolt remote
  configured, `.beads/issues.jsonl` is an export, not sync or source of
  truth — with a suggested repair (`bd dolt remote add origin <url> && bd
  dolt push`).
- `import.auto=true` (default) still runs the legacy JSONL import path, so
  behavior degrades gracefully to something close to Section 1 — but this
  is now explicitly a compatibility fallback, not the intended steady
  state, and generates ongoing warnings pushing you toward configuring a
  real remote.

**Practical takeaway:** upgrading this fork to a version at or past
v1.1.0 changes JSONL sync from "on by default and load-bearing" to "off
by default and cosmetic." Migrating means running `bd dolt remote add` and
verifying `bd sync`/`bd dolt push`/`bd dolt pull` before assuming issue
state is actually shared across machines.
