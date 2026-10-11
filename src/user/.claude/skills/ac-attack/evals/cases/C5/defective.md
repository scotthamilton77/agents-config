# Checkout: tax through the shared pricing library

## Problem

Checkout and invoicing each compute sales tax with their own copy of the same code. Last quarter the two copies drifted, and forty invoices disagreed with the receipts customers had been shown. The shared pricing library now holds the one maintained implementation, `tax_for(order)`.

## What changes

- Checkout takes the tax for every reference-corpus order from `tax_for` in the shared pricing library, as D3 states. This is a refactor, and decisions D1 and D2 state the behaviour it preserves.

## Decisions

- **D1 Preserved totals.** For each order in the reference corpus, checkout returns the same tax and total, to the cent, as the pre-change service returned for it. The reference corpus is last quarter's 5,000 accepted checkout requests, each captured with the tax and total the pre-change service returned. It spans every tax region checkout serves, tax-exempt customers and discounted orders.
- **D2 Preserved refusal.** Each reference-corpus request, with its shipping region replaced by a two-letter code that the tax tables do not hold, is still refused with HTTP 422 and the error code `unknown_tax_region`.
- **D3 One source.** For every order in the reference corpus, the tax checkout returns is exactly the value `tax_for` returns for that order.

## Acceptance criteria

Every criterion is checked by an automated test in checkout's CI suite, run on the pull request's head. A criterion passes when its test passes. The CI result decides, and the pull request does not merge until every criterion passes. TAX-A1 and TAX-A3 already hold before the change and must still hold after it. TAX-A2 starts red.

- **TAX-A1** Given the reference corpus, when each captured request is replayed against checkout built from the change, every response's tax equals the tax `tax_for` returns for the same order, and its total equals the order's subtotal plus that tax, to the cent. One differing order fails the criterion.
- **TAX-A2** Given checkout built from the change with `tax_for` replaced by a stub that returns, for each order, a tax drawn from a seeded random generator and records the value it returned, when the reference corpus is replayed, every response's tax equals the value the stub recorded for that order.
- **TAX-A3** Given each reference-corpus request with its shipping region replaced, in turn, by each two-letter code that the tax tables do not hold, when each such request is sent to checkout built from the change, every response is HTTP 422 with the error code `unknown_tax_region`.

## Out of scope

- Moving invoicing onto the shared library. Invoicing keeps its own copy until a later change.
- Any change to tax rates, rounding rules or the tax tables.
