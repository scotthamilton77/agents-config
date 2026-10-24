# Nightly sales report

## Problem

Finance reads a daily sales report each morning. Today an analyst builds it by hand from the warehouse, so it is late whenever the analyst is away.

The purpose of this change is that finance finds one complete, correct report for each past day in `reports/`, and never a partial or mixed one.

## What changes

- A new command, `sales-report build --date <YYYY-MM-DD>`, queries the warehouse for that day's orders and writes `reports/sales-<date>.csv`.
- The scheduler runs it at 02:00 UTC for the previous day. An operator can also run it by hand for any past date, for example to rebuild a day after the warehouse data was corrected.

## Decisions

- **D1 Format.** A day is a UTC calendar day. The report is a CSV file with the header `region,orders,revenue` and one row per region that had at least one order that day, sorted by region. Region names are lowercase ASCII words, so no field needs quoting. The warehouse holds order amounts in whole cents, so a region's revenue is an exact sum, printed with two decimal places.
- **D2 Whole files only.** A build replaces `reports/sales-<date>.csv` in one atomic step after its last row is written, so a reader sees the old report or the new one, never part of one.
- **D3 Rebuild.** Building a date that already has a report replaces that report with the new build.
- **D4 Read only on the warehouse.** The command only reads from the warehouse.

## Acceptance criteria

Every criterion is checked by an automated test that runs `sales-report build` against a stub warehouse whose orders, delays and failures the test scripts, with a temporary `reports/` directory, and asserts on the files in that directory, stderr and the exit status. A criterion passes when its test passes in CI on the pull request's head. The CI result decides, and the pull request does not merge until every criterion passes.

- **SLS-A1** Given the stub holding, for 2026-10-01, two orders totalling 30.00 in `north` and one order of 12.50 in `east`, when `sales-report build --date 2026-10-01` runs, `reports/sales-2026-10-01.csv` holds exactly the lines `region,orders,revenue`, `east,1,12.50` and `north,2,30.00`, and the command exits 0.
- **SLS-A2** Given the stub answering normally and writing the report failing, which the test forces by removing `reports/`, making it read-only, replacing it with a regular file, or setting a file-size limit smaller than the report, when the build for 2026-10-01 runs, every file in `reports/` is byte-identical to before, no other file appears there, stderr holds `cannot write report` and the command exits 5.
- **SLS-A3** Given a build for 2026-10-01 that ended without writing its report, because it was killed while waiting for the warehouse, killed after the stub had sent half of the rows, killed after the last row but before the report was replaced, at a point the test sets with a test-only pause hook, or exited under SLS-A2 or SLS-A7, when a new build for that date runs with the stub answering normally, it writes the report SLS-A1 describes, `reports/` holds no other new file, and it exits 0.
- A warehouse that cannot answer is a failure SLS-A7 tests.
- **SLS-A4** Given the stub holding no order for 2026-10-01, whether or not a report for that date already exists, when the build for that date runs, the report holds only the header line and the command exits 0.
- **SLS-A5** Given an invocation that does not carry exactly one `--date` and no other argument, or a date that is not valid or is today or later in UTC, when the build runs, no file in `reports/` changes, stderr holds `invalid date` and the command exits 2.
- **SLS-A6** Given the stub holding, in `north`, orders of 1.00 at 2026-09-30T23:59:59Z, 2.00 at 2026-10-01T00:00:00Z, 4.00 at 2026-10-01T23:59:59Z and 8.00 at 2026-10-02T00:00:00Z, when the build for 2026-10-01 runs, the report's only row is `north,2,6.00`.
- The command sets no limit on the number of orders or regions in a day.
- **SLS-A7** Given the stub refusing connections, failing the query after returning some rows, sending nothing for 60 seconds, or sending a row whose amount is not whole cents or whose region is not a lowercase ASCII word, when the build for 2026-10-01 runs, every file in `reports/` is byte-identical to before, no other file appears there, stderr holds `bad warehouse answer` and the command exits 3.
- A missing or unusable `reports/` is a write failure, which SLS-A2 tests.
- **SLS-A8** Given a report for 2026-10-01 already built and the stub now holding a corrected set of orders for that date, when the build for that date runs again, the report holds the rows for the corrected orders and the command exits 0.
- **SLS-A9** Given a build for 2026-10-01 in progress, held open by the stub delaying its answer by 20 seconds, a second build for the same date started meanwhile exits 4 with `build for 2026-10-01 already running` on stderr and adds no file to `reports/`, a build for 2026-09-30 started meanwhile writes its own report and exits 0, and once the first build finishes its report holds exactly the rows of the first build.
- **SLS-A10** Given a report for 2026-10-01 already built and the stub's orders for that date unchanged, when the build for that date runs again, the report is byte-identical to before and the command exits 0.

## Out of scope

- Sending the report to finance. Finance reads it from `reports/`.
- Any change to the warehouse or to the scheduler, including the scheduler retrying a failed build.
- Reports covering more than one day.
- Deleting old reports.
- Creating `reports/`. Deployment creates it before the scheduler's first run.
