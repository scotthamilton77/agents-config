# Invoices in the customer's currency

## Problem

The billing service issues every invoice in US dollars. Customers in the euro area pay by bank transfer in euros, so the amount that arrives differs from the invoice by their bank's conversion. Finance reconciles each short payment by hand.

## What changes

- A customer whose billing currency is EUR receives invoices in euros.
- Each invoice line converts from USD at the rate finance publishes for the invoice date.
- The invoice shows each line's converted amount, and a total that is the sum of the lines as shown.
- Invoices for customers billed in USD do not change.

## Decisions

- **D1 Rate source.** Finance publishes one USD-to-EUR rate, with four decimal places, for each UTC calendar date. A published rate never changes. The invoice date is a UTC calendar date.
- **D2 Missing rate.** When the invoice date has no published rate, the issuing run skips the invoice and logs `no rate for <date>`. The issuing run starts every hour, picks a skipped invoice up again, and issues it once the rate is published.
- **D3 Lookup is left open.** The service may read the rate table once per invoice, or keep each date's rate in memory once read. A published rate never changes, so both give the same invoices. The criteria therefore fix the rate used, not how it is fetched.

## Acceptance criteria

Every criterion is checked by an automated test in the billing service's integration suite. The suite seeds the rate table, issues invoices, and reads each issued invoice's JSON form, which holds every amount exactly as the invoice shows it. A criterion passes when its test passes in CI on the pull request's head. The CI result decides, and the pull request does not merge until every criterion passes.

- **INV-A1** Given a EUR customer, an invoice dated 2026-03-02 and a published rate of 0.9200 for that date, when the invoice is issued, a line of 100.00 USD shows as `92.00 EUR`.
- **INV-A2** Given a EUR customer and a line whose converted amount has more than two decimal places, when the invoice is issued, the line shows that amount rounded half away from zero to two decimal places: at a rate of 0.7500, a line of 13.50 USD, which converts to 10.125 EUR, shows as `10.13 EUR`.
- **INV-A3** Given a EUR customer, a rate of 0.3330 and three lines of 1.00 USD each, when the invoice is issued, each line shows `0.33 EUR` and the total shows `0.99 EUR`.
- **INV-A4** Given a EUR customer and an invoice dated 2026-03-02 with no published rate for that date, when the issuing run reaches the invoice, no invoice is issued and the run's log holds `no rate for 2026-03-02`.
- **INV-A5** Given the invoice INV-A4 skipped, when a rate of 0.9200 is then published for 2026-03-02 and the next issuing run starts, that run issues the invoice, and a line of 100.00 USD on it shows as `92.00 EUR`.
- **INV-A6** Given a USD customer, when an invoice is issued, its JSON form is byte-identical to the one the current release issues for the same customer, lines and date.

## Out of scope

- Currencies other than EUR.
- Credit notes and refunds, which stay in USD until a later change.
- How finance produces the rates.
