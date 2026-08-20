# grillui

The backend behind a grilling session's user interface: it serves the UI,
folds the session's decision log into the images the UI and the agents read,
and drives the grilling tiers. The design it is being built to is
`docs/specs/2026-08-18-grilling-ui-v1.md`.

## What exists

The session core and the projection. One process owns one session directory,
whose fixed file names are `log.jsonl`, `image1.json`, `image2.json`,
`handoff.json` and `result.json`, alongside a `dispatches/` directory holding
one file per recorded agent dispatch; the append-only log is the single source
of truth, and the process mints an epoch over it at startup and assigns every
sequence number. Restarting against the same directory mints a new epoch and
continues the sequence it had reached.

```bash
grillui serve ./sessions/my-session --port 8765
```

Seven modules, and the separation between them is load-bearing:

- `schemas.py` — the wire, log and image shapes, the per-kind payload shapes,
  and the closed vocabulary of the seven reasons a write can be refused for.
  That vocabulary is what decides where a malformed payload lands: a fault one
  of the seven names comes back as a typed receipt, and a fault none of them
  names — an add-node with one option, an invalidate with no rationale — is
  refused at the envelope with a 422, for the batch whole and before anything is
  appended.
- `log.py` — the appender. It assigns the sequence, writes durably before
  anything else can observe the entry, and answers every write with a typed
  receipt: `accepted` with the sequence assigned, `duplicate` naming where the
  key already landed, or `rejected` naming the reason. It never folds a
  projection.
- `projector.py` — a pure fold over the log into the two context images: no
  clock, no randomness, no I/O. The same log therefore always yields
  byte-identical images, and an image rebuilt from disk matches one held in
  memory. It is also where each update kind's meaning lives — what a revise, an
  invalidate, an unsettle or a blocking alert does to a decision's status — and
  the module docstring is the table.
- `persistence.py` — the only image I/O there is, downstream of the fold: it
  refreshes both image files after an accepted batch. The files are derived
  caches, never a recovery source, so a failure here surfaces as an error on
  the status lane and blocks neither the log nor the next event.
- `dispatch.py` — assembles an agent's dispatch context, records it under
  `dispatches/`, and refuses one that does not carry image 2 byte for byte.
  There is no elision path: a dispatch that omits part of its owed projection
  is data corruption, not a saving.
- `lane.py` — the status lane, the answerability decision, and the seam a tier
  plugs into. A human turn's `accepted` and `composing` entries are appended
  inside the same lock as the turn itself, before any driver is reached, so the
  page learns a message landed in under a millisecond rather than when a model
  gets around to it. Only a human turn is answered: an agent-authored thread is
  recorded and left alone, so the backend never answers itself. The driver runs
  off the lock and off the request path — one invocation per turn, no polling —
  and a tier that cannot be reached surfaces as an `error` phase in
  milliseconds instead of an unbounded silence.
- `api.py` — the board endpoints. `/status` is answered from memory and opens
  no file, so it stays cheap whatever the log has grown to; `/state`, `/image1`
  and `/image2` fold; `/updates` refuses a stale epoch with 409; `/events`
  takes a batch under one epoch and returns one receipt per event in
  submission order, and returns them without waiting on the turn it scheduled.

The update kinds are complete. An add-node mints its node id from the sequence
it lands at — deterministic, because the receipt echoes the node the fold will
later materialise, and two readers of one node is how a receipt and a board come
to disagree. An invalidate carries its own rationale onto the decision it
blocks. A `fold` is one gesture carrying an ordered set of sub-updates, applied
all of them or none: the whole gesture is a single log entry, so there is no
state in which half of it landed, and its receipt says what became of each
sub-update — applied, refused with its own reason, or vetoed by a refused
sibling.

Not built yet: the fast and heavy tier drivers behind the `TurnDriver` seam
(`create_app` takes one and has none by default, so no reply is promised until a
tier is configured), escalation, thread projections, handoff parsing, session
control, superseding or clearing anything from the pending queue, and the UI
itself.

## Development

```bash
make ci-grillui     # the full gate: lint, format, types, coverage, audit, entry
make test-grillui   # faster inner loop
```
