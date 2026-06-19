# `scripts/` — installer maintenance notes

`install.sh` (74 KB) is the **live behavioural spec** for the Python port under
`packages/installer/` — not dead code. When editing it:

- **Adding a managed namespace dir** (`commands` / `skills` / `agents` / `rules`
  / `formulas`): update **both** `backup()`'s namespace list **and**
  `scan_orphans`' `prune_subdirs` list. Miss the first and backups leak into
  runtime-discoverable locations; miss the second and prune skips orphans.
- **Never name a shell variable `path` under zsh.** zsh ties lowercase `path` to
  `PATH`, so assigning it breaks every external command in scope (`date`, `rm`,
  …). Same for `cdpath` / `fpath` / `manpath` / etc. — use `file_path`,
  `target_path`, etc. `install.sh` is a bash-4/zsh polyglot; use the `_ARRAY_BASE`
  shim (1 for zsh, 0 for bash) for any index-based array loop.
- **Auto-detect is config-dir-based, not CLI-presence.** It always includes
  `claude`; it adds `codex` / `gemini` only when `~/.codex/` / `~/.gemini/`
  exists, or when `--tools=` forces them. Don't describe it as "detecting
  installed CLIs".
- **Namespace-dir replace is backup-free in bash, backed-up in Python — an
  intentional divergence.** `sync_directory` replaces a *changed*
  `commands` / `skills` / `agents` / `rules` / `hooks` item with
  `rm -rf "$dest_item"; cp -R` and **no `backup()` call** — a user-modified
  skill/agent/hook is silently destroyed. The Python port (`packages/installer/`)
  backs the item up to `<namespace>-backup/` before replacing, deliberately
  fixing that latent data-loss bug. **Consequence for parity comparisons:** a
  real-home (drifted-state) `install.sh`-vs-`install.py` diff shows Python-only
  `<namespace>-backup/…` directories and `<namespace>/<file>.backup-*` entries —
  expected (Python preserving content bash would destroy), **not** a regression.
  The hermetic golden-master suite never seeds a content-drifted namespace dir,
  so it does not surface this; a real-home smoke does.

## Known bug — `flatten_agents_md` drops the last named rule

`flatten_agents_md` splits a `<!-- DYNAMIC-INCLUDE-RULES: a,b -->` marker with
`printf '%s' "$rule_names" | tr ',' '\n'` and feeds it to a `while read` loop.
`printf '%s'` emits no trailing newline, so the **last** comma-field arrives with
no terminating newline and `read` returns non-zero on it — and the inner rules
loop omits the `|| [[ -n "$rule_name" ]]` guard that the function's outer
line-reading loop has. The result: the last field of every named-RULES marker is
silently dropped. A single-name subset (`a`) inlines nothing; `a,b` inlines only
`a`. The bug is masked whenever the trailing field is a no-op anyway (empty entry
or a missing rule), which is why it went unnoticed — no live template uses the
marker yet.

The Python port (`packages/installer/src/installer/core/templates.py`,
`_resolve_named_rules`) **intentionally diverges to the correct behaviour** — it
inlines every listed rule, including the last/only one. The golden-master
differential (`tests/golden_master/test_parity_named_rules.py`) pins this: it
asserts parity only on bug-neutral inputs and asserts the corrected Python output
on a single-name subset.

Fix for the bash side (deferred — `install.sh` is slated for retirement once the
port reaches full parity): add the `|| [[ -n "$rule_name" ]]` guard to the inner
rules loop, matching the outer loop. Do this before any real template adopts the
`DYNAMIC-INCLUDE-RULES` marker.
