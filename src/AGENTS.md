# AGENTS.md — `src/`

The deployed configuration surface: every rule, skill, command, hook and
instruction template the installer deploys is authored here; the CLIs it puts
on PATH are built from `packages/`. Most content is documentation and templates
with no build step — changes follow existing formatting conventions per file
type. Shared content lives under
`src/user/.agents/` (staged into every active tool; see that directory's
`AGENTS.md` for the install model and the name-collision rules), per-tool
content under `src/user/.claude/`, `src/user/.codex/`, `src/user/.gemini/` and
`src/user/.opencode/`, and plugin content under `src/plugins/`. Each rules
directory carries its own `AGENTS.md` stating what currently lives there; read
it rather than inferring from the folder's contents.

Prompt prose authored here — lens mandates, dispatch briefs, anything a
dispatch site sends downstream — can be served to any routed model family
(Claude, GPT tiers, GLM, Kimi, Gemini), and no dispatch site varies its prompt
per model. Write that prose to the dialect every family tolerates: goal-level
framing with an explicit deliverable contract, no redundant or conflicting
imperatives, no manual chain-of-thought scaffolding, no ALL-CAPS pressure,
consistent delimiters. The provider citations behind each clause, and the
per-model *parameter* facts (temperature splits, token floors) that belong in
transport config rather than prose, are in
`docs/reference/2026-08-31-model-prompting-variance.md`.

Two gates read this tree, differently on purpose, and neither invokes the
installer:

- `content-tests` — the single gate over skill-shipped code. It runs every
  `.py`/`.js`/`.sh` suite it finds under `src/`, requires each shipped script
  to have a paired suite, and fails a suite that exits 0 without printing the
  clean-pass marker its runner declares — an empty run and a swallowed failure
  both exit 0 and would otherwise read as green. Those suites are gated code,
  not prose.
- `content-lint` — measures `src/` against the admission bar and its token
  caps. It stages the real tree for every tool and plugin and reports the
  always-on and per-skill numbers on a pass, so drift is visible before the
  cliff. It measures the *staged* tree, because the bar and the budget are
  properties of what deploys — and it fails on a directory staging never reads
  and nothing declares. `.installignore` is where a directory declares itself
  source-side, so an edit there changes what this gate measures.

Three things about this tree that a plain look misses:

- Every deployed artifact lives under a hidden directory (`src/user/.claude/`,
  `src/user/.agents/`, `src/plugins/*/.claude/`), so a plain `rg` over `src/`
  matches nothing and exits 0. Pass `--hidden` (or use `grep -r`), and never
  cap a census with `head`.
- Skill Python is held to `ruff check`, deliberately not `ruff format`: no gate
  formats it and the compact hand-formatting is the convention, so
  `ruff format --check` saying "would reformat" on a sibling is confirmation,
  not a finding.
- `*_test.py` / `*_test.js` under a skill deploy to user space with the skill
  and run inside other projects. A shipped test degrades to a skip, never a
  false FAIL, when a repo-internal path (this repo's `project-config.toml`) is
  absent.
