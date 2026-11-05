# Orders database: restore tooling and runbook

## Problem

The orders database is snapshotted every night, but a restore has only ever been run by the engineer who wrote the scripts. When that engineer is away, the on-call engineer cannot restore the database within the 30-minute recovery target.

## What changes

- `dbrestore list` lists the available snapshots.
- `dbrestore <snapshot-id>` restores a snapshot into a new cluster and points the orders service at it.
- A runbook in the on-call wiki walks an engineer through a restore with those two commands.
- An on-call engineer who has never restored the database can finish a restore within 30 minutes, using only the runbook.

## Decisions

- **D1 Listing.** `dbrestore list` prints one line per snapshot, newest first: its id and its time in UTC.
- **D2 Restore.** `dbrestore <snapshot-id>` creates a new cluster from the snapshot, waits until it accepts connections, then repoints the orders service. It exits 0 once the service's health check passes against the new cluster.
- **D3 Failure.** A restore that fails before repointing leaves the service on its current cluster, exits 1 and prints the failing step's name to stderr. An id that names no snapshot exits 2, prints `no such snapshot: <id>` to stderr and creates no cluster.
- **D4 Runbook.** The runbook names every command to run and the output to expect at each step, so an engineer needs no other document.

## Acceptance criteria

Criteria RST-A1 to RST-A4 are each checked by an automated test in the restore suite, which runs against a staging copy of the orders service with three nightly snapshots. A criterion passes when its test passes in CI on the pull request's head. The CI result decides, and the pull request does not merge until each of them passes.

- **RST-A1** Given three snapshots, when `dbrestore list` runs, it prints exactly three lines, each holding one snapshot's id and UTC time, newest first.
- **RST-A2** Given the newest snapshot's id and an order written before that snapshot was taken, when `dbrestore <id>` runs, the command exits 0, the orders service's connection points at the new cluster, its health check passes, and the order can be read through the service.
- **RST-A3** Given a restore whose new cluster never accepts connections, when `dbrestore <id>` runs, the command exits 1, prints `wait-for-cluster` to stderr, and the orders service still points at its original cluster.
- **RST-A4** Given an id that names no snapshot, when `dbrestore <id>` runs, the command exits 2, prints `no such snapshot: <id>` to stderr, and no new cluster exists.
- **RST-A5** An on-call engineer who has never restored the orders database completes a restore within 30 minutes, using only the runbook.

## Out of scope

- Point-in-time recovery between snapshots.
- Restoring any database other than orders.
- Changing the snapshot schedule.
