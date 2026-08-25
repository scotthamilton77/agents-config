# AGENTS.md — `packages/grillui/`

Package-scoped guidance for the `grillui` CLI. The repo-root `AGENTS.md` still
applies; this file adds what is specific to this package. Like the other
packages here, **this is real code with a real quality gate** — unlike the
config content under `src/`.

## The quality gate is mandatory

Before pushing any change under `packages/grillui/`, run the canonical gate
from the root of the tree you are working in:

```bash
make ci-grillui
```

Read the `ci-grillui` target in the repo `Makefile` for its current membership.
Run it standalone and read its exit status.

Two test trees sit outside that gate, because it would have to carry a browser
to run them. `tests/browser/` holds one-off probes, each run by hand. `tests/e2e/`
is the kept end-to-end harness: `make e2e-grillui` launches a real backend
through the same `launch` path a `grillui serve` takes, seats it on a local
stub and two scripted CLI shims, and drives every grill-master use case with
headless Playwright. Run it standalone too, and when a change touches seating,
the lane, the document ladder or the fold, run it as well as `ci-grillui` —
`testpaths` is `tests/unit`, so nothing else collects it. Its scenarios run on a
PATH holding only those shims: a scenario must never be able to reach a real
`codex` or `claude`, which would spend an account and read as a passing seat.

## What this package is

The grilling-session backend, per `docs/specs/2026-08-18-grilling-ui-v1.md`.
It serves the session UI, folds the decision log into the context images, and
drives the grilling tiers. The two skills that bracket a session —
`grill-with-ui` and `grill-capture` — are deployed content and live under
`src/`, not here.

Current state, by area:

- **Session core** — append-only session log, typed receipts, board endpoints,
  deterministic context images with persistence, recorded dispatch contexts, a
  mechanical status lane with a turn-driver seam, and the full v1 update-kind
  vocabulary behind an atomic fold.
- **Lifecycle** — handoff-seeded start, restart resume, and terminal-result
  capture.
- **Agent drive** — two tiers: a fast OpenRouter tier with code-evaluated
  escalation criteria, and a heavy `claude -p --resume` tier on a
  single-process resume chain. Every grill-master turn is a document of one
  closed shape — notice, updates, withdrawals, rulings, stop — refused and
  retried once on the same seat, handed up once, then recorded as a failure;
  no map reply is ever shown to the human as prose. A ruling of `stands` is a
  credited answer beside `invalidate` and `revise`, and the obligation check
  reads coverage off the turn's own rulings. Thread agents run on per-thread
  contexts; the grill-master is the sole author of map mutations; pending-queue
  supersede/conflict handling, the map doctor's backend flow, and the
  transfer-to-expert flow are pinned end to end. An agent's map mutation is a
  proposal until the human applies it — classified at arrival, with
  apply/dismiss gestures and proposal-driven frontier locks.
- **The page** — authored as separate style, script and markup sources that
  the package assembles into the single self-contained document it serves. It
  renders the board straight from image 1 without folding anything
  client-side, and carries a two-layer channel-state model — transport
  lifecycle and per-channel protocol state — behind a worst-state-wins
  three-signal indicator with an on-demand per-channel diagnostic. The v1 UI
  mandates hold: waiting clocks, OS-timezone timestamps, floating thread
  chrome, labelled options with notes, hover discipline, persistent
  mark-all-read, the single light palette.
- **Window arbitration** — one main window per session, outside the log. The
  claim goes to a name the window keeps in its own session storage; a second
  window is refused with a rendered explanation; an explicit take-over
  supersedes the holder.
- **Launch path** — `grillui serve` opens the session, takes the next free
  port when the default is occupied, prints the loopback URL and opens a
  browser at it only when asked with `--open`, refuses any request that did
  not come from this machine, and returns the terminal result on stdout when
  the human's end-session gesture stops the backend. `grillui capture` is
  that same result over a session directory nothing is serving.
