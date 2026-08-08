# AGENTS.md — `packages/workcli/`

Package-scoped guidance for the `work` CLI. The repo-root `AGENTS.md` still
applies; this file adds what is specific to this package. Unlike the config
content under `src/`, **this is real code with a real quality gate.**

`workcli` is the `work` facade CLI: it quarantines the issue-tracker backend
(bd) behind a stable, versioned JSON envelope contract — twelve verbs over an
injected `Backend` seam, typed error codes, and a bd adapter driven through a
subprocess port. See `docs/specs/2026-07-04-work-facade-cli-contract.md` for
the behavioral spec.

A lifecycle layer (`src/workcli/lifecycle/`) sits over that same transport
seam: noun-templated `work create <noun>` plus the guarded verbs
`claim`/`release`/`deliver`/`plan`/`promote`/`reconcile` — status only ever
moves through a lifecycle verb (plus transport's `close`/`reopen`). See
`docs/specs/2026-07-05-work-lifecycle-and-facade.md`. The finer capability-model
split (an honest server-authoritative `sync` no-op; read-only dep listing
surviving `supports_dep_types=False`) is deferred to the future non-bd (GH)
adapter bead — bd declares every `Capabilities` flag `True`, so nothing here
needs it yet.

## The quality gate is mandatory — run it, do not approximate it

Before pushing **any** change under `packages/workcli/`, run the canonical gate
from the root of **the tree you are working in** (the worktree root, if you are
on a worktree branch — the `Makefile` `cd`s relative to the invoking directory,
so a run from the main checkout gates code you did not change):

```bash
make ci-workcli   # the full gate CI enforces
```

It runs, in order: `ruff check` (lint), `ruff format --check` (formatting),
`mypy --strict src` (types), `pytest --cov` (tests + coverage), `pip-audit`
(deps), `work --protocol-version` and `work --help` (entry verify). `make ci`
runs this alongside `ci-installer`, `ci-prgroom`, and `lint-actions`.

Do **not** hand-pick a subset (e.g. `ruff check` alone). `ruff check` (linter)
and `ruff format` (formatter) are orthogonal — passing one says nothing about
the other. The `Makefile` is the single source of truth for the gate; mirror
it exactly. Faster inner loop while iterating: `make test-workcli` (pytest
only), but the full gate must pass before push.

## Toolchain

- `uv`-managed; Python ≥ 3.11.
- Run tools via `uv run …` from inside `packages/workcli/`, or the `make`
  targets from the repo root.
- The repo installer also deploys `work` globally onto PATH via
  `uv tool install` (receipt-tracked, pruned on retirement) as part of a
  normal install; `uv run` from inside `packages/workcli/` remains the way to
  exercise an in-checkout, unreleased change.
- Config lives in `pyproject.toml`: ruff (line-length 100), mypy
  `strict = true`, coverage `branch = true` / `fail_under = 90`.
- Zero runtime dependencies by design (stdlib only: argparse/json/subprocess/
  dataclasses) — keeps the `pip-audit` surface nil.

## Design principles for this package

- **Pure verb layer over an injected `Backend` seam.** The verb layer
  (`verbs/`) owns normalization, typed errors, and pre-checks; it never
  imports `subprocess` and never talks to bd directly. Adapters
  (`adapters/bd/`) own backend I/O and concept mapping only, and never print —
  all output flows back through the verb layer to the envelope.
- **Injected I/O everywhere.** `main()` accepts `argv`, `runner`, `out`,
  `err`, `sleep` as arguments — outside-world dependencies never reach a
  module global. Contract tests drive the CLI through `main()` with a
  `ScriptedBdRunner` fake (`tests/fakes.py`, from Task 2) in place of the real
  subprocess-backed `SubprocessBdRunner`; no live Dolt, no real subprocesses.
- **One JSON envelope on stdout, always.** Exit code mirrors `ok`
  (`envelope.py`, pinned contract). Argparse usage errors and unexpected
  internal exceptions both flow through the same envelope machinery — never a
  raw argparse stderr dump or an unhandled traceback to stdout.
- Layout: `cli.py` (argparse wiring + dispatch), `envelope.py` (error codes +
  emit helpers), `model.py` / `backend.py` (the `Backend` protocol and item
  shapes), `verbs/` (read/write/relations/syncing), `adapters/bd/` (the bd
  adapter: `runner.py` subprocess port, `parse.py`, `retry.py`, `backend.py`).

## What may name the backend, and where

The facade's whole promise is that a consumer never learns which issue
tracker is behind it. That promise is a property of the bytes that leave this
process, not of the import graph: `error.message` and `error.detail` are
published verbatim, and callers relay them into errors of their own. So the
wall runs through the envelope, and it is crossed in both directions.

**Downward — nothing above `adapters/` may name the backend.** `cli.py`,
`envelope.py`, `verbs/`, `lifecycle/`, `model.py`, `render.py` and
`config.py` author no backend vocabulary in any string that can be printed.
Argparse `help=` is the surface this is most often forgotten on, and it is
contract, not commentary: `work --help` is read by people choosing whether to
depend on the facade.

**Upward — the adapter may not reach past its own seam.** It may say what the
`Backend` protocol says: the protocol's operation names are the seam's shared
vocabulary, and an adapter naming `close` is naming the method it implements.
It may not spell the CLI's verbs, flags or command lines. Advice of the form
"run `work reconcile`" belongs to the layer that owns the verb, because that
layer is the one that renames it; an adapter that spelled it would go stale
silently, and a second adapter would have to copy it to stay consistent.
Adapters state the fact; `cli.py` attaches the instruction.

Inside the adapter, the axis is **audience, not vocabulary**. The question is
never whether the backend's name appears; it is who the sentence is addressed
to. Three cases, and only the last two are governed.

**Speech to the operating system is not governed at all.** `"bd"` as the
default binary, `"dolt"` at the head of an argv, a stderr marker the adapter
matches on to classify a failure — these are how the adapter *calls* its
backend and recognises the answer. An adapter that could not name its backend
could not invoke one. Laundering these would be pure ceremony: it would
obfuscate the call site, buy no consumer anything, and leave the rule looking
arbitrary to the next person applying it. The scrubber's own list of names to
remove is in this category too — it has to name what it hides.

The other two are speech to a consumer, and they split by who wrote it: **text
the adapter writes** and **text it passes on**.

- *Authored* text is written in facade vocabulary, always. "Backend", "the
  tracker", "the adapter" are facade concepts and are always fine; the
  product's name, its subcommands and its flags never are. A drift alarm may
  name the payload field it choked on — that is the alarm's content, not the
  backend's identity.
- *Passed-on* text — the backend's own stderr — travels only where the
  adapter has no answer of its own, which is the unrecognised-failure path
  and nothing else. Once a failure has a typed code, the code and its message
  are the complete answer, and the backend's sentence would add only the
  backend's vocabulary. Where it does travel it is scrubbed by the adapter's
  own redactor, because the adapter is the only layer permitted to know what
  to scrub.
- The backend's **argv never travels at all**. A caller cannot act on a
  command line without already knowing the backend, so publishing one buys
  nothing and spends the whole quarantine.

`data` is exempt from all of this. Item titles, descriptions and notes are
whatever a user typed, and a tracker item that discusses the tracker is a
thing people write. Echoing a user's own words back is not disclosure.

### The test for a comment or a docstring

Prose is held to the same axis, and again the question is not whether the name
appears but what it is doing there. **Rewrite the sentence with a second,
hypothetical adapter in its place.** If it stays true and still explains the
code, the name was *evidence* — keep it, and keep it marked as evidence
("verified against", "captured from"). If it becomes false or stops
explaining anything, the name was carrying *the contract*, and the contract
belongs in the sentence with the product's name demoted to the evidence that
established it. A comment sitting on an invocation is the third case above and
needs no test at all: a line reading `# bd's own reparent replaces` above the
argv that reparents is describing a call, to the person maintaining the call.

So "typed as the backend emits them" is already fine: it names a role, not a
product, and the substitution changes nothing. "This is what bd does" fails
the test — under a second adapter it is simply false — and should state the
facade's rule instead. "The backend may return null here; bd returns it as an
empty array" passes: the rule is stated independently and the product is cited
as the observation behind it.

### The check that enforces it

`tests/unit/test_envelope_invariants.py` asserts this mechanically, four
ways: the CLI's own envelopes are driven and read (including over stderr
captured from the live backend), every error message the adapter is *capable*
of raising is scanned in the source, the adapter is scanned for any route to
publishing an argv, and the layers above it are scanned for backend
vocabulary in a printable string. The source-level scans exist because the
behavioural one only meets the paths some test happens to drive, and the
leaks this rule guards against sit mostly on paths no test drives.

