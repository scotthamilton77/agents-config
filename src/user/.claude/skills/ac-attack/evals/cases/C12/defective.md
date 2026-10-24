# Nightly export: retry and parking

## Problem

The nightly export job sends each batch of invoices to the ledger service. Today one failed batch aborts the whole job. The operator learns of it the next morning, from the ledger team.

## What changes

- The job sends a failing batch at most three times in all. Then it parks the batch and carries on with the next one.
- An operator who runs `export status` sees every parked batch, with the time it was parked and the error that parked it.
- The reconciler is a separate service owned by the ledger team. It reads each parked batch's record from `parked/<batch-id>.json`. That file is the interface between the two systems, and decision D3 fixes its format.
- The ledger team measures the ledger service as failing about one send in ten during normal service. At that rate, three attempts should leave at most one batch in a hundred parked.
- An operator releases a parked batch with `export release <batch-id>`. The next run sends it again.

## Decisions

- **D1 Retries.** The job sends a batch at most three times, waiting 1 second and then 5 seconds between attempts. It retries only a transport error or a 5xx response. A 4xx response parks the batch at once.
- **D2 Parking.** A parked batch does not stop the batches after it. The job exits 0 when every batch was delivered and 3 when at least one was parked.
- **D3 Record format.** A parked batch's record is one JSON object with exactly four fields: `batch_id` (string), `parked_at` (UTC, ISO 8601, to the second), `attempts` (integer) and `last_error` (string). The reconciler rejects a record with any other field.
- **D4 Status.** `export status` prints one line for each parked batch: its id, its parked time and its last error. With nothing parked it prints `no parked batches`. It exits 0 in both cases.
- **D5 Release.** `export release <batch-id>` queues the batch for the next run, which sends it again and, once it is delivered, removes its record. Naming a batch that is not parked is an error.
- **D6 Reliability target.** During normal service at least 99 batches in 100 reach the ledger without being parked. A night on which the ledger team's status page records an outage is not normal service.

## Acceptance criteria

Criteria EXP-A1 to EXP-A9 and EXP-A11 are each checked by an automated test in the job's integration suite. The suite runs the job against a stub ledger service, and each test scripts the stub's responses. The stub records the time of every send it receives. A criterion passes when its test passes in CI on the pull request's head. The CI result decides, and the pull request does not merge until each of them passes. EXP-A10 is observed in production after release, as it states. The operations lead decides it from the job's run logs, and the item stays open after merge until EXP-A10 passes.

- **EXP-A1** Given a batch whose first send fails with a dropped connection, whose second returns 503 and whose third returns 200, when the job runs, the stub records exactly three sends for that batch, the second at least 1 second after the first and the third at least 5 seconds after the second, and no record for the batch exists under `parked/`.
- **EXP-A2** Given a batch whose first send returns 422, when the job runs, the stub records exactly one send for that batch and `parked/<batch-id>.json` exists for it.
- **EXP-A3** Given three batches where every send of the second returns 503, when the job runs, the stub records exactly three sends of the second batch, records the first and the third as delivered, and `parked/<batch-id>.json` exists for the second batch only.
- **EXP-A4** Given two batches parked with the last errors `503 Service Unavailable` and `422 Unprocessable Entity`, when the operator runs `export status`, stdout holds exactly two lines, each carrying one batch's id, its parked time and its last error, and the command exits 0.
- **EXP-A5** Given a batch parked after three failed sends, `parked/<batch-id>.json` holds one JSON object with exactly the four fields D3 names, each of the type D3 gives, and `attempts` is 3. The test validates the file against the D3 schema.
- **EXP-A6** Given no parked batch, when the operator runs `export status`, stdout is `no parked batches` and the command exits 0.
- **EXP-A7** Given a parked batch, when the operator runs `export release` with its id and the job then runs with the stub returning 200, the stub records exactly one further send for that batch and no record for it remains under `parked/`.
- **EXP-A8** Given an id that names no parked batch, when the operator runs `export release` with it, the command prints `not parked: <id>` to stderr, exits 2 and leaves every file under `parked/` unchanged.
- **EXP-A9** Given a run in which every batch is delivered, the job exits 0. Given a run in which any batch is parked, whether after three sends or on a 4xx response, the job exits 3.
- **EXP-A10** After release, at least 99% of batches sent during normal service are delivered without being parked.
- **EXP-A11** Given an input directory of five batches and the stub answering 200 to every send, when the job runs, its run log for that run lists each of the five batch ids exactly once, each with the outcome `delivered`, and lists no other batch id. Given the same input with every send of the third batch answered 503, the run log lists the five ids exactly once, the third with the outcome `parked` and the rest `delivered`.

## Out of scope

- Alerting. The operator still learns of a parked batch by running `export status`.
- Any change to the ledger service or the reconciler.
