# Claude-Specific Rules

Rules in this directory are Claude Code-specific and are installed into `~/.claude/rules/`. They append-merge with same-named plugin files.

Installation is gated on admission: a rule without a complete `admission:` record (`prevents` **or** `provides`, plus `cost` and `remove_when`) in its front matter is dropped at deploy and pruned. `delegation.md` is the only rule here; the record-less rules moved to `archive/src/user/.claude/rules/`.

## Companion readmes

When a rule needs longer rationale, incident history, or examples than belong in the deployed bytes, put them in a sibling `rules-readmes/` directory under the rule's base name plus `-readme` (`<rule>.md` → `rules-readmes/<rule>-readme.md`). Readmes are source-level documentation only — they are not installed, so the rule file must stand alone without one. `rules-readmes/` has no contents today; create it with the first rule that needs one.
