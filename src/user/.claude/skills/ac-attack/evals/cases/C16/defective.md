# Research: an online upgrade path for the orders database

## Question

The orders database runs PostgreSQL 13 on one primary with one streaming replica, and PostgreSQL 13 leaves community support next year. Before the platform team plans the upgrade, it needs an answer to one question:

Can the orders database move to PostgreSQL 16 through built-in logical replication, with a cutover during which writes are refused for less than 60 seconds?

## Why it matters

A dump-and-restore upgrade takes the database offline for about four hours, which needs a scheduled outage and notice to every merchant. If logical replication meets the 60-second bound, the upgrade runs as a routine change in a weekday window.

## Decisions

- **D1 Answer.** The research answers yes, no or inconclusive. A yes or a no states the conditions it holds under.
- **D2 Evidence.** A claim about PostgreSQL's behaviour counts as supported when it cites the PostgreSQL documentation for the version it concerns, or the log of the rehearsal in D3. A claim resting on a blog post or on recollection does not count.
- **D3 Rehearsal.** The cutover is rehearsed once on a restored copy of last month's production backup, with the load generator replaying production's busiest hour of writes. Write unavailability is the gap between the last write PostgreSQL 13 accepts and the first write PostgreSQL 16 accepts, read from the load generator's log.
- **D4 Inconclusive.** An inconclusive answer is acceptable when it names what blocked an answer and the experiment that would settle it.

## Acceptance criteria

The criterion below is a human check. The evaluator records the verdict as a comment on the work item, naming the revision of the note judged. The item closes only on a recorded pass.

- **ORD-A1** A research note on the question exists in the platform team's research folder and is linked from the work item. It passes when the database lead opens the link and finds the note.

## Out of scope

- Performing the production upgrade.
- Upgrade paths other than logical replication, such as dump and restore or `pg_upgrade`.
