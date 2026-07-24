# Rules

Rules in this directory are installed as always-on constraints for all supported tools — if they are admitted. A rule without a complete `admission:` record (`prevents`, `cost`, `remove_when`) in its front matter is dropped at deploy and pruned from every tool's config. This folder is empty today; the record-less rules moved to `archive/src/user/.agents/rules/`.

## Companion readmes

Longer rationale, incident history, and examples live in `rules-readmes/` under the same base name (e.g. `bash-scripting.md` → `rules-readmes/bash-scripting-readme.md`). Readmes are source-level documentation only — they are not installed. Rule files are self-contained.
