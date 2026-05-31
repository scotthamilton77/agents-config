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
