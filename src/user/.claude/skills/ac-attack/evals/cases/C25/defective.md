# Routing support tickets with a language model

## Problem

Every support ticket lands in one inbox, and a coordinator reads each one and moves it to one of six team queues. Tickets wait up to half a day for that step, and the coordinator spends most of the day on it.

## What changes

- The router reads each new ticket's subject and body and moves it to one of the six team queues.
- A ticket the router cannot place goes to the coordinator's manual queue, so no ticket is lost.

## Decisions

- **D1 Model.** The router asks a hosted language model to name one queue, with the prompt committed as `router/prompt.txt` and the model's default sampling. Two runs over one ticket can therefore name different queues.
- **D2 Evaluation set.** The set is 600 tickets from last quarter, each labelled with its correct queue by two coordinators who agreed on the label. It is committed as `eval/tickets-q2.jsonl` before any evaluation run. Tickets the two coordinators disagreed on are left out.
- **D3 Fallback.** A model answer that is not one of the six queue names, or no answer within 10 seconds, sends the ticket to the manual queue.

## Acceptance criteria

Each criterion is checked by an automated test. RTE-A1 runs the evaluation harness against the hosted model. The other criteria run in CI against a stub model whose answers each test scripts. A criterion passes when its test passes on the pull request's head, and the pull request does not merge until every criterion passes.

- **RTE-A1** Given the 600 tickets of D2, when the harness routes every ticket three times in three separate runs, then in each run the share of tickets landing in their labelled queue meets the threshold. The coordinators set the threshold once the three runs' results are in, at the share they judge acceptable from those results.
- **RTE-A2** Given the stub model answering `Billing`, when a ticket arrives, the ticket lands in the Billing queue within 30 seconds.
- **RTE-A3** Given the stub model answering `Refunds please`, which names no queue, when a ticket arrives, the ticket lands in the manual queue.
- **RTE-A4** Given the stub model giving no answer for 10 seconds, when a ticket arrives, the ticket lands in the manual queue.

## Out of scope

- Changing the six queues or their owners.
- Routing tickets that arrive by phone.
