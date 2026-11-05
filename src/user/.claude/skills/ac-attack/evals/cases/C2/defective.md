# Monthly statements: one month boundary in UTC

## Problem

Customers in several time zones receive a monthly statement listing their invoices. Today each regional office cuts the month at its own local midnight. An invoice issued near midnight can land in one month on the statement and in another in the ledger, and customers dispute the difference.

## What changes

- Every statement covers one calendar month in UTC.
- Every stored invoice carries its issue time with its UTC offset, such as `2026-03-31T21:30:00-04:00`.
- `statements build <YYYY-MM>` writes one statement file per customer for that month to `statements/<YYYY-MM>/<customer-id>.csv`. The billing portal reads those files.

## Decisions

- **D1 Month boundary.** An invoice belongs to the month that contains its issue time converted to UTC. A month runs from 00:00:00 UTC on its first day up to, but not including, 00:00:00 UTC on the first day of the next month.
- **D2 One home.** Each invoice appears in exactly one statement: its customer's statement for its UTC month.
- **D3 No empty statements.** A customer with no invoice in a month gets no file for that month.
- **D4 Rebuild.** Building a month again replaces that month's files and leaves every other month's files unchanged.
- **D5 Unfinished month.** Building a month that has not yet ended in UTC is refused: the command exits 2, prints `month not ended: <YYYY-MM>` to stderr and writes nothing.

## Acceptance criteria

Every criterion is checked by an automated test in the statements suite. Each test loads its fixture invoices into an empty test database, sets the test clock to 2026-05-15T12:00:00Z unless the criterion says otherwise, runs `statements build`, and reads the files it writes. A criterion passes when its test passes in CI on the pull request's head. The CI result decides, and the pull request does not merge until every criterion passes.

- **STM-A1** Given an invoice issued at 21:30 on 31 March 2026, when `statements build 2026-03` and `statements build 2026-04` run, the invoice appears in its customer's April 2026 statement and in no March 2026 statement.
- **STM-A2** Given an invoice issued at `2026-04-01T00:30:00+02:00`, which is 22:30 UTC on 31 March, when `statements build 2026-03` and `statements build 2026-04` run, the invoice appears in its customer's March 2026 statement and in no April 2026 statement.
- **STM-A3** Given invoices issued at `2026-03-31T23:59:59+00:00` and `2026-04-01T00:00:00+00:00` for one customer, when both months are built, the first appears only in the March 2026 statement and the second only in the April 2026 statement.
- **STM-A4** Given a customer with invoices in April 2026 and none in March 2026, when `statements build 2026-03` runs, no file for that customer exists under `statements/2026-03/`.
- **STM-A5** Given March 2026 already built, when an invoice issued at `2026-03-10T09:00:00+00:00` is added and `statements build 2026-03` runs again, that customer's March 2026 statement lists the new invoice as well as the invoices it listed before.
- **STM-A6** Given March and April 2026 already built, when `statements build 2026-03` runs again, every file under `statements/2026-04/` is byte-identical to its copy before the rebuild.
- **STM-A7** Given the test clock set to 2026-04-15T12:00:00Z, when `statements build 2026-04` runs, the command exits 2, prints `month not ended: 2026-04` to stderr, and no directory `statements/2026-04/` exists.

## Out of scope

- The statement file's columns, which the billing portal reads and which do not change.
- How invoices are entered. Every stored invoice already carries an offset.
- Statements for months before 2026, which were built under the old rule and are not rebuilt.
