# prgroom CLI — architecture

> **Design reference**: [`design.md`](design.md) — the only other file in this folder, and the one to read.

`prgroom` is the PR-grooming CLI: a `uv`-installed Python console-script that owns
the deterministic half of responding to pull-request review — polling GitHub for
review items, clustering them, dispatching a fix agent at named hand-off points,
pushing, replying, and resolving threads — so that work stops loading onto an
implementer's context as skill prose every cycle.

## What is here, and what is not

This folder used to hold a full HLD artifact set: C4 context, container and
component views, sequence diagrams, a state machine, a data view, a deployment
topology and a cutover runbook. All of it described a system substantially larger
than the one that will exist. Those files were retired to the
`scotthamilton77/agents-config-ARCHIVE` repository, where they keep their original
paths under `docs/architecture/prgroom/`.

Read them as history if you want the reasoning behind a decision. Do not read them
as a contract, and do not restore one into this repository to bring a diagram back:
the subsystem they draw is not the subsystem being built.

What survives is `design.md`, which now carries the parts that are still binding —
including the two boundary contracts that used to live in the data view:

- the `status --json` envelope (§4.5), which is the stable hand-off shape a merge
  gate consumes
- the escalation event's wire format, severity vocabulary and dedup semantics (§5)

## prgroom is being carved down, not finished

This is the single most important thing to know before reading `design.md`. The
package is not an unfinished implementation of that document; the document
describes more than will ever be built. The `verify` gate and its convergence loop
and the `sweep` verb are not going to be built at all, and the reply, poll, wait,
snapshot and legacy-export machinery — while built and wired into the CLI today —
is slated for removal rather than completion.

`design.md` marks the major cases inline, but the reliable rule is simpler:
**where the design and `packages/prgroom/src/` disagree about what exists, the code
is the authority.** The package's own `AGENTS.md` carries its quality gate and
working rules.
