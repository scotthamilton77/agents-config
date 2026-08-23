# AGENTS.md — `src/`

The deployed surface: everything installed into user space is authored here.
Most content is documentation and templates with no build step — changes follow
existing formatting conventions per file type. Shared content lives under
`src/user/.agents/` (staged into every active tool; see that directory's
`AGENTS.md` for the install model and the name-collision rules), per-tool
content under `src/user/.claude/`, `src/user/.codex/`, `src/user/.gemini/` and
`src/user/.opencode/`, and plugin content under `src/plugins/`. Each rules
directory carries its own `AGENTS.md` stating what currently lives there; read
it rather than inferring from the folder's contents.

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