Note what the adapter scan deliberately does not read: argv literals and
stderr markers. It reads the message argument of an error and nothing else,
which is what keeps the first case above out of its reach by construction
rather than by an exemption someone has to maintain.

The redactor's own coverage is pinned separately, in
`tests/unit/test_backend_redaction.py`, which names each spelling of the
backend's identity one at a time and then measures the widened pattern against
this package's captured backend output to show it eats nothing else. The
singular noun is the spelling most easily left out — it names no file and no
environment variable, so it reads as domain vocabulary rather than as a name.

The scan over the layers above the adapter carries exactly one exemption, and
it marks the one place the wall genuinely bends. The superseded spelling of a
config key contains the backend's singular noun and cannot be renamed without
silently ceasing to read `project-config.toml` files already on disk: its
bytes are a value the facade matches a user's keys against, not vocabulary the
facade chose. It is exempted by the name it is bound to rather than by its
text, so no second literal inherits the exemption, and a companion check fails
if the binding ever stops needing one. An exemption outliving its subject is
how a scan like this goes quiet.

## Tests

- Behavioural, not tautological — each test pins a coded decision (an
  envelope shape, a dispatch path, a bd call-log assertion), never the
  language/stdlib.
- Contract tests for verbs run against `tests/fakes.py`'s `ScriptedBdRunner`
  (records every call, feeds scripted results) — never a real bd subprocess
  and never a live Dolt database.
