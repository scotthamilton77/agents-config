# Configuration

Two scopes, two jobs:

- **User scope** (`~/.claude/`, `~/.codex/`, …) — your personal preferences,
  applied to every project. Set these once, after install.
- **Project scope** (a repo's `.claude/` and root config files) — how one
  project's workflow behaves: its quality gates, merge policy, domain language.
  Project settings override user settings.

> Read the [guide index](./index.md) first if you have not. Several of the
> control surfaces below are described as designed rather than working, because
> the code that read them was retired and its replacement is not finished. Each
> one says which it is.

## 1. Review `settings.json` (Claude)

The installed `~/.claude/settings.json` union-merges with anything you already
have (your values win; new keys are added). Worth knowing what ships:

- **Permissions** — a hardened `deny` list that blocks reading `.env`, shell
  profiles, SSH keys and `/etc/shadow`, and blocks writing to system binary
  directories. The `allow` list ships **empty** on purpose: an allowlist is
  personal, and every entry is a permission prompt you have chosen not to see.
  Add your own as you find the prompts that annoy you.
- **Hooks** — a `PostToolUse` hook that lints and formats Python you just wrote
  (`ruff-postedit`), and a `SessionStart`/`SessionEnd` hook that reaps leaked
  Codex broker processes (`codex-broker-reaper`).
- **Experimental features** — agent teams, fork-subagents, tool search, and
  auto-backgrounded tasks are enabled via env vars. Turn off any your setup
  doesn't support.

Some keys are simply the author's taste — `effortLevel`, `tui`, `voice`,
`verbose`. Change them freely; nothing depends on them.

## 2. Teach it your domain: `CONTEXT.md`

Put a `CONTEXT.md` at your repo root (or `CONTEXT-MAP.md` pointing at per-area
glossaries) with your domain vocabulary. The installed instruction core tells
the assistant to use that glossary's terminology when one exists — a soft
convention that sharply reduces terminology drift. This works today; it is one
line in the always-on `<conventions>` block, not a mechanism with moving parts.

## 3. `project-config.toml` — mostly not wired up yet

A `project-config.toml` at your project root is the intended control surface for
how a repo behaves: its quality gates, its coverage floor, its review and merge
policy. **Most of it has no reader.** The per-stage orchestrators that consumed
these sections were retired with the old pipeline, and the rebuild has not
replaced them. A section with no reader is a statement of intent that a human or
an agent may read, and nothing more — writing one does not change any behaviour.

What genuinely reads the file today:

- **`[install]`** — read by the installer, to select project-scoped install
  profiles.

The `work` CLI does not read this file. Its track partition and
work-in-progress rules come from `.work/config.toml`, which `work init`
scaffolds at your project root.

Everything else is currently inert. The sections below are documented because
they are the shape the rebuild is expected to restore, and the schema each one
would take is given here in full — this page is the reference, not a pointer to
one.

This repo's own `project-config.toml` is not that reference. It carries only
sections a named consumer actually reads, plus commented-out keys for work not
yet deployed. A section documented on this page and absent from that file is
absent on purpose.

### Quality gates — `[gates]`, `[coverage]` (no deployed reader)

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

The intent is that verification runs *your* commands for mechanical evidence.
No installed skill or rule currently reads these, so today they serve as
documentation for whoever — human or agent — goes looking for how to build and
test your repo.

### Completion-gate tiering — `[completion-gate]` (not implemented)

The design routes each change to SKIP, SERIAL, or HEAVY verification by size and
risk. **There is no tier router.** The skill that computed the tier was retired,
the thresholds have no reader, and the companion `.critical-paths` file selects
nothing. This repo's `project-config.toml` keeps the keys commented out for that
reason; uncomment them only in the change that deploys a router.

### Review and merge policy — `[review-expectations]`, `[merge-policy]` (not implemented)

```toml
[merge-policy]
merge-authorization = "explicit"   # never | explicit | rule-based
```

`merge-authorization` is meant to decide how far autonomy goes at the finish
line: `never` hands off to a human, `explicit` waits for a direct instruction,
`rule-based` permits an autonomous merge when a named rule and a live
eligibility check both pass.

**Nothing enforces this.** The `merge-guard` skill that read it has been
retired, no code reads `merge-authorization`, and nothing polls for reviews, so
`[review-expectations]` has no effect either. What remains true is the rule that
does not depend on any of it: **creating a PR is not authorization to merge**,
and that lives in the always-on `<hard-lines>` block your assistant loads on
every session. Treat a `[merge-policy]` section as a note to your future self
and to any agent reading the repo — not as a control.

The `[merge-policy.approver]` block — a GitHub App that submits an attested
approving review so an authorized autonomous merge can clear branch protection —
is designed and not built. Do not set it up expecting it to do anything.

### Adversarial review — `[foreign-cli]` (no deployed reader)

Binary paths and per-task model selections for cross-model review. The stages
that read it were retired. The `delegating-to-codex` skill, which does ship,
picks a model from its own routing table rather than from this section.

## 4. Wire up work tracking (optional)

The workflow treats durable work as issues that outlive a session and survive
context compaction. This repo's tracker is [beads](https://github.com/steveyegge/beads),
addressed through the `work` CLI — a facade over `bd` that ships from its own
repository, [scotthamilton77/workcli](https://github.com/scotthamilton77/workcli),
and is installed from there rather than by this repo's installer. You need `bd`
installed and a `bd init` in your project for any substantive `work` verb —
anything but `init` and `guide` — to function.

That `bd init` is a one-time, per-project setup step, and it is something
`work` deliberately has no verb for: a workspace carries storage, remote and
id-prefix decisions that belong to the tracker rather than to the facade over
it. Run a substantive `work` verb (anything but `init` and `guide`) where no
workspace has been created and it refuses with `E_NO_WORKSPACE`, telling you
to run from a directory that already has one and pointing here for the rest.
Running `bd init` at the root of your project is that rest — do it once, and
every `work` verb below that root then resolves.

`work init` is the second setup step: it writes `.work/config.toml` at your
project root, which is where `work` reads the vocabulary it validates but does
not author — your track names, your nouns, and the reasons work parks or is
deferred. It needs no `bd` workspace to run and touches no backend, so you can
run it before or independently of `bd init`.

Five deployed skills are the reason to do any of this, and all five reach for
`work` verbs directly. Four ship to every detected tool; `wayfinder` is
Claude Code only:

- `to-tickets` and `wayfinder` fall back to writing their tickets or decision
  map as a local markdown file instead of tracker items.
- `where-does-this-fit` falls back to fetching an item's container and
  siblings however the tracker in use exposes them, or asking you directly.
- `triaging-discovered-work` falls back to a dated entry in a backlog file at
  the repo root instead of a filed `work discover` item.
- `prototype` falls back to recording its verdict in the commit message
  instead of a `work note` on the tracker item.

None of the five hard-fails without a tracker — skip the setup above and each
degrades to its own fallback instead. Nothing else in the installed
instruction surface reaches for `work`.

Be aware of what does **not** ship: no installed rule or skill instructs your
assistant to file an issue before writing code, to claim one when it starts, or
to close one when it finishes. That discipline was carried by rules that have
been retired. Today the tracker is a tool available to you and to your agent
when either of you reaches for it, not a habit the configuration enforces.

## Optional: the CLIs on your PATH

A normal install puts four CLIs from this repo on your PATH via `uv tool
install` — `prgroom`, `grind`, `executor` and `gitclean` — no separate step
needed. Only `gitclean` is reached for by an installed skill
(`post-merge-cleanup`, which uses it to decide safely which branches and
worktrees a merged PR made disposable) and by the `/clean-up-git` slash command.

The other three are components of the rebuild rather than finished user tools.
`prgroom` grooms a PR deterministically but the skills that drove it were
retired; `grind` and `executor` are runtime pieces with no driver yet. They are
installed because the repo's own development uses them, and they are harmless if
you ignore them.

`work` is not among them: it ships from its own repository and is installed
from there.

If you want one without the installer, `uv tool install ./packages/<name>` from
this repo is the same command the installer runs.
