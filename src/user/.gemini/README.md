# src/user/.gemini/ — Google Gemini CLI Content

Gemini-specific content that `scripts/install.sh` copies into `~/.gemini/`
when Gemini is selected by the installer, such as when `~/.gemini/` already
exists or when the user passes `--tools=gemini`.

## What lives here

- `GEMINI.md.template` — Top-level instruction file. It is a single
  `DYNAMIC-INCLUDE` of the shared zero-based core in
  `src/user/.agents/USER-CORE.md.template`, which the installer flattens in at
  deploy time; it carries no text of its own. There is no Gemini-specific
  instruction content, so this is the whole of the Gemini tree's prose.

## Where it installs

Into `~/.gemini/` (user-scoped Gemini CLI config). The installer strips the
`.template` suffix on copy.

Shared content from `src/user/.agents/` also installs into `~/.gemini/` — the
skills, and the rules directory, which is empty today. No agent definitions and
no persona templates exist to install: the always-on surface is zero-based and
carries no identity content.

## Who it's for

Google Gemini CLI users who want the same shared instruction core they'd get
under Claude Code. The skills stage here too, but whether the Gemini CLI reads a
deployed skill at all is not established by any vendor documentation, so this
project does not model its skill loading and reports no skill measurement for
it — expect the instruction core to carry the weight.

See the [root README](../../../README.md) for install flow and customization
pointers.
