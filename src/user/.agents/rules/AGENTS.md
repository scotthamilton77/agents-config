# Rules

Rules in this directory are installed as always-on constraints for all supported tools — if they are admitted. A rule without a complete `admission:` record (`prevents` **or** `provides`, plus `cost` and `remove_when`) in its front matter is dropped at deploy and pruned from every tool's config. This folder is empty today; the record-less rules moved to `archive/src/user/.agents/rules/`.

## Companion readmes

When a rule needs longer rationale, incident history, or examples than belong in the deployed bytes, put them in a sibling `rules-readmes/` directory under the rule's base name plus `-readme` (`<rule>.md` → `rules-readmes/<rule>-readme.md`). Readmes are source-level documentation only — they are not installed, so the rule file must stand alone without one. Neither this directory nor `rules-readmes/` has any contents today; create the readme directory with the first rule that needs it.
