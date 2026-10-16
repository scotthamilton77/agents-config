# Till: refunds without a supervisor

## Problem

A cashier who refunds a purchase needs a supervisor to turn a key on the till. At busy times the queue waits several minutes for a supervisor, for refunds that are almost all small.

## What changes

- A cashier refunds a purchase under 50 pounds alone: scan the receipt, choose the items, confirm.
- A refund of 50 pounds or more still needs the supervisor key.
- A new cashier can make a refund unaided after the standard induction, with no separate training on the flow.

## Decisions

- **D1 Limit.** A refund totalling less than 50.00 pounds needs no supervisor. A refund of 50.00 pounds or more does.
- **D2 Receipt.** A refund needs a receipt from one of our stores, dated within the last 30 days.
- **D3 Payment.** The refund goes back to the payment method the receipt records.

## Acceptance criteria

TIL-A1 to TIL-A3 are automated tests run against the till simulator in CI on the pull request's head. TIL-A4 is a human-performed measurement on the release-candidate build. The training lead runs it and records each participant's result and the build number on the pull request. The release does not ship until every criterion passes.

- **TIL-A1** Given a receipt dated today for 49.99 pounds paid by card, when the cashier scans it, selects every item and confirms, the till completes a 49.99-pound refund to that card without asking for the supervisor key.
- **TIL-A2** Given a receipt dated today for 50.00 pounds, when the cashier scans it, selects every item and confirms, the till asks for the supervisor key before completing the refund.
- **TIL-A3** Given a receipt dated 31 days ago, when the cashier scans it, the till refuses the refund with the message `Receipt older than 30 days`.
- **TIL-A4** A new cashier can complete a refund without help. The training lead confirms this in usability sessions with new cashiers.

## Out of scope

- Refunds without a receipt.
- Exchanges.