- Coverage floor is 90% branch (enforced by `pytest --cov`); this package's
  sibling standard supersedes the repo's global 80%/70% default.

## Do not run bd mutations against the real DB from this package's tests

Contract tests exercise the `bd` adapter exclusively through the
`ScriptedBdRunner` fake. Golden `--json` captures for parser fixtures (Task 2)
are read-only and run from the **main repo root**, never this worktree — see
the plan's decision 14. Never invoke a mutating `bd` verb against the real
database while developing or testing this package.

## Real-bd integration suite (`make itest-workcli`)

`make itest-workcli` is the **sanctioned exception** to the rule above: it drives
the production `work` CLI against a **real, isolated** bd install (embedded Dolt
in a temp dir, bound via `BEADS_DIR` and an off-repo `tmp_path` + a git-repo
pre-flight guard, so it can never reach the repo's `.beads`). It catches bd-JSON
drift the hermetic `ScriptedBdRunner` fakes cannot. **Requirements & rules:**

- Needs `bd` on PATH; skips wholesale otherwise.
- **NOT** part of `make ci-workcli` / `make ci` — it needs the bd toolchain and
  runs ~40s+ serial. It is **pre-push discipline, not a merge gate**. `testpaths`
  in `pyproject.toml` pins the coverage-gated run to `tests/unit`.
- Runs serial (`-p no:xdist`) so the shared read-only install pays `bd init` once.
- Never weaken an integration assertion to make it pass: a failure is a real
  drift signal — fix the adapter/parser (and note the drift), or file it as
  discovered work, instead.

## Reference

Spec: `docs/specs/2026-07-04-work-facade-cli-contract.md`.
