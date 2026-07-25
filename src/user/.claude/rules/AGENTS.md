# Claude-Specific Rules

Rules in this directory are Claude Code-specific and are installed into `~/.claude/rules/`. They append-merge with same-named plugin files.

Installation is gated on admission: a rule without a complete `admission:` record (`prevents` **or** `provides`, plus `cost` and `remove_when`) in its front matter is dropped at deploy and pruned. This folder is empty today; the record-less rules moved to `archive/src/user/.claude/rules/`.

## Companion readmes

Longer rationale, incident history, and examples live in `rules-readmes/` under the same base name (e.g. `worktree-safety.md` → `rules-readmes/worktree-safety-readme.md`). Readmes are source-level documentation only — they are not installed. Rule files are self-contained.
