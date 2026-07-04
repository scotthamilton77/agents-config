# Configuration

Two scopes, two jobs:

- **User scope** (`~/.claude/`, `~/.codex/`, …) — your personal identity and
  preferences, applied to every project. Set these once, after install.
- **Project scope** (a repo's `.claude/` and root config files) — how one
  project's workflow behaves: its quality gates, merge policy, domain language.
  Project settings override user settings.

## 1. Personalize the personas (do this first)

The installer ships persona templates carrying the author's identity. Replace
them, or your assistant will think it's talking to someone else:

- **`USER-PERSONA.md`** — who *you* are: name, role, how you like to be
  challenged and addressed. Replace it entirely.
- **`AGENT-PERSONA.md`** — the assistant's personality and standards. Adjust to
  taste.

Both are referenced from your instruction file via `@AGENT-PERSONA.md` /
`@USER-PERSONA.md`.

## 2. Review `settings.json` (Claude)

The installed `~/.claude/settings.json` union-merges with anything you already
have (your values win; new keys are added). Worth knowing what ships:

- **Permissions** — an allowlist for common safe commands plus a hardened
  `deny` list (blocks reading `.env`, SSH keys, `/etc/shadow`, and writing to
  system binary dirs). Extend the allowlist to cut permission prompts.
- **Hooks** — a `PostToolUse` hook that lints/formats Python you just wrote
  (`ruff-postedit`), and one that detects a PR push to kick off review
  monitoring.
- **Experimental features** — agent teams, fork-subagents, tool search, and
  auto-backgrounded tasks are enabled via env vars. Turn off any your setup
  doesn't support.

## 3. Set your project's control surface: `project-config.toml`

Drop a `project-config.toml` at your **project root** to tell the workflow how
this repo behaves. Every section is optional; absent sections fall back to
sensible defaults. The high-value sections:

### Quality gates — `[gates]`, `[coverage]`

```toml
[gates]
build     = "npm run build"
typecheck = "tsc --noEmit"
lint      = "eslint ."
test      = "npm test"

[coverage]
applicable = true      # false for docs/config repos with no coverage tooling
threshold  = 80        # percent
```

The completion gate and verification skills read these to run *your* commands
for mechanical evidence. A docs-leaning repo can leave them empty and set
`applicable = false` — the gates detect empty stubs and skip gracefully.

### Completion-gate tiering — `[completion-gate]`

The gate routes each change to **SKIP** (trivial), **SERIAL** (default), or
**HEAVY** (large/critical) verification. Tune the thresholds:

```toml
[completion-gate]
trivial_max_loc      = 3     # SKIP ceiling (hard-capped at 20)
heavy_min_files      = 8
heavy_min_loc        = 400
heavy_min_subsystems = 3
```

### Review and merge policy

This is the safety-critical one. It has **two axes**:

```toml
[review-expectations]              # Axis 1: what reviews to wait for
bot-review-expected      = true
bot-reviewers            = ["Copilot"]
human-approvers-required = 0

[merge-policy]                     # Axis 2: who may merge
merge-authorization = "explicit"   # never | explicit | rule-based
# merge-rule        = "bot-quiescence"   # required only for rule-based
```

`merge-authorization` decides how far autonomy goes at the finish line:

| Value | Meaning |
|-------|---------|
| `never` | The agent never merges; it hands off to a human. |
| `explicit` (default) | The agent merges only on a direct human instruction ("merge it", "ship it"). |
| `rule-based` | The agent may auto-merge **only** when the named `merge-rule` and the live eligibility check both pass. A deliberate, named opt-in. |

Absent a `[merge-policy]` section, `explicit` applies — creating a PR is never
authorization to merge. This is enforced by the `merge-guard` skill; see
[The SDLC Workflow](./sdlc-workflow.md#7-merge) for how it plays out.

### Adversarial review — `[foreign-cli]`

If you use cross-model review (Codex/Gemini), point at their binaries and pick
per-task models here.

## 4. Teach it your domain: `CONTEXT.md`

Put a `CONTEXT.md` at your repo root (or `CONTEXT-MAP.md` pointing at per-area
glossaries) with your domain vocabulary. The rules tell the assistant to read it
and use *your* terms when discussing domain concepts — a soft convention that
sharply reduces terminology drift.

## 5. Wire up work tracking (beads)

The workflow treats durable work as **beads** — issues that outlive a session
and survive context compaction. Run `bd init` in your project. File a bead
before writing code for it; the assistant claims it, works it, and closes it.
See [The SDLC Workflow](./sdlc-workflow.md#1-capture) for the loop.

## Optional: the `prgroom` CLI

`prgroom` is a standalone CLI that grooms a PR deterministically (poll → cluster
feedback → fix → push → reply → resolve). The `monitor-pr` skill drives it. It
is **not** installed by the installer — if you want it, install it from the repo:

```bash
uv tool install ./packages/prgroom     # or: uv run prgroom --help
```

Without it, the skill-based `wait-for-pr-comments` path handles PR feedback
instead.
