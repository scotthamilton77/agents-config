# grillui

The backend behind a grilling session's user interface: it serves the UI,
folds the session's decision log into the images the UI and the agents read,
and drives the grilling tiers. The design it is being built to is
`docs/specs/2026-08-18-grilling-ui-v1.md`.

## What exists

The session core. One process owns one session directory, whose fixed file
names are `log.jsonl`, `image1.json`, `image2.json`, `handoff.json` and
`result.json`; the append-only log is the single source of truth, and the
process mints an epoch over it at startup and assigns every sequence number.
Restarting against the same directory mints a new epoch and continues the
sequence it had reached.

```bash
grillui serve ./sessions/my-session --port 8765
```

Four modules, and the separation between them is load-bearing:

- `schemas.py` — the wire, log and image shapes, plus the closed vocabulary of
  the seven reasons a write can be refused for.
- `log.py` — the appender. It assigns the sequence, writes durably before
  anything else can observe the entry, and answers every write with a typed
  receipt: `accepted` with the sequence assigned, `duplicate` naming where the
  key already landed, or `rejected` naming the reason. It never folds a
  projection.
- `projector.py` — a pure fold over the log into the two context images: no
  clock, no randomness, no I/O. Persisting an image is a separate step
  downstream, and the image files are derived caches, never a recovery source.
- `api.py` — the board endpoints. `/status` is answered from memory and opens
  no file, so it stays cheap whatever the log has grown to; `/state`, `/image1`
  and `/image2` fold; `/updates` refuses a stale epoch with 409; `/events`
  takes a batch under one epoch and returns one receipt per event in
  submission order.

Not built yet: the status lane, the agent drive, handoff parsing, session
control, per-kind payload semantics, and the UI itself.

## Development

```bash
make ci-grillui     # the full gate: lint, format, types, coverage, audit, entry
make test-grillui   # faster inner loop
```
