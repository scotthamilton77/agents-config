# Checkout: tax through the shared pricing library

## Problem

Checkout and invoicing each compute sales tax with their own copy of the same code. Last quarter the two copies drifted, and forty invoices disagreed with the receipts customers had been shown. The shared pricing library now holds the one maintained implementation, `tax_for(order)`.

## What changes

- Checkout's tax comes from the shared pricing library's tax tables, as D3 states. This is a refactor, and decisions D1 and D2 state the behaviour it preserves.

## Decisions

- **D1 Preserved totals.** For each order in the reference corpus, checkout returns the same tax and total, to the cent, as the pre-change service returned for it. The reference corpus is last quarter's 5,000 accepted checkout requests, each captured with the tax and total the pre-change service returned. It spans every tax region checkout serves, tax-exempt customers and discounted orders.
- **D2 Preserved refusal.** Each reference-corpus request, with its shipping region replaced by a two-letter code that the tax tables do not hold, is still refused with HTTP 422 and the error code `unknown_tax_region`.
- **D3 One source.** Checkout's tax follows the shared pricing library's tax tables. A rate changed in those tables changes the tax checkout returns for orders shipped to that region, with no change to checkout itself.

## Acceptance criteria

Every criterion is checked by an automated test in checkout's CI suite, run on the pull request's head. A criterion passes when its test passes. The CI result decides, and the pull request does not merge until every criterion passes. TAX-A1 and TAX-A3 already hold before the change and must still hold after it. TAX-A2 starts red.

- **TAX-A1** Given the reference corpus, when each captured request is replayed against checkout built from the change, every response's tax and total equal the tax and total captured beside that request, to the cent. One differing order fails the criterion.
- **TAX-A2** Given a test build of the shared pricing library whose tax tables set one region's rate to zero, when each reference-corpus order shipped to that region is replayed against checkout built from the change, every response's tax is 0.00, and when each order shipped elsewhere is replayed, its tax equals the tax captured beside that request, to the cent.
- **TAX-A3** Given each reference-corpus request with its shipping region replaced, in turn, by each two-letter code that the tax tables do not hold, when each such request is sent to checkout built from the change, every response is HTTP 422 with the error code `unknown_tax_region`.

## Out of scope

- Moving invoicing onto the shared library. Invoicing keeps its own copy until a later change.
- Any change to tax rates, rounding rules or the tax tables.
