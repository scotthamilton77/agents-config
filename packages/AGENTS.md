# AGENTS.md — `packages/`

Standalone uv projects; **not** part of the installed config surface. This is
real Python code with mandatory quality gates: `make ci` is the whole-repo gate
CI enforces, and each gated package also has its own `ci-<package>` target
running lint, format-check, typecheck, coverage, audit, and entry-verify. Read
the `Makefile` for which packages are currently in `ci` — not every package
under `packages/` is wired in. Most packages carry their own `AGENTS.md` with a
scoped workflow — read it before changing that package.

## The roster

- `installer/` — the installer engine that `scripts/install.sh` execs
- `grind/` — the event-sourced grind runtime: event schema, FSM fold, and the
  `grind` CLI that D14 nominates as the pipeline executor loop
- `prgroom/` — PR-grooming CLI. Per charter D13 it is **carved, not finished**
  (slice S8).
- `executor/` — the decision layer above grind and the `work` facade: the
  closed pairing table that turns one executor verb into one runtime event and
  at most one tracker verb. Driven by
  `docs/specs/2026-07-25-executor-seam-s9-tier1.md`. There is no dispatch
  loop — it answers what a verb pairs with, not when to run it.
- `gitclean/` — adjudicates one question about this repository's worktrees and
  branches — is this provably merged? — because `git branch --merged` is wrong
  in both directions under squash merges. A bare sweep takes only targets that
  clear that plus five measured checks, and reports everything else with the
  measurement that stopped it; a target named on the command line is not
  re-adjudicated at all, so naming one is an authorisation and the caller owns
  the consequence. On PATH; the `/clean-up-git` command drives it
  interactively, and the `post-merge-cleanup` skill is what tells an agent it
  exists at all.
- `grillui/` — the grilling-session backend: serves the session UI, folds the
  decision log into the context images, and drives the grilling tiers, per
  `docs/specs/2026-08-18-grilling-ui-v1.md`. See `packages/grillui/AGENTS.md`.

## PATH installs

`prgroom`, `grind`, `executor`, `gitclean` and `grillui` are the packages
installed onto PATH (`uv tool install`, receipt-tracked), landing as the
`prgroom`, `grind`, `executor`, `gitclean` and `grillui` commands;
`CLI_PACKAGES` in `packages/installer/src/installer/core/clis.py` holds that
list. Retiring one is **not** automatic: uninstall authority is bounded by
`CLI_PACKAGES | RETIRED_CLIS`, and `RETIRED_CLIS` is empty, so a package
dropped from `CLI_PACKAGES` alone leaves its binary on PATH until its name is
added to `RETIRED_CLIS` by hand. `work` is on PATH and absent from both lists
on purpose — a binary this repo does not own is not this installer's to
uninstall. Being gated by `make ci` is not what earns a place on the list —
`installer` is gated and stays off.

## Packages that live elsewhere

Some packages this repo depends on are not vendored here. The `work` facade
CLI — which quarantines the issue-tracker backend behind a stable
JSON-envelope contract — is `scotthamilton77/workcli`, and it owns its own
distribution: this repo neither builds nor installs it. `vizsuite/` lives in
`scotthamilton77/vizsuite`, which holds its history, its design spec and its
prototype corpus; only V1 is built, and V2 and V3 are not planned. `pdlc/` and
`holding-place/` are retired and live in the archive repository; the executor
work that would have drawn on their design carries a pointer to them.
