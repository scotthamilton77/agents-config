# AGENTS.md — `packages/agentprobe/`

Package-scoped guidance for the `agentprobe` CLI. The repo-root `AGENTS.md` still
applies; this file adds what is specific to this package. Like the other packages here,
**this is real code with a real quality gate** — unlike the config content under `src/`.

## The quality gate is mandatory

Before pushing any change under `packages/agentprobe/`, run the canonical gate from the
repo root:

```bash
make ci-agentprobe
```

It runs, in order: `ruff check`, `ruff format --check`, `mypy --strict src`,
`pytest --cov` (90% branch floor), `pip-audit`, and `agentprobe --help`. Do not hand-pick
a subset — the linter and the formatter are orthogonal. Faster inner loop:
`make test-agentprobe`.

This package is **not** in the installer's PATH-install registry. It is a diagnostic the
operator runs from this repository against this repository's mitigations, not a tool
other projects need, and membership of that registry is earned rather than granted by
being gated.

## Never run a probe as verification

`agentprobe run` launches a real Claude Code session and spends real agent turns on the
operator's account. No gate may invoke it, no test may invoke it, and claiming a change
works must not depend on having run one. Use `--dry-run`, which writes the run directory,
prints the command and the scrubbed environment, and stops.

Everything the suite checks is a pure function over recordings under
`packages/agentprobe/tests/unit/fixtures/`.

## Architecture

```
hooklog.py   →  events.py  →  detect.py  →  report.py  →  cli.py
(runs inside     (reads a      (judges       (rates        (two verbs)
 the probed      recording)    nothing,      across
 session)                      observes)     runs)

session.py — the only module that opens a terminal
```

- **`hooklog.py` runs inside the session being measured.** Claude Code invokes it as a
  hook command, by path, once per event. It imports nothing from the rest of the package
  for that reason, and it must never raise into the session it is observing.
- **`session.py` splits its decisions from its terminal.** Recognising the trust dialog,
  knowing the input line is ready, confirming the typed instruction echoed back, and
  deciding the run is over are all pure functions tested on captured strings. Only
  `run_session` touches a pseudo-terminal, and it is excluded from coverage.
- **A detector returns a hit and its evidence, never a verdict.** Adding one means adding
  a pure function of a `Run` and a test pinning it against a recording.

## Why the session is interactive

Agent teams do not exist under `claude -p`. A named Agent runs there as an ordinary
subagent and no teammate idle ever fires, so the behaviours this package exists to
measure are invisible in that mode. Driving a real interactive session on a
pseudo-terminal is the only way to reach them.

Two details of that driving are load-bearing, and both were learned by losing runs to
them. Accepting the workspace-trust dialog repaints the screen, and keystrokes sent
during the repaint are dropped silently; the driver therefore waits, and then reads the
instruction back off the screen before pressing return.

## Recordings

A fixture is a scrubbed copy of a real run: the operator's home path is replaced and
token-like values are redacted, while timestamps, agent ids and session ids are kept
because the detectors read them. Adding a fixture means adding the same five files a live
run produces, minus what the run did not generate.
